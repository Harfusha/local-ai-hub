"""Race-safe idle lifecycle for an optional shared Laya runtime session.

The controller owns no thread. The existing scheduler maintenance loop calls
``poll_idle_unload``; a provider adapter must supply loading and an explicit
successful close callback before any runtime session can be managed.
"""

from __future__ import annotations

import math
import threading
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator

DEFAULT_IDLE_UNLOAD_SECONDS = 600.0
MAX_IDLE_UNLOAD_SECONDS = 86_400.0


def validate_idle_unload_seconds(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("laya.idle_unload_seconds must be a number from 0 through 86400")
    try:
        numeric = float(value)
    except OverflowError as exc:
        raise ValueError("laya.idle_unload_seconds must be a number from 0 through 86400") from exc
    if not math.isfinite(numeric) or not 0 <= numeric <= MAX_IDLE_UNLOAD_SECONDS:
        raise ValueError("laya.idle_unload_seconds must be a number from 0 through 86400")
    return numeric


class LayaSessionLifecycle:
    """Manage one shared provider session, while leaving loading/inference to adapters."""

    def __init__(
        self,
        idle_unload_seconds: float = DEFAULT_IDLE_UNLOAD_SECONDS,
        *,
        close_session: Callable[[Any], Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.idle_unload_seconds = validate_idle_unload_seconds(idle_unload_seconds)
        self._close_session = close_session
        self._clock = clock
        self._condition = threading.Condition(threading.RLock())
        self._session: Any | None = None
        self._inflight = 0
        self._loading = False
        self._load_generation = 0
        self._failed_load_generation: int | None = None
        self._closing = False
        self._shutdown = False
        self._last_inference_completed: float | None = None
        self._close_failed_since_completion = False
        self._last_close_error: str | None = None
        self._unload_count = 0

    @property
    def status(self) -> dict[str, Any]:
        with self._condition:
            return {
                "available": self._session is not None,
                "provider_close_configured": self._close_session is not None,
                "idle_unload_seconds": self.idle_unload_seconds,
                "inflight": self._inflight,
                "loading": self._loading,
                "closing": self._closing,
                "shutdown": self._shutdown,
                "unload_count": self._unload_count,
                "last_close_error": self._last_close_error,
                "runtime_verification": "NOT_VERIFIED",
            }

    def bind_close_session(self, close_session: Callable[[Any], Any]) -> None:
        """Bind the shared provider's close callback once before its first load."""
        if not callable(close_session):
            raise TypeError("provider close callback must be callable")
        with self._condition:
            if self._shutdown:
                raise RuntimeError("Laya session lifecycle is shutting down")
            if self._close_session is close_session:
                return
            if self._close_session is not None:
                raise RuntimeError("Laya provider close callback is already bound")
            if self._loading or self._closing or self._session is not None or self._inflight:
                raise RuntimeError("Laya provider close callback must be bound before the first session load")
            self._close_session = close_session
            self._condition.notify_all()

    @contextmanager
    def inference_session(self, load_session: Callable[[], Any]) -> Iterator[Any]:
        """Load once, share safely, and timestamp idleness after inference completes."""
        session = self._acquire(load_session)
        try:
            yield session
        finally:
            with self._condition:
                self._inflight -= 1
                try:
                    completed_at = self._clock()
                except Exception:
                    completed_at = None
                if isinstance(completed_at, bool) or not isinstance(
                    completed_at, (int, float)
                ):
                    # Keep the session loaded when the clock cannot establish
                    # a trustworthy idle boundary. A later successful request
                    # can establish a fresh completion timestamp.
                    self._last_inference_completed = None
                else:
                    try:
                        completed_at = float(completed_at)
                    except OverflowError:
                        self._last_inference_completed = None
                    else:
                        self._last_inference_completed = (
                            completed_at if math.isfinite(completed_at) else None
                        )
                self._close_failed_since_completion = False
                self._last_close_error = None
                self._condition.notify_all()

    def _acquire(self, load_session: Callable[[], Any]) -> Any:
        waited_for_generation: int | None = None
        while True:
            with self._condition:
                while self._closing or self._loading:
                    if self._loading and waited_for_generation is None:
                        waited_for_generation = self._load_generation
                    self._condition.wait()
                    if (
                        waited_for_generation is not None
                        and self._failed_load_generation == waited_for_generation
                    ):
                        raise RuntimeError(
                            "Laya provider session load failed for concurrent request"
                        )
                if self._shutdown:
                    raise RuntimeError("Laya session lifecycle is shutting down")
                if self._session is not None:
                    self._inflight += 1
                    return self._session
                self._loading = True
                self._load_generation += 1
                load_generation = self._load_generation
            try:
                session = load_session()
                if session is None:
                    raise RuntimeError("Laya provider returned no session")
            except BaseException:
                with self._condition:
                    self._loading = False
                    self._failed_load_generation = load_generation
                    self._condition.notify_all()
                raise
            with self._condition:
                self._loading = False
                if self._shutdown:
                    # Keep ownership visible to shutdown; do not race an
                    # unclaimed close against a successful shutdown result.
                    self._session = session
                    self._condition.notify_all()
                    raise RuntimeError("Laya session lifecycle is shutting down")
                else:
                    self._session = session
                    self._inflight += 1
                    self._condition.notify_all()
                    return session

    def poll_idle_unload(self, now: float | None = None) -> str:
        """Claim and close an idle session; safe to call from the existing scheduler loop."""
        current = self._clock() if now is None else now
        if isinstance(current, bool) or not isinstance(current, (int, float)):
            raise ValueError("now must be a finite monotonic timestamp")
        try:
            current = float(current)
        except OverflowError as exc:
            raise ValueError("now must be a finite monotonic timestamp") from exc
        if not math.isfinite(current):
            raise ValueError("now must be a finite monotonic timestamp")
        with self._condition:
            if self._shutdown:
                return "shutdown"
            if self.idle_unload_seconds == 0:
                return "disabled"
            if self._session is None:
                return "no_session"
            if self._loading or self._closing or self._inflight:
                return "busy"
            if self._last_inference_completed is None:
                return "not_idle"
            if current - self._last_inference_completed < self.idle_unload_seconds:
                return "not_idle"
            if self._close_failed_since_completion:
                return "close_failed"
            if self._close_session is None:
                self._last_close_error = "provider close callback unavailable"
                self._close_failed_since_completion = True
                return "close_unconfirmed"
            session = self._session
            self._closing = True
        try:
            closed = self._close_session(session)
            if closed is not True:
                raise RuntimeError("provider did not confirm session release")
        except Exception as exc:
            with self._condition:
                self._closing = False
                self._close_failed_since_completion = True
                self._last_close_error = type(exc).__name__
                self._condition.notify_all()
            return "close_failed"
        with self._condition:
            if self._session is session:
                self._session = None
                self._unload_count += 1
            self._closing = False
            self._last_close_error = None
            self._condition.notify_all()
        return "unloaded"

    def shutdown(self, timeout_seconds: float = 5.0) -> bool:
        """Stop new admissions and close only after in-flight calls have ended."""
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not math.isfinite(float(timeout_seconds)) or timeout_seconds < 0:
            raise ValueError("timeout_seconds must be finite and non-negative")
        deadline = time.monotonic() + float(timeout_seconds)
        with self._condition:
            self._shutdown = True
            while self._loading or self._closing or self._inflight:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            session = self._session
            if session is None:
                return True
            if self._close_session is None:
                self._last_close_error = "provider close callback unavailable"
                return False
            self._closing = True
        try:
            closed = self._close_session(session)
            if closed is not True:
                raise RuntimeError("provider did not confirm session release")
        except Exception as exc:
            with self._condition:
                self._closing = False
                self._last_close_error = type(exc).__name__
                self._condition.notify_all()
            return False
        with self._condition:
            if self._session is session:
                self._session = None
            self._closing = False
            self._condition.notify_all()
        return True

    def close(self, timeout: float = 5.0) -> None:
        if not self.shutdown(timeout_seconds=timeout):
            raise TimeoutError("Laya provider session did not close cleanly")
