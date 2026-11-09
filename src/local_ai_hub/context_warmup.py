"""Small optional warmup queue; foreground correctness never depends on this work."""
from __future__ import annotations

import logging
import queue
import threading
import time
from collections import OrderedDict
from typing import Callable


class ContextWarmup:
    _SUCCESS_COOLDOWN_SECONDS = 60.0
    _FAILURE_BACKOFF_SECONDS = 1.0
    _RECENT_LIMIT = 64

    def __init__(self) -> None:
        self._queue: queue.Queue[tuple[str, float, Callable[[], object]]] = queue.Queue(maxsize=4)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._recent: OrderedDict[str, float] = OrderedDict()
        self._retry_after: OrderedDict[str, float] = OrderedDict()
        self._pending: set[str] = set()
        self._worker: threading.Thread | None = None

    def submit(self, key: str, operation: Callable[[], object]) -> bool:
        with self._lock:
            now = time.monotonic()
            if (
                self._stop.is_set()
                or key in self._pending
                or now - self._recent.get(key, float("-inf")) < self._SUCCESS_COOLDOWN_SECONDS
                or now < self._retry_after.get(key, float("-inf"))
            ):
                return False
            try:
                self._queue.put_nowait((key, now, operation))
            except queue.Full:
                return False
            self._pending.add(key)
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._run, name="context-warmup", daemon=True)
                try:
                    self._worker.start()
                except RuntimeError:
                    self._stop.set()
                    self._discard_pending()
                    return False
            return True

    def _discard_pending(self) -> None:
        while True:
            try:
                key, _queued_at, _operation = self._queue.get_nowait()
                self._pending.discard(key)
                self._queue.task_done()
            except queue.Empty:
                break

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                key, queued_at, operation = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                succeeded = False
                if not self._stop.is_set() and time.monotonic() - queued_at <= 30:
                    result = operation()
                    succeeded = result is not None and not (
                        isinstance(result, dict) and result.get("success") is False
                    )
            except Exception as exc:
                logging.getLogger(__name__).debug("optional context warmup failed: %s", type(exc).__name__)
            finally:
                with self._lock:
                    self._pending.discard(key)
                    completed_at = time.monotonic()
                    if succeeded:
                        self._recent[key] = completed_at
                        self._recent.move_to_end(key)
                        self._retry_after.pop(key, None)
                        while len(self._recent) > self._RECENT_LIMIT:
                            self._recent.popitem(last=False)
                    else:
                        self._retry_after[key] = completed_at + self._FAILURE_BACKOFF_SECONDS
                        self._retry_after.move_to_end(key)
                        while len(self._retry_after) > self._RECENT_LIMIT:
                            self._retry_after.popitem(last=False)
                self._queue.task_done()

    def close(self) -> None:
        with self._lock:
            self._stop.set()
            self._discard_pending()
            worker = self._worker
        if worker is not None and worker.is_alive() and worker is not threading.current_thread():
            worker.join(timeout=1.0)
