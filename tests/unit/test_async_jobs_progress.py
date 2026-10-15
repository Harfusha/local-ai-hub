"""Deferred bundle regressions; durable job databases are temporary."""
import time
from contextlib import closing
from types import SimpleNamespace

from local_ai_hub.async_jobs import AsyncJobManager, report_job_progress


def _manager(tmp_path, executor=None):
    return AsyncJobManager(
        {"server": {"state_dir": str(tmp_path / "state")}},
        SimpleNamespace(config={"models": {"heavy_code": "fake"}}),
        SimpleNamespace(put=lambda *_args: "artifact-progress"),
        executor or (lambda *_args: {"success": True}),
    )


def _seed(manager, *, state="running", attempt=1):
    now = time.time()
    with closing(manager._connect()) as con:
        con.execute(
            "INSERT INTO async_jobs(job_id,tenant,action,request_hash,payload_json,state,attempts,"
            "lease_until,created_at,updated_at,expires_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            ("job-progress", "tenant-a", "reason", "hash-progress", '{"task":"bounded"}', state,
             attempt, now + 600, now, now, now + 3600),
        )
        con.commit()


def test_progress_is_monotonic_throttled_tenant_and_attempt_scoped(tmp_path, monkeypatch):
    manager = _manager(tmp_path)
    clock = [10.0]
    monkeypatch.setattr("local_ai_hub.async_jobs.time.monotonic", lambda: clock[0])
    try:
        _seed(manager)
        update = manager._progress_callback("job-progress", "tenant-a", 1)
        assert update(50, "halfway")
        assert not update(60, "too soon")
        clock[0] += 1
        assert update(25, "later stage")
        status = manager.status("tenant-a", "job-progress")
        assert status["progress_percent"] == 50
        assert status["current_stage"] == "later stage"
        assert not manager.status("tenant-b", "job-progress")["success"]
        assert not manager._progress_callback("job-progress", "tenant-b", 1)(90, "foreign")
        assert not manager._progress_callback("job-progress", "tenant-a", 2)(90, "wrong attempt")
        clock[0] += 1
        assert update(100, "work finished")
        assert manager.status("tenant-a", "job-progress")["progress_percent"] == 99
        with closing(manager._connect()) as con:
            con.execute("UPDATE async_jobs SET cancel_requested=1 WHERE job_id='job-progress'")
            con.commit()
        clock[0] += 1
        assert not update(99, "after cancel")
    finally:
        manager.close()


def test_progress_survives_reopen_without_changing_durable_job_columns(tmp_path):
    manager = _manager(tmp_path)
    _seed(manager)
    assert manager._progress_callback("job-progress", "tenant-a", 1)(42, "retrieving")
    with closing(manager._connect()) as con:
        original_columns = con.execute("PRAGMA table_info(async_jobs)").fetchall()
    manager.close()
    reopened = _manager(tmp_path)
    try:
        assert reopened.status("tenant-a", "job-progress")["progress_percent"] == 42
        with closing(reopened._connect()) as con:
            assert con.execute("PRAGMA table_info(async_jobs)").fetchall() == original_columns
    finally:
        reopened.close()


def test_executor_context_callback_is_reset_and_done_requires_artifact(tmp_path):
    observed = []

    def execute(_action, _payload, _tenant):
        observed.append(report_job_progress(30, "analyzing"))
        return {"success": True}

    manager = _manager(tmp_path, execute)
    try:
        _seed(manager, state="queued", attempt=0)
        assert not report_job_progress(10, "outside")
        assert manager._execute("job-progress")["success"]
        assert observed == [True]
        assert not report_job_progress(10, "outside again")
        status = manager.status("tenant-a", "job-progress")
        assert status["state"] == "done"
        assert status["progress_percent"] == 100
        assert status["current_stage"] == "done"
    finally:
        manager.close()
