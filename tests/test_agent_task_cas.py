from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import sqlite3
from threading import Barrier
from contextlib import closing

import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import (
    ConcurrentTaskUpdateError,
    GoalContract,
    TaskCheckpoint,
    TaskStatus,
    TaskStore,
)
from local_ai_hub.sqlite_support import connect_sqlite


def test_competing_transitions_use_compare_and_set(tmp_path):
    state_store = AgentStateStore(tmp_path / "agent-state.sqlite3")
    tasks = TaskStore(state_store)
    task = tasks.create(
        GoalContract(goal="CAS transition"),
        ScopeContext(task_id="cas-task"),
        task_id="cas-task",
    )
    tasks.transition(
        task.task_id,
        TaskStatus.ACTIVE,
        reason="start",
        actor="test",
        idempotency_key="start",
    )
    barrier = Barrier(2)
    original_get = tasks.get

    def transition(target: TaskStatus, key: str):
        try:
            return tasks.transition(
                task.task_id,
                target,
                reason="competing update",
                actor="test",
                idempotency_key=key,
            )
        except ConcurrentTaskUpdateError as exc:
            return exc

    def synchronized_get(task_id: str):
        snapshot = original_get(task_id)
        barrier.wait(timeout=2)
        return snapshot

    tasks.get = synchronized_get
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(
            pool.map(
                lambda pair: transition(*pair),
                ((TaskStatus.WAITING, "wait"), (TaskStatus.BLOCKED, "block")),
            )
        )
    tasks.get = original_get

    successes = [outcome for outcome in outcomes if not isinstance(outcome, Exception)]
    conflicts = [outcome for outcome in outcomes if isinstance(outcome, ConcurrentTaskUpdateError)]
    assert len(successes) == 1
    assert len(conflicts) == 1
    current = tasks.get(task.task_id)
    assert current is not None
    assert current.status in {TaskStatus.WAITING, TaskStatus.BLOCKED}
    transition_events = [
        event
        for event in state_store.events(stream_id=f"task:{task.task_id}")
        if event.kind == "task.transitioned"
    ]
    assert len(transition_events) == 2  # start plus one winning update


def test_competing_checkpoint_updates_use_compare_and_set(tmp_path):
    state_store = AgentStateStore(tmp_path / "agent-state.sqlite3")
    tasks = TaskStore(state_store)
    task = tasks.create(
        GoalContract(goal="CAS checkpoint"),
        ScopeContext(task_id="cas-checkpoint"),
        task_id="cas-checkpoint",
    )
    barrier = Barrier(2)
    original_get = tasks.get

    def synchronized_get(task_id: str):
        snapshot = original_get(task_id)
        barrier.wait(timeout=2)
        return snapshot

    def checkpoint(phase: str):
        try:
            return tasks.checkpoint(
                task.task_id,
                TaskCheckpoint(phase=phase),
                idempotency_key=f"checkpoint-{phase}",
            )
        except ConcurrentTaskUpdateError as exc:
            return exc

    tasks.get = synchronized_get
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(checkpoint, ("one", "two")))
    tasks.get = original_get

    successes = [outcome for outcome in outcomes if not isinstance(outcome, Exception)]
    conflicts = [outcome for outcome in outcomes if isinstance(outcome, ConcurrentTaskUpdateError)]
    assert len(successes) == 1
    assert len(conflicts) == 1
    current = tasks.get(task.task_id)
    assert current is not None
    assert current.checkpoint.phase in {"one", "two"}
    events = state_store.events(stream_id=f"task:{task.task_id}")
    assert [event.kind for event in events].count("task.checkpointed") == 1


def test_task_creation_rolls_back_projection_when_event_insert_fails(tmp_path):
    state_store = AgentStateStore(tmp_path / "agent-state.sqlite3")
    tasks = TaskStore(state_store)
    tasks._init_projection_table()
    with closing(connect_sqlite(state_store.db_path, isolation_level=None)) as con:
        con.execute(
            """
            CREATE TRIGGER fail_task_created BEFORE INSERT ON agent_events
            WHEN NEW.kind = 'task.created'
            BEGIN
                SELECT RAISE(ABORT, 'atomic test failure');
            END;
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="atomic test failure"):
        tasks.create(
            GoalContract(goal="atomic create"),
            ScopeContext(task_id="atomic-create"),
            task_id="atomic-create",
        )

    assert tasks.get("atomic-create") is None
    assert state_store.events(stream_id="task:atomic-create") == []
