from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import closing

import pytest

from local_ai_hub.async_jobs import AsyncJobManager
from local_ai_hub.process_utils import hidden_run_kwargs, popen_managed


class _Job:
    def __init__(self) -> None:
        self.id = 7
        self.done = threading.Event()
        self.error = None


class _Scheduler:
    config = {"models": {"heavy_code": "audit-test-model"}}

    def enqueue(self, _model, _source, _execute, priority=1, *, background=True):
        return _Job()


class _Artifacts:
    def __init__(self) -> None:
        self.items: dict[str, str] = {}

    def put(self, content: str, *, kind: str) -> str:
        assert kind == "async-job"
        artifact_id = f"audit-artifact-{len(self.items) + 1}"
        self.items[artifact_id] = content
        return artifact_id

    def get(self, artifact_id: str, *, offset=0, max_chars=256):
        return {"success": artifact_id in self.items, "text": self.items.get(artifact_id, "")[:max_chars]}


class _VerificationStore:
    def __init__(self) -> None:
        self.receipts = []

    def record(self, receipt) -> None:
        self.receipts.append(receipt)


class _Process:
    def __init__(self) -> None:
        self.stopped = False

    def poll(self):
        return 0 if self.stopped else None

    def terminate(self):
        self.stopped = True

    def wait(self, timeout):
        assert timeout > 0
        self.stopped = True
        return 0


def _manager(tmp_path, executor, *, artifacts=None, verification_store=None):
    artifacts = artifacts or _Artifacts()
    manager = AsyncJobManager(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "async_jobs": {"wait_max_seconds": 90},
        },
        _Scheduler(),
        artifacts,
        executor,
        verification_store=verification_store,
    )
    return manager, artifacts


def _set_attempt_lease(manager: AsyncJobManager, job_id: str, lease_until: float) -> None:
    with manager._lock, closing(manager._connect()) as con:
        con.execute("UPDATE async_jobs SET lease_until=? WHERE job_id=?", (lease_until, job_id))
        con.commit()


@pytest.mark.parametrize("simultaneous_finalization", [False, True])
def test_stale_attempt_cannot_publish_result_artifact_or_positive_receipt(tmp_path, simultaneous_finalization):
    first_started = threading.Event()
    release_first = threading.Event()
    second_returned = threading.Event()
    call_lock = threading.Lock()
    calls = 0
    verification = _VerificationStore()

    def execute(_action, _payload):
        nonlocal calls
        with call_lock:
            calls += 1
            attempt = calls
        if attempt == 1:
            first_started.set()
            assert release_first.wait(5), "bounded stale attempt release missing"
            return {"success": True, "value": "stale"}
        second_returned.set()
        if simultaneous_finalization:
            assert release_first.wait(5), "bounded simultaneous finalization release missing"
        return {"success": True, "value": "current"}

    manager, artifacts = _manager(tmp_path, execute, verification_store=verification)
    try:
        submitted = manager.submit(
            "reason",
            {"task": "stale finalization", "request_id": "audit-stale-finalization", "task_id": "task-audit-stale"},
        )
        job_id = submitted["job_id"]
        assert first_started.wait(3), "first attempt did not start"

        _set_attempt_lease(manager, job_id, time.time() - 1)
        manager.tick()
        assert second_returned.wait(3), "replacement attempt did not execute"
        if simultaneous_finalization:
            release_first.set()
        assert manager._event(job_id).wait(3), "replacement attempt did not finalize"
        current = manager.result(job_id)
        assert current.get("result", {}).get("value") == "current", current

        release_first.set()
        with manager._lock:
            workers = list(manager._workers)
        for worker in workers:
            worker.join(timeout=3)
            assert not worker.is_alive(), "stale worker did not finish within the bound"

        final = manager.result(job_id)
        assert final.get("result", {}).get("value") == "current", final
        assert len(artifacts.items) == 1
        stored = json.loads(next(iter(artifacts.items.values())))
        assert stored.get("value") == "current"
        assert len(verification.receipts) == 1
        assert verification.receipts[0].passed is True
        assert verification.receipts[0].evidence_id == next(iter(artifacts.items))
    finally:
        release_first.set()
        manager.close()


