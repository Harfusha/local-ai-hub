from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import closing
from types import SimpleNamespace

import pytest
import local_ai_hub.async_jobs as async_jobs
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


def _mode_gate_error(snapshot):
    if snapshot.mode == "active" and not snapshot.degraded:
        return None
    return {
        "success": False,
        "error": f"Hub operational mode is {snapshot.mode}; agent tool calls are disabled",
        "error_code": "operational_mode_blocked",
        "operational_mode": snapshot.mode,
        "mode_revision": snapshot.revision,
        "degraded": snapshot.degraded,
        "terminal": True,
        "retryable": False,
    }


@pytest.fixture(autouse=True)
def _active_operational_mode(monkeypatch):
    snapshot = SimpleNamespace(
        mode="active", revision=0, updated_at=time.time(), degraded=False, error=""
    )
    monkeypatch.setattr(
        async_jobs,
        "load_operational_mode",
        lambda _state_dir: snapshot,
        raising=False,
    )
    monkeypatch.setattr(
        async_jobs, "operational_mode_gate_error", _mode_gate_error, raising=False
    )
    return snapshot


def _manager(tmp_path):
    scheduler = _Scheduler()
    manager = AsyncJobManager(
        {"server": {"state_dir": str(tmp_path / "state")}, "async_jobs": {"wait_max_seconds": 90}},
        scheduler,
        _Artifacts(),
        lambda action, payload, tenant: {"success": True, "action": action, "task": payload.get("task"), "tenant": tenant},
    )
    return manager, scheduler


def test_async_job_submit_rejects_conversation_payload_before_dispatch(tmp_path):
    manager, scheduler = _manager(tmp_path)
    try:
        result = manager.submit(
            "tenant-a", "delegate", {"task": "question", "conversation": True}
        )

        assert result["success"] is False
        assert result["error"] == "conversations require delivery=sync"
        assert result["terminal"] is True
        assert result["retryable"] is False
        assert scheduler.calls == []
    finally:
        manager.close()


def _simulate_process_crash(manager):
    with manager._lock:
        timers = list(manager._delayed_dispatch.values())
        manager._delayed_dispatch.clear()
        manager._shutdown.set()
    for timer in timers:
        timer.cancel()



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


def test_request_id_reuses_job_identity_and_conflicts_on_payload_change(tmp_path):
    manager, _scheduler = _manager(tmp_path)
    try:
        first = manager.submit(
            "tenant-a", "reason", {"task": "same", "request_id": "request-1"}, dispatch_delay_seconds=30
        )
        replay = manager.submit("tenant-a", "reason", {"task": "same", "request_id": "request-1"})
        conflict = manager.submit("tenant-a", "reason", {"task": "changed", "request_id": "request-1"})

        assert replay["job_id"] == first["job_id"]
        assert replay["idempotent_replay"] is True
        assert replay["coalesced"] is True
        assert conflict["job_id"] == first["job_id"]
        assert conflict["state"] == "conflict"
        assert conflict["conflict"] is True
    finally:
        _simulate_process_crash(manager)

    reopened, _scheduler = _manager(tmp_path)
    try:
        after_restart = reopened.submit(
            "tenant-a", "reason", {"task": "same", "request_id": "request-1"}
        )

        assert after_restart["job_id"] == first["job_id"]
        assert after_restart["idempotent_replay"] is True
        assert after_restart["state"] == "queued"
        assert reopened.cancel("tenant-a", first["job_id"])["state"] == "cancelled"
    finally:
        reopened.close()


def test_request_id_is_normalized_before_persistence_and_replay(tmp_path):
    manager, _scheduler = _manager(tmp_path)
    try:
        payload = {"task": "same", "request_id": " request-padded "}
        first = manager.submit("tenant-a", "reason", payload, dispatch_delay_seconds=30)
        manager.cancel("tenant-a", first["job_id"])

        replay = manager.submit("tenant-a", "reason", payload)
        normalized_replay = manager.submit(
            "tenant-a", "reason", {"task": "same", "request_id": "request-padded"}
        )

        assert replay["job_id"] == first["job_id"]
        assert replay["idempotent_replay"] is True
        assert normalized_replay["job_id"] == first["job_id"]
        assert normalized_replay["idempotent_replay"] is True
    finally:
        _simulate_process_crash(manager)


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


