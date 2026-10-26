"""Regressions for actual execution authority versus repository declarations."""

from pathlib import Path
import hashlib
import json

import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_tasks import GoalContract, ScopeContext, TaskStore
from local_ai_hub.agent_verification import VerificationStore
from local_ai_hub.artifacts import ArtifactStore
from local_ai_hub.repo_plan import agent_bridge
from local_ai_hub.repo_plan.storage import RepoPlanStorage
from local_ai_hub.repo_plan.workspace import RepoPlanWorkspace


@pytest.fixture
def environment(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    state = AgentStateStore(tmp_path / "state.db")
    tasks = TaskStore(state)
    artifacts = ArtifactStore(tmp_path / "artifacts")
    verifier = VerificationStore(state, task_store=tasks, artifact_store=artifacts)
    tasks.verification_store = verifier
    task = tasks.create(
        GoalContract(goal="Verify real work", acceptance_criteria=["tests pass"]),
        context=ScopeContext(repository_id=str(root), session_id="session_a"),
        actor="agent_a", repo_root=str(root), task_id="execution_a",
    )
    storage = RepoPlanStorage(root)
    rel = ".local-ai-hub/plans/plan_work.plan.json"
    data = {
        "schema_version": 1, "id": "plan_work", "title": "Work",
        "description": "", "lifecycle": "active", "spec_refs": [],
        "default_target_ref": "refs/heads/master",
        "tasks": {"task_work": {
            "title": "Work", "description": "", "kind": "code",
            "work_status": "planned", "depends_on": [], "clarifications": [],
            "acceptance_criteria": ["tests pass"], "next_action": "", "blocker": None,
        }},
    }
    result = storage.save_plan_file(rel, data)
    manager = agent_bridge.TaskBindingManager(root)
    binding = manager.bind_task(task.task_id, "plan_work", "task_work", rel)
    return root, tasks, artifacts, verifier, storage, manager, binding, result["file_revision"]


def test_caller_success_cannot_mint_native_receipt(environment):
    root, tasks, artifacts, verifier, *_ = environment
    with pytest.raises(ValueError, match="command_id|trusted|producer"):
        agent_bridge.record_authentic_native_receipt(
            tasks, verifier, artifacts, "execution_a", "tests pass",
            command="python -m pytest never_executed.py", root=root,
            owner="agent_a",
        )


def test_actual_contract_changes_with_adopted_requirements(environment):
    root, tasks, _, _, storage, _, binding, _ = environment
    result, revision = agent_bridge.reconcile_contract_revision(
        storage, binding, ["tests pass", "new requirement"], "Operator changed scope",
        owner="agent_a", task_store=tasks,
    )
    assert result["success"] is True
    assert revision == 2
    assert tasks.get("execution_a").contract.acceptance_criteria == (
        "tests pass", "new requirement",
    )
    assert tasks.get("execution_a").checkpoint.state_data["contract_revision"] == 2


def test_done_file_does_not_verify_delivery(environment):
    root, _, _, _, storage, _, binding, _ = environment
    data, rev = storage.read_plan_file(binding.plan_rel_path)
    task = data["tasks"]["task_work"]
    task["work_status"] = "done"
    task["deliveries"] = {"delivery_target": {
        "target_ref": "refs/heads/master", "accountable_role": "integrator",
        "disposition": "declared_integrated", "reason": "Claim only", "results": [],
    }}
    storage.save_plan_file(binding.plan_rel_path, data, expected_revision=rev)
    card = RepoPlanWorkspace(root).get_board_view()["columns"]["done"][0]
    assert card["verified"] is False
    assert card["verification_status"] != "verified"


def test_session_binding_is_persisted_and_unambiguous(environment):
    root, tasks, _, _, _, _, _, revision = environment
    result = agent_bridge.bind_plan_execution(
        tasks, root=root, task_id="execution_a", plan_id="plan_work",
        plan_task_id="task_work", expected_revision=revision, session_id="session_a",
    )
    assert result["success"] is True
    manager = agent_bridge.TaskBindingManager(root)
    assert manager.get_session_binding("session_a").task_id == "execution_a"
    assert manager.get_session_binding("other_session") is None


def test_revised_contract_cannot_reuse_old_receipt_mapping(environment):
    _, tasks, _, _, storage, _, binding, _ = environment
    agent_bridge.reconcile_contract_revision(
        storage, binding, ["new requirement"], "New acceptance",
        owner="agent_a", task_store=tasks,
    )
    current = tasks.get("execution_a")
    assert current.contract.acceptance_criteria == ("new requirement",)
    assert "tests pass" not in current.verification_receipts
    history = current.checkpoint.state_data["contract_history"]
    assert history[-1]["contract"]["acceptance_criteria"] == ["tests pass"]


def test_pending_contract_retry_uses_hash_name_and_atomic_scoped_file(environment):
    root, _, _, _, storage, _, binding, _ = environment
    binding.task_id = "../../outside"
    target = agent_bridge._persist_pending_contract_reconciliation(
        storage, binding, {"task_id": binding.task_id, "contract_revision": 2},
    )
    expected_parent = (root / ".local-ai-hub/local/pending-contract-reconciliation").resolve()
    assert target.parent == expected_parent
    assert target.name == hashlib.sha256(binding.task_id.encode()).hexdigest() + ".json"
    assert json.loads(target.read_text(encoding="utf-8"))["task_id"] == binding.task_id
