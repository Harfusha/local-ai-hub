"""Shared bounded executors for independent execution categories."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import threading
from typing import Any, Callable


class ExecutionPool:
    """Own fixed-size CPU, IO, and inference executors for one Hub instance."""

    def __init__(self, *, cpu_workers: int, io_workers: int, inference_workers: int):
        limits = {
            "cpu": cpu_workers,
            "io": io_workers,
            "inference": inference_workers,
        }
        for category, workers in limits.items():
            if type(workers) is not int or workers < 1:
                raise ValueError(f"{category}_workers must be a positive integer")
        self._limits = limits
        self._lock = threading.Lock()
        self._closed = False
        self._executors = {
            category: ThreadPoolExecutor(max_workers=workers, thread_name_prefix=f"local-ai-{category}")
            for category, workers in limits.items()
        }

    @property
    def category_limits(self) -> dict[str, int]:
        return dict(self._limits)

    def submit(self, category: str, fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Future[Any]:
        executor = self._executors.get(category)
        if executor is None:
            raise ValueError(f"unknown execution category: {category}")
        with self._lock:
            if self._closed:
                raise RuntimeError("execution pool is closed")
            return executor.submit(fn, *args, **kwargs)

    def shutdown(self, *, wait: bool = True, cancel_futures: bool = False) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        for executor in self._executors.values():
            executor.shutdown(wait=wait, cancel_futures=cancel_futures)

    def close(self) -> None:
        self.shutdown(wait=False, cancel_futures=True)
