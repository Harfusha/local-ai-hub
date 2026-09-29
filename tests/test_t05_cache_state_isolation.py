from __future__ import annotations

from contextlib import closing
import sqlite3

import pytest

from local_ai_hub.agent_events import AgentEvent, AgentStateStore
from local_ai_hub.agent_identity import AgentScope
from local_ai_hub.agent_memory import MemoryKind, MemoryRecord, MemoryStore
from local_ai_hub.agent_tasks import GoalContract, ScopeContext, TaskStore
from local_ai_hub.agent_verification import VerificationReceipt, VerificationStore
from local_ai_hub.cache import SQLiteCache
from local_ai_hub.code_index import CodeIndex
from local_ai_hub.leases import ScopeLeaseStore


@pytest.mark.parametrize("derived_db", ["cache", "code-index"])
def test_derived_sqlite_recovery_preserves_agent_state_and_leases(tmp_path, derived_db):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    repository = tmp_path / "repository"
    repository.mkdir()

    state = AgentStateStore(state_dir / "agent_state.sqlite3")
    tasks = TaskStore(state)
    task = tasks.create(
        GoalContract(goal="preserve durable state", acceptance_criteria=("receipt",)),
        ScopeContext(task_id="t05-durable-task"),
        task_id="t05-durable-task",
    )
    event = AgentEvent.create(task.task_id, "task.created", {"goal": task.contract.goal}, "t05-event")
    state.append(event)

    memories = MemoryStore(state)
    memory = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.TASK,
        scope_id=task.task_id,
        key="durable-marker",
        value="keep across derived database recovery",
        source="test",
    )
    memories.record(memory, actor="test")

    verifications = VerificationStore(state, task_store=tasks)
    receipt = VerificationReceipt.create(
        task_id=task.task_id,
        criterion="receipt",
        passed=True,
        expires_at=None,
        evidence_id="t05-durable-evidence",
    )
    verifications.record(receipt)

    leases = ScopeLeaseStore(state_dir)
    lease = leases.claim("t05", str(repository), ["src/durable.py"], purpose="persistence test")
    assert lease["success"] is True

    derived_name = "cache.sqlite3" if derived_db == "cache" else "code-index.sqlite3"
    derived_path = state_dir / derived_name
    derived_path.write_bytes(b"corrupt disposable database")

    if derived_db == "cache":
        SQLiteCache(derived_path, "t05-persistence-test")
    else:
        CodeIndex({"server": {"state_dir": str(state_dir)}}, repo_tools=None)

    with closing(sqlite3.connect(derived_path)) as connection:
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    assert list(state_dir.glob(f"{derived_name}.corrupt-*"))

    assert tasks.get(task.task_id).contract.goal == "preserve durable state"
    assert state.events(task.task_id) == [event.with_seq(1)]
    assert memories.get(
        memory.record_id,
        scope=memory.scope,
        scope_id=task.task_id,
    ).value == "keep across derived database recovery"
    assert verifications.completion(task.task_id).complete is True
    assert leases.list(str(repository))[0]["lease_id"] == lease["lease_id"]


def test_scoped_memory_delete_preserves_all_relations_until_authorized(tmp_path):
    state = AgentStateStore(tmp_path / "agent_state.sqlite3")
    memories = MemoryStore(state)
    record = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.WORKTREE,
        scope_id="t05-worktree",
        key="identity-marker",
        value="keep until owner deletes",
        source="test",
    )
    memories.record(record, actor="test")
    related = memories.record(
        MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=AgentScope.WORKTREE,
            scope_id="t05-worktree",
            key="related-marker",
            value="linked memory",
            source="test",
        ),
        actor="test",
    )
    memories.record_relation(record.record_id, "relates_to", related.record_id)
    original_relations = memories.find_relations(source_entity=record.record_id)
    assert original_relations

    assert memories.delete(record.record_id) is False
    assert memories.delete(
        record.record_id,
        scope=AgentScope.WORKTREE,
        scope_id="another-worktree",
    ) is False
    assert memories.get(
        record.record_id,
        scope=AgentScope.WORKTREE,
        scope_id="t05-worktree",
    ).value == "keep until owner deletes"
    assert memories.find_relations(source_entity=record.record_id) == original_relations

    assert memories.delete(
        record.record_id,
        scope=AgentScope.WORKTREE,
        scope_id="t05-worktree",
    ) is True
    assert memories.get(
        record.record_id,
        scope=AgentScope.WORKTREE,
        scope_id="t05-worktree",
    ) is None
    assert memories.find_relations(source_entity=record.record_id) == []
