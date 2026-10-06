import sqlite3
from contextlib import closing
from pathlib import Path
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import pytest
from local_ai_hub.cache import SQLiteCache
from local_ai_hub.agent_blackboard import BlackboardStore
from local_ai_hub.agent_events import AppendResult, AgentEvent, AgentStateStore, SwarmPubSub
from local_ai_hub.agent_memory import AgentScope, MemoryKind, MemoryRecord, MemoryStore
from local_ai_hub.agent_tasks import (
    ConcurrentTaskUpdateError,
    GoalContract,
    ScopeContext,
    TaskStatus,
    TaskStore,
)
from local_ai_hub.agent_verification import (
    ChangeIntent,
    OutcomeRecord,
    VerificationReceipt,
    VerificationStore,
)
from local_ai_hub.sqlite_support import (
    DurableSchemaMismatchError,
    connect_sqlite,
    validate_durable_schema,
)
from local_ai_hub.services import LocalAIServices
from local_ai_hub.swarm import SwarmCoordinator, SwarmState
from local_ai_hub.leases import ScopeLeaseStore
import local_ai_hub.sqlite_support as sqlite_support
def test_event_insert_failure_does_not_advance_cursor_or_survive_restart(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    store = AgentStateStore(db_path)
    store._ensure_schema()
    with closing(sqlite3.connect(db_path)) as con, con:
        con.execute(
            "CREATE TRIGGER fail_event BEFORE INSERT ON agent_events "
            "WHEN NEW.kind = 'test.fault' BEGIN SELECT RAISE(ABORT, 'event fault'); END"
        )

    failed = store.append(AgentEvent.create("task:fault", "test.fault", {"x": 1}))
    assert failed.error == "event fault"
    assert store.event_page("task:fault")["last_seq"] == 0

    with closing(sqlite3.connect(db_path)) as con, con:
        con.execute("DROP TRIGGER fail_event")
    restarted = AgentStateStore(db_path)
    recovered = restarted.append(AgentEvent.create("task:fault", "task.ok", {"x": 2}))
    assert recovered.seq == 1
    assert restarted.event_page("task:fault")["last_seq"] == 1
def test_append_in_transaction_preserves_caller_rollback_and_strict_replay(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    store = AgentStateStore(db_path)
    store._ensure_schema()
    stream_id = "task:append-provider"
    event = AgentEvent.create(
        stream_id, "test.appended", {"value": 1}, idempotency_key="provider-once"
    )
    subscriber = store.subscribe()

    con = connect_sqlite(db_path, isolation_level=None)
    try:
        con.execute("BEGIN IMMEDIATE")
        pending = store.append_in_transaction(con, event, strict_idempotency=True)
        assert pending.seq == 1
        assert pending.duplicate is False
        assert pending.event == event.with_seq(1)
        assert con.in_transaction is True
        assert subscriber.empty()
        con.execute("ROLLBACK")
    finally:
        con.close()

    rolled_back = store.event_page(stream_id)
    assert rolled_back["events"] == []
    assert rolled_back["last_seq"] == 0

    con = connect_sqlite(db_path, isolation_level=None)
    try:
        con.execute("BEGIN IMMEDIATE")
        committed = store.append_in_transaction(con, event, strict_idempotency=True)
        assert committed.seq == 1
        assert committed.duplicate is False
        con.execute("COMMIT")
        assert subscriber.empty()
    finally:
        con.close()

    con = connect_sqlite(db_path, isolation_level=None)
    try:
        con.execute("BEGIN IMMEDIATE")
        duplicate = store.append_in_transaction(con, event, strict_idempotency=True)
        assert duplicate.seq == committed.seq
        assert duplicate.duplicate is True
        assert duplicate.event == committed.event

        conflicting = AgentEvent.create(
            stream_id, "test.appended", {"value": 2}, idempotency_key="provider-once"
        )
        with pytest.raises(ValueError, match="idempotency key was already used"):
            store.append_in_transaction(con, conflicting, strict_idempotency=True)
        con.execute("ROLLBACK")
    finally:
        con.close()

    persisted = store.event_page(stream_id)
    page_events = [
        event.to_dict() if isinstance(event, AgentEvent) else event
        for event in persisted["events"]
    ]
    committed_event = (
        committed.event.to_dict()
        if isinstance(committed.event, AgentEvent)
        else committed.event
    )
    assert page_events == [committed_event]
    assert persisted["last_seq"] == committed.seq == 1
    store.unsubscribe(subscriber)
@pytest.mark.parametrize(
    ("field", "conflicting_value"),
    (("actor", "worker-b"), ("correlation_id", "trace-b")),
)
def test_append_in_transaction_strict_replay_binds_actor_and_correlation(
    tmp_path, field, conflicting_value
):
    db_path = tmp_path / "agent_state.sqlite3"
    store = AgentStateStore(db_path)
    store._ensure_schema()
    original = AgentEvent.create(
        "task:strict-identity",
        "test.appended",
        {"value": 1},
        idempotency_key="same-key",
        actor="worker-a",
        correlation_id="trace-a",
    )
    with closing(connect_sqlite(db_path, isolation_level=None)) as con:
        con.execute("BEGIN IMMEDIATE")
        store.append_in_transaction(con, original, strict_idempotency=True)
        con.execute("COMMIT")

    conflicting = AgentEvent.create(
        original.stream_id,
        original.kind,
        original.payload,
        idempotency_key=original.idempotency_key,
        actor=conflicting_value if field == "actor" else original.actor,
        correlation_id=conflicting_value if field == "correlation_id" else original.correlation_id,
    )
    with closing(connect_sqlite(db_path, isolation_level=None)) as con:
        con.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="idempotency key was already used"):
            store.append_in_transaction(con, conflicting, strict_idempotency=True)
        con.execute("ROLLBACK")
def test_append_in_transaction_rejects_connection_without_caller_transaction(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    store = AgentStateStore(db_path)
    store._ensure_schema()
    event = AgentEvent.create(
        "task:append-provider-no-transaction",
        "test.appended",
        {"value": 1},
        idempotency_key="provider-requires-transaction",
    )

    with closing(connect_sqlite(db_path, isolation_level=None)) as con:
        with pytest.raises(RuntimeError, match="caller-owned transaction"):
            store.append_in_transaction(con, event, strict_idempotency=True)

    recovered = store.event_page(event.stream_id)
    assert recovered["events"] == []
    assert recovered["last_seq"] == recovered["next_seq"] == 0
def test_task_receipt_projection_rejects_connection_without_caller_transaction(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    tasks = TaskStore(state_store)
    task = tasks.create(
        GoalContract(goal="receipt transaction", acceptance_criteria=("tests",)),
        ScopeContext(task_id="task-receipt-transaction"),
        task_id="task-receipt-transaction",
    )

    with closing(connect_sqlite(db_path, isolation_level=None)) as con:
        with pytest.raises(RuntimeError, match="caller-owned transaction"):
            tasks.add_verification_receipt_in_transaction(
                con, task.task_id, "tests", "receipt-without-transaction"
            )

    saved = tasks.get(task.task_id)
    assert saved is not None
    assert saved.verification_receipts == {}
    assert all(
        event.kind != "task.verified"
        for event in state_store.events(f"task:{task.task_id}")
    )
def test_ordered_event_publication_rejects_uncommitted_and_rolled_back_events(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    store = AgentStateStore(db_path)
    store._ensure_schema()
    subscriber = store.subscribe()
    event = AgentEvent.create(
        "task:ordered-rollback",
        "test.appended",
        {"value": 1},
        idempotency_key="ordered-rollback",
    )

    with closing(connect_sqlite(db_path, isolation_level=None)) as con:
        with store.ordered_event_publication(con) as publish_committed:
            con.execute("BEGIN IMMEDIATE")
            pending = store.append_in_transaction(con, event)
            with pytest.raises(RuntimeError, match="caller transaction is still open"):
                publish_committed([pending.event])
            assert subscriber.empty()
            con.execute("ROLLBACK")
            with pytest.raises(RuntimeError, match="event is not committed"):
                publish_committed([pending.event])

    page = store.event_page(event.stream_id)
    assert subscriber.empty()
    assert page["events"] == []
    assert page["last_seq"] == page["next_seq"] == 0
    store.unsubscribe(subscriber)
def test_duplicate_replay_rebuilds_cursor_from_stream_high_water(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    store = AgentStateStore(db_path)
    stream_id = "task:rebuild-cursor"
    events = [
        AgentEvent.create(
            stream_id,
            "test.appended",
            {"value": seq},
            idempotency_key=f"rebuild-cursor-{seq}",
        )
        for seq in range(1, 4)
    ]

    for expected_seq, event in enumerate(events, start=1):
        appended = store.append(event)
        assert appended.error is None
        assert appended.seq == expected_seq

    with closing(connect_sqlite(db_path, isolation_level=None)) as con:
        con.execute(
            "DELETE FROM agent_event_cursors WHERE stream_id = ?", (stream_id,)
        )

    duplicate = store.append(events[1])
    assert duplicate.error is None
    assert duplicate.duplicate is True
    assert duplicate.seq == 2

    next_append = store.append(
        AgentEvent.create(
            stream_id,
            "test.appended",
            {"value": 4},
            idempotency_key="rebuild-cursor-4",
        )
    )
    assert next_append.error is None
    assert next_append.seq == 4
def test_task_transition_append_result_error_rolls_back_projection(tmp_path, monkeypatch):
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    tasks = TaskStore(state_store)
    task = tasks.create(
        GoalContract(goal="atomic transition"),
        ScopeContext(task_id="task-append-error"),
        task_id="task-append-error",
    )
    task = tasks.transition(
        task.task_id, TaskStatus.ACTIVE, reason="start", actor="agent", idempotency_key="active"
    )
    monkeypatch.setattr(
        state_store,
        "append_in_transaction",
        lambda *args, **kwargs: AppendResult(seq=0, duplicate=False, error="append rejected"),
    )

    with pytest.raises(RuntimeError, match="append rejected"):
        tasks.transition(
            task.task_id, TaskStatus.VERIFYING, reason="verify", actor="agent", idempotency_key="verifying"
        )

    assert tasks.get(task.task_id).status.value == "active"
    assert state_store.events(f"task:{task.task_id}")[-1].payload["to_status"] == "active"
def test_task_transition_cas_has_one_winner_and_one_conflict(tmp_path, monkeypatch):
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    tasks = TaskStore(state_store)
    task = tasks.create(
        GoalContract(goal="concurrent transition"),
        ScopeContext(task_id="task-transition-cas"),
        task_id="task-transition-cas",
    )
    assert task.status == TaskStatus.PLANNED

    original_get = tasks.get
    readers_ready = threading.Barrier(2)

    def synchronized_get(task_id):
        state = original_get(task_id)
        if task_id == task.task_id:
            readers_ready.wait(timeout=5)
        return state

    monkeypatch.setattr(tasks, "get", synchronized_get)

    def transition(target, idempotency_key):
        try:
            updated = tasks.transition(
                task.task_id,
                target,
                reason="competing transition",
                actor="agent",
                idempotency_key=idempotency_key,
            )
            return "committed", updated
        except ConcurrentTaskUpdateError as error:
            return "conflict", error

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(
            lambda args: transition(*args),
            ((TaskStatus.ACTIVE, "transition-active"), (TaskStatus.CANCELLED, "transition-cancelled")),
        ))

    assert sorted(kind for kind, _ in outcomes) == ["committed", "conflict"]
    committed = next(value for kind, value in outcomes if kind == "committed")
    conflict = next(value for kind, value in outcomes if kind == "conflict")
    assert isinstance(conflict, ConcurrentTaskUpdateError)

    monkeypatch.setattr(tasks, "get", original_get)
    persisted = tasks.get(task.task_id)
    assert persisted.status == committed.status
    transitions = [
        event for event in state_store.events(f"task:{task.task_id}")
        if event.kind == "task.transitioned"
    ]
    assert len(transitions) == 1
    assert transitions[0].payload["to_status"] == committed.status.value
def test_verification_append_result_error_rolls_back_receipt_projection(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    tasks = TaskStore(state_store)
    tasks.create(
        GoalContract(goal="atomic receipt", acceptance_criteria=("tests",)),
        ScopeContext(task_id="task-append-error"),
        task_id="task-append-error",
    )
    verifications = VerificationStore(state_store, task_store=tasks)
    receipt = VerificationReceipt.create(
        "task-append-error", "tests", passed=True, evidence_id="evidence-tests",
        command_id="cmd-append-error",
    )
    monkeypatch.setattr(
        state_store,
        "append_in_transaction",
        lambda *args, **kwargs: AppendResult(seq=0, duplicate=False, error="append rejected"),
    )

    with pytest.raises(RuntimeError, match="append rejected"):
        verifications.record(receipt)

    with closing(sqlite3.connect(db_path)) as con:
        assert con.execute(
            "SELECT COUNT(*) FROM agent_verification_receipts WHERE receipt_id = ?",
            (receipt.receipt_id,),
        ).fetchone()[0] == 0
    assert tasks.get("task-append-error").verification_receipts == {}
    assert state_store.events("verification:task-append-error") == []
def test_verification_receipt_task_projection_and_events_rollback_together(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    tasks = TaskStore(state_store)
    verifications = VerificationStore(state_store, task_store=tasks)
    tasks.create(
        GoalContract(goal="atomic receipt", acceptance_criteria=("tests",)),
        ScopeContext(task_id="task-atomic-receipt"),
        task_id="task-atomic-receipt",
    )
    receipt = VerificationReceipt.create(
        "task-atomic-receipt", "tests", passed=True, evidence_id="evidence-tests",
        command_id="cmd-atomic-receipt",
    )
    with closing(sqlite3.connect(db_path)) as con, con:
        con.execute(
            "CREATE TRIGGER fail_task_verified BEFORE INSERT ON agent_events "
            "WHEN NEW.kind = 'task.verified' "
            "BEGIN SELECT RAISE(ABORT, 'task verification event fault'); END"
        )

    with pytest.raises(sqlite3.IntegrityError, match="task verification event fault"):
        verifications.record(receipt)

    with closing(sqlite3.connect(db_path)) as con:
        assert con.execute(
            "SELECT COUNT(*) FROM agent_verification_receipts WHERE receipt_id = ?",
            (receipt.receipt_id,),
        ).fetchone()[0] == 0
    assert state_store.events("verification:task-atomic-receipt") == []
    task = tasks.get("task-atomic-receipt")
    assert task is not None
    assert task.verification_receipts == {}

    with closing(sqlite3.connect(db_path)) as con, con:
        con.execute("DROP TRIGGER fail_task_verified")
    restarted_store = AgentStateStore(db_path)
    restarted_tasks = TaskStore(restarted_store)
    restarted_verifications = VerificationStore(restarted_store, task_store=restarted_tasks)
    restarted_verifications.record(receipt)

    saved = restarted_tasks.get("task-atomic-receipt")
    assert saved is not None
    assert saved.verification_receipts == {"tests": receipt.receipt_id}
    assert [event.kind for event in restarted_store.events("verification:task-atomic-receipt")] == [
        "verification.receipt_recorded"
    ]
    assert [event.kind for event in restarted_store.events("task:task-atomic-receipt")].count(
        "task.verified"
    ) == 1
def test_passed_receipt_for_unknown_task_persists_without_task_projection(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    tasks = TaskStore(state_store)
    verifications = VerificationStore(state_store, task_store=tasks)
    receipt = VerificationReceipt.create(
        "missing-task", "tests", passed=True, evidence_id="evidence-tests",
        command_id="cmd-unknown-task",
    )

    assert verifications.record(receipt) is receipt

    with closing(sqlite3.connect(db_path)) as con:
        assert con.execute(
            "SELECT COUNT(*) FROM agent_verification_receipts WHERE receipt_id = ?",
            (receipt.receipt_id,),
        ).fetchone()[0] == 1
        assert con.execute(
            "SELECT COUNT(*) FROM agent_tasks_projection WHERE task_id = ?",
            ("missing-task",),
        ).fetchone()[0] == 0
    assert [event.kind for event in state_store.events("verification:missing-task")] == [
        "verification.receipt_recorded"
    ]
    assert state_store.events("task:missing-task") == []

def test_add_verification_receipt_wrapper_rolls_back_when_event_append_fails(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    tasks = TaskStore(state_store)
    task = tasks.create(GoalContract(goal="atomic receipt wrapper"), ScopeContext())
    stream_id = f"task:{task.task_id}"
    before = state_store.event_page(stream_id)["events"]
    subscriber = state_store.subscribe()
    append = state_store.append_in_transaction

    def fail_receipt_append(con, event, *, strict_idempotency=False):
        if event.kind == "task.verified":
            raise RuntimeError("injected receipt append failure")
        return append(con, event, strict_idempotency=strict_idempotency)

    monkeypatch.setattr(state_store, "append_in_transaction", fail_receipt_append)
    with pytest.raises(RuntimeError, match="injected receipt append failure"):
        tasks.add_verification_receipt(task.task_id, "criterion", "receipt-1")

    persisted = tasks.get(task.task_id)
    assert persisted is not None
    assert persisted.verification_receipts == {}
    assert state_store.event_page(stream_id)["events"] == before
    assert subscriber.empty()
    state_store.unsubscribe(subscriber)


def test_expired_memory_delete_and_event_are_atomic(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    memory = MemoryStore(state_store)
    root = str(tmp_path.resolve())
    tenant = "t08-expiry-tenant"
    record = MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.TASK,
        scope_id="task-expired",
        key="expires",
        value={"keep_until": 1},
        provenance={"root": root, "tenant": tenant},
        expires_at=time.time() + 10,
    )
    saved = memory.record(record)
    with closing(sqlite3.connect(db_path)) as con, con:
        con.execute(
            "CREATE TRIGGER fail_memory_expired BEFORE INSERT ON agent_events "
            "WHEN NEW.kind = 'memory.expired' "
            "BEGIN SELECT RAISE(ABORT, 'memory expiry event fault'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="memory expiry event fault"):
        memory.reap_expired(now=time.time() + 20)
    assert memory.get(
        saved.record_id, scope=AgentScope.TASK, scope_id="task-expired",
        task_id="task-expired", root=root, tenant=tenant,
    ) is not None
    stream_id = "memory:" + "".join(
        f"{len(part)}:{part}" for part in (saved.scope.value, saved.scope_id, saved.key)
    )
    assert [event.kind for event in state_store.events(stream_id)] == [
        "memory.recorded"
    ]

    with closing(sqlite3.connect(db_path)) as con, con:
        con.execute("DROP TRIGGER fail_memory_expired")
    assert memory.reap_expired(now=time.time() + 20) == 1
    assert memory.get(
        saved.record_id, scope=AgentScope.TASK, scope_id="task-expired",
        task_id="task-expired", root=root, tenant=tenant,
    ) is None
    assert [event.kind for event in state_store.events(stream_id)] == [
        "memory.recorded", "memory.expired"
    ]