@pytest.mark.parametrize("during_finalization", ["cancel", "expire", "expire-cleanup-unknown"])
def test_running_result_cancelled_or_expired_before_finalize_cannot_publish_success(
    tmp_path, monkeypatch, during_finalization
):
    executor_started = threading.Event()
    release_executor = threading.Event()
    verification = _VerificationStore()

    def execute(_action, _payload):
        executor_started.set()
        assert release_executor.wait(5), "bounded finalization release missing"
        return {"success": True, "value": "must not publish"}

    manager, artifacts = _manager(tmp_path, execute, verification_store=verification)
    original_cleanup = manager._cleanup_processes
    if during_finalization == "expire-cleanup-unknown":
        monkeypatch.setattr(manager, "_cleanup_processes", lambda *_args, **_kwargs: False)
    try:
        submitted = manager.submit(
            "reason",
            {"task": "cancel or expire during execution", "request_id": f"audit-{during_finalization}"},
        )
        job_id = submitted["job_id"]
        assert executor_started.wait(3), "executor did not start"

        if during_finalization == "cancel":
            cancelled = manager.cancel(job_id)
            assert cancelled["success"] is True
        else:
            with manager._lock, closing(manager._connect()) as con:
                con.execute("UPDATE async_jobs SET expires_at=? WHERE job_id=?", (time.time() - 1, job_id))
                con.commit()

        release_executor.set()
        with manager._lock:
            workers = list(manager._workers)
        for worker in workers:
            worker.join(timeout=3)
            assert not worker.is_alive(), "finalizing worker did not stop within the bound"

        status = manager.status(job_id)
        expected = "cancelled" if during_finalization == "cancel" else "expired"
        assert status["state"] == expected
        if during_finalization == "expire-cleanup-unknown":
            with closing(manager._connect()) as connection:
                persisted = connection.execute(
                    "SELECT state,result_json FROM async_jobs WHERE job_id=?", (job_id,),
                ).fetchone()
            assert persisted[0] == "outcome_unknown"
            assert json.loads(persisted[1])["outcome_unknown"] is True
        assert artifacts.items == {}
        assert verification.receipts == []
    finally:
        release_executor.set()
        monkeypatch.setattr(manager, "_cleanup_processes", original_cleanup)
        manager.close()


def test_expiry_during_artifact_write_cannot_leave_running_or_publish_receipt(tmp_path, monkeypatch):
    verification = _VerificationStore()
    artifacts = _Artifacts()
    manager, _ = _manager(tmp_path, lambda *_args: {"success": True},
                          artifacts=artifacts, verification_store=verification)
    real_time = time.time
    offset = 0.0
    original_put = artifacts.put
    storage_finished = threading.Event()

    def slow_storage(content, *, kind):
        nonlocal offset
        artifact_id = original_put(content, kind=kind)
        offset = manager.result_ttl_seconds + 1.0
        storage_finished.set()
        return artifact_id

    monkeypatch.setattr(artifacts, "put", slow_storage)
    monkeypatch.setattr("local_ai_hub.async_jobs.time.time", lambda: real_time() + offset)
    try:
        submitted = manager.submit("reason", {"task": "expiry during storage",
                                               "request_id": "audit-storage-expiry",
                                               "task_id": "task-storage-expiry"})
        job_id = submitted["job_id"]
        assert storage_finished.wait(3), "artifact write did not execute"
        with manager._lock:
            workers = list(manager._workers)
        for worker in workers:
            worker.join(timeout=3)
            assert not worker.is_alive()
        status = manager.status(job_id)
        assert status["state"] == "expired", status
        assert manager._event(job_id).is_set()
        assert not manager.result(job_id).get("artifact_id")
        assert verification.receipts == []
        # A store write that completed across expiry may exist privately, but
        # the job must never publish its pointer or a positive receipt.
        assert len(artifacts.items) == 1
    finally:
        monkeypatch.setattr("local_ai_hub.async_jobs.time.time", real_time)
        manager.close()


