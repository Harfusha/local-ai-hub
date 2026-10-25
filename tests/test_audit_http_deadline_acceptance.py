"""Wire-level deadline regressions for the Hub handler and metadata clients."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
import json
import socket
import threading
import time
import urllib.request

import pytest


def _serve(server):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


def _stop_server(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)
    assert not thread.is_alive(), "local HTTP test server did not stop"


def test_unknown_post_rejects_without_waiting_for_an_unaccepted_body(monkeypatch):
    import local_ai_hub.http_server as server_module

    monkeypatch.setattr(server_module, "APP", None)

    class Handler(server_module.Handler):
        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = _serve(server)
    try:
        with socket.create_connection(server.server_address, timeout=3) as client:
            client.settimeout(1)
            # A rejected route has no reason to wait for this advertised body.
            # Withholding it must not retain a handler for the body-read deadline.
            client.sendall(
                b"POST /api/unknown-post-contract HTTP/1.1\r\n"
                b"Host: localhost\r\nContent-Length: 1024\r\n"
                b"Connection: close\r\n\r\n"
            )
            response = client.recv(4096)
            assert response.startswith(b"HTTP/1.1 404 "), response
    finally:
        _stop_server(server, thread)


def test_real_handler_times_out_trickled_head_then_accepts_token_authenticated_request(monkeypatch):
    import local_ai_hub.http_server as server_module

    token = "wire-test-token-123456789"
    monkeypatch.setattr(
        server_module,
        "APP",
        type("AppStub", (), {
            "config": {
                "server": {"keepalive_timeout_seconds": 1.0, "request_timeout_seconds": 1.0},
                "security": {"api_token": token, "api_token_permissions": ["read"]},
                "_config_path": "",
                "_runtime_override_path": "",
            }
        })(),
    )
    served = []

    class Handler(server_module.Handler):
        def do_GET(self):
            served.append(self.path)
            super().do_GET()

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = _serve(server)
    sender_done = threading.Event()
    start = time.monotonic()
    try:
        with socket.create_connection(server.server_address, timeout=3) as client:
            client.settimeout(3)

            def drip_incomplete_head():
                raw = b"GET /api/config HTTP/1.1\r\nHost: localhost\r\nX-Incomplete: " + b"x" * 80
                try:
                    for byte in raw:
                        if sender_done.wait(0.08):
                            break
                        client.sendall(bytes((byte,)))
                except OSError:
                    pass

            sender = threading.Thread(target=drip_incomplete_head, daemon=True)
            sender.start()
            assert client.recv(1) == b"", "incomplete trickled request head was not closed"
            elapsed = time.monotonic() - start
            sender_done.set()
            sender.join(timeout=2)
            assert not sender.is_alive()
            assert 0.7 <= elapsed < 2.5, f"request-head timeout outside its bound: {elapsed:.3f}s"
            assert served == [], "an incomplete request must not reach the application handler"

        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/api/config",
            headers={"X-LocalAI-Token": token},
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
            assert response.status == 200
        assert payload["success"] is True
        assert served == ["/api/config"]
    finally:
        sender_done.set()
        _stop_server(server, thread)


@pytest.mark.parametrize("send_content_length", [True, False], ids=["content-length", "close-delimited"])
def test_real_urllib_body_exceeding_metadata_cap_is_rejected(send_content_length):
    from local_ai_hub.llama_cpp import _read_response_body

    body = b"m" * 256

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            self.send_response(200)
            if send_content_length:
                self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
            self.close_connection = True

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = _serve(server)
    response = None
    try:
        response = urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/", timeout=3)
        with pytest.raises(ValueError, match="(byte|size|limit)"):
            _read_response_body(response, time.monotonic() + 2.0, max_bytes=32)
    finally:
        if response is not None:
            response.close()
        _stop_server(server, thread)


def test_endless_chunked_metadata_response_stops_when_bounded_reader_closes():
    from local_ai_hub.llama_cpp import _read_response_body

    disconnected = threading.Event()
    producer_stop = threading.Event()
    producer_finished = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            self.send_response(200)
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            chunk = b"z" * 4096
            try:
                while not producer_stop.wait(0.004):
                    self.wfile.write(f"{len(chunk):X}\r\n".encode("ascii"))
                    self.wfile.write(chunk + b"\r\n")
                    self.wfile.flush()
            except OSError:
                disconnected.set()
            finally:
                self.close_connection = True
                producer_finished.set()

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = _serve(server)
    response = None
    try:
        response = urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/", timeout=3)
        with pytest.raises(ValueError, match="(byte|size|limit)"):
            _read_response_body(response, time.monotonic() + 2.0, max_bytes=128)
        response.close()
        assert disconnected.wait(2), "chunked producer did not observe the bounded reader closing"
    finally:
        producer_stop.set()
        if response is not None:
            response.close()
        assert producer_finished.wait(2), "chunked producer handler did not stop during cleanup"
        _stop_server(server, thread)


def test_ollama_tags_success_body_trickle_keeps_one_total_deadline():
    from local_ai_hub.ollama import OllamaRuntime

    producer_disconnected = threading.Event()
    producer_stop = threading.Event()
    producer_finished = threading.Event()
    body = b'{"models":[{"name":"fixture"}]}'

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                for byte in body:
                    if producer_stop.wait(0.08):
                        break
                    self.wfile.write(bytes((byte,)))
                    self.wfile.flush()
            except OSError:
                producer_disconnected.set()
            finally:
                self.close_connection = True
                producer_finished.set()

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = _serve(server)
    runtime = object.__new__(OllamaRuntime)
    runtime.config = {"ollama": {"enabled": True, "request_attempts": 1, "retry_delay_seconds": 0}}
    runtime.base_url = f"http://127.0.0.1:{server.server_port}"
    runtime.timeout = 3.0
    start = time.monotonic()
    try:
        result = runtime.request("/api/tags", timeout=0.45)
        elapsed = time.monotonic() - start
        assert "timed out" in str(result.get("error", "")).lower(), result
        assert 0.25 <= elapsed < 1.5, f"successful-body trickle exceeded one total deadline: {elapsed:.3f}s"
        assert producer_disconnected.wait(2), "backend did not observe the timed-out client closing"
    finally:
        producer_stop.set()
        _stop_server(server, thread)
        assert producer_finished.wait(2), "trickling backend handler did not stop during cleanup"
