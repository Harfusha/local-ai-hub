from __future__ import annotations

from http.server import HTTPServer
import io
import socket
import threading
import time
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("clock_values,expired,consumed", [
    ([10.0], True, False),
    ([9.0, 10.0], True, True),
    ([9.0, 9.5], False, True),
])
def test_request_head_deadline_is_checked_before_and_after_each_read(monkeypatch, clock_values, expired, consumed):
    from local_ai_hub import http_transport
    clock = iter(clock_values)
    monkeypatch.setattr(http_transport.time, "monotonic", lambda: next(clock))
    timeouts = []
    raw = io.BytesIO(b"GET")
    reader = http_transport.RequestHeadReader(raw, SimpleNamespace(settimeout=timeouts.append))
    reader.deadline = 10.0
    buffer = bytearray(3)
    if expired:
        with pytest.raises(TimeoutError, match="request head deadline"):
            reader.readinto(buffer)
    else:
        assert reader.readinto(buffer) == 3
        assert buffer == b"GET"
    assert raw.tell() == (3 if consumed else 0)
    assert timeouts == ([1.0] if consumed else [])
    reader.close()


def test_request_body_without_head_deadline_does_not_change_socket_timeout():
    from local_ai_hub.http_transport import RequestHeadReader
    timeouts = []
    reader = RequestHeadReader(io.BytesIO(b"body"), SimpleNamespace(settimeout=timeouts.append))
    assert reader.readable() is True
    assert reader.readinto(bytearray(4)) == 4
    assert timeouts == []
    reader.close()


def test_slow_request_head_has_one_total_deadline(monkeypatch):
    import local_ai_hub.http_server as server_module
    served = threading.Event()
    monkeypatch.setattr(server_module, "APP", SimpleNamespace(config={"server": {
        "keepalive_timeout_seconds": 1.0, "request_timeout_seconds": 2.0,
    }}))
    class Handler(server_module.Handler):
        def do_GET(self):
            served.set()
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()
        def log_message(self, *args):
            pass
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.handle_request)
    thread.start()
    try:
        with socket.create_connection(server.server_address, timeout=3) as client:
            for byte in b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n":
                try:
                    client.sendall(bytes([byte]))
                except OSError:
                    break
                time.sleep(0.04)
        thread.join(timeout=3)
        assert not thread.is_alive()
        assert not served.is_set(), "dripping bytes must not extend the total request-head budget"
    finally:
        server.server_close()
        thread.join(timeout=3)


def test_metadata_response_reader_has_an_aggregate_byte_limit():
    from local_ai_hub.llama_cpp import _read_response_body
    class Response:
        calls = 0
        def read1(self, size):
            self.calls += 1
            return b"x" * min(size, 65536) if self.calls <= 200 else b""
    response = Response()
    with pytest.raises(ValueError, match="(byte|size|limit)"):
        _read_response_body(response, time.monotonic() + 3)
    assert response.calls <= 130


def test_plain_ollama_metadata_request_uses_bounded_body_reads(monkeypatch):
    import local_ai_hub.ollama as module
    class Response(io.BytesIO):
        def read(self, size=-1):
            assert size >= 0, "unbounded response.read()"
            return super().read(size)
    monkeypatch.setattr(module, "urlopen", lambda *args, **kwargs: Response(b'{"version":"fixture"}'))
    runtime = object.__new__(module.OllamaRuntime)
    runtime.config = {"ollama": {"enabled": True, "request_attempts": 1}}
    runtime.base_url = "http://fixture.invalid"
    runtime.timeout = 1.0
    result = runtime.request("/api/version", None)
    assert result.get("version") == "fixture", result
