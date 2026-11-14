from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import closing, contextmanager
from types import SimpleNamespace

import local_ai_hub.async_jobs as async_jobs_module
from local_ai_hub.async_jobs import AsyncJobManager


class _Artifacts:
    def put(self, _content, *, kind):
        return "async-lock-test-artifact"

    def get(self, _artifact_id, *, offset=0, max_chars=256):
        return {"success": True, "text": "{}"}


class _Scheduler:
    config = {"models": {"heavy_code": "test-model"}}

    @staticmethod
    def resource_status():
        return {"available": True, "pressure_level": "nominal", "context_budget_factor": 1.0}


def test_async_finalization_waits_for_short_external_writer_lock(tmp_path, monkeypatch):
    executor_started = threading.Event()
    allow_executor_finish = threading.Event()
    finalization_started = threading.Event()
    results: list[dict] = []
    errors: list[BaseException] = []
    finalization_json_serializations: list[object] = []
    finalization_active = threading.Event()

    def executor(_action, _payload):
        executor_started.set()
        assert allow_executor_finish.wait(5)
        return {"success": True}

    manager = AsyncJobManager(
        {"server": {"state_dir": str(tmp_path)}},
        _Scheduler(),
        _Artifacts(),
        executor,
    )
    monkeypatch.setattr(manager, "_dispatch_background", lambda _job_id: None)
    monkeypatch.setattr(
        manager,
        "_operational_mode_snapshot",
        lambda: {"mode": "active", "revision": 0, "degraded": False, "snapshot": None, "gate_error": None},
    )

    original_write_transaction = async_jobs_module.write_transaction
    original_json_dumps = async_jobs_module.json_dumps

    def observe_json_dumps(value, *args, **kwargs):
        if finalization_active.is_set():
            finalization_json_serializations.append(value)
            # Recreate the duration-budget failure if serialization drifts back
            # under the writer lock; the accepted path must never pay this cost.
            time.sleep(2.05)
        return original_json_dumps(value, *args, **kwargs)

    monkeypatch.setattr(async_jobs_module, "json_dumps", observe_json_dumps)

    @contextmanager
    def observe_finalization_start(connection, **kwargs):
        finalization_started.set()
        is_finalization = kwargs.get("rollback_label") == "async job finalization"
        if is_finalization:
            finalization_active.set()
        try:
            with original_write_transaction(connection, **kwargs) as active:
                yield active
        finally:
            if is_finalization:
                finalization_active.clear()

    monkeypatch.setattr(async_jobs_module, "write_transaction", observe_finalization_start)

    runner = None
    blocker = None
    try:
        submitted = manager.submit("reason", {"task": "bounded"}, dispatch_delay_seconds=30)
        assert submitted["success"] is True

        def run_job():
            try:
                results.append(manager._execute(submitted["job_id"]))
            except BaseException as exc:  # Capture worker-thread failures for the assertion below.
                errors.append(exc)

        runner = threading.Thread(target=run_job, daemon=True)
        runner.start()
        assert executor_started.wait(2)

        blocker = sqlite3.connect(manager.path, timeout=0.1, isolation_level=None)
        blocker.execute("BEGIN IMMEDIATE")
        allow_executor_finish.set()
        assert finalization_started.wait(2)
        time.sleep(0.9)
        assert runner.is_alive(), "finalization abandoned a lock released within its transaction budget"

        blocker.execute("COMMIT")
        runner.join(3)

        assert not runner.is_alive()
        assert errors == []
        assert results[0]["success"] is True
        assert manager.status(submitted["job_id"])["state"] == "done"
        assert finalization_json_serializations == []
    finally:
        allow_executor_finish.set()
        if blocker is not None:
            try:
                if blocker.in_transaction:
                    blocker.execute("ROLLBACK")
            finally:
                blocker.close()
        if runner is not None:
            runner.join(3)
        manager.close()
