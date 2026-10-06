from __future__ import annotations

import json
import threading
import json
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError, URLError
from io import BytesIO

from local_ai_hub import client as client_module
from local_ai_hub.client import HubClient


def _client(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(
        "[server]\nport=39123\nstate_dir='" + (tmp_path / "state").as_posix() + "'\n"
        "[client]\nmax_request_timeout_seconds=5\n",
        encoding="utf-8",
    )
    return HubClient(config_path=str(config), auto_start=False)


def test_client_get_non_object_json_uses_complete_invalid_response(tmp_path, monkeypatch):
    client = _client(tmp_path)
    monkeypatch.setattr(client, "_pooled_open", lambda *_args, **_kwargs: b"[]")

    result = client.get("/health")

    assert result["success"] is False
    assert result["error"] == "invalid JSON response"
    assert result["status_code"] == 502
    assert result["retryable"] is True
    assert result["terminal"] is False
    assert result["request_id"].startswith("req_")


def test_client_reuses_one_http11_connection_for_sequential_requests(tmp_path, monkeypatch):
    class Response:
        status = 200
        reason = "OK"
        will_close = False
        headers = {}
        def read(self): return b'{"success":true}'

    class Connection:
        instances = []
        def __init__(self, *_args, **_kwargs): self.__class__.instances.append(self)
        def request(self, *_args, **_kwargs): pass
        def getresponse(self): return Response()
        def close(self): pass

    monkeypatch.setattr(client_module.http.client, "HTTPConnection", Connection)
    client = _client(tmp_path)

    assert client.get("/health")["success"] is True
    assert client.get("/health")["success"] is True
    assert len(Connection.instances) == 1


def test_client_coalesces_simultaneous_identical_requests(tmp_path, monkeypatch):
    class Response:
        status = 200
        reason = "OK"
        will_close = False
        headers = {}
        def read(self): return b'{"success":true}'

    class Connection:
        calls = 0
        lock = threading.Lock()
        def __init__(self, *_args, **_kwargs): pass
        def request(self, *_args, **_kwargs):
            with self.lock: self.__class__.calls += 1
            time.sleep(0.05)
        def getresponse(self): return Response()
        def close(self): pass

    monkeypatch.setattr(client_module.http.client, "HTTPConnection", Connection)
    client = _client(tmp_path)
    start = threading.Barrier(2)
    results = []

    def call():
        start.wait()
        results.append(client.get("/health"))

    threads = [threading.Thread(target=call) for _ in range(2)]
    for thread in threads: thread.start()
    for thread in threads: thread.join(1)

    assert Connection.calls == 1
    assert sorted(bool(item.get("coalesced")) for item in results) == [False, True]


def test_coalesced_get_returns_server_visible_owner_request_id(tmp_path, monkeypatch):
    client = _client(tmp_path)
    owner_opened = threading.Event()
    waiter_joined = threading.Event()
    release_owner = threading.Event()
    sent_ids = []
    caller_ids = []
    original_singleflight = client._singleflight

    def pooled_open(_method, _path, _body, headers, _timeout):
        request_id = headers["X-LocalAI-Request-ID"]
        sent_ids.append(request_id)
        owner_opened.set()
        assert release_owner.wait(2)
        return json.dumps({"success": True, "request_id": request_id}).encode("utf-8")

    def observed_singleflight(key, timeout, execute, *, request_id=None, cancel_event=None):
        caller_ids.append(request_id)
        with client._flight_lock:
            is_waiter = key in client._flights
        if is_waiter:
            waiter_joined.set()
        return original_singleflight(
            key,
            timeout,
            execute,
            request_id=request_id,
            cancel_event=cancel_event,
        )

    monkeypatch.setattr(client, "_pooled_open", pooled_open)
    monkeypatch.setattr(client, "_singleflight", observed_singleflight)

    with ThreadPoolExecutor(max_workers=2) as pool:
        owner = pool.submit(client.get, "/health")
        assert owner_opened.wait(1)
        waiter = pool.submit(client.get, "/health")
        assert waiter_joined.wait(1)
        release_owner.set()
        owner_result = owner.result(timeout=1)
        waiter_result = waiter.result(timeout=1)

    assert len(sent_ids) == 1
    assert len(caller_ids) == 2 and caller_ids[0] != caller_ids[1]
    assert owner_result["request_id"] == waiter_result["request_id"] == sent_ids[0]
    assert waiter_result["coalesced"] is True


def test_get_reuses_request_id_after_autostart_retry(tmp_path, monkeypatch):
    client = _client(tmp_path)
    client.auto_start = True
    start_timeouts = []
    sent_ids = []

    def ensure_server(*, timeout):
        start_timeouts.append(timeout)
        return True

    def open_request(_method, _path, _body, headers, _timeout, **_kwargs):
        request_id = headers["X-LocalAI-Request-ID"]
        sent_ids.append(request_id)
        if len(sent_ids) == 1:
            raise URLError("connection refused")
        return json.dumps({"success": True, "request_id": request_id}).encode("utf-8")

    monkeypatch.setattr(client, "ensure_server", ensure_server)
    monkeypatch.setattr(client, "_open", open_request)

    result = client.get("/health", timeout=1)

    assert result["success"] is True
    assert len(start_timeouts) == 1 and start_timeouts[0] > 0
    assert len(sent_ids) == 2 and sent_ids[0] == sent_ids[1]
    assert result["request_id"] == sent_ids[0]


def test_coalesced_replay_safe_post_timeout_returns_owner_request_id(tmp_path, monkeypatch):
    client = _client(tmp_path)
    request_started = threading.Event()
    release_request = threading.Event()
    sent_ids = []

    def pooled_open(_method, _path, _body, headers, _timeout):
        request_id = headers["X-LocalAI-Request-ID"]
        sent_ids.append(request_id)
        request_started.set()
        assert release_request.wait(1)
        return json.dumps({"success": True, "request_id": request_id}).encode("utf-8")

    monkeypatch.setattr(client, "_pooled_open", pooled_open)
    with ThreadPoolExecutor(max_workers=1) as pool:
        owner = pool.submit(client.post, "/api/repo/complexity", {}, timeout=1)
        assert request_started.wait(1)
        try:
            waiter = client.post("/api/repo/complexity", {}, timeout=0.2)
        finally:
            release_request.set()
        owner_result = owner.result(timeout=1)

    assert owner_result["success"] is True
    assert waiter["success"] is False
    assert waiter["retry_timeout"] is True
    assert waiter["request_id"] == sent_ids[0]
    assert len(sent_ids) == 1


def test_get_passes_request_id_through_singleflight(tmp_path, monkeypatch):
    client = _client(tmp_path)
    observed_ids = []

    def pooled_open(_method, _path, _body, headers, _timeout):
        observed_ids.append(headers["X-LocalAI-Request-ID"])
        return b'{"success":true}'

    monkeypatch.setattr(client, "_pooled_open", pooled_open)

    result = client.get("/health")

    assert result["success"] is True
    assert len(observed_ids) == 1
    assert observed_ids[0].startswith("req_")


def test_singleflight_removes_completed_flight_before_signaling(tmp_path, monkeypatch):
    client = _client(tmp_path)
    native_event = threading.Event
    flight_present_at_signal = []

    class ObservedEvent:
        def __init__(self):
            self._event = native_event()

        def set(self):
            flight_present_at_signal.append("same-key" in client._flights)
            self._event.set()

        def wait(self, timeout=None):
            return self._event.wait(timeout)

    monkeypatch.setattr(client_module.threading, "Event", ObservedEvent)
    result = client._singleflight("same-key", 1, lambda: {"success": True})

    assert result["success"] is True
    assert flight_present_at_signal == [False]


def test_client_reconnects_on_idle_disconnect(tmp_path, monkeypatch):
    class Response:
        status = 200
        reason = "OK"
        will_close = False
        headers = {}
        def read(self): return b'{"success":true}'

    class FailingThenWorkingConnection:
        instances = []
        call_count = 0
        def __init__(self, *_args, **_kwargs):
            self.__class__.instances.append(self)
        def request(self, *_args, **_kwargs): pass
        def getresponse(self):
            self.__class__.call_count += 1
            if self.__class__.call_count == 1:
                raise client_module.http.client.RemoteDisconnected("Remote end closed connection")
            return Response()
        def close(self): pass

    monkeypatch.setattr(client_module.http.client, "HTTPConnection", FailingThenWorkingConnection)
    client = _client(tmp_path)
    res = client.get("/health")
    assert res["success"] is True
    assert len(FailingThenWorkingConnection.instances) == 2


def test_client_replays_duplicate_request_until_owner_finishes(tmp_path, monkeypatch):
    client = _client(tmp_path)
    calls = 0
    request_ids = []
    attempt_timeouts = []

    def pooled_open(_method, _path, _body, headers, _timeout, **_kwargs):
        nonlocal calls
        calls += 1
        request_ids.append(headers["X-LocalAI-Request-ID"])
        attempt_timeouts.append(_timeout)
        if calls == 1:
            time.sleep(0.1)
            raise HTTPError(
                "http://127.0.0.1/api/search",
                409,
                "Conflict",
                {},
                BytesIO(b'{"success":false,"retryable":true,"in_progress":true,"retry_after_seconds":0.01}'),
            )
        return b'{"success":true,"value":"owner-result"}'

    monkeypatch.setattr(client, "_pooled_open", pooled_open)
    result = client.request("/api/search", {"root": "repo"}, timeout=1)

    assert result == {"success": True, "value": "owner-result"}
    assert calls == 2
    assert len(set(request_ids)) == 1
    assert attempt_timeouts[1] < attempt_timeouts[0] - 0.05


def test_client_does_not_replay_ambiguous_default_post(tmp_path, monkeypatch):
    client = _client(tmp_path)
    calls = []

    def pooled_open(_method, _path, body, headers, _timeout):
        calls.append((body, headers["X-LocalAI-Request-ID"]))
        raise URLError("connection lost after send")

    monkeypatch.setattr(client, "_pooled_open", pooled_open)

    result = client.request("/api/command", {"command": "private payload"})

    assert len(calls) == 1
    assert result["outcome_unknown"] is True
    assert result["request_id"] == calls[0][1]
    assert "private payload" not in repr(result)


def test_client_does_not_coalesce_identical_mutating_posts(tmp_path, monkeypatch):
    client = _client(tmp_path)
    start = threading.Barrier(2)
    calls = []
    calls_lock = threading.Lock()

    def pooled_open(_method, _path, _body, headers, _timeout):
        with calls_lock:
            calls.append(headers["X-LocalAI-Request-ID"])
        return b'{"success":true}'

    monkeypatch.setattr(client, "_pooled_open", pooled_open)

    def send():
        start.wait(timeout=2)
        return client.post("/api/command", {"command": "same command"})

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: send(), range(2)))

    assert all(result["success"] for result in results)
    assert len(calls) == 2
    assert len(set(calls)) == 2


