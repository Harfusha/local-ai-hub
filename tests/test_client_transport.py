from __future__ import annotations

import errno
import http.client
import json
import sys
import threading
import time
import types
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError, URLError
from io import BytesIO
import pytest

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


def test_auto_start_timeout_terminates_and_reaps_only_its_child(tmp_path, monkeypatch):
    client = _client(tmp_path)
    client.startup_wait = 0.05
    client.startup_poll = 0.01
    launched = []
    terminated = []

    class Child:
        pid = 43210
        returncode = None

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self.returncode = -15
            return self.returncode

    child = Child()
    monkeypatch.setattr(client, "_online", lambda _timeout=None: False)
    monkeypatch.setattr(client_module, "find_listening_pid", lambda _port: None)
    monkeypatch.setattr(client_module.subprocess, "Popen", lambda *_args, **_kwargs: launched.append(child) or child)
    monkeypatch.setattr(client_module, "_retain_detached_child", lambda _process: None)
    monkeypatch.setattr(
        client_module,
        "terminate_tree",
        lambda pid, **_kwargs: terminated.append(pid) or True,
        raising=False,
    )

    assert client.ensure_server(timeout=0.05) is False
    assert launched == [child]
    assert terminated == [child.pid]
    assert child.returncode is not None


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


def test_client_coord_memo_put_forwards_expected_version(tmp_path, monkeypatch):
    client = _client(tmp_path)
    calls = []

    def capture_post(endpoint, payload, **kwargs):
        calls.append((endpoint, payload))
        return {"success": True}

    monkeypatch.setattr(client, "post", capture_post)
    result = client.coord(
        "memo_put", root="repo", key="decision", value="accepted", expected_version=4
    )

    assert result["success"] is True
    assert calls == [(
        "/api/memory/put",
        {"root": "repo", "key": "decision", "value": "accepted", "ttl_seconds": 604800, "expected_version": 4},
    )]


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
    result = client.post("/api/search", {"root": "repo"}, timeout=1)

    assert result == {"success": True, "value": "owner-result"}
    assert calls == 2
    assert len(set(request_ids)) == 1
    assert attempt_timeouts[1] < attempt_timeouts[0] - 0.05


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


def test_transport_connection_refusal_marks_request_not_sent(tmp_path, monkeypatch):
    client = _client(tmp_path)
    connection = http.client.HTTPConnection("127.0.0.1", 1)
    connection_calls = []
    connect_calls = []

    def refuse_connection():
        connect_calls.append(True)
        raise ConnectionRefusedError(errno.ECONNREFUSED, "connection refused")

    connection.connect = refuse_connection
    def get_connection(_timeout):
        connection_calls.append(True)
        return connection

    monkeypatch.setattr(client, "_connection", get_connection)

    result = client.post("/api/command", {"command": "echo safe"}, request_id="stable-refused-id")

    assert connection_calls == [True]
    assert connect_calls == [True]
    assert result == {
        "success": False,
        "error": "request was not sent because transport failed before write",
        "request_not_sent": True,
        "outcome_unknown": False,
        "request_id": "stable-refused-id",
        "terminal": True,
        "retryable": False,
    }


def test_transport_other_connect_failure_is_classified_as_request_not_sent(tmp_path, monkeypatch):
    client = _client(tmp_path)
    connection = http.client.HTTPConnection("127.0.0.1", 1)
    connect_calls = []

    def timeout_connection():
        connect_calls.append(True)
        raise TimeoutError("connect timed out")

    connection.connect = timeout_connection
    monkeypatch.setattr(client, "_connection", lambda _timeout: connection)

    result = client.request("/api/command", {"command": "echo safe"}, request_id="stable-timeout-id")

    assert connect_calls == [True]
    assert result["request_not_sent"] is True
    assert result["outcome_unknown"] is False
    assert result["request_id"] == "stable-timeout-id"


def test_transport_write_failure_marks_outcome_unknown(tmp_path, monkeypatch):
    client = _client(tmp_path)
    connection = http.client.HTTPConnection("127.0.0.1", 1)
    connection_calls = []

    class BrokenSocket:
        def __init__(self):
            self.send_calls = 0

        def sendall(self, _data):
            self.send_calls += 1
            raise ConnectionResetError("connection reset during write")

        def close(self):
            pass

    sock = BrokenSocket()

    def connect_with_socket():
        connection.sock = sock

    connection.connect = connect_with_socket
    def get_connection(_timeout):
        connection_calls.append(True)
        return connection

    monkeypatch.setattr(client, "_connection", get_connection)

    result = client.post("/api/command", {"command": "echo safe"}, request_id="stable-write-id")

    assert connection_calls == [True]
    assert sock.send_calls == 1
    assert result == {
        "success": False,
        "error": "request outcome is unknown after a transport failure",
        "outcome_unknown": True,
        "request_id": "stable-write-id",
        "terminal": True,
        "retryable": False,
    }


