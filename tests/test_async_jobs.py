from __future__ import annotations

import concurrent.futures
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


def _mode_gate_error(snapshot, _action=None):
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


def test_timed_out_accelerator_release_keeps_inference_admission_reserved(tmp_path):
    from local_ai_hub.operational_mode import unload_in_process_accelerators_for_gaming

    manager, _scheduler = _manager(tmp_path)
    release_started = threading.Event()
    finish_release = threading.Event()

    class _SlowAccelerator:
        def status(self):
            return {"loaded": True, "active_backend": "torch", "active_device": "cuda:0"}

        def release(self, timeout_seconds=3.0):
            release_started.set()
            finish_release.wait(timeout=2)
            return True

    try:
        receipt = unload_in_process_accelerators_for_gaming(
            embeddings=_SlowAccelerator(),
            inference_active=False,
            timeout_seconds=0.01,
            release_lifecycle=manager,
        )

        assert release_started.wait(timeout=1)
        assert receipt["models"]["embeddings"]["state"] == "timed_out"
        assert len(manager._resource_release_workers) == 1
        assert manager.foreground_busy() is True
        transition = manager.on_operational_mode_changed(
            SimpleNamespace(mode="gaming", revision=1, degraded=False, error="")
        )
        assert transition["inference_active"] is True
        assert transition["models_unloaded"] is False
        with manager.inference_admission("reason") as rejection:
            assert rejection["error_code"] == "resource_release_in_progress"
            assert rejection["retryable"] is True
    finally:
        finish_release.set()
        manager.close()
    assert manager._resource_release_tokens == set()
    assert manager._resource_release_workers == {}


def test_transcription_admission_drain_waits_for_http_handler_exit(tmp_path):
    manager, _scheduler = _manager(tmp_path)
    entered = threading.Event()
    finish = threading.Event()
    drained = threading.Event()

    def transcribe_request():
        with manager.inference_admission("transcribe") as rejection:
            assert rejection is None
            entered.set()
            finish.wait(timeout=2.0)

    worker = threading.Thread(target=transcribe_request)
    worker.start()
    try:
        assert entered.wait(timeout=1.0)
        assert manager.wait_for_inference_actions({"transcribe"}, 0.01) is False
        manager.when_inference_actions_drained({"transcribe"}, drained.set)
        finish.set()
        worker.join(timeout=1.0)
        assert not worker.is_alive()
        assert manager.wait_for_inference_actions({"transcribe"}, 0.1) is True
        assert drained.is_set()
    finally:
        finish.set()
        manager.close()


def test_async_executor_admission_drain_waits_for_service_exit(tmp_path):
    manager, _scheduler = _manager(tmp_path)
    entered = threading.Event()
    finish = threading.Event()
    drained = threading.Event()

    def blocked_executor(_action, _payload, _tenant):
        entered.set()
        finish.wait(timeout=2.0)
        return {"success": True}

    manager.executor = blocked_executor
    try:
        submitted = manager.submit("tenant-a", "reason", {"task": "wait for drain"})
        job_id = submitted["job_id"]
        assert entered.wait(timeout=1.0)
        assert manager.wait_for_inference_actions({"reason"}, 0.01) is False
        manager.when_inference_actions_drained({"reason"}, drained.set)
        assert drained.wait(timeout=0.05) is False

        finish.set()
        result = manager.wait("tenant-a", job_id, 1.0)
        assert result["state"] == "done"
        assert drained.wait(timeout=1.0) is True
    finally:
        finish.set()
        manager.close()


def test_dispatch_defers_queued_job_until_owned_resource_release_finishes(tmp_path, monkeypatch):
    manager, _scheduler = _manager(tmp_path)
    dispatched = []
    monkeypatch.setattr(manager, "_dispatch_background", lambda job_id: dispatched.append(job_id))
    try:
        token = manager.begin_resource_release()
        submitted = manager.submit("tenant-a", "reason", {"task": "wait for release"})
        job_id = submitted["job_id"]
        dispatched.clear()
        with closing(manager._connect()) as con:
            before = con.execute(
                "SELECT lease_until,dispatch_not_before FROM async_jobs WHERE job_id=?",
                (job_id,),
            ).fetchone()

        manager._dispatch(job_id)

        with closing(manager._connect()) as con:
            row = con.execute(
                "SELECT state,lease_until,dispatch_not_before FROM async_jobs WHERE job_id=?",
                (job_id,),
            ).fetchone()
        assert tuple(row) == ("queued", before[0], before[1])
        assert dispatched == []

        manager.end_resource_release(token)

        assert dispatched == [job_id]
    finally:
        manager.close()


