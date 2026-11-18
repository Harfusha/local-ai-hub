from __future__ import annotations

from types import SimpleNamespace

from local_ai_hub.app import LocalAIApp


def test_context_scope_skip_records_only_exception_type(tmp_path):
    app = LocalAIApp.__new__(LocalAIApp)
    app.config = {"laya": {"runtime": {
        "checkpoint_path": "pinned-local-checkpoint",
        "revision": "pinned-revision",
        "expected_sha256": {"model.safetensors": "a" * 64},
    }}}
    events = []
    app.telemetry = SimpleNamespace(record_stage=lambda **event: events.append(event))

    def fail_scope(*_args):
        raise ValueError("private task details")

    app.agent_tasks = object()
    app.laya_candidates = SimpleNamespace(_find_task=fail_scope)
    request = SimpleNamespace(task_id="task-1", session_id="session-1")

    result = app.capture_laya_context_source_from_context(request, {"success": True})

    assert result == {
        "status": "skipped", "reason": "task_scope_unavailable", "error_type": "ValueError",
    }
    assert events == [{
        "action": "laya_capture", "stage": "skipped",
        "bypass_reason": "task_scope_unavailable", "success": True,
        "error_type": "ValueError",
    }]
