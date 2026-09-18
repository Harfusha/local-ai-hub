from __future__ import annotations

import json
import threading
import urllib.request
import urllib.error
import base64
from pathlib import Path

from local_ai_hub.app import LocalAIApp
from local_ai_hub import http_server


def _post(url: str, payload: dict, *, origin: str = "chrome-extension://fixture", tenant: str = "tenant-a") -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Origin": origin,
            "X-LocalAI-Tenant": tenant,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return json.loads(error.read().decode("utf-8"))


def test_browser_capability_capture_and_review_routes_are_explicit_and_tenant_scoped(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                '[server]',
                'bind = "127.0.0.1"',
                'port = 11498',
                f'state_dir = "{state_dir.as_posix()}"',
                '[browser_bridge]',
                'enabled = true',
                'allowed_origins = ["chrome-extension://fixture"]',
                'max_payload_bytes = 200000',
            ]
        ),
        encoding="utf-8",
    )
    app = LocalAIApp(str(config_path))
    previous_app = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        capability = _post(
            f"{base}/api/browser/capability",
            {"origin": "chrome-extension://fixture", "tab_id": 7},
        )
        assert capability["success"] is True
        assert capability["one_use"] is True

        missing_tab = _post(
            f"{base}/api/browser/capability",
            {"origin": "chrome-extension://fixture"},
        )
        assert missing_tab["terminal"] is True
        assert "tab_id" in missing_tab["error"]

        unsupported = _post(
            f"{base}/api/browser/capture",
            {"capability": capability["capability"], "tab_id": 7, "capture_error": "permission_denied"},
        )
        assert unsupported["success"] is False
        assert unsupported["error_code"] == "permission_denied"

        cross_tenant = _post(
            f"{base}/api/browser/capture",
            {"capability": capability["capability"], "tab_id": 7, "capture_error": "closed_tab"},
            tenant="tenant-b",
        )
        assert cross_tenant["success"] is False
        assert cross_tenant["error_code"] in {"capability_tenant_mismatch", "capability_replayed"}

        capability = _post(
            f"{base}/api/browser/capability",
            {"origin": "chrome-extension://fixture", "tab_id": 7},
        )
        captured = _post(
            f"{base}/api/browser/capture",
            {
                "capability": capability["capability"],
                "tab_id": 7,
                "url": "https://fixture.test/checkout?session=preserved",
                "title": "Signed-in checkout",
                "screenshot": "data:image/png;base64," + base64.b64encode(b"png-fixture").decode("ascii"),
                "dom": {
                    "redaction": "none",
                    "html": '<main data-authenticated="true"><button id="pay">Pay</button></main>',
                    "elements": [{"element_id": "e0", "tag": "main"}, {"element_id": "e1", "tag": "button"}],
                },
                "accessibility": {"snapshot": [{"element_id": "e1", "role": "button", "name": "Pay"}]},
                "computed_styles": {"e1": {"display": "inline-block"}},
                "runtime": {"console_refs": [], "network_refs": [{"request_id": "resource:0", "method": "GET", "status": 200}]},
                "viewport": {"width": 1280, "height": 720, "device_scale_factor": 1},
            },
        )
        assert captured["success"] is True
        assert captured["page"]["url"] == "https://fixture.test/checkout"
        assert captured["bundle_artifact_id"]

        original_vision = app.services.vision
        app.services.vision = lambda payload, tenant: {
            "success": True,
            "bundle_artifact_id": payload.get("bundle_artifact_id"),
            "tenant": tenant,
        }
        try:
            review = _post(
                f"{base}/api/vision/review",
                {"bundle_artifact_id": captured["bundle_artifact_id"], "prompt": "Review checkout"},
            )
        finally:
            app.services.vision = original_vision
        assert review == {
            "success": True,
            "bundle_artifact_id": captured["bundle_artifact_id"],
            "tenant": "tenant-a",
        }
    finally:
        server.shutdown()
        server.server_close()
        http_server.APP = previous_app
        app.close()
