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
        if isinstance(foreground_priority, bool) or not isinstance(foreground_priority, int):
            raise ValueError("foreground_priority must be an integer")
        self.foreground_priority = foreground_priority
        self._cond = threading.Condition()
        self._active = False
        self._foreground_waiters = 0

    @property
    def is_active(self) -> bool:
        with self._cond:
            return self._active

    @contextmanager
    def slot(self, priority: int, timeout: float = 120.0) -> Iterator[None]:
        if isinstance(priority, bool) or not isinstance(priority, int):
            raise ValueError("priority must be an integer")
        if isinstance(timeout, bool) or not isinstance(timeout, Real):
            raise ValueError("timeout must be a finite non-negative real number")
        try:
            timeout_seconds = float(timeout)
        except (OverflowError, TypeError, ValueError):
            raise ValueError("timeout must be a finite non-negative real number") from None
        if not math.isfinite(timeout_seconds) or timeout_seconds < 0:
            raise ValueError("timeout must be a finite non-negative real number")
        foreground = priority >= self.foreground_priority
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

    def try_acquire(self, priority: int = 0) -> bool:
        """Attempt non-blocking acquire of the gate slot. Return True if acquired."""
        if isinstance(priority, bool) or not isinstance(priority, int):
            raise ValueError("priority must be an integer")
        foreground = priority >= self.foreground_priority
        with self._cond:
            if self._active or (not foreground and self._foreground_waiters > 0):
                return False
            self._active = True
            return True

    def release(self) -> None:
        """Release the acquired gate slot and notify waiting threads."""
        with self._cond:
            self._active = False
            self._cond.notify_all()

    def foreground_waiters_count(self) -> int:
        """Return the number of foreground threads currently waiting for a slot."""
        with self._cond:
            return self._foreground_waiters

    def reset(self) -> None:
        """Reset the gate state and unblock any waiting threads."""
        with self._cond:
            self._active = False
            self._foreground_waiters = 0
            self._cond.notify_all()

    def status(self) -> dict[str, int | bool]:
        with self._cond:
            return {
                "active": self._active,
                "foreground_waiters": self._foreground_waiters,
                "foreground_priority": self.foreground_priority,
            }
