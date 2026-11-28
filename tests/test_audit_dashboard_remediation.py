from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest


@pytest.fixture
def dashboard_server(tmp_path, monkeypatch):
    from local_ai_hub.app import LocalAIApp
    import local_ai_hub.http_server as module
    config = tmp_path / "config.toml"
    config.write_text('[local_ai_hub]\nconfig_schema_version=1\n[server]\nstate_dir=' + json.dumps(str(tmp_path / "state")) +
        '\n[security]\nallowed_roots=[' + json.dumps(str(tmp_path)) +
        ']\n[hardware]\nprofile="cpu"\n[prewarm]\nenabled=false\n[headless]\nmanage_ollama=false\n', encoding="utf-8")
    app = LocalAIApp(str(config))
    monkeypatch.setattr(module, "APP", app)
    server = module.LocalAIHTTPServer(("127.0.0.1", 0), module.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}", config
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)
    app.close()


@pytest.mark.parametrize("value", [0, 1, [], {}])
def test_dashboard_telemetry_mode_rejects_non_enum_values(dashboard_server, value):
    endpoint, config = dashboard_server
    request = urllib.request.Request(endpoint + "/api/config/update", method="POST",
        data=json.dumps({"settings": {"telemetry.mode": value}}).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        with exc:
            status = exc.code
    except (OSError, __import__("http.client").client.HTTPException):
        status = 0
    assert status == 400
    assert not config.with_name("config.runtime.toml").exists()

