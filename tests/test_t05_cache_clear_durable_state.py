from __future__ import annotations

from local_ai_hub.agent_events import AgentEvent, AgentStateStore
from local_ai_hub.agent_identity import AgentScope
from local_ai_hub.agent_memory import MemoryKind, MemoryRecord, MemoryStore
from local_ai_hub.agent_tasks import GoalContract, ScopeContext, TaskStore
from local_ai_hub.agent_verification import VerificationReceipt, VerificationStore
from local_ai_hub.cache import SQLiteCache
from local_ai_hub.leases import ScopeLeaseStore


def test_cache_namespace_clear_preserves_durable_agent_os_state(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    repository = tmp_path / "repository"
    repository.mkdir()

    cache_path = state_dir / "cache.sqlite3"
    cache = SQLiteCache(cache_path, "t05-clear")
    other_namespace = SQLiteCache(cache_path, "other")
    cache.set("discard", {"value": "derived"})
    other_namespace.set("retain", {"value": "other namespace"})

    state = AgentStateStore(state_dir / "agent_state.sqlite")
    tasks = TaskStore(state)
    task = tasks.create(
        GoalContract(goal="preserve durable state", acceptance_criteria=("receipt",)),
        ScopeContext(task_id="t05-clear-task"),
        task_id="t05-clear-task",
    )
    event = AgentEvent.create(task.task_id, "task.created", {"goal": task.contract.goal}, "t05-clear-event")
    state.append(event)

    memories = MemoryStore(state)
    memory = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.TASK,
        scope_id=task.task_id,
        key="durable-marker",
        value="preserve through cache clear",
        source="test",
        provenance={"root": str(repository), "tenant": "t05-cache-clear"},
    )
    # Cache-clear acceptance needs durable memory, not T08 event-writer coverage.
    memories._save_record(memory)

    verifications = VerificationStore(state, task_store=tasks)
    receipt = VerificationReceipt.create(
        task_id=task.task_id,
        criterion="receipt",
        passed=True,
        expires_at=None,
        evidence_id="t05-clear-evidence",
    )
    verifications.record(receipt)

    leases = ScopeLeaseStore(state_dir)
    lease = leases.claim("t05-clear", str(repository), ["src/durable.py"], purpose="cache clear isolation")
    assert lease["success"] is True

    assert cache.clear() == 1
    assert cache.get("discard") is None
    assert other_namespace.get("retain") == {"value": "other namespace"}

    reopened_state = AgentStateStore(state_dir / "agent_state.sqlite")
    reopened_tasks = TaskStore(reopened_state)
    reopened_memories = MemoryStore(reopened_state)
    reopened_verifications = VerificationStore(reopened_state, task_store=reopened_tasks)
    reopened_leases = ScopeLeaseStore(state_dir)

    assert reopened_tasks.get(task.task_id).contract.goal == "preserve durable state"
    assert reopened_state.events(task.task_id) == [event.with_seq(1)]
    assert reopened_memories.get(
        memory.record_id,
        scope=AgentScope.TASK,
        scope_id=task.task_id,
    ) is None
    restored_memory = reopened_memories.get(
        memory.record_id,
        scope=AgentScope.TASK,
        scope_id=task.task_id,
        task_id=task.task_id,
        root=memory.provenance["root"],
    )
    assert restored_memory is not None
    assert restored_memory.value == "preserve through cache clear"
    persisted_receipts = reopened_verifications.completion(task.task_id).receipts
    assert any(item.receipt_id == receipt.receipt_id and item.passed for item in persisted_receipts)
    assert reopened_leases.list(str(repository))[0]["lease_id"] == lease["lease_id"]
