from __future__ import annotations

import hashlib
import json
import math
import os
import re
import socket
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlparse

_ORIGINAL_URLOPEN = urlopen

from . import model_quality
from .llama_cpp import LlamaCppRouter, _cancel_response_on_stop, _open_interruptible_response, _read_response_body, _set_response_timeout, _stop_requested
from .llama_cpp_runtime import LlamaCppManagedRuntime, llama_cpp_backend_selection, llama_cpp_managed_selected
from .llm_context_recovery import fit_recovered_context
from .json_utils import dumps as json_dumps


_HTTP_ERROR_BODY_LIMIT = 65_536
_GAMING_UNLOAD_MAX_TIMEOUT_SECONDS = 5.0


def _oom_context_request(payload: dict[str, Any], default_context: int) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Halve KV allocation only when retained input fits a conservative byte bound."""
    raw_options = payload.get("options")
    if raw_options is not None and not isinstance(raw_options, dict):
        return None, {"reason": "invalid_context_options"}
    options = dict(raw_options or {})
    try:
        original = int(options.get("num_ctx", default_context))
    except (TypeError, ValueError, OverflowError):
        return None, {"reason": "invalid_context_options"}
    reduced = original // 2
    metadata = {"original_num_ctx": original, "effective_num_ctx": reduced,
                "input_truncated": False, "device_changed": False}
    if reduced < 1024:
        return None, {**metadata, "reason": "context_floor"}
    adjusted, recovery = fit_recovered_context(payload, original, reduced)
    if recovery.get("reason") == "native_preset_context_halved":
        recovery["reason"] = "oom_context_halved"
    return adjusted, recovery


def _read_http_error_body(error: HTTPError) -> str:
    try:
        raw = error.read(_HTTP_ERROR_BODY_LIMIT + 1)
    finally:
        error.close()
    truncated = len(raw) > _HTTP_ERROR_BODY_LIMIT
    body = raw[:_HTTP_ERROR_BODY_LIMIT].decode("utf-8", errors="replace")
    return body + ("\n...[truncated]" if truncated else "")


def _normalise_keep_alive(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return an Ollama-valid keep_alive value without mutating caller input."""
    if payload is None:
        return None
    clean = dict(payload)
    if str(clean.get("keep_alive", "")).strip() == "-1":
        clean["keep_alive"] = "-1m"
    return clean

from .process_utils import (
    atomic_write_file,
    close_job_object,
    hidden_run_kwargs,
    managed_process_lock,
    open_named_job_object,
    popen_managed,
    pid_alive,
    process_owner_record,
    process_owner_state,
    set_process_priority,
    terminate_job_object,
    terminate_tree,
    wait_job_object_empty,
    windows_job_contains_process,
)
from .model_policy import ModelExecutionPolicy