@pytest.mark.parametrize(
    "envelope",
    [
        pytest.param({"success": "false"}, id="string-false"),
        pytest.param({"success": 1}, id="integer-one"),
        pytest.param({"success": []}, id="empty-list"),
        pytest.param({}, id="missing"),
        pytest.param({"success": False, "retryable": False}, id="boolean-false"),
    ],
)
def test_only_explicit_boolean_true_can_publish_success_artifact_or_receipt(tmp_path, envelope):
    verification = _VerificationStore()
    manager, artifacts = _manager(
        tmp_path,
        lambda _action, _payload: dict(envelope),
        verification_store=verification,
    )
    try:
        submitted = manager.submit(
            "reason",
            {"task": "strict success", "request_id": "audit-strict-success", "task_id": "task-audit-strict"},
        )
        terminal = manager.wait(submitted["job_id"], 5)
        result = manager.result(submitted["job_id"])

        assert terminal["state"] == result["state"] == "failed"
        assert result["success"] is False
        assert result.get("artifact_id", "") == ""
        assert artifacts.items == {}
        assert verification.receipts == []
    finally:
        manager.close()


@pytest.mark.parametrize("failure_phase", ["connect", "update", "commit"])
@pytest.mark.parametrize("process_kind", ["handle", "actual-child"])
def test_close_database_failure_still_cleans_local_handles_and_can_retry(
    tmp_path, monkeypatch, failure_phase, process_kind
):
    manager, _artifacts = _manager(tmp_path, lambda _action, _payload: {"success": True})
    submitted = manager.submit("reason", {"task": "close cleanup"}, dispatch_delay_seconds=30)
    job_id = submitted["job_id"]
    process = (_Process() if process_kind == "handle" else popen_managed(
        [sys.executable, "-B", "-c", "import time; time.sleep(30)"],
        cwd=str(tmp_path), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        **hidden_run_kwargs(),
    ))
    assert process.poll() is None
    manager.register_process("audit-owned-process", process)
    waiter = manager._event(job_id)
    worker_done = threading.Event()
    worker = threading.Thread(target=lambda: (manager._shutdown.wait(), worker_done.set()))
    manager._workers.add(worker)
    worker.start()

    original_connect = manager._connect

    class FaultingConnection:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, sql, parameters=()):
            if failure_phase == "update" and sql.lstrip().upper().startswith("UPDATE ASYNC_JOBS"):
                raise sqlite3.OperationalError("injected close failure: update")
            return self.connection.execute(sql, parameters)

        def commit(self):
            if failure_phase == "commit":
                raise sqlite3.OperationalError("injected close failure: commit")
            return self.connection.commit()

        def close(self):
            self.connection.close()

    def connect_with_fault():
        if failure_phase == "connect":
            raise sqlite3.OperationalError("injected close failure: connect")
        connection = original_connect()
        return FaultingConnection(connection) if failure_phase in {"update", "commit"} else connection

    try:
        monkeypatch.setattr(manager, "_connect", connect_with_fault)
        started = time.monotonic()
        with pytest.raises(sqlite3.OperationalError, match=f"injected close failure: {failure_phase}"):
            manager.close()
        elapsed = time.monotonic() - started

        assert elapsed < 2.0
        assert manager._shutdown.is_set()
        assert waiter.is_set()
        assert process.poll() is not None
        assert worker_done.is_set()
        assert not worker.is_alive()
        assert not manager._processes

        monkeypatch.setattr(manager, "_connect", original_connect)
        manager.close()
        with closing(original_connect()) as con:
            row = con.execute("SELECT state,cancel_requested FROM async_jobs WHERE job_id=?", (job_id,)).fetchone()
        assert tuple(row) == ("cancelled", 1)
    finally:
        manager._shutdown.set()
        worker.join(timeout=1)
        monkeypatch.setattr(manager, "_connect", original_connect)
        try:
            manager.close()
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=3)

