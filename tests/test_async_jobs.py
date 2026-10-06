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

def test_submit_coalesces_active_job_without_outer_scheduler_enqueue(tmp_path):
    manager, scheduler = _manager(tmp_path)

    first = manager.submit("tenant-a", "reason", {"task": "same"})
    second = manager.submit("tenant-a", "reason", {"task": "same"})
    assert first["job_id"] == second["job_id"]
    assert second["coalesced"] is True
    assert second["admission"]["state"] == "coalesced"
    assert second["admission"]["reason"] == "duplicate_active_job"
    assert scheduler.calls == []
    manager.close()


def test_async_execution_does_not_consume_model_scheduler_slot(tmp_path):
    manager, scheduler = _manager(tmp_path)

    submitted = manager.submit("tenant-a", "reason", {"task": "run outside model slot"})
    result = manager.wait("tenant-a", submitted["job_id"], 1)

    assert result["state"] == "done"
    assert scheduler.calls == []
    manager.close()


def test_submit_returns_before_slow_async_execution(tmp_path):
    release = threading.Event()
    started = threading.Event()

    def execute(_action, _payload, _tenant):
        started.set()
        release.wait(1.5)
        return {"success": True}

    scheduler = _Scheduler()
    manager = AsyncJobManager(
        {"server": {"state_dir": str(tmp_path / "state")}, "async_jobs": {"wait_max_seconds": 90}},
        scheduler,
        _Artifacts(),
        execute,
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
    now = time.time()
    with closing(manager._connect()) as con:
        con.execute(
            "INSERT INTO async_jobs(job_id,tenant,action,request_hash,payload_json,state,created_at,updated_at,expires_at) VALUES(?,?,?,?,?,'running',?,?,?)",
            ("persisted", "tenant-a", "reason", "persisted-hash", '{"task":"resume","request_id":"recovery-persisted-001"}', now, now, now + 600),
        )
        con.commit()

    assert manager.recover() == 1
    assert manager.wait("tenant-a", "persisted", 1)["state"] == "done"
    assert scheduler.calls == []
    manager.close()


def test_recovery_keeps_unkeyed_running_job_outcome_unknown(tmp_path):
    manager, scheduler = _manager(tmp_path)
    dispatched = []
    manager._dispatch = dispatched.append
    now = time.time()
    with closing(manager._connect()) as con:
        con.execute(
            "INSERT INTO async_jobs(job_id,tenant,action,request_hash,payload_json,state,created_at,updated_at,expires_at) VALUES(?,?,?,?,?,'running',?,?,?)",
            ("unkeyed-persisted", "tenant-a", "reason", "unkeyed-persisted-hash", '{"task":"resume"}', now, now, now + 600),
        )
        con.commit()

    assert manager.recover() == 0
    status = manager.status("tenant-a", "unkeyed-persisted")
    assert status["state"] == "outcome_unknown"
    assert status["terminal"] is True
    assert status["retryable"] is False
    assert dispatched == []
    assert scheduler.calls == []
    manager.close()


def test_completed_job_returns_artifact_backed_result(tmp_path):
    manager, _scheduler = _manager(tmp_path)
    submitted = manager.submit("tenant-a", "reason", {"task": "finish"})
    assert manager.wait("tenant-a", submitted["job_id"], 3)["state"] == "done"
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

        assert manager.wait("tenant-a", submitted["job_id"], 1)["state"] == "failed"
        result = manager.result("tenant-a", submitted["job_id"])

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
    assert manager.wait("tenant-a", submitted["job_id"], 3)["state"] == "done"
    detail = store.detail(submitted["trace_id"])
    assert detail["session"]["request"]["task"] == "trace me"
    assert detail["session"]["async_job_id"] == submitted["job_id"]
    assert detail["session"]["scheduler_job_id"] == ""
    assert detail["session"]["state"] == "done"
    assert [event["event_type"] for event in detail["events"]][-2:] == ["running", "done"]
    manager.close()


def test_recovered_async_job_reopens_terminal_trace(tmp_path):
    config = {"server": {"state_dir": str(tmp_path / "state")}, "async_jobs": {"wait_max_seconds": 90}, "debug_traces": {"enabled": True}}
    store = DebugTraceStore(config)
    manager = AsyncJobManager(
        config,
        _Scheduler(),
        _Artifacts(),
        lambda action, payload, tenant: {"success": True, "action": action, "tenant": tenant},
        debug_traces=store,
    )
    try:
        now = time.time()
        trace_id = store.start(kind="async_job", tenant="tenant-a", action="reason", source="async-job")
        store.update(trace_id, request={"task": "recover me", "request_id": "trace-recovery-001"})
        with closing(manager._connect()) as con:
            con.execute(
                "INSERT INTO async_jobs(job_id,tenant,action,request_hash,payload_json,state,created_at,updated_at,expires_at,trace_id) VALUES(?,?,?,?,?,'running',?,?,?,?)",
                ("persisted", "tenant-a", "reason", "persisted-hash", '{"task":"recover me","request_id":"trace-recovery-001"}', now, now, now + 600, trace_id),
            )
            con.commit()
        assert store.recover_incomplete(reason="hub restarted")["recovered_sessions"] == 1
        assert store.detail(trace_id)["terminal"] is True

        assert manager.recover() == 1
        detail = store.detail(trace_id)
        assert detail["session"]["state"] == "queued"
        assert detail["session"]["finished_at"] == 0
        assert detail["session"]["error"] == ""
        assert detail["terminal"] is False
    finally:
        manager.close()


def test_async_jobs_tick_evicts_terminal_events(tmp_path):
    mgr = AsyncJobManager(
        {"server": {"state_dir": str(tmp_path / "state")}},
        _Scheduler(),
        _Artifacts(),
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



def test_close_releases_workers_and_rejects_new_jobs(tmp_path):
    manager, _scheduler = _manager(tmp_path)
    submitted = manager.submit("tenant-a", "reason", {"task": "long-running"})
    assert submitted["success"] is True
    assert manager._dispatchers or manager._workers

    manager.close()

    assert not any(thread.is_alive() for thread in manager._workers)
    rejected = manager.submit("tenant-a", "reason", {"task": "too-late"})
    assert rejected == {
        "success": False,
        "error": "async job manager is closed",
        "terminal": True,
        "retryable": False,
    }


def test_terminal_status_and_result_flags_are_consistent(tmp_path):
    manager, _scheduler = _manager(tmp_path)
    try:
        submitted = manager.submit("tenant-a", "reason", {"task": "terminal flags"})
        assert manager.wait("tenant-a", submitted["job_id"], 3)["state"] == "done"

        status = manager.status("tenant-a", submitted["job_id"])
        result = manager.result("tenant-a", submitted["job_id"])

        assert status["terminal"] is True
        assert status["in_progress"] is False
        assert status["retryable"] is False
        assert result["terminal"] is True
        assert result["retryable"] is False
    finally:
        manager.close()


def test_cancelling_queued_job_is_idempotent(tmp_path):
    manager, _scheduler = _manager(tmp_path)
    try:
        submitted = manager.submit("tenant-a", "reason", {"task": "cancel twice"}, dispatch_delay_seconds=30)

        first = manager.cancel("tenant-a", submitted["job_id"])
        second = manager.cancel("tenant-a", submitted["job_id"])

        assert first["success"] is True
        assert second["success"] is True
        assert first["state"] == second["state"] == "cancelled"
        assert first["terminal"] is second["terminal"] is True
        assert manager.status("tenant-a", submitted["job_id"])["state"] == "cancelled"
    finally:
        manager.close()


def test_expired_result_matches_expired_status(tmp_path):
    manager, _scheduler = _manager(tmp_path)
    try:
        submitted = manager.submit("tenant-a", "reason", {"task": "expiry parity"})
        assert manager.wait("tenant-a", submitted["job_id"], 3)["state"] == "done"
        with closing(manager._connect()) as con:
            con.execute("UPDATE async_jobs SET expires_at=? WHERE job_id=?", (time.time() - 1, submitted["job_id"]))
            con.commit()

        status = manager.status("tenant-a", submitted["job_id"])
        result = manager.result("tenant-a", submitted["job_id"])

        assert status["state"] == result["state"] == "expired"
        assert status["terminal"] is result["terminal"] is True
        assert status["retryable"] is result["retryable"] is False
    finally:
        manager.close()


def test_expired_running_job_with_cancel_request_reconciles_as_cancelled(tmp_path):
    manager, _scheduler = _manager(tmp_path)
    now = time.time()
    with closing(manager._connect()) as con:
        con.execute(
            "INSERT INTO async_jobs(job_id,tenant,action,request_hash,payload_json,state,lease_until,attempts,cancel_requested,created_at,updated_at,expires_at) VALUES(?,?,?,?,?,'running',?,?,?,?,?,?)",
            ("cancelled-on-restart", "tenant-a", "reason", "restart-hash", '{"task":"do not rerun"}', now - 1, 1, 1, now, now, now + 600),
        )
        con.commit()
    manager.close()

    reopened, scheduler = _manager(tmp_path)
    try:
        assert reopened.recover() == 0
        status = reopened.status("tenant-a", "cancelled-on-restart")

        assert status["state"] == "cancelled"
        assert status["terminal"] is True
        assert status["retryable"] is False
        assert scheduler.calls == []
        assert reopened.recover() == 0
    finally:
        reopened.close()


def test_recovery_wakes_real_waiter_blocked_on_cancellation(tmp_path):
    class ObservedEvent(threading.Event):
        def __init__(self):
            super().__init__()
            self.entered_wait = threading.Event()

        def wait(self, timeout=None):
            self.entered_wait.set()
            return super().wait(timeout)

    manager, _scheduler = _manager(tmp_path)
    try:
        now = time.time()
        job_id = "cancelled-while-waiting"
        with closing(manager._connect()) as con:
            con.execute(
                "INSERT INTO async_jobs(job_id,tenant,action,request_hash,payload_json,state,lease_until,attempts,cancel_requested,created_at,updated_at,expires_at) VALUES(?,?,?,?,?,'running',?,?,?,?,?,?)",
                (job_id, "tenant-a", "reason", "waiting-hash", '{"task":"wait for recovery"}', now - 1, 1, 1, now, now, now + 600),
            )
            con.commit()

        event = ObservedEvent()
        manager._events[job_id] = event
        waited = []
        waiter = threading.Thread(target=lambda: waited.append(manager.wait("tenant-a", job_id, 30)), daemon=True)
        waiter.start()

        assert event.entered_wait.wait(1)
        assert waiter.is_alive()
        assert manager.recover() == 0
        waiter.join(1)

        assert not waiter.is_alive()
        assert waited[0]["state"] == "cancelled"
        assert waited[0]["terminal"] is True
        assert waited[0]["retryable"] is False
    finally:
        manager.close()


def test_tick_keeps_cancelled_job_cancelled_after_execution_lease_expires(tmp_path):
    manager, _scheduler = _manager(tmp_path)
    try:
        now = time.time()
        with closing(manager._connect()) as con:
            con.execute(
                "INSERT INTO async_jobs(job_id,tenant,action,request_hash,payload_json,state,lease_until,attempts,cancel_requested,created_at,updated_at,expires_at) VALUES(?,?,?,?,?,'running',?,?,?,?,?,?)",
                ("cancelled-lease", "tenant-a", "reason", "lease-hash", '{"task":"must stay cancelled"}', now - 1, 1, 1, now, now, now + 600),
            )
            con.commit()

        manager.tick()

        status = manager.status("tenant-a", "cancelled-lease")
        result = manager.result("tenant-a", "cancelled-lease")
        assert status["state"] == result["state"] == "cancelled"
        assert status["terminal"] is result["terminal"] is True
        assert status["retryable"] is result["retryable"] is False
    finally:
        manager.close()


def test_tick_does_not_dispatch_during_delayed_submit_registration_gap(tmp_path, monkeypatch):
    manager, _scheduler = _manager(tmp_path)
    dispatched = []
    original_event = manager._event
    should_tick = True

    def _event_then_tick(job_id):
        nonlocal should_tick
        event = original_event(job_id)
        if should_tick:
            should_tick = False
            manager.tick()
        return event

    monkeypatch.setattr(manager, "_event", _event_then_tick)
    monkeypatch.setattr(manager, "_dispatch", lambda job_id: dispatched.append(job_id))
    try:
        submitted = manager.submit(
            "tenant-a", "reason", {"task": "delayed-dispatch"},
            dispatch_delay_seconds=30,
        )

        assert submitted["success"] is True
        assert dispatched == []
        assert manager.status("tenant-a", submitted["job_id"])["state"] == "queued"
    finally:
        manager.close()


def test_wait_timeout_leaves_job_active_and_reports_timeout_budget(tmp_path):
    manager, _scheduler = _manager(tmp_path)
    try:
        submitted = manager.submit("tenant-a", "reason", {"task": "still queued"}, dispatch_delay_seconds=30)

        waited = manager.wait("tenant-a", submitted["job_id"], 1)

        assert waited["wait_timeout_seconds"] == 1
        assert waited["state"] == "queued"
        assert waited["terminal"] is False
        assert waited["retryable"] is True
        assert manager.status("tenant-a", submitted["job_id"])["state"] == "queued"
    finally:
        manager.close()
