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


def test_legacy_v1_not_found_is_compatibility_noise():
    outcome = _telemetry_http_outcome(
        404,
        {"success": False, "error": "not found"},
        "/" + "v1/live/status",
    )

    assert outcome == (True, "compatibility_404", False)


def test_command_failure_is_operational_but_has_specific_category():
    outcome = _telemetry_http_outcome(
        200,
        {"success": False, "error": "command timed out after 120s", "timed_out": True},
        "/api/command",
    )

    assert outcome == (False, "command_timeout", True)