def test_safe_posts_with_distinct_explicit_request_ids_do_not_coalesce(tmp_path, monkeypatch):
    client = _client(tmp_path)
    first_started = threading.Event()
    second_started = threading.Event()
    release = threading.Event()
    request_ids = []

    def pooled_open(_method, _path, _body, headers, _timeout):
        request_id = headers["X-LocalAI-Request-ID"]
        request_ids.append(request_id)
        (first_started if request_id == "explicit-one" else second_started).set()
        release.wait(2)
        return b'{"success":true}'

    monkeypatch.setattr(client, "_pooled_open", pooled_open)

    def send(request_id):
        return client.request(
            "/api/repo/complexity",
            {"root": "repo"},
            timeout=1,
            replay_safe=True,
            request_id=request_id,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(send, "explicit-one")
        assert first_started.wait(1)
        second = pool.submit(send, "explicit-two")
        try:
            assert second_started.wait(1)
        finally:
            release.set()
        assert first.result(timeout=1)["success"] is True
        assert second.result(timeout=1)["success"] is True

    assert sorted(request_ids) == ["explicit-one", "explicit-two"]


def test_ensure_server_mode_load_failure_blocks_autostart(tmp_path, monkeypatch):
    client = _client(tmp_path)
    state_dir = client.config["server"]["state_dir"]
    starts = []
    mode_module = types.ModuleType("local_ai_hub.operational_mode")

    def fail_mode_load(_state_dir):
        raise OSError("mode state unavailable")

    mode_module.load_operational_mode = fail_mode_load
    monkeypatch.setitem(sys.modules, mode_module.__name__, mode_module)
    monkeypatch.setattr(client, "_online", lambda *_args: False)
    monkeypatch.setattr(client_module.subprocess, "Popen", lambda *_a, **_k: starts.append(True))

    assert client.ensure_server(timeout=1) is False
    assert starts == []
    assert not client_module.Path(state_dir).exists()
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
    del client.max_request_timeout
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


def test_async_job_replay_policy_requires_id_for_submit_and_allows_controls() -> None:
    replay_safe = HubClient._post_replay_safe

    for action in ("status", "wait", "result", "cancel"):
        assert replay_safe("/api/async-jobs", {"action": action, "job_id": "job-1"}) is True
    assert replay_safe(
        "/api/async-jobs", {"action": "submit", "request_id": "stable-submit"}
    ) is True
    assert replay_safe("/api/async-jobs", {"action": "submit"}) is False


def test_async_job_client_methods_keep_submit_identity_and_cover_wait_deadline(tmp_path, monkeypatch):
    client = _client(tmp_path)
    client.max_request_timeout = 100
    calls = []

    def fake_post(path, payload, timeout=360.0):
        calls.append((path, dict(payload), timeout))
        return {"success": True, "job_id": payload.get("job_id", "job-new")}

    monkeypatch.setattr(client, "post", fake_post)

    client.submit_async_job("reason", {"task": "summarize"}, request_id="stable-1", timeout=12)
    client.async_job_status("job-1")
    client.wait_async_job("job-1", timeout_seconds=40)
    client.async_job_result("job-1")
    client.cancel_async_job("job-1")

    assert calls[0] == (
        "/api/async-jobs",
        {"task": "summarize", "action": "submit", "job_action": "reason", "request_id": "stable-1"},
        12,
    )
    assert calls[1][1] == {"action": "status", "job_id": "job-1"}
    assert calls[2][1] == {"action": "wait", "job_id": "job-1", "timeout_seconds": 40}
    assert calls[2][2] == 70
    assert calls[3][1] == {"action": "result", "job_id": "job-1"}
    assert calls[4][1] == {"action": "cancel", "job_id": "job-1"}
    assert HubClient._post_replay_safe(
        "/api/async-jobs", {"action": "submit", "request_id": "stable-1"}
    ) is True
    assert HubClient._post_replay_safe(
        "/api/async-jobs", {"action": "submit"}
    ) is False


def test_continue_conversation_sends_only_supported_fields(tmp_path, monkeypatch):
    client = _client(tmp_path)
    calls = []

    def fake_post(path, payload, timeout=360.0):
        calls.append((path, dict(payload), timeout))
        return {"success": True, "conversation_id": payload["conversation_id"]}

    monkeypatch.setattr(client, "post", fake_post)

    result = client.continue_conversation(
        "conversation-1", "follow up", context="relevant context", timeout=12
    )

    assert result == {"success": True, "conversation_id": "conversation-1"}
    assert calls == [(
        "/api/conversations/continue",
        {"conversation_id": "conversation-1", "task": "follow up", "context": "relevant context"},
        12,
    )]


def test_async_job_submit_replays_after_transport_disconnect_with_stable_identity(tmp_path, monkeypatch):
    client = _client(tmp_path)
    calls = []

    def pooled_open(method, path, body, headers, _timeout):
        calls.append({
            "method": method,
            "path": path,
            "body": json.loads(body.decode("utf-8")),
            "request_id": headers["X-LocalAI-Request-ID"],
        })
        if len(calls) == 1:
            raise URLError("connection dropped after submit")
        return b'{"success":true,"job_id":"job-1"}'

    monkeypatch.setattr(client, "_pooled_open", pooled_open)

    result = client.submit_async_job(
        "reason", {"task": "resume safely"}, request_id="stable-submit", timeout=2
    )

    assert result["success"] is True
    assert result["job_id"] == "job-1"
    assert len(calls) == 2
    assert calls[0] == calls[1]
    assert calls[0]["method"] == "POST"
    assert calls[0]["path"] == "/api/async-jobs"
    assert calls[0]["body"] == {
        "task": "resume safely",
        "action": "submit",
        "job_action": "reason",
        "request_id": "stable-submit",
    }
    assert calls[0]["request_id"].startswith("req_")
