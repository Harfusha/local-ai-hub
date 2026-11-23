from __future__ import annotations

import threading
import time
from typing import Any, Callable


class _LinkedCancelEvent:
    """Combine a caller event with an async job callback across threads."""

    def __init__(self, event: threading.Event, parent_stop: Any) -> None:
        self._event = event
        self._parent_stop = parent_stop
        self._lock = threading.Lock()

    def set(self) -> None:
        self._event.set()

    def is_set(self) -> bool:
        if self._event.is_set():
            return True
        with self._lock:
            if self._event.is_set():
                return True
            try:
                if self._parent_stop():
                    self._event.set()
            except Exception:
                self._event.set()
        return self._event.is_set()

    def wait(self, timeout: float | None = None) -> bool:
        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        while not self.is_set():
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                return False
            self._event.wait(0.05 if remaining is None else min(0.05, remaining))
        return True


# Public alias for external and typed consumption
LinkedCancelEvent = _LinkedCancelEvent


def create_linked_cancel_event(
    event: threading.Event | None = None,
    parent_stop: Callable[[], bool] | Any | None = None,
) -> threading.Event | _LinkedCancelEvent:
    """Create or link a cancellation event with an optional parent stop check."""
    base_event = event if event is not None else threading.Event()
    if parent_stop is not None:
        return _LinkedCancelEvent(base_event, parent_stop)
    return base_event


def resolve_cancel_event(
    cancel_event: threading.Event | None = None,
    parent_stop: Callable[[], bool] | Any | None = None,
) -> threading.Event | _LinkedCancelEvent | None:
    """Resolve an effective cancellation event, linking a parent stop callback if provided."""
    if parent_stop is None:
        return cancel_event
    base = cancel_event if cancel_event is not None else threading.Event()
    return _LinkedCancelEvent(base, parent_stop)


def is_cancel_requested(cancel_event: Any | None) -> bool:
    """Check if cancellation has been requested on an event, callback, or token."""
    if cancel_event is None:
        return False
    is_set_fn = getattr(cancel_event, "is_set", None)
    if callable(is_set_fn):
        return bool(is_set_fn())
    if callable(cancel_event):
        try:
            return bool(cancel_event())
        except Exception:
            return True
    return False


__all__ = [
    "_LinkedCancelEvent",
    "LinkedCancelEvent",
    "create_linked_cancel_event",
    "resolve_cancel_event",
    "is_cancel_requested",
]
