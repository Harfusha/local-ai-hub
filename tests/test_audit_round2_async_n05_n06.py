from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path

from local_ai_hub.async_jobs import AsyncJobManager


class _DummyScheduler:
    config = {}

    def enqueue(self, *args, **kwargs):
        return None


class _SlowArtifacts:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.in_put = threading.Event()
        self.allow_put = threading.Event()
        self.put_completed = threading.Event()
        self.other_write_succeeded = False
        self.error = None

    def put(self, content: str, *, kind: str = "") -> str:
        self.in_put.set()
        # While artifacts.put is executing, another thread tries to acquire SQLite write lock
        try:
            with closing(sqlite3.connect(str(self.db_path), timeout=0.1)) as con:
                con.execute("BEGIN IMMEDIATE")
                con.execute("UPDATE async_jobs SET updated_at=? WHERE 1=0", (time.time(),))
                con.commit()
            self.other_write_succeeded = True
        except Exception as exc:
            self.error = exc
        self.allow_put.wait(timeout=2.0)
        self.put_completed.set()
        return "art-123"

    def get(self, artifact_id: str, **kwargs):
        return {"success": True, "text": "{}"}


def test_n06_artifact_put_outside_sqlite_write_transaction(tmp_path: Path):
    db_path = tmp_path / "async_jobs.sqlite3"
    artifacts = _SlowArtifacts(db_path)
    artifacts.allow_put.set()

    config = {
        "server": {"state_dir": str(tmp_path)},
        "async_jobs": {"enabled": True, "max_pending": 10},
    }

    manager = AsyncJobManager(
        config=config,
        scheduler=_DummyScheduler(),
        artifacts=artifacts,
        executor=lambda action, payload: {"success": True, "result": "ok"},
    )
    try:
        sub = manager.submit("reason", {"prompt": "hello"})
        job_id = sub["job_id"]
        res = manager.wait(job_id, timeout_seconds=5.0)
        assert res["success"] is True
        assert artifacts.other_write_succeeded is True, f"SQLite write lock was blocked by artifacts.put: {artifacts.error}"
    finally:
        manager.close()


def test_n05_async_burst_worker_threads_bounded(tmp_path: Path):
    max_workers = 4
    config = {
        "server": {"state_dir": str(tmp_path)},
        "async_jobs": {
            "enabled": True,
            "max_pending": 64,
            "max_workers": max_workers,
        },
    }

    running_count = 0
    max_running_observed = 0
    lock = threading.Lock()

    def slow_exec(action, payload):
        nonlocal running_count, max_running_observed
        with lock:
            running_count += 1
            if running_count > max_running_observed:
                max_running_observed = running_count
        try:
            # Let workers group up to test concurrency limit
            time.sleep(0.2)
            return {"success": True}
        finally:
            with lock:
                running_count -= 1

    class SimpleArtifacts:
        def put(self, content, **kw):
            return "art-dummy"
        def get(self, art_id, **kw):
            return {"success": True, "text": "{}"}

    manager = AsyncJobManager(
        config=config,
        scheduler=_DummyScheduler(),
        artifacts=SimpleArtifacts(),
        executor=slow_exec,
    )
    try:
        job_ids = []
        for i in range(16):
            sub = manager.submit("reason", {"prompt": f"job-{i}"})
            if sub.get("job_id"):
                job_ids.append(sub["job_id"])

        for jid in job_ids:
            manager.wait(jid, timeout_seconds=5.0)

        assert max_running_observed <= max_workers, f"Observed {max_running_observed} concurrent workers > limit {max_workers}"
    finally:
        manager.close()
