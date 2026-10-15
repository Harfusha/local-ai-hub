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
from local_ai_hub.sqlite_support import DurableSchemaMismatchError


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


def test_current_agent_state_reopens_without_changing_durable_rows(tmp_path: Path):
    db_path = tmp_path / "agent_state.sqlite3"
    task, event, memory, receipt = _seed_durable_rows(db_path, tmp_path / "artifacts")
    with closing(sqlite3.connect(db_path)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (1,)
        assert connection.execute("SELECT event_id FROM agent_events WHERE event_id=?", (event.event_id,)).fetchone() == (event.event_id,)

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
    with closing(sqlite3.connect(db_path)) as connection:
        tables = {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "agent_event_schema_versions" not in tables


def test_unsupported_future_schema_version_fails_closed_without_mutation(tmp_path: Path):
    db_path = tmp_path / "agent_state.sqlite3"
    _, event, _, _ = _seed_durable_rows(db_path, tmp_path / "artifacts")
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("PRAGMA user_version=2")
        connection.commit()
    original = db_path.read_bytes()

    with pytest.raises(DurableSchemaMismatchError):
        AgentStateStore(db_path)._ensure_schema()

    assert db_path.read_bytes() == original
    with closing(sqlite3.connect(db_path)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (2,)
        assert connection.execute("SELECT event_id FROM agent_events WHERE event_id=?", (event.event_id,)).fetchone() == (event.event_id,)
def test_unversioned_durable_state_rejects_without_writing_or_backup(tmp_path: Path):
    db_path = tmp_path / "agent_state.sqlite3"
    _, event, _, _ = _seed_durable_rows(db_path, tmp_path / "artifacts")
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("PRAGMA user_version=0")
        connection.commit()
    original = db_path.read_bytes()

    with pytest.raises(DurableSchemaMismatchError):
        AgentStateStore(db_path)._ensure_schema()

    assert db_path.read_bytes() == original
    with closing(sqlite3.connect(db_path)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (0,)
        assert connection.execute("SELECT event_id FROM agent_events WHERE event_id=?", (event.event_id,)).fetchone() == (event.event_id,)
    assert not list(tmp_path.glob("*.bak"))


def test_corrupt_agent_state_fails_closed_without_replacing_bytes(tmp_path: Path):
    db_path = tmp_path / "agent_state.sqlite3"
    original = b"not a sqlite database; preserve exact recovery input"
    db_path.write_bytes(original)

    with pytest.raises(sqlite3.DatabaseError):
        AgentStateStore(db_path)._ensure_schema()

    assert db_path.read_bytes() == original
