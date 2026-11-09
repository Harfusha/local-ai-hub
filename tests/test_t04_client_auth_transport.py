from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

from local_ai_hub import http_server
from local_ai_hub.client import HubClient


def test_client_uses_tokenless_loopback_http_transport(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"security": {}}))

    observed: list[tuple[str, str, bool]] = []

    class AuthHandler(http_server.Handler):
        def do_POST(self):
            token_header = self.headers.get("X-LocalAI-Token", "")
            authorization = self.headers.get("Authorization", "")
            allowed = self._authorized()
            observed.append((token_header, authorization, allowed))
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
        for index in range(2):
            config = tmp_path / f"config-{index}.toml"
            config.write_text(
                f"[server]\nport={server.server_port}\nstate_dir='{(tmp_path / f'state-{index}').as_posix()}'\n"
                "[client]\nmax_request_timeout_seconds=5\n",
                encoding="utf-8",
            )
            client = HubClient(config_path=str(config), auto_start=False)
            clients.append(client)
            assert client.post("/api/memory/get", {"key": "item"}) == {"authorized": True}
        assert observed == [
            ("", "", True),
            ("", "", True),
        ]
    finally:
        for client in clients:
            client.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
