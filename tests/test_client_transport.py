from __future__ import annotations

import threading
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

    def pooled_open(_method, _path, _body, headers, _timeout, **_kwargs):
        nonlocal calls
        calls += 1
        request_ids.append(headers["X-LocalAI-Request-ID"])
        if calls == 1:
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