def test_client_replays_explicitly_safe_post_with_stable_request_id(tmp_path, monkeypatch):
    client = _client(tmp_path)
    request_ids = []

    def pooled_open(_method, _path, _body, headers, _timeout):
        request_ids.append(headers["X-LocalAI-Request-ID"])
        if len(request_ids) == 1:
            raise URLError("connection lost")
        return b'{"success":true}'

    monkeypatch.setattr(client, "_pooled_open", pooled_open)

    result = client.request("/api/repo/complexity", {"root": "repo"}, replay_safe=True)

    assert result["success"] is True
    assert len(request_ids) == 2
    assert len(set(request_ids)) == 1
    assert request_ids[0].startswith("req_")


def test_post_does_not_replay_unclassified_mutation(tmp_path, monkeypatch):
    client = _client(tmp_path)
    request_ids = []

    def pooled_open(_method, _path, _body, headers, _timeout):
        request_ids.append(headers["X-LocalAI-Request-ID"])
        raise URLError("connection lost after send")

    monkeypatch.setattr(client, "_pooled_open", pooled_open)

    result = client.post("/api/rag/ingest_diagram", {"image_path": "secret.png"})

    assert len(request_ids) == 1
    assert result["outcome_unknown"] is True
    assert "secret.png" not in repr(result)


