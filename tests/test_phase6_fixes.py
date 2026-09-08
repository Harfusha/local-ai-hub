from __future__ import annotations

import queue
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from local_ai_hub.agent_blackboard import BlackboardStore
from local_ai_hub.agent_context import ContextCompiler
from local_ai_hub.agent_events import AgentEvent, AgentStateStore
from local_ai_hub.agent_identity import AgentScope
from local_ai_hub.agent_incidents import IncidentStore
from local_ai_hub.agent_memory import MemoryKind, MemoryRecord, MemoryStatus, MemoryStore
from local_ai_hub.agent_tasks import GoalContract, ScopeContext, TaskCheckpoint, TaskState, TaskStatus, TaskStore
from local_ai_hub.agent_verification import VerificationStore
from local_ai_hub.rag import RAGStore
from local_ai_hub.scheduler import QueueFullError


def test_memory_expiration_and_reap(tmp_path: Path) -> None:
    db = tmp_path / "state.sqlite3"
    state_store = AgentStateStore(db)
    mem_store = MemoryStore(state_store)

    now = time.time()
    # 1. Normal record (no expiry)
    rec1 = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.TASK,
        key="normal_key",
        value="normal_val",
    )
    # 2. Expired record
    rec2 = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.TASK,
        key="expired_key",
        value="expired_val",
        expires_at=now - 50.0,
    )
    # 3. Future expiring record
    rec3 = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.TASK,
        key="future_key",
        value="future_val",
        expires_at=now + 500.0,
    )

    mem_store.record(rec1)
    mem_store.record(rec2)
    mem_store.record(rec3)

    # find() should only return non-expired records by default
    found = mem_store.find()
    keys = {r.key for r in found}
    assert "normal_key" in keys
    assert "future_key" in keys
    assert "expired_key" not in keys

    # find(include_expired=True) returns all
    all_found = mem_store.find(include_expired=True)
    all_keys = {r.key for r in all_found}
    assert "expired_key" in all_keys

    # get() filters expired by default
    assert mem_store.get(rec2.record_id) is None
    assert mem_store.get(rec2.record_id, include_expired=True) is not None
    assert mem_store.get(rec1.record_id) is not None

    # reap_expired() removes expired records
    reaped = mem_store.reap_expired()
    assert reaped == 1
    assert mem_store.get(rec2.record_id, include_expired=True) is None
    assert mem_store.get(rec1.record_id) is not None


def test_task_heartbeat_and_extended_reap(tmp_path: Path) -> None:
    db = tmp_path / "state.sqlite3"
    state_store = AgentStateStore(db)
    task_store = TaskStore(state_store, default_heartbeat_ttl=10.0)

    contract = GoalContract(goal="test heartbeat")
    context = ScopeContext()
    t1 = task_store.create(contract, context, task_id="task_hb_1")
    t1 = task_store.transition(t1.task_id, TaskStatus.ACTIVE, reason="activate", actor="agent", idempotency_key="act1")

    # Call heartbeat
    before_hb = t1.heartbeat_expires_at
    time.sleep(0.01)
    t1_updated = task_store.heartbeat(t1.task_id, ttl_seconds=60.0)
    assert t1_updated.heartbeat_expires_at > before_hb

    # Create tasks in various states with expired heartbeats
    t_active = task_store.create(contract, context, task_id="task_act")
    task_store.transition(t_active.task_id, TaskStatus.ACTIVE, reason="act", actor="agent", idempotency_key="act_t")

    t_verifying = task_store.create(contract, context, task_id="task_ver")
    task_store.transition(t_verifying.task_id, TaskStatus.ACTIVE, reason="act", actor="agent", idempotency_key="act_v")
    task_store.transition(t_verifying.task_id, TaskStatus.VERIFYING, reason="ver", actor="agent", idempotency_key="ver_v")

    t_waiting = task_store.create(contract, context, task_id="task_wait")
    task_store.transition(t_waiting.task_id, TaskStatus.ACTIVE, reason="act", actor="agent", idempotency_key="act_w")
    task_store.transition(t_waiting.task_id, TaskStatus.WAITING, reason="wait", actor="agent", idempotency_key="wait_w")

    t_blocked = task_store.create(contract, context, task_id="task_block")
    task_store.transition(t_blocked.task_id, TaskStatus.ACTIVE, reason="act", actor="agent", idempotency_key="act_b")
    task_store.transition(t_blocked.task_id, TaskStatus.BLOCKED, reason="block", actor="agent", idempotency_key="block_b")

    # Manually backdate heartbeats after transitions complete
    with closing(sqlite3.connect(db)) as con:
        con.execute(
            "UPDATE agent_tasks_projection SET heartbeat_expires_at = ? WHERE task_id IN ('task_act', 'task_ver', 'task_wait', 'task_block')",
            (time.time() - 10,),
        )
        con.commit()

    reaped = task_store.reap_expired_heartbeats()
    assert "task_act" in reaped
    assert "task_ver" in reaped
    assert "task_wait" in reaped
    assert "task_block" in reaped

    assert task_store.get("task_act").status == TaskStatus.ABANDONED
    assert task_store.get("task_ver").status == TaskStatus.ABANDONED
    assert task_store.get("task_wait").status == TaskStatus.ABANDONED
    assert task_store.get("task_block").status == TaskStatus.ABANDONED


