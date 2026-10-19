from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest

from local_ai_hub.agent_board import BoardStore
from local_ai_hub.agent_events import SwarmPubSub
from local_ai_hub.agent_semaphores import SemaphoreStore


def test_semaphore_basic_acquire_release(tmp_path: Path) -> None:
    db_path = tmp_path / "semaphores.sqlite"
    store = SemaphoreStore(db_path)

    # 1. Acquire slot 1 of 2
    res1 = store.acquire("unity_slot", owner="agent-1", capacity=2, purpose="render scene")
    assert res1["success"] is True
    assert res1["acquired"] is True
    assert res1["lease_id"] != ""
    assert res1["available_slots"] == 1
    lease_id_1 = res1["lease_id"]

    # 2. Acquire slot 2 of 2
    res2 = store.acquire("unity_slot", owner="agent-2", capacity=2, purpose="bake navmesh")
    assert res2["success"] is True
    assert res2["acquired"] is True
    assert res2["available_slots"] == 0
    lease_id_2 = res2["lease_id"]

    # 3. Third acquire fails immediately when timeout=0
    res3 = store.acquire("unity_slot", owner="agent-3", capacity=2, timeout=0.0)
    assert res3["success"] is True
    assert res3["acquired"] is False
    assert res3["reason"] == "capacity_reached"

    # 4. Status check
    st = store.status("unity_slot")
    assert st["success"] is True
    sem = st["semaphores"]["unity_slot"]
    assert sem["capacity"] == 2
    assert sem["active_count"] == 2
    assert len(sem["active_holders"]) == 2

    # 5. Release slot 1
    rel1 = store.release("unity_slot", lease_id_1)
    assert rel1["success"] is True
    assert rel1["released"] is True

    # 6. Now third agent can acquire
    res4 = store.acquire("unity_slot", owner="agent-3", capacity=2, timeout=0.0)
    assert res4["success"] is True
    assert res4["acquired"] is True
    assert res4["lease_id"] != ""

    # Clean release remaining
    store.release("unity_slot", lease_id_2)
    store.release("unity_slot", res4["lease_id"])

    st2 = store.status("unity_slot")
    assert st2["semaphores"]["unity_slot"]["active_count"] == 0


def test_semaphore_wait_and_wakeup(tmp_path: Path) -> None:
    db_path = tmp_path / "semaphores_wait.sqlite"
    pubsub = SwarmPubSub()
    store = SemaphoreStore(db_path, pubsub=pubsub)

    # Acquire only available slot
    res1 = store.acquire("gpu_slot", owner="worker-1", capacity=1)
    assert res1["acquired"] is True
    lease_1 = res1["lease_id"]

    worker_2_result: dict[str, Any] = {}

    def worker_2_task():
        nonlocal worker_2_result
        worker_2_result = store.acquire("gpu_slot", owner="worker-2", capacity=1, timeout=5.0)

    t = threading.Thread(target=worker_2_task)
    t.start()

    # Give worker 2 time to start waiting
    time.sleep(0.1)

    # Release worker 1's lease
    rel = store.release("gpu_slot", lease_1)
    assert rel["released"] is True

    # Wait for thread to finish
    t.join(timeout=3.0)
    assert not t.is_alive()

    assert worker_2_result.get("success") is True
    assert worker_2_result.get("acquired") is True
    assert worker_2_result.get("lease_id") != ""

    store.release("gpu_slot", worker_2_result["lease_id"])


def test_semaphore_ttl_expiration(tmp_path: Path) -> None:
    db_path = tmp_path / "semaphores_ttl.sqlite"
    store = SemaphoreStore(db_path)

    # Acquire with very short TTL
    res = store.acquire("temp_slot", owner="short-agent", capacity=1, ttl_seconds=0.2)
    assert res["acquired"] is True

    # Immediate second acquire fails
    res_fail = store.acquire("temp_slot", owner="second-agent", capacity=1, timeout=0.0)
    assert res_fail["acquired"] is False

    # Wait for TTL to expire
    time.sleep(0.3)

    # After expiry, second agent can acquire
    res_ok = store.acquire("temp_slot", owner="second-agent", capacity=1, timeout=0.0)
    assert res_ok["acquired"] is True
    store.release("temp_slot", res_ok["lease_id"])


def test_wait_for_event_pubsub() -> None:
    bus = SwarmPubSub()

    # 1. Timeout when no event published
    res_timeout = bus.wait_for_event("test_topic", timeout=0.1)
    assert res_timeout["success"] is False
    assert res_timeout["timed_out"] is True
    assert res_timeout["event"] is None

    # 2. Successful wake-up upon event published on thread
    received: dict[str, Any] = {}

    def listener():
        nonlocal received
        received = bus.wait_for_event("test_topic", timeout=3.0)

    t = threading.Thread(target=listener)
    t.start()

    time.sleep(0.05)
    bus.publish("test_topic", {"type": "build_done", "exit_code": 0}, sender="builder")

    t.join(timeout=2.0)
    assert not t.is_alive()

    assert received.get("success") is True
    assert received.get("timed_out") is False
    evt = received.get("event", {})
    assert evt.get("topic") == "test_topic"
    assert evt.get("message", {}).get("type") == "build_done"
    assert evt.get("sender") == "builder"