def test_post_does_not_replay_file_writing_generate_types(tmp_path, monkeypatch):
    client = _client(tmp_path)
    calls = []

    def pooled_open(*_args, **_kwargs):
        calls.append(True)
        raise URLError("connection lost")

    monkeypatch.setattr(client, "_pooled_open", pooled_open)

    result = client.generate_types(root="repo", file="types.py", write_stub=True)

    assert len(calls) == 1
    assert result["outcome_unknown"] is True


def test_post_replays_allowlisted_read_only_route(tmp_path, monkeypatch):
    client = _client(tmp_path)
    request_ids = []

    def pooled_open(_method, _path, _body, headers, _timeout):
        request_ids.append(headers["X-LocalAI-Request-ID"])
        if len(request_ids) == 1:
            raise URLError("connection lost")
        return b'{"success":true}'

    monkeypatch.setattr(client, "_pooled_open", pooled_open)

    result = client.post("/api/repo/complexity", {"root": "repo"}, timeout=1)

    assert result["success"] is True
    assert len(request_ids) == 2
    assert len(set(request_ids)) == 1


def test_get_non_object_json_response_includes_request_id(tmp_path, monkeypatch):
    client = _client(tmp_path)
    request_ids = []

    def pooled_open(_method, _path, _body, headers, _timeout):
        request_ids.append(headers["X-LocalAI-Request-ID"])
        return b"[]"

    monkeypatch.setattr(client, "_pooled_open", pooled_open)

    result = client.get("/health")

    assert result == {
        "success": False,
        "error": "invalid JSON response",
        "status_code": 502,
        "request_id": request_ids[0],
        "retryable": True,
        "terminal": False,
    }


