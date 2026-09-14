from __future__ import annotations

import time
import threading
from contextlib import contextmanager
from typing import Iterator


class CooperativePriorityGate:
    """Single-resource gate that lets foreground work cut in between bounded batches.

    CPU transformer inference cannot safely be interrupted mid-forward-pass. Callers
    therefore acquire this gate per small batch. Low-priority preprocessing keeps
    making progress while GPU work runs, but a waiting interactive retrieval request
    is selected before the next background batch.
    """

    def __init__(self, foreground_priority: int = 3):
        self.foreground_priority = int(foreground_priority)
        self._cond = threading.Condition()
        self._active = False
        self._foreground_waiters = 0

    @contextmanager
    def slot(self, priority: int, timeout: float = 120.0) -> Iterator[None]:
        foreground = int(priority or 0) >= self.foreground_priority
        deadline = time.monotonic() + timeout if timeout else None
        with self._cond:
            if foreground:
                self._foreground_waiters += 1
            try:
                while self._active or (not foreground and self._foreground_waiters > 0):
                    remaining = max(0.0, deadline - time.monotonic()) if deadline else 30.0
                    if remaining <= 0:
                        raise TimeoutError("timed out waiting for cooperative priority gate")
                    self._cond.wait(timeout=remaining)
                self._active = True
            finally:
                if foreground:
                    self._foreground_waiters = max(0, self._foreground_waiters - 1)
        try:
            yield
        finally:
            with self._cond:
                self._active = False
                self._cond.notify_all()

    def status(self) -> dict[str, int | bool]:
        with self._cond:
            return {"active": self._active, "foreground_waiters": self._foreground_waiters}
