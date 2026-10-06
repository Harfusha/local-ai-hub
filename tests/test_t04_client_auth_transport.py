from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

from local_ai_hub import http_server
from local_ai_hub.client import HubClient


def test_client_token_reaches_http_authorization_boundary(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(config={"security": {"api_token": "expected-local-token"}}),
    )

    observed: list[tuple[str, bool]] = []

    class AuthHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            token = self.headers.get("X-LocalAI-Token", "")
            allowed = http_server.Handler._authorized(self)
            observed.append((token, allowed))
            body = json.dumps({"authorized": allowed}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), AuthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    clients = []
    try:
        for index, (token, expected) in enumerate(
            (("expected-local-token", True), ("wrong-token", False), (None, False))
        ):
            config = tmp_path / f"config-{index}.toml"
            token_section = f"[security]\napi_token='{token}'\n" if token else ""
            config.write_text(
                f"[server]\nport={server.server_port}\nstate_dir='{(tmp_path / f'state-{index}').as_posix()}'\n"
                "[client]\nmax_request_timeout_seconds=5\n"
                + token_section,
                encoding="utf-8",
            )
            client = HubClient(config_path=str(config), auto_start=False)
            clients.append(client)
            assert client.post("/api/memory/get", {"key": "item"}) == {"authorized": expected}
        assert observed == [
            ("expected-local-token", True),
            ("wrong-token", False),
            ("", False),
        ]
    finally:
        for client in clients:
            client.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
