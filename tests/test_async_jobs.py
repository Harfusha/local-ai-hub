from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import closing

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
        self.enqueued = threading.Event()

    def enqueue(self, model, tenant, source, execute, priority=1, *, background=True):
        self.calls.append({"model": model, "tenant": tenant, "source": source, "execute": execute, "priority": priority, "background": background})
        self.enqueued.set()
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



def test_async_jobs_rebuilds_non_current_schema(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    db_path = state_dir / "async_jobs.sqlite3"
    with closing(sqlite3.connect(db_path)) as con:
        con.execute("CREATE TABLE async_jobs (job_id TEXT PRIMARY KEY, tenant TEXT NOT NULL)")
        con.execute("INSERT INTO async_jobs(job_id, tenant) VALUES('stale', 'tenant-a')")
        con.commit()

    manager, _scheduler = _manager(tmp_path)
    try:
        with closing(sqlite3.connect(db_path)) as con:
            columns = [str(row[1]) for row in con.execute("PRAGMA table_info(async_jobs)")]
            rows = con.execute("SELECT COUNT(*) FROM async_jobs").fetchone()[0]
        assert columns == [
            "job_id", "tenant", "action", "request_hash", "payload_json", "state", "result_json",
            "artifact_id", "error", "lease_until", "attempts", "cancel_requested", "created_at",
            "updated_at", "expires_at", "trace_id", "task_id",
        ]
        assert rows == 0
    finally:
        manager.close()

def test_submit_coalesces_active_job_and_uses_background_enqueue(tmp_path):
    manager, scheduler = _manager(tmp_path)

    first = manager.submit("tenant-a", "reason", {"task": "same"})
    second = manager.submit("tenant-a", "reason", {"task": "same"})
    assert scheduler.enqueued.wait(1)

    assert first["job_id"] == second["job_id"]
    assert second["coalesced"] is True
    assert len(scheduler.calls) == 1
    assert scheduler.calls[0]["background"] is True
    assert scheduler.calls[0]["priority"] == 1
    manager.close()


def test_submit_returns_before_slow_scheduler_enqueue(tmp_path):
    release = threading.Event()
    started = threading.Event()

    class _SlowScheduler(_Scheduler):
        def enqueue(self, *args, **kwargs):
            started.set()
            release.wait(1.5)
            return super().enqueue(*args, **kwargs)

    scheduler = _SlowScheduler()
    manager = AsyncJobManager(
        {"server": {"state_dir": str(tmp_path / "state")}, "async_jobs": {"wait_max_seconds": 90}},
        scheduler,
        _Artifacts(),
        lambda action, payload, tenant: {"success": True, "action": action},
    )
    try:
        started_at = time.monotonic()
        submitted = manager.submit("tenant-a", "reason", {"task": "slow dispatch"})
        elapsed = time.monotonic() - started_at

        assert submitted["success"] is True
        assert elapsed < 0.75
        assert started.wait(0.5)
    finally:
        release.set()
        manager.close()


def test_review_diff_is_supported_as_async_job(tmp_path):
    manager, _scheduler = _manager(tmp_path)

    submitted = manager.submit("tenant-a", "review_diff", {"task": "review", "context": "diff"})

    assert submitted["success"] is True
    manager.close()


def test_wait_clamps_to_ninety_seconds_without_polling(tmp_path):
    manager, _scheduler = _manager(tmp_path)
    submitted = manager.submit("tenant-a", "reason", {"task": "same"})
    manager.cancel("tenant-a", submitted["job_id"])

    result = manager.wait("tenant-a", submitted["job_id"], 999)

    assert result["wait_timeout_seconds"] == 90
    assert result["state"] == "cancelled"
    manager.close()


def test_recovery_requeues_persisted_job_once(tmp_path):
    manager, scheduler = _manager(tmp_path)
    submitted = manager.submit("tenant-a", "reason", {"task": "resume"})

    assert manager.recover() == 1
    assert manager.status("tenant-a", submitted["job_id"])["state"] == "queued"
    assert len(scheduler.calls) == 2
    manager.close()


def test_completed_job_returns_artifact_backed_result(tmp_path):
    manager, _scheduler = _manager(tmp_path)
    submitted = manager.submit("tenant-a", "reason", {"task": "finish"})

    manager._execute(submitted["job_id"])
    result = manager.result("tenant-a", submitted["job_id"])

    assert result["success"] is True
    assert result["artifact_id"] == "artifact-1"
    assert result["result"]["task"] == "finish"
    manager.close()


def test_malformed_executor_result_fails_job_without_retry(tmp_path):
    scheduler = _Scheduler()
    manager = AsyncJobManager(
        {"server": {"state_dir": str(tmp_path / "state")}, "async_jobs": {"wait_max_seconds": 90}},
        scheduler,
        _Artifacts(),
        lambda _action, _payload, _tenant: "not a result object",
    )
    try:
        submitted = manager.submit("tenant-a", "reason", {"task": "bad result"})

        result = manager._execute(submitted["job_id"])

        assert result["success"] is False
        assert result["retryable"] is False
        assert manager.status("tenant-a", submitted["job_id"])["state"] == "failed"
    finally:
        manager.close()


def test_async_job_trace_links_prompt_scheduler_and_terminal_state(tmp_path):
    config = {"server": {"state_dir": str(tmp_path / "state")}, "async_jobs": {"wait_max_seconds": 90}, "debug_traces": {"enabled": True}}
    store = DebugTraceStore(config)
    scheduler = _Scheduler()
    manager = AsyncJobManager(config, scheduler, _Artifacts(), lambda action, payload, tenant: {"success": True, "action": action, "task": payload.get("task"), "tenant": tenant}, debug_traces=store)

    submitted = manager.submit("tenant-a", "reason", {"task": "trace me", "context": "full context"})
    assert scheduler.enqueued.wait(1)
    manager._execute(submitted["job_id"])

    detail = store.detail(submitted["trace_id"])
    assert detail["session"]["request"]["task"] == "trace me"
    assert detail["session"]["async_job_id"] == submitted["job_id"]
    assert detail["session"]["scheduler_job_id"] == "7"
    assert detail["session"]["state"] == "done"
    assert [event["event_type"] for event in detail["events"]][-2:] == ["running", "done"]
    manager.close()


def test_async_jobs_tick_evicts_terminal_events(tmp_path):
    mgr = AsyncJobManager(
        {"server": {"state_dir": str(tmp_path / "state")}},
        _Scheduler(),
        None,
        lambda _action, _payload, _tenant: {"success": True},
    )
    res = mgr.submit("tenant-1", "reason", {"task": "hello"})
    assert res["success"] is True
    job_id = res["job_id"]
    assert job_id in mgr._events

    mgr._execute(job_id)
    assert mgr.status("tenant-1", job_id)["state"] == "done"
    assert job_id in mgr._events

    mgr.tick()
    assert job_id not in mgr._events
    mgr.close()



def test_close_releases_watchers_and_rejects_new_jobs(tmp_path):
    manager, _scheduler = _manager(tmp_path)
    submitted = manager.submit("tenant-a", "reason", {"task": "long-running"})
    assert submitted["success"] is True
    assert manager._dispatchers or manager._watchers

    manager.close()

    assert not any(thread.is_alive() for thread in manager._watchers)
    rejected = manager.submit("tenant-a", "reason", {"task": "too-late"})
    assert rejected == {
        "success": False,
        "error": "async job manager is closed",
        "terminal": True,
        "retryable": False,
    }