def test_task_complete_from_waiting_blocked(tmp_path: Path) -> None:
    db = tmp_path / "state.sqlite3"
    state_store = AgentStateStore(db)
    task_store = TaskStore(state_store)

    contract = GoalContract(goal="complete waiting", acceptance_criteria=())
    context = ScopeContext()
    t_wait = task_store.create(contract, context, task_id="t_wait_comp")
    task_store.transition(t_wait.task_id, TaskStatus.ACTIVE, reason="act", actor="agent", idempotency_key="act_wc")
    task_store.transition(t_wait.task_id, TaskStatus.WAITING, reason="wait", actor="agent", idempotency_key="wait_wc")

    completed = task_store.complete("t_wait_comp")
    assert completed.status == TaskStatus.COMPLETED

    t_block = task_store.create(contract, context, task_id="t_block_comp")
    task_store.transition(t_block.task_id, TaskStatus.ACTIVE, reason="act", actor="agent", idempotency_key="act_bc")
    task_store.transition(t_block.task_id, TaskStatus.BLOCKED, reason="block", actor="agent", idempotency_key="block_bc")

    completed_b = task_store.complete("t_block_comp")
    assert completed_b.status == TaskStatus.COMPLETED


def test_blackboard_delete(tmp_path: Path) -> None:
    db = tmp_path / "bb.sqlite3"
    bb = BlackboardStore(db)

    bb.update("board_1", "sec_a", "content_a", author="alice")
    bb.update("board_1", "sec_b", "content_b", author="bob")
    bb.update("board_2", "sec_c", "content_c", author="carol")

    # Delete single section
    del_res = bb.delete("board_1", section="sec_a")
    assert del_res["success"] is True
    assert del_res["deleted_count"] == 1
    assert bb.get("board_1", section="sec_a")["success"] is False
    assert len(bb.get("board_1")["sections"]) == 1

    # Delete entire board
    del_board = bb.delete("board_1")
    assert del_board["success"] is True
    assert del_board["deleted_count"] == 1
    assert bb.get("board_1")["sections"] == {}
    assert "board_1" not in bb.list_boards()
    assert "board_2" in bb.list_boards()


def test_event_store_schema_and_publish_overflow(tmp_path: Path) -> None:
    db = tmp_path / "events.sqlite3"
    store = AgentStateStore(db)

    # Subscribe with tiny queue
    q = store.subscribe(maxsize=2)
    # Append 5 events
    for i in range(5):
        store.append(AgentEvent.create(stream_id="s1", kind="test.evt", payload={"idx": i}))

    # Queue should contain newest items without blocking or overflowing
    items = []
    while not q.empty():
        items.append(q.get_nowait())
    assert len(items) <= 2
    # The last appended item should be in the queue
    last_payload = items[-1].payload
    assert last_payload["idx"] == 4


def test_store_concurrency_locks(tmp_path: Path) -> None:
    db = tmp_path / "concurrent.sqlite3"
    state_store = AgentStateStore(db)

    errors: list[Exception] = []

    def init_stores() -> None:
        try:
            m = MemoryStore(state_store)
            i = IncidentStore(state_store)
            v = VerificationStore(state_store)
            c = ContextCompiler(state_store)
            assert m._initialized
            assert i._initialized
            assert v._initialized
            assert c._initialized
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=init_stores) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []


def test_rag_embedder_queue_exception_handling(tmp_path: Path) -> None:
    services = MagicMock()
    # Mock services.embed to raise QueueFullError
    services.embed.side_effect = QueueFullError("queue full")

    config = {
        "server": {"state_dir": str(tmp_path / "state")},
        "rag": {"scope": "shared", "extensions": [".py"]},
    }
    store = RAGStore(config=config, services=services, reranker=MagicMock())
    root = tmp_path / "proj"
    root.mkdir()
    f1 = root / "code.py"
    f1.write_text("def hello():\n    return 'world'\n", encoding="utf-8")

    res = store.index(str(root), tenant="t1", workspace="w1")
    assert res["success"] is False
    assert res["retryable"] is True
    assert "busy or timed out" in res["error"]


def test_http_and_mcp_coordination_endpoints(tmp_path: Path) -> None:
    from local_ai_hub.client import HubClient

    c = HubClient.__new__(HubClient)
    c.post = MagicMock(return_value={"success": True, "deleted_count": 1})
    res = c.coord("blackboard_delete", board_id="b1", section="s1")
    assert res["success"] is True
    c.post.assert_called_once_with(
        "/v1/agent-state/blackboard",
        {
            "action": "delete",
            "board_id": "b1",
            "section": "s1",
            "content": None,
            "author": "agent",
            "remote_sections": {},
            "clock": None,
        },
    )
