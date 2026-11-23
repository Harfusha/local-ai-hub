"""Transcription registry and request disconnect monitoring for HTTP server."""

from __future__ import annotations

import select
import socket
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

__all__ = [
    "ActiveTranscriptionRegistry",
    "_ActiveTranscriptionRegistry",
    "invoke_cancellable_request",
    "_invoke_cancellable_request",
    "is_client_disconnect",
    "_is_client_disconnect",
    "start_disconnect_monitor",
    "_start_disconnect_monitor",
]


class ActiveTranscriptionRegistry:
    """Track synchronous Whisper calls and cancel them before gaming release."""

    def __init__(self) -> None:
        self._condition = threading.Condition(threading.RLock())
        self._active: dict[str, threading.Event] = {}
        self._results: dict[str, dict[str, Any]] = {}
        self._waiting: set[str] = set()
        self._gaming = False
        self._drained_callbacks: list[Callable[[], Any]] = []

    def enter_gaming(self) -> None:
        with self._condition:
            self._gaming = True
            # Track before signaling: a cooperative worker may finish before
            # cancel_and_wait takes its own active snapshot.
            self._waiting.update(self._active)
            for event in self._active.values():
                event.set()
            self._condition.notify_all()

    def enter_active(self) -> None:
        with self._condition:
            self._gaming = False

    def begin(self) -> tuple[str, threading.Event]:
        token = uuid.uuid4().hex
        event = threading.Event()
        with self._condition:
            if self._gaming:
                self._waiting.add(token)
                event.set()
            self._active[token] = event
            self._condition.notify_all()
        return token, event

    def finish(self, token: str, result: Any) -> None:
        callbacks: list[Callable[[], Any]] = []
        with self._condition:
            normalized = result if isinstance(result, dict) else {}
            if token in self._waiting:
                self._results[token] = {
                    "cancelled": normalized.get("reason") == "cancelled" or normalized.get("cancelled") is True,
                    "success": normalized.get("success") is True,
                }
            self._active.pop(token, None)
            if not self._active:
                callbacks, self._drained_callbacks = self._drained_callbacks, []
                self._condition.notify_all()
        for callback in callbacks:
            try:
                callback()
            except Exception:
                pass

    def cancel_and_wait(self, timeout_seconds: float) -> dict[str, Any]:
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        with self._condition:
            active_at_start = tuple(self._active)
            self._waiting.update(active_at_start)
            for event in self._active.values():
                event.set()
            while self._active and time.monotonic() < deadline:
                self._condition.wait(max(0.0, deadline - time.monotonic()))
            pending = len(self._active)
            tracked = set(active_at_start) | set(self._waiting) | set(self._results)
            results = [self._results.pop(token, {}) for token in tracked]
            self._waiting.difference_update(tracked)
        if pending:
            return {"state": "timed_out", "inference_active": True, "active": pending}
        if not tracked:
            return {"state": "not_applicable", "inference_active": False, "active": 0}
        cancelled = all(item.get("cancelled") is True for item in results)
        return {
            "state": "cancelled" if cancelled else "completed",
            "inference_active": False,
            "active": 0,
            "cancelled": cancelled,
        }

    def when_drained(self, callback: Callable[[], Any]) -> None:
        with self._condition:
            if self._active:
                self._drained_callbacks.append(callback)
                return
        try:
            callback()
        except Exception:
            pass

    def active_count(self) -> int:
        with self._condition:
            return len(self._active)

    def defer_process_cleanup(self, token: str, process: Any, *, tree_termination_confirmed: bool) -> None:
        if not tree_termination_confirmed:
            return

        def observe_exit() -> None:
            try:
                process.wait()
            except Exception:
                return
            self.finish(token, {"success": False, "reason": "cancelled", "cancelled": True})

        try:
            threading.Thread(target=observe_exit, name="whisper-cleanup-observer", daemon=True).start()
        except Exception:
            return


_ActiveTranscriptionRegistry = ActiveTranscriptionRegistry


def start_disconnect_monitor(
    connection: socket.socket | None,
    cancel_event: threading.Event,
) -> tuple[threading.Event, threading.Thread | None]:
    stop_monitor = threading.Event()
    if not isinstance(connection, socket.socket):
        return stop_monitor, None

    def watch_disconnect() -> None:
        while not stop_monitor.is_set():
            try:
                readable, _, _ = select.select([connection], [], [], 0)
                if readable and connection.recv(1, socket.MSG_PEEK) == b"":
                    cancel_event.set()
                    return
            except (OSError, ValueError):
                if not stop_monitor.is_set():
                    cancel_event.set()
                return
            stop_monitor.wait(0.05)

    monitor = threading.Thread(target=watch_disconnect, name="hub-request-disconnect", daemon=True)
    monitor.start()
    return stop_monitor, monitor


_start_disconnect_monitor = start_disconnect_monitor


def is_client_disconnect(exc: BaseException) -> bool:
    """Identify a peer closing an HTTP connection before the response is written."""
    if isinstance(exc, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
        return True
    # Socket error codes indicating peer disconnect across Windows & POSIX:
    #   32     – ERROR_BROKEN_PIPE  (mapped from POSIX EPIPE)
    #   103    – ECONNABORTED       – software caused connection abort (POSIX)
    #   104    – ECONNRESET         – connection reset by peer (POSIX)
    #   107    – ENOTCONN           – transport is not connected (POSIX)
    #   108    – ESHUTDOWN          – cannot send after transport endpoint shutdown (POSIX)
    #   10038  – WSAENOTSOCK        – socket closed/invalidated before send
    #   10040  – WSAEMSGSIZE        – used by some intermediaries on broken pipes in older stacks
    #   10052  – WSAENETRESET       – connection timed out / reset
    #   10053  – WSAECONNABORTED    – software caused connection abort
    #   10054  – WSAECONNRESET      – connection reset by peer
    #   10057  – WSAENOTCONN        – transport is already connected, but not connected anymore
    #   10058  – WSAESHUTDOWN       – cannot send after socket shutdown
    if not isinstance(exc, OSError):
        return False
    win_error = getattr(exc, "winerror", None)
    errno = getattr(exc, "errno", None)
    known = {32, 103, 104, 107, 108, 10038, 10040, 10052, 10053, 10054, 10057, 10058}
    if win_error in known or errno in known:
        return True
    msg = str(exc).lower()
    return any(
        marker in msg
        for marker in (
            "broken pipe",
            "connection reset",
            "connection aborted",
            "not a socket",
            "cannot send after socket shutdown",
            "winerror 10038",
            "winerror 10053",
            "winerror 10054",
            "winerror 10057",
            "winerror 10058",
        )
    )


_is_client_disconnect = is_client_disconnect


def invoke_cancellable_request(
    registry: ActiveTranscriptionRegistry,
    callback: Callable[..., Any],
    payload: dict[str, Any],
    *,
    connection: socket.socket | None = None,
) -> Any:
    from .client import CURRENT_REQUEST_CANCEL_EVENT

    token, cancel_event = registry.begin()
    context_token = CURRENT_REQUEST_CANCEL_EVENT.set(cancel_event)
    result: Any = {}
    stop_monitor, monitor = start_disconnect_monitor(connection, cancel_event)
    try:
        result = callback(payload, cancel_event=cancel_event)
        return result
    finally:
        stop_monitor.set()
        if monitor is not None:
            monitor.join(timeout=0.2)
        CURRENT_REQUEST_CANCEL_EVENT.reset(context_token)
        registry.finish(token, result)


_invoke_cancellable_request = invoke_cancellable_request