def test_recovery_replays_persisted_running_job_with_one_executor_invocation(tmp_path):
    executions = []
    payload = {"tasks": [{"task": "resume"}], "request_id": "request-recovery"}

    def execute(action, job_payload, tenant):
        executions.append((action, tenant, job_payload))
        return {"success": True, "action": action, "tasks": job_payload.get("tasks"), "tenant": tenant}

    def create_manager():
        return AsyncJobManager(
            {"server": {"state_dir": str(tmp_path / "state")}, "async_jobs": {"wait_max_seconds": 90}},
            _Scheduler(),
            _Artifacts(),
            execute,
        )

    manager = create_manager()
    try:
        # Delayed dispatch keeps the executor from starting before the simulated crash.
        # This proves one invocation in this controlled recovery/replay case, not exactly-once
        # external effects after a crash during execution.
        submitted = manager.submit("tenant-a", "batch", payload, dispatch_delay_seconds=30)
        job_id = submitted["job_id"]
        with closing(manager._connect()) as con:
            con.execute(
                "UPDATE async_jobs SET state='running',attempts=1,lease_until=0 WHERE job_id=?",
                (job_id,),
            )
            con.commit()
        _simulate_process_crash(manager)
    finally:
        manager.close()

    reopened = create_manager()
    try:
        assert reopened.recover() == 1
        replay = reopened.submit("tenant-a", "batch", payload)
        waited = reopened.wait("tenant-a", job_id, 3)
        status = reopened.status("tenant-a", job_id)
        result = reopened.result("tenant-a", job_id)

        assert replay["job_id"] == job_id
        assert replay["idempotent_replay"] is True
        assert waited["job_id"] == job_id
        assert status["job_id"] == job_id
        assert result["job_id"] == job_id
        assert waited["state"] == status["state"] == result["state"] == "done"
        assert result["success"] is True
        assert result["result"]["tasks"] == payload["tasks"]
        assert len(executions) == 1
        assert executions[0][0:2] == ("batch", "tenant-a")
        assert reopened.recover() == 0
    finally:
        reopened.close()


def test_recovery_marks_running_job_unknown_without_t07_request_id(tmp_path):
    manager, _scheduler = _manager(tmp_path)
    now = time.time()
    with closing(manager._connect()) as con:
        con.execute(
            "INSERT INTO async_jobs(job_id,tenant,action,request_hash,payload_json,state,attempts,created_at,updated_at,expires_at) VALUES(?,?,?,?,?,'running',?,?,?,?)",
            ("mutation-unknown", "tenant-a", "batch", "mutation-hash", '{"tasks":[{"task":"write"}]}', 1, now, now, now + 600),
        )
        con.commit()
    _simulate_process_crash(manager)

    reopened, scheduler = _manager(tmp_path)
    try:
        assert reopened.recover() == 0
        status = reopened.status("tenant-a", "mutation-unknown")
        result = reopened.result("tenant-a", "mutation-unknown")

        assert status["state"] == result["state"] == "outcome_unknown"
        assert status["outcome_unknown"] is True
        assert status["terminal"] is result["terminal"] is True
        assert status["retryable"] is result["retryable"] is False
        assert scheduler.calls == []
    finally:
        reopened.close()


