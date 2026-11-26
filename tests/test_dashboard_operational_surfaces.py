def test_native_desktop_discloses_trace_access_and_retention_policy():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "desktop/src/main.rs").read_text(encoding="utf-8")
    assert "Full inputs and outputs are captured only when detailed telemetry is enabled" in source
    assert "Stored details appear as recorded" in source
    assert "local access only" in source
    assert "separate local retention policy" in source


def test_retired_dashboard_route_returns_json_not_found(monkeypatch) -> None:
    import json
    import threading
    import urllib.error
    import urllib.request
    from types import SimpleNamespace
    from local_ai_hub import http_server
    import pytest

    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={
        "monitoring": {"dashboard_enabled": True},
        "features": {"dashboard": True},
    }))
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for path in ("/", "/dashboard", "/dashboard/", "/favicon.ico"):
            with pytest.raises(urllib.error.HTTPError) as rejected:
                urllib.request.urlopen(f"http://127.0.0.1:{server.server_address[1]}{path}", timeout=3)
            assert rejected.value.code == 404
            assert rejected.value.headers.get_content_type() == "application/json"
            assert json.loads(rejected.value.read())["success"] is False
            rejected.value.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
