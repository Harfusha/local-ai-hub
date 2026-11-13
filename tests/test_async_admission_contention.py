from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

from local_ai_hub.async_jobs import AsyncJobManager


class _Artifacts:
    def put(self, _content: str, *, kind: str) -> str:
        return "contention-result"

    def get(self, _artifact_id: str, *, offset: int = 0, max_chars: int = 256) -> dict[str, object]:
        return {"success": True, "text": "{}"}


def test_concurrent_submissions_respect_durable_capacity_and_worker_cap(tmp_path):
    submitter_count = 8
    capacity = 3
    worker_cap = 2
    start = threading.Barrier(submitter_count)
    release_workers = threading.Event()
    workers_started = threading.Condition()
    active_workers = 0
    max_active_workers = 0

    def execute(_action: str, _payload: dict[str, object]) -> dict[str, object]:
        nonlocal active_workers, max_active_workers
        with workers_started:
            active_workers += 1
            max_active_workers = max(max_active_workers, active_workers)
            workers_started.notify_all()
        try:
            assert release_workers.wait(5)
            return {"success": True, "text": "done"}
        finally:
            with workers_started:
                active_workers -= 1
                workers_started.notify_all()

    manager = AsyncJobManager(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "async_jobs": {
                "max_pending": capacity,
                "max_workers": worker_cap,
                "max_dispatch_workers": worker_cap,
            },
        },
        scheduler=object(),
        artifacts=_Artifacts(),
        executor=execute,
    )
    manager._resource_admission = lambda: {"state": "accepted"}

    def submit(index: int) -> dict[str, object]:
        start.wait(timeout=5)
        return manager.submit("reason", {"task": f"contention-{index}"})

    try:
        with ThreadPoolExecutor(max_workers=submitter_count) as submitters:
            results = list(submitters.map(submit, range(submitter_count)))

        accepted = [result for result in results if result.get("success") is True]
        rejected = [result for result in results if result.get("state") == "rejected"]
        assert len(accepted) == capacity
        assert len(rejected) == submitter_count - capacity
        assert all(result.get("retryable") is True for result in rejected)

        with workers_started:
            assert workers_started.wait_for(lambda: active_workers == worker_cap, timeout=3)
            assert max_active_workers <= worker_cap

        with closing(manager._connect()) as con:
            durable_active = int(con.execute(
                "SELECT COUNT(*) FROM async_jobs WHERE state IN ('queued', 'running')"
            ).fetchone()[0])
        assert durable_active == capacity
    finally:
        release_workers.set()
        manager.close()
