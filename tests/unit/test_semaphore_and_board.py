from __future__ import annotations

import multiprocessing
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from local_ai_hub.agent_board import BoardStore
from local_ai_hub.agent_events import SwarmPubSub
from local_ai_hub.agent_semaphores import SemaphoreStore


def _semaphore_process_acquire(
    db_path: str,
    owner: str,
    start_event: Any,
    ready_queue: Any,
    result_queue: Any,
) -> None:
    ready_queue.put(owner)
    if not start_event.wait(timeout=5.0):
        result_queue.put({"owner": owner, "error": "start barrier timed out"})
        return
    result = SemaphoreStore(db_path).acquire("process_slot", owner=owner, capacity=1)
    result_queue.put({"owner": owner, "acquired": result["acquired"], "lease_id": result.get("lease_id")})


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
    rel1 = store.release("unity_slot", lease_id_1, owner="agent-1")
    assert rel1["success"] is True
    assert rel1["released"] is True

    # 6. Now third agent can acquire
    res4 = store.acquire("unity_slot", owner="agent-3", capacity=2, timeout=0.0)
    assert res4["success"] is True
    assert res4["acquired"] is True
    assert res4["lease_id"] != ""

    # Clean release remaining
    store.release("unity_slot", lease_id_2, owner="agent-2")
    store.release("unity_slot", res4["lease_id"], owner="agent-3")

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
    rel = store.release("gpu_slot", lease_1, owner="worker-1")
    assert rel["released"] is True

    # Wait for thread to finish
    t.join(timeout=3.0)
    assert not t.is_alive()

    assert worker_2_result.get("success") is True
    assert worker_2_result.get("acquired") is True
    assert worker_2_result.get("lease_id") != ""

    store.release("gpu_slot", worker_2_result["lease_id"], owner="worker-2")


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
    store.release("temp_slot", res_ok["lease_id"], owner="second-agent")


def test_semaphore_single_capacity_is_process_safe(tmp_path: Path) -> None:
    db_path = tmp_path / "semaphores_process_race.sqlite"
    store = SemaphoreStore(db_path)
    store.status("process_slot")

    context = multiprocessing.get_context("spawn")
    start_event = context.Event()
    ready_queue = context.Queue()
    result_queue = context.Queue()
    workers = [
        context.Process(
            target=_semaphore_process_acquire,
            args=(str(db_path), f"worker-{index}", start_event, ready_queue, result_queue),
        )
        for index in range(2)
    ]
    try:
        for process in workers:
            process.start()
        assert {ready_queue.get(timeout=5.0) for _ in workers} == {"worker-0", "worker-1"}
        start_event.set()
        for process in workers:
            process.join(timeout=8.0)
        assert all(not process.is_alive() for process in workers)
        assert all(process.exitcode == 0 for process in workers)

        outcomes = [result_queue.get(timeout=2.0) for _ in workers]
        assert all("error" not in outcome for outcome in outcomes)
        acquired = [outcome for outcome in outcomes if outcome["acquired"]]
        assert len(acquired) == 1
        winner = acquired[0]
        assert store.release("process_slot", winner["lease_id"], owner=winner["owner"])["released"] is True
    finally:
        for process in workers:
            if process.is_alive():
                process.terminate()
            process.join(timeout=1.0)
        ready_queue.close()
        result_queue.close()