def test_post_uses_explicit_request_id_across_safe_retry(tmp_path, monkeypatch):
    client = _client(tmp_path)
    request_ids = []

    def pooled_open(_method, _path, _body, headers, _timeout):
        request_ids.append(headers["X-LocalAI-Request-ID"])
        if len(request_ids) == 1:
            raise URLError("connection lost")
        return b'{"success":true}'

    monkeypatch.setattr(client, "_pooled_open", pooled_open)

    result = client.post(
        "/api/repo/complexity",
        {"root": "repo"},
        timeout=1,
        request_id="stable-client-id",
    )

    assert result["success"] is True
    assert request_ids == ["stable-client-id", "stable-client-id"]


def test_post_rejects_malformed_request_ids_before_network(tmp_path, monkeypatch):
    client = _client(tmp_path)
    calls = []

    def pooled_open(*_args, **_kwargs):
        calls.append(True)
        return b'{"success":true}'

    monkeypatch.setattr(client, "_pooled_open", pooled_open)

    for request_id in ("", "bad request", "bad\nid", "café", "x" * 129, 123):
        result = client.post("/api/tasks/checkpoint", {}, request_id=request_id)

        assert result["success"] is False
        assert result["terminal"] is True
        assert result["retryable"] is False

    assert calls == []


def test_post_malformed_response_returns_explicit_unknown_outcome(tmp_path, monkeypatch):
    client = _client(tmp_path)
    calls = []

    def pooled_open(_method, _path, body, headers, _timeout):
        calls.append((body, headers["X-LocalAI-Request-ID"]))
        return b'{"success":true,"value":'

    monkeypatch.setattr(client, "_pooled_open", pooled_open)

    result = client.request("/api/command", {"command": "private payload"})

    assert len(calls) == 1
    assert result["outcome_unknown"] is True
    assert result["request_id"] == calls[0][1]
    assert "private payload" not in repr(result)


