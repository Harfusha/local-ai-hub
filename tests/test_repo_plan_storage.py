"""Unit tests for repo plan storage, 9-step atomic save protocol, and crash recovery."""

import pytest

from local_ai_hub.repo_plan import (
    OperationIntent,
    RepoPlanConflictError,
    RepoPlanStorage,
)


@pytest.fixture
def temp_workspace(tmp_path):
    plans_dir = tmp_path / ".local-ai-hub" / "plans"
    plans_dir.mkdir(parents=True)
    intents_dir = tmp_path / ".local-ai-hub" / "local" / "intents"
    storage = RepoPlanStorage(tmp_path, intents_dir=intents_dir)
    return tmp_path, storage


def create_sample_plan_dict(plan_id="plan_sample", title="Sample Plan"):
    return {
        "schema_version": 1,
        "id": plan_id,
        "title": title,
        "description": "Durable storage test",
        "lifecycle": "draft",
        "default_target_ref": "refs/heads/master",
        "spec_refs": [],
        "tasks": {
            "task_init": {
                "title": "Initial Task",
                "description": "",
                "kind": "code",
                "work_status": "planned",
                "depends_on": [],
                "clarifications": [],
                "acceptance_criteria": ["Atomic save works"],
                "next_action": "",
                "blocker": None,
            }
        },
    }


def test_clean_save_and_read(temp_workspace):
    """Test saving a new plan file and reading it back."""
    tmp_path, storage = temp_workspace
    rel_path = ".local-ai-hub/plans/sample.plan.json"
    plan_dict = create_sample_plan_dict()

    res = storage.save_plan_file(rel_path, plan_dict, expected_revision="")
    assert res["success"] is True
    assert res["saved"] is True
    assert res["no_op"] is False
    assert len(res["file_revision"]) == 64

    # Read back
    loaded_dict, rev = storage.read_plan_file(rel_path)
    assert loaded_dict["id"] == "plan_sample"
    assert rev == res["file_revision"]


def test_stale_revision_conflict(temp_workspace):
    """Test that saving with a stale revision raises RepoPlanConflictError."""
    tmp_path, storage = temp_workspace
    rel_path = ".local-ai-hub/plans/conflict.plan.json"
    plan_dict = create_sample_plan_dict(plan_id="plan_conflict", title="Rev 1")

    # Initial save
    res1 = storage.save_plan_file(rel_path, plan_dict)
    rev1 = res1["file_revision"]

    # Second update
    plan_dict["title"] = "Rev 2"
    res2 = storage.save_plan_file(rel_path, plan_dict, expected_revision=rev1)
    rev2 = res2["file_revision"]
    assert rev2 != rev1

    # Stale update attempting to use rev1
    plan_dict["title"] = "Rev 3 Stale"
    with pytest.raises(RepoPlanConflictError, match="Content revision conflict"):
        storage.save_plan_file(rel_path, plan_dict, expected_revision=rev1)


def test_no_op_save_does_not_mutate(temp_workspace):
    """Test that saving identical content returns no_op=True without churning file."""
    tmp_path, storage = temp_workspace
    rel_path = ".local-ai-hub/plans/noop.plan.json"
    plan_dict = create_sample_plan_dict(plan_id="plan_noop")

    res1 = storage.save_plan_file(rel_path, plan_dict)
    full_path = tmp_path / rel_path
    mtime1 = full_path.stat().st_mtime_ns

    res2 = storage.save_plan_file(rel_path, plan_dict, expected_revision=res1["file_revision"])
    assert res2["success"] is True
    assert res2["saved"] is True
    assert res2["no_op"] is True
    assert full_path.stat().st_mtime_ns == mtime1


def test_idempotency_key_replay_and_mismatch(temp_workspace):
    """Test idempotency key caches result, and rejects if payload changes."""
    tmp_path, storage = temp_workspace
    rel_path = ".local-ai-hub/plans/idem.plan.json"
    plan_dict = create_sample_plan_dict(plan_id="plan_idem", title="Original")

    key = "idem_key_12345"
    res1 = storage.save_plan_file(rel_path, plan_dict, idempotency_key=key)
    assert res1["success"] is True

    # Replay with same key & same content returns cached result
    res2 = storage.save_plan_file(rel_path, plan_dict, idempotency_key=key)
    assert res2 == res1

    # Replay with same key & DIFFERENT content raises conflict
    plan_dict_different = create_sample_plan_dict(plan_id="plan_idem", title="Changed Content")
    with pytest.raises(RepoPlanConflictError, match="reused with different payload"):
        storage.save_plan_file(rel_path, plan_dict_different, idempotency_key=key)


