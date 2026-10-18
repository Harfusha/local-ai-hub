from __future__ import annotations

from contextlib import closing
import json
import os
import sqlite3
from pathlib import Path

import pytest

from local_ai_hub.agent_events import AgentEvent, AgentStateStore
from local_ai_hub.sqlite_support import DurableSchemaMismatchError
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
    ).value == "durable memory"
    assert VerificationStore(state, task_store=tasks, artifact_store=_MigrationArtifactStore(task)).completion(task.task_id).complete is True


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


def test_current_schema_reopens_without_payload_version_side_table(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    task, event, memory = _seed_state(db_path)

    AgentStateStore(db_path)._ensure_schema()
    with closing(sqlite3.connect(db_path)) as connection:
        tables = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        columns = [row[1] for row in connection.execute("PRAGMA table_info(agent_events)")]
        assert connection.execute("PRAGMA user_version").fetchone() == (1,)
        assert columns == [
            "stream_id", "seq", "event_id", "kind", "payload", "idempotency_key",
            "correlation_id", "actor", "created_at",
        ]
        assert "agent_event_schema_versions" not in tables
    _assert_state_survives(db_path, task, event, memory)
    assert not list(tmp_path.glob("agent_state.sqlite3.migration-v0-v1-*.bak"))


def test_current_layout_with_old_database_version_rejects_without_writes(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    _seed_state(db_path)
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute("PRAGMA user_version=0")
        connection.commit()
    before = _sqlite_file_snapshot(db_path)

    with pytest.raises(DurableSchemaMismatchError):
        AgentStateStore(db_path)._ensure_schema()

    assert _sqlite_file_snapshot(db_path) == before
    assert not list(tmp_path.glob("*.bak"))


def test_historical_payload_version_layout_rejects_without_writes(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    _, event, _ = _seed_state(db_path)
    _make_historical_v0(db_path, event)
    before = _sqlite_file_snapshot(db_path)

    with pytest.raises(DurableSchemaMismatchError):
        AgentStateStore(db_path).events(event.stream_id)

    assert _sqlite_file_snapshot(db_path) == before
    assert not list(tmp_path.glob("*.bak"))

@pytest.mark.parametrize("unsupported_version", [2, 99])
def test_unsupported_newer_schema_version_fails_closed_byte_for_byte(tmp_path, unsupported_version):
    db_path = tmp_path / "agent_state.sqlite3"
    _, event, _ = _seed_state(db_path)
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute(f"PRAGMA user_version={unsupported_version}")
        connection.commit()
    before = _sqlite_file_snapshot(db_path)

    with pytest.raises(DurableSchemaMismatchError, match="schema version") as caught:
        AgentStateStore(db_path)._preflight_schema_read_only()

    assert caught.value.recovery_required is True
    assert caught.value.backup_path is None
    assert db_path.is_file()
    assert _sqlite_file_snapshot(db_path) == before
    assert not list(tmp_path.glob("*.bak"))


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


def test_event_schema_and_partial_current_lease_store_reopen(tmp_path):
    db_path = tmp_path / "agent_state.sqlite"
    _seed_state(db_path)
    ScopeLeaseStore(tmp_path)

    AgentStateStore(db_path)._ensure_schema()
    with closing(sqlite3.connect(db_path)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (1,)
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        assert {"agent_events", "agent_snapshots", "leases", "lease_waits"} <= tables
        assert "agent_event_schema_versions" not in tables

def test_unknown_legacy_layout_fails_closed_without_changing_database_bytes(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    _, event, _ = _seed_state(db_path)
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute("ALTER " "TABLE agent_events ADD COLUMN unknown_future_data TEXT")
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
    assert internal.backup_path is None
    assert not list(tmp_path.glob("*.bak"))
    assert _sqlite_file_snapshot(db_path) == before

    with pytest.raises(DurableSchemaMismatchError):
        state.events(event.stream_id)
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
        connection.commit()
    before = _sqlite_file_snapshot(db_path)

    with pytest.raises(DurableSchemaMismatchError) as exc_info:
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
        connection.commit()
        before = _sqlite_file_snapshot(db_path)
        assert before[1] is not None
        assert before[2] is not None

        with pytest.raises(DurableSchemaMismatchError):
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
        connection.commit()
        before = _sqlite_file_snapshot(db_path)
        assert before[1] is not None
        assert before[2] is not None

        with pytest.raises(DurableSchemaMismatchError, match="missing required schema objects") as exc_info:
            AgentStateStore(db_path).events(event.stream_id)

        assert _sqlite_file_snapshot(db_path) == before
        assert exc_info.value.backup_path is None
        assert not list(tmp_path.glob("*.bak"))
        assert "no migration applied" in str(exc_info.value).casefold()
    finally:
        connection.close()


@pytest.mark.parametrize("schema_changes", [
    ("ALTER TABLE agent_tasks_projection ADD COLUMN extra TEXT NOT NULL DEFAULT ''",),
    ("ALTER TABLE agent_change_intents ADD COLUMN linked_task TEXT REFERENCES agent_tasks_projection(task_id)",),
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
        for schema_change in schema_changes:
            connection.execute(schema_change)
        connection.execute("PRAGMA user_version=0")
        connection.commit()
    before = _sqlite_file_snapshot(db_path)

    with pytest.raises(DurableSchemaMismatchError, match="unsupported agent_state schema"):
        AgentStateStore(db_path).events(event.stream_id)

    assert _sqlite_file_snapshot(db_path) == before


def test_known_index_definition_change_fails_closed_byte_for_byte(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    _, event, _ = _seed_state(db_path)
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute("DROP INDEX idx_agent_tasks_updated")
        connection.execute(
            "CREATE INDEX idx_agent_tasks_updated ON agent_tasks_projection(task_id)"
        )
        connection.execute("PRAGMA user_version=0")
        connection.commit()
    before = _sqlite_file_snapshot(db_path)

    with pytest.raises(DurableSchemaMismatchError, match="unsupported agent_state schema"):
        AgentStateStore(db_path).events(event.stream_id)

    assert _sqlite_file_snapshot(db_path) == before


def test_legacy_incident_identity_layout_rejects_without_writes(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    _seed_state(db_path)

    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute("DROP TABLE agent_incidents")
        connection.executescript(
            """
            CREATE TABLE agent_incidents (
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
                ignored INTEGER NOT NULL DEFAULT 0,
                repository_key TEXT NOT NULL DEFAULT '',
                tenant_key TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX idx_agent_incidents_fp
                ON agent_incidents (error_class, operation_class, signature_hash, state_revision);
            CREATE INDEX idx_agent_incidents_lookup
                ON agent_incidents (operation_class, signature_hash, state_revision, updated_at DESC);
            CREATE INDEX idx_agent_incidents_recent
                ON agent_incidents (operation_class, signature_hash, updated_at DESC);
            CREATE INDEX idx_agent_incidents_scope
                ON agent_incidents (tenant_key, repository_key, updated_at DESC);
            INSERT INTO agent_incidents VALUES
                ('command', '', '', '', '', 0, '[]', NULL, NULL, 0, 0, 1, 1, NULL, '[]', 0, '', '');
            """
        )
        connection.commit()

    before = _sqlite_file_snapshot(db_path)
    with pytest.raises(DurableSchemaMismatchError):
        IncidentStore(AgentStateStore(db_path))
    assert _sqlite_file_snapshot(db_path) == before
    assert not list(tmp_path.glob("*.bak"))
