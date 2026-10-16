"""Bounded status probes without worker creation on the HTTP request thread."""
from concurrent.futures import Executor, Future, InvalidStateError, ThreadPoolExecutor
from functools import partial
import math
import queue
import threading
from typing import Any
import weakref


def _safe_int(val: Any, default: int, min_val: int | None = None, max_val: int | None = None) -> int:
    if isinstance(val, bool) or val is None:
        return default
    try:
        if isinstance(val, float) and not math.isfinite(val):
            return default
        res = int(val)
    except (ValueError, TypeError, OverflowError):
        return default
    if min_val is not None and res < min_val:
        return min_val
    if max_val is not None and res > max_val:
        return max_val
    return res


def _release(future, pending, lock, slots):
    with lock:
        pending.discard(future)
    slots.release()


def _stop(lock, closed, pending, cancel, cancel_futures):
    with lock:
        closed.set()
        if cancel_futures:
            cancel.set()
        futures = tuple(pending) if cancel_futures else ()
    for future in futures:
        future.cancel()


def _execute(future, callback, args, kwargs, gate):
    with gate:
        if future.done() or not future.set_running_or_notify_cancel():
            return
    try:
        result = callback(*args, **kwargs)
    except BaseException as exc:
        future.set_exception(exc)
    else:
        future.set_result(result)


def _fail_pending(target, error, gate):
    with gate:
        if target.done() or target.running():
            return
        try:
            target.set_exception(error)
        except InvalidStateError:
            if not target.cancelled():
                raise


def _forward_failure(target, gate, completed):
    if completed.cancelled():
        target.cancel()
    elif not target.done():
        error = completed.exception()
        if error is not None:
            _fail_pending(target, error, gate)


def _dispatch(work, pool, closed, cancel):
    try:
        while not (closed.is_set() and work.empty()):
            try:
                future, callback, args, kwargs, gate = work.get(timeout=0.05)
            except queue.Empty:
                continue
            if future.cancelled():
                continue
            try:
                submitted = pool.submit(_execute, future, callback, args, kwargs, gate)
            except BaseException as exc:
                _fail_pending(future, exc, gate)
            else:
                submitted.add_done_callback(partial(_forward_failure, future, gate))
    finally:
        pool.shutdown(wait=False, cancel_futures=cancel.is_set())


class StatusDependencyExecutor(Executor):
    """At most capacity accepted probes; submission never starts pool workers."""

    def __init__(self, *, max_workers: int, capacity: int):
        if isinstance(max_workers, bool) or not isinstance(max_workers, int) or max_workers < 1:
            raise ValueError("status executor max_workers must be positive")
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
            raise ValueError("status executor capacity must be positive")
        self._max_workers = int(max_workers)
        self._capacity = int(capacity)
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="local-ai-status")
        self._work = queue.Queue(maxsize=capacity)
        self._slots = threading.BoundedSemaphore(capacity)
        self._lock = threading.Lock()
        self._pending = set()
        self._closed = threading.Event()
        self._cancel = threading.Event()
        self._thread = threading.Thread(
            target=_dispatch,
            args=(self._work, self._pool, self._closed, self._cancel),
            name="local-ai-status-dispatch", daemon=True,
        )
        self._thread.start()
        self._finalizer = weakref.finalize(
            self, _stop, self._lock, self._closed, self._pending, self._cancel, True,
        )

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def max_workers(self) -> int:
        return self._max_workers

    @property
    def is_shutdown(self) -> bool:
        return self._closed.is_set()

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    def submit(self, fn, /, *args, **kwargs):
        if not callable(fn):
            raise TypeError("fn must be callable")
        with self._lock:
            if self._closed.is_set():
                raise RuntimeError("status executor is shut down")
            if not self._slots.acquire(blocking=False):
                raise RuntimeError("status executor capacity exhausted")
            future = Future()
            self._pending.add(future)
            try:
                self._work.put_nowait((future, fn, args, kwargs, threading.Lock()))
            except queue.Full:
                self._pending.remove(future)
                self._slots.release()
                raise RuntimeError("status executor queue full") from None
        # A completed/cancelled Future invokes callbacks inline: no state lock here.
        future.add_done_callback(partial(_release, pending=self._pending, lock=self._lock, slots=self._slots))
        return future

    def shutdown(self, wait=True, *, cancel_futures=False):
        _stop(self._lock, self._closed, self._pending, self._cancel, cancel_futures)
        self._finalizer.detach()
        if wait:
            if self._thread.is_alive():
                self._thread.join()
            self._pool.shutdown(wait=True, cancel_futures=cancel_futures)

