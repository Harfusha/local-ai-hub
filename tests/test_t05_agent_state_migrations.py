from __future__ import annotations

from contextlib import closing
import hashlib
import json
import os
import sqlite3
import subprocess
from pathlib import Path

import pytest

from local_ai_hub import agent_events as agent_events_module
from local_ai_hub.agent_events import AgentEvent, AgentStateStore
from local_ai_hub.agent_blackboard import BlackboardStore
from local_ai_hub.agent_context import ContextCompiler
from local_ai_hub.agent_identity import AgentScope
from local_ai_hub.agent_incidents import IncidentStore
from local_ai_hub.agent_learning import LearningStore
from local_ai_hub.leases import ScopeLeaseStore
from local_ai_hub.agent_memory import MemoryKind, MemoryRecord, MemoryStore
from local_ai_hub.agent_policy import PolicyEngine
from local_ai_hub.agent_tasks import GoalContract, ScopeContext, TaskStore
from local_ai_hub.agent_verification import VerificationReceipt, VerificationStore


class _MigrationArtifactStore:
    def __init__(self, task):
        self.task = task

    def get(self, artifact_id, *, max_chars, tenant):
        proof = {
            "passed": True,
            "kind": "work_source_review",
            "criteria": ["migration"],
            "task_id": self.task.task_id,
            "owner": tenant,
            "repository_revision": "",
            "mutation_generation": 0,
        }
        return {
            "success": True,
            "artifact_id": artifact_id,
            "kind": "source_review",
            "next_offset": None,
            "text": json.dumps(proof),
        }


def _seed_state(db_path):
    state = AgentStateStore(db_path)
    tasks = TaskStore(state)
    task = tasks.create(
        GoalContract(goal="preserve durable records", acceptance_criteria=("migration",)),
        ScopeContext(task_id="migration-task"),
        task_id="migration-task",
    )
    event = AgentEvent.create(
        "migration-stream",
        "migration.seeded",
        {"sentinel": "durable event"},
        "migration-event-key",
    )
    assert state.append(event).event == event.with_seq(1)
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute(
            "INSERT INTO agent_snapshots(stream_id, seq, state, created_at) VALUES (?, ?, ?, ?)",
            (event.stream_id, 1, '{"snapshot":"durable"}', 1.0),
        )
        connection.commit()

    memory = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.TASK,
        scope_id=task.task_id,
        key="migration-memory",
        value="durable memory",
        source="test",
        provenance={
            "root": str(db_path.parent / "memory-repo"),
            "tenant": "migration-tenant",
        },
    )
    # Seed durable projection directly; event-writer integration belongs to T08.
    MemoryStore(state)._save_record(memory)

    verifications = VerificationStore(state, task_store=tasks, artifact_store=_MigrationArtifactStore(task))
    receipt = VerificationReceipt.create(
        task_id=task.task_id,
        criterion="migration",
        passed=True,
        evidence_id="migration-evidence",
    )
    verifications.record(receipt)
    BlackboardStore(db_path)
    ContextCompiler(state)
    IncidentStore(state)
    LearningStore(state)
    PolicyEngine(state)
    return task, event, memory


def _assert_state_survives(db_path, task, event, memory):
    state = AgentStateStore(db_path)
    tasks = TaskStore(state)
    assert tasks.get(task.task_id).contract.goal == "preserve durable records"
    assert state.events(event.stream_id) == [event.with_seq(1)]
    with closing(sqlite3.connect(db_path)) as connection:
        assert connection.execute(
            "SELECT state FROM agent_snapshots WHERE stream_id=? AND seq=1",
            (event.stream_id,),
        ).fetchone()[0] == '{"snapshot":"durable"}'
    row = None
    with closing(sqlite3.connect(db_path)) as connection:
        row = connection.execute(
            "SELECT scope, scope_id, provenance FROM agent_memory_records WHERE record_id=?",
            (memory.record_id,),
        ).fetchone()
    assert row is not None
    assert row[0:2] == (AgentScope.TASK.value, task.task_id)
    assert json.loads(row[2]) == dict(memory.provenance)

    memory_store = MemoryStore(state)
    assert memory_store.get(
        memory.record_id,
        scope=AgentScope.TASK,
        scope_id=task.task_id,
    ) is None
    assert memory_store.get(
        memory.record_id,
        scope=AgentScope.TASK,
        scope_id=task.task_id,
        task_id=task.task_id,
        root=memory.provenance["root"],
        tenant=memory.provenance["tenant"],
    ).value == "durable memory"
    assert VerificationStore(state, task_store=tasks, artifact_store=_MigrationArtifactStore(task)).completion(task.task_id).complete is True


