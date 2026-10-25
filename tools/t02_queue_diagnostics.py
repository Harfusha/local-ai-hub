"""Safe, bounded failure labels for T02 async-queue benchmark probes."""

from __future__ import annotations

from typing import Any
import math


_SUBMIT_ERRORS = {
    "async jobs disabled": "async_jobs_disabled",
    "async job manager is closed": "manager_closed",
    "async job admission rejected by resource pressure": "resource_pressure",
    "async job queue limit reached": "queue_limit",
}
_CANCEL_STATES = {"queued", "running", "cancelled", "done", "failed", "expired", "outcome_unknown"}


class NominalFixtureScheduler:
    """Explicit harness-only double; delegate scheduling, replace only sampling."""

    def __init__(self, scheduler):
        self.scheduler = scheduler

    def __getattr__(self, name):
        return getattr(self.scheduler, name)

    def resource_status(self):
        return {"pressure_level": "nominal", "throttle_background": False,
                "context_budget_factor": 1.0}


def resource_decision_sample(response: Any) -> dict[str, Any] | None:
    """Project only typed, bounded admission metadata, never task payloads."""
    admission = response.get("admission") if isinstance(response, dict) else None
    sample = admission.get("resource_sample") if isinstance(admission, dict) else None
    if not isinstance(sample, dict):
        return None
    result = {}
    available = sample.get("available")
    result["available"] = available if type(available) is bool else None
    for key in ("provider", "pressure_level", "telemetry_error", "measurement_basis"):
        value = sample.get(key)
        result[key] = value[:256] if isinstance(value, str) else None
    for key in ("observed_at", "sample_timestamp", "sample_age_seconds", "context_budget_factor"):
        value = sample.get(key)
        result[key] = value if type(value) in (int, float) and math.isfinite(value) else None
    value = sample.get("throttle_background")
    result["throttle_background"] = value if type(value) is bool else None
    basis = sample.get("measured_basis")
    result["measured_basis"] = {
        key: value if type(value) in (int, float) and math.isfinite(value) else None
        for key in ("vram_total_mb", "vram_used_mb", "vram_available_mb", "vram_used_pct",
                    "unified_memory_mb", "unified_memory_used_mb", "unified_memory_available_mb",
                    "policy_pressure_pct", "policy_headroom_mb")
        for value in [(basis.get(key) if isinstance(basis, dict) else None)]
    }
    return result


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