def test_wait_for_event_with_filter() -> None:
    bus = SwarmPubSub()

    received: dict[str, Any] = {}

    def listener():
        nonlocal received
        received = bus.wait_for_event("tasks", timeout=3.0, filter_payload={"task_id": "task-42"})

    t = threading.Thread(target=listener)
    t.start()

    time.sleep(0.05)
    # Publish non-matching event
    bus.publish("tasks", {"task_id": "task-99", "status": "done"})
    time.sleep(0.05)
    # Publish matching event
    bus.publish("tasks", {"task_id": "task-42", "status": "completed"})

    t.join(timeout=2.0)
    assert not t.is_alive()

    assert received.get("success") is True
    assert received.get("event", {}).get("message", {}).get("task_id") == "task-42"


def test_board_item_lifecycle_and_milestones(tmp_path: Path) -> None:
    db_path = tmp_path / "board.sqlite"
    board = BoardStore(db_path)

    # 1. Create milestone
    m_res = board.milestone_create("v1.0", target_date="2026-11-01", description="Initial release")
    assert m_res["success"] is True
    assert m_res["milestone"]["name"] == "v1.0"

    # 2. Create board items
    item1 = board.item_create(
        title="Implement semaphores",
        status="planned",
        priority="high",
        labels=["sync", "core"],
        assignee="agent-1",
        milestone="v1.0",
        details={"note": "generic counting semaphore"},
    )
    assert item1["success"] is True
    id1 = item1["item"]["item_id"]

    item2 = board.item_create(
        title="Implement board",
        status="in_progress",
        priority="high",
        labels=["board"],
        assignee="agent-2",
        milestone="v1.0",
    )
    assert item2["success"] is True
    id2 = item2["item"]["item_id"]

    item3 = board.item_create(
        title="Add documentation",
        status="planned",
        priority="medium",
        milestone="v1.0",
    )
    assert item3["success"] is True
    id3 = item3["item"]["item_id"]

    # 3. Get item
    got = board.item_get(id1)
    assert got["success"] is True
    assert got["item"]["title"] == "Implement semaphores"
    assert got["item"]["labels"] == ["sync", "core"]

    # 4. Update item
    upd = board.item_update(id1, status="done")
    assert upd["success"] is True
    assert upd["item"]["status"] == "done"

    # 5. List items with filters
    done_items = board.item_list(status="done")
    assert done_items["total"] == 1
    assert done_items["items"][0]["item_id"] == id1

    agent2_items = board.item_list(assignee="agent-2")
    assert agent2_items["total"] == 1
    assert agent2_items["items"][0]["item_id"] == id2

    # 6. Milestone status
    m_stat = board.milestone_status("v1.0")
    assert m_stat["success"] is True
    assert m_stat["total_items"] == 3
    assert m_stat["done_items"] == 1
    assert m_stat["progress_percentage"] == 33.3

    # 7. Summary
    summ = board.summary()
    assert summ["success"] is True
    assert summ["by_status"]["done"] == 1
    assert summ["by_status"]["in_progress"] == 1
    assert summ["by_status"]["planned"] == 1
    assert summ["total_items"] == 3

    # 8. Delete item
    del_res = board.item_delete(id3)
    assert del_res["success"] is True
    del_get = board.item_get(id3)
    assert del_get["success"] is False

    # 9. Session briefing
    brief = board.session_briefing()
    assert brief["success"] is True
    assert "board" in brief
    assert brief["board"]["summary"]["total_items"] == 2
    assert "recent_items" in brief["board"]


