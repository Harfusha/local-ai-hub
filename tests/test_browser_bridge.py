from __future__ import annotations

import base64
import json
import threading
import tomllib
from pathlib import Path

import pytest

import local_ai_hub.browser_bridge as browser_bridge_module
from local_ai_hub.browser_bridge import (
    CaptureProtocolError,
    abandon_staged_capture,
    capture_to_artifacts,
    commit_staged_capture,
    issue_capture_capability,
    origin_allowed,
    stage_capture,
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
        "origin": "chrome-extension://fixture",
        "tab_id": tab_id,
        "window_id": window_id,
        "url": "https://fixture.test/checkout?secret=not-persisted",
        "target_origin": "https://fixture.test",
        "captured_at": "2026-09-18T10:20:30.123Z",
        "capture_identity": {
            "initial": {
                "url": "https://fixture.test/checkout?secret=not-persisted",
                "target_origin": "https://fixture.test",
                "document_token": "document:fixture:1",
                "document_state_token": "state:fixture:1",
            },
            "final": {
                "url": "https://fixture.test/checkout?secret=not-persisted",
                "target_origin": "https://fixture.test",
                "document_token": "document:fixture:1",
                "document_state_token": "state:fixture:1",
            },
        },
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


def test_capability_requires_exact_window_id_at_issue_and_validation() -> None:
    with pytest.raises(CaptureProtocolError, match="window_id"):
        issue_capture_capability(config(), origin="chrome-extension://fixture", tenant="tenant-a", tab_id=7)

    capability = issue_capture_capability(
        config(), origin="chrome-extension://fixture", tenant="tenant-a", tab_id=7, window_id=3
    )
    missing = validate_capture_request(
        capability,
        {"origin": "chrome-extension://fixture", "tenant": "tenant-a", "tab_id": 7},
    )
    assert missing["error_code"] == "missing_window_id"
    assert missing["terminal"] is True


def test_capture_requires_sanitized_timestamp_and_target_origin_provenance() -> None:
    sink = ArtifactSink()
    result = capture_to_artifacts(capture_payload(), artifacts=sink, tenant="tenant-a", config=config())

    bundle = next(call[1] for call in sink.calls if call[0] == "frontend-review-bundle")
    assert result["success"] is True
    assert bundle["provenance"] == {
        "captured_at": "2026-09-18T10:20:30.123Z",
        "target_origin": "https://fixture.test",
        "document_token": "document:fixture:1",
        "document_state_token": "state:fixture:1",
    }

    oversized = capture_payload()
    oversized["captured_at"] = "x" * 65
    assert validate_capture_payload(oversized, config=config())["error_code"] == "invalid_capture_timestamp"

    oversized = capture_payload()
    oversized["target_origin"] = "https://" + ("a" * 260) + ".test"
    assert validate_capture_payload(oversized, config=config())["error_code"] == "target_origin_mismatch"


def test_capture_aborts_same_tab_navigation_before_artifact_commit() -> None:
    payload = capture_payload()
    payload["capture_identity"]["final"]["url"] = "https://fixture.test/other"
    result = validate_capture_payload(payload, config=config())

    assert result["success"] is False
    assert result["error_code"] == "target_changed"
    assert result["status"] == 409


def test_staged_capture_requires_explicit_commit_and_abandon_is_terminal() -> None:
    sink = ArtifactSink()
    capability = issue_capture_capability(
        config(), origin="chrome-extension://fixture", tenant="tenant-a", tab_id=7, window_id=3
    )
    payload = capture_payload()
    payload["request_id"] = "capture-request-1"

    staged = stage_capture(capability, payload, tenant="tenant-a", config=config())
    assert staged == {"success": True, "staged": True, "request_id": "capture-request-1"}
    assert sink.calls == []

    duplicate = stage_capture(capability, payload, tenant="tenant-a", config=config())
    assert duplicate == staged
    committed = commit_staged_capture(
        capability,
        {"origin": "chrome-extension://fixture", "tab_id": 7, "window_id": 3, "request_id": "capture-request-1"},
        artifacts=sink,
        tenant="tenant-a",
        config=config(),
    )
    assert committed["success"] is True
    assert any(call[0] == "frontend-review-bundle" for call in sink.calls)
    late_commit = commit_staged_capture(
        capability,
        {"origin": "chrome-extension://fixture", "tab_id": 7, "window_id": 3, "request_id": "capture-request-1"},
        artifacts=sink,
        tenant="tenant-a",
        config=config(),
    )
    assert late_commit == committed
    assert len([call for call in sink.calls if call[0] == "frontend-review-bundle"]) == 1

    abandoned_sink = ArtifactSink()
    abandoned_capability = issue_capture_capability(
        config(), origin="chrome-extension://fixture", tenant="tenant-a", tab_id=7, window_id=3
    )
    abandoned_payload = capture_payload()
    abandoned_payload["request_id"] = "capture-request-abandoned"
    assert stage_capture(abandoned_capability, abandoned_payload, tenant="tenant-a", config=config())["success"] is True
    abandoned = abandon_staged_capture(
        abandoned_capability,
        {"origin": "chrome-extension://fixture", "tab_id": 7, "window_id": 3, "request_id": "capture-request-abandoned"},
        tenant="tenant-a",
    )
    assert abandoned["success"] is True
    assert abandoned_sink.calls == []
    late_commit = commit_staged_capture(
        abandoned_capability,
        {"origin": "chrome-extension://fixture", "tab_id": 7, "window_id": 3, "request_id": "capture-request-abandoned"},
        artifacts=abandoned_sink,
        tenant="tenant-a",
        config=config(),
    )
    assert late_commit == abandoned
    assert abandoned_sink.calls == []


def test_request_id_conflict_does_not_poison_losing_capability() -> None:
    payload = capture_payload()
    payload["request_id"] = "shared-request"
    first = issue_capture_capability(config(), origin="chrome-extension://fixture", tenant="tenant-a", tab_id=7, window_id=3)
    second = issue_capture_capability(config(), origin="chrome-extension://fixture", tenant="tenant-a", tab_id=7, window_id=3)

    assert stage_capture(first, payload, tenant="tenant-a", config=config())["success"] is True
    assert stage_capture(second, payload, tenant="tenant-a", config=config())["error_code"] == "request_id_conflict"

    replacement = dict(payload)
    replacement["request_id"] = "second-request"
    assert stage_capture(second, replacement, tenant="tenant-a", config=config())["success"] is True


def test_terminal_request_id_is_idempotent_and_conflicts_across_capabilities() -> None:
    sink = ArtifactSink()
    first = issue_capture_capability(config(), origin="chrome-extension://fixture", tenant="tenant-a", tab_id=7, window_id=3)
    payload = capture_payload()
    payload["request_id"] = "terminal-request"
    assert stage_capture(first, payload, tenant="tenant-a", config=config())["success"] is True
    request = {"origin": "chrome-extension://fixture", "tab_id": 7, "window_id": 3, "request_id": "terminal-request"}

    committed = commit_staged_capture(first, request, artifacts=sink, tenant="tenant-a", config=config())
    replay = commit_staged_capture(first, request, artifacts=sink, tenant="tenant-a", config=config())
    assert replay == committed
    assert len([call for call in sink.calls if call[0] == "frontend-review-bundle"]) == 1

    other = issue_capture_capability(config(), origin="chrome-extension://fixture", tenant="tenant-a", tab_id=7, window_id=3)
    conflict = commit_staged_capture(other, request, artifacts=ArtifactSink(), tenant="tenant-a", config=config())
    assert conflict["error_code"] == "request_id_conflict"


def test_abandon_cancels_inflight_commit_before_artifact_write(monkeypatch: pytest.MonkeyPatch) -> None:
    started = threading.Event()
    release = threading.Event()
    sink = ArtifactSink()
    capability = issue_capture_capability(config(), origin="chrome-extension://fixture", tenant="tenant-a", tab_id=7, window_id=3)
    payload = capture_payload()
    payload["request_id"] = "cancel-inflight"
    assert stage_capture(capability, payload, tenant="tenant-a", config=config())["success"] is True

    def delayed_capture(*_args, cancel_check=None, **_kwargs):
        started.set()
        release.wait(2)
        assert cancel_check is not None
        if cancel_check():
            return {"success": False, "terminal": True, "retryable": False, "error_code": "capture_cancelled", "error": "cancelled"}
        raise AssertionError("cancel check did not observe abandon")

    monkeypatch.setattr(browser_bridge_module, "capture_to_artifacts", delayed_capture)
    result: list[dict] = []
    worker = threading.Thread(
        target=lambda: result.append(
            commit_staged_capture(
                capability,
                {"origin": "chrome-extension://fixture", "tab_id": 7, "window_id": 3, "request_id": "cancel-inflight"},
                artifacts=sink,
                tenant="tenant-a",
                config=config(),
            )
        )
    )
    worker.start()
    assert started.wait(2)
    cancelled = abandon_staged_capture(
        capability,
        {"origin": "chrome-extension://fixture", "tab_id": 7, "window_id": 3, "request_id": "cancel-inflight"},
        tenant="tenant-a",
    )
    assert cancelled["success"] is True
    release.set()
    worker.join(2)
    assert result == [{"success": False, "terminal": True, "retryable": False, "error_code": "capture_cancelled", "error": "cancelled", "request_id": "cancel-inflight"}]
    assert sink.calls == []
def test_expired_staged_capture_is_cleaned_without_artifact_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = {"now": 100.0}
    monkeypatch.setattr(browser_bridge_module.time, "monotonic", lambda: clock["now"])
    short_config = config()
    short_config["browser_bridge"]["capability_ttl_seconds"] = 1
    sink = ArtifactSink()
    capability = issue_capture_capability(
        short_config, origin="chrome-extension://fixture", tenant="tenant-a", tab_id=7, window_id=3
    )
    payload = capture_payload()
    payload["request_id"] = "capture-request-expired"
    assert stage_capture(capability, payload, tenant="tenant-a", config=short_config)["success"] is True

    clock["now"] = 102.0
    replacement = issue_capture_capability(
        short_config, origin="chrome-extension://fixture", tenant="tenant-a", tab_id=7, window_id=3
    )
    assert replacement
    late_commit = commit_staged_capture(
        capability,
        {"origin": "chrome-extension://fixture", "tab_id": 7, "window_id": 3, "request_id": "capture-request-expired"},
        artifacts=sink,
        tenant="tenant-a",
        config=short_config,
    )
    assert late_commit["success"] is False
    assert sink.calls == []


def test_packaged_browser_bridge_defaults_match_source_defaults() -> None:
    root = Path(__file__).parents[1]
    source = tomllib.loads((root / "src/local_ai_hub/defaults.toml").read_text(encoding="utf-8"))
    packaged = tomllib.loads((root / "defaults.toml").read_text(encoding="utf-8"))
    assert packaged["browser_bridge"] == source["browser_bridge"]


def test_default_browser_origin_policy_is_fail_closed() -> None:
    assert origin_allowed({"browser_bridge": {"enabled": True, "allowed_origins": []}}, "chrome-extension://x") is False
    assert origin_allowed({"browser_bridge": {"enabled": True, "allowed_origins": ["chrome-extension://fixture*"]}}, "chrome-extension://fixture-extra") is False
    defaults = Path(__file__).parents[1] / "src/local_ai_hub/defaults.toml"
    assert 'allowed_origins = ["chrome-extension://*"]' not in defaults.read_text(encoding="utf-8")


def test_explicit_api_token_authorization_can_replace_origin_allow_list() -> None:
    token_config = {"browser_bridge": {"enabled": True, "allowed_origins": []}}
    capability = issue_capture_capability(
        token_config,
        origin="chrome-extension://configured-by-token",
        tenant="tenant-a",
        tab_id=7,
        window_id=3,
        api_token_authorized=True,
    )
    result = validate_capture_request(
        capability,
        {"origin": "chrome-extension://configured-by-token", "tenant": "tenant-a", "tab_id": 7, "window_id": 3},
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
    [("unsupported", 501), ("permission_denied", 403), ("closed_tab", 410), ("timeout", 408), ("target_changed", 409)],
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
    with pytest.raises(ConfigError, match="exact origins"):
        validate_config({"server": {"port": 11435}, "browser_bridge": {"allowed_origins": ["chrome-extension://*"]}})


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
    assert "document.documentElement.setAttribute(" not in capture
    assert "location.href =" not in capture
