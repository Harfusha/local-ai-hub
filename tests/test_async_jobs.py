from __future__ import annotations

import sqlite3
import pytest
import threading
import time
from contextlib import closing

import local_ai_hub.async_jobs as async_jobs_module
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


def _wait_for_terminal(manager, job_id, expected_state="done"):
    # These tests check persisted results, not a loaded Windows host's throughput.
    # Keep the real dispatch and one bounded wait; timeout semantics are tested below.
    waited = manager.wait("tenant-a", job_id, 10)
    assert waited["state"] == expected_state, waited
    return waited


def test_async_jobs_rejects_non_current_schema_without_deleting_rows(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    db_path = state_dir / "async_jobs.sqlite3"
    with closing(sqlite3.connect(db_path)) as con:
        con.execute("CREATE TABLE async_jobs (job_id TEXT PRIMARY KEY, tenant TEXT NOT NULL)")
        con.execute("INSERT INTO async_jobs(job_id, tenant) VALUES('stale', 'tenant-a')")
        con.commit()

    with pytest.raises(RuntimeError, match="unsupported async_jobs schema"):
        _manager(tmp_path)

    with closing(sqlite3.connect(db_path)) as con:
        columns = [str(row[1]) for row in con.execute("PRAGMA table_info(async_jobs)")]
        rows = con.execute("SELECT job_id, tenant FROM async_jobs").fetchall()
    assert columns == ["job_id", "tenant"]
    assert rows == [("stale", "tenant-a")]

def test_async_jobs_rejects_legacy_schema_without_mutating_rows(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    db_path = state_dir / "async_jobs.sqlite3"
    now = time.time()
    with closing(sqlite3.connect(db_path)) as con:
        con.execute("""CREATE TABLE async_jobs (
            job_id TEXT PRIMARY KEY, tenant TEXT NOT NULL, action TEXT NOT NULL, request_hash TEXT NOT NULL,
            payload_json TEXT NOT NULL, state TEXT NOT NULL, result_json TEXT NOT NULL DEFAULT '',
            artifact_id TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '', lease_until REAL NOT NULL DEFAULT 0,
            attempts INTEGER NOT NULL DEFAULT 0, cancel_requested INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL, updated_at REAL NOT NULL, expires_at REAL NOT NULL,
            trace_id TEXT NOT NULL DEFAULT '', task_id TEXT NOT NULL DEFAULT ''
        )""")
        con.execute("""INSERT INTO async_jobs (job_id, tenant, action, request_hash, payload_json, state, created_at, updated_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("queued-job", "tenant-a", "reason", "request-hash", '{"task":"resume"}', "queued", now, now, now + 600),
        )
        con.commit()

    with pytest.raises(RuntimeError, match="unsupported async_jobs schema"):
        _manager(tmp_path)

    with closing(sqlite3.connect(db_path)) as con:
        columns = [str(row[1]) for row in con.execute("PRAGMA table_info(async_jobs)")]
        row = con.execute("SELECT job_id, state, request_hash FROM async_jobs").fetchone()
    assert columns[-1] == "task_id"
    assert row == ("queued-job", "queued", "request-hash")

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
    try:
        submitted = manager.submit("tenant-a", "reason", {"task": "run outside model slot"})
        result = _wait_for_terminal(manager, submitted["job_id"])
        assert result["state"] == "done"
        assert scheduler.calls == []
    finally:
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
    seen_request_ids = []
    manager.executor = lambda action, payload, tenant: (
        seen_request_ids.append(payload.get("request_id"))
        or {"success": True, "action": action, "tenant": tenant}
    )
    now = time.time()
    with closing(manager._connect()) as con:
        con.execute(
            "INSERT INTO async_jobs(job_id,tenant,action,request_hash,payload_json,state,created_at,updated_at,expires_at) VALUES(?,?,?,?,?,'running',?,?,?)",
            ("persisted", "tenant-a", "reason", "persisted-hash", '{"task":"resume","request_id":"persisted-recovery-1","_async_request_id_supplied":true}', now, now, now + 600),
        )
        con.commit()

    try:
        assert manager.recover() == 1
        _wait_for_terminal(manager, "persisted")
        assert seen_request_ids == ["persisted-recovery-1"]
        assert scheduler.calls == []
    finally:
        manager.close()


def test_recovery_keeps_unkeyed_running_job_outcome_unknown(tmp_path):
    manager, scheduler = _manager(tmp_path)
    dispatched = []
    manager._dispatch = dispatched.append
    now = time.time()
    with closing(manager._connect()) as con:
        con.execute(
            "INSERT INTO async_jobs(job_id,tenant,action,request_hash,payload_json,state,attempts,created_at,updated_at,expires_at) VALUES(?,?,?,?,?,'running',1,?,?,?)",
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
    try:
        submitted = manager.submit("tenant-a", "reason", {"task": "finish"})
        _wait_for_terminal(manager, submitted["job_id"])
        result = manager.result("tenant-a", submitted["job_id"])

        assert result["success"] is True
        assert result["artifact_id"] == "artifact-1"
        assert result["result"]["task"] == "finish"
    finally:
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

        _wait_for_terminal(manager, submitted["job_id"], "failed")
        result = manager.result("tenant-a", submitted["job_id"])

        assert result["success"] is False
        assert result["retryable"] is False
        assert manager.status("tenant-a", submitted["job_id"])["state"] == "failed"
    finally:
        manager.close()


def test_async_job_trace_links_metadata_scheduler_and_terminal_state(tmp_path):
    config = {"server": {"state_dir": str(tmp_path / "state")}, "async_jobs": {"wait_max_seconds": 90}, "debug_traces": {"enabled": True}}
    store = DebugTraceStore(config)
    scheduler = _Scheduler()
    manager = AsyncJobManager(config, scheduler, _Artifacts(), lambda action, payload, tenant: {"success": True, "action": action, "task": payload.get("task"), "tenant": tenant}, debug_traces=store)

    try:
        submitted = manager.submit("tenant-a", "reason", {"task": "trace me", "context": "full context"})
        _wait_for_terminal(manager, submitted["job_id"])
        detail = store.detail(submitted["trace_id"])
        assert detail["session"]["request"]["task"] == "trace me"
        assert detail["session"]["request"]["context"] == "full context"
        assert "task" in detail["session"]["output"]
        assert detail["session"]["async_job_id"] == submitted["job_id"]
        assert detail["session"]["scheduler_job_id"] == ""
        assert detail["session"]["state"] == "done"
        assert [event["event_type"] for event in detail["events"]][-2:] == ["running", "done"]
    finally:
        manager.close()


def test_recovered_async_job_reopens_terminal_trace(tmp_path, monkeypatch):
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
        store.update(trace_id, request={"task": "recover me", "request_id": "trace-recovery-1"})
        with closing(manager._connect()) as con:
            con.execute(
                "INSERT INTO async_jobs(job_id,tenant,action,request_hash,payload_json,state,created_at,updated_at,expires_at,trace_id) VALUES(?,?,?,?,?,'running',?,?,?,?)",
                ("persisted", "tenant-a", "reason", "persisted-hash", '{"task":"recover me","request_id":"trace-recovery-1"}', now, now, now + 600, trace_id),
            )
            con.commit()
        assert store.recover_incomplete(reason="hub restarted")["recovered_sessions"] == 1
        assert store.detail(trace_id)["terminal"] is True

        monkeypatch.setattr(manager, "_dispatch", lambda _job_id: None)
        assert manager.recover() == 1
        detail = store.detail(trace_id)
        assert detail["session"]["state"] == "queued"
        assert detail["session"]["finished_at"] == 0
        assert detail["session"]["error"] == ""
        assert detail["terminal"] is False
    finally:
        manager.close()


def test_recovery_keeps_running_job_without_request_id_outcome_unknown(tmp_path):
    manager, _scheduler = _manager(tmp_path)
    now = time.time()
    with closing(manager._connect()) as con:
        con.execute(
            "INSERT INTO async_jobs(job_id,tenant,action,request_hash,payload_json,state,attempts,created_at,updated_at,expires_at) VALUES(?,?,?,?,?,'running',1,?,?,?)",
            ("unsafe-replay", "tenant-a", "reason", "unsafe-hash", '{"task":"resume"}', now, now, now + 600),
        )
        con.commit()

    try:
        assert manager.recover() == 0
        status = manager.status("tenant-a", "unsafe-replay")
        assert status["state"] == "outcome_unknown"
        assert status["outcome_unknown"] is True
        assert status["retryable"] is False
    finally:
        manager.close()


def test_legacy_retryable_job_without_request_id_is_not_requeued(tmp_path):
    manager, _scheduler = _manager(tmp_path)
    manager.executor = lambda _action, _payload, _tenant: {
        "success": False,
        "retryable": True,
        "error": "transient failure without replay key",
    }
    now = time.time()
    with closing(manager._connect()) as con:
        con.execute(
            "INSERT INTO async_jobs(job_id,tenant,action,request_hash,payload_json,state,created_at,updated_at,expires_at) VALUES(?,?,?,?,?,'queued',?,?,?)",
            ("legacy-no-replay-key", "tenant-a", "reason", "legacy-hash", '{"task":"resume"}', now, now, now + 600),
        )
        con.commit()

    try:
        result = manager._execute("legacy-no-replay-key")
        status = manager.status("tenant-a", "legacy-no-replay-key")
        assert result["outcome_unknown"] is True
        assert status["state"] == "outcome_unknown"
        assert status["retryable"] is False
    finally:
        manager.close()


def test_submit_persists_request_id_without_breaking_active_deduplication(tmp_path):
    manager, _scheduler = _manager(tmp_path)
    try:
        first = manager.submit("tenant-a", "reason", {"task": "same"}, dispatch_delay_seconds=30.0)
        second = manager.submit("tenant-a", "reason", {"task": "same"}, dispatch_delay_seconds=30.0)

        assert second["job_id"] == first["job_id"]
        assert second["coalesced"] is True
        row = manager._row("tenant-a", first["job_id"])
        assert row is not None
        request_id = manager._request_id(row["payload_json"])
        assert request_id
    finally:
        manager.close()


def test_async_jobs_tick_evicts_terminal_events(tmp_path):
    mgr = AsyncJobManager(
        {"server": {"state_dir": str(tmp_path / "state")}},
        _Scheduler(),
        _Artifacts(),
        lambda _action, _payload, _tenant: {"success": True},
    )
    res = mgr.submit("tenant-1", "reason", {"task": "hello"}, dispatch_delay_seconds=30)
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
        _wait_for_terminal(manager, submitted["job_id"])

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


def test_tick_does_not_dispatch_before_delayed_submit_is_registered(tmp_path):
    manager, _scheduler = _manager(tmp_path)
    trace_started = threading.Event()
    release_trace = threading.Event()
    dispatched = []

    class _BlockingTrace:
        def start(self, **_kwargs):
            trace_started.set()
            assert release_trace.wait(2)
            return "trace-1"

        def update(self, *_args, **_kwargs):
            pass

        def link(self, *_args, **_kwargs):
            pass

    manager.debug_traces = _BlockingTrace()
    manager._dispatch = lambda job_id: dispatched.append(job_id)
    submitted = {}
    thread = threading.Thread(
        target=lambda: submitted.update(manager.submit(
            "tenant-a", "reason", {"task": "delayed dispatch race"}, dispatch_delay_seconds=30,
        )),
    )

    try:
        thread.start()
        assert trace_started.wait(2)
        manager.tick()
        assert dispatched == []
    finally:
        release_trace.set()
        thread.join(2)
        manager.close()

    assert not thread.is_alive()
    assert submitted.get("success") is True


def test_early_delayed_dispatch_callback_preserves_queued_cancellation(tmp_path, monkeypatch):
    manager, _scheduler = _manager(tmp_path)
    timer_instances = []
    executions = []
    manager.executor = lambda action, payload, tenant: executions.append((action, tenant)) or {"success": True}
    real_threading = async_jobs_module.threading

    class ManualTimer:
        def __init__(self, _interval, function, args=(), kwargs=None):
            self.function = function
            self.args = args
            self.kwargs = kwargs or {}
            self.daemon = False
            self.cancelled = False

        def start(self):
            timer_instances.append(self)

        def cancel(self):
            self.cancelled = True

        def fire(self):
            self.function(*self.args, **self.kwargs)

    class InlineThread:
        def __init__(self, target, name=None, daemon=None):
            self.target = target
            self.name = name
            self.daemon = daemon
            self._alive = False

        def start(self):
            self._alive = True
            try:
                self.target()
            finally:
                self._alive = False

        def is_alive(self):
            return self._alive

        def join(self, timeout=None):
            return None

    class ThreadingProxy:
        Timer = ManualTimer
        Thread = InlineThread

        def __getattr__(self, name):
            return getattr(real_threading, name)

    monkeypatch.setattr(async_jobs_module, "threading", ThreadingProxy())
    try:
        submitted = manager.submit(
            "tenant-a", "reason", {"task": "early dispatch callback"}, dispatch_delay_seconds=30
        )
        job_id = submitted["job_id"]

        timer_instances[0].fire()

        assert executions == []
        assert manager.status("tenant-a", job_id)["state"] == "queued"
        assert len(timer_instances) == 2
        assert manager._delayed_dispatch[job_id] is timer_instances[1]

        cancelled = manager.cancel("tenant-a", job_id)
        assert cancelled["state"] == "cancelled"
        timer_instances[1].fire()
        assert executions == []
        assert manager.status("tenant-a", job_id)["state"] == "cancelled"
    finally:
        manager.close()


def test_expired_result_matches_expired_status(tmp_path):
    manager, _scheduler = _manager(tmp_path)
    try:
        submitted = manager.submit("tenant-a", "reason", {"task": "expiry parity"})
        _wait_for_terminal(manager, submitted["job_id"])
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


def test_tick_cannot_claim_delayed_submit_before_timer_registration(tmp_path, monkeypatch):
    manager, scheduler = _manager(tmp_path)
    tick_injected = False
    dispatch_attempts = []
    original_event = manager._event

    def event_with_tick(job_id):
        nonlocal tick_injected
        if not tick_injected:
            tick_injected = True
            manager.tick()
        return original_event(job_id)

    monkeypatch.setattr(manager, "_event", event_with_tick)
    monkeypatch.setattr(manager, "_dispatch", dispatch_attempts.append)
    try:
        submitted = manager.submit(
            "tenant-a", "reason", {"task": "delayed dispatch race"},
            dispatch_delay_seconds=30,
        )
        assert submitted["job_id"] in manager._delayed_dispatch
        cancelled = manager.cancel("tenant-a", submitted["job_id"])
        assert cancelled["state"] == "cancelled"
        assert dispatch_attempts == []
        assert scheduler.calls == []
        assert submitted.get("error") is None
    finally:
        manager.close()
