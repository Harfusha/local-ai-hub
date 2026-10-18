from __future__ import annotations

import json
import threading
import time
import urllib.request
import urllib.error
import base64
from pathlib import Path
from types import SimpleNamespace

from local_ai_hub.app import LocalAIApp
from local_ai_hub import http_server


def _post(url: str, payload: dict, *, origin: str = "chrome-extension://fixture", token: str | None = "test-api-token", request_id: str | None = None, extra_headers: dict[str, str] | None = None) -> dict:
    headers = {
        "Content-Type": "application/json",
        "Origin": origin,
    }
    headers.update(extra_headers or {})
    if token:
        headers["X-LocalAI-Token"] = token
    if request_id:
        headers["X-LocalAI-Request-ID"] = request_id
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return json.loads(error.read().decode("utf-8"))


def test_browser_capability_capture_and_review_routes_are_explicit_and_origin_scoped(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                '[server]',
                'bind = "127.0.0.1"',
                'port = 11498',
                f'state_dir = "{state_dir.as_posix()}"',
                '[security]',
                'api_token = "test-api-token"',
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
            {"origin": "chrome-extension://fixture", "tab_id": 7, "window_id": 3},
        )
        assert capability["success"] is True
        assert capability["one_use"] is True

        missing_tab = _post(
            f"{base}/api/browser/capability",
            {"origin": "chrome-extension://fixture"},
        )
        assert missing_tab["terminal"] is True
        assert "tab_id" in missing_tab["error"]

        missing_window = _post(
            f"{base}/api/browser/capability",
            {"origin": "chrome-extension://fixture", "tab_id": 7},
        )
        assert missing_window["terminal"] is True
        assert "window_id" in missing_window["error"]

        unsupported = _post(
            f"{base}/api/browser/capture",
            {"capability": capability["capability"], "tab_id": 7, "window_id": 3, "capture_error": "permission_denied"},
        )
        assert unsupported["success"] is False
        assert unsupported["error_code"] == "permission_denied"

        retired_header = _post(
            f"{base}/api/browser/capability",
            {"origin": "chrome-extension://fixture", "tab_id": 8, "window_id": 3},
            extra_headers={"X-LocalAI-Tenant": "retired"},
        )
        assert retired_header["error_code"] == "retired_tenant_header"

        capability = _post(
            f"{base}/api/browser/capability",
            {"origin": "chrome-extension://fixture", "tab_id": 7, "window_id": 3},
        )
        captured = _post(
            f"{base}/api/browser/capture",
            {
                "capability": capability["capability"],
                "tab_id": 7,
                "window_id": 3,
                "url": "https://fixture.test/checkout?session=preserved",
                "target_origin": "https://fixture.test",
                "captured_at": "2026-09-18T10:20:30.123Z",
                "capture_identity": {
                    "initial": {
                        "url": "https://fixture.test/checkout?session=preserved",
                        "target_origin": "https://fixture.test",
                        "document_token": "document:fixture:1",
                        "document_state_token": "state:fixture:1",
                    },
                    "final": {
                        "url": "https://fixture.test/checkout?session=preserved",
                        "target_origin": "https://fixture.test",
                        "document_token": "document:fixture:1",
                        "document_state_token": "state:fixture:1",
                    },
                },
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

        artifacts_before_bad_provenance = {
            item["artifact_id"] for item in app.artifacts.list(limit=100)
        }
        malformed_capability = _post(
            f"{base}/api/browser/capability",
            {"origin": "chrome-extension://fixture", "tab_id": 7, "window_id": 3},
        )
        malformed_capture = _post(
            f"{base}/api/browser/capture",
            {
                "capability": malformed_capability["capability"],
                "tab_id": 7,
                "window_id": 3,
                "url": "https://fixture.test/checkout",
                "target_origin": "https://spoofed.test",
                "captured_at": "2026-09-18T10:20:30.123Z",
                "capture_identity": {
                    "initial": {
                        "url": "https://fixture.test/checkout",
                        "target_origin": "https://fixture.test",
                        "document_token": "document:fixture:2",
                        "document_state_token": "state:fixture:2",
                    },
                    "final": {
                        "url": "https://fixture.test/checkout",
                        "target_origin": "https://fixture.test",
                        "document_token": "document:fixture:2",
                        "document_state_token": "state:fixture:2",
                    },
                },
                "screenshot": "data:image/png;base64," + base64.b64encode(b"png-fixture").decode("ascii"),
                "dom": {"redaction": "none", "html": "<main />", "elements": []},
            },
        )
        assert malformed_capture["success"] is False
        assert malformed_capture["error_code"] == "target_origin_mismatch"
        assert {item["artifact_id"] for item in app.artifacts.list(limit=100)} == artifacts_before_bad_provenance

        original_vision = app.services.vision
        app.services.vision = lambda payload: {
            "success": True,
            "bundle_artifact_id": payload.get("bundle_artifact_id"),
        }
        try:
            review = _post(
                f"{base}/api/vision/review",
                {"bundle_artifact_id": captured["bundle_artifact_id"], "prompt": "Review checkout"},
                request_id="t17-vision-review-route",
            )
        finally:
            app.services.vision = original_vision
        assert review == {
            "success": True,
            "bundle_artifact_id": captured["bundle_artifact_id"],
            "request_id": "t17-vision-review-route",
        }
    finally:
        server.shutdown()
        server.server_close()
        http_server.APP = previous_app
        app.close()


def test_browser_stage_commit_and_abandon_http_lifecycle(tmp_path: Path, monkeypatch) -> None:
    state_dir = tmp_path / "state"
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                '[server]',
                'bind = "127.0.0.1"',
                'port = 11499',
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
    app.config["browser_bridge"]["capability_ttl_seconds"] = 1
    from local_ai_hub import browser_bridge

    # Logical operations occur before expiry regardless of HTTP/disk scheduling.
    # Patch only this module's clock, not the shared time module or server timers.
    capture_clock = [time.monotonic()]
    monkeypatch.setattr(browser_bridge, "time", SimpleNamespace(monotonic=lambda: capture_clock[0]))
    previous_app = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        origin = "chrome-extension://fixture"
        capability = _post(
            f"{base}/api/browser/capability",
            {"origin": origin, "tab_id": 7, "window_id": 3},
        )["capability"]
        payload = {
            "capability": capability,
            "origin": origin,
            "tab_id": 7,
            "window_id": 3,
            "request_id": "http-staged-commit",
            "url": "https://fixture.test/checkout",
            "target_origin": "https://fixture.test",
            "capture_identity": {
                "initial": {
                    "url": "https://fixture.test/checkout",
                    "target_origin": "https://fixture.test",
                    "document_token": "document:http:1",
                    "document_state_token": "state:http:1",
                },
                "final": {
                    "url": "https://fixture.test/checkout",
                    "target_origin": "https://fixture.test",
                    "document_token": "document:http:1",
                    "document_state_token": "state:http:1",
                },
            },
            "screenshot": "data:image/png;base64," + base64.b64encode(b"png-fixture").decode("ascii"),
            "dom": {"redaction": "none", "html": "<main />", "elements": [{"element_id": "e0", "tag": "main"}]},
        }
        staged = _post(f"{base}/api/browser/capture/stage", payload)
        assert staged["success"] is True
        assert staged["staged"] is True
        assert "bundle_artifact_id" not in staged

        request = {key: payload[key] for key in ("capability", "origin", "tab_id", "window_id", "request_id")}
        committed = _post(f"{base}/api/browser/capture/commit", request)
        artifacts_after_commit = app.artifacts.list(limit=100)
        replay = _post(f"{base}/api/browser/capture/commit", request)
        assert committed["success"] is True
        assert committed["bundle_artifact_id"]
        assert replay == committed
        assert committed["bundle_artifact_id"] in {item["artifact_id"] for item in artifacts_after_commit}
        stored_bundle = app.artifacts.get(committed["bundle_artifact_id"])
        assert stored_bundle["success"] is True
        assert app.artifacts.list(limit=100) == artifacts_after_commit

        abandoned_capability = _post(
            f"{base}/api/browser/capability",
            {"origin": origin, "tab_id": 7, "window_id": 3},
        )["capability"]
        abandoned_payload = {**payload, "capability": abandoned_capability, "request_id": "http-staged-abandon"}
        abandoned_stage = _post(f"{base}/api/browser/capture/stage", abandoned_payload)
        assert abandoned_stage["success"] is True, abandoned_stage
        abandoned_request = {**request, "capability": abandoned_capability, "request_id": "http-staged-abandon"}
        abandoned = _post(f"{base}/api/browser/capture/abandon", abandoned_request)
        late_commit = _post(f"{base}/api/browser/capture/commit", abandoned_request)
        assert abandoned["success"] is True
        assert abandoned["abandoned"] is True
        assert late_commit == abandoned

        expired_capability = _post(
            f"{base}/api/browser/capability",
            {"origin": origin, "tab_id": 7, "window_id": 3},
        )["capability"]
        expired_payload = {**payload, "capability": expired_capability, "request_id": "http-staged-expiry"}
        expired_stage = _post(f"{base}/api/browser/capture/stage", expired_payload)
        assert expired_stage["success"] is True
        expired_request = {**request, "capability": expired_capability, "request_id": "http-staged-expiry"}
        capture_clock[0] += 1.1
        expired_commit = _post(f"{base}/api/browser/capture/commit", expired_request)
        expired_replay = _post(f"{base}/api/browser/capture/commit", expired_request)
        assert expired_commit["success"] is False, {
            "commit": expired_commit,
            "stage": expired_stage,
            "browser_bridge_config": app.config.get("browser_bridge"),
        }
        assert expired_commit["error_code"] == "capture_expired"
        assert expired_replay == expired_commit
        assert app.artifacts.list(limit=100) == artifacts_after_commit
    finally:
        server.shutdown()
        server.server_close()
        http_server.APP = previous_app
        app.close()


def test_token_auth_supports_bridge_and_review_preflight_without_wildcard_origin(tmp_path: Path) -> None:
    token = "0123456789abcdef"
    state_dir = tmp_path / "state"
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join([
            "[server]", 'bind = "127.0.0.1"', "port = 11499", f'state_dir = "{state_dir.as_posix()}"',
            "[security]", f'api_token = "{token}"',
            "[browser_bridge]", "enabled = true", "allowed_origins = []",
        ]), encoding="utf-8"
    )
    app = LocalAIApp(str(config_path))
    previous_app = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        preflight = urllib.request.Request(
            f"{base}/api/vision/review",
            headers={
                "Origin": "chrome-extension://token-only",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type, x-localai-token",
            }, method="OPTIONS"
        )
        with urllib.request.urlopen(preflight) as response:
            assert response.status == 204
            assert response.headers["Access-Control-Allow-Origin"] == "chrome-extension://token-only"
            assert "X-LocalAI-Token" in response.headers["Access-Control-Allow-Headers"]

        browser_preflight = urllib.request.Request(
            f"{base}/api/browser/capture",
            headers={
                "Origin": "chrome-extension://token-only",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type, x-localai-token",
            }, method="OPTIONS"
        )
        with urllib.request.urlopen(browser_preflight) as response:
            assert response.status == 204
            assert response.headers["Access-Control-Allow-Origin"] == "chrome-extension://token-only"
            assert "X-LocalAI-Token" in response.headers["Access-Control-Allow-Headers"]

        capability = _post(
            f"{base}/api/browser/capability",
            {"origin": "chrome-extension://token-only", "tab_id": 7, "window_id": 3},
            origin="chrome-extension://token-only", token=token,
        )
        assert capability["success"] is True
        denied = _post(
            f"{base}/api/browser/capability",
            {"origin": "chrome-extension://token-only", "tab_id": 7, "window_id": 3},
            origin="chrome-extension://token-only",
        )
        assert denied["success"] is False

        original_vision = app.services.vision
        app.services.vision = lambda payload: {"success": True}
        try:
            review = _post(
                f"{base}/api/vision/review",
                {"bundle_artifact_id": "frontend-review-bundle:artifact", "prompt": "Review"},
                origin="chrome-extension://token-only", token=token,
                request_id="t17-token-vision-review-route",
            )
        finally:
            app.services.vision = original_vision
        assert review == {
            "success": True,
            "request_id": "t17-token-vision-review-route",
        }
        denied = _post(
            f"{base}/api/vision/review",
            {"bundle_artifact_id": "frontend-review-bundle:artifact", "prompt": "Review"},
            origin="chrome-extension://token-only", token=token,
            extra_headers={"X-LocalAI-Tenant": "retired"},
        )
        assert denied["error_code"] == "retired_tenant_header"
    finally:
        server.shutdown()
        server.server_close()
        http_server.APP = previous_app
        app.close()
