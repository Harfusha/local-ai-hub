from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from local_ai_hub.async_jobs import AsyncJobManager
from tools.benchmark_surfaces import _queue_admission_error_reason


def test_nine_admission_probes_cancel_while_one_worker_is_in_flight(tmp_path: Path) -> None:
    worker_started = threading.Event()
    release_worker = threading.Event()

    def execute(_action: str, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("task_id") == "t02-inflight-sentinel":
            worker_started.set()
            release_worker.wait(timeout=5)
        return {"success": True}

    manager = AsyncJobManager(
        {"server": {"state_dir": str(tmp_path)}},
        scheduler=None,
        artifacts=None,
        executor=execute,
    )
    snapshots: list[dict[str, Any]] = []
    try:
        sentinel = manager.submit(
            "reason", {"task_id": "t02-inflight-sentinel"},
        )
        assert sentinel.get("success") is True
        sentinel_id = str(sentinel["job_id"])
        assert worker_started.wait(timeout=3)
        assert manager.status(sentinel_id).get("state") == "running"

        def probe(sample_id: str) -> dict[str, Any]:
            submitted = manager.submit(
                "reason", {"task_id": f"t02-{sample_id}"},
                dispatch_delay_seconds=30,
            )
            job_id = str(submitted.get("job_id", ""))
            before = manager.status(job_id) if job_id else {}
            cancelled = manager.cancel(job_id) if job_id else None
            after = manager.status(job_id) if job_id else {}
            counters = manager.stats()
            with manager._lock:
                in_flight = sum(thread.is_alive() for thread in manager._workers)
                delayed_ids = sorted(manager._delayed_dispatch)
            snapshot = {
                "sample_id": sample_id,
                "job_id": job_id,
                "submit_success": submitted.get("success"),
                "submit_state": submitted.get("state"),
                "before_state": before.get("state"),
                "cancel_success": cancelled.get("success") if isinstance(cancelled, dict) else None,
                "cancel_state": cancelled.get("state") if isinstance(cancelled, dict) else None,
                "after_state": after.get("state"),
                "after_attempts": after.get("attempts"),
                "after_cancel_requested": after.get("cancel_requested"),
                "counts": counters.get("counts", {}),
                "cancelled_counter": counters.get("cancelled"),
                "in_flight_workers": in_flight,
                "delayed_ids": delayed_ids,
            }
            assert submitted.get("success") is True, snapshot
            assert before.get("state") == "queued", snapshot
            assert _queue_admission_error_reason(submitted, cancelled) is None, snapshot
            assert after.get("state") == "cancelled", snapshot
            assert after.get("cancel_requested") is True, snapshot
            assert after.get("attempts") == 0, snapshot
            assert in_flight == 1, snapshot
            return snapshot

        completed = 0
        for level in (1, 2):
            for iteration in range(3):
                sample_ids = [
                    f"queue-admission:level-{level}:iteration-{iteration}:slot-{slot}"
                    for slot in range(level)
                ]
                with ThreadPoolExecutor(max_workers=level) as pool:
                    batch = list(pool.map(probe, sample_ids))
                snapshots.extend(batch)
                completed += level
                counters = manager.stats()
                with manager._lock:
                    in_flight = sum(thread.is_alive() for thread in manager._workers)
                    delayed_ids = sorted(manager._delayed_dispatch)
                batch_snapshot = {
                    "samples": batch,
                    "completed_probes": completed,
                    "counts": counters.get("counts", {}),
                    "cancelled_counter": counters.get("cancelled"),
                    "in_flight_workers": in_flight,
                    "delayed_ids": delayed_ids,
                }
                assert counters.get("counts", {}).get("queued", 0) == 0, batch_snapshot
                assert counters.get("counts", {}).get("running", 0) == 1, batch_snapshot
                assert counters.get("cancelled") == completed, batch_snapshot
                assert in_flight == 1, batch_snapshot
                assert delayed_ids == [], batch_snapshot

        assert len(snapshots) == 9
    finally:
        release_worker.set()
        manager.close()