def test_dispatch_requeues_claimed_job_when_release_starts_before_admission(
    tmp_path, monkeypatch
):
    manager, _scheduler = _manager(tmp_path)
    calls = []
    dispatches = []
    at_admission = threading.Event()
    continue_admission = threading.Event()
    release_token = None
    original_admission = manager._invoke_executor_if_allowed

    def pause_before_admission(job_id, action, payload, tenant):
        at_admission.set()
        assert continue_admission.wait(3)
        return original_admission(job_id, action, payload, tenant)

    monkeypatch.setattr(manager, "_invoke_executor_if_allowed", pause_before_admission)
    monkeypatch.setattr(manager, "_dispatch_background", lambda job_id: dispatches.append(job_id))
    manager.executor = lambda action, payload, tenant: calls.append((action, payload, tenant)) or {"success": True}
    worker = None
    try:
        submitted = manager.submit("tenant-a", "reason", {"task": "release admission race"})
        job_id = submitted["job_id"]
        dispatches.clear()
        worker = threading.Thread(target=manager._dispatch, args=(job_id,))
        worker.start()

        assert at_admission.wait(2)
        release_token = manager.begin_resource_release()
        continue_admission.set()
        worker.join(2)
        assert not worker.is_alive()
        for running in list(manager._workers):
            running.join(2)

        with closing(manager._connect()) as con:
            row = con.execute(
                "SELECT state,attempts FROM async_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
        assert tuple(row) == ("queued", 0)
        assert job_id in manager._resource_release_waiters
        assert calls == []

        manager.end_resource_release(release_token)
        release_token = None
        assert dispatches == [job_id]
        assert not manager._event(job_id).is_set()
    finally:
        continue_admission.set()
        if worker is not None:
            worker.join(2)
        if release_token is not None:
            manager.end_resource_release(release_token)
        manager.close()


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



def test_async_jobs_rejects_unknown_schema_without_modifying_database(tmp_path):
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
        version = int(con.execute("PRAGMA user_version").fetchone()[0])
    assert columns == ["job_id", "tenant"]
    assert rows == [("stale", "tenant-a")]
    assert version == 0


def test_async_jobs_rejects_previous_schema_without_mutating_rows(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    db_path = state_dir / "async_jobs.sqlite3"
    with closing(sqlite3.connect(db_path)) as con:
        con.execute("""CREATE TABLE async_jobs (
            job_id TEXT PRIMARY KEY, tenant TEXT NOT NULL, action TEXT NOT NULL, request_hash TEXT NOT NULL,
            payload_json TEXT NOT NULL, state TEXT NOT NULL, result_json TEXT NOT NULL DEFAULT '',
            artifact_id TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '', lease_until REAL NOT NULL DEFAULT 0,
            attempts INTEGER NOT NULL DEFAULT 0, cancel_requested INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL, updated_at REAL NOT NULL, expires_at REAL NOT NULL,
            trace_id TEXT NOT NULL DEFAULT '', task_id TEXT NOT NULL DEFAULT ''
        )""")
        con.execute(
            "INSERT INTO async_jobs(job_id,tenant,action,request_hash,payload_json,state,created_at,updated_at,expires_at) VALUES(?,?,?,?,?,'queued',?,?,?)",
            ("legacy-queued", "tenant-a", "reason", "legacy-hash", '{"task":"preserve"}', time.time(), time.time(), time.time() + 600),
        )
        con.commit()

    with pytest.raises(RuntimeError, match="unsupported async_jobs schema"):
        _manager(tmp_path)

    with closing(sqlite3.connect(db_path)) as con:
        columns = [str(row[1]) for row in con.execute("PRAGMA table_info(async_jobs)")]
        row = con.execute("SELECT job_id, state, request_hash FROM async_jobs").fetchone()
        version = int(con.execute("PRAGMA user_version").fetchone()[0])
    assert columns == [
        "job_id", "tenant", "action", "request_hash", "payload_json", "state", "result_json",
        "artifact_id", "error", "lease_until", "attempts", "cancel_requested", "created_at",
        "updated_at", "expires_at", "trace_id", "task_id",
    ]
    assert row == ("legacy-queued", "queued", "legacy-hash")
    assert version == 0

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
        assert started.wait(2.0)
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


def test_cancel_serializes_with_dispatch_across_manager_instances(tmp_path, monkeypatch):
    cancelling, _ = _manager(tmp_path)
    executor_started = threading.Event()
    cancel_selected = threading.Event()
    release_cancel = threading.Event()
    dispatch_started = threading.Event()
    dispatch_finished = threading.Event()

    def execute(_action, _payload, _tenant):
        executor_started.set()
        return {"success": True}

    dispatching = AsyncJobManager(
        {"server": {"state_dir": str(tmp_path / "state")}},
        _Scheduler(),
        _Artifacts(),
        execute,
    )
    original_connect = cancelling._connect

    class _ObservedConnection:
        def __init__(self, connection):
            self._connection = connection

        @property
        def row_factory(self):
            return self._connection.row_factory

        @row_factory.setter
        def row_factory(self, value):
            self._connection.row_factory = value

        def execute(self, sql, parameters=()):
            cursor = self._connection.execute(sql, parameters)
            if sql.lstrip().upper().startswith(
                "SELECT STATE,TRACE_ID,EXPIRES_AT,ARTIFACT_ID FROM ASYNC_JOBS"
            ):
                cancel_selected.set()
                release_cancel.wait(3)
            return cursor

        def __getattr__(self, name):
            return getattr(self._connection, name)

    monkeypatch.setattr(
        cancelling, "_connect", lambda: _ObservedConnection(original_connect())
    )
    cancel_result = []
    try:
        submitted = cancelling.submit(
            "tenant-a", "reason", {"task": "cancel dispatch race"},
            dispatch_delay_seconds=30,
        )
        with closing(original_connect()) as con:
            con.execute(
                "UPDATE async_jobs SET dispatch_not_before=0 WHERE job_id=?",
                (submitted["job_id"],),
            )
            con.commit()
        cancel_thread = threading.Thread(
            target=lambda: cancel_result.append(
                cancelling.cancel("tenant-a", submitted["job_id"])
            ),
            daemon=True,
        )
        cancel_thread.start()
        assert cancel_selected.wait(1)

        def run_dispatch():
            dispatch_started.set()
            dispatching._dispatch(submitted["job_id"])
            dispatch_finished.set()

        dispatch_thread = threading.Thread(target=run_dispatch, daemon=True)
        dispatch_thread.start()
        assert dispatch_started.wait(1)
        assert not executor_started.wait(0.2)
        assert not dispatch_finished.wait(0.2)

        release_cancel.set()
        cancel_thread.join(2)
        dispatch_thread.join(2)

        assert not cancel_thread.is_alive()
        assert not dispatch_thread.is_alive()
        assert dispatch_finished.is_set()
        assert cancel_result[0]["state"] == "cancelled"
        assert cancelling.status("tenant-a", submitted["job_id"])["state"] == "cancelled"
        assert not executor_started.is_set()
    finally:
        release_cancel.set()
        cancelling.close()
        dispatching.close()


def test_cancel_serializes_with_finalization_across_manager_instances(
    tmp_path, monkeypatch
):
    artifact_put_started = threading.Event()
    release_artifact_put = threading.Event()
    cancel_finished = threading.Event()
    cancel_write_attempted = threading.Event()
    cancel_result = []

    class _BlockingArtifacts(_Artifacts):
        def put(self, content, tenant, kind):
            artifact_put_started.set()
            assert release_artifact_put.wait(3)
            return super().put(content, tenant, kind)

    state_dir = str(tmp_path / "state")
    finalizing = AsyncJobManager(
        {"server": {"state_dir": state_dir}},
        _Scheduler(),
        _BlockingArtifacts(),
        lambda _action, _payload, _tenant: {"success": True},
    )
    cancelling = AsyncJobManager(
        {"server": {"state_dir": state_dir}},
        _Scheduler(),
        _Artifacts(),
        lambda _action, _payload, _tenant: {"success": True},
    )
    original_cancel_connect = cancelling._connect

    class _ObservedConnection:
        def __init__(self, connection):
            self._connection = connection

        def execute(self, sql, parameters=()):
            if sql.strip().upper() == "BEGIN IMMEDIATE":
                cancel_write_attempted.set()
            return self._connection.execute(sql, parameters)

        def __getattr__(self, name):
            return getattr(self._connection, name)

    monkeypatch.setattr(
        cancelling,
        "_connect",
        lambda: _ObservedConnection(original_cancel_connect()),
    )
    try:
        submitted = finalizing.submit(
            "tenant-a", "reason", {"task": "cancel finalization race"},
            dispatch_delay_seconds=30,
        )
        job_id = submitted["job_id"]
        with closing(finalizing._connect()) as con:
            con.execute(
                "UPDATE async_jobs SET dispatch_not_before=0 WHERE job_id=?",
                (job_id,),
            )
            con.commit()

        finalizing._dispatch(job_id)
        assert artifact_put_started.wait(2)

        def cancel():
            cancel_result.append(cancelling.cancel("tenant-a", job_id))
            cancel_finished.set()

        cancel_thread = threading.Thread(target=cancel, daemon=True)
        cancel_thread.start()
        assert cancel_write_attempted.wait(1)
        assert not cancel_finished.wait(0.2)

        release_artifact_put.set()
        cancel_thread.join(2)
        for worker in list(finalizing._workers):
            worker.join(2)

        assert not cancel_thread.is_alive()
        assert cancel_result[0]["state"] == "done"
        assert finalizing.status("tenant-a", job_id)["state"] == "done"
    finally:
        release_artifact_put.set()
        finalizing.close()
        cancelling.close()


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
        assert blocked["terminal"] is False
        assert blocked["retryable"] is True
        assert 0 < blocked["retry_after_seconds"] <= 10
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
        assert blocked["terminal"] is False
        assert blocked["retryable"] is True
        assert 0 < blocked["retry_after_seconds"] <= 10
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


def test_persisted_modes_gate_async_admission_without_test_overrides(tmp_path, monkeypatch):
    monkeypatch.delattr(async_jobs, "load_operational_mode", raising=False)
    monkeypatch.delattr(async_jobs, "operational_mode_gate_error", raising=False)
    from local_ai_hub.operational_mode import load_operational_mode, set_operational_mode

    manager, scheduler = _manager(tmp_path)
    state_dir = tmp_path / "state"
    try:
        active = set_operational_mode(state_dir, "active")
        accepted = manager.submit(
            "tenant-a", "reason", {"task": "active mode"},
            dispatch_delay_seconds=30,
        )
        assert accepted["success"] is True
        assert load_operational_mode(state_dir).revision == active.revision
        assert manager.cancel("tenant-a", accepted["job_id"])["state"] == "cancelled"

        gaming = set_operational_mode(state_dir, "gaming")
        rejected_inference = manager.submit(
            "tenant-a", "reason", {"task": "gaming mode inference"},
            dispatch_delay_seconds=30,
        )
        assert rejected_inference["success"] is False
        assert rejected_inference["operational_mode"] == "gaming"
        assert rejected_inference["operational_mode_revision"] == gaming.revision

        allowed_lint = manager.submit(
            "tenant-a", "speculative_lint", {"task": "gaming mode lint"},
            dispatch_delay_seconds=30,
        )
        assert allowed_lint["success"] is True
        assert manager.cancel("tenant-a", allowed_lint["job_id"])["state"] == "cancelled"

        maintenance = set_operational_mode(state_dir, "maintenance")
        rejected_lint = manager.submit(
            "tenant-a", "speculative_lint", {"task": "maintenance mode lint"},
            dispatch_delay_seconds=30,
        )
        assert rejected_lint["success"] is False
        assert rejected_lint["operational_mode"] == "maintenance"
        assert rejected_lint["operational_mode_revision"] == maintenance.revision
        assert scheduler.calls == []
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


def test_submit_mode_gate_and_queue_insert_are_atomic_with_mode_transition(tmp_path, monkeypatch):
    mode = _patch_operational_mode(monkeypatch)
    manager, _scheduler = _manager(tmp_path)
    gate_reached = threading.Event()
    continue_submit = threading.Event()
    transition_started = threading.Event()
    transition_mode_changed = threading.Event()
    transition_done = threading.Event()
    submitted = {}
    original_gate = manager._mode_blocked_result

    def pause_after_mode_gate(action, snapshot):
        result = original_gate(action, snapshot)
        gate_reached.set()
        assert continue_submit.wait(2)
        return result

    monkeypatch.setattr(manager, "_mode_blocked_result", pause_after_mode_gate)

    def do_submit():
        submitted.update(
            manager.submit(
                "tenant-a", "reason", {"task": "atomic admission"}, dispatch_delay_seconds=30
            )
        )

    def change_mode():
        transition_started.set()
        with manager.operational_mode_change_guard():
            mode.mode = "gaming"
            transition_mode_changed.set()
            mode.revision = 1
            manager.on_operational_mode_changed(mode)
        transition_done.set()

    submit_thread = threading.Thread(target=do_submit)
    transition_thread = threading.Thread(target=change_mode)
    try:
        submit_thread.start()
        assert gate_reached.wait(1)
        transition_thread.start()
        assert transition_started.wait(1)
        assert not transition_mode_changed.wait(0.05)
        assert not transition_done.wait(0.05)
        assert mode.mode == "active"

        continue_submit.set()
        submit_thread.join(1)
        transition_thread.join(1)

        assert not submit_thread.is_alive()
        assert not transition_thread.is_alive()
        assert submitted["success"] is True
        status = manager.status("tenant-a", submitted["job_id"])
        assert status["state"] == "cancelled"
    finally:
        continue_submit.set()
        submit_thread.join(1)
        if transition_thread.ident is not None:
            transition_thread.join(1)
        manager.close()


@pytest.mark.parametrize(
    ("mode_name", "action"),
    (("gaming", "reason"), ("maintenance", "speculative_lint")),
)
def test_dispatch_paused_before_admission_is_cancelled_by_mode_transition(
    tmp_path, monkeypatch, mode_name, action
):
    mode = _patch_operational_mode(monkeypatch)
    calls = []
    manager = AsyncJobManager(
        {"server": {"state_dir": str(tmp_path / "state")}, "async_jobs": {"wait_max_seconds": 90}},
        _Scheduler(),
        _Artifacts(),
        lambda task_action, payload, tenant: calls.append((task_action, payload, tenant))
        or {"success": True},
    )
    at_admission = threading.Event()
    continue_dispatch = threading.Event()
    original_admission = manager._invoke_executor_if_allowed

    def pause_before_final_admission(job_id, task_action, payload, tenant):
        at_admission.set()
        assert continue_dispatch.wait(5)
        return original_admission(job_id, task_action, payload, tenant)

    monkeypatch.setattr(manager, "_invoke_executor_if_allowed", pause_before_final_admission)
    monkeypatch.setattr(manager, "_dispatch_background", lambda _job_id: None)
    dispatch = None
    try:
        submitted = manager.submit(
            "tenant-a", action, {"task": "dispatch admission race"}
        )
        assert submitted["success"] is True

        dispatch = threading.Thread(target=manager._dispatch, args=(submitted["job_id"],))
        dispatch.start()
        assert at_admission.wait(2)
        with manager.operational_mode_change_guard():
            mode.mode = mode_name
            mode.revision = 1
            manager.on_operational_mode_changed(mode)

        continue_dispatch.set()
        dispatch.join(2)
        assert not dispatch.is_alive()
        status = manager.wait("tenant-a", submitted["job_id"], 2)
        assert status["state"] == "cancelled"
        assert calls == []
    finally:
        continue_dispatch.set()
        if dispatch is not None:
            dispatch.join(2)
        manager.close()


def test_inference_admission_reservation_is_nonblocking_and_app_rechecks_mode(
    tmp_path, monkeypatch
):
    mode = _patch_operational_mode(monkeypatch)
    manager, _scheduler = _manager(tmp_path)
    from local_ai_hub.app import LocalAIApp

    app = LocalAIApp.__new__(LocalAIApp)
    app.async_jobs = manager
    service_calls = []
    app.services = SimpleNamespace(
        reason=lambda payload, tenant: service_calls.append((payload, tenant))
        or {"success": True}
    )
    transition_done = threading.Event()

    def change_mode():
        with manager.operational_mode_change_guard():
            mode.mode = "gaming"
            mode.revision = 1
            manager.on_operational_mode_changed(mode)
        transition_done.set()

    transition_thread = threading.Thread(target=change_mode)
    try:
        with manager.inference_admission("reason") as rejection:
            assert rejection is None
            assert manager.foreground_busy() is True

            transition_thread.start()
            assert transition_done.wait(1)

            result = app._execute_async_task(
                "reason", {"task": "must stay blocked"}, "tenant-a"
            )
            assert result["success"] is False
            assert result["error_code"] == "operational_mode_blocked"
            assert service_calls == []
            assert manager.foreground_busy() is True

        assert manager.foreground_busy() is False
    finally:
        if transition_thread.ident is not None:
            transition_thread.join(1)
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
        assert started.wait(2)

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


def test_mode_change_receipt_reports_running_inference_until_cancel_finishes(tmp_path, monkeypatch):
    mode = _patch_operational_mode(monkeypatch)
    started = threading.Event()
    release = threading.Event()

    def execute(_action, _payload, _tenant):
        started.set()
        release.wait(2)
        return {"success": True, "text": "inference returned"}

    manager = AsyncJobManager(
        {"server": {"state_dir": str(tmp_path / "state")}, "async_jobs": {"wait_max_seconds": 90}},
        _Scheduler(),
        _Artifacts(),
        execute,
    )
    try:
        running = manager.submit("tenant-a", "reason", {"task": "model inference"})
        assert started.wait(1)
        mode.mode = "gaming"
        mode.revision = 3

        receipt = manager.on_operational_mode_changed(mode)
        assert receipt["cancel_requests_issued"] == 1
        assert receipt["active_inference_jobs"] == 1
        assert receipt["inference_active"] is True
        assert receipt["models_unloaded"] is False

        release.set()
        assert manager.wait("tenant-a", running["job_id"], 1)["state"] == "cancelled"
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
    monkeypatch.setattr(manager, "_dispatch_background", lambda _job_id: None)
    try:
        submitted = manager.submit(
            "tenant-a", action, {"task": "mode start race"}
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
        assert submitted["admission_state"] == "accepted"
        assert submitted["job_id"] in manager._delayed_dispatch
        cancelled = manager.cancel("tenant-a", submitted["job_id"])

        assert cancelled["state"] == "cancelled"
        assert dispatch_attempts == []
        assert scheduler.calls == []
        assert submitted.get("error") is None
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


def test_job_execution_claim_is_atomic_across_manager_instances(tmp_path, monkeypatch):
    first, _ = _manager(tmp_path)
    second, _ = _manager(tmp_path)
    selected_queued = threading.Barrier(2)
    executor_calls = []
    executor_lock = threading.Lock()

    class _BarrierConnection:
        def __init__(self, connection, claim_barrier_used):
            self._connection = connection
            self._claim_barrier_used = claim_barrier_used
            self._claim_transaction_started = False

        @property
        def row_factory(self):
            return self._connection.row_factory

        @row_factory.setter
        def row_factory(self, value):
            self._connection.row_factory = value

        def execute(self, sql, parameters=()):
            if not self._claim_transaction_started and sql.strip().upper() == "BEGIN IMMEDIATE":
                if not self._claim_barrier_used.is_set():
                    self._claim_barrier_used.set()
                    selected_queued.wait(timeout=5)
                self._claim_transaction_started = True
            cursor = self._connection.execute(sql, parameters)
            if not self._claim_transaction_started and sql.lstrip().upper().startswith(
                "SELECT * FROM ASYNC_JOBS WHERE JOB_ID="
            ):
                selected_queued.wait(timeout=5)
            return cursor

        def __getattr__(self, name):
            return getattr(self._connection, name)

    try:
        def executor(action, payload, tenant):
            with executor_lock:
                executor_calls.append((action, tenant))
            return {"success": True, "task": payload.get("task")}

        first.executor = executor
        second.executor = executor
        monkeypatch.setattr(first, "_dispatch", lambda *_args: None)
        monkeypatch.setattr(second, "_dispatch", lambda *_args: None)
        submitted = first.submit("tenant-a", "reason", {"task": "single claim"})
        assert submitted["admission_state"] == "accepted"

        for manager in (first, second):
            original_connect = manager._connect
            claim_barrier_used = threading.Event()
            monkeypatch.setattr(
                manager,
                "_connect",
                lambda original=original_connect, used=claim_barrier_used: _BarrierConnection(original(), used),
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    lambda manager: manager._execute(submitted["job_id"]),
                    (first, second),
                )
            )

        assert len(executor_calls) == 1
        assert all(isinstance(result, dict) for result in results)
    finally:
        first.close()
        second.close()


@pytest.mark.parametrize(
    ("field", "value"),
    (("cancel_requested", 1), ("lease_until", 10**12), ("dispatch_not_before", 10**12)),
)
def test_dispatch_claim_rechecks_cancel_lease_and_deadline_atomically(
    tmp_path, monkeypatch, field, value
):
    manager, _scheduler = _manager(tmp_path)
    started = []
    real_thread = threading.Thread

    class _TrackingThread(real_thread):
        def start(self):
            started.append(self)
            super().start()

    try:
        original_dispatch = manager._dispatch
        monkeypatch.setattr(manager, "_dispatch_background", lambda *_args: None)
        monkeypatch.setattr(manager, "_execute", lambda *_args: None)
        monkeypatch.setattr(manager, "_cancel_jobs_blocked_by_mode", lambda *_args: None)
        submitted = manager.submit("tenant-a", "reason", {"task": "atomic dispatch"})
        assert submitted.get("admission_state") == "accepted", submitted
        job_id = submitted["job_id"]
        original_connect = manager._connect
        claim_attempts = []

        class _RaceConnection:
            def __init__(self, connection):
                self._connection = connection

            @property
            def row_factory(self):
                return self._connection.row_factory

            @row_factory.setter
            def row_factory(self, value):
                self._connection.row_factory = value

            def execute(self, sql, parameters=()):
                if "UPDATE async_jobs SET lease_until=?,dispatch_not_before=0,updated_at=?" in sql:
                    claim_attempts.append(sql)
                    self._connection.execute(
                        f"UPDATE async_jobs SET {field}=? WHERE job_id=?", (value, job_id)
                    )
                    self._connection.commit()
                return self._connection.execute(sql, parameters)

            def __getattr__(self, name):
                return getattr(self._connection, name)

        monkeypatch.setattr(
            manager, "_connect", lambda: _RaceConnection(original_connect())
        )
        monkeypatch.setattr(async_jobs.threading, "Thread", _TrackingThread)
        monkeypatch.setattr(manager, "_dispatch", original_dispatch)

        manager._dispatch(job_id)

        assert len(claim_attempts) == 1
        assert started == []
    finally:
        manager.close()


def test_recover_preserves_unelapsed_dispatch_delay(tmp_path, monkeypatch):
    manager, _scheduler = _manager(tmp_path)
    submitted = manager.submit(
        "tenant-a", "reason", {"task": "delayed recovery race"},
        dispatch_delay_seconds=30,
    )
    _simulate_process_crash(manager)

    reopened, _scheduler = _manager(tmp_path)
    dispatch_attempts = []
    monkeypatch.setattr(reopened, "_dispatch", dispatch_attempts.append)
    try:
        reopened.recover()
        recovered = reopened._row("tenant-a", submitted["job_id"])

        assert recovered is not None
        assert recovered["state"] == "queued"
        assert recovered["dispatch_not_before"] > time.time()
        assert recovered["lease_until"] == 0
        assert dispatch_attempts == []
    finally:
        reopened.close()


def test_recover_does_not_treat_dispatch_lease_as_submit_delay(tmp_path, monkeypatch):
    manager, _scheduler = _manager(tmp_path)
    manager._dispatch = lambda _job_id: None
    submitted = manager.submit("tenant-a", "reason", {"task": "dispatch claim crash"})
    with closing(manager._connect()) as con:
        con.execute(
            "UPDATE async_jobs SET lease_until=?,dispatch_not_before=0 WHERE job_id=?",
            (time.time() + 900, submitted["job_id"]),
        )
        con.commit()
    _simulate_process_crash(manager)

    reopened, _scheduler = _manager(tmp_path)
    dispatch_attempts = []
    monkeypatch.setattr(reopened, "_dispatch", dispatch_attempts.append)
    try:
        reopened.recover()
        recovered = reopened._row("tenant-a", submitted["job_id"])

        assert recovered is not None
        assert recovered["state"] == "queued"
        assert recovered["lease_until"] == 0
        assert recovered["dispatch_not_before"] == 0
        assert dispatch_attempts == [submitted["job_id"]]
    finally:
        reopened.close()
