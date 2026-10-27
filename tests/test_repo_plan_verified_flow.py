"""Regressions for actual execution authority versus repository declarations."""

from pathlib import Path
import hashlib
import json
import multiprocessing
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_tasks import GoalContract, ScopeContext, TaskStatus, TaskStore
from local_ai_hub.agent_verification import VerificationStore
from local_ai_hub.artifacts import ArtifactStore
from local_ai_hub.repo_plan import agent_bridge
from local_ai_hub.repo_plan.storage import RepoPlanStorage
from local_ai_hub.repo_plan.workspace import RepoPlanWorkspace


def _bind_from_process(root, state_path, task_id, revision, start, outcomes):
    store = TaskStore(AgentStateStore(state_path))
    outcomes.put(("ready", task_id))
    if not start.wait(15):
        outcomes.put(("error", "start timeout"))
        return
    try:
        result = agent_bridge.bind_plan_execution(
            store, root=root, task_id=task_id, plan_id="plan_work",
            plan_task_id="task_work", expected_revision=revision,
        )
        outcomes.put(("success", result["success"]))
    except Exception as error:
        outcomes.put(("error", str(error)))


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


def test_terminal_history_does_not_hide_an_active_plan_binding(environment):
    root, tasks, _, _, _, _, _, revision = environment
    tasks.transition("execution_a", TaskStatus.CANCELLED, reason="superseded", actor="agent_a", idempotency_key="dispose-a")
    for name in ("b", "c"):
        tasks.create(
            GoalContract(goal="Verify real work", acceptance_criteria=["tests pass"]),
            context=ScopeContext(repository_id=str(root), session_id=f"session_{name}"),
            actor=f"agent_{name}", repo_root=str(root), task_id=f"execution_{name}",
        )
    revision = RepoPlanWorkspace(root).get_plan("plan_work")["file_revision"]
    assert agent_bridge.bind_plan_execution(
        tasks, root=root, task_id="execution_b", plan_id="plan_work",
        plan_task_id="task_work", expected_revision=revision,
    )["success"] is True
    with pytest.raises(ValueError, match="active execution binding"):
        agent_bridge.bind_plan_execution(
            tasks, root=root, task_id="execution_c", plan_id="plan_work",
            plan_task_id="task_work", expected_revision=revision,
        )


def test_unknown_prior_binding_requires_reconciliation(environment, monkeypatch):
    root, tasks, _, _, _, _, _, revision = environment
    tasks.create(
        GoalContract(goal="Verify real work", acceptance_criteria=["tests pass"]),
        context=ScopeContext(repository_id=str(root), session_id="session_b"),
        actor="agent_b", repo_root=str(root), task_id="execution_b",
    )
    original_get = tasks.get
    monkeypatch.setattr(tasks, "get", lambda task_id: None if task_id == "execution_a" else original_get(task_id))
    with pytest.raises(ValueError, match="unresolved prior binding"):
        agent_bridge.bind_plan_execution(
            tasks, root=root, task_id="execution_b", plan_id="plan_work",
            plan_task_id="task_work", expected_revision=revision,
        )


def test_failed_attempt_remains_reserved_because_it_can_resume(environment):
    root, tasks, _, _, _, _, _, _ = environment
    tasks.fail("execution_a", reason="retry possible", actor="agent_a")
    tasks.create(
        GoalContract(goal="Verify real work", acceptance_criteria=["tests pass"]),
        context=ScopeContext(repository_id=str(root), session_id="session_b"),
        actor="agent_b", repo_root=str(root), task_id="execution_b",
    )
    revision = RepoPlanWorkspace(root).get_plan("plan_work")["file_revision"]
    with pytest.raises(ValueError, match="failed execution binding"):
        agent_bridge.bind_plan_execution(
            tasks, root=root, task_id="execution_b", plan_id="plan_work",
            plan_task_id="task_work", expected_revision=revision,
        )


def test_stale_manager_does_not_overwrite_another_binding_update(environment):
    root, _, _, _, _, manager, _, _ = environment
    stale_manager = agent_bridge.TaskBindingManager(root)
    manager.bind_task("execution_a", "plan_work", "task_work",
                      ".local-ai-hub/plans/plan_work.plan.json", contract_revision=2)
    stale_manager.bind_task("execution_b", "plan_work", "other_task",
                            ".local-ai-hub/plans/plan_work.plan.json")
    fresh = agent_bridge.TaskBindingManager(root)
    assert fresh.get_binding("execution_a").contract_revision == 2
    assert fresh.get_binding("execution_b") is not None
    with pytest.raises(ValueError, match="contract revision"):
        stale_manager.bind_task("execution_a", "plan_work", "task_work",
                                ".local-ai-hub/plans/plan_work.plan.json", contract_revision=1)


def test_concurrent_plan_bindings_only_allow_one_active_execution(environment):
    root, tasks, _, _, _, _, _, _ = environment
    tasks.transition("execution_a", TaskStatus.CANCELLED, reason="superseded", actor="agent_a", idempotency_key="dispose-a")
    for name in ("b", "c"):
        tasks.create(
            GoalContract(goal="Verify real work", acceptance_criteria=["tests pass"]),
            context=ScopeContext(repository_id=str(root), session_id=f"session_{name}"),
            actor=f"agent_{name}", repo_root=str(root), task_id=f"execution_{name}",
        )
    revision = RepoPlanWorkspace(root).get_plan("plan_work")["file_revision"]
    barrier = Barrier(2)

    def attempt(name):
        barrier.wait(timeout=10)
        try:
            return agent_bridge.bind_plan_execution(
                tasks, root=root, task_id=f"execution_{name}", plan_id="plan_work",
                plan_task_id="task_work", expected_revision=revision,
            )["success"]
        except ValueError as error:
            assert "active execution binding" in str(error)
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ("b", "c")))
    assert sorted(results) == [False, True]


def test_separate_processes_cannot_bind_two_active_attempts(environment):
    root, tasks, _, _, _, _, _, _ = environment
    tasks.transition("execution_a", TaskStatus.CANCELLED, reason="superseded", actor="agent_a", idempotency_key="dispose-a")
    for name in ("b", "c"):
        tasks.create(
            GoalContract(goal="Verify real work", acceptance_criteria=["tests pass"]),
            context=ScopeContext(repository_id=str(root), session_id=f"session_{name}"),
            actor=f"agent_{name}", repo_root=str(root), task_id=f"execution_{name}",
        )
    revision = RepoPlanWorkspace(root).get_plan("plan_work")["file_revision"]
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    outcomes = context.Queue()
    processes = [context.Process(target=_bind_from_process, args=(
        str(root), str(root.parent / "state.db"), f"execution_{name}", revision, start, outcomes,
    )) for name in ("b", "c")]
    try:
        for process in processes:
            process.start()
        assert [outcomes.get(timeout=30)[0] for _ in processes] == ["ready", "ready"]
        start.set()
        results = [outcomes.get(timeout=30) for _ in processes]
        for process in processes:
            process.join(timeout=10)
            assert process.exitcode == 0
        assert sum(kind == "success" and value is True for kind, value in results) == 1
        assert sum(kind == "error" and "active execution binding" in value for kind, value in results) == 1
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=10)
        outcomes.close()
        outcomes.join_thread()


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
