from concurrent.futures import ThreadPoolExecutor

import pytest

from local_ai_hub.repo_plan.schema_validation import RepoPlanConflictError
from local_ai_hub.repo_plan.workspace import RepoPlanWorkspace


def test_mcp_does_not_invent_mutation_outcome_without_storage_evidence(tmp_path, monkeypatch):
    from local_ai_hub import mcp_server
    class Backend:
        def coord(self, **_kwargs):
            return {"success": True, "plan_id": "plan_replay", "task_id": "task_a",
                    "file_revision": "a" * 64, "task": {"title": "A"}}
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server, "CLIENT", Backend())
    result = mcp_server.local_ai_coord(action="plan_task_edit", root=str(tmp_path),
                                      plan_id="plan_replay", task_id="task_a", task_data={"title": "A"})
    assert "mutation_applied" not in result


@pytest.mark.parametrize("action", ["update", "edit"])
def test_retry_returns_original_result_without_overwriting_later_change(tmp_path, action):
    workspace = RepoPlanWorkspace(tmp_path)
    workspace.init_workspace()
    created = workspace.create_plan(plan_id="plan_replay", title="Initial")
    if action == "edit":
        created = workspace.edit_task("plan_replay", "task_a", title="Initial", expected_revision=created["file_revision"])
        invoke = lambda: workspace.edit_task("plan_replay", "task_a", title="First", expected_revision=created["file_revision"], idempotency_key="first")
    else:
        invoke = lambda: workspace.update_plan("plan_replay", title="First", expected_revision=created["file_revision"], idempotency_key="first")
    first = invoke()
    later = workspace.update_plan("plan_replay", description="later", expected_revision=first["file_revision"])
    replay = invoke()
    assert replay == first
    assert workspace.get_plan("plan_replay")["file_revision"] == later["file_revision"]
    assert workspace.get_plan("plan_replay")["plan"]["description"] == "later"


def test_reused_key_with_different_request_rejects(tmp_path):
    workspace = RepoPlanWorkspace(tmp_path)
    workspace.init_workspace()
    initial = workspace.create_plan(plan_id="plan_replay", title="Initial")
    workspace.update_plan("plan_replay", title="First", expected_revision=initial["file_revision"], idempotency_key="same")
    with pytest.raises(RepoPlanConflictError):
        workspace.update_plan("plan_replay", title="Other", expected_revision=initial["file_revision"], idempotency_key="same")


def test_concurrent_identical_requests_are_replayed(tmp_path):
    workspace = RepoPlanWorkspace(tmp_path)
    workspace.init_workspace()
    initial = workspace.create_plan(plan_id="plan_replay", title="Initial")
    def invoke(_):
        return workspace.update_plan("plan_replay", title="First", expected_revision=initial["file_revision"], idempotency_key="same")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(invoke, range(2)))
    assert results[0] == results[1]


def test_noop_replay_retains_original_outcome_after_later_edit(tmp_path):
    workspace = RepoPlanWorkspace(tmp_path)
    workspace.init_workspace()
    initial = workspace.create_plan(plan_id="plan_replay", title="Initial")
    noop = workspace.update_plan("plan_replay", title="Initial", expected_revision=initial["file_revision"], idempotency_key="noop")
    assert noop["no_op"] is True
    later = workspace.update_plan("plan_replay", title="Later", expected_revision=noop["file_revision"])
    replay = workspace.update_plan("plan_replay", title="Initial", expected_revision=initial["file_revision"], idempotency_key="noop")
    assert replay == noop
    assert workspace.get_plan("plan_replay")["file_revision"] == later["file_revision"]


def test_replay_after_crash_recovery_retains_original_result(tmp_path, monkeypatch):
    workspace = RepoPlanWorkspace(tmp_path)
    workspace.init_workspace()
    initial = workspace.create_plan(plan_id="plan_replay", title="Initial")
    original_complete = workspace.storage._complete_intent
    monkeypatch.setattr(workspace.storage, "_complete_intent", lambda _intent: (_ for _ in ()).throw(RuntimeError("crash")))
    with pytest.raises(RuntimeError, match="crash"):
        workspace.update_plan("plan_replay", title="First", expected_revision=initial["file_revision"], idempotency_key="crash")
    monkeypatch.setattr(workspace.storage, "_complete_intent", original_complete)
    workspace.storage.recover_pending_intents()
    replay = workspace.update_plan("plan_replay", title="First", expected_revision=initial["file_revision"], idempotency_key="crash")
    assert replay["plan"]["title"] == "First"
    assert replay["file_revision"] == workspace.get_plan("plan_replay")["file_revision"]


def test_legacy_record_without_client_identity_fails_closed(tmp_path):
    workspace = RepoPlanWorkspace(tmp_path)
    workspace.init_workspace()
    initial = workspace.create_plan(plan_id="plan_replay", title="Initial")
    snapshot = workspace.get_plan("plan_replay")["plan"]
    snapshot["title"] = "First"
    workspace.storage.save_plan_file(".local-ai-hub/plans/plan_replay.plan.json", snapshot,
                                     expected_revision=initial["file_revision"], idempotency_key="legacy")
    with pytest.raises(RepoPlanConflictError, match="unverified request"):
        workspace.update_plan("plan_replay", title="First", expected_revision=initial["file_revision"], idempotency_key="legacy")


def test_corrupted_replay_snapshot_fails_closed(tmp_path):
    workspace = RepoPlanWorkspace(tmp_path)
    workspace.init_workspace()
    initial = workspace.create_plan(plan_id="plan_replay", title="Initial")
    first = workspace.update_plan("plan_replay", title="First", expected_revision=initial["file_revision"], idempotency_key="key")
    path = workspace.storage._request_path("key")
    record = workspace.storage._read_record(path)
    record["result"]["client_plan_snapshot"]["title"] = "Forged"
    workspace.storage._atomic_record(path, record)
    with pytest.raises(RepoPlanConflictError, match="revision does not match"):
        workspace.update_plan("plan_replay", title="First", expected_revision=initial["file_revision"], idempotency_key="key")
    assert workspace.get_plan("plan_replay")["file_revision"] == first["file_revision"]
