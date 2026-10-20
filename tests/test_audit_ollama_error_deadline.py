from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import time

import pytest


@pytest.mark.parametrize("interruptible", [False, True])
def test_ollama_error_body_respects_total_metadata_deadline(interruptible):
    from local_ai_hub.ollama import OllamaRuntime
    stop = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(503)
            self.send_header("Content-Length", "80")
            self.end_headers()
            for _ in range(80):
                if stop.wait(0.03):
                    break
                try:
                    self.wfile.write(b"x")
                    self.wfile.flush()
                except OSError:
                    break

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.handle_request, daemon=True)
    worker.start()
    runtime = object.__new__(OllamaRuntime)
    runtime.config = {"ollama": {"enabled": True, "request_attempts": 1}}
    runtime.base_url = "http://127.0.0.1:" + str(server.server_port)
    runtime.timeout = 0.18
    started = time.monotonic()
    try:
        kwargs = {"should_stop": lambda: False} if interruptible else {}
        result = runtime.request("/api/tags", None, **kwargs)
        elapsed = time.monotonic() - started
        assert elapsed < 1.0, "error bytes renewed an idle timeout instead of honoring total deadline"
        assert result.get("timed_out") is True, result
    finally:
        stop.set()
        worker.join(timeout=2)
        server.server_close()
        assert not worker.is_alive()
