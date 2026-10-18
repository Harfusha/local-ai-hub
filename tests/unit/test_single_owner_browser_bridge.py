from __future__ import annotations

import inspect

import pytest

from local_ai_hub import browser_bridge


@pytest.mark.parametrize(
    "function",
    [
        browser_bridge.issue_capture_capability,
        browser_bridge.validate_capture_request,
        browser_bridge.stage_capture,
        browser_bridge.commit_staged_capture,
        browser_bridge.abandon_staged_capture,
        browser_bridge.capture_to_artifacts,
        browser_bridge.capture_browser_page,
    ],
)
def test_browser_capture_public_apis_have_no_tenant_parameter(function: object) -> None:
    assert "tenant" not in inspect.signature(function).parameters


@pytest.mark.parametrize("value", [None, False, ""])
def test_capture_payload_rejects_retired_tenant_field_by_presence(value: object) -> None:
    result = browser_bridge.validate_capture_payload({"tenant": value})

    assert result["success"] is False
    assert result["error_code"] == "invalid_request"


def test_capture_capability_request_rejects_retired_field_before_lookup() -> None:
    result = browser_bridge.validate_capture_request("unavailable-capability", {"tenant_id": None})

    assert result["success"] is False
    assert result["error_code"] == "invalid_request"


@pytest.mark.parametrize("value", [None, False, ""])
def test_staging_rejects_retired_tenant_before_request_reservation(value: object) -> None:
    result = browser_bridge.stage_capture(
        "capability", {"tenant_scope": value}, config={}
    )

    assert result["success"] is False
    assert result["error_code"] == "invalid_request"


def test_browser_bridge_source_no_longer_mentions_tenant_in_public_projection() -> None:
    assert "tenant" not in inspect.signature(browser_bridge.capture_to_artifacts).parameters
