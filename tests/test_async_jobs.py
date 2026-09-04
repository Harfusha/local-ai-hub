from __future__ import annotations

import threading

from local_ai_hub.async_jobs import AsyncJobManager
from local_ai_hub.debug_traces import DebugTraceStore


class _Job:
    def __init__(self) -> None:
        self.id = 7
        self.done = threading.Event()
        self.error = None


class _Scheduler:
    config = {"models": {"heavy_code": "test-model"}}

    def __init__(self) -> None:
        self.calls = []

    def enqueue(self, model, tenant, source, execute, priority=1, *, background=True):
        self.calls.append({"model": model, "tenant": tenant, "source": source, "execute": execute, "priority": priority, "background": background})
        return _Job()


class _Artifacts:
    def put(self, _content, _tenant, _kind):
        return "artifact-1"


def _manager(tmp_path):
    scheduler = _Scheduler()
    manager = AsyncJobManager(
        {"server": {"state_dir": str(tmp_path / "state")}, "async_jobs": {"wait_max_seconds": 90}},
        scheduler,
        _Artifacts(),
        lambda action, payload, tenant: {"success": True, "action": action, "task": payload.get("task"), "tenant": tenant},
    )
    return manager, scheduler


def test_submit_coalesces_active_job_and_uses_background_enqueue(tmp_path):
    manager, scheduler = _manager(tmp_path)

    first = manager.submit("tenant-a", "reason", {"task": "same"})
    second = manager.submit("tenant-a", "reason", {"task": "same"})

    assert first["job_id"] == second["job_id"]
    assert second["coalesced"] is True
    assert len(scheduler.calls) == 1
    assert scheduler.calls[0]["background"] is True
    assert scheduler.calls[0]["priority"] == 1


def test_wait_clamps_to_ninety_seconds_without_polling(tmp_path):
    manager, _scheduler = _manager(tmp_path)
    submitted = manager.submit("tenant-a", "reason", {"task": "same"})
    manager.cancel("tenant-a", submitted["job_id"])

    result = manager.wait("tenant-a", submitted["job_id"], 999)

    assert result["wait_timeout_seconds"] == 90
    assert result["state"] == "cancelled"


def test_recovery_requeues_persisted_job_once(tmp_path):
    manager, scheduler = _manager(tmp_path)
    submitted = manager.submit("tenant-a", "reason", {"task": "resume"})

    assert manager.recover() == 1
    assert manager.status("tenant-a", submitted["job_id"])["state"] == "queued"
    assert len(scheduler.calls) == 2


def test_completed_job_returns_artifact_backed_result(tmp_path):
    manager, _scheduler = _manager(tmp_path)
    submitted = manager.submit("tenant-a", "reason", {"task": "finish"})

    manager._execute(submitted["job_id"])
    result = manager.result("tenant-a", submitted["job_id"])

    assert result["success"] is True
    assert result["artifact_id"] == "artifact-1"
    assert result["result"]["task"] == "finish"


def test_async_job_trace_links_prompt_scheduler_and_terminal_state(tmp_path):
    config = {"server": {"state_dir": str(tmp_path / "state")}, "async_jobs": {"wait_max_seconds": 90}, "debug_traces": {"enabled": True}}
    store = DebugTraceStore(config)
    scheduler = _Scheduler()
    manager = AsyncJobManager(config, scheduler, _Artifacts(), lambda action, payload, tenant: {"success": True, "action": action, "task": payload.get("task"), "tenant": tenant}, debug_traces=store)

    submitted = manager.submit("tenant-a", "reason", {"task": "trace me", "context": "full context"})
    manager._execute(submitted["job_id"])

    detail = store.detail(submitted["trace_id"])
    assert detail["session"]["request"]["task"] == "trace me"
    assert detail["session"]["async_job_id"] == submitted["job_id"]
    assert detail["session"]["scheduler_job_id"] == "7"
    assert detail["session"]["state"] == "done"
    assert [event["event_type"] for event in detail["events"]][-2:] == ["running", "done"]