class RepetitionWatchdog:
    """Detects repetitive degenerative generation loops in streaming LLM responses."""

    def __init__(self, max_repeat: int = 3, min_line_len: int = 4):
        self.max_repeat = max_repeat
        self.min_line_len = min_line_len
        self.buffer = ""
        self.lines: list[str] = []
        self.word_buffer = ""
        self.loop_detected = False
        self.cycle_length: int = 0

    def push(self, delta: str) -> bool:
        """Push streaming delta. Returns True if a repetitive loop is detected."""
        if self.loop_detected or not delta:
            return self.loop_detected
        self.word_buffer = (self.word_buffer + delta)[-512:]
        self.buffer += delta
        if "\n" in self.buffer:
            parts = self.buffer.split("\n")
            self.buffer = parts[-1]
            for line in parts[:-1]:
                cleaned = line.strip()
                norm = cleaned.lstrip("-* \t").strip()
                if len(norm) >= self.min_line_len:
                    self.lines.append(norm)
                    if len(self.lines) > 30:
                        self.lines.pop(0)
                    if self._check_loop():
                        self.loop_detected = True
                        return True
        if self._check_ngram_loop() or self._check_word_loop():
            self.loop_detected = True
            return True
        return False
    def _check_word_loop(self) -> bool:
        words = re.findall(r"[\w]+(?:['’][\w]+)?", self.word_buffer.casefold())
        count = len(words)
        if count < self.max_repeat:
            return False
        for width in range(1, min(8, count // self.max_repeat) + 1):
            repeats = max(4, self.max_repeat + 1) if width == 1 else self.max_repeat
            if count < width * repeats:
                continue
            tail = words[-width * repeats:]
            cycle = tail[-width:]
            if all(tail[i:i + width] == cycle for i in range(0, len(tail), width)):
                return True
        return False

    def _check_ngram_loop(self) -> bool:
        """Catch repeated token cycles in streamed or complete responses."""
        tokens = [
            token.strip(".,!?;:()[]{}<>\\\"'").lower()
            for token in self.word_buffer.split()
        ]
        tail = [token for token in tokens if token][-64:]
        if len(tail) < self.max_repeat * 2:
            return False

        for end in range(len(tail), max(0, len(tail) - 12), -1):
            for width in range(1, min(12, end // self.max_repeat) + 1):
                minimum_repeats = self.max_repeat + (1 if width == 1 else 0)
                if end < width * minimum_repeats:
                    continue
                pattern = tail[end - width:end]
                repeats = 1
                cursor = end - width
                while cursor >= width and tail[cursor - width:cursor] == pattern:
                    repeats += 1
                    cursor -= width
                if repeats >= minimum_repeats:
                    return True
        return False
    def _check_loop(self) -> bool:
        n = len(self.lines)
        if n < self.max_repeat:
            return False
        # 1-line repetition: X, X, X
        last = self.lines[-1]
        if all(self.lines[-i] == last for i in range(1, self.max_repeat + 1)):
            self.cycle_length = 1
            return True
        # 2-line cycle: A, B, A, B, A, B
        if n >= self.max_repeat * 2:
            a, b = self.lines[-2], self.lines[-1]
            if a != b:
                is_2_cycle = True
                for k in range(1, self.max_repeat + 1):
                    if self.lines[-2 * k] != a or self.lines[-2 * k + 1] != b:
                        is_2_cycle = False
                        break
                if is_2_cycle:
                    self.cycle_length = 2
                    return True
        # 3-line cycle: A, B, C, A, B, C, A, B, C
        if n >= self.max_repeat * 3:
            a, b, c = self.lines[-3], self.lines[-2], self.lines[-1]
            if len({a, b, c}) >= 2:
                is_3_cycle = True
                for k in range(1, self.max_repeat + 1):
                    if (
                        self.lines[-3 * k] != a
                        or self.lines[-3 * k + 1] != b
                        or self.lines[-3 * k + 2] != c
                    ):
                        is_3_cycle = False
                        break
                if is_3_cycle:
                    self.cycle_length = 3
                    return True
        return False

    def trim_trailing_loop(self, text: str) -> str:
        """Trims redundant trailing repeated loop cycles from the generated response."""
        if not self.loop_detected or self.cycle_length <= 0 or not text:
            return text
        text_lines = text.splitlines(keepends=True)
        if not text_lines:
            return text
        # Remove (self.max_repeat - 1) * self.cycle_length trailing repeating lines
        lines_to_remove = (self.max_repeat - 1) * self.cycle_length
        removed = 0
        idx = len(text_lines) - 1
        while idx >= 0 and removed < lines_to_remove:
            line_content = text_lines[idx].strip()
            norm = line_content.lstrip("-* \t").strip()
            if len(norm) >= self.min_line_len:
                removed += 1
            idx -= 1
        if idx >= 0:
            return "".join(text_lines[:idx + 1]).rstrip() + "\n"
        return text


class ModelPreparationCancelled(InterruptedError):
    """Preparation stopped because no active scheduler caller still needs it."""

    preparation_cancelled = True


class ModelPreparationAdmissionRejected(RuntimeError):
    """A fresh resource check rejected loading after existing models were unloaded."""

    def __init__(self, admission: dict[str, Any], evicted_models: list[str] | None = None):
        self.admission = dict(admission)
        self.evicted_models = list(evicted_models or [])
        super().__init__(str(self.admission.get("reason", "post-unload admission rejected")))


class OllamaRuntime:
    def __init__(self, config: dict[str, Any], *, managed_name: str = "ollama"):
        self.config = config
        self.base_url = config["server"]["ollama_url"].rstrip("/")
        self.timeout = float(config["server"].get("request_timeout_seconds", 300))
        self.state_dir = Path(config["server"]["state_dir"])
        self.state_dir.mkdir(parents=True, exist_ok=True)
        safe_name = "".join(ch for ch in str(managed_name) if ch.isalnum() or ch in {"-", "_"}) or "ollama"
        self.managed_name = safe_name
        self.managed_pid_path = self.state_dir / f"{safe_name}.managed.pid"
        self.managed_owner_path = self.state_dir / f"{safe_name}.owner.json"
        self.managed_lock_path = self.state_dir / f"{safe_name}.managed.lock"
        self._managed_owner: dict[str, Any] | None = None
        self._managed_process: subprocess.Popen[Any] | None = None
        self.model_policy = ModelExecutionPolicy(config)
        self.llama_cpp_managed = LlamaCppManagedRuntime(config)
        self.llama_cpp = LlamaCppRouter(config, managed_runtime=(
            self.llama_cpp_managed if llama_cpp_managed_selected(config) else None
        ))
        self._meta_cache: dict[str, Any] = {}
        self._meta_cache_at: dict[str, float] = {}
        self._ensure_lock = threading.Lock()

    def _is_embedding_model(self, model: str) -> bool:
        configured = str(self.config.get("models", {}).get("embedding", "") or "").strip()
        return bool(configured) and str(model or "").strip() == configured

    def _llama_version_label(self) -> str:
        if llama_cpp_managed_selected(self.config):
            mode = str(self.llama_cpp_managed.status().get("mode", ""))
            return "llama.cpp CPU" if mode == "none" else "llama.cpp SYCL" if mode else "llama.cpp"
        return "llama.cpp external"

    def request(
        self,
        endpoint: str,
        payload: dict[str, Any] | None = None,
        timeout: float | None = None,
        *,
        should_stop: Any | None = None,
        deadline: float | None = None,
    ) -> dict[str, Any]:
        if payload is not None and endpoint in {"/api/chat", "/api/generate"}:
            return self.request_stream(
                endpoint, payload, None, timeout, should_stop=should_stop, deadline=deadline,
            )
        if endpoint == "/api/show":
            router = getattr(self, "llama_cpp", None)
            describe = getattr(router, "model_capabilities", None)
            model = payload.get("name", "") if isinstance(payload, dict) else ""
            if callable(describe):
                result = describe(str(model))
                if isinstance(result, dict):
                    return result
        if not bool(self.config.get("ollama", {}).get("enabled", False)):
            if endpoint == "/api/version":
                router = getattr(self, "llama_cpp", None)
                return {"version": self._llama_version_label()} if router is not None and router.is_online() else {"error": "llama.cpp router unavailable"}
            if endpoint == "/api/tags":
                models = self._online_llama_cpp_models()
                if models is None:
                    return {"error": "llama.cpp SYCL router unavailable"}
                return {"models": [{"name": model} for model in models]}
            if endpoint == "/api/ps":
                try:
                    rows = self.llama_cpp.loaded_model_details()
                except Exception:
                    return {"error": "llama.cpp model inventory unavailable"}
                return {"models": [
                    {"name": row["name"], "model": row["name"], "context_length": row.get("context_length", 0), "size": 0, "size_vram": 0, "details": {"quantization_level": row.get("quantization", "GGUF")}}
                    for row in rows
                ]}
            return {"error": "Ollama is not the selected backend and this endpoint is not provided by llama.cpp"}
        if should_stop is not None or deadline is not None:
            return self._request_json_interruptible(
                endpoint, payload, timeout=timeout, should_stop=should_stop, deadline=deadline,
            )
        payload = _normalise_keep_alive(payload)
        body = json_dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"} if body is not None else {}
        attempts = max(1, int(self.config.get("ollama", {}).get("request_attempts", 2)))
        retry_delay = max(0.0, float(self.config.get("ollama", {}).get("retry_delay_seconds", 0.6)))
        total_timeout = max(0.05, float(timeout if timeout is not None else self.timeout))
        request_deadline = time.monotonic() + total_timeout
        last_error = "unknown Ollama error"
        for attempt in range(1, attempts + 1):
            remaining = request_deadline - time.monotonic()
            if remaining <= 0:
                break
            req = Request(f"{self.base_url}{endpoint}", data=body, headers=headers)
            try:
                with urlopen(req, timeout=max(0.05, remaining)) as response:
                    raw = response.read().decode("utf-8")
                    result = json.loads(raw) if raw else {}
                    if isinstance(result, dict):
                        result["_lah_retry_count"] = max(0, attempt - 1)
                    return result
            except HTTPError as exc:
                raw = _read_http_error_body(exc)
                last_error = f"HTTP {exc.code}: {raw}"
                if exc.code < 500 or attempt >= attempts:
                    return {"error": last_error, "_lah_retry_count": max(0, attempt - 1)}
            except URLError as exc:
                last_error = f"Ollama unavailable: {exc.reason}"
                if isinstance(getattr(exc, "reason", None), (socket.timeout, TimeoutError)) or attempt >= attempts:
                    break
            except (socket.timeout, TimeoutError) as exc:
                last_error = f"Ollama request timed out: {exc}"
                break
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if "timeout" in str(exc).lower() or "timed out" in str(exc).lower() or attempt >= attempts:
                    break
            remaining = request_deadline - time.monotonic()
            if remaining <= 0:
                break
            if retry_delay:
                time.sleep(min(retry_delay, remaining))
        return {"error": last_error, "_lah_retry_count": max(0, attempts - 1), "timed_out": time.monotonic() >= request_deadline}

    def _request_json_interruptible(
        self,
        endpoint: str,
        payload: dict[str, Any] | None,
        *,
        timeout: float | None,
        should_stop: Any | None,
        deadline: float | None,
    ) -> dict[str, Any]:
        """Send bounded JSON requests with cancellation and retry handling."""
        started = time.monotonic()
        timeout_budget = max(0.05, float(timeout if timeout is not None else self.timeout))
        request_deadline = started + timeout_budget
        if deadline is not None:
            request_deadline = min(request_deadline, float(deadline))
        if _stop_requested(should_stop):
            return {"success": False, "preempted": True, "error": "request cancelled before Ollama request", "_lah_provider": "ollama"}
        if request_deadline <= time.monotonic():
            return {"error": "Ollama request deadline expired", "timed_out": True, "_lah_provider": "ollama"}

        clean = _normalise_keep_alive(payload)
        body = json_dumps(clean).encode("utf-8") if clean is not None else None
        headers = {"Content-Type": "application/json"} if body is not None else {}
        attempts = max(1, int(self.config.get("ollama", {}).get("request_attempts", 2)))
        retry_delay = max(0.0, float(self.config.get("ollama", {}).get("retry_delay_seconds", 0.6)))
        last_error = "unknown Ollama error"
        attempts_used = 0
        for attempt in range(1, attempts + 1):
            attempts_used = attempt
            if _stop_requested(should_stop):
                return {"success": False, "preempted": True, "error": "request cancelled during Ollama request", "_lah_retry_count": attempt - 1, "_lah_provider": "ollama"}
            if time.monotonic() >= request_deadline:
                return {"error": last_error, "timed_out": True, "_lah_retry_count": attempt - 1, "_lah_provider": "ollama"}
            req = Request(f"{self.base_url}{endpoint}", data=body, headers=headers)
            retryable = False
            try:
                with _open_interruptible_response(req, request_deadline, should_stop) as response, _cancel_response_on_stop(
                    response, should_stop, request_deadline,
                ):
                    raw = _read_response_body(response, request_deadline, should_stop).decode("utf-8", errors="replace")
                    status = int(getattr(response, "status", getattr(response, "code", 200)) or 200)
                if _stop_requested(should_stop):
                    return {"success": False, "preempted": True, "error": "request cancelled during Ollama request", "_lah_retry_count": attempt - 1, "_lah_provider": "ollama"}
                if time.monotonic() >= request_deadline:
                    return {"error": "Ollama request deadline expired", "timed_out": True, "_lah_retry_count": attempt - 1, "_lah_provider": "ollama"}
                if status >= 400:
                    last_error = f"HTTP {status}: {raw[:2000]}"
                    retryable = status >= 500
                else:
                    try:
                        result = json.loads(raw) if raw else {}
                    except (json.JSONDecodeError, UnicodeError) as exc:
                        return {"error": f"Invalid Ollama JSON response: {exc}", "_lah_retry_count": attempt - 1, "_lah_provider": "ollama"}
                    if isinstance(result, dict):
                        result.setdefault("_lah_retry_count", attempt - 1)
                        return result
                    return {"error": "Ollama returned a non-object JSON response", "_lah_retry_count": attempt - 1, "_lah_provider": "ollama"}
            except HTTPError as exc:
                last_error = f"HTTP {exc.code}: {_read_http_error_body(exc)}"
                retryable = exc.code >= 500
            except URLError as exc:
                reason = getattr(exc, "reason", exc)
                last_error = f"Ollama unavailable: {reason}"
                if isinstance(reason, (socket.timeout, TimeoutError)):
                    break
                retryable = True
            except (socket.timeout, TimeoutError) as exc:
                last_error = f"Ollama request timed out: {exc}"
                break
            except Exception as exc:
                if _stop_requested(should_stop):
                    return {"success": False, "preempted": True, "error": "request cancelled during Ollama request", "_lah_retry_count": attempt - 1, "_lah_provider": "ollama"}
                last_error = f"{type(exc).__name__}: {exc}"
                if "timeout" in str(exc).lower() or "timed out" in str(exc).lower():
                    break
                retryable = True

            if not retryable or attempt >= attempts:
                break
            pause_until = min(request_deadline, time.monotonic() + retry_delay)
            while time.monotonic() < pause_until:
                if _stop_requested(should_stop):
                    return {"success": False, "preempted": True, "error": "request cancelled while retrying Ollama request", "_lah_retry_count": attempt, "_lah_provider": "ollama"}
                time.sleep(min(0.05, max(0.0, pause_until - time.monotonic())))

        if _stop_requested(should_stop):
            return {"success": False, "preempted": True, "error": "request cancelled during Ollama request", "_lah_retry_count": max(0, attempts_used - 1), "_lah_provider": "ollama"}
        return {"error": last_error, "_lah_retry_count": max(0, attempts_used - 1), "timed_out": time.monotonic() >= request_deadline, "_lah_provider": "ollama"}

    def request_stream(
        self, endpoint: str, payload: dict[str, Any] | None, on_chunk: Any,
        timeout: float | None = None, *, on_thinking: Any | None = None,
        should_stop: Any | None = None, deadline: float | None = None,
    ) -> dict[str, Any]:
        return self._request_stream_tracked(endpoint, payload, on_chunk, timeout,
                                            on_thinking=on_thinking, should_stop=should_stop, deadline=deadline)

    def _request_stream_tracked(
        self, endpoint: str, payload: dict[str, Any] | None, on_chunk: Any,
        timeout: float | None = None, *, on_thinking: Any | None = None,
        should_stop: Any | None = None, deadline: float | None = None,
        single_attempt: bool = False,
    ) -> dict[str, Any]:
        emitted = False

        def forward(text: str) -> None:
            nonlocal emitted
            emitted = emitted or bool(text)
            if callable(on_chunk):
                on_chunk(text)

        def forward_thinking(text: str) -> None:
            nonlocal emitted
            emitted = emitted or bool(text)
            if callable(on_thinking):
                on_thinking(text)

        try:
            result = self._request_stream_impl(endpoint, payload, forward, timeout,
                                               on_thinking=forward_thinking, should_stop=should_stop, deadline=deadline,
                                               single_attempt=single_attempt)
        except Exception as exc:
            return {"success": False, "error": f"{type(exc).__name__}: {exc}",
                    "_lah_partial_response": emitted, "terminal": True, "retryable": False}
        if emitted and "error" in result:
            return {**result, "_lah_partial_response": True}
        return result

    def _request_stream_impl(
        self,
        endpoint: str,
        payload: dict[str, Any] | None,
        on_chunk: Any,
        timeout: float | None = None,
        *,
        on_thinking: Any | None = None,
        should_stop: Any | None = None,
        deadline: float | None = None,
        single_attempt: bool = False,
    ) -> dict[str, Any]:
        started = time.monotonic()
        timeout_budget = max(0.05, float(timeout if timeout is not None else self.timeout))
        request_deadline = started + timeout_budget
        if deadline is not None:
            request_deadline = min(request_deadline, float(deadline))
        total_timeout = max(0.0, request_deadline - started)
        remaining = request_deadline - time.monotonic()
        if remaining <= 0:
            return {"error": "Ollama request deadline expired", "timed_out": True, "_lah_provider": "ollama"}
        if _stop_requested(should_stop):
            return {"success": False, "preempted": True, "error": "request cancelled before start", "_lah_provider": "ollama"}
        llama_router = getattr(self, "llama_cpp", None)
        llama_selected = not bool(self.config.get("ollama", {}).get("enabled", False))
        llama_result = llama_router.request_stream(
            endpoint, payload, on_chunk, timeout=remaining, on_thinking=on_thinking,
            should_stop=should_stop, deadline=request_deadline,
        ) if llama_selected and llama_router is not None else None
        if not (isinstance(llama_result, dict) and (llama_result.get("preempted") or llama_result.get("timed_out"))):
            provider = "llama.cpp" if llama_selected else "ollama"
            if _stop_requested(should_stop):
                return {"success": False, "preempted": True, "error": "request cancelled before backend fallback", "_lah_provider": provider}
            if time.monotonic() >= request_deadline:
                return {"error": "request deadline expired before backend fallback", "timed_out": True, "_lah_provider": provider}
        if llama_result is not None:
            if "_lah_backend_unavailable" not in llama_result:
                if llama_cpp_managed_selected(self.config):
                    device = str(self.llama_cpp_managed.status().get("mode", ""))
                    llama_result["_lah_provider"] = "llama.cpp-cpu" if device == "none" else "llama.cpp-sycl" if device else "llama.cpp"
                return llama_result
            backend_fallback = str(llama_result.get("_lah_backend_unavailable", "SYCL unavailable"))
            if llama_selected:
                if _stop_requested(should_stop):
                    return {"success": False, "preempted": True, "error": "request cancelled while llama.cpp was unavailable", "_lah_provider": "llama.cpp"}
                if time.monotonic() >= request_deadline:
                    return {"error": "request deadline expired while llama.cpp was unavailable", "timed_out": True, "_lah_provider": "llama.cpp"}
                return {"error": f"llama.cpp unavailable: {backend_fallback}", "_lah_provider": "llama.cpp"}
        else:
            backend_fallback = ""
            if llama_selected:
                if _stop_requested(should_stop):
                    return {"success": False, "preempted": True, "error": "request cancelled while llama.cpp route was unavailable", "_lah_provider": "llama.cpp"}
                if time.monotonic() >= request_deadline:
                    return {"error": "request deadline expired while llama.cpp route was unavailable", "timed_out": True, "_lah_provider": "llama.cpp"}
                return {"error": "Selected llama.cpp route is unavailable for this model", "_lah_provider": "llama.cpp"}
        if _stop_requested(should_stop):
            return {"success": False, "preempted": True, "error": "request cancelled before Ollama backend", "_lah_provider": "ollama"}
        if time.monotonic() >= request_deadline:
            return {"error": "request deadline expired before Ollama backend", "timed_out": True, "_lah_provider": "ollama"}
        clean = dict(_normalise_keep_alive(payload) or {})
        clean["stream"] = True
        body = json_dumps(clean).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        attempts = 1 if single_attempt else max(1, int(self.config.get("ollama", {}).get("request_attempts", 2)))
        retry_delay = max(0.0, float(self.config.get("ollama", {}).get("retry_delay_seconds", 0.6)))
        deadline = request_deadline
        last_error = "unknown Ollama error"
        timed_out = False
        context_recovery: dict[str, Any] | None = None
        allowed_attempts = attempts
        for attempt in range(1, attempts + 2):
            remaining = request_deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            generated: list[str] = []
            chat: list[str] = []
            thinking_parts: list[str] = []
            emitted_output = False
            stream_error = False
            final: dict[str, Any] = {}
            watchdog = RepetitionWatchdog(max_repeat=3)
            req = Request(f"{self.base_url}{endpoint}", data=body, headers=headers)
            try:
                if _stop_requested(should_stop):
                    return {"success": False, "preempted": True, "error": "request cancelled before Ollama request", "_lah_provider": "ollama"}
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return {"error": f"Ollama request timed out after {total_timeout:g}s", "timed_out": True, "_lah_provider": "ollama"}
                import urllib.request
                from contextlib import contextmanager
                active_urlopen = urlopen if urlopen is not _ORIGINAL_URLOPEN else urllib.request.urlopen
                if active_urlopen is not _ORIGINAL_URLOPEN:
                    @contextmanager
                    def _custom_opener():
                        resp = active_urlopen(req, timeout=remaining)
                        try:
                            yield resp
                        finally:
                            if hasattr(resp, "close"):
                                try:
                                    resp.close()
                                except Exception:
                                    pass
                    response_ctx = _custom_opener()
                else:
                    response_ctx = _open_interruptible_response(req, deadline, should_stop)
                with response_ctx as response, _cancel_response_on_stop(response, should_stop, deadline):
                    response_lines = iter(response)
                    while True:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            last_error = f"Ollama request timed out after {total_timeout:g}s"
                            timed_out = True
                            break
                        if _stop_requested(should_stop):
                            return {"success": False, "preempted": True, "error": "request cancelled during generation", "_lah_provider": "ollama"}
                        _set_response_timeout(response, remaining)
                        try:
                            raw_line = next(response_lines)
                        except StopIteration:
                            break
                        except socket.timeout:
                            if _stop_requested(should_stop):
                                return {"success": False, "preempted": True, "error": "request cancelled during generation", "_lah_provider": "ollama"}
                            last_error = f"Ollama request timed out after {total_timeout:g}s"
                            timed_out = True
                            break
                        if time.monotonic() >= deadline:
                            last_error = f"Ollama request timed out after {total_timeout:g}s"
                            timed_out = True
                            break
                        if _stop_requested(should_stop):
                            return {"success": False, "preempted": True, "error": "request cancelled during generation", "_lah_provider": "ollama"}
                        if isinstance(raw_line, (bytes, bytearray)):
                            raw_text = raw_line.decode("utf-8", errors="replace").strip()
                        else:
                            raw_text = str(raw_line).strip()
                        if not raw_text:
                            continue
                        try:
                            chunk = json.loads(raw_text)
                        except json.JSONDecodeError:
                            last_error, stream_error = "Ollama returned malformed stream JSON", True
                            break
                        if not isinstance(chunk, dict):
                            last_error, stream_error = "Ollama returned a non-object stream event", True
                            break
                        if chunk.get("error"):
                            last_error = str(chunk["error"])
                            stream_error = True
                            break
                        delta = chunk.get("response")
                        if delta is not None:
                            text = str(delta)
                            if text:
                                generated.append(text)
                                if on_chunk is not None:
                                    emitted_output = True
                                    try: on_chunk(text)
                                    except Exception: pass
                                if watchdog.push(text):
                                    final["_lah_repetition_loop_detected"] = True
                                    break
                        message = chunk.get("message")
                        if isinstance(message, dict) and message.get("content") is not None:
                            text = str(message["content"])
                            if text:
                                chat.append(text)
                                if on_chunk is not None:
                                    emitted_output = True
                                    try: on_chunk(text)
                                    except Exception: pass
                                if watchdog.push(text):
                                    final["_lah_repetition_loop_detected"] = True
                                    break
                        thinking_delta = chunk.get("thinking")
                        if thinking_delta is None and isinstance(message, dict):
                            thinking_delta = message.get("thinking")
                        if thinking_delta:
                            thinking_text = str(thinking_delta)
                            thinking_parts.append(thinking_text)
                            if on_thinking is not None:
                                emitted_output = True
                                try: on_thinking(thinking_text)
                                except Exception: pass
                        final.update(chunk)
                        if chunk.get("done") is True:
                            break
                if timed_out:
                    return {"error": last_error, "_lah_retry_count": max(0, attempt - 1), "timed_out": True}
                if watchdog.loop_detected:
                    return {
                        "error": "model output repetition loop detected",
                        "_lah_repetition_loop_detected": True,
                        "_lah_retry_count": max(0, attempt - 1),
                        "model": str(clean.get("model", "")),
                    }
                if generated:
                    resp_text = "".join(generated)
                    if watchdog.loop_detected:
                        resp_text = watchdog.trim_trailing_loop(resp_text)
                    final["response"] = resp_text
                if chat:
                    message = dict(final.get("message") or {})
                    chat_text = "".join(chat)
                    if watchdog.loop_detected:
                        chat_text = watchdog.trim_trailing_loop(chat_text)
                    message["content"] = chat_text
                    final["message"] = message
                if thinking_parts:
                    final["thinking"] = "".join(thinking_parts)
                if final.get("done") is True and not final.get("error") and not stream_error:
                    final["_lah_retry_count"] = max(0, attempt - 1)
                    if context_recovery is not None:
                        final["context_recovery"] = context_recovery
                    if backend_fallback:
                        final["_lah_backend_fallback"] = backend_fallback
                    return final
                if not stream_error:
                    return {"error": "Ollama stream ended before a completion marker", "incomplete_stream": True,
                            "retryable": False, "_lah_partial_response": bool(generated or chat or thinking_parts),
                            "_lah_retry_count": max(0, attempt - 1)}
            except HTTPError as exc:
                raw = _read_http_error_body(exc)
                last_error = f"HTTP {exc.code}: {raw}"
                if exc.code < 500:
                    break
            except URLError as exc:
                if _stop_requested(should_stop):
                    return {"success": False, "preempted": True, "error": "request cancelled during generation", "_lah_provider": "ollama"}
                last_error = f"Ollama unavailable: {exc.reason}"
                if isinstance(getattr(exc, "reason", None), (socket.timeout, TimeoutError)):
                    timed_out = True
                    break
            except (socket.timeout, TimeoutError) as exc:
                if _stop_requested(should_stop):
                    return {"success": False, "preempted": True, "error": "request cancelled during generation", "_lah_provider": "ollama"}
                if time.monotonic() >= deadline:
                    return {"error": f"Ollama request timed out after {total_timeout:g}s", "timed_out": True, "_lah_provider": "ollama"}
                last_error = f"Ollama request timed out: {exc}"
                timed_out = True
                break
            except Exception as exc:
                if _stop_requested(should_stop):
                    return {"success": False, "preempted": True, "error": "request cancelled during generation", "_lah_provider": "ollama"}
                if time.monotonic() >= deadline:
                    return {"error": f"Ollama request timed out after {total_timeout:g}s", "timed_out": True, "_lah_provider": "ollama"}
                last_error = f"{type(exc).__name__}: {exc}"
                if "timeout" in str(exc).lower() or "timed out" in str(exc).lower():
                    timed_out = True
                    break
            if timed_out:
                return {"error": last_error, "_lah_retry_count": max(0, attempt - 1), "timed_out": True}
            if emitted_output or generated or chat or thinking_parts:
                return {
                    "error": last_error,
                    "_lah_retry_count": max(0, attempt - 1),
                    "_lah_partial_response": True,
                }
            memory_error = any(marker in last_error.lower() for marker in (
                "out of memory", "not enough memory", "insufficient memory", "failed to allocate",
            ))
            if memory_error:
                if context_recovery is not None:
                    break
                model = str(clean.get("model", ""))
                try:
                    default_context = self.model_policy.profile(model).num_ctx
                except (AttributeError, TypeError, ValueError):
                    context_recovery = {"reason": "context_profile_unavailable"}
                    break
                adjusted, recovery = _oom_context_request(clean, default_context)
                context_recovery = recovery
                if adjusted is None:
                    break
                clean = adjusted
                body = json_dumps(clean).encode("utf-8")
                allowed_attempts = max(attempts, attempt + 1)
            if attempt >= allowed_attempts:
                break
            remaining = request_deadline - time.monotonic()
            if attempt < allowed_attempts and remaining > 0 and retry_delay:
                time.sleep(min(retry_delay, remaining))
        return {"error": last_error, "_lah_retry_count": max(0, attempt - 1),
                "timed_out": timed_out or time.monotonic() >= deadline,
                **({"context_recovery": context_recovery} if context_recovery is not None else {})}

    def run_benchmark_scenario(
        self,
        *,
        name: str,
        contract: dict[str, Any],
        scheduler: Any,
        resource_sampler: Any | None = None,
    ) -> dict[str, Any]:
        """Run bounded synthetic inference and return only observed measurements."""
        scenario_names = {"scheduler", "batch", "deadline", "overload", "cancel", "fallback"}
        if not isinstance(name, str) or name not in scenario_names or not isinstance(contract, dict) or contract.get("scenario") != name:
            return {"success": False, "error_type": "invalid_scenario_contract"}
        required_fields = contract.get("required_fields")
        if (
            not isinstance(required_fields, list)
            or not required_fields
            or any(not isinstance(field, str) or not field for field in required_fields)
        ):
            return {"success": False, "error_type": "invalid_scenario_contract"}
        requested_fields = tuple(required_fields)
        inputs = contract.get("scenario_inputs")
        if not isinstance(inputs, dict):
            return {"success": False, "error_type": "invalid_scenario_inputs"}

        model = inputs.get("model")
        profile = inputs.get("profile")
        items = inputs.get("items")
        if (
            not isinstance(model, str) or not model.strip() or len(model) > 256
            or not isinstance(profile, str) or not profile.strip() or len(profile) > 64
            or not isinstance(items, list) or not 1 <= len(items) <= 32
        ):
            return {"success": False, "error_type": "invalid_scenario_inputs"}

        normalized_items: list[dict[str, str]] = []
        seen_ids: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                return {"success": False, "error_type": "invalid_scenario_inputs"}
            item_id = item.get("id")
            tenant = item.get("tenant", "benchmark")
            prompt = item.get("prompt")
            if (
                not isinstance(item_id, str) or not item_id or len(item_id) > 128 or item_id in seen_ids
                or not isinstance(tenant, str) or not tenant or len(tenant) > 128
                or not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 4096
            ):
                return {"success": False, "error_type": "invalid_scenario_inputs"}
            seen_ids.add(item_id)
            normalized_items.append({"id": item_id, "tenant": tenant, "prompt": prompt})

        failure_probe_item_id: str | None = None
        if name == "batch":
            if len(normalized_items) < 2:
                return {"success": False, "error_type": "invalid_scenario_inputs"}
            requested_probe = inputs.get("failure_probe_item_id")
            if requested_probe is None and normalized_items:
                requested_probe = normalized_items[-1]["id"]
            if not isinstance(requested_probe, str) or requested_probe not in seen_ids:
                return {"success": False, "error_type": "invalid_scenario_inputs"}
            failure_probe_item_id = requested_probe

        max_tokens = inputs.get("max_tokens", 64)
        source_max_tokens = inputs.get("source_max_tokens", max_tokens)
        fallback_max_tokens = inputs.get("fallback_max_tokens", max_tokens)
        concurrency_limit = inputs.get("max_concurrency", contract.get("concurrency_limit", 1))
        if (
            isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or not 1 <= max_tokens <= 4096
            or isinstance(source_max_tokens, bool) or not isinstance(source_max_tokens, int)
            or not 1 <= source_max_tokens <= 4096
            or isinstance(fallback_max_tokens, bool) or not isinstance(fallback_max_tokens, int)
            or not 1 <= fallback_max_tokens <= 4096
            or isinstance(concurrency_limit, bool) or not isinstance(concurrency_limit, int)
            or not 1 <= concurrency_limit <= 8
        ):
            return {"success": False, "error_type": "invalid_scenario_inputs"}

        configured_timeout = self.config.get("server", {}).get("request_timeout_seconds", 30)
        try:
            configured_timeout = max(0.05, min(120.0, float(configured_timeout)))
        except (TypeError, ValueError, OverflowError):
            configured_timeout = 30.0
        deadline_ms = inputs.get("deadline_ms", round(configured_timeout * 1000))
        if isinstance(deadline_ms, bool) or not isinstance(deadline_ms, int) or not 1 <= deadline_ms <= 120_000:
            return {"success": False, "error_type": "invalid_scenario_inputs"}
        timeout_seconds = deadline_ms / 1000

        cancel_after_ms = inputs.get("cancel_after_ms", 0)
        if name == "cancel" and (
            isinstance(cancel_after_ms, bool) or not isinstance(cancel_after_ms, int)
            or not 1 <= cancel_after_ms < deadline_ms
        ):
            return {"success": False, "error_type": "invalid_scenario_inputs"}
        fallback_model = inputs.get("fallback_model")
        fallback_profile = inputs.get("fallback_profile")
        expected = inputs.get("expected")
        floor = inputs.get("quality_floor_pct", contract.get("quality_floor_pct"))
        if name == "fallback" and (
            not isinstance(fallback_model, str) or not fallback_model.strip() or len(fallback_model) > 256
            or fallback_model.strip() == model.strip()
            or not isinstance(fallback_profile, str) or not fallback_profile.strip() or len(fallback_profile) > 64
            or not isinstance(expected, dict) or isinstance(floor, bool)
            or not isinstance(floor, (int, float)) or not 0 <= float(floor) <= 100
        ):
            return {"success": False, "error_type": "invalid_scenario_inputs"}
        overload_count = inputs.get("overload_count", len(normalized_items))
        if name == "overload" and (
            isinstance(overload_count, bool) or not isinstance(overload_count, int)
            or not 1 <= overload_count <= len(normalized_items)
        ):
            return {"success": False, "error_type": "invalid_scenario_inputs"}

        def queue_depth() -> int | None:
            pending = getattr(scheduler, "_pending", None)
            condition = getattr(scheduler, "_cond", None)
            if not isinstance(pending, list) or condition is None:
                return None
            try:
                with condition:
                    return len(pending)
            except Exception:
                return None

        running_lock = threading.Lock()
        running_count = 0
        maximum_running = 0
        depth_observations: list[int] = []
        cancel_event = threading.Event()
        cancel_observed = threading.Event()
        cancel_signal_at: list[float] = []
        timer: threading.Timer | None = None
        vram_lock = threading.Lock()
        vram_samples: list[dict[str, Any]] = []
        sampler_stop = threading.Event()
        sampler_thread: threading.Thread | None = None

        def capture_vram() -> None:
            callback = getattr(resource_sampler, "sample_vram", None)
            if not callable(callback):
                return
            try:
                sample = callback()
            except Exception:
                return
            if not isinstance(sample, dict) or sample.get("available") is not True:
                return
            used_mb = sample.get("vram_used_mb")
            total_mb = sample.get("vram_total_mb")
            if (
                isinstance(used_mb, bool) or not isinstance(used_mb, (int, float))
                or not math.isfinite(used_mb) or used_mb < 0
                or isinstance(total_mb, bool) or not isinstance(total_mb, (int, float))
                or not math.isfinite(total_mb) or total_mb <= 0
            ):
                return
            available_mb = sample.get("vram_available_mb")
            if (
                isinstance(available_mb, bool) or not isinstance(available_mb, (int, float))
                or not math.isfinite(available_mb) or available_mb < 0
            ):
                available_mb = max(0.0, float(total_mb) - float(used_mb))
            row = {
                "used_mb": float(used_mb),
                "total_mb": float(total_mb),
                "available_mb": min(float(total_mb), float(available_mb)),
            }
            pressure = sample.get("pressure_level")
            if isinstance(pressure, str) and pressure:
                row["pressure_level"] = pressure
            with vram_lock:
                vram_samples.append(row)

        def sample_vram_loop() -> None:
            while not sampler_stop.is_set():
                capture_vram()
                if sampler_stop.wait(0.1):
                    return

        def run_item(
            item: dict[str, str],
            *,
            request_model: str = model,
            source_suffix: str = name,
            inject_failure: bool = False,
            token_budget: int | None = None,
        ) -> dict[str, Any]:
            request_started = threading.Event()
            execute_finished = threading.Event()
            execution_finished_at: list[float] = []
            invocation_started_at = time.monotonic()
            absolute_deadline = invocation_started_at + timeout_seconds
            before_depth = queue_depth()
            if before_depth is not None:
                depth_observations.append(before_depth)

            def should_stop() -> bool:
                if cancel_event.is_set():
                    cancel_observed.set()
                    return True
                return False

            def execute() -> dict[str, Any]:
                nonlocal running_count, maximum_running, timer
                with running_lock:
                    running_count += 1
                    maximum_running = max(maximum_running, running_count)
                if inject_failure:
                    try:
                        return {"success": False, "error_type": "t12_injected_item_failure"}
                    finally:
                        with running_lock:
                            running_count = max(0, running_count - 1)
                        execution_finished_at.append(time.monotonic())
                        execute_finished.set()
                request_started.set()
                if name == "cancel" and timer is None:
                    timer = threading.Timer(cancel_after_ms / 1000, request_cancel)
                    timer.daemon = True
                    timer.start()
                try:
                    remaining = max(0.05, absolute_deadline - time.monotonic())
                    payload = {
                        "model": request_model,
                        "prompt": item["prompt"],
                        "stream": False,
                        "options": {
                            "num_predict": token_budget if token_budget is not None else max_tokens,
                            "temperature": 0.0,
                        },
                    }
                    if bool(self.config.get("ollama", {}).get("enabled", False)) and (
                        name != "fallback" or request_model != model
                    ):
                        payload["think"] = False
                    response = self.request_interruptible(
                        "/api/generate",
                        payload,
                        should_stop,
                        timeout=remaining,
                        deadline=absolute_deadline,
                    )
                    return response if isinstance(response, dict) else {"error": "runtime returned non-object"}
                finally:
                    with running_lock:
                        running_count = max(0, running_count - 1)
                    execution_finished_at.append(time.monotonic())
                    execute_finished.set()

            call_started_at = time.monotonic()
            scheduler_error: Exception | None = None
            scheduler_job: Any | None = None
            try:
                result = scheduler.submit(
                    request_model,
                    item["tenant"],
                    f"t12-{source_suffix}",
                    execute,
                    priority=2,
                    wait_timeout=timeout_seconds,
                    background=False,
                    cancel_event=cancel_event,
                )
            except Exception as exc:
                scheduler_error = exc
                scheduler_job = getattr(exc, "job", None)
                result = {"success": False, "error_type": type(exc).__name__}
                admission = getattr(exc, "admission", None)
                if isinstance(admission, dict):
                    result["admission"] = admission
            finished_at = time.monotonic()
            after_depth = queue_depth()
            if after_depth is not None:
                depth_observations.append(after_depth)
            response = result if isinstance(result, dict) else {"error": "scheduler returned non-object"}
            response_text = response.get("response", response.get("text", ""))
            response_text = response_text if isinstance(response_text, str) else ""
            admission = response.get("admission")
            admission = admission if isinstance(admission, dict) else {}
            queue_wait = response.get("_lah_scheduler_queue_wait_ms")
            queue_age = admission.get("queue_age_ms", queue_wait)
            fairness_wait = admission.get(
                "fairness_wait_ms", response.get("_lah_scheduler_fairness_wait_ms"),
            )
            return {
                "id": item["id"],
                "tenant": item["tenant"],
                "ok": bool(response_text) and not response.get("error") and not response.get("timed_out")
                and not response.get("preempted") and response.get("success") is not False,
                "response": response,
                "response_text": response_text,
                "elapsed_ms": max(0.0, (finished_at - call_started_at) * 1000),
                "call_started_at": call_started_at,
                "queue_wait_ms": queue_wait,
                "queue_age_ms": queue_age,
                "fairness_wait_ms": fairness_wait,
                "admission": admission,
                "scheduler_error": type(scheduler_error).__name__ if scheduler_error else "",
                "scheduler_job": scheduler_job,
                "request_started": request_started.is_set(),
                "execute_finished": execute_finished,
                "execution_finished_at": execution_finished_at,
                "request_finished_at": finished_at,
            }

        def run_many(selected_items: list[dict[str, str]], limit: int) -> list[dict[str, Any]]:
            with ThreadPoolExecutor(max_workers=max(1, min(limit, len(selected_items)))) as pool:
                futures = [pool.submit(run_item, item) for item in selected_items]
                return [future.result() for future in futures]

        if callable(getattr(resource_sampler, "sample_vram", None)):
            capture_vram()
            sampler_thread = threading.Thread(target=sample_vram_loop, name="t12-scenario-vram", daemon=True)
            sampler_thread.start()

        if name == "cancel":
            def request_cancel() -> None:
                cancel_signal_at.append(time.monotonic())
                cancel_event.set()

        scheduler_bucket_id: str | None = None
        scheduler_batch_size = 0
        if name in {"scheduler", "batch", "overload"}:
            selected_items = normalized_items
            if name == "overload":
                selected_items = normalized_items[:overload_count]
            if name == "scheduler":
                buckets: dict[str, list[dict[str, str]]] = {}
                for item in selected_items:
                    prompt_bytes = len(item["prompt"].encode("utf-8"))
                    bucket_limit = 1 << (max(1, prompt_bytes) - 1).bit_length()
                    bucket_id = f"prompt-bytes-p2-{bucket_limit}"
                    buckets.setdefault(bucket_id, []).append(item)
                scheduler_bucket_id, largest_bucket = max(
                    buckets.items(),
                    key=lambda pair: (len(pair[1]), pair[0]),
                )
                scheduler_batch_size = len(largest_bucket)
                records_by_id: dict[str, dict[str, Any]] = {}
                for bucket_items in buckets.values():
                    for row in run_many(bucket_items, concurrency_limit):
                        records_by_id[row["id"]] = row
                records = [records_by_id[item["id"]] for item in selected_items]
            elif name == "batch":
                with ThreadPoolExecutor(max_workers=max(1, min(concurrency_limit, len(selected_items)))) as pool:
                    futures = [
                        pool.submit(
                            run_item,
                            item,
                            inject_failure=item["id"] == failure_probe_item_id,
                        )
                        for item in selected_items
                    ]
                    records = [future.result() for future in futures]
            else:
                records = run_many(selected_items, concurrency_limit)
        else:
            records = [run_item(
                normalized_items[0],
                token_budget=source_max_tokens if name == "fallback" else None,
            )]
        if timer is not None:
            timer.cancel()
            timer.join(timeout=0.2)
        if sampler_thread is not None:
            sampler_stop.set()
            sampler_thread.join(timeout=1.0)
            capture_vram()

        metrics: dict[str, Any] = {}
        queue_waits = [
            float(row[key])
            for row in records
            for key in ("queue_wait_ms",)
            if isinstance(row.get(key), (int, float)) and not isinstance(row.get(key), bool)
        ]
        queue_ages = [
            float(row["queue_age_ms"])
            for row in records
            if isinstance(row.get("queue_age_ms"), (int, float)) and not isinstance(row.get("queue_age_ms"), bool)
        ]
        if queue_waits:
            metrics["queue_wait_ms"] = round(sum(queue_waits) / len(queue_waits), 2)
        if queue_ages:
            metrics["queue_age_ms"] = round(sum(queue_ages) / len(queue_ages), 2)
        if records:
            metrics["end_to_end_latency_ms"] = round(
                sum(float(row["elapsed_ms"]) for row in records) / len(records), 2
            )
            metrics["batch_item_count"] = len(records)
            metrics["prefill_tokens"] = sum(
                int(row["response"]["prompt_eval_count"])
                for row in records
                if isinstance(row.get("response"), dict)
                and isinstance(row["response"].get("prompt_eval_count"), int)
                and not isinstance(row["response"].get("prompt_eval_count"), bool)
                and row["response"]["prompt_eval_count"] >= 0
            )
            admission_states = [
                str(row["admission"].get("state"))
                for row in records
                if isinstance(row.get("admission"), dict) and row["admission"].get("state")
            ]
            if admission_states:
                metrics["resource_admission"] = admission_states[-1]
            vram_admission_states = [
                row["admission"].get("vram_admission")
                for row in records
                if isinstance(row.get("admission"), dict)
                and row["admission"].get("vram_admission") in {"admitted", "rejected"}
            ]
            if len(vram_admission_states) == len(records):
                metrics["vram_admission"] = (
                    "admitted" if all(state == "admitted" for state in vram_admission_states) else "rejected"
                )
            estimate_sources = [
                str(row["admission"].get("vram_estimate_source", "unknown"))
                for row in records
                if isinstance(row.get("admission"), dict)
            ]
            if estimate_sources:
                recognized_sources = {"measured", "configured", "resident"}
                complete_sources = (
                    len(estimate_sources) == len(records)
                    and all(source in recognized_sources for source in estimate_sources)
                )
                metrics["vram_estimate_source"] = (
                    (estimate_sources[0] if len(set(estimate_sources)) == 1 else "mixed")
                    if complete_sources else "unknown"
                )
            admission_pairs = []
            for row in records:
                admission = row.get("admission")
                if not isinstance(admission, dict):
                    continue
                budget = admission.get("vram_admission_budget_bytes")
                required = admission.get("vram_incremental_required_bytes")
                if (
                    isinstance(budget, int) and not isinstance(budget, bool)
                    and isinstance(required, int) and not isinstance(required, bool)
                ):
                    admission_pairs.append((budget, required))
            if len(admission_pairs) == len(records):
                # Keep budget and demand from same request. Combining smallest
                # resident budget with largest cold demand creates impossible evidence.
                worst_budget, worst_required = max(admission_pairs, key=lambda pair: pair[1])
                metrics["vram_admission_budget_bytes"] = worst_budget
                metrics["vram_incremental_required_bytes"] = worst_required
        if name == "scheduler" and scheduler_bucket_id is not None:
            metrics["bucket_id"] = scheduler_bucket_id
            metrics["batch_size"] = scheduler_batch_size
        with vram_lock:
            observed_vram = list(vram_samples)
        if observed_vram:
            metrics["peak_vram_bytes"] = int(round(max(row["used_mb"] for row in observed_vram) * 1024 * 1024))
            metrics["vram_budget_bytes"] = int(round(min(row["total_mb"] for row in observed_vram) * 1024 * 1024))
            metrics["vram_available_bytes"] = int(
                round(min(row["available_mb"] for row in observed_vram) * 1024 * 1024)
            )
            pressure_levels = [row["pressure_level"] for row in observed_vram if row.get("pressure_level")]
            if pressure_levels:
                metrics["vram_pressure_level"] = pressure_levels[-1]
        runtime_owner = getattr(scheduler, "runtime", self)
        loaded_details = getattr(runtime_owner, "loaded_model_details", None)
        if callable(loaded_details):
            try:
                rows = loaded_details()
            except Exception:
                rows = []
            matching_vram = [
                row["vram_bytes"]
                for row in rows
                if isinstance(row, dict)
                and str(row.get("name", row.get("model", ""))).strip().casefold() == model.strip().casefold()
                and isinstance(row.get("vram_bytes"), (int, float))
                and not isinstance(row.get("vram_bytes"), bool)
                and math.isfinite(row["vram_bytes"])
                and row["vram_bytes"] > 0
            ] if isinstance(rows, list) else []
            if matching_vram:
                metrics["vram_required_bytes"] = int(sum(matching_vram))
        fairness_waits = [
            float(row["fairness_wait_ms"])
            for row in records
            if isinstance(row.get("fairness_wait_ms"), (int, float))
            and not isinstance(row.get("fairness_wait_ms"), bool)
            and math.isfinite(float(row["fairness_wait_ms"]))
        ]
        if fairness_waits:
            metrics["fairness_wait_ms"] = round(sum(fairness_waits) / len(fairness_waits), 2)

        if name == "batch":
            statuses = ["success" if row["ok"] else "failed" for row in records]
            metrics.update({
                "input_item_ids": [item["id"] for item in normalized_items],
                "result_item_ids": [row["id"] for row in records],
                "item_statuses": statuses,
                "partial_failure_count": sum(status == "failed" for status in statuses),
                "max_concurrency": maximum_running,
                "concurrency_limit": concurrency_limit,
                "failure_probe_item_id": failure_probe_item_id,
                "failure_probe_observed": any(
                    row["id"] == failure_probe_item_id and not row["ok"] for row in records
                ),
            })

        if name == "overload":
            rejected_count = sum(
                isinstance(row.get("admission"), dict)
                and row["admission"].get("state") == "rejected"
                and row["admission"].get("reason") == "queue_limit"
                for row in records
            )
            resource_rejected_count = sum(
                isinstance(row.get("admission"), dict)
                and row["admission"].get("state") == "rejected"
                and row["admission"].get("reason") != "queue_limit"
                for row in records
            )
            queued_count = sum(
                any(
                    isinstance(row.get(field), (int, float))
                    and not isinstance(row.get(field), bool)
                    and row[field] > 0
                    for field in ("queue_wait_ms", "queue_age_ms")
                )
                for row in records
            )
            queue_depth_max = max(depth_observations) if depth_observations else None
            metrics["overloaded"] = bool(rejected_count or queued_count or (queue_depth_max or 0) > 0)
            metrics["queue_admission"] = (
                "rejected" if rejected_count
                else "queued" if queued_count or (queue_depth_max or 0) > 0
                else "resource_rejected" if resource_rejected_count
                else "not_observed"
            )
            metrics["queued_count"] = queued_count
            metrics["rejected_count"] = rejected_count
            metrics["resource_rejected_count"] = resource_rejected_count
            if queue_depth_max is not None:
                metrics["queue_depth"] = queue_depth_max

        if name == "deadline":
            record = records[0]
            response = record["response"]
            stage_timings: dict[str, float] = {}
            if isinstance(record.get("queue_age_ms"), (int, float)) and not isinstance(record.get("queue_age_ms"), bool):
                stage_timings["queue"] = round(float(record["queue_age_ms"]), 2)
            load_duration = response.get("load_duration") if isinstance(response, dict) else None
            if isinstance(load_duration, (int, float)) and not isinstance(load_duration, bool) and load_duration >= 0:
                stage_timings["model_load"] = round(float(load_duration) / 1_000_000, 2)
            eval_duration = response.get("eval_duration") if isinstance(response, dict) else None
            if isinstance(eval_duration, (int, float)) and not isinstance(eval_duration, bool) and eval_duration >= 0:
                stage_timings["generation"] = round(float(eval_duration) / 1_000_000, 2)
            within_deadline = bool(record["elapsed_ms"] <= deadline_ms)
            stage_names = [stage for stage in ("queue", "model_load", "generation") if stage in stage_timings]
            if record["elapsed_ms"] > deadline_ms:
                queue_ms = stage_timings.get("queue", 0.0)
                load_ms = stage_timings.get("model_load", 0.0)
                if queue_ms >= deadline_ms:
                    deadline_stage = "queue"
                elif queue_ms + load_ms >= deadline_ms:
                    deadline_stage = "model_load"
                else:
                    deadline_stage = "generation"
            else:
                deadline_stage = stage_names[-1] if stage_names else "queue"
            metrics.update({
                "deadline_ms": deadline_ms,
                "stages": stage_names,
                "stage_timings_ms": stage_timings,
                "deadline_stage": deadline_stage,
                "completed_within_deadline": within_deadline,
                "request_succeeded": bool(record["ok"]),
            })

        if name == "cancel":
            record = records[0]
            cancellation_requested = cancel_event.is_set()
            scheduler_job = record["scheduler_job"]
            scheduler_job_done = getattr(scheduler_job, "done", None)
            if cancellation_requested and hasattr(scheduler_job_done, "wait"):
                scheduler_job_done.wait(timeout=min(2.0, timeout_seconds))
                cleanup_complete = bool(scheduler_job_done.is_set()) and (
                    not record["request_started"] or record["execute_finished"].is_set()
                )
            elif cancellation_requested and record["request_started"]:
                record["execute_finished"].wait(timeout=min(2.0, timeout_seconds))
                cleanup_complete = record["execute_finished"].is_set()
            else:
                cleanup_complete = False
            cancelled = bool(
                cancellation_requested
                and (cancel_observed.is_set() or not record["request_started"] and cleanup_complete)
            )
            metrics.update({
                "cancel_requested": cancellation_requested,
                "cancelled": cancelled,
                "cleanup_complete": cleanup_complete,
            })
            if cancellation_requested and cancel_signal_at:
                if cleanup_complete and record["execution_finished_at"]:
                    stopped_at = record["execution_finished_at"][0]
                elif cleanup_complete and scheduler_job is not None and getattr(scheduler_job, "finished_at", 0):
                    stopped_at = float(scheduler_job.finished_at)
                else:
                    stopped_at = time.monotonic()
                metrics["cancel_to_stop_ms"] = round(max(0.0, (stopped_at - cancel_signal_at[0]) * 1000), 2)

        if name == "fallback":
            primary = records[0]
            def quality(row: dict[str, Any]) -> float | None:
                if not row["ok"]:
                    return None
                try:
                    output = json.loads(row["response_text"])
                    evaluation = model_quality.evaluate_case("benchmark", [], output, expected)
                    return round(float(evaluation.get("grounded_relevance", 0.0)) * 100, 2)
                except (TypeError, ValueError, AttributeError):
                    return 0.0

            primary_quality = quality(primary)
            fallback_record: dict[str, Any] | None = None
            if primary_quality is None or primary_quality < float(floor):
                fallback_record = run_item(
                    normalized_items[0],
                    request_model=fallback_model,
                    source_suffix="fallback",
                    token_budget=fallback_max_tokens,
                )
            fallback_quality = quality(fallback_record) if fallback_record is not None else None
            fallback_response = fallback_record["response"] if fallback_record is not None else {}
            fallback_provider = fallback_response.get("_lah_provider") if isinstance(fallback_response, dict) else None
            if not isinstance(fallback_provider, str) or not fallback_provider:
                fallback_provider = "ollama" if bool(self.config.get("ollama", {}).get("enabled", False)) else "llama.cpp"
            metrics.update({
                "fallback_used": fallback_record is not None,
                "fallback_visible": bool(fallback_record and fallback_record["ok"] and isinstance(fallback_provider, str) and fallback_provider),
                "quality_floor_met": bool(
                    fallback_quality is not None and fallback_quality >= float(floor)
                    or fallback_record is None and primary_quality is not None and primary_quality >= float(floor)
                ),
                "source_profile": profile,
                "fallback_profile": fallback_profile,
                "quality_floor_pct": float(floor),
                "source_model": model,
                "fallback_model": fallback_model,
                "source_max_tokens": source_max_tokens,
                "fallback_max_tokens": fallback_max_tokens,
                "source_quality_pct": primary_quality if primary_quality is not None else 0.0,
                "source_quality_status": "scored" if primary_quality is not None else "no_valid_response",
            })
            if fallback_record is not None:
                metrics["fallback_latency_ms"] = round(float(fallback_record["elapsed_ms"]), 2)
                metrics["fallback_total_latency_ms"] = round(
                    max(0.0, (time.monotonic() - float(primary["call_started_at"])) * 1000), 2
                )
            if fallback_quality is not None:
                metrics["fallback_quality_pct"] = fallback_quality
            source_provider = primary["response"].get("_lah_provider")
            if not isinstance(source_provider, str) or not source_provider:
                source_provider = "ollama" if bool(self.config.get("ollama", {}).get("enabled", False)) else "llama.cpp"
            metrics["source_backend"] = source_provider
            metrics["fallback_backend"] = fallback_provider

        if name == "deadline" and set(metrics.get("stage_timings_ms", {})) != {"queue", "model_load", "generation"}:
            missing_fields = [
                stage for stage in ("queue", "model_load", "generation")
                if stage not in metrics.get("stage_timings_ms", {})
            ]
            return {"success": False, "scenario": name, "status": "unmeasured", "metrics": metrics, "missing_fields": missing_fields}
        complete = all(field in metrics and metrics[field] is not None for field in requested_fields)
        if not complete:
            missing_fields = [field for field in requested_fields if field not in metrics or metrics[field] is None]
            return {"success": False, "scenario": name, "status": "unmeasured", "metrics": metrics, "missing_fields": missing_fields}
        observed_fields = {
            "queue_wait_ms", "queue_age_ms", "resource_admission", "prefill_tokens", "fairness_wait_ms",
            "peak_vram_bytes", "vram_budget_bytes", "vram_available_bytes", "vram_required_bytes", "vram_pressure_level",
            "end_to_end_latency_ms", "fallback_latency_ms", "fallback_total_latency_ms",
            "item_statuses", "partial_failure_count", "max_concurrency",
            "failure_probe_item_id", "failure_probe_observed",
            "overloaded", "queue_admission", "queue_depth", "stage_timings_ms", "deadline_stage",
            "completed_within_deadline", "cancel_requested", "cancelled", "cleanup_complete", "cancel_to_stop_ms",
            "fallback_used", "fallback_visible", "fallback_quality_pct", "source_backend", "fallback_backend",
            "source_model", "fallback_model", "source_profile", "fallback_profile", "source_quality_pct",
            "source_quality_status", "quality_floor_pct", "quality_floor_met",
        }
        receipt_fields = observed_fields.union(requested_fields)
        observed_metrics = {field: metrics[field] for field in sorted(receipt_fields) if field in metrics}
        if not observed_metrics:
            return {"success": False, "error_type": "scenario_observation_unavailable"}
        try:
            receipt_material = json.dumps(
                {"scenario": name, "model": model, "profile": profile, "observed_metrics": observed_metrics},
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError):
            return {"success": False, "error_type": "scenario_measurement_invalid"}
        receipt_id = "t12:" + hashlib.sha256(receipt_material).hexdigest()
        return {
            "success": True,
            "scenario": name,
            "status": "measured",
            "metrics": metrics,
            "receipt_id": receipt_id,
        }

    def request_interruptible(
        self, endpoint: str, payload: dict[str, Any] | None, should_stop: Any,
        *, timeout: float | None = None, deadline: float | None = None,
    ) -> dict[str, Any]:
        """Use shared streaming with one generic attempt and bounded OOM recovery.

        Cancellation, partial output and transport failures are never replayed here.
        A confirmed pre-output allocation failure may use the single reduced-context
        attempt within the original deadline, as on the foreground streaming path.
        """
        return self._request_stream_tracked(endpoint, payload, None, timeout,
                                            should_stop=should_stop, deadline=deadline,
                                            single_attempt=True)

    def is_online(self) -> bool:
        now = time.monotonic()
        if now - self._meta_cache_at.get("online", 0) < 1.0:
            return bool(self._meta_cache.get("online", False))
        online = self.version() is not None
        self._meta_cache["online"] = online
        self._meta_cache_at["online"] = now
        return online

    def _configured_environment(self) -> dict[str, str]:
        env = dict(os.environ)
        cfg = self.config.get("ollama", {})
        sched = self.config.get("scheduler", {})
        num_parallel = int(cfg.get("num_parallel", sched.get("max_parallel", 1)))
        env["OLLAMA_NUM_PARALLEL"] = str(num_parallel)
        env["OLLAMA_MAX_LOADED_MODELS"] = str(int(sched.get("max_loaded_models", 1)))
        if bool(cfg.get("allow_integrated_gpu", False)):
            env["OLLAMA_IGPU_ENABLE"] = "1"
        else:
            env.pop("OLLAMA_IGPU_ENABLE", None)
        # Vulkan is the portable Intel/AMD GPU path on Windows/Linux in Ollama.
        # It stays opt-in globally and is enabled by the conservative integrated
        # profile only; Ollama may still fall back to CPU when discovery fails.
        if bool(cfg.get("enable_vulkan", False)):
            env["OLLAMA_VULKAN"] = "1"
        else:
            env.pop("OLLAMA_VULKAN", None)
        if bool(cfg.get("flash_attention", True)):
            env["OLLAMA_FLASH_ATTENTION"] = "1"
        else:
            env.pop("OLLAMA_FLASH_ATTENTION", None)
        kv_cache = str(cfg.get("kv_cache_type", "q8_0")).strip()
        if kv_cache:
            env["OLLAMA_KV_CACHE_TYPE"] = kv_cache
        llm_library = str(cfg.get("llm_library", "")).strip()
        if llm_library:
            env["OLLAMA_LLM_LIBRARY"] = llm_library
        overhead = int(cfg.get("gpu_overhead_bytes", 0) or 0)
        if overhead > 0:
            env["OLLAMA_GPU_OVERHEAD"] = str(overhead)
        parsed = urlparse(self.base_url)
        if parsed.hostname:
            host = parsed.hostname
            if ":" in host and not host.startswith("["):
                host = f"[{host}]"
            env["OLLAMA_HOST"] = f"{host}:{parsed.port or 11434}"
        keep_alive = str(cfg.get("keep_alive", "")).strip()
        if keep_alive:
            env["OLLAMA_KEEP_ALIVE"] = keep_alive
        else:
            env.setdefault("OLLAMA_KEEP_ALIVE", "-1m")
        num_threads = cfg.get("num_threads")
        if num_threads:
            env["OLLAMA_NUM_THREADS"] = str(int(num_threads))
        return env

    def _read_managed_owner(self) -> dict[str, Any] | None:
        try:
            if self.managed_owner_path.stat().st_size > 16_384:
                return None
            owner = json.loads(self.managed_owner_path.read_text(encoding="utf-8"))
            return owner if isinstance(owner, dict) else None
        except (OSError, ValueError):
            return None

    def _remove_managed_markers(self, owner: dict[str, Any]) -> bool:
        # Called while holding the cross-process kernel lock. Never erase a
        # replacement owner's record after an uncertain cleanup.
        if not self.managed_owner_path.exists() and not self.managed_pid_path.exists():
            return True
        if self._read_managed_owner() != owner:
            return False
        try:
            if self.managed_pid_path.exists():
                if self.managed_pid_path.read_text(encoding="utf-8").strip() != str(owner["pid"]):
                    return False
                self.managed_pid_path.unlink()
            self.managed_owner_path.unlink()
            return True
        except (OSError, KeyError):
            return False

    def _cleanup_failed_start(self, proc: subprocess.Popen[Any]) -> bool:
        """Reap a child whose endpoint never became healthy."""
        try:
            running = proc.poll() is None
        except Exception:
            running = True
        tree_stopped = False
        if running or os.name == "nt":
            try:
                tree_stopped = terminate_tree(
                    proc.pid,
                    grace_seconds=2.0,
                    process_handle=proc,
                )
            except Exception:
                pass
        reaped = False
        try:
            proc.wait(timeout=3.0)
            reaped = True
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
            try:
                proc.wait(timeout=1.0)
                reaped = True
            except Exception:
                pass
        if not reaped or not tree_stopped:
            self._managed_process = proc
            return False
        if self._managed_process is proc:
            self._managed_process = None
        owner = self._managed_owner
        if owner is not None:
            removed = self._remove_managed_markers(owner)
            if removed:
                self._managed_owner = None
            return removed
        try:
            if self.managed_pid_path.read_text(encoding="utf-8").strip() == str(proc.pid):
                self.managed_pid_path.unlink(missing_ok=True)
        except (OSError, ValueError):
            pass
        return True

    def ensure_running(self) -> bool:
        if llama_cpp_managed_selected(self.config):
            return self.llama_cpp_managed.ensure_running()
        if not bool(self.config.get("ollama", {}).get("enabled", False)):
            return self.llama_cpp.is_online()
        if not bool(self.config.get("llama_cpp", {}).get("fallback_to_ollama", True)):
            return False
        # An already-running endpoint is borrowed. PID/name/port discovery
        # never grants permission to stop it or apply a different profile.
        if self.is_online():
            return True
        if not bool(self.config.get("headless", {}).get("autostart_ollama", True)):
            return False
        try:
            with self._ensure_lock, managed_process_lock(self.managed_lock_path) as acquired:
                return self._start_managed_server_locked() if acquired else False
        except OSError:
            return False

    def _start_managed_server_locked(self) -> bool:
        if self.is_online():
            return True
        if not self._stop_managed_server_locked():
            return False

        env = self._configured_environment()
        executable = self.config.get("ollama", {}).get("executable") or "ollama"
        args = [executable, "serve"]
        popen_kwargs: dict[str, Any] = hidden_run_kwargs(new_group=True)
        if os.name != "nt":
            popen_kwargs["start_new_session"] = True
        proc: subprocess.Popen[Any] | None = None
        try:
            job_name = f"Local\\LocalAIHubManaged-{uuid.uuid4().hex}" if os.name == "nt" else None
            proc = popen_managed(
                args, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, job_name=job_name, **popen_kwargs,
            )
            self._managed_process = proc
            owner = process_owner_record(proc.pid, self.state_dir, self.managed_name)
            if owner is None:
                raise OSError("Cannot retain managed Ollama process identity")
            if job_name:
                owner["windows_job_name"] = job_name
            owner["profile"] = self._expected_managed_profile()
            atomic_write_file(self.managed_owner_path, json_dumps(owner))
            self._managed_owner = owner
            priority = str(self.config.get("ollama", {}).get("process_priority", "") or "")
            if not priority and self.managed_name.startswith("ollama-background"):
                priority = str(self.config.get("background_gpu", {}).get("process_priority", "") or "")
            set_process_priority(proc.pid, priority)
            atomic_write_file(self.managed_pid_path, str(proc.pid))
        except Exception:
            if proc is not None:
                self._cleanup_failed_start(proc)
            return False

        startup_timeout = max(1.0, float(self.config.get("ollama", {}).get("startup_timeout_seconds", 12.0)))
        deadline = time.monotonic() + startup_timeout
        while time.monotonic() < deadline:
            if self.is_online():
                return True
            if proc.poll() is not None:
                break
            time.sleep(min(0.4, max(0.05, deadline - time.monotonic())))
        if self.is_online():
            return True
        self._cleanup_failed_start(proc)
        return False

    def _expected_managed_profile(self) -> dict[str, Any]:
        cfg = self.config.get("ollama", {})
        sched = self.config.get("scheduler", {})
        return {
            "num_parallel": int(cfg.get("num_parallel", sched.get("max_parallel", 1))),
            "max_loaded_models": int(sched.get("max_loaded_models", 1)),
            "allow_integrated_gpu": bool(cfg.get("allow_integrated_gpu", False)),
            "enable_vulkan": bool(cfg.get("enable_vulkan", False)),
            "flash_attention": bool(cfg.get("flash_attention", True)),
            "kv_cache_type": str(cfg.get("kv_cache_type", "q8_0")),
            "gpu_overhead_bytes": int(cfg.get("gpu_overhead_bytes", 0) or 0),
        }

    def managed_profile_status(self) -> dict[str, Any]:
        owner = self._read_managed_owner()
        managed = owner is not None and process_owner_state(owner, self.state_dir, self.managed_name) == "owned"
        expected = self._expected_managed_profile()
        return {
            "managed": managed,
            "managed_name": self.managed_name,
            "url": self.base_url,
            "pid": owner["pid"] if managed else None,
            "profile_verifiable": bool(managed and owner.get("profile") == expected),
            "expected": expected,
            "llama_cpp": {
                "mode": str(self.config.get("llama_cpp", {}).get("mode", "auto")),
                "online_models": self.llama_cpp.available_models(),
                **self.llama_cpp_managed.status(),
            },
        }

    def stop_managed_server(self) -> bool:
        if llama_cpp_managed_selected(self.config):
            return self.llama_cpp_managed.stop()
        try:
            with self._ensure_lock:
                if (self._managed_process is None and not self.managed_owner_path.exists()
                        and not self.managed_pid_path.exists() and not self.managed_lock_path.exists()):
                    return True
                with managed_process_lock(self.managed_lock_path) as acquired:
                    return self._stop_managed_server_locked() if acquired else False
        except OSError:
            return False

    def _stop_managed_server_locked(self) -> bool:
        owner = self._read_managed_owner()
        process = self._managed_process
        if process is not None:
            return self._cleanup_failed_start(process)
        if owner is None:
            if self.managed_owner_path.exists():
                return False
            try:
                pid = int(self.managed_pid_path.read_text(encoding="utf-8").strip() or 0)
            except FileNotFoundError:
                return True
            except (OSError, ValueError):
                return False
            if pid > 0 and pid_alive(pid):
                return False  # A numeric PID is not an owner record.
            try:
                self.managed_pid_path.unlink(missing_ok=True)
                return True
            except OSError:
                return False
        state = process_owner_state(owner, self.state_dir, self.managed_name)
        name = owner.get("windows_job_name", "")
        if state == "unknown" or os.name != "nt" or not re.fullmatch(r"Local\\LocalAIHubManaged-[0-9a-f]{32}", str(name)):
            return False
        job = None
        try:
            job = open_named_job_object(name)
            if job is None:
                return self._remove_managed_markers(owner) if state == "stale" else False
            if state == "stale":
                return self._remove_managed_markers(owner) if wait_job_object_empty(job, 0) else False
            if not windows_job_contains_process(job, int(owner["pid"]), owner):
                return False
            if not terminate_job_object(job) or not wait_job_object_empty(job, 5000):
                return False
            return self._remove_managed_markers(owner)
        except (OSError, ValueError, TypeError, KeyError):
            return False
        finally:
            if job is not None:
                close_job_object(job)

    def version(self) -> str | None:
        now = time.monotonic()
        if now - self._meta_cache_at.get("version", 0) < 5.0 and "version" in self._meta_cache:
            return self._meta_cache.get("version")
        v = None
        if bool(self.config.get("ollama", {}).get("enabled", False)):
            result = self.request("/api/version", timeout=1.0)
            v = result.get("version") if "error" not in result else None
            if v:
                self._meta_cache["version"] = v
                self._meta_cache_at["version"] = now
                return v
        if self.llama_cpp.is_online():
            v = self._llama_version_label()
        self._meta_cache["version"] = v
        self._meta_cache_at["version"] = now
        return v

    def _online_llama_cpp_models(self) -> list[str] | None:
        router = getattr(self, "llama_cpp", None)
        is_online = getattr(router, "is_online", None)
        available_models = getattr(router, "available_models", None)
        if not callable(is_online) or not callable(available_models):
            return None
        try:
            if not is_online():
                return None
            return [str(model) for model in available_models() if str(model).strip()]
        except Exception:
            return None

    def installed_models(self) -> list[str]:
        now = time.monotonic()
        if now - self._meta_cache_at.get("installed", 0) < 5.0 and "installed" in self._meta_cache:
            return list(self._meta_cache.get("installed", []))
        result = self.request("/api/tags", timeout=1.0)
        if "error" not in result and "models" in result:
            models = [m.get("name", "") for m in result.get("models", []) if m.get("name")]
            self._meta_cache["installed"] = models
            self._meta_cache_at["installed"] = now
            return models
        llama_models = self._online_llama_cpp_models()
        if llama_models is not None:
            self._meta_cache["installed"] = llama_models
            self._meta_cache_at["installed"] = now
            return llama_models
        return list(self._meta_cache.get("installed", []))

    def model_digest(self, model: str) -> str | None:
        """Return the installed Ollama digest for an exact model name."""
        target = str(model or "").strip().casefold()
        if not target:
            return None
        now = time.monotonic()
        meta_cache = getattr(self, "_meta_cache", None)
        meta_cache = meta_cache if isinstance(meta_cache, dict) else {}
        cache_at = getattr(self, "_meta_cache_at", None)
        cache_at = cache_at if isinstance(cache_at, dict) else {}
        cached = meta_cache.get("model_digests")
        if (
            now - cache_at.get("model_digests", 0) < 5.0
            and isinstance(cached, dict)
        ):
            return cached.get(target)

        result = self.request("/api/tags", timeout=1.0)
        digests: dict[str, str] = {}
        rows = result.get("models") if isinstance(result, dict) else None
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                name = row.get("name")
                digest = row.get("digest")
                if not isinstance(name, str) or not isinstance(digest, str):
                    continue
                normalized_digest = digest[7:] if digest.startswith("sha256:") else digest
                if len(normalized_digest) == 64 and all(
                    char in "0123456789abcdefABCDEF" for char in normalized_digest
                ):
                    digests[name.strip().casefold()] = normalized_digest.lower()
        self._meta_cache = meta_cache
        self._meta_cache_at = cache_at
        meta_cache["model_digests"] = digests
        cache_at["model_digests"] = now
        return digests.get(target)

    def loaded_models(self) -> list[str]:
        details = self.loaded_model_details()
        return [d["name"] for d in details if d.get("name")]

    def loaded_model_details(
        self,
        *,
        should_stop: Any | None = None,
        deadline: float | None = None,
        force_refresh: bool = False,
    ) -> list[dict[str, Any]]:
        now = time.monotonic()
        if (
            not force_refresh
            and now - self._meta_cache_at.get("loaded_details", 0) < 2.0
            and "loaded_details" in self._meta_cache
        ):
            return list(self._meta_cache.get("loaded_details", []))
        result = self.request("/api/ps", timeout=1.0, should_stop=should_stop, deadline=deadline)
        if result.get("preempted") or _stop_requested(should_stop):
            raise ModelPreparationCancelled("model preparation cancelled while checking loaded models")
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("model preparation deadline expired while checking loaded models")
        if "error" in result or not isinstance(result, dict):
            if should_stop is not None or deadline is not None:
                llama_rows = self.llama_cpp.loaded_model_details(
                    should_stop=should_stop, deadline=deadline,
                )
                if _stop_requested(should_stop):
                    raise ModelPreparationCancelled("model preparation cancelled while checking adapter models")
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError("model preparation deadline expired while checking adapter models")
                return llama_rows or list(self._meta_cache.get("loaded_details", []))
            llama_rows = self.llama_cpp.loaded_model_details()
            return llama_rows or list(self._meta_cache.get("loaded_details", []))
        rows: list[dict[str, Any]] = []
        for raw in result.get("models", []):
            if not isinstance(raw, dict):
                continue
            details = raw.get("details", {}) if isinstance(raw.get("details"), dict) else {}
            size = int(raw.get("size", 0) or 0)
            vram = int(raw.get("size_vram", 0) or 0)
            cpu = max(0, size - vram)
            rows.append({
                "name": str(raw.get("name", raw.get("model", ""))),
                "parameter_size": str(details.get("parameter_size", "")),
                "quantization": str(details.get("quantization_level", "")),
                "size_bytes": size,
                "vram_bytes": vram,
                "cpu_bytes": cpu,
                "gpu_fraction": round((vram / size), 4) if size > 0 else 0.0,
                "cpu_offload_fraction": round((cpu / size), 4) if size > 0 else 0.0,
                "context_length": int(raw.get("context_length", 0) or 0),
                "expires_at": raw.get("expires_at"),
            })
        self._meta_cache["loaded_details"] = rows
        self._meta_cache_at["loaded_details"] = now
        return rows

    def _invalidate_loaded_cache(self) -> None:
        self._meta_cache.pop("loaded_details", None)
        self._meta_cache_at.pop("loaded_details", None)

    def prepare_model(
        self,
        model: str,
        *,
        unload_others: bool = True,
        post_unload_admission: Any | None = None,
        should_stop: Any | None = None,
        deadline: float | None = None,
    ) -> list[str]:
        """Ensure ``model`` is resident with the execution policy's context size.

        The scheduler treats this as the authoritative model-switch primitive. Keep
        the method in the runtime rather than duplicating load/unload/context logic in
        scheduler/background callers so all adapters share one contract.
        """
        model = str(model or "").strip()
        if not model:
            raise ValueError("model is required")

        load_timeout = max(0.05, float(self.config.get("llama_cpp", {}).get("model_load_timeout_seconds", 90)))
        prepare_deadline = time.monotonic() + load_timeout
        if deadline is not None:
            prepare_deadline = min(prepare_deadline, float(deadline))

        def stopped() -> bool:
            return _stop_requested(should_stop)

        def check_active() -> None:
            if stopped():
                raise ModelPreparationCancelled("model preparation cancelled")
            if time.monotonic() >= prepare_deadline:
                raise TimeoutError("model preparation deadline expired")

        check_active()
        # llama.cpp loads the configured GGUF in its local server. Avoid also
        # loading that same model into Ollama when the SYCL endpoint is ready.
        if post_unload_admission is not None and self.llama_cpp.supports_model(model):
            raise ModelPreparationAdmissionRejected({
                "state": "rejected", "reason": "post_unload_admission_unsupported_backend",
                "vram_admission": "rejected", "vram_admission_phase": "post_unload",
            })
        if self.llama_cpp.ensure_model(
            model,
            timeout=max(0.05, min(load_timeout, prepare_deadline - time.monotonic())),
            should_stop=stopped,
            deadline=prepare_deadline,
        ):
            return []
        check_active()
        if not bool(self.config.get("llama_cpp", {}).get("fallback_to_ollama", True)) and self.llama_cpp.supports_model(model):
            raise RuntimeError("configured llama.cpp SYCL model is not available")
        if not self.ensure_running():
            raise RuntimeError("Ollama is not available")
        check_active()

        profile = self.model_policy.profile(model)
        details = self.loaded_model_details(should_stop=stopped, deadline=prepare_deadline)
        check_active()
        evicted: list[str] = []
        current = next((row for row in details if str(row.get("name", "")) == model), None)

        if unload_others:
            for row in details:
                check_active()
                name = str(row.get("name", "") or "")
                if name and name != model and self.unload_model(name, should_stop=stopped, deadline=prepare_deadline):
                    evicted.append(name)
                check_active()

        if current is not None and int(current.get("context_length", 0) or 0) >= profile.num_ctx:
            return evicted

        # A runner loaded with a smaller context cannot be safely reused for a larger
        # request. Explicitly unload it so Ollama recreates the runner with num_ctx.
        if current is not None:
            check_active()
            if self.unload_model(model, should_stop=stopped, deadline=prepare_deadline):
                evicted.append(model)
            check_active()

        if post_unload_admission is not None:
            check_active()
            try:
                admission = post_unload_admission()
            except Exception as exc:
                raise ModelPreparationAdmissionRejected({
                    "state": "rejected", "reason": "post_unload_admission_failed",
                    "vram_admission": "rejected", "vram_admission_phase": "post_unload",
                    "failure_type": type(exc).__name__,
                }, evicted) from exc
            if not isinstance(admission, dict) or admission.get("state") != "admitted":
                rejected_admission = dict(admission) if isinstance(admission, dict) else {}
                rejected_admission["state"] = "rejected"
                rejected_admission.setdefault("reason", "post_unload_admission_rejected")
                rejected_admission.setdefault("vram_admission", "rejected")
                rejected_admission.setdefault("vram_admission_phase", "post_unload")
                raise ModelPreparationAdmissionRejected(rejected_admission, evicted)
            check_active()

        keep_alive = self.config.get("ollama", {}).get("keep_alive", "24h")
        if self._is_embedding_model(model):
            payload = {"model": model, "input": [""], "keep_alive": keep_alive}
            result = self.request(
                "/api/embed", payload,
                timeout=max(0.05, min(self.timeout, prepare_deadline - time.monotonic())),
                should_stop=stopped, deadline=prepare_deadline,
            )
        else:
            payload = {
                "model": model,
                "prompt": "",
                "stream": False,
                "keep_alive": keep_alive,
                "options": {"num_ctx": profile.num_ctx},
            }
            result = self.request(
                "/api/generate", payload,
                timeout=max(0.05, min(self.timeout, prepare_deadline - time.monotonic())),
                should_stop=stopped, deadline=prepare_deadline,
            )
        if result.get("preempted") or stopped():
            raise ModelPreparationCancelled("model preparation cancelled")
        if time.monotonic() >= prepare_deadline:
            raise TimeoutError("model preparation deadline expired")
        if "error" in result:
            raise RuntimeError(str(result.get("error", "model load failed")))
        self._invalidate_loaded_cache()
        return evicted

    def supports_post_unload_admission(self, model: str) -> bool:
        """Whether this model uses Ollama's unload-then-load preparation path."""
        try:
            return not bool(self.llama_cpp.supports_model(model))
        except Exception:
            return False

    def unload(self, model: str) -> bool:
        """Scheduler-facing alias with cache invalidation."""
        return self.unload_model(model)

    def load_model(self, model: str, *, keep_alive: str | None = None) -> bool:
        if self.llama_cpp.supports_model(model):
            if self.llama_cpp.ensure_model(model, timeout=float(self.config.get("llama_cpp", {}).get("model_load_timeout_seconds", 600))):
                return True
            if not bool(self.config.get("llama_cpp", {}).get("fallback_to_ollama", True)):
                return False
        payload: dict[str, Any] = {"model": model}
        if keep_alive:
            payload["keep_alive"] = keep_alive
        endpoint = "/api/generate"
        if self._is_embedding_model(model):
            payload["input"] = [""]
            endpoint = "/api/embed"
        result = self.request(endpoint, payload)
        ok = "error" not in result
        if ok:
            self._invalidate_loaded_cache()
        return ok

    def unload_model(
        self,
        model: str,
        *,
        should_stop: Any | None = None,
        deadline: float | None = None,
    ) -> bool:
        if self.llama_cpp.supports_model(model) and (
            self.llama_cpp.ready_for_model(model)
            if should_stop is None and deadline is None
            else self.llama_cpp.ready_for_model(model, should_stop=should_stop, deadline=deadline)
        ):
            if should_stop is None and deadline is None:
                return self.llama_cpp.unload_model(model)
            return self.llama_cpp.unload_model(model, should_stop=should_stop, deadline=deadline)
        if not bool(self.config.get("llama_cpp", {}).get("fallback_to_ollama", True)):
            return False
        endpoint = "/api/generate"
        payload: dict[str, Any] = {"model": model, "keep_alive": 0}
        if self._is_embedding_model(model):
            payload["input"] = [""]
            endpoint = "/api/embed"
        result = self.request(endpoint, payload, should_stop=should_stop, deadline=deadline)
        ok = "error" not in result
        if ok:
            self._invalidate_loaded_cache()
        return ok

    def loaded_model_inventory(
        self,
        *,
        should_stop: Any | None = None,
        deadline: float | None = None,
        force_refresh: bool = True,
        include_llama: bool = True,
    ) -> dict[str, Any]:
        """Read fresh, endpoint-identified inventory without empty-on-error fallback."""
        backends: dict[str, dict[str, Any]] = {}
        rows: list[dict[str, Any]] = []
        errors: dict[str, str] = {}
        if bool(self.config.get("ollama", {}).get("enabled", False)):
            endpoint_id = self.base_url
            endpoint_status = "unknown"
            endpoint_rows: list[dict[str, Any]] = []
            try:
                if _stop_requested(should_stop):
                    raise InterruptedError("inventory cancelled")
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError("inventory deadline exceeded")
                response = self.request(
                    "/api/ps",
                    timeout=None if deadline is None else max(0.0, deadline - time.monotonic()),
                    should_stop=should_stop,
                    deadline=deadline,
                )
                if not isinstance(response, dict) or "error" in response or not isinstance(response.get("models"), list):
                    raise RuntimeError("Ollama inventory unavailable or malformed")
                malformed = False
                for index, row in enumerate(response["models"]):
                    if not isinstance(row, dict):
                        errors[f"ollama:{endpoint_id}:row:{index}"] = "model row is not an object"
                        malformed = True
                        continue
                    name = next(
                        (value.strip() for field in ("name", "model") if isinstance((value := row.get(field)), str) and value.strip()),
                        "",
                    )
                    if not name:
                        errors[f"ollama:{endpoint_id}:row:{index}"] = "model row has no usable name or model"
                        malformed = True
                        continue
                    endpoint_rows.append({**row, "name": name, "model": str(row.get("model") or name), "backend": "ollama", "endpoint_id": endpoint_id})
                endpoint_status = "unknown" if malformed else "complete"
                if malformed:
                    raise ValueError("Ollama inventory contains malformed model rows")
                rows.extend(endpoint_rows)
            except Exception as exc:
                errors.setdefault(f"ollama:{endpoint_id}", "cancelled" if _stop_requested(should_stop) else str(exc) or type(exc).__name__)
            backends["ollama"] = {
                "complete": endpoint_status == "complete",
                "endpoints": {endpoint_id: endpoint_status},
                "models": endpoint_rows,
            }

        llama_settings = self.config.get("llama_cpp", {})
        llama_models = llama_settings.get("models", {}) if isinstance(llama_settings, dict) else {}
        llama_mode = str(llama_settings.get("mode", "auto")).strip().lower() if isinstance(llama_settings, dict) else "off"
        if include_llama and llama_mode in {"auto", "on"} and isinstance(llama_models, dict) and llama_models:
            endpoint_status: dict[str, str] = {}
            endpoint_rows: list[dict[str, Any]] = []
            try:
                snapshot = self.llama_cpp.loaded_model_inventory(
                    should_stop=should_stop, deadline=deadline, force_refresh=force_refresh,
                )
                if not isinstance(snapshot, dict) or snapshot.get("complete") is not True or not isinstance(snapshot.get("models"), list):
                    raise RuntimeError("llama.cpp inventory incomplete")
                raw_endpoints = snapshot.get("endpoints")
                if not isinstance(raw_endpoints, dict) or any(value != "complete" for value in raw_endpoints.values()):
                    raise RuntimeError("llama.cpp endpoint inventory incomplete")
                endpoint_status = {str(key): str(value) for key, value in raw_endpoints.items()}
                for index, row in enumerate(snapshot["models"]):
                    if not isinstance(row, dict):
                        raise ValueError(f"llama.cpp model row {index} is not an object")
                    name = next(
                        (value.strip() for field in ("name", "model") if isinstance((value := row.get(field)), str) and value.strip()),
                        "",
                    )
                    endpoint_id = str(row.get("endpoint_url", "")).strip()
                    if not name or not endpoint_id or endpoint_status.get(endpoint_id) != "complete":
                        raise ValueError(f"llama.cpp model row {index} has incomplete identity")
                    endpoint_rows.append({**row, "name": name, "model": str(row.get("model") or name), "backend": "llama.cpp-sycl", "endpoint_id": endpoint_id})
                rows.extend(endpoint_rows)
            except Exception as exc:
                errors["llama.cpp"] = "cancelled" if _stop_requested(should_stop) else str(exc) or type(exc).__name__
                if not endpoint_status:
                    endpoint_status = {"llama.cpp": "unknown"}
            backends["llama_cpp"] = {
                "complete": not any(value != "complete" for value in endpoint_status.values()) and "llama.cpp" not in errors,
                "endpoints": endpoint_status,
                "models": endpoint_rows,
            }

        return {
            "complete": all(item["complete"] for item in backends.values()),
            "backend_available": bool(backends) and any(item["complete"] for item in backends.values()),
            "observed_at_monotonic": time.monotonic(),
            "backends": backends,
            "models": rows,
            "errors": errors,
        }

    def unload_inventory_model(
        self,
        row: dict[str, Any],
        *,
        should_stop: Any | None = None,
        deadline: float | None = None,
    ) -> bool:
        """Unload one inventory row through the backend and endpoint that owns it."""
        name = str(row.get("name") or row.get("model") or "").strip()
        if not name:
            return False
        backend = str(row.get("backend", ""))
        if backend == "ollama":
            response = self.request(
                "/api/generate", {"model": name, "prompt": "", "keep_alive": 0},
                timeout=None if deadline is None else max(0.0, deadline - time.monotonic()),
                should_stop=should_stop, deadline=deadline,
            )
            ok = isinstance(response, dict) and "error" not in response and response.get("done_reason") == "unload"
            if ok:
                self._invalidate_loaded_cache()
            return ok
        endpoint_url = str(row.get("endpoint_id") or row.get("endpoint_url") or "").strip()
        if backend == "llama.cpp-sycl" and endpoint_url:
            served = str(row.get("served_model") or name).strip()
            if served != name:
                resolve = getattr(self.llama_cpp, "recovery_alias_for_model", None)
                if not callable(resolve) or resolve(name) != served:
                    return False
            return bool(self.llama_cpp.unload_model(served, endpoint_url=endpoint_url, should_stop=should_stop, deadline=deadline))
        return False

    def unload_configured_models(
        self,
        *,
        timeout_seconds: float = 3.0,
        should_stop: Any | None = None,
        deadline: float | None = None,
        include_llama: bool = True,
    ) -> dict[str, Any]:
        """Request bounded unload and verify the resulting loaded-model state.

        Pause never starts a backend or loads a model. One deadline covers both
        ``/api/ps`` queries and all unload requests. An unload acknowledgement alone
        is not treated as proof that the model left the loaded set. An empty loaded
        set does not prove that physical VRAM was reclaimed.
        """
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be a finite positive number")

        timeout = min(float(timeout_seconds), _GAMING_UNLOAD_MAX_TIMEOUT_SECONDS)
        unload_deadline = time.monotonic() + timeout
        if deadline is not None:
            if isinstance(deadline, bool) or not isinstance(deadline, (int, float)) or not math.isfinite(deadline):
                raise ValueError("deadline must be a finite monotonic timestamp")
            unload_deadline = min(unload_deadline, float(deadline))
        unloaded: list[str] = []
        failed: dict[str, str] = {}
        ollama_enabled = bool(self.config.get("ollama", {}).get("enabled", False))
        ollama_endpoint = str(
            getattr(self, "base_url", "")
            or self.config.get("server", {}).get("ollama_url", "")
            or "default"
        ).rstrip("/")

        def request_ollama(endpoint: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
            remaining = max(0.0, unload_deadline - time.monotonic())
            return self.request(
                endpoint, payload, timeout=remaining,
                should_stop=should_stop, deadline=unload_deadline,
            )

        if _stop_requested(should_stop):
            return {
                "success": False,
                "backend_available": False,
                "unloaded": unloaded,
                "failed": {"operation": "unload cancelled"},
                "cancelled": True,
                "requested": [],
                "remaining": None,
                "verified": False,
                "complete": False,
                "unverified": True,
                "physical_vram_reclaimed": False,
            }
        if time.monotonic() >= unload_deadline:
            return {
                "success": False,
                "backend_available": False,
                "unloaded": unloaded,
                "failed": {"operation": "unload deadline exceeded"},
                "requested": [],
                "remaining": None,
                "verified": False,
                "complete": False,
                "unverified": True,
                "physical_vram_reclaimed": False,
            }

        llama_settings = self.config.get("llama_cpp", {})
        llama_models = llama_settings.get("models", {}) if isinstance(llama_settings, dict) else {}
        llama_mode = str(llama_settings.get("mode", "auto")).strip().lower() if isinstance(llama_settings, dict) else "off"
        llama_configured = llama_mode in {"auto", "on"} and isinstance(llama_models, dict) and bool(llama_models)
        # Pause checks every configured auto/on endpoint. A failed or empty
        # convenience probe cannot distinguish an empty inventory from failure.
        llama_active = include_llama and llama_configured

        backend_names = (["ollama"] if ollama_enabled else []) + (["llama_cpp"] if llama_active else [])
        if not backend_names:
            reason = "no configured llama.cpp models" if not llama_configured else "backend unavailable"
            return {
                "success": False, "backend_available": False, "unloaded": unloaded,
                "failed": {"backend": reason}, "requested": [], "remaining": None,
                "verified": False, "complete": False, "unverified": True,
                "physical_vram_reclaimed": False,
            }

        last_llama_endpoint_status: dict[str, str] = {}
        last_llama_urls: dict[str, str] = {}

        def read_llama_inventory() -> tuple[list[dict[str, Any]], dict[str, str]]:
            inventory_reader = getattr(self.llama_cpp, "loaded_model_inventory", None)
            if callable(inventory_reader):
                snapshot = inventory_reader(
                    should_stop=should_stop, deadline=unload_deadline, force_refresh=True,
                )
                if not isinstance(snapshot, dict):
                    raise RuntimeError("llama.cpp inventory incomplete")
                rows = snapshot.get("models")
                if not isinstance(rows, list):
                    raise RuntimeError("llama.cpp inventory incomplete")
                endpoint_status = snapshot.get("endpoint_status", {})
                if not isinstance(endpoint_status, dict):
                    raise RuntimeError("llama.cpp endpoint status unavailable")
                endpoints = snapshot.get("endpoints", {})
                if not isinstance(endpoints, dict):
                    raise RuntimeError("llama.cpp endpoint receipts unavailable")
                errors = snapshot.get("errors")
                if snapshot.get("complete") is not True or not isinstance(errors, dict) or errors:
                    raise RuntimeError("llama.cpp inventory incomplete")
                if not rows and not endpoint_status and not endpoints:
                    last_llama_endpoint_status.clear()
                    last_llama_urls.clear()
                    return rows, {}
                if (
                    not endpoints
                    or not endpoint_status
                    or any(
                        not isinstance(endpoint, str)
                        or not endpoint.strip()
                        or status != "complete"
                        for endpoint, status in endpoints.items()
                    )
                ):
                    raise RuntimeError("llama.cpp endpoint receipts unavailable")
                last_llama_endpoint_status.clear()
                last_llama_endpoint_status.update({str(key): str(value) for key, value in endpoint_status.items()})
                last_llama_urls.clear()
                last_llama_urls.update({str(key): str(value) for key, value in endpoints.items()})
                if any(
                    status != "complete" for status in endpoint_status.values()
                ):
                    raise RuntimeError("llama.cpp endpoint status unavailable")
                for index, row in enumerate(rows):
                    if (
                        not isinstance(row, dict)
                        or not isinstance(row.get("name") or row.get("model"), str)
                        or not (row.get("name") or row.get("model")).strip()
                        or row.get("endpoint_url") not in endpoints
                    ):
                        raise RuntimeError(f"llama.cpp inventory row {index} is incomplete")
                return rows, dict(last_llama_endpoint_status)
            raise RuntimeError("llama.cpp canonical inventory contract unavailable")

        loaded_rows_by_backend: dict[str, list[dict[str, Any]]] = {}
        failed_by_backend: dict[str, dict[str, str]] = {name: {} for name in backend_names}
        backend_inventory_ok: dict[str, bool] = {}
        backend_inventory_status: dict[str, dict[str, str]] = {}
        for backend in backend_names:
            if _stop_requested(should_stop):
                failed["operation"] = "unload cancelled"
                break
            if time.monotonic() >= unload_deadline:
                failed[backend] = "unload deadline exceeded before inventory"
                backend_inventory_ok[backend] = False
                continue
            try:
                if backend == "ollama":
                    response = request_ollama("/api/ps")
                    if not isinstance(response, dict) or "error" in response or not isinstance(response.get("models"), list):
                        raise RuntimeError("backend unavailable")
                    rows = response["models"]
                    backend_inventory_status[backend] = {"ollama": "complete"}
                else:
                    rows, backend_inventory_status[backend] = read_llama_inventory()
                if _stop_requested(should_stop):
                    raise InterruptedError("unload cancelled")
                loaded_rows_by_backend[backend] = rows
                backend_inventory_ok[backend] = True
            except Exception as exc:
                stopped = _stop_requested(should_stop)
                failed[backend] = "unload cancelled" if stopped else ("backend unavailable" if isinstance(exc, RuntimeError) else type(exc).__name__)
                backend_inventory_ok[backend] = False
                backend_inventory_status[backend] = (
                    dict(last_llama_endpoint_status) or {"llama.cpp": "unknown"}
                    if backend == "llama_cpp" else {"ollama": "unknown"}
                )

        loaded_by_backend: dict[str, list[str]] = {name: [] for name in backend_names}
        loaded_targets_by_backend: dict[str, list[tuple[str, str]]] = {name: [] for name in backend_names}
        requested_by_endpoint: dict[str, list[str]] = {}
        remaining_by_endpoint: dict[str, list[str] | None] = {}
        if "ollama" in backend_names:
            remaining_by_endpoint[f"ollama:{ollama_endpoint}"] = None
        for endpoint_url in last_llama_urls:
            remaining_by_endpoint[f"llama_cpp:{endpoint_url}"] = None
        for backend, rows in loaded_rows_by_backend.items():
            for row_index, row in enumerate(rows):
                if not isinstance(row, dict):
                    failed_by_backend[backend][f"model_row_{row_index}"] = "loaded model row is not an object"
                    backend_inventory_ok[backend] = False
                    if backend == "ollama":
                        backend_inventory_status[backend] = {"ollama": "unknown"}
                    continue
                model = next(
                    (value.strip() for field in ("name", "model") if isinstance((value := row.get(field)), str) and value.strip()),
                    "",
                )
                if not model:
                    failed_by_backend[backend][f"model_row_{row_index}"] = "loaded model row has no usable name or model"
                    backend_inventory_ok[backend] = False
                    if backend == "ollama":
                        backend_inventory_status[backend] = {"ollama": "unknown"}
                    continue
                endpoint_url = ollama_endpoint if backend == "ollama" else str(row.get("endpoint_url", "")).strip()
                if not endpoint_url:
                    failed_by_backend[backend][f"model_row_{row_index}"] = "loaded llama.cpp row has no endpoint identity"
                    backend_inventory_ok[backend] = False
                    for known_endpoint in list(last_llama_urls):
                        last_llama_urls[known_endpoint] = "unknown"
                    continue
                if (model, endpoint_url) not in loaded_targets_by_backend[backend]:
                    loaded_targets_by_backend[backend].append((model, endpoint_url))
                remaining_by_endpoint.setdefault(f"{backend}:{endpoint_url}", None)
                if model not in loaded_by_backend[backend]:
                    loaded_by_backend[backend].append(model)

        cancelled = bool(_stop_requested(should_stop))
        requested_by_backend: dict[str, list[str]] = {name: [] for name in backend_names}
        for backend, targets in loaded_targets_by_backend.items():
            for model_index, (model, endpoint_url) in enumerate(targets):
                if _stop_requested(should_stop):
                    cancelled = True
                    for pending, _endpoint in targets[model_index:]:
                        failed_by_backend[backend][pending] = "unload cancelled"
                    break
                if time.monotonic() >= unload_deadline:
                    failed_by_backend[backend][model] = "unload deadline exceeded"
                    continue
                requested_by_backend[backend].append(model)
                requested_by_endpoint.setdefault(f"{backend}:{endpoint_url}", []).append(model)
                try:
                    if backend == "ollama":
                        response = request_ollama(
                            "/api/generate", {"model": model, "prompt": "", "keep_alive": 0},
                        )
                        ok = isinstance(response, dict) and "error" not in response and response.get("done_reason") == "unload"
                        if ok:
                            self._invalidate_loaded_cache()
                    else:
                        ok = self.llama_cpp.unload_model(
                            model, endpoint_url=endpoint_url,
                            should_stop=should_stop, deadline=unload_deadline,
                        )
                except Exception as exc:
                    ok = False
                    failed_by_backend[backend][model] = "unload cancelled" if _stop_requested(should_stop) else type(exc).__name__
                if not ok and model not in failed_by_backend[backend]:
                    failed_by_backend[backend][model] = "unload cancelled" if _stop_requested(should_stop) else "unload failed or timed out"
                cancelled = cancelled or _stop_requested(should_stop)

        requested = [model for backend in backend_names for model in requested_by_backend[backend]]
        for backend, errors in failed_by_backend.items():
            for key, value in errors.items():
                failed[f"{backend}:{key}" if len(backend_names) > 1 else key] = value

        remaining_by_backend: dict[str, list[str] | None] = {name: None for name in backend_names}
        verification_errors: list[str] = []
        if _stop_requested(should_stop):
            cancelled = True
            verification_errors.append("unload cancelled before verification")
        elif time.monotonic() >= unload_deadline:
            verification_errors.append("unload deadline exceeded before verification")
        else:
            for backend in backend_names:
                try:
                    if backend == "ollama":
                        response = request_ollama("/api/ps")
                        if not isinstance(response, dict) or "error" in response or not isinstance(response.get("models"), list):
                            raise RuntimeError("post-unload /api/ps unavailable")
                        rows = response["models"]
                        endpoint_rows = {ollama_endpoint: []}
                    else:
                        rows, post_endpoint_status = read_llama_inventory()
                        backend_inventory_status[backend] = post_endpoint_status
                        endpoint_rows = {url: [] for url, state in last_llama_urls.items() if state == "complete"}
                    parsed: list[str] = []
                    for row_index, row in enumerate(rows):
                        if not isinstance(row, dict):
                            raise ValueError(f"post-unload model row {row_index} is not an object")
                        name = next(
                            (value.strip() for field in ("name", "model") if isinstance((value := row.get(field)), str) and value.strip()),
                            "",
                        )
                        if not name:
                            raise ValueError(f"post-unload model row {row_index} has no usable name or model")
                        endpoint_url = ollama_endpoint if backend == "ollama" else str(row.get("endpoint_url", "")).strip()
                        if not endpoint_url or endpoint_url not in endpoint_rows:
                            raise ValueError(f"post-unload model row {row_index} has unknown endpoint identity")
                        endpoint_rows[endpoint_url].append(name)
                        if name not in parsed:
                            parsed.append(name)
                    if _stop_requested(should_stop):
                        cancelled = True
                        raise InterruptedError("unload cancelled during verification")
                    if time.monotonic() >= unload_deadline:
                        raise TimeoutError("unload deadline exceeded during verification")
                    remaining_by_backend[backend] = parsed
                    for endpoint_url, endpoint_models in endpoint_rows.items():
                        remaining_by_endpoint[f"{backend}:{endpoint_url}"] = endpoint_models
                except Exception as exc:
                    if backend == "llama_cpp":
                        backend_inventory_status[backend] = dict(last_llama_endpoint_status) or {"llama.cpp": "unknown"}
                    reason = "unload cancelled during verification" if _stop_requested(should_stop) else str(exc) if isinstance(exc, (RuntimeError, ValueError, TimeoutError)) else f"post-unload verification failed: {type(exc).__name__}"
                    verification_errors.append(f"{backend}: {reason}")

        remaining_models = None if any(value is None for value in remaining_by_backend.values()) else [
            model for backend in backend_names for model in (remaining_by_backend[backend] or [])
        ]
        if verification_errors:
            failed["verification"] = "; ".join(verification_errors)
        verified = (
            not verification_errors
            and all(backend_inventory_ok.get(name, False) for name in backend_names)
            and not any(failed_by_backend.values())
            and all(name not in (remaining_by_backend[backend] or []) for backend in backend_names for name in requested_by_backend[backend])
        )
        inventory_complete = all(backend_inventory_ok.get(name, False) for name in backend_names)
        complete = remaining_models is not None and not remaining_models and inventory_complete
        if remaining_models is not None:
            unloaded = [
                name for backend in backend_names for name in requested_by_backend[backend]
                if name not in (remaining_by_backend[backend] or [])
            ]
        backend_available = bool(loaded_rows_by_backend)
        endpoint_receipts: dict[str, dict[str, Any]] = {}
        for backend in backend_names:
            endpoints = (
                {ollama_endpoint: backend_inventory_status.get(backend, {}).get("ollama", "unknown")}
                if backend == "ollama" else (last_llama_urls or {"llama.cpp": "unknown"})
            )
            for endpoint_id, endpoint_state in endpoints.items():
                receipt_key = f"{backend}:{endpoint_id}"
                requested_at_endpoint = requested_by_endpoint.get(receipt_key, [])
                remaining_at_endpoint = remaining_by_endpoint.get(receipt_key)
                receipt_state = endpoint_state if backend_inventory_ok.get(backend, False) else "unknown"
                endpoint_receipts[f"{backend}:{endpoint_id}"] = {
                    "backend": backend,
                    "endpoint_id": endpoint_id,
                    "inventory_status": receipt_state,
                    "requested": requested_at_endpoint,
                    "remaining": remaining_at_endpoint,
                    "complete": receipt_state == "complete" and isinstance(remaining_at_endpoint, list),
                }
        result = {
            "success": complete and not failed,
            "backend_available": backend_available,
            "unloaded": unloaded,
            "failed": failed,
            "requested": requested,
            "remaining": remaining_models,
            "requested_by_backend": requested_by_backend,
            "remaining_by_backend": remaining_by_backend,
            "backend_inventory_status": backend_inventory_status,
            "endpoint_receipts": endpoint_receipts,
            "verified": verified,
            "complete": complete,
            "unverified": remaining_models is None or not inventory_complete,
            "physical_vram_reclaimed": False,
        }
        if cancelled:
            result["cancelled"] = True
        return result

    def generate(
        self,
        model: str,
        prompt: str,
        *,
        system: str | None = None,
        options: dict[str, Any] | None = None,
        keep_alive: str | None = None,
        project_settings: Any | None = None,
        role: str = "",
    ) -> dict[str, Any]:
        options = dict(options or {})
        payload: dict[str, Any] = {"model": model, "prompt": prompt, "stream": False, "options": options}
        # Ollama expects `think` at the request top level.  Accepting it in the
        # options mapping keeps small callers (benchmarks and probes) bounded and
        # prevents reasoning models from consuming the whole visible-output budget.
        if "think" in options:
            payload["think"] = bool(options.pop("think"))
        if "format" in options:
            response_format = options.pop("format")
            if isinstance(response_format, (str, dict)):
                payload["format"] = response_format
        if system:
            payload["system"] = system
        if keep_alive:
            payload["keep_alive"] = keep_alive
        model, payload = self.model_policy.apply_project_settings(
            model, payload, settings=project_settings, role=role,
        )
        return self.request("/api/generate", payload)

    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        options: dict[str, Any] | None = None,
        keep_alive: str | None = None,
        project_settings: Any | None = None,
        role: str = "",
    ) -> dict[str, Any]:
        options = dict(options or {})
        payload: dict[str, Any] = {"model": model, "messages": messages, "stream": False, "options": options}
        if keep_alive:
            payload["keep_alive"] = keep_alive
        model, payload = self.model_policy.apply_project_settings(
            model, payload, settings=project_settings, role=role,
        )
        return self.request("/api/chat", payload)

    def embeddings(self, model: str, prompt: str) -> dict[str, Any]:
        return self.request("/api/embeddings", {"model": model, "prompt": prompt})

    def evict_if_needed(self, required_model: str) -> bool:
        if not bool(self.config.get("scheduler", {}).get("preempt_loaded_models", True)):
            return True
        details = self.loaded_model_details()
        for item in details:
            name = item.get("name")
            if name and name != required_model:
                self.unload_model(name)
        return True
