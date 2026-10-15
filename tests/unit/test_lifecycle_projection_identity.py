"""Deferred F14 lifecycle projection regressions; no live Hub requests."""

import pytest

from local_ai_hub import mcp_server
from local_ai_hub.response_budget import budget_response


def test_projector_restores_async_identity_and_acceptance():
    raw = {
        "success": True, "operation": "preprocess", "operation_id": "op-123",
        "job_id": "job-123", "request_id": "req-123", "accepted": True,
        "completed": False, "status": "queued", "state": "pending",
        "in_progress": True, "request_not_sent": False,
    }
    assert mcp_server._preserve_contract_state(raw, {"success": True}) == raw


@pytest.mark.parametrize("profile", ["minimal", "compact", "standard", "delta"])
def test_bounded_profiles_keep_async_acceptance_distinct_from_completion(profile):
    raw = {
        "success": True, "operation_id": "op-123", "job_id": "job-123",
        "request_id": "req-123", "accepted": True, "completed": False,
        "status": "queued", "in_progress": True,
        "text": "optional detail " * 10_000,
    }
    result = budget_response(raw, max_tokens=600, profile=profile)
    assert result["success"] is True
    for key in ("operation_id", "job_id", "request_id", "accepted", "completed", "status", "in_progress"):
        assert result[key] == raw[key]


def test_terminal_unknown_result_keeps_request_identity():
    result = budget_response({
        "success": False, "terminal": True, "retryable": False,
        "operation_id": "op-unknown", "request_id": "req-unknown",
        "outcome_unknown": True, "request_not_sent": False,
        "error": "Delivery outcome unknown. " * 1000,
    }, max_tokens=600, profile="minimal")
    assert result["success"] is False
    assert result["outcome_unknown"] is True
    assert result["request_not_sent"] is False
    assert result["request_id"] == "req-unknown"
