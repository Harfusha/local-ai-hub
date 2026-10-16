from __future__ import annotations

import math
import threading
import time
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
        if isinstance(foreground_priority, bool):
            fp = 3
        else:
            try:
                fp = int(foreground_priority)
            except (TypeError, ValueError, OverflowError):
                fp = 3
        self.foreground_priority = fp
        self._cond = threading.Condition()
        self._active = False
        self._foreground_waiters = 0

    @contextmanager
    def slot(self, priority: int = 0, timeout: float = 120.0) -> Iterator[None]:
        if isinstance(priority, bool) or priority is None:
            p_val = 0
        else:
            try:
                p_val = int(priority)
            except (TypeError, ValueError, OverflowError):
                p_val = 0
        foreground = p_val >= self.foreground_priority

        if isinstance(timeout, bool):
            val_timeout = 120.0
        else:
            try:
                val_timeout = float(timeout) if timeout is not None else None
                if val_timeout is not None and (not math.isfinite(val_timeout) or val_timeout < 0):
                    val_timeout = 0.0
            except (TypeError, ValueError):
                val_timeout = 120.0

        deadline = time.monotonic() + val_timeout if val_timeout is not None else None
        with self._cond:
            if foreground:
                self._foreground_waiters += 1
            try:
                while self._active or (not foreground and self._foreground_waiters > 0):
                    remaining = max(0.0, deadline - time.monotonic()) if deadline is not None else 30.0
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

    def try_acquire(self, priority: int = 0) -> bool:
        """Attempt non-blocking acquire of the gate slot. Return True if acquired."""
        if isinstance(priority, bool) or priority is None:
            p_val = 0
        else:
            try:
                p_val = int(priority)
            except (TypeError, ValueError, OverflowError):
                p_val = 0
        foreground = p_val >= self.foreground_priority
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

    def is_active(self) -> bool:
        """Return True if the gate currently has an active tenant."""
        with self._cond:
            return self._active

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
            return {"active": self._active, "foreground_waiters": self._foreground_waiters}