def test_lease_fencing_preflight(temp_workspace):
    """Test that expired lease stops write in preflight."""
    tmp_path, storage = temp_workspace
    rel_path = ".local-ai-hub/plans/lease.plan.json"
    plan_dict = create_sample_plan_dict(plan_id="plan_lease")

    # Lease check returns False
    with pytest.raises(RepoPlanConflictError, match="Writer lease expired"):
        storage.save_plan_file(rel_path, plan_dict, lease_check_fn=lambda: False)


def test_multi_file_save_spec_and_plan(temp_workspace):
    """Test atomic coordinated save of specification and plan files."""
    tmp_path, storage = temp_workspace
    spec_path = "docs/superpowers/specs/feature.md"
    plan_path = ".local-ai-hub/plans/feature.plan.json"
    spec_content = "# Feature Specification\n\nDetails here.\n"
    plan_dict = create_sample_plan_dict(plan_id="plan_feature", title="Feature Plan")

    res = storage.save_spec_and_plan(
        spec_path,
        spec_content,
        plan_path,
        plan_dict,
        idempotency_key="multi_feat_1",
    )
    assert res["success"] is True
    assert res["saved"] is True
    assert (tmp_path / spec_path).read_text(encoding="utf-8") == spec_content
    loaded_plan, _ = storage.read_plan_file(plan_path)
    assert loaded_plan["id"] == "plan_feature"


def test_recovery_of_intents(temp_workspace):
    """Test recovery manager reconciles already applied and unapplied intents."""
    tmp_path, storage = temp_workspace
    rel_path = ".local-ai-hub/plans/recover.plan.json"
    plan_dict = create_sample_plan_dict(plan_id="plan_recover")

    # 1. Normal save
    res = storage.save_plan_file(rel_path, plan_dict)

    # 2. Simulate pending intent for an operation that actually succeeded
    intent_id = "intent_sim_completed"
    intent = OperationIntent(
        intent_id=intent_id,
        operation="save_plan",
        idempotency_key="k1",
        payload_sha256="payload1",
        owner="agent",
        created_at=1000.0,
        status="pending",
        targets=[
            storage.intents_dir.parent.parent  # dummy, let's use actual IntentTarget
        ],
    )
    from local_ai_hub.repo_plan.storage import IntentTarget
    intent.targets = [
        IntentTarget(rel_path=rel_path, expected_sha256="", candidate_sha256=res["file_revision"])
    ]
    storage._save_intent(intent)

    # Run recovery
    outcomes = storage.recover_pending_intents()
    assert len(outcomes) == 1
    assert outcomes[0]["intent_id"] == intent_id
    assert outcomes[0]["resolution"] == "already_applied"
    assert outcomes[0]["status"] == "completed"


def test_independent_worktrees_isolation(tmp_path):
    """Test that two separate worktrees have independent storages without locking conflicts."""
    wt_a = tmp_path / "wt_a"
    wt_b = tmp_path / "wt_b"
    wt_a.mkdir()
    wt_b.mkdir()

    storage_a = RepoPlanStorage(wt_a)
    storage_b = RepoPlanStorage(wt_b)

    plan_a = create_sample_plan_dict(plan_id="plan_a", title="Plan in Worktree A")
    plan_b = create_sample_plan_dict(plan_id="plan_b", title="Plan in Worktree B")

    res_a = storage_a.save_plan_file(".local-ai-hub/plans/main.plan.json", plan_a)
    res_b = storage_b.save_plan_file(".local-ai-hub/plans/main.plan.json", plan_b)

    assert res_a["success"] is True
    assert res_b["success"] is True

    # Check contents are distinct
    data_a, _ = storage_a.read_plan_file(".local-ai-hub/plans/main.plan.json")
    data_b, _ = storage_b.read_plan_file(".local-ai-hub/plans/main.plan.json")
    assert data_a["id"] == "plan_a"
    assert data_b["id"] == "plan_b"