def test_conversation_non_object_response_is_unknown_and_not_retryable(tmp_path, monkeypatch):
    client = _client(tmp_path)
    calls = []

    def pooled_open(_method, path, _body, headers, _timeout):
        calls.append((path, headers["X-LocalAI-Request-ID"]))
        return b'["unexpected"]'

    monkeypatch.setattr(client, "_pooled_open", pooled_open)

    result = client.continue_conversation("conversation-1", "follow-up")

    assert calls[0][0] == "/api/conversations/continue"
    assert len(calls) == 1
    assert result == {
        "success": False,
        "error": "invalid JSON response",
        "status_code": 502,
        "request_id": calls[0][1],
        "outcome_unknown": True,
        "retryable": False,
        "terminal": True,
    }


def test_client_coalescing_timeout_returns_structured_result(tmp_path, monkeypatch):
    client = _client(tmp_path)
    request_started = threading.Event()
    release_request = threading.Event()

    def pooled_open(*_args, **_kwargs):
        request_started.set()
        release_request.wait(1)
        return b'{"success":true}'

    monkeypatch.setattr(client, "_pooled_open", pooled_open)
    owner_results = []
    owner = threading.Thread(
        target=lambda: owner_results.append(client.post("/api/repo/complexity", {}, timeout=1))
    )
    owner.start()
    assert request_started.wait(1)
    try:
        result = client.post("/api/repo/complexity", {}, timeout=0.2)
    finally:
        release_request.set()
        owner.join(1)

    assert not owner.is_alive()
    assert owner_results[0]["success"] is True
    assert result["success"] is False
    assert result["retry_timeout"] is True
    assert result["request_id"].startswith("req_")


def test_coord_pubsub_poll_uses_after_seq_in_json_body(tmp_path, monkeypatch):
    client = _client(tmp_path)
    captured = []
    responses = []

    def capture_open(method, path, body, _headers, _timeout):
        request_body = json.loads(body.decode("utf-8"))
        captured.append({"method": method, "path": path, "body": request_body})
        after_seq = request_body["after_seq"]
        messages = [{"seq": max(after_seq + 1, 8), "value": "update"}]
        response = {
            "success": True,
            "messages": messages,
            "after_seq": after_seq,
            "next_seq": messages[-1]["seq"],
            "last_seq": 24,
            "has_more": messages[-1]["seq"] < 24,
            "has_gap": after_seq < 7,
            "first_retained_seq": 8,
        }
        responses.append(response)
        return json.dumps(response).encode("utf-8")

    monkeypatch.setattr(client, "_terminal_preflight", lambda *_args: None)
    monkeypatch.setattr(client, "_pooled_open", capture_open)

    default_result = client.coord("pubsub_poll", root="repo", topic="updates")
    explicit_result = client.coord("pubsub_poll", root="repo", topic="updates", after_seq=17)

    assert default_result["success"] is True
    assert explicit_result["success"] is True
    assert [type(call["body"]["after_seq"]) for call in captured] == [int, int]
    assert default_result == responses[0]
    assert explicit_result == responses[1]
    assert default_result["has_gap"] is True
    assert explicit_result["has_gap"] is False
    assert default_result["next_seq"] == 8
    assert explicit_result["next_seq"] == 18
    assert captured == [
        {
            "method": "POST",
            "path": "/api/coord/pubsub_poll",
            "body": {
                "root": "repo",
                "topic": "updates",
                "after_seq": 0,
                "limit": 50,
            },
        },
        {
            "method": "POST",
            "path": "/api/coord/pubsub_poll",
            "body": {
                "root": "repo",
                "topic": "updates",
                "after_seq": 17,
                "limit": 50,
            },
        },
    ]


