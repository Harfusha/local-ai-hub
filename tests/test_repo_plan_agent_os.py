"""Unit tests for Agent OS task binding, checkpoint sync, contract revisions, and authentic native receipts."""

import pytest

from local_ai_hub.agent_tasks import GoalContract, ScopeContext, TaskStore
from local_ai_hub.agent_verification import (
    VerificationStore,
    evaluate_completion_receipts,
)
from local_ai_hub.artifacts import ArtifactStore
from local_ai_hub.repo_plan import RepoPlanStorage
from local_ai_hub.repo_plan.agent_bridge import (
    TaskBindingManager,
    reconcile_contract_revision,
    record_authentic_native_receipt,
    sync_checkpoint_to_plan,
)
from local_ai_hub.services import AgentStateStore


@pytest.fixture
def test_environment(tmp_path):
    plans_dir = tmp_path / ".local-ai-hub" / "plans"
    plans_dir.mkdir(parents=True)
    intents_dir = tmp_path / ".local-ai-hub" / "local" / "intents"
    storage = RepoPlanStorage(tmp_path, intents_dir=intents_dir)

    db_path = tmp_path / "state.db"
    state_store = AgentStateStore(db_path)
    task_store = TaskStore(state_store)
    artifact_store = ArtifactStore(tmp_path / "artifacts")
    verif_store = VerificationStore(
        state_store,
        task_store=task_store,
        artifact_store=artifact_store,
    )
    binding_manager = TaskBindingManager(tmp_path)

    return tmp_path, storage, state_store, task_store, artifact_store, verif_store, binding_manager


def create_initial_plan_file(storage: RepoPlanStorage, rel_path: str):
    plan_dict = {
        "schema_version": 1,
        "id": "plan_workflow",
        "title": "Agent Workflow Plan",
        "description": "Integration testing",
        "lifecycle": "active",
        "default_target_ref": "refs/heads/master",
        "spec_refs": [],
        "tasks": {
            "task_core": {
                "title": "Implement core logic",
                "description": "",
                "kind": "code",
                "work_status": "planned",
                "depends_on": [],
                "clarifications": [],
                "acceptance_criteria": [
                    "Core module passes unit tests",
                    "Specification documentation is verified",
                ],
                "next_action": "",
                "blocker": None,
                "deliveries": {
                    "delivery_master": {
                        "target_ref": "refs/heads/master",
                        "accountable_role": "integrator",
                        "disposition": "pending",
                        "reason": "awaiting verification",
                        "results": [],
                    }
                },
            }
        },
    }
    storage.save_plan_file(rel_path, plan_dict)
    return plan_dict


def test_task_binding_lifecycle(test_environment):
    """Test binding Agent OS task to plan file task and persistence."""
    tmp_path, storage, _, _, _, _, binding_manager = test_environment
    rel_path = ".local-ai-hub/plans/workflow.plan.json"
    create_initial_plan_file(storage, rel_path)

    binding = binding_manager.bind_task(
        task_id="agent_task_001",
        plan_id="plan_workflow",
        plan_task_id="task_core",
        plan_rel_path=rel_path,
        contract_revision=1,
    )
    assert binding.task_id == "agent_task_001"
    assert binding.plan_id == "plan_workflow"

    # Reload from disk
    new_manager = TaskBindingManager(tmp_path)
    found = new_manager.get_binding("agent_task_001")
    assert found is not None
    assert found.plan_task_id == "task_core"


def test_checkpoint_sync_to_plan(test_environment):
    """Test that updating an Agent OS task checkpoint updates the bound plan file."""
    tmp_path, storage, _, _, _, _, binding_manager = test_environment
    rel_path = ".local-ai-hub/plans/workflow.plan.json"
    create_initial_plan_file(storage, rel_path)

    binding = binding_manager.bind_task("task_001", "plan_workflow", "task_core", rel_path)

    # 1. Update to in_progress (active)
    sync_checkpoint_to_plan(
        storage,
        binding,
        agent_status="active",
        phase="implementation",
        next_action="Writing domain models",
        blocker=None,
    )
    data, _ = storage.read_plan_file(rel_path)
    assert data["tasks"]["task_core"]["work_status"] == "in_progress"
    assert data["tasks"]["task_core"]["work_phase"] == "implementation"
    assert data["tasks"]["task_core"]["next_action"] == "Writing domain models"

    # 2. Update to blocked
    sync_checkpoint_to_plan(
        storage,
        binding,
        agent_status="blocked",
        phase="implementation",
        next_action="Waiting for dependency",
        blocker="Service unavailable",
    )
    data, _ = storage.read_plan_file(rel_path)
    assert data["tasks"]["task_core"]["work_status"] == "blocked"
    assert data["tasks"]["task_core"]["blocker"] == "Service unavailable"

    # 3. Update to completed with pending delivery -> status is source_ready
    sync_checkpoint_to_plan(
        storage,
        binding,
        agent_status="completed",
        phase="verification",
        next_action="Merge obligation open",
    )
    data, _ = storage.read_plan_file(rel_path)
    assert data["tasks"]["task_core"]["work_status"] == "source_ready"


