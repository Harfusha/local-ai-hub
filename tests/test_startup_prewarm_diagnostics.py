from __future__ import annotations

from local_ai_hub.app import _record_startup_prewarm_failure
from local_ai_hub.debug_traces import DebugTraceStore


def _store(tmp_path, *, enabled: bool) -> DebugTraceStore:
    return DebugTraceStore({
        "server": {"state_dir": str(tmp_path)},
        "debug_traces": {"enabled": enabled},
    })


def test_startup_prewarm_failure_is_detailed_only_when_traces_are_enabled(tmp_path):
    disabled = _store(tmp_path / "disabled", enabled=False)
    error = RuntimeError("disabled-secret-detail")
    assert _record_startup_prewarm_failure(disabled, "model-a", error) == ""
    assert disabled.list(limit=10)["items"] == []

    enabled = _store(tmp_path / "enabled", enabled=True)
    try:
        raise RuntimeError("backend returned unexpected failure")
    except RuntimeError as error:
        trace_id = _record_startup_prewarm_failure(enabled, "model-a", error)

    assert trace_id
    detail = enabled.detail(trace_id, full_payload=True)
    assert detail["session"]["state"] == "failed"
    failure = next(event for event in detail["events"] if event["event_type"] == "prewarm_attempt_failed")
    assert failure["payload"]["exception_type"] == "RuntimeError"
    assert failure["payload"]["exception_message"] == "backend returned unexpected failure"
    assert "RuntimeError: backend returned unexpected failure" in failure["payload"]["traceback"]