def test_semaphore_waiter_wakes_when_holder_ttl_expires(tmp_path: Path) -> None:
    pubsub = SwarmPubSub()
    store = SemaphoreStore(tmp_path / "semaphores_ttl_wait.sqlite", pubsub=pubsub)
    held = store.acquire("ttl_wait_slot", owner="worker-1", ttl_seconds=0.15)
    assert held["acquired"] is True

    waiting = threading.Event()
    original_wait = pubsub.wait_for_event

    def observe_wait(
        topic: str,
        timeout: float = 60.0,
        filter_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        waiting.set()
        return original_wait(topic, timeout=timeout, filter_payload=filter_payload)

    pubsub.wait_for_event = observe_wait
    result: dict[str, Any] = {}

    def waiter() -> None:
        result.update(store.acquire("ttl_wait_slot", owner="worker-2", timeout=1.0))

    thread = threading.Thread(target=waiter)
    thread.start()
    assert waiting.wait(timeout=0.5)
    thread.join(timeout=0.5)
    if thread.is_alive():
        thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert result.get("success") is True
    assert result.get("acquired") is True
    store.release("ttl_wait_slot", result["lease_id"], owner="worker-2")


@pytest.mark.parametrize("timeout", [0.0, 0.05])
def test_semaphore_non_acquired_call_does_not_leave_stale_queue(
    tmp_path: Path,
    timeout: float,
) -> None:
    store = SemaphoreStore(tmp_path / "semaphores_stale_wait.sqlite", pubsub=SwarmPubSub())
    held = store.acquire("stale_wait_slot", owner="worker-1")

    result = store.acquire("stale_wait_slot", owner="worker-2", timeout=timeout)

    assert result["acquired"] is False
    assert store.status("stale_wait_slot")["semaphore"]["queue_length"] == 0
    store.release("stale_wait_slot", held["lease_id"], owner="worker-1")


def test_semaphore_wait_queue_preserves_fifo_against_new_acquirer(tmp_path: Path) -> None:
    class ControlledPubSub:
        def __init__(self) -> None:
            self.waiting = {"waiter-1": threading.Event(), "waiter-2": threading.Event()}
            self.wake = {"waiter-1": threading.Event(), "waiter-2": threading.Event()}

        def wait_for_event(self, topic: str, timeout: float = 60.0) -> dict[str, Any]:
            owner = threading.current_thread().name
            self.waiting[owner].set()
            if self.wake[owner].wait(timeout):
                return {"success": True, "timeout": False}
            return {"success": False, "timeout": True}

        def publish(self, topic: str, payload: dict[str, Any], sender: str = "") -> dict[str, Any]:
            return {"success": True}

    pubsub = ControlledPubSub()
    store = SemaphoreStore(tmp_path / "semaphores_fifo.sqlite", pubsub=pubsub)
    held = store.acquire("fifo_slot", owner="holder")
    results: dict[str, dict[str, Any]] = {}

    def wait(owner: str) -> None:
        results[owner] = store.acquire("fifo_slot", owner=owner, timeout=3.0)

    first = threading.Thread(target=wait, args=("waiter-1",), name="waiter-1")
    second = threading.Thread(target=wait, args=("waiter-2",), name="waiter-2")
    newcomer_result: dict[str, Any] = {}
    first.start()
    try:
        assert pubsub.waiting["waiter-1"].wait(timeout=1.0)
        second.start()
        assert pubsub.waiting["waiter-2"].wait(timeout=1.0)
        queue = store.status("fifo_slot")["semaphore"]["queue"]
        assert [entry["owner"] for entry in queue] == ["waiter-1", "waiter-2"]

        assert store.release("fifo_slot", held["lease_id"], owner="holder")["released"] is True
        newcomer_result = store.acquire("fifo_slot", owner="newcomer", timeout=0.0)
        assert newcomer_result["acquired"] is False
        assert [entry["owner"] for entry in store.status("fifo_slot")["semaphore"]["queue"]] == [
            "waiter-1",
            "waiter-2",
        ]

        pubsub.wake["waiter-1"].set()
        first.join(timeout=1.0)
        assert not first.is_alive()
        assert results["waiter-1"]["acquired"] is True
        assert store.release("fifo_slot", results["waiter-1"]["lease_id"], owner="waiter-1")["released"] is True

        pubsub.wake["waiter-2"].set()
        second.join(timeout=1.0)
        assert not second.is_alive()
        assert results["waiter-2"]["acquired"] is True
        assert store.release("fifo_slot", results["waiter-2"]["lease_id"], owner="waiter-2")["released"] is True
    finally:
        for owner in pubsub.wake:
            pubsub.wake[owner].set()
        for thread in (first, second):
            if thread.ident is not None:
                thread.join(timeout=1.0)
        if newcomer_result.get("acquired"):
            store.release("fifo_slot", newcomer_result["lease_id"], owner="newcomer")
        for owner, result in results.items():
            if result.get("acquired"):
                store.release("fifo_slot", result["lease_id"], owner=owner)


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


def test_legacy_board_writes_are_rejected(tmp_path: Path) -> None:
    db_path = tmp_path / "board.sqlite"
    board = BoardStore(db_path)

    milestone = board.milestone_create(
        "v1.0", target_date="2026-11-01", description="Initial release"
    )
    item = board.item_create(title="Implement semaphores", status="planned")

    assert milestone["success"] is False
    assert milestone["error_code"] == "legacy_board_read_only"
    assert item["success"] is False
    assert item["error_code"] == "legacy_board_read_only"


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

