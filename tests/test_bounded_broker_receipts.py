import json
import threading
import pytest

from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import GoalContract, TaskStatus
from local_ai_hub.app import LocalAIApp
from test_work_orchestrator import init_repo, wait_terminal


@pytest.mark.parametrize("second_edit", [False, True])
def test_bounded_work_returns_real_receipt_without_accepting_task(tmp_path, monkeypatch, second_edit):
    root = init_repo(tmp_path)
    (root / "test_sample.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    config = tmp_path / "isolated.toml"
    config.write_text("[server]\nstate_dir = " + json.dumps(str(tmp_path / "state"))
        + "\n[ollama]\nenabled = false\n[smart_ollama]\nenabled = false"
        + "\n[observability]\nenabled = false\n[background_gpu]\nenabled = false"
        + "\n[preprocessing]\nenabled = false\n[security]\nallowed_roots = ["
        + json.dumps(str(root)) + "]\n", encoding="utf-8")
    app = LocalAIApp(str(config))
    try:
        # Receipt semantics are tested without optional streaming; blocked
        # callback delivery has its own fail-closed regression test.
        monkeypatch.setattr(app.services, "agent_state", None)
        store = app.work_orchestrator.verification_store.task_store
        task = store.create(GoalContract(goal="change", acceptance_criteria=("pytest tests pass",)),
                            ScopeContext(task_id="task"), task_id="task", actor="owner", repo_root=str(root))
        store.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="owner", idempotency_key="start")
        finished = threading.Event()
        finish = store._finish_fenced_work_mutation
        def finish_observed(*args, **kwargs):
            result = finish(*args, **kwargs)
            finished.set()
            return result
        monkeypatch.setattr(store, "_finish_fenced_work_mutation", finish_observed)
        calls = []
        def delegate(_args, **_kwargs):
            calls.append(1)
            if len(calls) == 1:
                steps = [
                    {"id": "edit", "kind": "edit", "task": "change", "depends_on": []},
                    {"id": "validate", "kind": "validate", "task": "pytest tests pass", "depends_on": ["edit"]}]
                if second_edit:
                    steps.extend([
                        {"id": "edit2", "kind": "edit", "task": "change again", "depends_on": ["validate"]},
                        {"id": "validate2", "kind": "validate", "task": "pytest tests pass", "depends_on": ["edit2"]}])
                return {"success": True, "text": json.dumps({"summary": "change", "steps": steps})}
            if second_edit and len(calls) == 3:
                return {"success": True, "text": "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-new\n+newer\n"}
            return {"success": True, "text": "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n"}
        monkeypatch.setattr(app.services, "delegate_repo", delegate)
        monkeypatch.setattr(app.services, "second_opinion", lambda *_a, **_k: {"success": True, "text": json.dumps({
            "passed": True, "summary": "checked", "criteria": [{"criterion": "pytest tests pass", "passed": True}], "risks": []})})
        result = app.work_orchestrator.submit({"root": str(root), "task": "change", "task_id": task.task_id,
            "mode": "bounded", "acceptance_criteria": ["pytest tests pass"], "allowed_paths": ["a.txt"],
            "approved_commands": ["python -m pytest -q test_sample.py"], "budget": {"max_steps": 8, "max_seconds": 90},
            "permissions": {"edit": True, "tests": True, "build": True}})
        assert result["success"] is True
        handoff = wait_terminal(app.work_orchestrator, result["work_id"], timeout=40)
        assert finished.wait(5)
        if handoff["status"] != "needs_agent":
            diagnostic = app.artifacts.get(handoff["artifact_id"], max_chars=30000)
            pytest.fail(f"work failed: {handoff}; report: {diagnostic.get('text')}")
        assert handoff["validation"]["receipt_status"] == "recorded_unmapped"
        report = json.loads(app.artifacts.get(handoff["artifact_id"], max_chars=30000)["text"])
        assert report["verification_receipts"]
        receipt = report["verification_receipts"][-1]
        assert receipt["passed"] is True and receipt["mutation_generation"] == store.get(task.task_id).checkpoint.state_data["mutation_generation"]
        if second_edit:
            assert all(item["mutation_generation"] == 2 for item in report["verification_receipts"])
            assert any(item.get("receipt_status") == "stale" for item in report["validation"])
        assert store.get(task.task_id).verification_receipts == {}
        assert (root / "a.txt").read_text(encoding="utf-8").strip() == ("newer" if second_edit else "new")
        assert any(item.get("exit_code") == 0 for item in report["validation"])
        from local_ai_hub.agent_verification import VerificationReceipt
        app.work_orchestrator.verification_store.record(VerificationReceipt.from_dict(receipt), update_task=True)
        assert store.get(task.task_id).verification_receipts["pytest tests pass"] == receipt["receipt_id"]
    finally:
        app.close()


def test_task_bound_validation_without_patch_does_not_require_barrier(tmp_path, monkeypatch):
    root = init_repo(tmp_path)
    (root / "test_sample.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    config = tmp_path / "isolated.toml"
    config.write_text("[server]\nstate_dir = " + json.dumps(str(tmp_path / "state"))
        + "\n[ollama]\nenabled = false\n[smart_ollama]\nenabled = false"
        + "\n[observability]\nenabled = false\n[background_gpu]\nenabled = false"
        + "\n[preprocessing]\nenabled = false\n[security]\nallowed_roots = ["
        + json.dumps(str(root)) + "]\n", encoding="utf-8")
    app = LocalAIApp(str(config))
    try:
        monkeypatch.setattr(app.services, "agent_state", None)
        store = app.work_orchestrator.verification_store.task_store
        task = store.create(GoalContract(goal="validate"), ScopeContext(task_id="task"),
                            task_id="task", actor="owner", repo_root=str(root))
        store.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="owner", idempotency_key="start")
        monkeypatch.setattr(app.services, "delegate_repo", lambda *_a, **_k: {"success": True, "text": json.dumps({
            "summary": "validate", "steps": [{"id": "check", "kind": "validate", "task": "pytest tests pass", "depends_on": []}]})})
        monkeypatch.setattr(app.services, "second_opinion", lambda *_a, **_k: {"success": True, "text": json.dumps({
            "passed": True, "summary": "checked", "criteria": [{"criterion": "pytest tests pass", "passed": True}], "risks": []})})
        result = app.work_orchestrator.submit({"root": str(root), "task": "validate", "task_id": task.task_id,
            "mode": "bounded", "acceptance_criteria": ["pytest tests pass"], "allowed_paths": ["a.txt"],
            "approved_commands": ["python -m pytest -q test_sample.py"], "budget": {"max_steps": 6, "max_seconds": 90},
            "permissions": {"edit": True, "tests": True, "build": True}})
        assert result["success"] is True
        handoff = wait_terminal(app.work_orchestrator, result["work_id"], timeout=40)
        if handoff["status"] != "needs_agent":
            diagnostic = app.artifacts.get(handoff["artifact_id"], max_chars=30000)
            pytest.fail(f"work failed: {handoff}; report: {diagnostic.get('text')}")
        assert handoff["validation"]["receipt_status"] == "not_recorded"
        assert "_pending_fenced_work" not in store.get(task.task_id).checkpoint.state_data
    finally:
        app.close()