def _backup_for(db_path):
    backups = list(db_path.parent.glob(f"{db_path.name}.migration-v0-v1-*.bak"))
    assert len(backups) == 1
    return backups[0]


def _sqlite_file_snapshot(db_path):
    paths = (
        db_path,
        Path(f"{db_path}-wal"),
        Path(f"{db_path}-shm"),
        Path(f"{db_path}-journal"),
    )
    return tuple(path.read_bytes() if path.is_file() else None for path in paths)


def _make_historical_v0(db_path, event):
    with closing(sqlite3.connect(db_path)) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "agent_event_schema_versions" in tables:
            connection.execute("DROP TABLE agent_event_schema_versions")
        connection.execute("ALTER " "TABLE agent_events RENAME TO agent_events_current")
        connection.execute("""
            CREATE TABLE agent_events (
                stream_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                event_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                payload TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                correlation_id TEXT NOT NULL,
                actor TEXT NOT NULL,
                schema_version INTEGER NOT NULL,
                created_at REAL NOT NULL,
                PRIMARY KEY (stream_id, seq),
                UNIQUE (stream_id, idempotency_key)
            )
        """)
        connection.execute("""
            INSERT INTO agent_events (
                stream_id, seq, event_id, kind, payload, idempotency_key,
                correlation_id, actor, schema_version, created_at
            )
            SELECT stream_id, seq, event_id, kind, payload, idempotency_key,
                   correlation_id, actor, CASE WHEN event_id=? THEN 7 ELSE 1 END, created_at
            FROM agent_events_current
        """, (event.event_id,))
        connection.execute("DROP TABLE agent_events_current")
        connection.execute("CREATE INDEX idx_agent_events_created ON agent_events(created_at)")
        connection.execute("CREATE INDEX idx_agent_events_kind ON agent_events(kind)")
        connection.execute("""
            CREATE TABLE agent_schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at REAL NOT NULL,
                description TEXT NOT NULL
            )
        """)
        connection.execute("INSERT INTO agent_schema_migrations VALUES (1, 1.0, 'legacy v1')")
        connection.execute("PRAGMA user_version=0")
        connection.commit()


