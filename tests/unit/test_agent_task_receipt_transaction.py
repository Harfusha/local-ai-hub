from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
import time

import pytest

from local_ai_hub import agent_tasks, sqlite_support
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import GoalContract, TaskStore


def test_task_projection_writes_keep_filesystem_io_outside_sqlite_transactions(
    tmp_path, monkeypatch
):
    state_store = AgentStateStore(tmp_path / "state.sqlite3")
    store = TaskStore(state_store)
    task_id = "task-transaction-boundary"
    transaction_active = False
    original_transaction = agent_tasks.write_transaction

    @contextmanager
    def _tracked_transaction(con, **kwargs):
        nonlocal transaction_active
        with original_transaction(con, **kwargs):
            transaction_active = True
            try:
                yield con
            finally:
                transaction_active = False

    monkeypatch.setattr(agent_tasks, "write_transaction", _tracked_transaction)

    for name in ("open", "read_text", "write_text", "unlink", "replace", "mkdir", "stat"):
        original = getattr(Path, name)

        def _guarded(path, *args, _original=original, _name=name, **kwargs):
            if transaction_active:
                raise AssertionError(f"filesystem operation {_name} ran inside a SQLite write transaction")
            return _original(path, *args, **kwargs)

        monkeypatch.setattr(Path, name, _guarded)

    store.create(
        GoalContract(goal="Create safely", acceptance_criteria=("criterion",)),
        ScopeContext(repository_id="repo-1", task_id=task_id),
        task_id=task_id,
    )
    store.transition(
        task_id,
        agent_tasks.TaskStatus.ACTIVE,
        reason="start task",
        actor="agent",
        idempotency_key="start-task",
    )


@pytest.mark.parametrize("operation", ["create", "update"])
def test_task_projection_write_timeout_rolls_back_slow_index_work(
    tmp_path, monkeypatch, operation
):
    state_store = AgentStateStore(tmp_path / "state.sqlite3")
    store = TaskStore(state_store)
    task_id = f"task-slow-{operation}"
    if operation == "update":
        store.create(
            GoalContract(goal="Update safely", acceptance_criteria=("criterion",)),
            ScopeContext(repository_id="repo-1", task_id=task_id),
            task_id=task_id,
        )

    refresh_index = store._refresh_task_search_index

    def _slow_refresh(con, indexed_task_id):
        refresh_index(con, indexed_task_id)
        time.sleep(0.30)

    monkeypatch.setattr(store, "_refresh_task_search_index", _slow_refresh)
    with pytest.raises(TimeoutError, match="duration budget"):
        if operation == "create":
            store.create(
                GoalContract(goal="Create safely", acceptance_criteria=("criterion",)),
                ScopeContext(repository_id="repo-1", task_id=task_id),
                task_id=task_id,
            )
        else:
            store.transition(
                task_id,
                agent_tasks.TaskStatus.ACTIVE,
                reason="start task",
                actor="agent",
                idempotency_key="start-task",
            )

    current = store.get(task_id)
    assert (current is None) if operation == "create" else current.status is agent_tasks.TaskStatus.PLANNED
    events = state_store.events(f"task:{task_id}")
    if operation == "create":
        assert events == []
    else:
        assert not [event for event in events if event.kind != "task.created"]


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
        kwargs.pop("max_duration_seconds", None)
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
        kwargs.pop("max_duration_seconds", None)
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


def test_task_create_idempotent_replay_leaves_commit_to_transaction_owner(tmp_path):
    state_store = AgentStateStore(tmp_path / "state.sqlite3")
    store = TaskStore(state_store)
    contract = GoalContract(goal="Replay safely", acceptance_criteria=("criterion",))
    context = ScopeContext(repository_id="repo-1", task_id="task-create-replay")

    first = store.create(
        contract, context, task_id="task-create-replay", idempotency_key="create-once"
    )
    event = state_store.events("task:task-create-replay")[0]
    replay = store._commit_create(first, event)

    assert replay == first
    assert len(state_store.events("task:task-create-replay")) == 1


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
        kwargs.pop("max_duration_seconds", None)
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
