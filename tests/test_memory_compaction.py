from __future__ import annotations

import time
import pytest
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import AgentScope
from local_ai_hub.agent_memory import MemoryKind, MemoryRecord, MemoryStatus, MemoryStore


def test_memory_compaction_basic(tmp_path):
    store_dir = tmp_path / "agent_state"
    state_store = AgentStateStore(store_dir)
    mem_store = MemoryStore(state_store)
    root = str(tmp_path.resolve())
    task_id = "compaction-test-task"

    # Insert 4 task-level fact records
    now = time.time()
    for i in range(4):
        rec = MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=AgentScope.TASK,
            scope_id=task_id,
            key=f"discovery_{i}",
            value={"detail": f"found item {i}"},
            confidence=0.9,
            source="test",
            provenance={"root": root, "task_id": task_id},
        )
        mem_store.record(rec)

    # Initial count should be 4
    active_before = mem_store.find(
        scope=AgentScope.TASK,
        status=MemoryStatus.ACTIVE,
        root=root,

        task_id=task_id,
    )
    assert len(active_before) == 4

    # Compact with min_records=3
    res = mem_store.compact(min_records=3, actor="test_runner")
    assert res["success"] is True
    assert res["compacted_groups"] == 1
    assert res["compacted_records"] == 4
    assert len(res["created_records"]) == 1

    digest_info = res["created_records"][0]
    assert digest_info["key"].startswith("compacted_fact_")
    assert digest_info["value"]["record_count"] == 4

    # Active records in TASK scope: the 4 original should now be SUPERSEDED, and 1 new compacted digest is ACTIVE
    active_after = mem_store.find(
        scope=AgentScope.TASK,
        status=MemoryStatus.ACTIVE,
        root=root,

        task_id=task_id,
    )
    assert len(active_after) == 1
    assert active_after[0].key.startswith("compacted_fact_")

    # Check that superseded records point to the digest
    superseded = mem_store.find(
        scope=AgentScope.TASK,
        status=MemoryStatus.SUPERSEDED,
        root=root,

        task_id=task_id,
    )
    assert len(superseded) == 4
    for r in superseded:
        assert r.supersedes_record_id == active_after[0].record_id


def test_memory_compaction_insufficient_records(tmp_path):
    store_dir = tmp_path / "agent_state"
    state_store = AgentStateStore(store_dir)
    mem_store = MemoryStore(state_store)
    root = str(tmp_path.resolve())
    task_id = "compaction-test-task"

    # Insert only 2 records
    for i in range(2):
        rec = MemoryRecord.create(
            kind=MemoryKind.GOTCHA,
            scope=AgentScope.TASK,
            scope_id=task_id,
            key=f"gotcha_{i}",
            value=f"watch out {i}",
            provenance={"root": root, "task_id": task_id},
        )
        mem_store.record(rec)

    # Compact with min_records=3 should skip
    res = mem_store.compact(min_records=3)
    assert res["success"] is True
    assert res["compacted_groups"] == 0
    assert res["compacted_records"] == 0
