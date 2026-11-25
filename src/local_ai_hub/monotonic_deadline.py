from __future__ import annotations

import time
from typing import Any


class DeadlineExceededError(TimeoutError):
    """Raised when an operation exceeds its monotonic wall-clock deadline."""


class MonotonicDeadline:
    """Tracks a single monotonic wall-clock deadline across downstream call trees."""

    def __init__(self, timeout_seconds: float | None = None, *, deadline: float | None = None) -> None:
        if deadline is not None:
            if isinstance(deadline, bool) or not isinstance(deadline, (int, float)):
                raise ValueError("deadline must be a finite float")
            self._deadline = float(deadline)
        elif timeout_seconds is not None:
            if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
                raise ValueError("timeout_seconds must be a finite float")
            self._deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        else:
            self._deadline = float("inf")

    @classmethod
    def from_timeout(cls, timeout: float | None) -> MonotonicDeadline:
        return cls(timeout_seconds=timeout)

    @classmethod
    def from_deadline(cls, deadline: float | None) -> MonotonicDeadline:
        return cls(deadline=deadline)

    @property
    def deadline(self) -> float:
        return self._deadline

    @property
    def remaining_seconds(self) -> float:
        if self._deadline == float("inf"):
            return float("inf")
        return max(0.0, self._deadline - time.monotonic())

    def check(self, operation: str = "operation") -> None:
        """Raise DeadlineExceededError if the deadline has expired."""
        if self.is_expired:
            raise DeadlineExceededError(f"{operation} exceeded monotonic deadline")

    @property
    def is_expired(self) -> bool:
        return time.monotonic() >= self._deadline

    def remaining_or_default(self, default: float) -> float:
        """Return remaining seconds clamped by default."""
        rem = self.remaining_seconds
        if rem == float("inf"):
            return default
        return min(rem, default)
