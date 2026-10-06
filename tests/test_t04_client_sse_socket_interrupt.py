from __future__ import annotations

import socket
import threading
from concurrent.futures import ThreadPoolExecutor

from local_ai_hub import client as client_module
from local_ai_hub.client import HubClient


def test_stream_deadline_shuts_down_blocked_socket_and_reports_timeout(monkeypatch):
    client = HubClient.__new__(HubClient)
    client.base_url = "http://127.0.0.1:1"
    client.api_token = ""
    client.tenant = "t04-test-tenant"
    client.agent = "t04-test-agent"
    client.max_request_timeout = 0.2

    class FakeSocket:
        def __init__(self):
            self.shutdown_mode = None
            self.interrupted = threading.Event()

        def shutdown(self, mode):
            self.shutdown_mode = mode
            self.interrupted.set()

    class FakeConnection:
        def __init__(self):
            self.closed = threading.Event()

        def close(self):
            self.closed.set()

    class FakeResponse:
        def __init__(self, stream_socket, connection):
            self.fp = type("FakeFile", (), {"raw": type("FakeRaw", (), {"_sock": stream_socket})()})()
            self._connection = connection
            self.closed = threading.Event()
            self.waiting = threading.Event()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

        def close(self):
            self.closed.set()

        def __iter__(self):
            yield b"event: update\n"
            yield b'data: {"value":1}\n'
            yield b"\n"
            self.waiting.set()
            if not self.fp.raw._sock.interrupted.wait(2):
                raise AssertionError("deadline did not interrupt the socket")
            raise OSError("socket interrupted")

    stream_socket = FakeSocket()
    connection = FakeConnection()
    response = FakeResponse(stream_socket, connection)
    monkeypatch.setattr(client_module, "urlopen", lambda *_args, **_kwargs: response)
    events = client.stream_events(timeout=0.1)

    assert next(events) == ("update", {"value": 1})
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(next, events, None)
        assert response.waiting.wait(1)
        error_event = pending.result(timeout=2)

    assert error_event[0] == "error"
    assert error_event[1]["retry_timeout"] is True
    assert stream_socket.shutdown_mode == socket.SHUT_RDWR
    assert response.closed.is_set()
    assert connection.closed.is_set()
