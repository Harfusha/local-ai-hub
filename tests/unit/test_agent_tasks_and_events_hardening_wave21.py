from __future__ import annotations

import math
import time
import pytest
from local_ai_hub.agent_events import AgentEvent, AgentStateStore
from local_ai_hub.agent_tasks import (
    GoalContract,
    TaskCheckpoint,
    TaskState,
    TaskStatus,
    TaskStore,
)
from local_ai_hub.agent_identity import AgentScope, ScopeContext


@pytest.mark.parametrize("field,value", [
    ("event_id", "evt_\x00123"), ("stream_id", "stream\x00_abc"),
    ("kind", "task\x00.created"), ("idempotency_key", "idemp_\x00456"),
    ("correlation_id", "corr_\x00789"), ("actor", "agent\x00_worker"),
    ("created_at", True), ("created_at", float("inf")),
    ("seq", True), ("seq", -5), ("payload", "not-a-dict"),
])
def test_agent_event_invalid_fields_reject(field, value):
    fields = dict(event_id="evt-1", stream_id="stream-1", kind="task.created",
                  payload={}, idempotency_key="idemp-1", correlation_id="", actor="agent",
                  created_at=1700000000.0, seq=1)
    fields[field] = value
    with pytest.raises((TypeError, ValueError)):
        AgentEvent(**fields)


def test_agent_event_from_dict_and_roundtrip():
    with pytest.raises((TypeError, ValueError)):
        AgentEvent.from_dict("invalid")

    # Normal roundtrip
    event = AgentEvent.create(
        stream_id="stream-1",
        kind="task.progress",
        payload={"step": 5},
        correlation_id="c-1",
    ).with_seq(42)
    d = event.to_dict()
    recovered = AgentEvent.from_dict(d)
    assert recovered.event_id == event.event_id
    assert recovered.stream_id == "stream-1"
    assert recovered.kind == "task.progress"
    assert recovered.payload == {"step": 5}
    assert recovered.correlation_id == "c-1"
    assert recovered.seq == 42


def test_agent_event_from_row_resilience():
    # Valid row
    row = (
        "stream-1",
        1,
        "evt_1",
        "task.created",
        '{"goal": "test"}',
        "idemp_1",
        "corr_1",
        "agent",
        1700000000.0,
    )
    ev = AgentEvent.from_row(row)
    assert ev.stream_id == "stream-1"
    assert ev.seq == 1
    assert ev.payload == {"goal": "test"}

    # Corrupt JSON payload row
    row_corrupt = (
        "stream-1",
        2,
        "evt_2",
        "task.created",
        "{malformed-json",
        "idemp_2",
        "corr_2",
        "agent",
        1700000001.0,
    )
    with pytest.raises(ValueError):
        AgentEvent.from_row(row_corrupt)

    # None payload row
    row_none = (
        "stream-1",
        3,
        "evt_3",
        "task.created",
        None,
        "idemp_3",
        "corr_3",
        "agent",
        1700000002.0,
    )
    with pytest.raises((TypeError, ValueError)):
        AgentEvent.from_row(row_none)

    # Row with insufficient columns
    with pytest.raises(ValueError):
        AgentEvent.from_row(("stream-1", 4))


def test_task_checkpoint_hardening_and_from_dict():
    # Non-mapping state_data in checkpoint
    cp = TaskCheckpoint(
        phase="discover\x00",
        next_action="inspect\x00",
        affected_paths=("src/\x00main.py",),
        state_data="not-a-dict",  # type: ignore[arg-type]
    )
    assert cp.phase == "discover"
    assert cp.next_action == "inspect"
    assert cp.affected_paths == ("src/main.py",)
    assert cp.state_data == {}

    # from_dict with invalid input
    fallback = TaskCheckpoint.from_dict(None)  # type: ignore[arg-type]
    assert isinstance(fallback, TaskCheckpoint)
    assert fallback.phase == ""

    # from_dict with non-mapping state_data
    recovered = TaskCheckpoint.from_dict({
        "phase": "plan",
        "state_data": 12345,
    })
    assert recovered.phase == "plan"
    assert recovered.state_data == {}


def test_task_state_from_dict_and_roundtrip():
    contract = GoalContract(goal="Implement wave 21 hardening")
    context = ScopeContext(repository_id="repo-1", task_id="task-1")
    checkpoint = TaskCheckpoint(phase="implementation")
    state = TaskState(
        task_id="task-1",
        status=TaskStatus.ACTIVE,
        contract=contract,
        context=context,
        owner="worker-1",
        lease_id="lease-1",
        created_at=1700000000.0,
        updated_at=1700000010.0,
        checkpoint=checkpoint,
        verification_receipts={"crit-1": "receipt-1"},
    )

    d = state.to_dict()
    recovered = TaskState.from_dict(d)
    assert recovered.task_id == "task-1"
    assert recovered.status == TaskStatus.ACTIVE
    assert recovered.contract.goal == "Implement wave 21 hardening"
    assert recovered.context.repository_id == "repo-1"
    assert recovered.checkpoint.phase == "implementation"
    assert recovered.verification_receipts == {"crit-1": "receipt-1"}

    # Invalid input should raise ValueError
    with pytest.raises(ValueError):
        TaskState.from_dict("not-a-dict")


def test_task_state_store_row_to_state_corruption_rejects(tmp_path):
    state_store = AgentStateStore(tmp_path / "tasks.db")
    store = TaskStore(state_store)
    # Row with corrupted JSON fields and unknown status
    row = (
        "task-corrupt",
        "unknown_status_val",
        "owner-1",
        "lease-1",
        "{malformed_contract_json",
        "{malformed_context_json",
        "{malformed_checkpoint_json",
        "{malformed_receipts_json",
        0.0,
        1700000000.0,
        1700000010.0,
    )
    with pytest.raises(ValueError):
        store._row_to_state(row)
