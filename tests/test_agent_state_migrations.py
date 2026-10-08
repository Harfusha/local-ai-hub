from __future__ import annotations

from contextlib import closing
import sqlite3
from pathlib import Path

import pytest

from local_ai_hub.agent_events import AgentEvent, AgentStateStore
from local_ai_hub.agent_identity import AgentScope, ScopeContext
from local_ai_hub.agent_memory import MemoryKind, MemoryRecord, MemoryStore
from local_ai_hub.agent_tasks import GoalContract, TaskStore
from local_ai_hub.agent_verification import VerificationReceipt, VerificationStore
from local_ai_hub.artifacts import ArtifactStore


def _seed_durable_rows(db_path: Path, artifact_dir: Path):
    state = AgentStateStore(db_path)
    tasks = TaskStore(state)
    task = tasks.create(
        GoalContract(goal="preserve migration state", acceptance_criteria=("tests",)),
        ScopeContext(task_id="migration-task"),
        task_id="migration-task",
        actor="test-owner",
    )
    event = AgentEvent.create(task.task_id, "migration.marker", {"value": "keep"}, "migration-event")
    state.append(event)

    memories = MemoryStore(state)
    memory = memories.record(MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.TASK,
        scope_id=task.task_id,
        key="migration-marker",
        value="keep durable memory",
        source="test",
        provenance={
            "root": str(db_path.parent.resolve()),
            "tenant": "test-owner",
            "task_id": task.task_id,
        },
    ), actor="test")

    artifacts = ArtifactStore(artifact_dir)
    proof_id = artifacts.put_json({
        "kind": "work_source_review",
        "passed": True,
        "task_id": task.task_id,
        "owner": "test-owner",
        "repository_revision": "rev-migration",
        "mutation_generation": 0,
        "criteria": ["tests"],
    }, "test-owner", "source_review")
    receipt = VerificationReceipt.create(
        task_id=task.task_id,
        criterion="tests",
        passed=True,
        evidence_id=proof_id,
        owner="test-owner",
        repository_revision="rev-migration",
        mutation_generation=0,
        evidence_type="source_review",
    )
    verifications = VerificationStore(state, task_store=tasks, artifact_store=artifacts)
    verifications.record(receipt)
    return task, event, memory, receipt


def _table_counts(connection: sqlite3.Connection) -> dict[str, int]:
    tables = [str(row[0]) for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )]
    return {name: int(connection.execute(f' SELECT COUNT(*) FROM "{name}"').fetchone()[0]) for name in tables}


def _migration_backups(db_path: Path) -> list[Path]:
    return sorted(db_path.parent.glob(f"{db_path.name}.migration-v0-v1-*.bak"))


def test_current_unversioned_agent_state_migrates_with_verified_backup_and_restart(tmp_path: Path):
    db_path = tmp_path / "agent_state.sqlite3"
    task, event, memory, receipt = _seed_durable_rows(db_path, tmp_path / "artifacts")
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("PRAGMA user_version=0")
        connection.commit()
        expected_counts = _table_counts(connection)
        expected_events = connection.execute(
            "SELECT event_id, payload FROM agent_events WHERE event_id=?", (event.event_id,)
        ).fetchall()

    AgentStateStore(db_path)._ensure_schema()

    backups = _migration_backups(db_path)
    assert len(backups) == 1
    with closing(sqlite3.connect(backups[0])) as backup:
        assert backup.execute("PRAGMA quick_check").fetchone() == ("ok",)
        assert backup.execute("PRAGMA user_version").fetchone() == (0,)
        assert _table_counts(backup) == expected_counts
        assert backup.execute(
            "SELECT event_id, payload FROM agent_events WHERE event_id=?", (event.event_id,)
        ).fetchall() == expected_events
    with closing(sqlite3.connect(db_path)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (1,)
        assert _table_counts(connection) == expected_counts

    reopened_state = AgentStateStore(db_path)
    reopened_tasks = TaskStore(reopened_state)
    reopened_memory = MemoryStore(reopened_state)
    reopened_verifications = VerificationStore(reopened_state, task_store=reopened_tasks)
    with closing(sqlite3.connect(db_path)) as connection:
        restored_memory_row = connection.execute(
            "SELECT record_id, scope, scope_id, sensitivity, value, provenance "
            "FROM agent_memory_records WHERE record_id=?",
            (memory.record_id,),
        ).fetchone()
    assert restored_memory_row is not None
    assert reopened_tasks.get(task.task_id).contract.goal == task.contract.goal
    assert reopened_state.events(task.task_id) == [event.with_seq(1), *reopened_state.events(task.task_id)[1:]]
    restored_memory = reopened_memory.get(
        memory.record_id,
        scope=memory.scope,
        task_id=task.task_id,
        root=str(db_path.parent.resolve()),
        tenant="test-owner",
    )
    assert restored_memory is not None, restored_memory_row
    assert restored_memory.value == memory.value
    assert any(row.receipt_id == receipt.receipt_id for row in reopened_verifications.completion(task.task_id).receipts)


def test_unsupported_future_schema_version_fails_closed_without_mutation(tmp_path: Path):
    db_path = tmp_path / "agent_state.sqlite3"
    _, event, _, _ = _seed_durable_rows(db_path, tmp_path / "artifacts")
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("PRAGMA user_version=2")
        connection.commit()
    original = db_path.read_bytes()

    with pytest.raises(RuntimeError, match="unsupported agent state schema version: 2"):
        AgentStateStore(db_path)._ensure_schema()

    assert db_path.read_bytes() == original
    with closing(sqlite3.connect(db_path)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (2,)
        assert connection.execute("SELECT event_id FROM agent_events WHERE event_id=?", (event.event_id,)).fetchone() == (event.event_id,)
    assert not _migration_backups(db_path)


def test_migration_backup_failure_prevents_schema_version_write(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "agent_state.sqlite3"
    _, event, _, _ = _seed_durable_rows(db_path, tmp_path / "artifacts")
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("PRAGMA user_version=0")
        connection.commit()

    def fail_backup(cls, source):
        raise OSError("injected durable backup failure")

    monkeypatch.setattr(AgentStateStore, "_verified_backup", classmethod(fail_backup))
    with pytest.raises(OSError, match="injected durable backup failure"):
        AgentStateStore(db_path)._ensure_schema()

    with closing(sqlite3.connect(db_path)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (0,)
        assert connection.execute("SELECT event_id FROM agent_events WHERE event_id=?", (event.event_id,)).fetchone() == (event.event_id,)
    assert not _migration_backups(db_path)


def test_corrupt_agent_state_fails_closed_without_replacing_bytes(tmp_path: Path):
    db_path = tmp_path / "agent_state.sqlite3"
    original = b"not a sqlite database; preserve exact recovery input"
    db_path.write_bytes(original)

    with pytest.raises(sqlite3.DatabaseError):
        AgentStateStore(db_path)._ensure_schema()

    assert db_path.read_bytes() == original
    assert not _migration_backups(db_path)
