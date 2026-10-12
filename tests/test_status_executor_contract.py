import gc
import threading
import weakref

import pytest

from local_ai_hub import app as app_module
from local_ai_hub.status_executor import StatusDependencyExecutor


def test_status_executor_capacity_is_bounded_and_returns_after_release():
    entered, release, completed = threading.Event(), threading.Event(), threading.Event()
    executor = StatusDependencyExecutor(max_workers=1, capacity=1)

    def blocked():
        entered.set()
        assert release.wait(2)
        return "done"

    try:
        future = executor.submit(blocked)
        future.add_done_callback(lambda _: completed.set())
        assert entered.wait(1)
        with pytest.raises(RuntimeError, match="capacity exhausted"):
            executor.submit(lambda: None)
        release.set()
        assert future.result(1) == "done"
        assert completed.wait(1)
        assert executor.submit(lambda: "next").result(1) == "next"
    finally:
        release.set()
        executor.shutdown(wait=True, cancel_futures=True)


def test_unused_status_executor_does_not_keep_dispatcher_alive():
    executor = StatusDependencyExecutor(max_workers=1, capacity=1)
    dispatcher, reference = executor._thread, weakref.ref(executor)
    del executor
    gc.collect()
    dispatcher.join(1)
    assert reference() is None
    assert not dispatcher.is_alive()


def test_async_status_submission_failure_releases_entry_and_slot(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    def cannot_start(_pool):
        raise RuntimeError("injected worker startup failure")

    monkeypatch.setattr(ThreadPoolExecutor, "_adjust_thread_count", cannot_start)
    executor = StatusDependencyExecutor(max_workers=1, capacity=1)
    lock, inflight = threading.Lock(), {}
    slots = threading.BoundedSemaphore(1)
    diagnostic, called = {}, threading.Event()
    try:
        result = app_module._status_dependency(
            called.set, "fallback", key="failure", lock=lock, inflight=inflight,
            slots=slots, executor=executor, diagnostic=diagnostic,
        )
        assert result == ("fallback", False)
        assert diagnostic == {"reason": "probe_error", "error_type": "RuntimeError"}
        assert not inflight
        assert slots.acquire(blocking=False)
        slots.release()
        assert not called.is_set()
    finally:
        executor.shutdown(wait=True, cancel_futures=True)


def test_zero_capacity_is_rejected_before_starting_dispatcher():
    with pytest.raises(ValueError, match="positive"):
        StatusDependencyExecutor(max_workers=1, capacity=0)