def test_stream_events_sends_client_identity_and_caps_timeout(tmp_path, monkeypatch):
    client = _client(tmp_path)
    client.api_token = "test-token"
    seen = {}

    class Response:
        def __enter__(self): return self
        def __exit__(self, *_args): pass
        def __iter__(self):
            return iter([b"event: update\n", b'data: {"value":1}\n', b"\n"])

    def fake_urlopen(request, timeout):
        seen["headers"] = {key.casefold(): value for key, value in request.header_items()}
        seen["timeout"] = timeout
        seen["url"] = request.full_url
        return Response()

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)

    events = list(client.stream_events(stream_id="stream-a", timeout=100))

    assert events == [("update", {"value": 1})]
    assert seen["headers"]["x-localai-tenant"] == client.tenant
    assert seen["headers"]["x-localai-agent"] == client.agent
    assert seen["headers"]["x-localai-token"] == "test-token"
    assert seen["headers"]["x-localai-request-id"].startswith("req_")
    assert seen["timeout"] <= client.max_request_timeout
    assert "timeout=5" in seen["url"]


def test_stream_events_wraps_non_object_json_in_data_dict(tmp_path, monkeypatch):
    client = _client(tmp_path)

    class Response:
        def __enter__(self): return self
        def __exit__(self, *_args): pass
        def __iter__(self):
            return iter([
                b'data: ["value"]\n', b"\n",
                b"data: 7\n", b"\n",
                b"data: true\n", b"\n",
            ])

    monkeypatch.setattr(client_module, "urlopen", lambda *_args, **_kwargs: Response())

    events = list(client.stream_events(timeout=1))

    assert events == [
        ("message", {"raw": '["value"]'}),
        ("message", {"raw": "7"}),
        ("message", {"raw": "true"}),
    ]


def test_stream_events_reports_uncertain_partial_disconnect(tmp_path, monkeypatch):
    client = _client(tmp_path)

    class Response:
        def __enter__(self): return self
        def __exit__(self, *_args): pass
        def __iter__(self):
            yield b"event: update\n"
            yield b'data: {"value":1}\n'
            yield b"\n"
            raise URLError("stream disconnected")

    monkeypatch.setattr(client_module, "urlopen", lambda *_args, **_kwargs: Response())

    events = list(client.stream_events(timeout=1))

    assert events[0] == ("update", {"value": 1})
    event_type, error = events[-1]
    assert event_type == "error"
    assert error["success"] is False
    assert error["outcome_unknown"] is True
    assert error["request_id"].startswith("req_")


def test_stream_events_cancel_event_closes_blocked_response(tmp_path, monkeypatch):
    client = _client(tmp_path)
    cancel = threading.Event()

    class Response:
        def __init__(self):
            self.closed = threading.Event()
            self.waiting = threading.Event()

        def __enter__(self): return self
        def __exit__(self, *_args): self.close()
        def close(self): self.closed.set()
        def __iter__(self):
            yield b"event: update\n"
            yield b'data: {"value":1}\n'
            yield b"\n"
            self.waiting.set()
            self.closed.wait(2)
            if self.closed.is_set():
                raise OSError("response closed")
            yield b"data: {\"value\":2}\n"

    response = Response()
    monkeypatch.setattr(client_module, "urlopen", lambda *_args, **_kwargs: response)
    events = client.stream_events(timeout=30, cancel_event=cancel)

    assert next(events) == ("update", {"value": 1})
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(next, events, None)
        assert response.waiting.wait(1)
        cancel.set()
        assert pending.result(timeout=1) is None
    assert response.closed.is_set()


def test_stream_events_enforces_deadline_while_response_is_blocked(tmp_path, monkeypatch):
    client = _client(tmp_path)
    client.max_request_timeout = 0.2

    class Response:
        def __init__(self):
            self.closed = threading.Event()
            self.waiting = threading.Event()

        def __enter__(self): return self
        def __exit__(self, *_args): self.close()
        def close(self): self.closed.set()
        def __iter__(self):
            yield b"event: update\n"
            yield b'data: {"value":1}\n'
            yield b"\n"
            self.waiting.set()
            self.closed.wait(2)
            if self.closed.is_set():
                raise OSError("response closed")

    response = Response()
    monkeypatch.setattr(client_module, "urlopen", lambda *_args, **_kwargs: response)
    events = client.stream_events(timeout=0.1)

    assert next(events) == ("update", {"value": 1})
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(next, events, None)
            assert response.waiting.wait(0.5)
            result = pending.result(timeout=1)
    finally:
        response.close()

    assert response.closed.is_set()
    assert result[0] == "error"
    assert result[1]["retry_timeout"] is True
    assert result[1]["outcome_unknown"] is True