def test_mcp_coord_routing_and_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    from local_ai_hub import mcp_server as local_ai_mcp

    calls: list[dict[str, Any]] = []

    def fake_coord(action: str, **kwargs: Any) -> dict[str, Any]:
        calls.append({"action": action, "kwargs": kwargs})
        return {"success": True, "action": action, "mocked": True}

    monkeypatch.setattr(local_ai_mcp.CLIENT, "coord", fake_coord)

    # 1. Semaphore Acquire
    res = local_ai_mcp.local_ai_coord(
        action="semaphore_acquire",
        name="unity_worker",
        capacity=2,
        owner="test-agent",
        ttl_seconds=300,
        purpose="render",
    )
    assert res["success"] is True
    assert calls[-1]["action"] == "semaphore_acquire"
    assert calls[-1]["kwargs"]["name"] == "unity_worker"
    assert calls[-1]["kwargs"]["capacity"] == 2
    assert calls[-1]["kwargs"]["owner"] == "test-agent"

    # 2. Semaphore Status
    res = local_ai_mcp.local_ai_coord(action="semaphore_status", name="unity_worker")
    assert res["success"] is True
    assert calls[-1]["action"] == "semaphore_status"
    assert calls[-1]["kwargs"]["name"] == "unity_worker"

    # 3. Semaphore Release
    res = local_ai_mcp.local_ai_coord(
        action="semaphore_release",
        name="unity_worker",
        lease_id="lease-xyz",
        owner="test-agent",
    )
    assert res["success"] is True
    assert calls[-1]["action"] == "semaphore_release"
    assert calls[-1]["kwargs"]["lease_id"] == "lease-xyz"

    # 4. Wait for event
    res = local_ai_mcp.local_ai_coord(
        action="wait_for_event",
        topic="build_pipeline",
        timeout=15.0,
        filter_payload={"status": "done"},
    )
    assert res["success"] is True
    assert calls[-1]["action"] == "wait_for_event"
    assert calls[-1]["kwargs"]["topic"] == "build_pipeline"
    assert calls[-1]["kwargs"]["timeout"] == 15.0

    # 5. Board Item Create
    res = local_ai_mcp.local_ai_coord(
        action="board_item_create",
        title="Fix texture glitch",
        status="planned",
        priority="high",
        labels=["graphics", "bug"],
        assignee="renderer-agent",
        milestone="v1.0",
        details={"asset": "hero.mat"},
    )
    assert res["success"] is True
    assert calls[-1]["action"] == "board_item_create"
    assert calls[-1]["kwargs"]["title"] == "Fix texture glitch"
    assert calls[-1]["kwargs"]["status"] == "planned"
    assert calls[-1]["kwargs"]["priority"] == "high"

    # 6. Board Item List
    res = local_ai_mcp.local_ai_coord(action="board_item_list", status="planned", limit=20)
    assert res["success"] is True
    assert calls[-1]["action"] == "board_item_list"
    assert calls[-1]["kwargs"]["status"] == "planned"
    assert calls[-1]["kwargs"]["limit"] == 20

    # 7. Board Summary
    res = local_ai_mcp.local_ai_coord(action="board_summary")
    assert res["success"] is True
    assert calls[-1]["action"] == "board_summary"

    # 8. Milestone Create
    res = local_ai_mcp.local_ai_coord(
        action="milestone_create",
        name="v1.0",
        target_date="2026-11-15",
        description="First major milestone",
    )
    assert res["success"] is True
    assert calls[-1]["action"] == "milestone_create"
    assert calls[-1]["kwargs"]["name"] == "v1.0"

    # 9. Milestone Status
    res = local_ai_mcp.local_ai_coord(action="milestone_status", name="v1.0")
    assert res["success"] is True
    assert calls[-1]["action"] == "milestone_status"
    assert calls[-1]["kwargs"]["name"] == "v1.0"

    # 10. Session Briefing
    res = local_ai_mcp.local_ai_coord(action="session_briefing", include=["board", "semaphores"])
    assert res["success"] is True
    assert calls[-1]["action"] == "session_briefing"
    assert calls[-1]["kwargs"]["include"] == ["board", "semaphores"]


def test_client_coord_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    from local_ai_hub import mcp_server as local_ai_mcp

    posted: list[dict[str, Any]] = []

    def fake_post(path: str, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        posted.append({"path": path, "payload": payload, "kwargs": kwargs})
        return {"success": True, "path": path}

    monkeypatch.setattr(local_ai_mcp.CLIENT, "post", fake_post)

    client = local_ai_mcp.CLIENT

    # 1. Semaphore acquire
    client.coord("semaphore_acquire", name="test_sem", capacity=3, owner="ag")
    assert posted[-1]["path"] == "/api/coord/semaphore_acquire"
    assert posted[-1]["payload"]["name"] == "test_sem"

    # 2. Semaphore release
    client.coord("semaphore_release", name="test_sem", lease_id="lid1")
    assert posted[-1]["path"] == "/api/coord/semaphore_release"
    assert posted[-1]["payload"]["lease_id"] == "lid1"

    # 3. Semaphore status
    client.coord("semaphore_status", name="test_sem")
    assert posted[-1]["path"] == "/api/coord/semaphore_status"

    # 4. Wait for event
    client.coord("wait_for_event", topic="ev_topic", timeout=5.0)
    assert posted[-1]["path"] == "/api/coord/wait_for_event"

    # 5. Board items
    client.coord("board_item_create", title="Test item", status="planned")
    assert posted[-1]["path"] == "/api/coord/board_item_create"

    client.coord("board_item_update", item_id="item-1", status="done")
    assert posted[-1]["path"] == "/api/coord/board_item_update"

    client.coord("board_item_get", item_id="item-1")
    assert posted[-1]["path"] == "/api/coord/board_item_get"

    client.coord("board_item_delete", item_id="item-1")
    assert posted[-1]["path"] == "/api/coord/board_item_delete"

    client.coord("board_item_list", status="done")
    assert posted[-1]["path"] == "/api/coord/board_item_list"

    client.coord("board_summary")
    assert posted[-1]["path"] == "/api/coord/board_summary"

    # 6. Milestones
    client.coord("milestone_create", name="m1", target_date="2026-12-01")
    assert posted[-1]["path"] == "/api/coord/milestone_create"

    client.coord("milestone_status", name="m1")
    assert posted[-1]["path"] == "/api/coord/milestone_status"

    # 7. Session briefing
    client.coord("session_briefing", include=["board"])
    assert posted[-1]["path"] == "/api/coord/session_briefing"

