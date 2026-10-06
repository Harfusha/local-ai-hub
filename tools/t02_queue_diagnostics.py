"""Safe, bounded failure labels for T02 async-queue benchmark probes."""

from __future__ import annotations

from typing import Any


_SUBMIT_ERRORS = {
    "async jobs disabled": "async_jobs_disabled",
    "async job manager is closed": "manager_closed",
    "async job admission rejected by resource pressure": "resource_pressure",
    "async job queue limit reached": "queue_limit",
}
_CANCEL_STATES = {"queued", "running", "cancelled", "done", "failed", "expired", "outcome_unknown"}


def admission_failure_code(response: Any) -> str | None:
    """Return an allowlisted reason; never copy arbitrary response text."""
    if isinstance(response, dict) and response.get("success") is True and response.get("job_id"):
        return None
    if not isinstance(response, dict):
        return "submit_rejected:other"
    reason = response.get("error")
    if not isinstance(reason, str):
        return "submit_rejected:other"
    return f"submit_rejected:{_SUBMIT_ERRORS.get(reason.strip().lower(), 'other')}"


def cancellation_failure_code(response: Any) -> str | None:
    """Describe a failed cancellation using only a known async-job state."""
    if not isinstance(response, dict):
        return "cancel_not_cancelled:other"
    if response.get("success") is True and response.get("state") == "cancelled":
        return None
    state = response.get("state")
    if not isinstance(state, str):
        return "cancel_not_cancelled:other"
    normalized = state.strip().lower()
    if normalized not in _CANCEL_STATES or normalized == "cancelled":
        return "cancel_not_cancelled:other"
    return f"cancel_not_cancelled:{normalized}"
