from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from local_ai_hub.browser_bridge import (
    CaptureProtocolError,
    capture_to_artifacts,
    issue_capture_capability,
    origin_allowed,
    validate_capture_payload,
    validate_capture_request,
)
from local_ai_hub.config import ConfigError, validate_config


PNG_DATA = base64.b64encode(b"png-fixture").decode("ascii")


def config() -> dict:
    return {
        "browser_bridge": {
            "enabled": True,
            "allowed_origins": ["chrome-extension://fixture"],
            "capability_ttl_seconds": 60,
            "max_payload_bytes": 200_000,
            "max_dom_chars": 20_000,
            "max_elements": 16,
        }
    }


def capture_payload(*, tab_id: int = 7, window_id: int = 3) -> dict:
    return {
        "tab_id": tab_id,
        "window_id": window_id,
        "url": "https://fixture.test/checkout?secret=not-persisted",
        "target_origin": "https://fixture.test",
        "captured_at": "2026-09-18T10:20:30.123Z",
        "title": "Checkout",
        "screenshot": f"data:image/png;base64,{PNG_DATA}",
        "dom": {
            "redaction": "none",
            "html": '<main data-state="logged-in"><button id="pay">Pay</button></main>',
            "elements": [{"element_id": "e0", "tag": "main"}, {"element_id": "e1", "tag": "button"}],
        },
        "accessibility": {"snapshot": [{"element_id": "e1", "role": "button", "name": "Pay"}]},
        "computed_styles": {"e1": {"display": "inline-block", "color": "rgb(0, 0, 0)"}},
        "runtime": {"console_refs": ["console:1"], "network_refs": [{"request_id": "req:1", "method": "GET", "status": 200}]},
        "viewport": {"width": 1280, "height": 720, "device_scale_factor": 1},
    }


class ArtifactSink:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object, str, str | None]] = []

    def put_bytes(self, value: bytes, tenant: str, kind: str, mime_type: str) -> str:
        self.calls.append(("bytes", value, tenant, mime_type))
        return f"{tenant}:screenshot"

    def put_json(self, value: dict, tenant: str, kind: str) -> str:
        self.calls.append((kind, value, tenant, None))
        return f"{tenant}:{kind}"


def test_capture_capability_is_single_use_and_tab_bound() -> None:
    capability = issue_capture_capability(
        config(), origin="chrome-extension://fixture", tenant="tenant-a", tab_id=7, window_id=3
    )

    first = validate_capture_request(
        capability,
        {"origin": "chrome-extension://fixture", "tenant": "tenant-a", "tab_id": 7, "window_id": 3},
    )
    second = validate_capture_request(
        capability,
        {"origin": "chrome-extension://fixture", "tenant": "tenant-a", "tab_id": 7, "window_id": 3},
    )
    wrong_tab = validate_capture_request(
        issue_capture_capability(
            config(), origin="chrome-extension://fixture", tenant="tenant-a", tab_id=7, window_id=3
        ),
        {"origin": "chrome-extension://fixture", "tenant": "tenant-a", "tab_id": 8, "window_id": 3},
    )

    assert first["success"] is True
    assert second["success"] is False
    assert second["error_code"] == "capability_replayed"
    assert wrong_tab["error_code"] == "tab_mismatch"


def test_capability_requires_explicit_tab_id_at_issue_and_validation() -> None:
    with pytest.raises(CaptureProtocolError, match="tab_id"):
        issue_capture_capability(config(), origin="chrome-extension://fixture", tenant="tenant-a")

    capability = issue_capture_capability(
        config(), origin="chrome-extension://fixture", tenant="tenant-a", tab_id=7, window_id=3
    )
    missing = validate_capture_request(
        capability,
        {"origin": "chrome-extension://fixture", "tenant": "tenant-a", "window_id": 3},
    )
    assert missing["error_code"] == "missing_tab_id"
    assert missing["terminal"] is True


def test_capture_requires_sanitized_timestamp_and_target_origin_provenance() -> None:
    sink = ArtifactSink()
    result = capture_to_artifacts(capture_payload(), artifacts=sink, tenant="tenant-a", config=config())

    bundle = next(call[1] for call in sink.calls if call[0] == "frontend-review-bundle")
    assert result["success"] is True
    assert bundle["provenance"] == {
        "captured_at": "2026-09-18T10:20:30.123Z",
        "target_origin": "https://fixture.test",
    }

    oversized = capture_payload()
    oversized["captured_at"] = "x" * 65
    assert validate_capture_payload(oversized, config=config())["error_code"] == "invalid_capture_timestamp"

    oversized = capture_payload()
    oversized["target_origin"] = "https://" + ("a" * 260) + ".test"
    assert validate_capture_payload(oversized, config=config())["error_code"] == "target_origin_mismatch"


