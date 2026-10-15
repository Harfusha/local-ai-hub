from __future__ import annotations

import math
import threading
import time
from contextlib import contextmanager
from numbers import Real
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
        if isinstance(timeout, bool) or not isinstance(timeout, Real):
            raise ValueError("timeout must be a finite non-negative real number")
        try:
            timeout_seconds = float(timeout)
        except (OverflowError, TypeError, ValueError):
            raise ValueError("timeout must be a finite non-negative real number") from None
        if not math.isfinite(timeout_seconds) or timeout_seconds < 0:
            raise ValueError("timeout must be a finite non-negative real number")
        foreground = int(priority or 0) >= self.foreground_priority
        deadline = time.monotonic() + timeout_seconds
        with self._cond:
            if foreground:
                self._foreground_waiters += 1
            try:
                while self._active or (not foreground and self._foreground_waiters > 0):
                    remaining = max(0.0, deadline - time.monotonic())
                    if remaining <= 0:
                        raise TimeoutError("timed out waiting for cooperative priority gate")
                    self._cond.wait(timeout=min(remaining, 30.0))
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