def test_submitted_job_survives_disconnect_restart_recovery_and_result_read(tmp_path):
    manager, _scheduler = _manager(tmp_path)
    executions = []
    manager.executor = lambda action, payload, tenant: (
        executions.append((action, payload, tenant))
        or {"success": True, "action": action, "task": payload.get("task"), "tenant": tenant}
    )
    payload = {"task": "resume after client disconnect", "request_id": "request-disconnect"}
    submitted = manager.submit(
        "tenant-a",
        "reason",
        payload,
        dispatch_delay_seconds=30,
    )
    job_id = submitted["job_id"]
    db_path = tmp_path / "state" / "async_jobs.sqlite3"
    with closing(sqlite3.connect(db_path)) as con:
        queued = con.execute(
            "SELECT request_hash, json_extract(payload_json, '$.request_id'), payload_json, state, attempts "
            "FROM async_jobs WHERE job_id=?",
            (job_id,),
        ).fetchone()
    assert queued is not None
    request_hash, request_id, payload_json = queued[:3]
    assert request_hash
    assert request_id == payload["request_id"]
    assert queued[3:] == ("queued", 0)

    with closing(sqlite3.connect(db_path)) as con:
        con.execute(
            "UPDATE async_jobs SET state='running', attempts=1, lease_until=?, updated_at=? WHERE job_id=?",
            (time.time() + 60, time.time(), job_id),
        )
        con.commit()
        crashed = con.execute(
            "SELECT request_hash, json_extract(payload_json, '$.request_id'), payload_json, state, attempts "
            "FROM async_jobs WHERE job_id=?",
            (job_id,),
        ).fetchone()
    assert crashed == (request_hash, request_id, payload_json, "running", 1)
    _simulate_process_crash(manager)

    restarted, _scheduler = _manager(tmp_path)
    restarted.executor = manager.executor
    try:
        assert restarted.recover() == 1
        waited = restarted.wait("tenant-a", job_id, 3)
        status = restarted.status("tenant-a", job_id)

        result = restarted.result("tenant-a", job_id)
        replay = restarted.submit(
            "tenant-a",
            "reason",
            payload,
        )

        assert result["success"] is True
        assert result["result"]["task"] == "resume after client disconnect"
        assert waited["state"] == status["state"] == result["state"] == replay["state"] == "done"
        assert waited["job_id"] == status["job_id"] == result["job_id"] == replay["job_id"] == job_id
        assert len(executions) == 1
        assert replay["job_id"] == job_id
        assert replay["idempotent_replay"] is True
    finally:
        restarted.close()


def test_completed_job_returns_artifact_backed_result(tmp_path):
    manager, _scheduler = _manager(tmp_path)
    submitted = manager.submit("tenant-a", "reason", {"task": "finish"})
    waited = manager.wait("tenant-a", submitted["job_id"], 3)
    assert waited["state"] == "done"
    status = manager.status("tenant-a", submitted["job_id"])
    result = manager.result("tenant-a", submitted["job_id"])

    assert result["success"] is True
    assert result["artifact_id"] == "artifact-1"
    assert status["artifact_id"] == waited["artifact_id"] == result["artifact_id"]
    assert status["expires_at"] == waited["expires_at"] == result["expires_at"] == submitted["expires_at"]
    assert result["result"]["task"] == "finish"
    manager.close()


def test_timed_out_wait_returns_active_state_without_cancelling(tmp_path):
    executing = threading.Event()
    release = threading.Event()

    def execute(action, payload, tenant):
        executing.set()
        release.wait(2)
        return {"success": True, "state": "done"}

    manager = AsyncJobManager(
        {"server": {"state_dir": str(tmp_path / "state")}, "async_jobs": {"wait_max_seconds": 90}},
        _Scheduler(),
        _Artifacts(),
        execute,
    )
    try:
        submitted = manager.submit("tenant-a", "reason", {"task": "slow"})
        assert executing.wait(5)

        waited = manager.wait("tenant-a", submitted["job_id"], 0)

        assert waited["state"] == "running"
        assert waited["wait_timeout_seconds"] == 0
        assert waited["cancel_requested"] is False
    finally:
        release.set()
        manager.close()


