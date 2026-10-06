import sqlite3
from contextlib import closing

import pytest

from local_ai_hub.agent_events import AgentEvent, AgentStateStore
from local_ai_hub.agent_memory import AgentScope, MemoryKind, MemoryRecord, MemoryStore
from local_ai_hub.agent_tasks import GoalContract, ScopeContext, TaskStore
from local_ai_hub.agent_verification import VerificationReceipt, VerificationStore
from local_ai_hub.cache import SQLiteCache

def _get_task_memory(store, record_id, *, task_id, root):
    return store.get(
        record_id,
        scope=AgentScope.TASK,
        scope_id=task_id,
        root=str(root),
        tenant="t08-cache-test",
        task_id=task_id,
    )


def test_disposable_cache_rebuild_preserves_live_agent_state(tmp_path):
    state_path = tmp_path / "agent_state.sqlite"
    cache_path = tmp_path / "cache.sqlite"
    state_store = AgentStateStore(state_path)
    task_store = TaskStore(state_store)
    task_id = "task-cache-rebuild-preserves-state"
    task_store.create(
        GoalContract(
            goal="preserve state when rebuilding disposable cache",
            acceptance_criteria=("agent state survives cache recovery",),
        ),
        ScopeContext(task_id=task_id),
        task_id=task_id,
    )
    event = state_store.append(
        AgentEvent.create(
            "stream-cache-rebuild",
            "cache.rebuild.probe",
            {"preserved": True},
            idempotency_key="cache-rebuild-probe",
        )
    ).event
    assert event is not None
    memory = MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.TASK,
        scope_id=task_id,
        key="cache-rebuild-probe",
        value={"preserved": True},
        source="T08 cache isolation regression",
        provenance={"root": str(tmp_path.resolve()), "tenant": "t08-cache-test"},
    )
    MemoryStore(state_store).record(memory, actor="test")
    receipt = VerificationReceipt.create(
        task_id,
        "cache isolation",
        passed=True,
        evidence_id="cache-rebuild-probe",
    )
    VerificationStore(state_store, task_store=task_store).record(receipt)

    cache_path.write_bytes(b"damaged disposable cache")
    cache = SQLiteCache(cache_path, "t08-live-state-isolation")
    cache.set("rebuilt", {"ready": True})

    reopened = AgentStateStore(state_path)
    assert TaskStore(reopened).get(task_id) is not None
    assert reopened.events(event.stream_id) == [event]
    recovered_memory = _get_task_memory(
        MemoryStore(reopened), memory.record_id, task_id=task_id, root=tmp_path
    )
    assert recovered_memory is not None
    assert recovered_memory.value == {"preserved": True}
    assert len(list(tmp_path.glob("cache.sqlite.corrupt-*"))) == 1
    with closing(sqlite3.connect(state_path)) as con:
        assert con.execute(
            "SELECT task_id, criterion, evidence_id, passed FROM agent_verification_receipts "
            "WHERE receipt_id = ?",
            (receipt.receipt_id,),
        ).fetchall() == [(task_id, "cache isolation", "cache-rebuild-probe", 1)]
    reopened_cache = SQLiteCache(cache_path, "t08-live-state-isolation")
    assert reopened_cache.get("rebuilt") == {"ready": True}


def test_failed_disposable_cache_schema_rebuild_preserves_live_agent_state(
    tmp_path, monkeypatch
):
    state_path = tmp_path / "agent_state.sqlite"
    cache_path = tmp_path / "cache.sqlite"
    state_store = AgentStateStore(state_path)
    task_store = TaskStore(state_store)
    task_id = "task-cache-schema-failure-preserves-state"
    task_store.create(
        GoalContract(
            goal="preserve state when disposable cache schema rebuild fails",
            acceptance_criteria=("cache schema failure",),
        ),
        ScopeContext(task_id=task_id),
        task_id=task_id,
    )
    event = state_store.append(
        AgentEvent.create(
            "stream-cache-schema-failure",
            "cache.schema_failure.probe",
            {"preserved": True},
            idempotency_key="cache-schema-failure-probe",
        )
    ).event
    memory = MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.TASK,
        scope_id=task_id,
        key="cache-schema-failure-probe",
        value={"preserved": True},
        source="T08 cache schema failure regression",
        provenance={"root": str(tmp_path.resolve()), "tenant": "t08-cache-test"},
    )
    MemoryStore(state_store).record(memory, actor="test")
    receipt = VerificationReceipt.create(
        task_id,
        "cache schema failure",
        passed=True,
        evidence_id="cache-schema-failure-probe",
    )
    VerificationStore(state_store, task_store=task_store).record(receipt)
    cache_path.write_bytes(b"damaged disposable cache")

    def fail_schema_creation(_cache):
        raise sqlite3.DatabaseError("injected cache schema failure")

    with monkeypatch.context() as patcher:
        patcher.setattr(SQLiteCache, "_create_schema", fail_schema_creation)
        with pytest.raises(sqlite3.DatabaseError, match="injected cache schema failure"):
            SQLiteCache(cache_path, "t08-live-state-isolation")

    reopened = AgentStateStore(state_path)
    recovered_task = TaskStore(reopened).get(task_id)
    assert recovered_task is not None
    assert reopened.events(event.stream_id) == [event]
    recovered_memory = _get_task_memory(
        MemoryStore(reopened), memory.record_id, task_id=task_id, root=tmp_path
    )
    assert recovered_memory.value == {"preserved": True}
    with closing(sqlite3.connect(state_path)) as con:
        assert con.execute(
            "SELECT task_id, criterion, evidence_id, passed FROM agent_verification_receipts "
            "WHERE receipt_id = ?",
            (receipt.receipt_id,),
        ).fetchall() == [(task_id, "cache schema failure", "cache-schema-failure-probe", 1)]
    assert len(list(tmp_path.glob("cache.sqlite.corrupt-*"))) == 1

    rebuilt_cache = SQLiteCache(cache_path, "t08-live-state-isolation")
    rebuilt_cache.set("rebuilt-after-failure", {"ready": True})
    assert SQLiteCache(cache_path, "t08-live-state-isolation").get(
        "rebuilt-after-failure"
    ) == {"ready": True}
