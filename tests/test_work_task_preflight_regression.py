"""New task-bound mutating work must not queue against a planned task."""
import json

from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import GoalContract, TaskStatus
from local_ai_hub.app import LocalAIApp


def test_bounded_submit_requires_active_task_but_preserves_idempotent_replay(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "file.py").write_text("value = 1\n", encoding="utf-8")
    config = tmp_path / "isolated.toml"
    config.write_text(
        "[server]\nstate_dir = " + json.dumps(str(tmp_path / "state"))
        + "\n[ollama]\nenabled = false\n[smart_ollama]\nenabled = false"
        + "\n[observability]\nenabled = false\n[background_gpu]\nenabled = false"
        + "\n[preprocessing]\nenabled = false\n[security]\nallowed_roots = ["
        + json.dumps(str(root)) + "]\n", encoding="utf-8",
    )
    app = LocalAIApp(str(config))
    try:
        work = app.work_orchestrator
        monkeypatch.setattr(work, "_ensure_workers", lambda: None)
        store = work.verification_store.task_store
        store.create(GoalContract(goal="change", acceptance_criteria=("tests pass",)),
                     ScopeContext(task_id="task"), task_id="task", actor="owner", repo_root=str(root))
        payload = {
            "root": str(root), "task": "Update the fixture", "task_id": "task", "work_id": "work-1",
            "acceptance_criteria": ["tests pass"], "mode": "bounded", "allowed_paths": ["file.py"],
            "approved_commands": ["python -m pytest -q"],
            "permissions": {"read": True, "edit": True, "tests": True, "build": True},
            "budget": {"max_steps": 4, "max_seconds": 60},
        }
        denied = work.submit(payload)
        assert denied["success"] is False
        assert denied["terminal"] is True
        assert work._row("work-1") is None

        missing = work.submit({**payload, "task_id": "missing", "work_id": "missing-work"})
        assert missing["success"] is False
        assert work._row("missing-work") is None
        other_root = tmp_path / "other"
        other_root.mkdir()
        store.create(GoalContract(goal="other", acceptance_criteria=("tests pass",)),
                     ScopeContext(task_id="foreign"), task_id="foreign", actor="owner", repo_root=str(other_root))
        store.transition("foreign", TaskStatus.ACTIVE, reason="start", actor="owner", idempotency_key="foreign-start")
        foreign = work.submit({**payload, "task_id": "foreign", "work_id": "foreign-work"})
        assert foreign["success"] is False
        assert work._row("foreign-work") is None

        store.transition("task", TaskStatus.ACTIVE, reason="start", actor="owner", idempotency_key="start")
        with monkeypatch.context() as patcher:
            def unavailable(_task_id):
                raise OSError("task database unavailable")
            patcher.setattr(store, "get", unavailable)
            error = work.submit({**payload, "work_id": "unavailable-work"})
        assert error["success"] is False
        assert error["retryable"] is True
        assert error["operation_not_started"] is True
        assert work._row("unavailable-work") is None

        accepted = work.submit(payload)
        assert accepted["success"] is True
        assert accepted["status"] == "queued"
        store.transition("task", TaskStatus.BLOCKED, reason="pause", actor="owner", idempotency_key="pause")
        replay = work.submit(payload)
        assert replay["success"] is True
        assert replay["work_id"] == "work-1"

        store.create(GoalContract(goal="read", acceptance_criteria=("tests pass",)),
                     ScopeContext(task_id="read-task"), task_id="read-task", actor="owner", repo_root=str(root))
        read_only = work.submit({**payload, "task_id": "read-task", "work_id": "read-work",
                                 "permissions": {**payload["permissions"], "edit": False}})
        assert read_only["success"] is True
    finally:
        app.close()