def test_manager_requires_artifact_ttl_to_cover_job_ttl(tmp_path):
    class ShortRetentionArtifacts(_Artifacts):
        ttl_seconds = 60

    class MatchingRetentionArtifacts(_Artifacts):
        ttl_seconds = 120

    manager = None
    try:
        manager = AsyncJobManager(
            {
                "server": {"state_dir": str(tmp_path / "state")},
                "async_jobs": {"wait_max_seconds": 90, "result_ttl_seconds": 120},
            },
            _Scheduler(),
            ShortRetentionArtifacts(),
            lambda _action, _payload, _tenant: {"success": True},
        )
    except ValueError as exc:
        assert "result_ttl_seconds" in str(exc)
        assert "artifact" in str(exc)
    else:
        if manager is not None:
            manager.close()
        raise AssertionError("manager accepted artifact retention shorter than job retention")

    matching = AsyncJobManager(
        {
            "server": {"state_dir": str(tmp_path / "matching-state")},
            "async_jobs": {"wait_max_seconds": 90, "result_ttl_seconds": 120},
        },
        _Scheduler(),
        MatchingRetentionArtifacts(),
        lambda _action, _payload, _tenant: {"success": True},
    )
    try:
        assert matching.result_ttl_seconds == MatchingRetentionArtifacts.ttl_seconds
    finally:
        matching.close()


