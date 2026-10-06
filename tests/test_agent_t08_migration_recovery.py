import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from local_ai_hub.agent_events import AgentEvent, AgentStateStore
from local_ai_hub.agent_identity import AgentScope
from local_ai_hub.agent_memory import MemoryKind, MemoryRecord, MemoryStore
from local_ai_hub.agent_tasks import GoalContract, ScopeContext, TaskStore
from local_ai_hub.agent_verification import VerificationReceipt, VerificationStore


def _seed_durable_state(db_path):
    state = AgentStateStore(db_path)
    repository_root = str(Path(db_path).parent)
    tenant = "t08-migration-tenant"
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
        provenance={"root": repository_root, "tenant": tenant},
    )
    MemoryStore(state).record(memory, actor="test")
    receipt = VerificationReceipt.create(
        task_id=task.task_id,
        criterion="migration",
        passed=True,
        evidence_id="t08-migration-evidence",
    )
    VerificationStore(state, task_store=tasks).record(receipt)
    return task, event, memory, receipt, repository_root, tenant


def _downgrade_to_unversioned_v0(db_path):
    with closing(sqlite3.connect(db_path)) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(agent_events)")}
        if "schema_version" in columns:
            connection.execute("ALTER TABLE agent_events DROP COLUMN schema_version")
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        for table in ("agent_event_schema_versions", "agent_schema_migrations"):
            if table in tables:
                connection.execute(f'DROP TABLE "{table}"')
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


def test_versioned_migration_backup_restart_preserves_agent_state(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    task, event, memory, receipt, repository_root, tenant = _seed_durable_state(db_path)
    _downgrade_to_unversioned_v0(db_path)

    migrated = AgentStateStore(db_path)
    assert migrated.events(event.stream_id) == [event]
    backup_paths = list(tmp_path.glob("agent_state.sqlite3.migration-v0-v1-*.bak"))
    assert len(backup_paths) == 1
    with closing(sqlite3.connect(backup_paths[0])) as backup:
        assert backup.execute("PRAGMA quick_check").fetchone() == ("ok",)
        assert backup.execute("PRAGMA user_version").fetchone() == (0,)
        _assert_rows_exist(backup, task, event, memory, receipt)

    with closing(sqlite3.connect(db_path)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (1,)
        _assert_rows_exist(connection, task, event, memory, receipt)

    restarted = AgentStateStore(db_path)
    assert TaskStore(restarted).get(task.task_id).contract.goal == "preserve durable state"
    assert restarted.events(event.stream_id) == [event]
    memory_store = MemoryStore(restarted)
    restored_memory = memory_store.get(
        memory.record_id,
        scope=AgentScope.TASK,
        scope_id=task.task_id,
        task_id=task.task_id,
        root=repository_root,
        tenant=tenant,
    )
    assert restored_memory is not None
    assert restored_memory.value == "preserved memory"
    with closing(sqlite3.connect(db_path)) as connection:
        _assert_rows_exist(connection, task, event, memory, receipt)


def test_migration_backup_timeout_preserves_durable_state_bytes(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_state.sqlite3"
    task, event, memory, receipt, _, _ = _seed_durable_state(db_path)
    _downgrade_to_unversioned_v0(db_path)
    before = _sqlite_file_snapshot(db_path)
    monkeypatch.setattr(
        AgentStateStore,
        "_MIGRATION_BACKUP_TIMEOUT_SECONDS",
        0.0,
        raising=False,
    )

    with pytest.raises(TimeoutError, match="backup time limit"):
        AgentStateStore(db_path).events(event.stream_id)

    assert _sqlite_file_snapshot(db_path) == before
    with closing(sqlite3.connect(db_path)) as connection:
        _assert_rows_exist(connection, task, event, memory, receipt)


def test_legacy_incident_schema_is_allowlisted_and_preserved_on_migration(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    state = AgentStateStore(db_path)
    state.append(
        AgentEvent.create(
            "incident-migration", "test.seeded", {"seed": True}, "incident-schema-seed"
        )
    )
    incident_key = ("table", "agent_incidents", "agent_incidents")
    recognized_hashes = {
        AgentStateStore._EXPECTED_OBJECT_SQL_HASHES[incident_key],
        *AgentStateStore._ALTERNATE_OBJECT_SQL_HASHES.get(incident_key, set()),
    }
    assert recognized_hashes == {
        "6ea9770af294cd83e1fd6dcc80a0c7950bc93d142c27d40996c5acf5a0b478d4",
        "a2be58a71724133b64d9a7a773680a193488f64414ee245e378b06973454e420",
        "43c461c1906a1c11a5558889e2c49478942b940c3e98d0a926848ead3010a63e",
        "b3f8fa5c1723ab3addf421e28c3e9e07d232a7734cc95c247aed04224f3856b0",
    }
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
            INSERT INTO agent_incidents (
                incident_id, operation_class, error_class, signature_hash,
                redacted_message, state_revision, attempts, evidence_ids,
                confidence, resolved, created_at, updated_at
            ) VALUES (
                'legacy-incident-migration', 'validation', 'TestError', 'sha256:test',
                'redacted failure', 'revision-1', 1, '[]', 0.25, 0, 1.0, 1.0
            );
            """
        )
        sql = " ".join(
            str(connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='agent_incidents'"
            ).fetchone()[0]).split()
        ).casefold()
        assert hashlib.sha256(sql.encode("utf-8")).hexdigest() == (
            "6ea9770af294cd83e1fd6dcc80a0c7950bc93d142c27d40996c5acf5a0b478d4"
        )
        assert hashlib.sha256(sql.encode("utf-8")).hexdigest() in recognized_hashes
        connection.commit()
    _downgrade_to_unversioned_v0(db_path)

    migrated = AgentStateStore(db_path)
    assert [event.kind for event in migrated.events("incident-migration")] == ["test.seeded"]
    backups = list(tmp_path.glob("agent_state.sqlite3.migration-v0-v1-*.bak"))
    assert len(backups) == 1
    for path in (db_path, backups[0]):
        with closing(sqlite3.connect(path)) as connection:
            assert connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
            assert connection.execute(
                "SELECT incident_id, redacted_message FROM agent_incidents WHERE incident_id=?",
                ("legacy-incident-migration",),
            ).fetchone() == ("legacy-incident-migration", "redacted failure")
    assert migrated.enabled is True


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
