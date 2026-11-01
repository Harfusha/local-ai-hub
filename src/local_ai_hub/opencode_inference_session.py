"""Experimental single-model external session over the Hub's GPU scheduler.

Only trusted bridge code may report terminal backend completion. This class
does not inspect Ollama and does not expose an HTTP interface by itself.
"""
from __future__ import annotations

import secrets
import threading
from typing import Any

from .opencode_model_names import validate_local_model_name


class InferenceSessionError(RuntimeError):
    """The external session cannot safely accept or release work."""


class ExternalInferenceSession:
    def __init__(self, scheduler: Any, model: str, token: str) -> None:
        self._scheduler = scheduler
        self._model = model
        self._token = token
        self._lock = threading.Lock()
        self._request: str | None = None
        self._uncertain = False
        self._closed = False

    @classmethod
    def open(cls, scheduler: Any, model: str) -> ExternalInferenceSession:
        try:
            validate_local_model_name(model)
        except ValueError as exc:
            raise InferenceSessionError(str(exc)) from exc
        token = scheduler.reserve_external_gpu()
        if not isinstance(token, str) or not token:
            raise InferenceSessionError("GPU reservation unavailable")
        return cls(scheduler, model, token)

    def start_request(self, model: str) -> str:
        with self._lock:
            if self._closed or self._uncertain or self._request is not None:
                raise InferenceSessionError("session is not available")
            if model != self._model:
                raise InferenceSessionError("session model cannot change")
            self._request = secrets.token_urlsafe(24)
            return self._request

    def finish_request(self, request: str, *, terminal_confirmed: bool) -> None:
        with self._lock:
            if (self._closed or not isinstance(request, str) or not request.isascii()
                    or self._request is None or not secrets.compare_digest(request, self._request)):
                raise InferenceSessionError("unknown request")
            if type(terminal_confirmed) is not bool:
                raise InferenceSessionError("terminal confirmation must be boolean")
            self._request = None
            if not terminal_confirmed:
                self._uncertain = True

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
            if self._scheduler.release_external_gpu(self._token) is not True:
                raise InferenceSessionError("GPU reservation release was not confirmed")
            self._closed = True
            self._token = ""
