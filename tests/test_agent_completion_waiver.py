from pathlib import Path
from dataclasses import replace

import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import CompletionGateError, GoalContract, TaskStatus, TaskStore
from local_ai_hub.agent_verification import VerificationStore
from local_ai_hub.verification_rules import complete_task_with_project_rules


def test_completion_requires_explicit_operator_waiver(tmp_path: Path) -> None:
    store = TaskStore(AgentStateStore(str(tmp_path / "state.db")))
    task = store.create(
        GoalContract(goal="Example", acceptance_criteria=("tests pass",)),
        ScopeContext(repository_id="example"),
        repo_root=str(tmp_path),
    )
    with pytest.raises(CompletionGateError):
        store.complete(task.task_id)

    completed = store.complete(
        task.task_id,
        actor=task.owner,
        idempotency_key="waiver-1",
        operator_waiver={"consent": True, "reason": "User explicitly requested closure without receipts"},
    )
    assert completed.status is TaskStatus.COMPLETED
    assert completed.verification_receipts == {}
    waiver = completed.checkpoint.state_data["completion_waiver"]
    assert waiver["reason"] == "User explicitly requested closure without receipts"
    assert waiver["unverified_criteria"] == ["tests pass"]
    repeated = store.complete(
        task.task_id, actor=task.owner,
        idempotency_key="waiver-1",
        operator_waiver={"consent": True, "reason": "User explicitly requested closure without receipts"},
    )
    assert repeated.status is TaskStatus.COMPLETED


@pytest.mark.parametrize("waiver", [None, {}, {"consent": False, "reason": "x"}, {"consent": True, "reason": " "}])
def test_completion_rejects_invalid_waiver(tmp_path: Path, waiver: object) -> None:
    store = TaskStore(AgentStateStore(str(tmp_path / "state.db")))
    task = store.create(
        GoalContract(goal="Example", acceptance_criteria=("tests pass",)),
        ScopeContext(repository_id="example"),
        repo_root=str(tmp_path),
    )
    with pytest.raises((ValueError, CompletionGateError)):
        store.complete(task.task_id, actor=task.owner, operator_waiver=waiver)
    assert store.get(task.task_id).status is not TaskStatus.COMPLETED


def test_project_completion_preserves_unverified_result(tmp_path: Path) -> None:
    store = TaskStore(AgentStateStore(str(tmp_path / "state.db")))
    verification = VerificationStore(store.state_store, task_store=store)
    store.set_verification_store(verification)
    task = store.create(
        GoalContract(goal="Example", acceptance_criteria=("tests pass",)),
        ScopeContext(repository_id="example"),
        repo_root=str(tmp_path),
    )
    completed = complete_task_with_project_rules(
        store, verification, task.task_id, root=tmp_path, state_dir=tmp_path,
        current_revision="revision", actor=task.owner,
        operator_waiver={"consent": True, "reason": "Explicit request"},
    )
    assert completed.status is TaskStatus.COMPLETED
    assert completed.verification_receipts == {}
    assert verification.completion(task.task_id).complete is False


def test_mcp_forwards_explicit_waiver(monkeypatch: pytest.MonkeyPatch) -> None:
    from local_ai_hub import mcp_server

    observed = {}

    def coord(**kwargs):
        observed.update(kwargs)
        return {"success": True}

    monkeypatch.setattr(mcp_server.CLIENT, "coord", coord)
    waiver = {"consent": True, "reason": "Explicit user instruction"}
    mcp_server.local_ai_coord(action="task_complete", task_id="t1", operator_waiver=waiver)
    assert observed["operator_waiver"] == waiver


def test_waiver_does_not_bypass_pending_fenced_work(tmp_path: Path) -> None:
    store = TaskStore(AgentStateStore(str(tmp_path / "state.db")))
    task = store.create(
        GoalContract(goal="Example", acceptance_criteria=("tests pass",)),
        ScopeContext(repository_id="example"), repo_root=str(tmp_path),
    )
    pending = replace(task, checkpoint=replace(
        task.checkpoint,
        state_data={**task.checkpoint.state_data, "_pending_fenced_work": {"work_id": "w1"}},
    ))
    with pytest.raises(CompletionGateError, match="fenced work"):
        store._verify_completion(pending, _waive_receipts=True)