def test_default_browser_origin_policy_is_fail_closed() -> None:
    assert origin_allowed({"browser_bridge": {"enabled": True, "allowed_origins": []}}, "chrome-extension://x") is False
    defaults = Path(__file__).parents[1] / "src/local_ai_hub/defaults.toml"
    assert 'allowed_origins = ["chrome-extension://*"]' not in defaults.read_text(encoding="utf-8")


def test_explicit_api_token_authorization_can_replace_origin_allow_list() -> None:
    token_config = {"browser_bridge": {"enabled": True, "allowed_origins": []}}
    capability = issue_capture_capability(
        token_config,
        origin="chrome-extension://configured-by-token",
        tenant="tenant-a",
        tab_id=7,
        api_token_authorized=True,
    )
    result = validate_capture_request(
        capability,
        {"origin": "chrome-extension://configured-by-token", "tenant": "tenant-a", "tab_id": 7},
    )
    assert result["success"] is True


def test_capture_payload_preserves_full_dom_and_requires_none_attestation() -> None:
    result = validate_capture_payload(capture_payload())

    assert result["success"] is True
    assert result["payload"]["dom"]["redaction"] == "none"
    assert "logged-in" in result["payload"]["dom"]["html"]

    missing = capture_payload()
    del missing["dom"]["redaction"]
    assert validate_capture_payload(missing)["error_code"] == "missing_dom_redaction"


def test_capture_rejects_credentials_and_network_bodies() -> None:
    payload = capture_payload()
    payload.update({"cookies": [], "authorization": "Bearer secret", "request_bodies": [{}]})

    result = validate_capture_payload(payload)

    assert result["success"] is False
    assert result["error"] == "credential-bearing capture fields are not allowed"

    payload = capture_payload()
    payload["runtime"] = {"network": [{"request_id": "req:1", "body": "must-not-persist"}]}
    assert validate_capture_payload(payload)["error_code"] == "credential_bearing_capture_fields"


@pytest.mark.parametrize(
    ("error_code", "status"),
    [("unsupported", 501), ("permission_denied", 403), ("closed_tab", 410), ("timeout", 408)],
)
def test_capture_failure_codes_are_explicit(error_code: str, status: int) -> None:
    from local_ai_hub.browser_bridge import capture_failure

    result = capture_failure(error_code)

    assert result["success"] is False
    assert result["error_code"] == error_code
    assert result["status"] == status
    assert result["fallback"] is False


def test_capture_bounds_reject_oversized_dom_and_element_list() -> None:
    payload = capture_payload()
    payload["dom"]["html"] = "x" * 20_001
    assert validate_capture_payload(payload, config=config())["error_code"] == "dom_too_large"

    payload = capture_payload()
    payload["dom"]["elements"] = [{"element_id": str(i)} for i in range(17)]
    assert validate_capture_payload(payload, config=config())["error_code"] == "too_many_elements"


def test_capture_artifacts_are_tenant_scoped_and_network_is_metadata_only() -> None:
    sink = ArtifactSink()
    result = capture_to_artifacts(capture_payload(), artifacts=sink, tenant="tenant-a", config=config())

    assert result["success"] is True
    assert result["bundle_artifact_id"] == "tenant-a:frontend-review-bundle"
    assert all(call[2] == "tenant-a" for call in sink.calls)
    runtime = next(call[1] for call in sink.calls if call[0] == "browser-runtime")
    assert runtime["network_refs"][0] == {"request_id": "req:1", "method": "GET", "status": 200}
    assert "secret" not in json.dumps(runtime)
    assert not any("authorization" in json.dumps(call[1]).lower() for call in sink.calls if isinstance(call[1], dict))


def test_browser_bridge_config_validates_bounds_without_becoming_required() -> None:
    validate_config({"server": {"port": 11435}})
    validate_config({"server": {"port": 11435}, **config()})
    with pytest.raises(ConfigError, match="allowed_origins"):
        validate_config({"server": {"port": 11435}, "browser_bridge": {"allowed_origins": "not-a-list"}})


def test_extension_is_explicit_current_tab_only_and_does_not_mutate_pages() -> None:
    root = Path(__file__).parents[1] / "browser_bridge"
    background = (root / "background.js").read_text(encoding="utf-8")
    capture = (root / "capture.js").read_text(encoding="utf-8")

    assert "chrome.action.onClicked" in background
    assert "tabs.get" in background
    assert "tabs.query" in background
    assert "tabs.update" not in background
    assert "windows.create" not in background
    assert "document.cookie" not in capture
    assert "input.value" not in capture
    assert "setAttribute(" not in capture
    assert "location.href =" not in capture
