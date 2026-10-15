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


# Historical stash 16269603: restored contract intent, not a replacement of newer guards.

def test_durable_schema_mismatch_rejects_without_backup_or_source_write(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    with closing(sqlite3.connect(db_path)) as con, con:
        con.execute("CREATE TABLE agent_events (stream_id TEXT, seq INTEGER)")
        con.execute("INSERT INTO agent_events VALUES ('task:keep', 7)")
    original = db_path.read_bytes()

    store = AgentStateStore(db_path)
    with pytest.raises(DurableSchemaMismatchError) as caught:
        store._ensure_schema()

    assert caught.value.recovery_required is True
    assert caught.value.backup_path is None
    assert db_path.read_bytes() == original
    with closing(sqlite3.connect(db_path)) as con, con:
        assert con.execute("SELECT stream_id, seq FROM agent_events").fetchall() == [("task:keep", 7)]
    assert not list(tmp_path.glob(f"{db_path.name}.schema-mismatch-*.sqlite3"))


def test_durable_schema_mismatch_preserves_database_and_wal_sidecars(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    writer = sqlite3.connect(db_path)
    try:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower() == "wal"
        writer.execute("CREATE TABLE agent_events (stream_id TEXT, seq INTEGER)")
        writer.execute("INSERT INTO agent_events VALUES ('task:wal', 9)")
        writer.commit()

        wal_path = db_path.with_name(f"{db_path.name}-wal")
        assert wal_path.exists() and wal_path.stat().st_size > 0
        paths = tuple(
            db_path.with_name(f"{db_path.name}{suffix}")
            for suffix in ("", "-wal", "-shm", "-journal")
        )
        before = tuple(path.read_bytes() if path.is_file() else None for path in paths)

        with pytest.raises(DurableSchemaMismatchError) as caught:
            AgentStateStore(db_path)._ensure_schema()

        assert caught.value.backup_path is None
        assert tuple(path.read_bytes() if path.is_file() else None for path in paths) == before
        with closing(sqlite3.connect(db_path)) as con:
            assert con.execute("SELECT stream_id, seq FROM agent_events").fetchall() == [("task:wal", 9)]
    finally:
        writer.close()


def test_disposable_derived_cache_quarantines_and_rebuilds(tmp_path):
    db_path = tmp_path / "derived-cache.sqlite3"
    corrupt_bytes = b"not a sqlite database"
    db_path.write_bytes(corrupt_bytes)

    cache = SQLiteCache(db_path, "t08-derived-cache")

    quarantined = list(tmp_path.glob("derived-cache.sqlite3.corrupt-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_bytes() == corrupt_bytes
    assert cache.get("before-rebuild") is None

    cache.set("after-rebuild", {"usable": True})
    reopened = SQLiteCache(db_path, "t08-derived-cache")
    assert reopened.get("after-rebuild") == {"usable": True}


def test_event_page_reports_empty_retention_gap_and_future_cursor(tmp_path):
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    empty = store.event_page("task:cursor", after_seq=0, limit=10)
    assert set(empty) == {
        "success", "events", "next_seq", "first_retained_seq", "last_seq",
        "has_more", "gap_ranges", "cursor_reset",
    }
    assert empty["success"] is True
    assert empty["events"] == []
    assert empty["next_seq"] == 0
    assert empty["first_retained_seq"] == 0
    assert empty["last_seq"] == 0
    assert empty["has_more"] is False
    assert empty["gap_ranges"] == []
    assert empty["cursor_reset"] is False

    old = time.time() - 3 * 86400
    store.append(AgentEvent.create("task:cursor", "task.old", {"n": 1}, created_at=old))
    store.append(AgentEvent.create("task:cursor", "task.old", {"n": 2}, created_at=old + 1))
    current = store.append(AgentEvent.create("task:cursor", "task.current", {"n": 3}))
    assert current.seq == 3
    partial = store.event_page("task:cursor", after_seq=0, limit=1)
    assert [event["seq"] for event in partial["events"]] == [1]
    assert partial["next_seq"] == 1
    assert partial["has_more"] is True

    cleanup = store.cleanup(retention_days=1)
    assert cleanup["deleted_events"] == 2
    page = store.event_page("task:cursor", after_seq=0, limit=1)
    assert [event["seq"] for event in page["events"]] == [3]
    assert page["first_retained_seq"] == 3
    assert page["last_seq"] == 3
    assert page["has_more"] is False
    assert page["gap_ranges"] == [{"from_seq": 1, "to_seq": 2}]
    assert page["next_seq"] == 3
    assert page["cursor_reset"] is False

    future = store.event_page("task:cursor", after_seq=99, limit=1)
    assert [event["seq"] for event in future["events"]] == [3]
    assert future["first_retained_seq"] == 3
    assert future["last_seq"] == 3
    assert future["has_more"] is False
    assert future["gap_ranges"] == []
    assert future["cursor_reset"] is True
    assert future["next_seq"] == 3

    with closing(sqlite3.connect(store.db_path)) as con, con:
        con.execute(
            "UPDATE agent_events SET created_at = ? WHERE stream_id = ? AND seq = 3",
            (old + 2, "task:cursor"),
        )
    store.cleanup(retention_days=1)
    empty_after_retention = store.event_page("task:cursor", after_seq=0, limit=1)
    assert empty_after_retention["events"] == []
    assert empty_after_retention["first_retained_seq"] is None
    assert empty_after_retention["last_seq"] == 3
    assert empty_after_retention["gap_ranges"] == [{"from_seq": 1, "to_seq": 3}]
    assert empty_after_retention["next_seq"] == 3
    future_empty = store.event_page("task:cursor", after_seq=99, limit=1)
    assert future_empty["success"] is True
    assert future_empty["events"] == []
    assert future_empty["cursor_reset"] is True
    assert future_empty["next_seq"] == 3
    assert future_empty["gap_ranges"] == []


def test_event_page_reports_gaps_inside_page_in_sequence_order(tmp_path):
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    stream_id = "task:interleaved-gaps"

    first = store.append(AgentEvent.create(stream_id, "task.updated", {"n": 1}))
    store.append(AgentEvent.create(stream_id, "task.updated", {"n": 2}))
    middle = store.append(AgentEvent.create(stream_id, "task.updated", {"n": 3}))
    store.append(AgentEvent.create(stream_id, "task.updated", {"n": 4}))
    last = store.append(AgentEvent.create(stream_id, "task.updated", {"n": 5}))
    assert (first.seq, middle.seq, last.seq) == (1, 3, 5)

    with closing(connect_sqlite(store.db_path, isolation_level=None)) as con:
        deleted = con.execute(
            "DELETE FROM agent_events WHERE stream_id = ? AND seq IN (2, 4)",
            (stream_id,),
        ).rowcount
    assert deleted == 2

    page = store.event_page(stream_id, after_seq=0, limit=3)

    assert [event["seq"] for event in page["events"]] == [1, 3, 5]
    assert page["gap_ranges"] == [
        {"from_seq": 2, "to_seq": 2},
        {"from_seq": 4, "to_seq": 4},
    ]
    assert page["next_seq"] == 5
    assert page["has_more"] is False
    assert page["first_retained_seq"] == 1
    assert page["last_seq"] == 5


def test_event_page_uses_one_snapshot_while_cleanup_commits(tmp_path, monkeypatch):
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    stream_id = "task:concurrent-cleanup"
    old = time.time() - 3 * 86400
    store.append(AgentEvent.create(stream_id, "task.updated", {"n": 1}, created_at=old))
    store.append(AgentEvent.create(stream_id, "task.updated", {"n": 2}, created_at=old + 1))

    original_connect = connect_sqlite
    wrapped_page_connection = False
    cleanup_results = []

    class BufferedCursor:
        def __init__(self, cursor, first_row):
            self.cursor = cursor
            self.first_row = first_row
            self.has_buffered_row = True

        def fetchone(self):
            if self.has_buffered_row:
                self.has_buffered_row = False
                return self.first_row
            return self.cursor.fetchone()

    class InterleavingConnection:
        def __init__(self, connection):
            self.connection = connection
            self.interleaved = False

        def execute(self, sql, parameters=()):
            cursor = self.connection.execute(sql, parameters)
            normalized_sql = " ".join(sql.upper().split())
            if (
                not self.interleaved
                and normalized_sql.startswith(
                    "SELECT LAST_SEQ, FIRST_RETAINED_SEQ FROM AGENT_EVENT_CURSORS"
                )
            ):
                first_row = cursor.fetchone()
                self.interleaved = True
                cleanup_results.append(store.cleanup(retention_days=1))
                return BufferedCursor(cursor, first_row)
            return cursor

        def close(self):
            self.connection.close()

    def connect_with_cleanup_interleaving(path, *args, **kwargs):
        nonlocal wrapped_page_connection
        connection = original_connect(path, *args, **kwargs)
        if not wrapped_page_connection and kwargs.get("isolation_level") is None:
            wrapped_page_connection = True
            return InterleavingConnection(connection)
        return connection

    monkeypatch.setattr(store, "_ensure_schema", lambda: None)
    monkeypatch.setattr(
        "local_ai_hub.agent_events.connect_sqlite", connect_with_cleanup_interleaving
    )

    page = store.event_page(stream_id, after_seq=0, limit=10)

    assert wrapped_page_connection is True
    assert cleanup_results[0]["deleted_events"] == 2
    assert [event["seq"] for event in page["events"]] == [1, 2]
    assert page["first_retained_seq"] == 1
    assert page["last_seq"] == 2
    assert page["gap_ranges"] == []

    after_cleanup = store.event_page(stream_id, after_seq=0, limit=10)
    assert after_cleanup["events"] == []
    assert after_cleanup["first_retained_seq"] is None
    assert after_cleanup["last_seq"] == 2
    assert after_cleanup["gap_ranges"] == [{"from_seq": 1, "to_seq": 2}]


def test_event_page_advances_cursor_past_trailing_gap_after_events(tmp_path):
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    stream_id = "task:trailing-gap"

    first = store.append(AgentEvent.create(stream_id, "task.updated", {"n": 1}))
    store.append(AgentEvent.create(stream_id, "task.updated", {"n": 2}))
    store.append(AgentEvent.create(stream_id, "task.updated", {"n": 3}))
    assert first.seq == 1

    with closing(connect_sqlite(store.db_path, isolation_level=None)) as con:
        deleted = con.execute(
            "DELETE FROM agent_events WHERE stream_id = ? AND seq IN (2, 3)",
            (stream_id,),
        ).rowcount
    assert deleted == 2

    page = store.event_page(stream_id, after_seq=0, limit=1)

    assert [event["seq"] for event in page["events"]] == [1]
    assert page["gap_ranges"] == [{"from_seq": 2, "to_seq": 3}]
    assert page["next_seq"] == 3
    assert page["has_more"] is False
    assert page["first_retained_seq"] == 1
    assert page["last_seq"] == 3


def test_event_page_error_is_stable_and_preserves_input_cursor(tmp_path, monkeypatch):
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    store._ensure_schema()

    def fail_schema():
        raise OSError("database temporarily unavailable")

    monkeypatch.setattr(store, "_ensure_schema", fail_schema)
    page = store.event_page("task:failure", after_seq=27)

    assert page["success"] is False
    assert page["error"] == {
        "code": "event_page_unavailable",
        "message": "Event page could not be read.",
    }
    assert page["events"] == []
    assert page["next_seq"] == 27
    assert page["first_retained_seq"] is None
    assert page["last_seq"] == 0
    assert page["has_more"] is False
    assert page["gap_ranges"] == []
    assert page["cursor_reset"] is False


def test_event_page_replays_more_than_default_page_without_gaps(tmp_path):
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    stream_id = "task:large-replay"
    for n in range(1, 1002):
        store.append(
            AgentEvent.create(
                stream_id,
                "task.updated",
                {"n": n},
                idempotency_key=f"large-replay-{n}",
            )
        )

    first = store.event_page(stream_id, after_seq=0)
    assert first["success"] is True
    assert [event["seq"] for event in first["events"]] == list(range(1, 1001))
    assert first["next_seq"] == 1000
    assert first["has_more"] is True
    assert first["gap_ranges"] == []

    second = store.event_page(stream_id, after_seq=first["next_seq"])
    assert [event["seq"] for event in second["events"]] == [1001]
    assert second["next_seq"] == 1001
    assert second["has_more"] is False
    assert second["gap_ranges"] == []


def test_blackboard_expected_version_has_one_winner_and_one_conflict(tmp_path):
    store = BlackboardStore(tmp_path / "agent_state.sqlite3")
    initial = store.update("board", "section", {"n": 0}, author="base")
    expected = initial["version"]
    barrier = threading.Barrier(3)

    def update(value):
        barrier.wait(timeout=2)
        return store.update("board", "section", {"n": value}, author=f"agent-{value}", expected_version=expected)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(update, 1)
        second = pool.submit(update, 2)
        barrier.wait(timeout=2)
        results = [first.result(timeout=5), second.result(timeout=5)]

    assert sum(result["success"] for result in results) == 1
    assert sum(result.get("version_conflict", False) for result in results) == 1
    current = store.get("board", "section")["section"]
    assert current["version"] == expected + 1
    assert current["content"] in ({"n": 1}, {"n": 2})


def test_blackboard_idempotency_key_binds_expected_version(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    store = BlackboardStore(db_path, state_store=AgentStateStore(db_path))
    first = store.update(
        "board", "section", {"n": 1}, author="agent",
        expected_version=0, idempotency_key="write-once",
    )
    replay = store.update(
        "board", "section", {"n": 1}, author="agent",
        expected_version=0, idempotency_key="write-once",
    )
    changed_version = store.update(
        "board", "section", {"n": 1}, author="agent",
        expected_version=1, idempotency_key="write-once",
    )

    assert first["success"] is True
    assert replay["success"] is True and replay["duplicate"] is True
    assert changed_version["success"] is False
    assert changed_version["idempotency_conflict"] is True
    assert store.get("board", "section")["section"]["version"] == 1


@pytest.mark.parametrize("mismatch_on_blackboard", [False, True])
def test_swarm_rejects_state_store_on_different_database(tmp_path, mismatch_on_blackboard):
    db_path = tmp_path / "swarm.sqlite3"
    other_store = AgentStateStore(tmp_path / "events.sqlite3")
    if mismatch_on_blackboard:
        kwargs = {
            "state_store": AgentStateStore(db_path),
            "blackboard": BlackboardStore(db_path, state_store=other_store),
        }
    else:
        kwargs = {"state_store": other_store}

    with pytest.raises(ValueError, match="swarm and .* state stores must share one SQLite database"):
        SwarmCoordinator(db_path, **kwargs)


def test_blackboard_event_failure_rolls_back_projection(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    state_store._ensure_schema()
    board = BlackboardStore(db_path, state_store=state_store)
    with closing(sqlite3.connect(db_path)) as con, con:
        con.execute(
            "CREATE TRIGGER fail_blackboard_event BEFORE INSERT ON agent_events "
            "WHEN NEW.kind = 'blackboard.updated' "
            "BEGIN SELECT RAISE(ABORT, 'blackboard event fault'); END"
        )

    with pytest.raises(sqlite3.IntegrityError, match="blackboard event fault"):
        board.update("atomic", "section", {"value": 1}, author="agent")

    assert board.get("atomic")["sections"] == {}
    assert state_store.events("blackboard:atomic:section") == []
    with closing(sqlite3.connect(db_path)) as con, con:
        assert con.execute("SELECT COUNT(*) FROM agent_event_cursors WHERE stream_id = ?", ("blackboard:atomic:section",)).fetchone()[0] == 0
        con.execute("DROP TRIGGER fail_blackboard_event")

    saved = board.update("atomic", "section", {"value": 2}, author="agent")
    events = state_store.events("blackboard:atomic:section")
    assert saved["success"] is True
    assert [event.kind for event in events] == ["blackboard.updated"]
    assert saved["section"]["version"] == events[0].payload["section"]["version"]


def test_blackboard_append_result_error_rolls_back_projection(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    board = BlackboardStore(db_path, state_store=state_store)
    monkeypatch.setattr(
        state_store,
        "append_in_transaction",
        lambda *args, **kwargs: AppendResult(seq=0, duplicate=False, error="append rejected"),
    )

    with pytest.raises(RuntimeError, match="append rejected"):
        board.update("atomic", "section", {"value": 1}, author="agent")

    assert board.get("atomic")["sections"] == {}
    assert state_store.events("blackboard:atomic:section") == []


def test_memory_append_result_error_rolls_back_projection(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    memory = MemoryStore(state_store)
    record = MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.REPOSITORY,
        scope_id="repo",
        key="append-error",
        value={"status": "verified"},
        evidence_ids=("evidence-1",),
    )
    monkeypatch.setattr(
        state_store,
        "append_in_transaction",
        lambda *args, **kwargs: AppendResult(seq=0, duplicate=False, error="append rejected"),
    )

    with pytest.raises(RuntimeError, match="append rejected"):
        memory.record(record)

    assert memory.count() == 0
    assert state_store.events(f"memory:{AgentScope.REPOSITORY.value}:append-error") == []


def test_swarm_append_result_error_rolls_back_projection(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    coordinator = SwarmCoordinator(db_path, state_store=state_store)
    monkeypatch.setattr(
        state_store,
        "append_in_transaction",
        lambda *args, **kwargs: AppendResult(seq=0, duplicate=False, error="append rejected"),
    )

    result = coordinator.dispatch("atomic dispatch", root=str(tmp_path))

    assert result["success"] is False
    assert "append rejected" in result["error"]
    with closing(sqlite3.connect(db_path)) as con:
        assert con.execute("SELECT COUNT(*) FROM agent_swarms").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM agent_events").fetchone()[0] == 0


def test_blackboard_retry_is_idempotent_and_rejects_key_collision(tmp_path):
    store = BlackboardStore(tmp_path / "agent_state.sqlite3", state_store=AgentStateStore(tmp_path / "agent_state.sqlite3"))
    first = store.update(
        "board-idem", "section", {"n": 1}, author="agent", expected_version=0,
        idempotency_key="board-operation",
    )
    retry = store.update(
        "board-idem", "section", {"n": 1}, author="agent", expected_version=0,
        idempotency_key="board-operation",
    )
    conflict = store.update(
        "board-idem", "section", {"n": 2}, author="agent", expected_version=0,
        idempotency_key="board-operation",
    )
    assert first["success"] is True
    assert retry["success"] is True and retry["duplicate"] is True
    assert conflict["success"] is False and conflict["idempotency_conflict"] is True
    assert store.get("board-idem", "section")["section"]["content"] == {"n": 1}


def test_schema_type_and_incomplete_group_mismatches_backup_without_repair(tmp_path):
    db_path = tmp_path / "durable.sqlite3"
    with closing(sqlite3.connect(db_path)) as con, con:
        con.execute("CREATE TABLE durable_record (record_id TEXT PRIMARY KEY, value TEXT NOT NULL)")
        con.execute("INSERT INTO durable_record VALUES ('keep', 'source')")

    with closing(sqlite3.connect(db_path)) as con:
        with pytest.raises(DurableSchemaMismatchError) as caught:
            validate_durable_schema(
                con,
                db_path,
                {"durable_record": [("record_id", "TEXT", 0, 1), ("value", "INTEGER", 1, 0)]},
            )
    assert caught.value.backup_path and caught.value.backup_path.exists()
    with closing(sqlite3.connect(db_path)) as con:
        assert con.execute("SELECT record_id, value FROM durable_record").fetchall() == [("keep", "source")]

    with closing(sqlite3.connect(db_path)) as con:
        with pytest.raises(DurableSchemaMismatchError, match="incomplete durable table group") as caught_group:
            validate_durable_schema(
                con,
                db_path,
                {"durable_record": ["record_id", "value"], "durable_relation": ["id"]},
                complete_groups=(("durable_record", "durable_relation"),),
            )
    assert caught_group.value.backup_path and caught_group.value.backup_path.exists()
    with closing(sqlite3.connect(db_path)) as con:
        assert con.execute("SELECT name FROM sqlite_master WHERE name = 'durable_relation'").fetchone() is None


def test_missing_memory_projection_with_durable_events_requires_recovery(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    store = AgentStateStore(db_path)
    memory = MemoryStore(store)
    memory.record(
        MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope=AgentScope.TASK,
            scope_id="task-preserve",
            key="durable",
            value={"keep": True},
        )
    )
    with closing(sqlite3.connect(db_path)) as con, con:
        con.execute("DROP TABLE agent_memory_records")
        con.execute("DROP TABLE agent_entity_relations")

    with pytest.raises(DurableSchemaMismatchError, match="related events remain") as caught:
        MemoryStore(AgentStateStore(db_path))
    assert caught.value.backup_path and caught.value.backup_path.exists()
    with closing(sqlite3.connect(db_path)) as con:
        assert con.execute(
            "SELECT COUNT(*) FROM agent_events WHERE kind = 'memory.recorded'"
        ).fetchone()[0] == 1
        assert con.execute(
            "SELECT name FROM sqlite_master WHERE name = 'agent_memory_records'"
        ).fetchone() is None


def test_missing_task_projection_with_durable_events_requires_recovery(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    tasks = TaskStore(state_store)
    tasks.create(
        GoalContract(goal="preserve durable task", acceptance_criteria=("tests",)),
        ScopeContext(task_id="task-projection-preserve"),
        task_id="task-projection-preserve",
    )
    with closing(sqlite3.connect(db_path)) as con, con:
        con.execute("DROP TABLE agent_tasks_projection")

    with pytest.raises(DurableSchemaMismatchError, match="related events remain") as caught:
        TaskStore(AgentStateStore(db_path))
    assert caught.value.backup_path and caught.value.backup_path.exists()
    with closing(sqlite3.connect(caught.value.backup_path)) as con:
        assert con.execute(
            "SELECT COUNT(*) FROM agent_events WHERE stream_id = ?",
            ("task:task-projection-preserve",),
        ).fetchone()[0] > 0
    with closing(sqlite3.connect(db_path)) as con:
        assert con.execute(
            "SELECT name FROM sqlite_master WHERE name = 'agent_tasks_projection'"
        ).fetchone() is None


def test_agent_event_queue_overflow_emits_replayable_gap_marker(tmp_path):
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    subscriber = store.subscribe(maxsize=1)
    first = store.append(AgentEvent.create("task:overflow", "task.updated", {"n": 1}))
    second = store.append(AgentEvent.create("task:overflow", "task.updated", {"n": 2}))

    assert first.seq == 1 and second.seq == 2
    marker = subscriber.get_nowait()
    store.unsubscribe(subscriber)
    assert marker.kind == "stream.gap"
    assert marker.payload["gap_ranges"] == [
        {"stream_id": "task:overflow", "from_seq": 1, "to_seq": 2}
    ]
    assert marker.payload["lost_count"] == 2
    assert marker.payload["replay_required"] is True
    assert marker.payload["cursor"] == 2
    assert store.event_page("task:overflow", after_seq=0)["last_seq"] == 2


def test_pubsub_replays_after_restart_and_rejects_idempotency_collision(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    first_store = AgentStateStore(db_path)
    bus = SwarmPubSub(first_store)
    published = bus.publish("T08", {"n": 1}, sender="agent", idempotency_key="publish-once")
    assert published["success"] is True and published["durable"] is True
    assert published["cursor"] == 1

    restarted = SwarmPubSub(AgentStateStore(db_path))
    replay = restarted.poll("t08", after_seq=0)
    assert replay["durable"] is True
    assert replay["messages"][0]["payload"] == {"n": 1}
    assert replay["messages"][0]["sequence"] == 1

    duplicate = restarted.publish("t08", {"n": 1}, sender="agent", idempotency_key="publish-once")
    assert duplicate["success"] is True and duplicate["duplicate"] is True
    collision = restarted.publish("t08", {"n": 2}, sender="agent", idempotency_key="publish-once")
    assert collision["success"] is False
    assert "idempotency key" in collision["error"]
    assert restarted.poll("t08", after_seq=0)["last_seq"] == 1

    with closing(sqlite3.connect(db_path)) as con, con:
        con.execute(
            "UPDATE agent_events SET created_at = ? WHERE stream_id = ? AND seq = 1",
            (time.time() - 3 * 86400, "pubsub:t08"),
        )
    restarted.publish("t08", {"n": 3}, sender="agent", idempotency_key="publish-after-retention")
    restarted.state_store.cleanup(retention_days=1)
    after_retention = restarted.poll("t08", after_seq=0)
    assert after_retention["gap_ranges"] == [{"from_seq": 1, "to_seq": 1}]
    assert [item["sequence"] for item in after_retention["messages"]] == [2]


def test_durable_pubsub_poll_preserves_event_page_failure(tmp_path, monkeypatch):
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    store._ensure_schema()
    failure = store._event_page_error(27)
    monkeypatch.setattr(store, "event_page", lambda **_kwargs: failure)

    result = SwarmPubSub(store).poll("unavailable", after_seq=27)

    assert result["success"] is False
    assert result["cursor"] == result["after_seq"] == 27
    assert result["messages"] == []
    assert result["error"] == failure["error"]


def test_pubsub_live_overflow_sends_gap_marker(tmp_path):
    bus = SwarmPubSub(AgentStateStore(tmp_path / "agent_state.sqlite3"))
    subscription, q = bus.subscribe("overflow", maxsize=10)
    for index in range(11):
        assert bus.publish("overflow", {"n": index})["success"]
    messages = [q.get_nowait() for _ in range(q.qsize())]
    marker = next(item for item in messages if item["kind"] == "pubsub.gap")
    assert marker["gap_ranges"] == [{"from_seq": 1, "to_seq": 2}]
    assert marker["payload"]["cursor"] == 11
    bus.unsubscribe("overflow", subscription)


def test_services_pubsub_uses_app_owned_durable_store(tmp_path, monkeypatch):
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    monkeypatch.setattr(SwarmPubSub, "_instance", None)
    services = object.__new__(LocalAIServices)
    services.set_agent_state(store)

    published = services.pubsub_publish("owned-topic", {"durable": True}, sender="test")
    replay = services.pubsub_poll("owned-topic", after_seq=0)

    assert published["success"] is True and published["durable"] is True
    assert replay["durable"] is True
    assert replay["messages"][0]["payload"] == {"durable": True}
    assert replay["messages"][0]["sequence"] == published["cursor"] == 1
    assert store.events("pubsub:owned-topic")[0].kind == "pubsub.message"


def test_verification_change_and_outcome_rows_rollback_with_events(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    store = AgentStateStore(db_path)
    verifications = VerificationStore(store)
    change = ChangeIntent.create("task-audit", ["module.py"], expected_impact="safe")
    with closing(sqlite3.connect(db_path)) as con, con:
        con.execute(
            "CREATE TRIGGER fail_change BEFORE INSERT ON agent_change_intents "
            "BEGIN SELECT RAISE(ABORT, 'change projection fault'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="change projection fault"):
        verifications.record_change(change)
    assert store.events("change:task-audit") == []
    with closing(sqlite3.connect(db_path)) as con, con:
        assert con.execute("SELECT COUNT(*) FROM agent_change_intents").fetchone()[0] == 0
        con.execute("DROP TRIGGER fail_change")

    verifications.record_change(change)
    outcome = OutcomeRecord.reverted(change.change_id, task_id=change.task_id)
    with closing(sqlite3.connect(db_path)) as con, con:
        con.execute(
            "CREATE TRIGGER fail_outcome BEFORE INSERT ON agent_outcomes "
            "BEGIN SELECT RAISE(ABORT, 'outcome projection fault'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="outcome projection fault"):
        verifications.record_outcome(outcome)
    assert store.events(f"outcome:{change.change_id}") == []
    with closing(sqlite3.connect(db_path)) as con, con:
        assert con.execute("SELECT COUNT(*) FROM agent_outcomes").fetchone()[0] == 0


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
def test_blackboard_delete_projection_and_event_share_transaction(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    board = BlackboardStore(db_path, state_store=state_store)
    board.update("delete-board", "section", {"value": 1}, author="agent")
    with closing(sqlite3.connect(db_path)) as con, con:
        con.execute(
            "CREATE TRIGGER fail_blackboard_delete BEFORE INSERT ON agent_events "
            "WHEN NEW.kind = 'blackboard.deleted' "
            "BEGIN SELECT RAISE(ABORT, 'blackboard delete event fault'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="blackboard delete event fault"):
        board.delete("delete-board", "section")
    assert board.get("delete-board", "section")["success"] is True
    assert [event.kind for event in state_store.events("blackboard:delete-board:section")].count(
        "blackboard.deleted"
    ) == 0

    with closing(sqlite3.connect(db_path)) as con, con:
        con.execute("DROP TRIGGER fail_blackboard_delete")
    result = board.delete("delete-board", "section")
    assert result["deleted_count"] == 1
    assert board.get("delete-board", "section")["success"] is False
    assert [event.kind for event in state_store.events("blackboard:delete-board:section")][-1] == "blackboard.deleted"


def test_swarm_expected_version_allows_one_parallel_step(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    coordinator = SwarmCoordinator(db_path, state_store=state_store)
    dispatched = coordinator.dispatch("parallel step CAS", root=str(tmp_path))
    swarm_id = dispatched["swarm_id"]
    barrier = threading.Barrier(3)

    def step(value):
        barrier.wait(timeout=2)
        return coordinator.step(
            swarm_id,
            "Coder",
            "submit_patch",
            {"value": value},
            expected_version=dispatched["version"],
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(step, "one")
        second = pool.submit(step, "two")
        barrier.wait(timeout=2)
        results = [first.result(timeout=5), second.result(timeout=5)]

    assert sum(result["success"] for result in results) == 1
    assert sum(result.get("version_conflict", False) for result in results) == 1
    status = coordinator.get_status(swarm_id)
    assert status["state"] == SwarmState.TESTING.value
    assert status["version"] == dispatched["version"] + 1
    assert len([event for event in state_store.events(f"swarm:{swarm_id}") if event.kind == "swarm.step"]) == 1


def test_swarm_verification_failure_rolls_back_step_without_receipt(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    tasks = TaskStore(state_store)
    blackboard = BlackboardStore(db_path, state_store=state_store)
    verifications = VerificationStore(state_store, task_store=tasks)
    coordinator = SwarmCoordinator(
        db_path,
        blackboard=blackboard,
        verifications=verifications,
        state_store=state_store,
    )
    swarm_id = coordinator.dispatch("atomic reviewer receipt", root=str(tmp_path))["swarm_id"]
    assert coordinator.step(swarm_id, "Coder", "submit_patch", {"patch": "safe"})["success"]
    assert coordinator.step(
        swarm_id,
        "Tester",
        "report_test_results",
        {"passed": True, "output": "focused check passed"},
    )["state"] == SwarmState.REVIEWING.value

    with closing(sqlite3.connect(db_path)) as con, con:
        con.execute(
            "CREATE TRIGGER fail_swarm_receipt BEFORE INSERT ON agent_verification_receipts "
            "BEGIN SELECT RAISE(ABORT, 'swarm receipt fault'); END"
        )
    failed = coordinator.step(swarm_id, "Reviewer", "approve", {"review": "approve"})
    assert failed["success"] is False
    assert "swarm receipt fault" in failed["error"]
    status = coordinator.get_status(swarm_id)
    assert status["state"] == SwarmState.REVIEWING.value
    assert status["receipt_id"] is None
    assert len(status["history"]) == 3
    assert blackboard.get(f"swarm:{swarm_id}", "review")["success"] is False
    assert state_store.events(f"verification:{swarm_id}") == []
    assert [event.kind for event in state_store.events(f"swarm:{swarm_id}")].count("swarm.step") == 2


def test_swarm_cancel_is_atomic_cas_and_idempotent(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    coordinator = SwarmCoordinator(db_path, state_store=state_store)
    dispatched = coordinator.dispatch("atomic cancel", root=str(tmp_path))
    swarm_id = dispatched["swarm_id"]
    with closing(sqlite3.connect(db_path)) as con, con:
        con.execute(
            "CREATE TRIGGER fail_cancel_event BEFORE INSERT ON agent_events "
            "WHEN NEW.kind = 'swarm.cancelled' "
            "BEGIN SELECT RAISE(ABORT, 'cancel event fault'); END"
        )

    failed = coordinator.cancel(swarm_id, "operator stop", expected_version=dispatched["version"])
    assert failed["success"] is False
    assert "cancel event fault" in failed["error"]
    assert coordinator.get_status(swarm_id)["state"] == SwarmState.CODING.value
    assert coordinator.get_status(swarm_id)["version"] == dispatched["version"]
    assert [event.kind for event in state_store.events(f"swarm:{swarm_id}")].count("swarm.cancelled") == 0

    with closing(sqlite3.connect(db_path)) as con, con:
        con.execute("DROP TRIGGER fail_cancel_event")
    cancelled = coordinator.cancel(swarm_id, "operator stop", expected_version=dispatched["version"])
    repeated = coordinator.cancel(swarm_id, "operator stop", expected_version=dispatched["version"])
    changed_request = coordinator.cancel(swarm_id, "operator stop")
    assert cancelled["success"] is True
    assert cancelled["version"] == dispatched["version"] + 1
    assert repeated["success"] is True and repeated["duplicate"] is True
    assert changed_request["success"] is False
    assert changed_request["idempotency_conflict"] is True
    assert [event.kind for event in state_store.events(f"swarm:{swarm_id}")].count("swarm.cancelled") == 1


def test_duplicate_swarm_cancel_retries_pending_lease_release(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    coordinator = SwarmCoordinator(db_path, state_store=AgentStateStore(db_path))
    swarm_id = coordinator.dispatch("retry lease release", root=str(tmp_path))["swarm_id"]
    release_attempts = []

    def release_once_then_succeed(value):
        release_attempts.append(value)
        return len(release_attempts) > 1

    coordinator._release_all_leases = release_once_then_succeed
    first = coordinator.cancel(swarm_id, "operator stop")
    repeated = coordinator.cancel(swarm_id, "operator stop")

    assert first["lease_release_pending"] is True
    assert repeated["success"] is True and repeated["duplicate"] is True
    assert "lease_release_pending" not in repeated
    assert release_attempts == [swarm_id, swarm_id]


def test_relation_event_failure_rolls_back_relation_projection(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    memory = MemoryStore(state_store)
    with closing(sqlite3.connect(db_path)) as con, con:
        con.execute(
            "CREATE TRIGGER fail_relation_event BEFORE INSERT ON agent_events "
            "WHEN NEW.kind = 'relation.recorded' "
            "BEGIN SELECT RAISE(ABORT, 'relation event fault'); END"
        )

    with pytest.raises(sqlite3.IntegrityError, match="relation event fault"):
        memory.record_relation("source", "relates_to", "target")

    with closing(sqlite3.connect(db_path)) as con:
        assert con.execute("SELECT COUNT(*) FROM agent_entity_relations").fetchone()[0] == 0
    assert state_store.events("relation:source:target") == []


def test_compaction_event_failure_rolls_back_digest_sources_and_relations(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    memory = MemoryStore(state_store)
    source_ids = []
    for index in range(2):
        saved = memory.record(
            MemoryRecord.create(
                kind=MemoryKind.FACT,
                scope=AgentScope.TASK,
                scope_id="task-atomic-compact",
                key=f"fact-{index}",
                value={"index": index},
            )
        )
        source_ids.append(saved.record_id)

    with closing(sqlite3.connect(db_path)) as con, con:
        con.execute(
            "CREATE TRIGGER fail_compaction_event BEFORE INSERT ON agent_events "
            "WHEN NEW.kind = 'memory.compacted' "
            "BEGIN SELECT RAISE(ABORT, 'compaction event fault'); END"
        )

    with pytest.raises(sqlite3.IntegrityError, match="compaction event fault"):
        memory.compact(min_records=2, actor="test")

    with closing(sqlite3.connect(db_path)) as con:
        assert con.execute(
            "SELECT COUNT(*) FROM agent_memory_records WHERE key LIKE 'compacted_fact_%'"
        ).fetchone()[0] == 0
        source_rows = con.execute(
            "SELECT status, supersedes_record_id FROM agent_memory_records "
            "WHERE record_id IN (?, ?)",
            source_ids,
        ).fetchall()
        assert len(source_rows) == 2
        assert all(status == "active" and supersedes is None for status, supersedes in source_rows)
        assert con.execute(
            "SELECT COUNT(*) FROM agent_entity_relations WHERE relation = 'compacted_into'"
        ).fetchone()[0] == 0
    with closing(sqlite3.connect(db_path)) as con:
        assert con.execute(
            "SELECT COUNT(*) FROM agent_events WHERE kind = 'memory.compacted'"
        ).fetchone()[0] == 0


@pytest.mark.parametrize("filename", ["agent_state.sqlite3", "leases.sqlite3", "agent_blackboard.sqlite3"])
def test_legacy_only_durable_state_is_rejected_without_writes(tmp_path, filename):
    from local_ai_hub.sqlite_support import (
        UnsupportedLegacyStateDatabase,
        require_canonical_agent_state_database,
    )

    legacy = tmp_path / filename
    legacy.write_bytes(b"preserve legacy state")

    with pytest.raises(UnsupportedLegacyStateDatabase, match="unsupported legacy durable state database"):
        require_canonical_agent_state_database(tmp_path)

    assert legacy.read_bytes() == b"preserve legacy state"
    assert not (tmp_path / "agent_state.sqlite").exists()


def test_archived_legacy_database_does_not_block_canonical_state(tmp_path):
    from local_ai_hub.sqlite_support import require_canonical_agent_state_database

    canonical = tmp_path / "agent_state.sqlite"
    with closing(sqlite3.connect(canonical)) as con, con:
        con.execute("CREATE TABLE canonical_marker (value TEXT)")
    archived = tmp_path / "leases.sqlite3"
    archived.write_bytes(b"preserve archived state")

    assert require_canonical_agent_state_database(tmp_path) == canonical
    assert archived.read_bytes() == b"preserve archived state"


@pytest.mark.parametrize("canonical_kind", ["zero", "corrupt", "directory"])
def test_invalid_canonical_path_does_not_hide_legacy_state(tmp_path, canonical_kind):
    from local_ai_hub.sqlite_support import (
        UnsupportedLegacyStateDatabase,
        require_canonical_agent_state_database,
    )

    canonical = tmp_path / "agent_state.sqlite"
    if canonical_kind == "zero":
        canonical.touch()
    elif canonical_kind == "corrupt":
        canonical.write_bytes(b"SQLite format 3\x00" + bytes(84))
    else:
        canonical.mkdir()

    legacy = tmp_path / "leases.sqlite3"
    with closing(sqlite3.connect(legacy)) as con, con:
        con.execute("CREATE TABLE leases (lease_id TEXT PRIMARY KEY)")
        con.execute("INSERT INTO leases VALUES ('keep')")
    legacy_before = legacy.read_bytes()
    canonical_before = None if canonical.is_dir() else canonical.read_bytes()

    with pytest.raises(UnsupportedLegacyStateDatabase, match="canonical database is missing or not a readable SQLite file"):
        require_canonical_agent_state_database(tmp_path)

    assert legacy.read_bytes() == legacy_before
    assert canonical.exists()
    assert canonical.is_dir() == (canonical_kind == "directory")
    if canonical_before is not None:
        assert canonical.read_bytes() == canonical_before


def test_wal_canonical_probe_uses_immutable_mode_without_sidecars(tmp_path):
    from local_ai_hub.sqlite_support import require_canonical_agent_state_database

    canonical = tmp_path / "agent_state.sqlite"
    with closing(sqlite3.connect(canonical)) as con, con:
        assert con.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower() == "wal"
        con.execute("CREATE TABLE canonical_marker (value TEXT)")
        con.execute("INSERT INTO canonical_marker VALUES ('keep')")
    legacy = tmp_path / "leases.sqlite3"
    legacy.write_bytes(b"archived legacy state")
    wal_path = Path(f"{canonical}-wal")
    shm_path = Path(f"{canonical}-shm")
    assert not wal_path.exists() and not shm_path.exists()

    assert require_canonical_agent_state_database(tmp_path) == canonical

    assert not wal_path.exists() and not shm_path.exists()
    assert legacy.read_bytes() == b"archived legacy state"


@pytest.mark.parametrize("sidecar_name", ["agent_state.sqlite-wal", "agent_state.sqlite-shm"])
def test_wal_canonical_probe_rejects_incomplete_sidecars_without_creating_files(tmp_path, sidecar_name):
    from local_ai_hub.sqlite_support import (
        UnsupportedLegacyStateDatabase,
        require_canonical_agent_state_database,
    )

    canonical = tmp_path / "agent_state.sqlite"
    with closing(sqlite3.connect(canonical)) as con, con:
        assert con.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower() == "wal"
        con.execute("CREATE TABLE canonical_marker (value TEXT)")
    legacy = tmp_path / "leases.sqlite3"
    legacy.write_bytes(b"archived legacy state")
    legacy_before = legacy.read_bytes()
    canonical_before = canonical.read_bytes()
    sidecar = tmp_path / sidecar_name
    sidecar.write_bytes(b"existing sidecar")
    missing_sidecar = tmp_path / (
        "agent_state.sqlite-shm" if sidecar_name.endswith("-wal") else "agent_state.sqlite-wal"
    )

    with pytest.raises(UnsupportedLegacyStateDatabase, match="canonical database is missing or not a readable SQLite file"):
        require_canonical_agent_state_database(tmp_path)

    assert sidecar.read_bytes() == b"existing sidecar"
    assert not missing_sidecar.exists()
    assert canonical.read_bytes() == canonical_before
    assert legacy.read_bytes() == legacy_before


def test_legacy_lease_wait_schema_is_rejected_before_schema_changes(tmp_path):
    from local_ai_hub.leases import ScopeLeaseStore

    canonical = tmp_path / "agent_state.sqlite"
    with closing(sqlite3.connect(canonical)) as con, con:
        con.execute("""CREATE TABLE lease_waits (
            tenant TEXT NOT NULL, blocked_by TEXT NOT NULL, root_id TEXT NOT NULL,
            requested_path TEXT NOT NULL, updated_at REAL NOT NULL,
            PRIMARY KEY(tenant, blocked_by, requested_path))""")
    with closing(sqlite3.connect(canonical)) as con:
        before = con.execute("SELECT sql FROM sqlite_master WHERE name='lease_waits'").fetchone()[0]
    before_bytes = canonical.read_bytes()

    with pytest.raises(DurableSchemaMismatchError):
        ScopeLeaseStore(tmp_path)

    with closing(sqlite3.connect(canonical)) as con:
        after = con.execute("SELECT sql FROM sqlite_master WHERE name='lease_waits'").fetchone()[0]
    assert after == before
    assert canonical.read_bytes() == before_bytes
    assert not list(tmp_path.glob("agent_state.sqlite.schema-mismatch-*.sqlite3"))


def test_lease_view_name_is_rejected_before_writes(tmp_path):
    from local_ai_hub.leases import ScopeLeaseStore

    canonical = tmp_path / "agent_state.sqlite"
    with closing(sqlite3.connect(canonical)) as con, con:
        con.execute("CREATE VIEW leases AS SELECT 'lease' AS lease_id")
    before = canonical.read_bytes()

    with pytest.raises(DurableSchemaMismatchError, match="unsupported durable schema object type for leases: view"):
        ScopeLeaseStore(tmp_path)

    assert canonical.read_bytes() == before
    assert not list(tmp_path.glob("agent_state.sqlite.schema-mismatch-*.sqlite3"))


def test_partial_lease_table_group_is_rejected_before_writes(tmp_path):
    from local_ai_hub.leases import ScopeLeaseStore

    canonical = tmp_path / "agent_state.sqlite"
    with closing(sqlite3.connect(canonical)) as con, con:
        con.execute("""CREATE TABLE leases (
            lease_id TEXT NOT NULL, tenant TEXT NOT NULL, root_id TEXT NOT NULL,
            root_path TEXT NOT NULL, path TEXT NOT NULL, purpose TEXT NOT NULL,
            created_at REAL NOT NULL, expires_at REAL NOT NULL,
            PRIMARY KEY(lease_id, path))""")
    before = canonical.read_bytes()

    with pytest.raises(DurableSchemaMismatchError, match="incomplete durable table group; missing=lease_waits"):
        ScopeLeaseStore(tmp_path)

    assert canonical.read_bytes() == before
    assert not list(tmp_path.glob("agent_state.sqlite.schema-mismatch-*.sqlite3"))


def test_oversized_expected_schema_definition_is_rejected_without_backup(tmp_path):
    canonical = tmp_path / "agent_state.sqlite"
    ddl = "CREATE TABLE leases (lease_id TEXT /*" + ("x" * 8200) + "*/ )"
    with closing(sqlite3.connect(canonical)) as con, con:
        con.execute(ddl)
    before = canonical.read_bytes()

    with closing(sqlite3.connect(canonical)) as con:
        with pytest.raises(
            DurableSchemaMismatchError,
            match="durable table definition exceeds 8192 bytes: leases",
        ):
            validate_durable_schema(
                con,
                canonical,
                {"leases": ["lease_id"]},
                backup_on_mismatch=False,
            )

    assert canonical.read_bytes() == before
    assert not list(tmp_path.glob("agent_state.sqlite.schema-mismatch-*.sqlite3"))


def test_cache_rebuild_does_not_erase_agent_state_records(tmp_path):
    agent_state = tmp_path / "agent_state.sqlite"
    cache_db = tmp_path / "cache.sqlite"
    with closing(sqlite3.connect(agent_state)) as con, con:
        con.execute("CREATE TABLE durable_record (record_id TEXT PRIMARY KEY)")
        con.execute("INSERT INTO durable_record VALUES ('keep')")
    cache_db.write_bytes(b"damaged disposable cache")

    cache = SQLiteCache(cache_db, "t08-cache-isolation")
    cache.set("rebuilt", {"ready": True})

    assert cache.get("rebuilt") == {"ready": True}
    with closing(sqlite3.connect(agent_state)) as con:
        assert con.execute("SELECT record_id FROM durable_record").fetchall() == [("keep",)]
    assert len(list(tmp_path.glob("cache.sqlite.corrupt-*"))) == 1
