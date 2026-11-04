"""Experimental single-model external session over the Hub's GPU scheduler.

Only trusted bridge code may report terminal backend completion. This class
does not inspect Ollama and does not expose an HTTP interface by itself.
"""
from __future__ import annotations

import secrets
import threading
import math
from typing import Any

from .opencode_model_names import validate_local_model_name


class InferenceSessionError(RuntimeError):
    """The external session cannot safely accept or release work."""


class ExternalInferenceSession:
    def __init__(self, scheduler: Any, model: str, token: str, *, idle_timeout_seconds: float = 900) -> None:
        self._scheduler = scheduler
        self._model = model
        self._token = token
        self._lock = threading.Lock()
        self._request: str | None = None
        self._uncertain = False
        self._closed = False
        self._idle_timeout_seconds = idle_timeout_seconds
        self._idle_timer: threading.Timer | None = None
        self._timer_generation = 0
        self._lease_timer: threading.Timer | None = None
        self._lease_timer_generation = 0
        self._arm_idle_timer()

    def _cancel_idle_timer(self) -> None:
        self._timer_generation += 1
        if self._idle_timer is not None:
            self._idle_timer.cancel()
            self._idle_timer = None

    def _arm_idle_timer(self) -> None:
        self._cancel_idle_timer()
        generation = self._timer_generation
        timer = threading.Timer(self._idle_timeout_seconds, self._expire_idle, args=(generation,))
        timer.daemon = True
        self._idle_timer = timer
        timer.start()

    def _cancel_lease_timer(self) -> None:
        self._lease_timer_generation += 1
        if self._lease_timer is not None:
            self._lease_timer.cancel()
            self._lease_timer = None

    def _arm_lease_timer(self, request: str) -> None:
        self._cancel_lease_timer()
        generation = self._lease_timer_generation
        delay = max(1.0, min(self._idle_timeout_seconds / 3.0, 300.0))
        timer = threading.Timer(delay, self._renew_active_lease, args=(generation, request))
        timer.daemon = True
        self._lease_timer = timer
        timer.start()

    def _renew_active_lease(self, generation: int, request: str) -> None:
        with self._lock:
            if (generation != self._lease_timer_generation or self._closed or self._request != request
                    or self._uncertain or not self._token):
                return
            renew = getattr(self._scheduler, "renew_external_gpu", None)
            if not callable(renew):
                self._lease_timer = None
                return
            try:
                renewed = renew(self._token, state="active") is True
            except Exception:
                renewed = False
            if not renewed:
                self._uncertain = True
                self._lease_timer = None
                return
            self._lease_timer = None
            self._arm_lease_timer(request)

    def _expire_idle(self, generation: int) -> None:
        with self._lock:
            if generation != self._timer_generation or self._closed or self._request is not None or self._uncertain or not self._token:
                return
            try:
                released = self._scheduler.release_external_gpu(self._token) is True
            except Exception:
                released = False
            if released:
                self._token = ""
                self._idle_timer = None
            else:
                self._uncertain = True

    @classmethod
    def open(cls, scheduler: Any, model: str, *, idle_timeout_seconds: float = 900) -> ExternalInferenceSession:
        if isinstance(idle_timeout_seconds, bool) or not isinstance(idle_timeout_seconds, (int, float)) or not math.isfinite(idle_timeout_seconds) or idle_timeout_seconds <= 0:
            raise ValueError("idle timeout must be a positive finite number")
        try:
            validate_local_model_name(model)
        except ValueError as exc:
            raise InferenceSessionError(str(exc)) from exc
        token = scheduler.reserve_external_gpu()
        if not isinstance(token, str) or not token:
            raise InferenceSessionError("GPU reservation unavailable")
        return cls(scheduler, model, token, idle_timeout_seconds=idle_timeout_seconds)

    def start_request(self, model: str) -> str:
        with self._lock:
            if self._closed or self._uncertain or self._request is not None:
                raise InferenceSessionError("session is not available")
            if model != self._model:
                raise InferenceSessionError("session model cannot change")
            if not self._token:
                token = self._scheduler.reserve_external_gpu()
                if not isinstance(token, str) or not token:
                    raise InferenceSessionError("GPU reservation unavailable")
                self._token = token
            renew = getattr(self._scheduler, "renew_external_gpu", None)
            if callable(renew) and renew(self._token, state="active") is not True:
                self._uncertain = True
                raise InferenceSessionError("GPU reservation renewal was not confirmed")
            self._cancel_idle_timer()
            self._request = secrets.token_urlsafe(24)
            self._arm_lease_timer(self._request)
            return self._request

    def finish_request(self, request: str, *, terminal_confirmed: bool) -> None:
        with self._lock:
            if (self._closed or not isinstance(request, str) or not request.isascii()
                    or self._request is None or not secrets.compare_digest(request, self._request)):
                raise InferenceSessionError("unknown request")
            if type(terminal_confirmed) is not bool:
                raise InferenceSessionError("terminal confirmation must be boolean")
            self._cancel_lease_timer()
            self._request = None
            if not terminal_confirmed:
                self._uncertain = True
            else:
                renew = getattr(self._scheduler, "renew_external_gpu", None)
                if callable(renew) and self._token and renew(self._token, state="idle") is not True:
                    self._uncertain = True
                else:
                    self._arm_idle_timer()

    def relay_stream(self, model: str, source: Any, sink: Any, *, preflight: Any = None) -> None:
        """Relay a bounded-parsed SSE stream; only clean EOF after DONE is terminal."""
        from .opencode_stream_guard import CompletionStreamGuard

        if not callable(source) or not callable(sink) or (preflight is not None and not callable(preflight)):
            raise InferenceSessionError("stream source and sink must be callable")
        request = self.start_request(model)
        confirmed = False
        submitted = False
        try:
            if preflight is not None:
                preflight()
            guard = CompletionStreamGuard()
            # The source may submit upstream immediately; failures thereafter
            # cannot be interpreted as proof that inference did not start.
            submitted = True
            for chunk in source():
                guard.feed(chunk)
                sink(chunk)
            if not guard.complete():
                raise InferenceSessionError("upstream completion was not confirmed")
            confirmed = True
        finally:
            self.finish_request(request, terminal_confirmed=confirmed or not submitted)

    def close(self) -> None:
        with self._lock:
            if self._closed or self._request is not None or self._uncertain:
                raise InferenceSessionError("session cannot safely release GPU")
            self._cancel_idle_timer()
            self._cancel_lease_timer()
            if self._token and self._scheduler.release_external_gpu(self._token) is not True:
                raise InferenceSessionError("GPU reservation release was not confirmed")
            self._closed = True
            self._token = ""
