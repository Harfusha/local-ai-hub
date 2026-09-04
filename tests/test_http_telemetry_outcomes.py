from __future__ import annotations

from local_ai_hub.http_server import _telemetry_http_outcome


def test_policy_block_is_a_successful_terminal_client_outcome():
    outcome = _telemetry_http_outcome(
        400,
        {"success": False, "policy_blocked": True, "terminal": True, "retryable": False},
    )

    assert outcome == (True, "policy_block", False)


def test_duplicate_in_progress_is_not_a_runtime_failure_or_retry():
    outcome = _telemetry_http_outcome(
        409,
        {"success": False, "in_progress": True, "retryable": True},
    )

    assert outcome == (True, "in_progress", False)


def test_service_failure_remains_a_runtime_failure():
    outcome = _telemetry_http_outcome(503, {"success": False, "error": "overloaded", "retryable": True})

    assert outcome == (False, "http_error", True)
