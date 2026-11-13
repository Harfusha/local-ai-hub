from __future__ import annotations

from dataclasses import replace

import pytest

from local_ai_hub import agent_tasks, sqlite_support
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import GoalContract, TaskStore


def test_receipt_projection_and_event_roll_back_when_transaction_budget_expires(
    tmp_path, monkeypatch
):
    state_store = AgentStateStore(tmp_path / "state.sqlite3")
    store = TaskStore(state_store)
    task_id = "task-receipt-rollback"
    store.create(
        GoalContract(goal="Record proof", acceptance_criteria=("criterion",)),
        ScopeContext(repository_id="repo-1", task_id=task_id),
        task_id=task_id,
    )

    def _expired_transaction(con, **kwargs):
        return sqlite_support.write_transaction(
            con, max_duration_seconds=1e-12, **kwargs
        )

    monkeypatch.setattr(agent_tasks, "write_transaction", _expired_transaction, raising=False)
    with pytest.raises(TimeoutError, match="duration budget"):
        store.add_verification_receipt(task_id, "criterion", "receipt-1")

    current = store.get(task_id)
    assert current is not None
    assert current.verification_receipts == {}
    events = state_store.events(f"task:{task_id}")
    assert not any(event.kind == "task.verified" for event in events)


def test_task_creation_rolls_back_when_transaction_budget_expires(tmp_path, monkeypatch):
    state_store = AgentStateStore(tmp_path / "state.sqlite3")
    store = TaskStore(state_store)
    task_id = "task-create-rollback"

    def _expired_transaction(con, **kwargs):
        return sqlite_support.write_transaction(
            con, max_duration_seconds=1e-12, **kwargs
        )

    monkeypatch.setattr(agent_tasks, "write_transaction", _expired_transaction, raising=False)
    with pytest.raises(TimeoutError, match="duration budget"):
        store.create(
            GoalContract(goal="Create safely", acceptance_criteria=("criterion",)),
            ScopeContext(repository_id="repo-1", task_id=task_id),
            task_id=task_id,
        )

    assert store.get(task_id) is None
    assert state_store.events(f"task:{task_id}") == []


def test_task_update_rolls_back_when_transaction_budget_expires(tmp_path, monkeypatch):
    state_store = AgentStateStore(tmp_path / "state.sqlite3")
    store = TaskStore(state_store)
    task_id = "task-update-rollback"
    store.create(
        GoalContract(goal="Update safely", acceptance_criteria=("criterion",)),
        ScopeContext(repository_id="repo-1", task_id=task_id),
        task_id=task_id,
    )

    def _expired_transaction(con, **kwargs):
        return sqlite_support.write_transaction(
            con, max_duration_seconds=1e-12, **kwargs
        )

    monkeypatch.setattr(agent_tasks, "write_transaction", _expired_transaction, raising=False)
    with pytest.raises(TimeoutError, match="duration budget"):
        store.transition(
            task_id,
            agent_tasks.TaskStatus.ACTIVE,
            reason="start task",
            actor="agent",
            idempotency_key="start-task",
        )

    current = store.get(task_id)
    assert current is not None
    assert current.status is agent_tasks.TaskStatus.PLANNED
    events = state_store.events(f"task:{task_id}")
    assert not any(event.kind == "task.status_changed" for event in events)


def test_projection_save_rolls_back_when_transaction_budget_expires(tmp_path, monkeypatch):
    state_store = AgentStateStore(tmp_path / "state.sqlite3")
    store = TaskStore(state_store)
    task_id = "task-projection-rollback"
    current = store.create(
        GoalContract(goal="Save safely", acceptance_criteria=("criterion",)),
        ScopeContext(repository_id="repo-1", task_id=task_id),
        task_id=task_id,
    )

    def _expired_transaction(con, **kwargs):
        return sqlite_support.write_transaction(
            con, max_duration_seconds=1e-12, **kwargs
        )

    monkeypatch.setattr(agent_tasks, "write_transaction", _expired_transaction, raising=False)
    with pytest.raises(TimeoutError, match="duration budget"):
        store._save_projection(replace(current, status=agent_tasks.TaskStatus.ACTIVE))

    persisted = store.get(task_id)
    assert persisted is not None
    assert persisted.status is agent_tasks.TaskStatus.PLANNED


def test_same_transition_replay_aborts_when_transaction_budget_expires(tmp_path, monkeypatch):
    state_store = AgentStateStore(tmp_path / "state.sqlite3")
    store = TaskStore(state_store)
    task_id = "task-replay-timeout"
    store.create(
        GoalContract(goal="Replay safely", acceptance_criteria=("criterion",)),
        ScopeContext(repository_id="repo-1", task_id=task_id),
        task_id=task_id,
    )
    transition = {
        "reason": "start task",
        "actor": "agent",
        "idempotency_key": "start-task",
    }
    store.transition(task_id, agent_tasks.TaskStatus.ACTIVE, **transition)

    def _expired_transaction(con, **kwargs):
        return sqlite_support.write_transaction(
            con, max_duration_seconds=1e-12, **kwargs
        )

    monkeypatch.setattr(agent_tasks, "write_transaction", _expired_transaction, raising=False)
    with pytest.raises(TimeoutError, match="duration budget"):
        store.transition(task_id, agent_tasks.TaskStatus.ACTIVE, **transition)

    persisted = store.get(task_id)
    assert persisted is not None
    assert persisted.status is agent_tasks.TaskStatus.ACTIVE
