from tools.t02_queue_diagnostics import (
    admission_failure_code,
    cancellation_failure_code,
)


def test_admission_failure_has_stage_and_allowlisted_reason_only() -> None:
    assert admission_failure_code({"success": True, "job_id": "j-1"}) is None
    assert admission_failure_code({"success": False, "error": "async jobs disabled"}) == (
        "submit_rejected:async_jobs_disabled"
    )
    assert admission_failure_code(
        {"success": False, "error": "secret or path must not be recorded"}
    ) == "submit_rejected:other"


def test_cancel_failure_records_state_without_payload() -> None:
    assert cancellation_failure_code({"success": True, "state": "cancelled"}) is None
    assert cancellation_failure_code({"success": True, "state": "running"}) == (
        "cancel_not_cancelled:running"
    )
    assert cancellation_failure_code({"success": False, "state": "other", "payload": "secret"}) == (
        "cancel_not_cancelled:other"
    )
