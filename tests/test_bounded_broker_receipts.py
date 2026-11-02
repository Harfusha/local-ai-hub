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


@pytest.mark.parametrize("ending", ["needs_agent", "needs_agent_large_patch", "needs_agent_no_artifact", "needs_agent_blank_artifact", "failure", "failure_no_artifact", "failure_invalid_artifact", "cancel", "budget", "budget_no_artifact", "conflict", "conflict_unknown", "cancel_conflict", "cancel_conflict_unknown", "cancel_conflict_no_artifact", "cancel_conflict_blank_artifact", "cancel_after_rollback", "cancel_after_budget_rollback", "cancel_during_failure_conflict", "cancel_during_failure_conflict_no_artifact", "rollback_lost_fence", "rollback_lost_fence_cancelled", "final_handoff_no_artifact"])
def test_review_rollback_marks_real_broker_receipt_stale(tmp_path, monkeypatch, ending):
    invalid_failure_artifact = ending == "failure_invalid_artifact"
    if invalid_failure_artifact:
        ending = "failure_no_artifact"
    blank_cancellation_artifact = ending == "cancel_conflict_blank_artifact"
    if blank_cancellation_artifact:
        ending = "cancel_conflict_no_artifact"
    blank_handoff_artifact = ending == "needs_agent_blank_artifact"
    if blank_handoff_artifact:
        ending = "needs_agent_no_artifact"
    cancel_lost_fence = ending == "rollback_lost_fence_cancelled"
    if cancel_lost_fence:
        ending = "rollback_lost_fence"
    no_failure_artifact = ending in {"cancel_during_failure_conflict_no_artifact", "failure_no_artifact"}
    if no_failure_artifact:
        ending = ending.removesuffix("_no_artifact")
    large_patch = ending == "needs_agent_large_patch"
    if large_patch:
        ending = "needs_agent"
    no_handoff_artifact = ending in {"needs_agent_no_artifact", "budget_no_artifact"}
    if no_handoff_artifact:
        ending = ending.removesuffix("_no_artifact")
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
        if ending == "final_handoff_no_artifact":
            original_put = app.artifacts.put
            def no_final_handoff(text, *, kind, **kwargs):
                if kind == "work-handoff":
                    return None
                return original_put(text, kind=kind, **kwargs)
            monkeypatch.setattr(app.artifacts, "put", no_final_handoff)
        if ending == "rollback_lost_fence":
            from local_ai_hub.work_fencing import LeaseLostError
            finished = threading.Event()
            recovery_scheduled = threading.Event()
            artifact_kinds = []
            original_execute = app.work_orchestrator._execute
            original_put = app.artifacts.put
            original_rollback = app.work_orchestrator._rollback_transaction
            def execute_once(row):
                try:
                    return original_execute(row)
                finally:
                    finished.set()
            def track_artifact(text, *, kind, **kwargs):
                artifact_kinds.append(kind)
                return original_put(text, kind=kind, **kwargs)
            def lost_fence(*args, **kwargs):
                raise LeaseLostError("attempt superseded")
            monkeypatch.setattr(app.work_orchestrator, "_execute", execute_once)
            monkeypatch.setattr(app.work_orchestrator, "_rollback_transaction", lost_fence)
            monkeypatch.setattr(app.work_orchestrator, "_schedule_recovery_retry", recovery_scheduled.set)
            monkeypatch.setattr(app.artifacts, "put", track_artifact)
        if no_failure_artifact:
            original_put = app.artifacts.put
            def no_failure_report(text, *, kind, **kwargs):
                if kind == "work-failure":
                    if invalid_failure_artifact:
                        return "\x00invalid"
                    raise OSError("artifact storage unavailable")
                return original_put(text, kind=kind, **kwargs)
            monkeypatch.setattr(app.artifacts, "put", no_failure_report)
        if no_handoff_artifact:
            original_put = app.artifacts.put
            def no_partial_artifact(text, *, kind, **kwargs):
                if kind in {"work-partial", "work-needs-agent"}:
                    return "   " if blank_handoff_artifact else None
                return original_put(text, kind=kind, **kwargs)
            monkeypatch.setattr(app.artifacts, "put", no_partial_artifact)
        store = app.work_orchestrator.verification_store.task_store
        task = store.create(GoalContract(goal="change", acceptance_criteria=("pytest tests pass",)),
                            ScopeContext(task_id="task"), task_id="task", actor="owner", repo_root=str(root))
        store.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="owner", idempotency_key="start")
        rollback_calls = []
        if ending == "cancel_during_failure_conflict":
            original_fail = app.work_orchestrator._fail_if_not_cancelled
            def cancel_before_failure(work_id, result, **kwargs):
                assert app.work_orchestrator.cancel(work_id)["success"] is True
                return original_fail(work_id, result, **kwargs)
            monkeypatch.setattr(app.work_orchestrator, "_fail_if_not_cancelled", cancel_before_failure)
        if ending in {"cancel_after_rollback", "cancel_after_budget_rollback"}:
            original_terminal = app.work_orchestrator._set_terminal_if_not_cancelled
            original_rollback = app.work_orchestrator._rollback_transaction
            def cancel_before_terminal(work_id, state, result, **kwargs):
                if state == ("partial" if ending == "cancel_after_budget_rollback" else "needs_agent"):
                    assert app.work_orchestrator.cancel(work_id)["success"] is True
                return original_terminal(work_id, state, result, **kwargs)
            def count_rollback(*args, **kwargs):
                rollback_calls.append(1)
                return original_rollback(*args, **kwargs)
            monkeypatch.setattr(app.work_orchestrator, "_set_terminal_if_not_cancelled", cancel_before_terminal)
            monkeypatch.setattr(app.work_orchestrator, "_rollback_transaction", count_rollback)
        if ending == "cancel_conflict_no_artifact":
            original_put = app.artifacts.put
            def no_cancellation_artifact(text, *, kind, **kwargs):
                if kind == "work-cancellation":
                    return "   " if blank_cancellation_artifact else None
                return original_put(text, kind=kind, **kwargs)
            monkeypatch.setattr(app.artifacts, "put", no_cancellation_artifact)
        if ending in {"conflict_unknown", "cancel_conflict_unknown"}:
            original_rollback = app.work_orchestrator._rollback_transaction
            original_get = store.get
            fail_next_get = [False]
            def unavailable_once(task_id):
                if fail_next_get[0]:
                    fail_next_get[0] = False
                    raise OSError("task generation temporarily unavailable")
                return original_get(task_id)
            def fail_generation_lookup_after_conflict(*args, **kwargs):
                try:
                    return original_rollback(*args, **kwargs)
                except Exception:
                    fail_next_get[0] = True
                    raise
            monkeypatch.setattr(store, "get", unavailable_once)
            monkeypatch.setattr(app.work_orchestrator, "_rollback_transaction", fail_generation_lookup_after_conflict)
        calls = []
        review_entered = threading.Event()
        def delegate(_args, **_kwargs):
            calls.append(1)
            if len(calls) == 1:
                steps = [
                    {"id": "edit", "kind": "edit", "task": "change", "depends_on": []},
                    {"id": "validate", "kind": "validate", "task": "pytest tests pass", "depends_on": ["edit"]},
                    {"id": "review", "kind": "review", "task": "review", "depends_on": ["validate"]}]
                if ending in {"budget", "cancel_after_budget_rollback"}:
                    steps.append({"id": "integrate", "kind": "integrate", "task": "integrate", "depends_on": ["review"]})
                return {"success": True, "text": json.dumps({"summary": "change", "steps": steps})}
            return {"success": True, "text": "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new" + ("x" * 40000 if large_patch else "") + "\n"}
        monkeypatch.setattr(app.services, "delegate_repo", delegate)
        def review(*_a, **kwargs):
            if ending in {"conflict", "conflict_unknown", "cancel_conflict", "cancel_conflict_unknown", "cancel_conflict_no_artifact", "cancel_during_failure_conflict"}:
                (root / "a.txt").write_text("foreign change\n", encoding="utf-8")
            if ending in {"failure", "conflict", "conflict_unknown", "cancel_during_failure_conflict", "rollback_lost_fence"}:
                if no_failure_artifact:
                    raise RuntimeError("review failure " + "x" * 500)
                return {"success": False, "error": "unavailable"}
            if ending in {"cancel", "cancel_conflict", "cancel_conflict_unknown", "cancel_conflict_no_artifact"}:
                review_entered.set()
                assert kwargs["cancel_event"].wait(15)
                return {"success": False, "cancelled": True}
            if ending in {"budget", "cancel_after_budget_rollback", "final_handoff_no_artifact"}:
                return {"success": True, "text": json.dumps({"passed": True, "summary": "checked",
                    "criteria": [{"criterion": "pytest tests pass", "passed": True}], "risks": []})}
            return {"success": True, "text": json.dumps({
                "passed": False, "needs_agent": True, "summary": "needs a decision", "question": "Which?", "risks": []})}
        monkeypatch.setattr(app.services, "second_opinion", review)
        budget = {"max_steps": 8, "max_seconds": 90}
        if ending in {"budget", "cancel_after_budget_rollback"}:
            budget["max_llm_calls"] = 3
        submitted = app.work_orchestrator.submit({"root": str(root), "task": "change", "task_id": task.task_id,
            "mode": "bounded", "acceptance_criteria": ["pytest tests pass"], "allowed_paths": ["a.txt"],
            "approved_commands": ["python -m pytest -q test_sample.py"], "budget": budget,
            "permissions": {"edit": True, "tests": True, "build": True}})
        assert submitted["success"] is True
        if ending == "rollback_lost_fence":
            assert finished.wait(30)
            assert "work-failure" not in artifact_kinds
            assert app.work_orchestrator.status(submitted["work_id"])["status"] != "failed"
            assert app.work_orchestrator._load_journal(submitted["work_id"])
            assert recovery_scheduled.is_set()
            if cancel_lost_fence:
                assert app.work_orchestrator.cancel(submitted["work_id"])["success"] is True
            monkeypatch.setattr(app.work_orchestrator, "_rollback_transaction", original_rollback)
            successor = app.work_orchestrator.fencing_store.claim_attempt(
                str(root), submitted["work_id"], "live-successor", ttl_seconds=60,
                coordination_id=app.work_orchestrator._coordination_id(root))
            try:
                app.work_orchestrator._recover()
                assert app.work_orchestrator.status(submitted["work_id"])["status"] == "executing"
                assert app.work_orchestrator._load_journal(submitted["work_id"])
                assert (root / "a.txt").read_text(encoding="utf-8").strip() == "new"
            finally:
                app.work_orchestrator.fencing_store.release_attempt(successor)
            app.work_orchestrator._recover()
            recovered = app.work_orchestrator.status(submitted["work_id"])
            assert recovered["status"] == ("cancelled" if cancel_lost_fence else "needs_agent") and recovered["success"] is False, recovered
            assert recovered["outcome_unknown"] is True
            assert recovered["requires_primary_review"] is True
            minimal = app.work_orchestrator.get(submitted["work_id"], profile="minimal", return_fields=["summary"], max_output_tokens=128)
            assert minimal["outcome_unknown"] is True
            from local_ai_hub import mcp_server
            assert mcp_server._compact(minimal, "status")["outcome_unknown"] is True
            assert not app.work_orchestrator._has_queued_work()
            assert len(calls) == 2
            if not cancel_lost_fence:
                resumed = app.work_orchestrator.continue_work(submitted["work_id"], "continue")
                assert resumed["success"] is False, resumed
                assert "unknown" in resumed["error"]
                assert app.work_orchestrator.status(submitted["work_id"])["status"] == "needs_agent"
            assert (root / "a.txt").read_text(encoding="utf-8").strip() == "old"
            assert app.work_orchestrator._load_journal(submitted["work_id"]) == []
            return
        if ending in {"cancel", "cancel_conflict", "cancel_conflict_unknown", "cancel_conflict_no_artifact"}:
            assert review_entered.wait(30)
            assert app.work_orchestrator.cancel(submitted["work_id"])["success"] is True
        handoff = wait_terminal(app.work_orchestrator, submitted["work_id"], timeout=10 if ending.startswith("cancel_conflict") else 40)
        if ending == "final_handoff_no_artifact":
            assert handoff["status"] == "failed" and handoff["success"] is False
            assert "handoff artifact unavailable" in handoff["error"]
            report = json.loads(app.artifacts.get(handoff["artifact_id"], max_chars=30000)["text"])
            assert report["stale_verification_receipts"]
            assert report["verification_receipts"] == []
            assert (root / "a.txt").read_text(encoding="utf-8").strip() == "old"
            assert "_pending_fenced_work" not in store.get(task.task_id).checkpoint.state_data
            assert store.get(task.task_id).verification_receipts == {}
            return
        assert handoff["status"] == {"needs_agent": "needs_agent", "failure": "failed", "cancel": "cancelled", "budget": "partial", "conflict": "failed", "conflict_unknown": "failed", "cancel_conflict": "cancelled", "cancel_conflict_unknown": "cancelled", "cancel_conflict_no_artifact": "cancelled", "cancel_after_rollback": "cancelled", "cancel_after_budget_rollback": "cancelled", "cancel_during_failure_conflict": "cancelled"}[ending], handoff
        if no_failure_artifact and ending == "failure":
            assert "failure artifact unavailable" in handoff["error"]
            minimal = app.work_orchestrator.get(submitted["work_id"], profile="minimal", max_output_tokens=128)
            assert "failure artifact unavailable" in minimal["error"]
            assert not handoff.get("artifact_id")
            assert handoff["verification_receipts"] == []
            assert (root / "a.txt").read_text(encoding="utf-8").strip() == "old"
            return
        if ending == "cancel_during_failure_conflict":
            assert handoff["rollback_status"] == "reconciliation_required"
            assert handoff["task_barrier_status"] == "reconciliation_required"
            assert handoff["verification_receipts"] == []
            if no_failure_artifact:
                assert not handoff.get("artifact_id")
                assert "failure artifact unavailable" in handoff["error"]
                minimal = app.work_orchestrator.get(submitted["work_id"], profile="minimal", max_output_tokens=128)
                assert "failure artifact unavailable" in minimal["error"]
                assert minimal["rollback_status"] == "reconciliation_required"
                selected = app.work_orchestrator.get(submitted["work_id"], return_fields=["summary"], max_output_tokens=128)
                assert selected["rollback_status"] == "reconciliation_required"
                assert selected["task_barrier_status"] == "reconciliation_required"
                from local_ai_hub import mcp_server
                wire = mcp_server._compact(minimal, "status")
                assert wire["rollback_status"] == "reconciliation_required"
                assert wire["task_barrier_status"] == "reconciliation_required"
                token = mcp_server._CURRENT_RESPONSE_OPTIONS.set({"action": "get", "tool": "local_ai_work", "max_response_tokens": 128, "response_profile": "minimal"})
                try:
                    tight = mcp_server._compact(minimal, "status")
                finally:
                    mcp_server._CURRENT_RESPONSE_OPTIONS.reset(token)
                assert (tight.get("rollback_status") == "reconciliation_required"
                        or tight.get("response_budget", {}).get("rejected") is True)
            else:
                assert handoff["artifact_id"]
                report = json.loads(app.artifacts.get(handoff["artifact_id"], max_chars=30000)["text"])
                assert report["rollback_error"]
                assert report["stale_verification_receipts"]
                assert any(item.get("receipt_status") == "stale" for item in report["validation"])
            assert (root / "a.txt").read_text(encoding="utf-8").strip() == "foreign change"
            assert app.work_orchestrator._load_journal(submitted["work_id"])
            assert "_pending_fenced_work" in store.get(task.task_id).checkpoint.state_data
            return
        if no_handoff_artifact:
            assert handoff["error"] == "work handoff artifact unavailable"
            assert not handoff.get("artifact_id")
            assert handoff["rolled_back"] is True
            assert (root / "a.txt").read_text(encoding="utf-8").strip() == "old"
            assert store.get(task.task_id).verification_receipts == {}
            return
        if ending == "cancel_conflict_no_artifact":
            assert handoff["error"] == "cancellation validation artifact unavailable"
            assert handoff["rollback_status"] == "reconciliation_required"
            assert handoff["task_barrier_status"] == "reconciliation_required"
            assert handoff["verification_receipts"] == []
            assert app.work_orchestrator._load_journal(submitted["work_id"])
            assert "_pending_fenced_work" in store.get(task.task_id).checkpoint.state_data
            assert (root / "a.txt").read_text(encoding="utf-8").strip() == "foreign change"
            return
        report = handoff if ending in {"needs_agent", "budget"} else json.loads(app.artifacts.get(handoff["artifact_id"], max_chars=30000)["text"])
        assert report["rolled_back"] is (ending not in {"conflict", "conflict_unknown", "cancel_conflict", "cancel_conflict_unknown"})
        assert (root / "a.txt").read_text(encoding="utf-8").strip() == ("foreign change" if ending in {"conflict", "conflict_unknown", "cancel_conflict", "cancel_conflict_unknown"} else "old")
        if ending in {"needs_agent", "budget"}:
            minimal = app.work_orchestrator.get(submitted["work_id"], profile="minimal", max_output_tokens=128)
            assert minimal.get("artifact_id"), minimal
            chunks = []
            offset = 0
            while offset is not None:
                artifact = app.artifacts.get(minimal["artifact_id"], offset=offset, max_chars=8000)
                assert artifact["success"] is True
                chunks.append(artifact["text"])
                offset = artifact["next_offset"]
            if large_patch:
                assert len(chunks) > 1
            detail = json.loads("".join(chunks))
            assert detail["validation"] and detail["applied_patches"]
            assert "+new" in detail["applied_patches"][0]["patch"]
            assert detail["applied_patches"][0]["truncated"] is large_patch
            if large_patch:
                from local_ai_hub import mcp_server
                wire_chunks = []
                offset = 0
                while offset is not None:
                    page = app.artifacts.get(minimal["artifact_id"], offset=offset, max_chars=512)
                    wire = mcp_server._compact(page, "artifact")
                    assert wire["success"] is True
                    assert wire["text"] == page["text"]
                    assert wire["next_offset"] == page["next_offset"]
                    wire_chunks.append(wire["text"])
                    offset = wire["next_offset"]
                assert json.loads("".join(wire_chunks)) == detail
        if ending in {"conflict", "conflict_unknown", "cancel_conflict", "cancel_conflict_unknown"}:
            assert handoff["task_barrier_status"] == "reconciliation_required"
            assert handoff["rollback_status"] == "reconciliation_required"
            assert app.work_orchestrator._load_journal(submitted["work_id"])
            assert "_pending_fenced_work" in store.get(task.task_id).checkpoint.state_data
        evidence = [item for item in report["validation"] if item.get("receipt_ids")]
        assert evidence and all(item["receipt_status"] == ("unknown" if ending in {"conflict_unknown", "cancel_conflict_unknown"} else "stale") for item in evidence)
        if ending in {"failure", "conflict", "conflict_unknown"}:
            assert report["verification_receipts"] == []
        if ending in {"failure", "cancel", "budget", "conflict", "cancel_conflict", "cancel_after_rollback", "cancel_after_budget_rollback"}:
            assert report["stale_verification_receipts"]
        if ending in {"conflict_unknown", "cancel_conflict_unknown"}:
            assert report["uncertain_verification_receipts"]
        if ending in {"cancel", "cancel_conflict", "cancel_conflict_unknown", "cancel_after_rollback", "cancel_after_budget_rollback"}:
            assert handoff["verification_receipts"] == []
        if ending in {"cancel_after_rollback", "cancel_after_budget_rollback"}:
            assert len(rollback_calls) == 1
        assert store.get(task.task_id).checkpoint.state_data["mutation_generation"] == 2
        assert store.get(task.task_id).verification_receipts == {}
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