def test_result_remains_available_until_configured_retention_expires(tmp_path):
    manager = AsyncJobManager(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "async_jobs": {"wait_max_seconds": 90, "result_ttl_seconds": 120},
        },
        _Scheduler(),
        _Artifacts(),
        lambda _action, _payload, _tenant: {"success": True},
    )
    try:
        submitted = manager.submit(
            "tenant-a", "reason", {"task": "retained result"}, dispatch_delay_seconds=30
        )
        with closing(manager._connect()) as con:
            row = con.execute(
                "SELECT created_at,expires_at FROM async_jobs WHERE job_id=?", (submitted["job_id"],)
            ).fetchone()
            con.execute(
                "UPDATE async_jobs SET state='done',result_json=?,artifact_id=? WHERE job_id=?",
                ('{"success":true,"value":"retained"}', "artifact-1", submitted["job_id"]),
            )
            con.commit()

        assert abs((float(row[1]) - float(row[0])) - 120.0) < 1.0
        manager.tick()
        result = manager.result("tenant-a", submitted["job_id"])

        assert result["success"] is True
        assert result["result"]["value"] == "retained"
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
        store.update(trace_id, request={"task": "recover me"})
        manager._dispatch = lambda _job_id: None
        with closing(manager._connect()) as con:
            con.execute(
                "INSERT INTO async_jobs(job_id,tenant,action,request_hash,payload_json,state,attempts,created_at,updated_at,expires_at,trace_id) VALUES(?,?,?,?,?,'running',1,?,?,?,?)",
                ("persisted", "tenant-a", "reason", "persisted-hash", '{"task":"recover me","request_id":"safe-replay-1"}', now, now, now + 600, trace_id),
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


def test_foreign_tenant_cannot_cancel_delayed_dispatch(tmp_path):
    manager, scheduler = _manager(tmp_path)
    try:
        submitted = manager.submit("tenant-a", "reason", {"task": "private"}, dispatch_delay_seconds=30)
        job_id = submitted["job_id"]

        denied = manager.cancel("tenant-b", job_id)

        assert denied["success"] is False
        assert denied["error"] == "async job not found"
        assert job_id in manager._delayed_dispatch
        assert scheduler.calls == []
        assert manager.status("tenant-a", job_id)["state"] == "queued"
        assert manager.cancel("tenant-a", job_id)["state"] == "cancelled"
    finally:
        manager.close()


def test_running_cancel_ack_does_not_wake_waiter_before_terminal_state(tmp_path):
    release = threading.Event()
    executing = threading.Event()
    wait_entered = threading.Event()

    class ObservedEvent(threading.Event):
        def wait(self, timeout=None):
            wait_entered.set()
            return super().wait(timeout)

    event = ObservedEvent()

    def execute(_action, _payload, _tenant):
        executing.set()
        release.wait(3)
        return {"success": True, "text": "finished after cancellation request"}

    manager = AsyncJobManager(
        {"server": {"state_dir": str(tmp_path / "state")}, "async_jobs": {"wait_max_seconds": 90}},
        _Scheduler(),
        _Artifacts(),
        execute,
    )
    manager._event = lambda _job_id: event
    waited = []
    try:
        submitted = manager.submit("tenant-a", "reason", {"task": "cancel running"})
        assert executing.wait(1)

        acknowledgement = manager.cancel("tenant-a", submitted["job_id"])
        assert acknowledgement["success"] is True
        assert acknowledgement["state"] == "running"
        assert acknowledgement["cancel_requested"] is True
        assert acknowledgement["terminal"] is False
        assert acknowledgement["retryable"] is True
        assert acknowledgement["expires_at"] == submitted["expires_at"]
        assert acknowledgement["artifact_id"] == ""

        waiter = threading.Thread(
            target=lambda: waited.append(manager.wait("tenant-a", submitted["job_id"], 3)),
            daemon=True,
        )
        waiter.start()
        assert wait_entered.wait(1)
        assert waiter.is_alive()

        release.set()
        waiter.join(2)
        assert not waiter.is_alive()
        assert waited[0]["state"] == "cancelled"
        assert waited[0]["terminal"] is True
    finally:
        release.set()
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
        cancel = manager.cancel("tenant-a", submitted["job_id"])

        assert status["state"] == result["state"] == "expired"
        assert status["terminal"] is result["terminal"] is True
        assert status["retryable"] is result["retryable"] is False
        assert status["expires_at"] == result["expires_at"]
        assert cancel["state"] == "expired"
        assert cancel["expires_at"] == status["expires_at"]
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


def test_wait_preserves_zero_timeout_budget_instead_of_using_default(tmp_path, monkeypatch):
    manager, _scheduler = _manager(tmp_path)
    wait_timeouts = []

    class _ImmediateEvent:
        def wait(self, timeout):
            wait_timeouts.append(timeout)
            return False

    monkeypatch.setattr(manager, "status", lambda _tenant, _job_id: {"success": True, "state": "running"})
    monkeypatch.setattr(manager, "_event", lambda _job_id: _ImmediateEvent())
    try:
        result = manager.wait("tenant-a", "job-running", 0)

        assert wait_timeouts == [0]
        assert result["wait_timeout_seconds"] == 0
    finally:
        manager.close()


def _patch_operational_mode(monkeypatch, mode="active", revision=0, *, degraded=False, error=""):
    snapshot = SimpleNamespace(
        mode=mode,
        revision=revision,
        updated_at=time.time(),
        degraded=degraded,
        error=error,
    )
    monkeypatch.setattr(
        async_jobs,
        "load_operational_mode",
        lambda _state_dir: snapshot,
        raising=False,
    )
    return snapshot


class _Receipts:
    def __init__(self):
        self.items = []

    def record(self, receipt):
        self.items.append(receipt)


def test_gaming_rejects_new_inference_before_persistence_and_preserves_result_receipt(tmp_path, monkeypatch):
    mode = _patch_operational_mode(monkeypatch)
    scheduler = _Scheduler()
    artifacts = _Artifacts()
    receipts = _Receipts()
    manager = AsyncJobManager(
        {"server": {"state_dir": str(tmp_path / "state")}, "async_jobs": {"wait_max_seconds": 90}},
        scheduler,
        artifacts,
        lambda action, payload, tenant: {"success": True, "action": action, "task": payload.get("task"), "tenant": tenant},
        verification_store=receipts,
    )
    try:
        existing = manager.submit(
            "tenant-a", "reason", {"task": "finished before gaming", "task_id": "task-existing", "request_id": "existing"}
        )
        assert manager.wait("tenant-a", existing["job_id"], 2)["state"] == "done"
        stored_result = manager.result("tenant-a", existing["job_id"])
        assert stored_result["success"] is True
        assert len(receipts.items) == 1

        mode.mode = "gaming"
        mode.revision = 1
        blocked = manager.submit("tenant-a", "reason", {"task": "new inference", "request_id": "new"})

        assert blocked["success"] is False
        assert blocked["state"] == "rejected"
        assert blocked["code"] == "operational_mode_blocked"
        assert blocked["status_code"] == 423
        assert blocked["terminal"] is True
        assert blocked["retryable"] is False
        with closing(manager._connect()) as con:
            assert con.execute("SELECT COUNT(*) FROM async_jobs").fetchone()[0] == 1
        assert manager.result("tenant-a", existing["job_id"]) == stored_result
        assert len(receipts.items) == 1
    finally:
        manager.close()


def test_maintenance_blocks_speculative_lint_before_persistence(tmp_path, monkeypatch):
    _patch_operational_mode(monkeypatch, "maintenance", 3, degraded=True, error="state file corrupt")
    manager, _scheduler = _manager(tmp_path)
    try:
        blocked = manager.submit("tenant-a", "speculative_lint", {"path": "src/example.py"})

        assert blocked["success"] is False
        assert blocked["code"] == "operational_mode_blocked"
        assert blocked["status_code"] == 423
        assert blocked["terminal"] is True
        assert blocked["retryable"] is False
        with closing(manager._connect()) as con:
            assert con.execute("SELECT COUNT(*) FROM async_jobs").fetchone()[0] == 0
    finally:
        manager.close()


def test_gaming_allows_non_inference_lint_job(tmp_path, monkeypatch):
    _patch_operational_mode(monkeypatch, "gaming", 4)
    manager, _scheduler = _manager(tmp_path)
    try:
        submitted = manager.submit("tenant-a", "speculative_lint", {"path": "src/example.py"})

        assert submitted["success"] is True
        assert manager.wait("tenant-a", submitted["job_id"], 2)["state"] == "done"
    finally:
        manager.close()


@pytest.mark.parametrize(
    ("mode_name", "action"),
    (("gaming", "reason"), ("maintenance", "speculative_lint")),
)
def test_submit_before_restricted_mode_is_cancelled_at_dispatch(tmp_path, monkeypatch, mode_name, action):
    mode = _patch_operational_mode(monkeypatch)
    calls = []
    manager = AsyncJobManager(
        {"server": {"state_dir": str(tmp_path / "state")}, "async_jobs": {"wait_max_seconds": 90}},
        _Scheduler(),
        _Artifacts(),
        lambda action, payload, tenant: calls.append((action, payload, tenant)) or {"success": True},
    )
    try:
        submitted = manager.submit(
            "tenant-a", action, {"task": "pause race"}, dispatch_delay_seconds=30
        )
        assert submitted["success"] is True

        mode.mode = mode_name
        mode.revision = 1
        manager._dispatch(submitted["job_id"])

        status = manager.status("tenant-a", submitted["job_id"])
        assert status["state"] == "cancelled"
        assert status["terminal"] is True
        assert status["retryable"] is False
        assert calls == []
    finally:
        manager.close()


@pytest.mark.parametrize(
    ("mode_name", "action"),
    (("gaming", "reason"), ("maintenance", "speculative_lint")),
)
def test_restricted_mode_requests_running_job_cancellation_without_early_completion(
    tmp_path, monkeypatch, mode_name, action
):
    mode = _patch_operational_mode(monkeypatch)
    started = threading.Event()
    release = threading.Event()

    def execute(_action, _payload, _tenant):
        started.set()
        release.wait(2)
        return {"success": True, "text": "finished after cancellation request"}

    manager = AsyncJobManager(
        {"server": {"state_dir": str(tmp_path / "state")}, "async_jobs": {"wait_max_seconds": 90}},
        _Scheduler(),
        _Artifacts(),
        execute,
    )
    try:
        running = manager.submit("tenant-a", action, {"task": "active job"})
        assert started.wait(1)

        mode.mode = mode_name
        mode.revision = 1
        pending = manager.status("tenant-a", running["job_id"])
        assert pending["state"] == "running"
        assert pending["cancel_requested"] is True
        assert manager.wait("tenant-a", running["job_id"], 0.01)["state"] == "running"

        release.set()
        finished = manager.wait("tenant-a", running["job_id"], 1)
        assert finished["state"] == "cancelled"
        assert finished["terminal"] is True
        assert finished["retryable"] is False
    finally:
        release.set()
        manager.close()


@pytest.mark.parametrize(
    ("mode_name", "action"),
    (("gaming", "reason"), ("maintenance", "speculative_lint")),
)
def test_mode_change_hook_requests_running_job_cancel_before_status_or_result(
    tmp_path, monkeypatch, mode_name, action
):
    mode = _patch_operational_mode(monkeypatch)
    started = threading.Event()
    release = threading.Event()

    def execute(_action, _payload, _tenant):
        started.set()
        release.wait(2)
        return {"success": True, "text": "finished after mode change"}

    manager = AsyncJobManager(
        {"server": {"state_dir": str(tmp_path / "state")}, "async_jobs": {"wait_max_seconds": 90}},
        _Scheduler(),
        _Artifacts(),
        execute,
    )
    try:
        running = manager.submit("tenant-a", action, {"task": "active job"})
        assert started.wait(1)

        mode.mode = mode_name
        mode.revision = 2
        manager.on_operational_mode_changed(mode)

        with closing(manager._connect()) as con:
            row = con.execute(
                "SELECT state,cancel_requested FROM async_jobs WHERE job_id=?",
                (running["job_id"],),
            ).fetchone()
        assert row == ("running", 1)

        release.set()
        finished = manager.wait("tenant-a", running["job_id"], 1)
        assert finished["state"] == "cancelled"
    finally:
        release.set()
        manager.close()


@pytest.mark.parametrize(
    ("mode_name", "action"),
    (("gaming", "reason"), ("maintenance", "speculative_lint")),
)
def test_mode_commit_at_executor_boundary_prevents_inference_start(
    tmp_path, monkeypatch, mode_name, action
):
    mode = _patch_operational_mode(monkeypatch)
    executor_calls = []
    boundary_entered = threading.Event()
    release_boundary = threading.Event()

    def execute(actual_action, _payload, _tenant):
        executor_calls.append(actual_action)
        return {"success": True, "text": "should not start"}

    manager = AsyncJobManager(
        {"server": {"state_dir": str(tmp_path / "state")}, "async_jobs": {"wait_max_seconds": 90}},
        _Scheduler(),
        _Artifacts(),
        execute,
    )
    original_start = getattr(manager, "_invoke_executor_if_allowed", None)

    def pause_at_boundary(job_id, actual_action, payload, tenant):
        boundary_entered.set()
        assert release_boundary.wait(2)
        return original_start(job_id, actual_action, payload, tenant)

    monkeypatch.setattr(manager, "_invoke_executor_if_allowed", pause_at_boundary, raising=False)
    try:
        submitted = manager.submit(
            "tenant-a", action, {"task": "mode start race"}, dispatch_delay_seconds=30
        )
        dispatch = threading.Thread(target=manager._dispatch, args=(submitted["job_id"],))
        dispatch.start()
        assert boundary_entered.wait(1)

        with manager.operational_mode_change_guard():
            mode.mode = mode_name
            mode.revision = 3
            manager.on_operational_mode_changed(mode)
        release_boundary.set()
        dispatch.join(1)

        assert executor_calls == []
        finished = manager.wait("tenant-a", submitted["job_id"], 1)
        assert finished["state"] == "cancelled"
        assert finished["terminal"] is True
        assert finished["retryable"] is False
    finally:
        release_boundary.set()
        manager.close()
