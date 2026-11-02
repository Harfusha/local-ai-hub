"""Experimental per-container process and whole-session control service."""
from __future__ import annotations

import threading

from .opencode_owned_stop import OwnedJobBinding
from .opencode_stop_protocol import ControlError, control_exchange
from .opencode_winpipe import WindowsPipeListener


class StopService:
    """Serve authenticated stop requests; uncertain outcomes stop the service."""

    def __init__(self, sid: str, secret: bytes, binding: OwnedJobBinding):
        if not isinstance(secret, bytes) or len(secret) != 32 or type(binding) is not OwnedJobBinding:
            raise ValueError("valid secret and owned job binding are required")
        self._listener = WindowsPipeListener(sid)
        self.name = self._listener.name
        self._secret, self._binding = secret, binding
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._active = None
        self._failure = None
        self._thread = None

    def __enter__(self):
        if self._thread is not None:
            raise RuntimeError("control service cannot be restarted")
        self._listener.__enter__()
        self._thread = threading.Thread(target=self._serve, name="opencode-stop-control", daemon=True)
        try:
            self._thread.start()
        except BaseException:
            self._listener.__exit__(None, None, None)
            raise
        return self

    def _serve(self):
        try:
            while not self._stop.is_set():
                try:
                    pipe = self._listener.accept(timeout=0.5, stop=self._stop)
                except TimeoutError:
                    continue
                except InterruptedError:
                    if self._stop.is_set():
                        break
                    raise
                with self._lock:
                    self._active = pipe
                    stopping = self._stop.is_set()
                try:
                    if not stopping:
                        try:
                            result = control_exchange(pipe, self._secret, self._binding, timeout=10)
                            if result == "unknown":
                                raise ControlError("control outcome is unknown", outcome_unknown=True)
                        except ControlError as exc:
                            if exc.outcome_unknown:
                                raise
                finally:
                    with self._lock:
                        pipe.close()
                        self._active = None
        except BaseException as exc:
            self._failure = exc
        finally:
            try:
                self._listener.__exit__(None, None, None)
            except BaseException as exc:
                if self._failure is None:
                    self._failure = exc

    def check_health(self):
        if self._failure is not None:
            raise RuntimeError("control service failed") from self._failure
        if self._thread is None or not self._thread.is_alive() or self._stop.is_set():
            raise RuntimeError("control service is not running")

    def close(self):
        if self._thread is None:
            raise RuntimeError("control service was not started")
        self._stop.set()
        with self._lock:
            if self._active is not None:
                self._active.close()
        self._thread.join(timeout=12)
        if self._thread.is_alive():
            raise RuntimeError("control service shutdown was not confirmed")
        if self._failure is not None:
            raise RuntimeError("control service failed") from self._failure

    def __exit__(self, *_args):
        self.close()