def test_unversioned_current_schema_migrates_with_verified_backup_and_restart(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    task, event, memory = _seed_state(db_path)

    with closing(sqlite3.connect(db_path)) as connection:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(agent_events)")]
        if "schema_version" in columns:
            connection.execute("ALTER " "TABLE agent_events DROP COLUMN schema_version")
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in ("agent_event_schema_versions", "agent_schema_migrations"):
            if table in tables:
                connection.execute(f'DROP TABLE "{table}"')
        connection.execute("PRAGMA user_version=0")
        connection.commit()

    _assert_state_survives(db_path, task, event, memory)
    backup_path = _backup_for(db_path)
    with closing(sqlite3.connect(backup_path)) as backup:
        assert backup.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert backup.execute("PRAGMA user_version").fetchone()[0] == 0
        assert backup.execute(
            "SELECT payload FROM agent_events WHERE event_id=?", (event.event_id,)
        ).fetchone()[0]

    with closing(sqlite3.connect(db_path)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        columns = [row[1] for row in connection.execute("PRAGMA table_info(agent_events)")]
        assert columns == [
            "stream_id", "seq", "event_id", "kind", "payload", "idempotency_key",
            "correlation_id", "actor", "created_at",
        ]
    _assert_state_survives(db_path, task, event, memory)
    assert len(list(tmp_path.glob("agent_state.sqlite3.migration-v0-v1-*.bak"))) == 1


def test_historical_schema_version_migrates_and_preserves_legacy_event_versions(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    task, event, memory = _seed_state(db_path)
    _make_historical_v0(db_path, event)

    _assert_state_survives(db_path, task, event, memory)
    backup_path = _backup_for(db_path)
    with closing(sqlite3.connect(backup_path)) as backup:
        assert backup.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert backup.execute(
            "SELECT schema_version FROM agent_events WHERE event_id=?", (event.event_id,)
        ).fetchone()[0] == 7
    with closing(sqlite3.connect(db_path)) as connection:
        assert connection.execute(
            "SELECT schema_version FROM agent_event_schema_versions WHERE stream_id=? AND seq=1",
            (event.stream_id,),
        ).fetchone()[0] == 7
        assert connection.execute(
            "SELECT COUNT(*) FROM agent_event_schema_versions"
        ).fetchone()[0] == 1
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
    _assert_state_survives(db_path, task, event, memory)


def test_migration_backup_verification_failure_preserves_source_bytes_and_retries(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_state.sqlite3"
    task, event, memory = _seed_state(db_path)
    _make_historical_v0(db_path, event)
    before = _sqlite_file_snapshot(db_path)

    def fail_verification(cls, source, backup, *, deadline=None):
        raise RuntimeError("injected migration backup verifier failure")

    with monkeypatch.context() as patch:
        patch.setattr(AgentStateStore, "_verify_backup", classmethod(fail_verification))
        with pytest.raises(RuntimeError, match="injected migration backup verifier failure"):
            AgentStateStore(db_path).events(event.stream_id)

    assert _sqlite_file_snapshot(db_path) == before
    assert not list(tmp_path.glob("agent_state.sqlite3.migration-v0-v1-*.bak"))
    _assert_state_survives(db_path, task, event, memory)
    assert len(list(tmp_path.glob("agent_state.sqlite3.migration-v0-v1-*.bak"))) == 1


def test_migration_ddl_failure_rolls_back_after_backup_and_retry_succeeds(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_state.sqlite3"
    task, event, memory = _seed_state(db_path)
    _make_historical_v0(db_path, event)
    with closing(sqlite3.connect(db_path)) as connection:
        before_schema = AgentStateStore._classify_schema(connection)
        before_event = connection.execute(
            "SELECT schema_version FROM agent_events WHERE event_id=?", (event.event_id,)
        ).fetchone()

    real_connect = sqlite3.connect
    partial_ddl_seen = False
    failure_injected = False

    class FailingMigrationConnection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            nonlocal partial_ddl_seen, failure_injected
            statement = " ".join(str(sql).split()).casefold()
            if "create table if not exists agent_event_schema_versions" in statement:
                result = super().execute(sql, parameters)
                partial_ddl_seen = True
                return result
            if partial_ddl_seen and statement.startswith("create table agent_events_v1"):
                failure_injected = True
                raise sqlite3.OperationalError("injected migration DDL failure")
            return super().execute(sql, parameters)

    def connect_with_migration_fault(database, *args, **kwargs):
        if not kwargs.get("uri", False) and Path(database).resolve(strict=False) == db_path.resolve():
            kwargs["factory"] = FailingMigrationConnection
        return real_connect(database, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(agent_events_module.sqlite3, "connect", connect_with_migration_fault)
        with pytest.raises(sqlite3.OperationalError, match="injected migration DDL failure"):
            AgentStateStore(db_path).events(event.stream_id)

    assert partial_ddl_seen is True
    assert failure_injected is True
    backups = list(tmp_path.glob("agent_state.sqlite3.migration-v0-v1-*.bak"))
    assert len(backups) == 1
    with closing(real_connect(db_path)) as source, closing(real_connect(backups[0])) as backup:
        assert AgentStateStore._classify_schema(source) == before_schema
        assert source.execute(
            "SELECT schema_version FROM agent_events WHERE event_id=?", (event.event_id,)
        ).fetchone() == before_event
        AgentStateStore._verify_backup(source, backup)

    _assert_state_survives(db_path, task, event, memory)
    assert backups[0].is_file()


@pytest.mark.parametrize("unsupported_version", [2, 99])
def test_unsupported_newer_schema_version_fails_closed_byte_for_byte(tmp_path, unsupported_version, monkeypatch):
    db_path = tmp_path / "agent_state.sqlite3"
    _, event, _ = _seed_state(db_path)
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute(f"PRAGMA user_version={unsupported_version}")
        connection.commit()
    before = _sqlite_file_snapshot(db_path)

    # This checks backup contents and untouched source bytes, not backup latency.
    # Separate ACL/lock deadline tests retain their explicit short budgets.
    monkeypatch.setattr(AgentStateStore, "_MIGRATION_BACKUP_TIMEOUT_SECONDS", 15.0)
    with pytest.raises(RuntimeError, match="schema version") as caught:
        AgentStateStore(db_path)._preflight_schema_read_only()

    assert caught.value.recovery_required is True
    assert caught.value.backup_path is not None and caught.value.backup_path.is_file()
    with closing(sqlite3.connect(caught.value.backup_path)) as backup:
        assert backup.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert backup.execute("PRAGMA user_version").fetchone()[0] == unsupported_version
        assert backup.execute(
            "SELECT event_id FROM agent_events WHERE event_id=?", (event.event_id,)
        ).fetchone() == (event.event_id,)
    assert db_path.is_file()
    assert _sqlite_file_snapshot(db_path) == before


def test_preflight_ignores_transient_shm_metadata_change(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_state.sqlite3"
    _seed_state(db_path)
    shm_path = Path(f"{db_path}-shm")
    shm_path.write_bytes(b"transient sqlite shared-memory state")
    original_classify = AgentStateStore._classify_schema.__func__

    def touch_shm_during_snapshot_classification(cls, connection):
        result = original_classify(cls, connection)
        stat = shm_path.stat()
        os.utime(shm_path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000))
        return result

    monkeypatch.setattr(
        AgentStateStore,
        "_classify_schema",
        classmethod(touch_shm_during_snapshot_classification),
    )
    AgentStateStore(db_path)._preflight_schema_read_only()


def test_component_schema_version_is_independent_of_database_version(tmp_path):
    db_path = tmp_path / "agent_state.sqlite"
    _seed_state(db_path)
    ScopeLeaseStore(tmp_path)
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute("DROP TABLE agent_event_schema_versions")
        connection.execute("PRAGMA user_version=0")
        connection.commit()

    AgentStateStore(db_path)._ensure_schema()

    with closing(sqlite3.connect(db_path)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert connection.execute(
            "SELECT version FROM agent_state_schema_versions WHERE component='leases'"
        ).fetchone() == (1,)


def test_legacy_event_version_metadata_is_sparse_and_pruned_with_event(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    _, event, _ = _seed_state(db_path)
    with closing(sqlite3.connect(db_path)) as connection:
        assert connection.execute(
            "SELECT schema_version FROM agent_event_schema_versions WHERE stream_id=? AND seq=?",
            (event.stream_id, 1),
        ).fetchone() is None
        connection.execute(
            "INSERT INTO agent_event_schema_versions(stream_id, seq, schema_version) "
            "VALUES (?, ?, 7)",
            (event.stream_id, 1),
        )
        connection.execute(
            "UPDATE agent_events SET created_at=? WHERE stream_id=? AND seq=?",
            (time.time() - (2 * 86400), event.stream_id, 1),
        )
        connection.commit()

    result = AgentStateStore(db_path).cleanup(retention_days=1)

    assert result["success"] is True
    assert result["deleted_events"] >= 1
    with closing(sqlite3.connect(db_path)) as connection:
        assert connection.execute(
            "SELECT 1 FROM agent_events WHERE stream_id=? AND seq=?",
            (event.stream_id, 1),
        ).fetchone() is None
        assert connection.execute(
            "SELECT 1 FROM agent_event_schema_versions WHERE stream_id=? AND seq=?",
            (event.stream_id, 1),
        ).fetchone() is None


def test_unknown_legacy_layout_fails_closed_without_changing_database_bytes(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    _, event, _ = _seed_state(db_path)
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute("ALTER " "TABLE agent_events ADD COLUMN unknown_future_data TEXT")
        connection.execute("DROP TABLE agent_event_schema_versions")
        connection.execute("PRAGMA user_version=0")
        connection.commit()
    before = _sqlite_file_snapshot(db_path)

    from local_ai_hub.sqlite_support import DurableSchemaMismatchError

    state = AgentStateStore(db_path)
    mismatch = "unsupported agent_state schema object definition: table agent_events"
    with pytest.raises(DurableSchemaMismatchError) as internal_exc:
        state._preflight_schema_read_only()
    internal = internal_exc.value
    assert internal.mismatches == (mismatch,)
    assert str(internal.__cause__) == mismatch
    assert internal.recovery_required is True
    assert internal.database_path == db_path
    assert internal.backup_path is not None
    assert internal.backup_path.is_file()
    assert _sqlite_file_snapshot(db_path) == before

    page = state.event_page(event.stream_id)
    assert page["success"] is False
    assert page["events"] == []
    assert page["error"] == {
        "code": "event_page_unavailable",
        "message": "Event page could not be read.",
    }
    public = json.dumps(page)
    for private_detail in (str(db_path), str(internal.backup_path), mismatch):
        assert private_detail not in public
        assert json.dumps(private_detail)[1:-1] not in public
    assert "schema-mismatch-" not in public
    assert "recovery_required" not in public
    assert "backup" not in public
    assert _sqlite_file_snapshot(db_path) == before

    with pytest.raises(RuntimeError) as exc_info:
        state.events(event.stream_id)

    assert str(exc_info.value) == "event_page_unavailable: Event page could not be read."
    assert db_path.is_file()
    assert _sqlite_file_snapshot(db_path) == before


@pytest.mark.parametrize("unknown_object", [
    "CREATE TABLE future_table (id INTEGER)",
    "CREATE VIEW future_view AS SELECT 1 AS value",
    "CREATE INDEX idx_future_unknown ON agent_events(created_at)",
    "CREATE TRIGGER future_trigger AFTER INSERT ON agent_events BEGIN SELECT 1; END",
])
def test_unknown_schema_objects_fail_closed_without_file_changes(tmp_path, unknown_object):
    db_path = tmp_path / "agent_state.sqlite3"
    _, event, _ = _seed_state(db_path)
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute(unknown_object)
        connection.execute("DROP TABLE agent_event_schema_versions")
        connection.execute("PRAGMA user_version=0")
        connection.commit()
    before = _sqlite_file_snapshot(db_path)

    with pytest.raises(RuntimeError) as exc_info:
        AgentStateStore(db_path).events(event.stream_id)

    diagnostic = str(exc_info.value).casefold().replace("_", " ")
    assert "unsupported" in diagnostic
    assert "agent state schema" in diagnostic
    assert _sqlite_file_snapshot(db_path) == before


def test_unknown_schema_read_only_preflight_preserves_wal_and_shm_bytes(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    _, event, _ = _seed_state(db_path)
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE VIEW future_view AS SELECT 1 AS value")
        connection.execute("DROP TABLE agent_event_schema_versions")
        connection.execute("PRAGMA user_version=0")
        connection.commit()
        before = _sqlite_file_snapshot(db_path)
        assert before[1] is not None
        assert before[2] is not None

        with pytest.raises(RuntimeError):
            AgentStateStore(db_path).events(event.stream_id)

        assert _sqlite_file_snapshot(db_path) == before
    finally:
        connection.close()


def test_missing_required_projection_schema_fails_closed_and_preserves_wal_and_shm(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    _, event, _ = _seed_state(db_path)
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("DROP TABLE agent_tasks_projection")
        connection.execute("DROP TABLE agent_event_schema_versions")
        connection.execute("PRAGMA user_version=0")
        connection.commit()
        before = _sqlite_file_snapshot(db_path)
        assert before[1] is not None
        assert before[2] is not None

        with pytest.raises(RuntimeError, match="missing required schema objects") as exc_info:
            AgentStateStore(db_path).events(event.stream_id)

        assert _sqlite_file_snapshot(db_path) == before
        backups = list(tmp_path.glob("agent_state.sqlite.schema-mismatch-*.sqlite3"))
        assert len(backups) == 1
        assert str(backups[0]) in str(exc_info.value)
        assert "no migration applied" in str(exc_info.value).casefold()
        with closing(sqlite3.connect(backups[0])) as backup:
            assert backup.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
            assert backup.execute("PRAGMA user_version").fetchone()[0] == 0
            assert backup.execute(
                "SELECT payload FROM agent_events WHERE event_id=?", (event.event_id,)
            ).fetchone()[0]
        if os.name == "posix":
            assert backups[0].stat().st_mode & 0o777 == 0o600
        elif os.name == "nt":
            account = subprocess.run(
                ["whoami"], check=True, capture_output=True, text=True, timeout=2.0
            ).stdout.strip()
            acl = subprocess.run(
                ["icacls", str(backups[0])],
                check=True,
                capture_output=True,
                text=True,
                timeout=2.0,
            ).stdout
            assert account.casefold() in acl.casefold()
            assert "(I)" not in acl
    finally:
        connection.close()


@pytest.mark.parametrize("schema_changes", [
    ("ALTER " "TABLE agent_tasks_projection ADD COLUMN extra TEXT NOT NULL DEFAULT ''",),
    ("ALTER " "TABLE agent_change_intents ADD COLUMN linked_task TEXT REFERENCES agent_tasks_projection(task_id)",),
    (
        "DROP TABLE agent_memory_embeddings",
        "CREATE TABLE agent_memory_embeddings (record_id BLOB PRIMARY KEY, embedding TEXT NOT NULL, created_at REAL NOT NULL)",
    ),
    (
        "DROP TABLE agent_memory_embeddings",
        "CREATE TABLE agent_memory_embeddings (record_id TEXT NOT NULL, embedding TEXT NOT NULL, created_at REAL NOT NULL)",
    ),
])
def test_known_table_definition_change_fails_closed_byte_for_byte(tmp_path, schema_changes):
    db_path = tmp_path / "agent_state.sqlite3"
    _, event, _ = _seed_state(db_path)
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute("DROP TABLE agent_event_schema_versions")
        for schema_change in schema_changes:
            connection.execute(schema_change)
        connection.execute("PRAGMA user_version=0")
        connection.commit()
    before = _sqlite_file_snapshot(db_path)

    with pytest.raises(RuntimeError, match="unsupported agent_state schema"):
        AgentStateStore(db_path).events(event.stream_id)

    assert _sqlite_file_snapshot(db_path) == before


def test_known_index_definition_change_fails_closed_byte_for_byte(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    _, event, _ = _seed_state(db_path)
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute("DROP TABLE agent_event_schema_versions")
        connection.execute("DROP INDEX idx_agent_tasks_updated")
        connection.execute(
            "CREATE INDEX idx_agent_tasks_updated ON agent_tasks_projection(task_id)"
        )
        connection.execute("PRAGMA user_version=0")
        connection.commit()
    before = _sqlite_file_snapshot(db_path)

    with pytest.raises(RuntimeError, match="unsupported agent_state schema"):
        AgentStateStore(db_path).events(event.stream_id)

    assert _sqlite_file_snapshot(db_path) == before


def test_backup_verifier_rejects_same_count_different_row_content(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    _, event, _ = _seed_state(db_path)
    backup_path = tmp_path / "altered-backup.sqlite3"
    with closing(sqlite3.connect(db_path)) as source, closing(sqlite3.connect(backup_path)) as backup:
        source.backup(backup)
        before_count = backup.execute("SELECT COUNT(*) FROM agent_events").fetchone()[0]
        backup.execute("UPDATE agent_events SET payload='{}' WHERE event_id=?", (event.event_id,))
        backup.commit()
        assert backup.execute("SELECT COUNT(*) FROM agent_events").fetchone()[0] == before_count

        with pytest.raises(RuntimeError, match="content hash mismatch"):
            AgentStateStore._verify_backup(source, backup)


def test_backup_verifier_rejects_same_objects_with_different_sql(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    _seed_state(db_path)
    backup_path = tmp_path / "altered-schema-backup.sqlite3"
    with closing(sqlite3.connect(db_path)) as source, closing(sqlite3.connect(backup_path)) as backup:
        source.backup(backup)
        backup.execute("DROP INDEX idx_agent_tasks_updated")
        backup.execute(
            "CREATE INDEX idx_agent_tasks_updated ON agent_tasks_projection(task_id)"
        )
        backup.commit()

        with pytest.raises(RuntimeError, match="schema definition mismatch"):
            AgentStateStore._verify_backup(source, backup)


def test_backup_timeout_bounds_sqlite_busy_wait(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_state.sqlite3"
    _seed_state(db_path)
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.commit()

    locker = sqlite3.connect(db_path, timeout=5.0)
    source = sqlite3.connect(db_path, timeout=5.0)
    try:
        locker.execute("BEGIN EXCLUSIVE")
        monkeypatch.setattr(AgentStateStore, "_MIGRATION_BACKUP_TIMEOUT_SECONDS", 0.08)
        started = time.monotonic()
        with pytest.raises(TimeoutError, match="backup time limit"):
            AgentStateStore._verified_backup(source)
        assert time.monotonic() - started < 0.5
    finally:
        source.close()
        locker.rollback()
        locker.close()


def test_preflight_accepts_incident_store_ignored_column_migration_variant(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    _seed_state(db_path)

    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute("DROP TABLE agent_incidents")
        incident_ddl = """CREATE TABLE agent_incidents (
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
                                affected_paths TEXT NOT NULL DEFAULT '[]'
                            , ignored INTEGER NOT NULL DEFAULT 0)"""
        connection.execute(incident_ddl)
        connection.executescript(
            """
            CREATE INDEX idx_agent_incidents_fp
                ON agent_incidents (error_class, operation_class, signature_hash, state_revision);
            CREATE INDEX idx_agent_incidents_lookup
                ON agent_incidents (operation_class, signature_hash, state_revision, updated_at DESC);
            CREATE INDEX idx_agent_incidents_recent
                ON agent_incidents (operation_class, signature_hash, updated_at DESC);
            """
        )
        connection.execute(
            "INSERT INTO agent_incidents (incident_id, operation_class, error_class, "
            "signature_hash, redacted_message, state_revision, attempts, evidence_ids, "
            "confidence, resolved, created_at, updated_at, affected_paths) "
            "VALUES ('legacy-incident', 'command', '', '', '', '', 0, '[]', 0, 0, 1, 1, '[]')"
        )
        connection.commit()
        incident_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='agent_incidents'"
        ).fetchone()[0]

    incident_hash = hashlib.sha256(
        " ".join(str(incident_sql).split()).casefold().encode("utf-8")
    ).hexdigest()
    assert incident_hash == "43c461c1906a1c11a5558889e2c49478942b940c3e98d0a926848ead3010a63e", repr(incident_sql)

    before = _sqlite_file_snapshot(db_path)
    state = AgentStateStore(db_path)
    state._preflight_schema_read_only()
    assert _sqlite_file_snapshot(db_path) == before
    IncidentStore(state)
    backups = list(tmp_path.glob("agent_state.sqlite3.migration-v0-v1-*.bak"))
    assert len(backups) == 1
    with closing(sqlite3.connect(backups[0])) as backup:
        assert backup.execute(
            "SELECT incident_id FROM agent_incidents WHERE incident_id='legacy-incident'"
        ).fetchone() == ("legacy-incident",)
        backup_sql = backup.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='agent_incidents'"
        ).fetchone()[0]
        assert hashlib.sha256(
            " ".join(str(backup_sql).split()).casefold().encode("utf-8")
        ).hexdigest() == incident_hash
    with closing(sqlite3.connect(db_path)) as migrated:
        columns = {str(row[1]) for row in migrated.execute("PRAGMA table_info(agent_incidents)")}
        assert {"ignored", "repository_key", "tenant_key"}.issubset(columns)
        assert migrated.execute(
            "SELECT incident_id FROM agent_incidents WHERE incident_id='legacy-incident'"
        ).fetchone() == ("legacy-incident",)


def test_preflight_accepts_incident_store_scope_columns_variant(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    _seed_state(db_path)

    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute("DROP TABLE agent_incidents")
        connection.execute(
            """CREATE TABLE agent_incidents (
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
                affected_paths TEXT NOT NULL DEFAULT '[]'
            , ignored INTEGER NOT NULL DEFAULT 0, repository_key TEXT NOT NULL DEFAULT '', tenant_key TEXT NOT NULL DEFAULT '')"""
        )
        connection.commit()
        incident_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='agent_incidents'"
        ).fetchone()[0]
    incident_hash = hashlib.sha256(
        " ".join(str(incident_sql).split()).casefold().encode("utf-8")
    ).hexdigest()
    assert incident_hash == "b3f8fa5c1723ab3addf421e28c3e9e07d232a7734cc95c247aed04224f3856b0"

    before = _sqlite_file_snapshot(db_path)
    AgentStateStore(db_path)._preflight_schema_read_only()
    assert _sqlite_file_snapshot(db_path) == before
