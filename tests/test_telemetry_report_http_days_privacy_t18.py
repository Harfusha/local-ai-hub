from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request

from local_ai_hub import http_server
from local_ai_hub.app import LocalAIApp


def test_telemetry_report_invalid_days_does_not_echo_private_input(tmp_path):
    state_dir = tmp_path / "state"
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join([
            "[server]", 'bind = "127.0.0.1"', "port = 11498", f'state_dir = "{state_dir.as_posix()}"',
        ]),
        encoding="utf-8",
    )
    app = LocalAIApp(str(config_path))
    previous_app = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    private_value = "PROMPT-PRIVATE token=TOKEN-PRIVATE /private/project/config.json"
    try:
        query = urllib.parse.urlencode({"days": private_value})
        url = f"http://127.0.0.1:{server.server_address[1]}/api/telemetry/report?{query}"
        try:
            urllib.request.urlopen(url)
        except urllib.error.HTTPError as exc:
            status = exc.code
            payload = json.loads(exc.read().decode("utf-8"))
        else:
            raise AssertionError("invalid days must be rejected")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)
        http_server.APP = previous_app
        app.close()

    assert status == 400
    assert payload["error"] == "days must be an integer"
    assert payload["terminal"] is True
    assert payload["retryable"] is False
    serialized = json.dumps(payload)
    for private in ("PROMPT-PRIVATE", "TOKEN-PRIVATE", "/private/project"):
        assert private not in serialized