def test_pooled_stale_connection_does_not_replay_mutating_post(tmp_path, monkeypatch):
    class Response:
        status = 200
        reason = "OK"
        will_close = False
        headers = {}

        def read(self): return b'{"success":true}'

    class Connection:
        post_calls = 0

        def __init__(self, *_args, **_kwargs): self.sock = self
        def settimeout(self, _timeout): pass
        def request(self, method, *_args, **_kwargs):
            if method == "POST":
                self.__class__.post_calls += 1
                raise client_module.http.client.RemoteDisconnected("closed after send")
        def getresponse(self): return Response()
        def close(self): pass

    monkeypatch.setattr(client_module.http.client, "HTTPConnection", Connection)
    client = _client(tmp_path)
    assert client.get("/health")["success"] is True

    result = client.request("/api/command", {"command": "private payload"})

    assert Connection.post_calls == 1
    assert result["outcome_unknown"] is True


def test_client_close_closes_connections_created_by_worker_threads(tmp_path, monkeypatch):
    class Response:
        status = 200
        reason = "OK"
        will_close = False
        headers = {}

        def read(self): return b'{"success":true}'

    class Connection:
        closed = 0

        def __init__(self, *_args, **_kwargs): pass
        def request(self, *_args, **_kwargs): pass
        def getresponse(self): return Response()
        def close(self): self.__class__.closed += 1

    monkeypatch.setattr(client_module.http.client, "HTTPConnection", Connection)
    client = _client(tmp_path)
    worker = threading.Thread(target=lambda: client.get("/health"))
    worker.start()
    worker.join(1)

    client.close()

    assert Connection.closed == 1


def test_continue_conversation_sends_task_over_real_http_and_keeps_transcript(tmp_path):
    import json
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from local_ai_hub.conversations import ConversationStore

    store = ConversationStore(idle_ttl_seconds=60, max_turns=4)
    conversation = store.start("tenant-a", {"model": "fast", "system": "system"})
    reserved, error = store.reserve(conversation.conversation_id, "tenant-a")
    assert reserved is conversation
    assert error == ""
    store.complete(
        conversation.conversation_id,
        "tenant-a",
        "USER:\nfirst question",
        "first answer",
    )

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers["Content-Length"])
            payload = json.loads(self.rfile.read(length))
            self.server.payloads.append(payload)
            conversation_id = payload.get("conversation_id", "")
            if "task" not in payload:
                response = {
                    "success": False,
                    "error": "task is required",
                    "terminal": True,
                    "retryable": False,
                }
            else:
                current, error = self.server.store.reserve(conversation_id, "tenant-a")
                if error:
                    response = {"success": False, "error": error}
                else:
                    transcript = "\n".join(
                        message["content"]
                        for message in current.messages + [{"role": "user", "content": payload["task"]}]
                    )
                    self.server.store.complete(
                        conversation_id, "tenant-a", payload["task"], "second answer"
                    )
                    response = {
                        "success": True,
                        "conversation_id": conversation_id,
                        "text": "second answer",
                        "transcript": transcript,
                    }

            body = json.dumps(response).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.store = store
    server.payloads = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config = tmp_path / "conversation-client.toml"
    config.write_text(
        f"[server]\nport={server.server_port}\nstate_dir='{(tmp_path / 'state').as_posix()}'\n"
        "[client]\nmax_request_timeout_seconds=5\n",
        encoding="utf-8",
    )
    client = HubClient(config_path=str(config), auto_start=False)
    try:
        result = client.continue_conversation(conversation.conversation_id, "second question")
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)

    assert result["success"] is True
    assert result["conversation_id"] == conversation.conversation_id
    assert "first question" in result["transcript"]
    assert "first answer" in result["transcript"]
    assert "second question" in result["transcript"]
    assert server.payloads[0]["task"] == "second question"
    assert "prompt" not in server.payloads[0]
