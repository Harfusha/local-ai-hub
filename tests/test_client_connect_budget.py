from __future__ import annotations

import http.client
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from local_ai_hub.client import HubClient, _TransportFailure


def _client(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(
        "[server]\nstate_dir='" + (tmp_path / "state").as_posix() + "'\n"
        "[client]\nhealth_timeout_seconds=0.1\n",
        encoding="utf-8",
    )
    return HubClient(config_path=str(config), auto_start=False)


@pytest.mark.parametrize("budget", [0.01, 1.0])
def test_absent_connect_is_bounded_before_any_write(tmp_path, monkeypatch, budget):
    client = _client(tmp_path)
    connection = http.client.HTTPConnection("127.0.0.1", timeout=budget)
    seen = []

    def refuse():
        seen.append(connection.timeout)
        raise TimeoutError("connect timed out")

    connection.connect = refuse
    monkeypatch.setattr(client, "_connection", lambda _timeout: connection)
    with pytest.raises(_TransportFailure) as caught:
        client._pooled_open("POST", "/api/command", b"{}", {}, budget)
    assert 0 < seen[0] <= min(budget, client.health_timeout)
    assert connection.timeout == budget
    assert caught.value.request_not_sent is True
    assert caught.value.cancelled is False


def test_real_response_can_outlast_connect_budget(tmp_path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            time.sleep(0.2)
            body = b'{"success":true}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    client = _client(tmp_path)
    client._http_port = server.server_port
    try:
        assert client._pooled_open("GET", "/health", None, {}, 1) == b'{"success":true}'
    finally:
        client._drop_connection()
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
    assert not worker.is_alive()
