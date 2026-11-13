from __future__ import annotations

import threading

import pytest

from local_ai_hub.execution_pool import ExecutionPool


def test_execution_pool_enforces_configured_category_limits() -> None:
    pool = ExecutionPool(cpu_workers=1, io_workers=2, inference_workers=1)
    release = threading.Event()
    started = [threading.Event() for _ in range(5)]
    lock = threading.Lock()
    active = {"cpu": 0, "io": 0}
    peak = {"cpu": 0, "io": 0}

    def run(category: str, index: int) -> int:
        with lock:
            active[category] += 1
            peak[category] = max(peak[category], active[category])
            started[index].set()
        assert release.wait(5), "test worker release missing"
        with lock:
            active[category] -= 1
        return index

    futures = [
        pool.submit("cpu", run, "cpu", 0),
        pool.submit("cpu", run, "cpu", 1),
        pool.submit("io", run, "io", 2),
        pool.submit("io", run, "io", 3),
        pool.submit("io", run, "io", 4),
    ]
    try:
        assert started[0].wait(2)
        assert started[2].wait(2)
        assert started[3].wait(2)
        assert not started[1].wait(0.05)
        assert not started[4].wait(0.05)
        assert pool.category_limits == {"cpu": 1, "io": 2, "inference": 1}
    finally:
        release.set()

    assert [future.result(timeout=2) for future in futures] == list(range(5))
    assert peak == {"cpu": 1, "io": 2}
    pool.shutdown(wait=True)


def test_execution_pool_rejects_unknown_category() -> None:
    pool = ExecutionPool(cpu_workers=1, io_workers=1, inference_workers=1)
    try:
        with pytest.raises(ValueError, match="unknown execution category"):
            pool.submit("gpu", lambda: None)
    finally:
        pool.shutdown(wait=True)


def test_execution_pool_rejects_work_after_shutdown() -> None:
    pool = ExecutionPool(cpu_workers=1, io_workers=1, inference_workers=1)
    pool.shutdown(wait=True)
    with pytest.raises(RuntimeError, match="execution pool is closed"):
        pool.submit("cpu", lambda: None)
