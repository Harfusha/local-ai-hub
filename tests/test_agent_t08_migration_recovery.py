import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from local_ai_hub.agent_events import AgentEvent, AgentStateStore
from local_ai_hub.sqlite_support import DurableSchemaMismatchError
from local_ai_hub.agent_identity import AgentScope
from local_ai_hub.agent_memory import MemoryKind, MemoryRecord, MemoryStore
from local_ai_hub.agent_tasks import GoalContract, ScopeContext, TaskStore
from local_ai_hub.agent_verification import VerificationReceipt, VerificationStore


def _seed_durable_state(db_path):
    state = AgentStateStore(db_path)
    tasks = TaskStore(state)
    task = tasks.create(
        GoalContract(goal="preserve durable state", acceptance_criteria=("migration",)),
        ScopeContext(task_id="t08-migration-task"),
        task_id="t08-migration-task",
    )
    event = state.append(
        AgentEvent.create(
            "t08-migration-stream",
            "t08.migration.seeded",
            {"preserve": True},
            "t08-migration-event",
        )
    ).event
    memory = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.TASK,
        scope_id=task.task_id,
        key="t08-migration-memory",
        value="preserved memory",
        source="T08 migration recovery test",
        provenance={
            "root": str(db_path.parent / "memory-repo"),
            "tenant": "t08-migration-tenant",
        },
    )
    MemoryStore(state).record(memory, actor="test")
    receipt = VerificationReceipt.create(
        task_id=task.task_id,
        criterion="migration",
        passed=True,
        evidence_id="t08-migration-evidence",
    )
    VerificationStore(state, task_store=tasks).record(receipt)
    return task, event, memory, receipt


def _mark_incompatible_database_version(db_path):
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute("PRAGMA user_version=0")
        connection.commit()

def _sqlite_file_snapshot(db_path):
    paths = (db_path, *[Path(f"{db_path}{suffix}") for suffix in ("-wal", "-shm", "-journal")])
    return tuple(path.read_bytes() if path.is_file() else None for path in paths)


def _assert_rows_exist(connection, task, event, memory, receipt):
    assert connection.execute(
        "SELECT task_id FROM agent_tasks_projection WHERE task_id=?", (task.task_id,)
    ).fetchone() == (task.task_id,)
    assert connection.execute(
        "SELECT event_id FROM agent_events WHERE event_id=?", (event.event_id,)
    ).fetchone() == (event.event_id,)
    assert connection.execute(
        "SELECT record_id FROM agent_memory_records WHERE record_id=?", (memory.record_id,)
    ).fetchone() == (memory.record_id,)
    assert connection.execute(
        "SELECT receipt_id FROM agent_verification_receipts WHERE receipt_id=?",
        (receipt.receipt_id,),
    ).fetchone() == (receipt.receipt_id,)


def test_current_schema_reopen_preserves_agent_state(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    task, event, memory, receipt = _seed_durable_state(db_path)

    reopened = AgentStateStore(db_path)
    assert reopened.events(event.stream_id) == [event]
    assert TaskStore(reopened).get(task.task_id).contract.goal == "preserve durable state"
    assert MemoryStore(reopened).get(
        memory.record_id,
        scope=AgentScope.TASK,
        scope_id=task.task_id,
        task_id=task.task_id,
        root=memory.provenance["root"],
        tenant=memory.provenance["tenant"],
    ).value == "preserved memory"
    with closing(sqlite3.connect(db_path)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (1,)
        assert "agent_event_schema_versions" not in {
            row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        _assert_rows_exist(connection, task, event, memory, receipt)
    assert not list(tmp_path.glob("*.bak"))


def test_incompatible_database_version_rejects_without_backup_or_writes(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    task, event, memory, receipt = _seed_durable_state(db_path)
    _mark_incompatible_database_version(db_path)
    before = _sqlite_file_snapshot(db_path)

    with pytest.raises(DurableSchemaMismatchError):
        AgentStateStore(db_path).events(event.stream_id)

    assert _sqlite_file_snapshot(db_path) == before
    assert not list(tmp_path.glob("*.bak"))
    with closing(sqlite3.connect(db_path)) as connection:
        _assert_rows_exist(connection, task, event, memory, receipt)


def test_incompatible_incident_schema_rejects_without_backup_or_writes(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    state = AgentStateStore(db_path)
    state.append(AgentEvent.create("incident-migration", "test.seeded", {"seed": True}, "incident-schema-seed"))
    with closing(sqlite3.connect(db_path)) as connection:
        connection.executescript(
            """
            CREATE TABLE agent_incidents (
                incident_id TEXT PRIMARY KEY,
                operation_class TEXT NOT NULL,
                error_class TEXT NOT NULL,
                signature_hash TEXT NOT NULL,
                redacted_message TEXT NOT NULL,
                state_revision TEXT NOT NULL,
                attempts INTEGER NOT NULL,
                evidence_ids TEXT NOT NULL,
                root_cause TEXT,
                verified_fix TEXT,
                confidence REAL NOT NULL,
                resolved INTEGER NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                expires_at REAL,
                affected_paths TEXT NOT NULL DEFAULT '[]',
                ignored INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX idx_agent_incidents_fp
                ON agent_incidents (error_class, operation_class, signature_hash, state_revision);
            CREATE INDEX idx_agent_incidents_lookup
                ON agent_incidents (operation_class, signature_hash, state_revision, updated_at DESC);
            CREATE INDEX idx_agent_incidents_recent
                ON agent_incidents (operation_class, signature_hash, updated_at DESC);
            INSERT INTO agent_incidents VALUES (
                'legacy-incident-migration', 'validation', 'TestError', 'sha256:test',
                'redacted failure', 'revision-1', 1, '[]', NULL, NULL, 0.25, 0, 1.0, 1.0, NULL, '[]', 0
            );
            """
        )
        connection.commit()
    before = _sqlite_file_snapshot(db_path)

    with pytest.raises(DurableSchemaMismatchError):
        AgentStateStore(db_path)._preflight_schema_read_only()

    assert _sqlite_file_snapshot(db_path) == before
    assert not list(tmp_path.glob("*.bak"))

def test_schema_preflight_accepts_concurrent_agent_state_writes(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_state.sqlite3"
    _seed_durable_state(db_path)
    store = AgentStateStore(db_path)
    classify = AgentStateStore._classify_schema
    wrote = False

    def classify_with_concurrent_write(connection):
        nonlocal wrote
        result = classify(connection)
        if not wrote:
            wrote = True
            with closing(sqlite3.connect(db_path)) as writer:
                writer.execute(
                    "INSERT INTO agent_event_cursors(stream_id, last_seq, first_retained_seq) "
                    "VALUES (?, 0, 1)",
                    ("concurrent-preflight-writer",),
                )
                writer.commit()
        return result

    monkeypatch.setattr(store, "_classify_schema", classify_with_concurrent_write)

    store._ensure_schema()

    assert wrote