def test_contract_revision_reconciliation(test_environment):
    """Test updating contract criteria mid-flight preserves history and appends clarification."""
    tmp_path, storage, _, _, _, _, binding_manager = test_environment
    rel_path = ".local-ai-hub/plans/workflow.plan.json"
    create_initial_plan_file(storage, rel_path)

    binding = binding_manager.bind_task("task_001", "plan_workflow", "task_core", rel_path)

    spec_path = "docs/superpowers/specs/feature.md"
    spec_content = "# Refined Specification\n\nNew acceptance details.\n"
    new_criteria = [
        "Core module passes unit tests",
        "Refined criteria: support concurrent readers",
    ]

    save_res, new_rev = reconcile_contract_revision(
        storage,
        binding,
        new_criteria,
        reason="Operator clarified concurrency requirements during implementation",
        spec_rel_path=spec_path,
        spec_content=spec_content,
    )
    assert save_res["success"] is True
    assert new_rev == 2

    # Check plan file on disk
    data, _ = storage.read_plan_file(rel_path)
    task_data = data["tasks"]["task_core"]
    assert task_data["acceptance_criteria"] == new_criteria
    assert len(task_data["clarifications"]) == 1

    clar = task_data["clarifications"][0]
    assert clar["adoption"] == "adopted"
    assert "concurrency requirements" in clar["summary"]
    assert clar["spec_refs"][0]["path"] == spec_path

    # Check spec file exists
    assert (tmp_path / spec_path).exists()


def test_authentic_native_receipts(test_environment):
    """Test recording authentic native verification receipts for code and doc criteria."""
    tmp_path, storage, state_store, task_store, artifact_store, verif_store, binding_manager = test_environment
    rel_path = ".local-ai-hub/plans/workflow.plan.json"
    create_initial_plan_file(storage, rel_path)

    criteria = [
        "Core module passes unit tests",
        "Specification documentation is verified",
    ]

    # Create Agent OS task contract
    contract = GoalContract(goal="Test Task", acceptance_criteria=tuple(criteria))
    context = ScopeContext(repository_id=str(tmp_path))
    task_state = task_store.create(
        contract,
        context,
        actor="test_agent",
        repo_root=str(tmp_path),
    )
    task_id = task_state.task_id

    binding = binding_manager.bind_task(task_id, "plan_workflow", "task_core", rel_path)

    # 1. Reject fake pass command
    with pytest.raises(ValueError, match="Trivial pass command"):
        record_authentic_native_receipt(
            task_store=task_store,
            verification_store=verif_store,
            artifact_store=artifact_store,
            task_id=task_id,
            criterion=criteria[0],
            command="echo PASS",
            root=tmp_path,
            owner="test_agent",
        )

    # 2. Reject nonzero exit code for test
    with pytest.raises(ValueError, match="Native test command failed"):
        record_authentic_native_receipt(
            task_store=task_store,
            verification_store=verif_store,
            artifact_store=artifact_store,
            task_id=task_id,
            criterion=criteria[0],
            command="pytest tests/unit",
            root=tmp_path,
            owner="test_agent",
            exit_code=1,
        )

    # 3. Reject wrong root
    with pytest.raises(ValueError, match="Root mismatch"):
        record_authentic_native_receipt(
            task_store=task_store,
            verification_store=verif_store,
            artifact_store=artifact_store,
            task_id=task_id,
            criterion=criteria[0],
            command="pytest tests/unit",
            root=tmp_path / "wrong_dir",
            owner="test_agent",
        )

    # 4. Valid native test receipt
    res_test = record_authentic_native_receipt(
        task_store=task_store,
        verification_store=verif_store,
        artifact_store=artifact_store,
        task_id=task_id,
        criterion=criteria[0],
        command="pytest tests/test_core.py -q",
        root=tmp_path,
        owner="test_agent",
        exit_code=0,
        output_summary="10 passed in 0.5s",
        binding=binding,
        plan_storage=storage,
    )
    assert res_test["success"] is True
    assert res_test["evidence_type"] == "test"

    # 5. Valid documentation/inspection receipt
    res_doc = record_authentic_native_receipt(
        task_store=task_store,
        verification_store=verif_store,
        artifact_store=artifact_store,
        task_id=task_id,
        criterion=criteria[1],
        command="git diff --check docs/superpowers/specs/feature.md",
        root=tmp_path,
        owner="test_agent",
        exit_code=0,
        producer="inspection_producer",
        output_summary="Specification reviewed and verified",
        binding=binding,
        plan_storage=storage,
    )
    assert res_doc["success"] is True
    assert res_doc["evidence_type"] == "source_review"

    # 6. Verify that receipts satisfy evaluate_completion_receipts!
    updated_task = task_store.get(task_id)
    assert updated_task.verification_receipts.get(criteria[0]) == res_test["receipt_id"]
    assert updated_task.verification_receipts.get(criteria[1]) == res_doc["receipt_id"]

    receipts = [res_test["receipt"], res_doc["receipt"]]
    assert all(r is not None and r.passed for r in receipts)

    comp_res = evaluate_completion_receipts(
        task_id=task_id,
        required_criteria=criteria,
        receipts=receipts,
        owner="test_agent",
        artifact_store=artifact_store,
        command_execution_record_lookup=verif_store.command_execution_record_lookup,
    )
    assert comp_res.complete is True
