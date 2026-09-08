from __future__ import annotations

import json
from pathlib import Path
import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import AgentScope, ScopeContext
from local_ai_hub.agent_tasks import (
    CompletionGateError,
    GoalContract,
    InvalidTransitionError,
    TaskCheckpoint,
    TaskState,
    TaskStatus,
    TaskStore,
)


@pytest.fixture
def store(tmp_path: Path) -> TaskStore:
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    return TaskStore(state_store)


def task_context() -> ScopeContext:
    return ScopeContext(repository_id="repo-1", branch="main", task_id="task-1")


def contract_with_criteria(*criteria: str) -> GoalContract:
    return GoalContract(
        goal="Implement feature",
        acceptance_criteria=tuple(criteria),
        scope=AgentScope.TASK,
    )


def test_task_creation_and_retrieval(store: TaskStore):
    contract = contract_with_criteria("unit_tests")
    task = store.create(contract, task_context(), task_id="t-1")
    assert task.task_id == "t-1"
    assert task.status == TaskStatus.PLANNED
    fetched = store.get("t-1")
    assert fetched is not None
    assert fetched.task_id == "t-1"
    assert fetched.contract.goal == "Implement feature"


def test_completed_requires_all_criteria_to_have_fresh_receipts(store: TaskStore):
    task = store.create(contract_with_criteria("tests", "review"), task_context())
    store.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="agent", idempotency_key="a")
    store.transition(task.task_id, TaskStatus.VERIFYING, reason="ready", actor="agent", idempotency_key="v")
    with pytest.raises(CompletionGateError):
        store.transition(task.task_id, TaskStatus.COMPLETED, reason="claimed", actor="agent", idempotency_key="c")


def test_completed_succeeds_when_verified(store: TaskStore):
    task = store.create(contract_with_criteria("tests"), task_context())
    store.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="agent", idempotency_key="a")
    store.transition(task.task_id, TaskStatus.VERIFYING, reason="ready", actor="agent", idempotency_key="v")
    # attach verified receipt
    store.add_verification_receipt(task.task_id, "tests", "receipt-1")
    completed = store.transition(task.task_id, TaskStatus.COMPLETED, reason="all passed", actor="agent", idempotency_key="c")
    assert completed.status == TaskStatus.COMPLETED


def test_expired_active_task_becomes_abandoned_with_checkpoint(store: TaskStore):
    task = store.create(contract_with_criteria("tests"), task_context(), task_id="t-heartbeat")
    store.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="agent", idempotency_key="a")
    store.checkpoint(task.task_id, TaskCheckpoint(phase="coding", next_action="run tests"), actor="agent", idempotency_key="chk-1")
    active_task = store.get(task.task_id)
    assert active_task is not None
    assert active_task.status == TaskStatus.ACTIVE
    assert active_task.heartbeat_expires_at > 0

    reaped = store.reap_expired_heartbeats(now=active_task.heartbeat_expires_at + 10)
    assert reaped == [task.task_id]
    abandoned = store.get(task.task_id)
    assert abandoned is not None
    assert abandoned.status == TaskStatus.ABANDONED
    assert abandoned.checkpoint.phase == "coding"
    assert abandoned.checkpoint.next_action == "run tests"


def test_resume_abandoned_task(store: TaskStore):
    task = store.create(contract_with_criteria("tests"), task_context(), task_id="t-resume")
    store.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="agent", idempotency_key="a")
    store.reap_expired_heartbeats(now=store.get(task.task_id).heartbeat_expires_at + 10)

    resumed = store.resume(task.task_id, actor="agent", idempotency_key="res-1")
    assert resumed.status == TaskStatus.ACTIVE


def test_illegal_transition_raises_error(store: TaskStore):
    task = store.create(contract_with_criteria("tests"), task_context())
    with pytest.raises(InvalidTransitionError):
        store.transition(task.task_id, TaskStatus.COMPLETED, reason="skip to end", actor="agent", idempotency_key="bad")


def test_add_verification_receipt_emits_event(tmp_path: Path):
    from local_ai_hub.agent_events import AgentStateStore

    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    task_store = TaskStore(state_store)
    task = task_store.create(contract_with_criteria("tests"), task_context(), task_id="t-evt")

    events_before = state_store.events(stream_id=f"task:{task.task_id}")
    assert len(events_before) == 1  # task.created

    task_store.add_verification_receipt(task.task_id, "tests", "rcpt-123")

    events_after = state_store.events(stream_id=f"task:{task.task_id}")
    assert len(events_after) == 2
    assert events_after[-1].kind == "task.verified"
    assert events_after[-1].payload == {"criterion": "tests", "receipt_id": "rcpt-123"}


def test_stores_schema_initialized_flag(tmp_path: Path):
    from local_ai_hub.agent_events import AgentStateStore
    from local_ai_hub.agent_verification import VerificationStore
    from local_ai_hub.agent_memory import MemoryStore
    from local_ai_hub.agent_incidents import IncidentStore
    from local_ai_hub.agent_learning import LearningStore

    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    ts = TaskStore(state_store)
    vs = VerificationStore(state_store)
    ms = MemoryStore(state_store)
    inc = IncidentStore(state_store)
    ls = LearningStore(state_store)

    assert ts._initialized is True
    assert vs._initialized is True
    assert ms._initialized is True
    assert inc._initialized is True
    assert ls._initialized is True

