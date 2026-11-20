from __future__ import annotations

import sys
import threading
import time
from contextlib import closing
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from local_ai_hub.async_jobs import AsyncJobManager


class _DummyScheduler:
    max_parallel = 2


class _DummyArtifacts:
    def __init__(self):
        self._store = {}

    def put(self, content: str, kind: str = "async-job") -> str:
        aid = f"art-{len(self._store)+1}"
        self._store[aid] = content
        return aid

    def get(self, artifact_id: str, offset: int = 0, max_chars: int = 256) -> dict:
        if artifact_id in self._store:
            return {"success": True, "data": self._store[artifact_id]}
        return {"success": False}


def test_100_parallel_synthetic_jobs_strict_worker_bounds(tmp_path: Path):
    max_w = 4
    max_disp = 2
    max_pend = 150

    peak_workers = 0
    worker_lock = threading.Lock()

    def slow_executor(action: str, payload: dict) -> dict:
        nonlocal peak_workers
        with worker_lock:
            current = len(mgr._workers)
            if current > peak_workers:
                peak_workers = current
        time.sleep(0.005)
        return {"success": True, "action": action}

    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "async_jobs": {
            "max_workers": max_w,
            "max_dispatch_workers": max_disp,
            "max_pending": max_pend,
            "wait_max_seconds": 30,
        },
    }

    mgr = AsyncJobManager(cfg, _DummyScheduler(), _DummyArtifacts(), slow_executor)
    job_ids = []

    try:
        # Submit 100 unique jobs rapidly
        for i in range(100):
            res = mgr.submit("compress", {"task": f"job_{i}"})
            assert res["success"] is True
            job_ids.append(res["job_id"])

        # Wait for all jobs to complete
        start = time.time()
        while time.time() - start < 30.0:
            with closing(mgr._connect()) as con:
                done_count = con.execute("SELECT COUNT(*) FROM async_jobs WHERE state='done'").fetchone()[0]
                if done_count == 100:
                    break
            time.sleep(0.05)

        with closing(mgr._connect()) as con:
            final_done = con.execute("SELECT COUNT(*) FROM async_jobs WHERE state='done'").fetchone()[0]
        assert final_done == 100

        # Assert worker concurrency never exceeded max_workers
        assert peak_workers <= max_w
        assert peak_workers > 0
    finally:
        mgr.close()


def test_queue_limit_backpressure(tmp_path: Path):
    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "async_jobs": {
            "max_workers": 1,
            "max_pending": 5,
        },
    }

    artifacts = _DummyArtifacts()
    mgr = AsyncJobManager(cfg, _DummyScheduler(), artifacts, lambda a, p: {"success": True})
    # Keep the test focused on admission. Wall-clock timers may expire while
    # the rest of the suite is under load and make the queue drain mid-loop.
    mgr._dispatch = lambda _job_id: None
    try:
        accepted = 0
        rejected = 0
        for i in range(10):
            res = mgr.submit("compress", {"task": f"task_{i}"}, dispatch_delay_seconds=30.0)
            if res["success"]:
                accepted += 1
            else:
                assert res["error"] == "async job queue limit reached"
                assert res["retryable"] is True
                rejected += 1

        assert accepted == 5
        assert rejected == 5
    finally:
        mgr.close()


def test_priority_and_starvation_aging_contract(tmp_path: Path):
    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "async_jobs": {
            "max_workers": 1,
            "max_pending": 50,
        },
    }

    dispatched_order = []

    def track_executor(action: str, payload: dict) -> dict:
        dispatched_order.append(payload.get("task"))
        return {"success": True}

    mgr = AsyncJobManager(cfg, _DummyScheduler(), _DummyArtifacts(), track_executor)
    try:
        now = time.time()
        # Submit with dispatch_delay_seconds so they don't dispatch immediately
        res_low = mgr.submit("compress", {"task": "low_aged", "priority": 1}, dispatch_delay_seconds=30.0)
        res_med = mgr.submit("compress", {"task": "med_new", "priority": 3}, dispatch_delay_seconds=30.0)

        assert res_low["success"] is True
        assert res_med["success"] is True

        # Manually adjust created_at for low_aged in sqlite to simulate 150s age (aging bonus = +5 => effective priority 6)
        # and clear dispatch_not_before so both are immediately eligible
        with closing(mgr._connect()) as con:
            con.execute("UPDATE async_jobs SET created_at=?, dispatch_not_before=0, state='queued' WHERE job_id=?", (now - 150.0, res_low["job_id"]))
            con.execute("UPDATE async_jobs SET created_at=?, dispatch_not_before=0, state='queued' WHERE job_id=?", (now, res_med["job_id"]))
            con.commit()

        # Clear any delayed timers
        with mgr._lock:
            for timer in mgr._delayed_dispatch.values():
                timer.cancel()
            mgr._delayed_dispatch.clear()

        # Call _dispatch_next_queued to see which is selected
        # We need low_aged (effective priority 1 + 5 = 6) to be selected BEFORE med_new (priority 3)
        mgr._dispatch_next_queued()

        # Wait briefly for execution
        start = time.time()
        while not dispatched_order and time.time() - start < 5.0:
            time.sleep(0.02)

        # A fast worker may also finish med_new before this assertion;
        # the priority contract is about which job is dispatched first.
        assert dispatched_order and dispatched_order[0] == "low_aged", (
            f"Expected low_aged first due to starvation aging, got {dispatched_order}"
        )
    finally:
        mgr.close()


def test_durability_and_restart_without_task_loss(tmp_path: Path):
    state_dir = tmp_path / "state"
    cfg = {
        "server": {"state_dir": str(state_dir)},
        "async_jobs": {
            "max_workers": 1,
            "max_pending": 10,
        },
    }

    artifacts = _DummyArtifacts()

    # Manager 1 submits jobs with a delay
    mgr1 = AsyncJobManager(cfg, _DummyScheduler(), artifacts, lambda a, p: {"success": True})
    job_ids = []
    # Submit 3 jobs
    for i in range(3):
        res = mgr1.submit("compress", {"task": f"t_{i}"}, dispatch_delay_seconds=60.0)
        assert res["success"] is True
        job_ids.append(res["job_id"])

    # Simulate abrupt process exit (without graceful close which marks queued->cancelled)
    mgr1._shutdown.set()
    with mgr1._lock:
        for timer in mgr1._delayed_dispatch.values():
            timer.cancel()

    # Manager 2 opens the same state_dir after manager 1 process ended
    executed = []
    def exec2(action: str, payload: dict) -> dict:
        executed.append(payload.get("task"))
        return {"success": True}

    mgr2 = AsyncJobManager(cfg, _DummyScheduler(), artifacts, exec2)
    try:
        # Verify all jobs are present in sqlite in queued state
        for jid in job_ids:
            st = mgr2.status(jid)
            assert st["success"] is True
            assert st["state"] == "queued"

        # Clear dispatch_not_before so tick/dispatch can run them
        with closing(mgr2._connect()) as con:
            con.execute("UPDATE async_jobs SET dispatch_not_before=0 WHERE state='queued'")
            con.commit()

        # Run tick
        mgr2.tick()

        # Wait for all to finish
        start = time.time()
        while len(executed) < 3 and time.time() - start < 5.0:
            time.sleep(0.05)

        assert sorted(executed) == ["t_0", "t_1", "t_2"]
    finally:
        mgr2.close()
