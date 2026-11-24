from __future__ import annotations

import json
import logging
import os
import re
import socket
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlparse

_ORIGINAL_URLOPEN = urlopen

from .llama_cpp import LlamaCppRouter, _cancel_response_on_stop, _open_interruptible_response, _read_response_body, _set_response_timeout, _stop_requested
from .llama_cpp_runtime import LlamaCppManagedRuntime, llama_cpp_managed_selected
from .llm_context_recovery import fit_recovered_context
from .ollama_models import (
    ModelPreparationAdmissionRejected,
    ModelPreparationCancelled,
    ModelPreparationNotStarted,
    OllamaModelNotFoundError,
    OllamaModelsMixin,
)
from .ollama_benchmark import OllamaBenchmarkMixin
from .json_utils import dumps as json_dumps

__all__ = [
    "OllamaRuntime",
    "ModelPreparationAdmissionRejected",
    "ModelPreparationCancelled",
    "ModelPreparationNotStarted",
    "OllamaModelNotFoundError",
    "OllamaModelsMixin",
    "OllamaBenchmarkMixin",
]

logger = logging.getLogger(__name__)


_HTTP_ERROR_BODY_LIMIT = 65_536


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


def _ensure_trained_preprocessing_model(runtime: Any, model: str) -> None:
    if model not in {
        "qwen2.5-coder-prep-v4:3b",
        "qwen2.5-coder-prep-v3:1.5b",
        "qwen2.5-coder-prep-v3:0.5b",
    }:
        return
    from .model_distribution import ensure_distribution_model
    state_dir = Path(runtime.config.get("server", {}).get("state_dir") or (Path.cwd() / "state"))
    ready = ensure_distribution_model(model, allow_download=True, models_dir=state_dir / "models")
    if ready.get("status") not in {"ready", "registered"}:
        raise RuntimeError(
            f"trained preprocessing model provisioning failed: {ready.get('error', ready.get('status'))}"
        )


def _read_http_error_body(error: HTTPError, deadline: float | None = None, should_stop: Any | None = None) -> str:
    try:
        with _cancel_response_on_stop(error, should_stop, deadline):
            if deadline is None:
                raw = error.read(_HTTP_ERROR_BODY_LIMIT + 1)
            else:
                chunks: list[bytes] = []
                total = 0
                read_chunk = getattr(error, "read1", None) or error.read
                while total <= _HTTP_ERROR_BODY_LIMIT:
                    if _stop_requested(should_stop):
                        raise InterruptedError("request cancelled")
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("request deadline expired")
                    _set_response_timeout(error, remaining)
                    chunk = read_chunk(min(65536, _HTTP_ERROR_BODY_LIMIT + 1 - total))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    total += len(chunk)
                if time.monotonic() >= deadline:
                    raise TimeoutError("request deadline expired")
                raw = b"".join(chunks)
    except Exception:
        if _stop_requested(should_stop):
            raise InterruptedError("request cancelled") from None
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("request deadline expired") from None
        raise
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


class OllamaRuntime(OllamaModelsMixin, OllamaBenchmarkMixin):
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
        mixed_managed = (isinstance(config.get("llama_cpp"), dict)
                         and config["llama_cpp"].get("managed_with_ollama") is True)
        self.llama_cpp = LlamaCppRouter(config, managed_runtime=(
            self.llama_cpp_managed if llama_cpp_managed_selected(config) or mixed_managed else None
        ))
        self._meta_cache: dict[str, Any] = {}
        self._meta_cache_at: dict[str, float] = {}
        self._ensure_lock = threading.Lock()
        self._mixed_provider_lock = threading.RLock()
        self._mixed_fallback_guard: socket.socket | None = None
        self._mixed_fallback_model: str | None = None
        self._mixed_fallback_preparing = False
        self._mixed_fallback_admitted = False

    def _is_embedding_model(self, model: str) -> bool:
        configured = str(self.config.get("models", {}).get("embedding", "") or "").strip()
        return bool(configured) and str(model or "").strip() == configured

    def _llama_version_label(self) -> str:
        if llama_cpp_managed_selected(self.config):
            mode = str(self.llama_cpp_managed.status().get("mode", ""))
            if mode.startswith("CUDA"):
                return "llama.cpp CUDA"
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
                with urlopen(req, timeout=max(0.05, remaining)) as response, _cancel_response_on_stop(response, None, request_deadline):
                    raw = _read_response_body(response, request_deadline).decode("utf-8")
                    result = json.loads(raw) if raw else {}
                    if isinstance(result, dict):
                        result["_lah_retry_count"] = max(0, attempt - 1)
                    return result
            except HTTPError as exc:
                try:
                    raw = _read_http_error_body(exc, request_deadline)
                except (socket.timeout, TimeoutError) as read_error:
                    last_error = f"Ollama request timed out: {read_error}"
                    break
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
                try:
                    raw = _read_http_error_body(exc, request_deadline, should_stop)
                except InterruptedError:
                    return {"success": False, "preempted": True, "error": "request cancelled during Ollama request", "_lah_retry_count": attempt - 1, "_lah_provider": "ollama"}
                except (socket.timeout, TimeoutError) as read_error:
                    last_error = f"Ollama request timed out: {read_error}"
                    break
                last_error = f"HTTP {exc.code}: {raw}"
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

    def _reserve_mixed_cuda_endpoint(self) -> socket.socket | None:
        managed = self.llama_cpp_managed
        guard: socket.socket | None = None
        try:
            if managed._managed_pid_alive() or managed.pid_path.exists():
                return None
            port, _ = managed._port_and_url()
            guard = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            if os.name == "nt":
                guard.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            guard.bind(("127.0.0.1", port))
            guard.listen(1)
            if managed._managed_pid_alive() or managed.pid_path.exists():
                return None
            reserved = guard
            guard = None
            return reserved
        except (OSError, ValueError, TypeError):
            return None
        finally:
            if guard is not None:
                guard.close()

    def _release_mixed_fallback_guard(self, model: str) -> None:
        with self._mixed_provider_lock:
            if self._mixed_fallback_model == model and self._mixed_fallback_guard is not None:
                self._mixed_fallback_guard.close()
                self._mixed_fallback_guard = None
                self._mixed_fallback_model = None
                self._mixed_fallback_admitted = False

    def _confirm_mixed_fallback_unloaded(self, model: str, *, should_stop: Any | None, deadline: float | None) -> bool:
        limit = min(time.monotonic() + self.timeout, float(deadline)) if deadline is not None else time.monotonic() + self.timeout
        acquired = False
        try:
            while not acquired:
                if _stop_requested(should_stop):
                    return False
                remaining = limit - time.monotonic()
                if remaining <= 0:
                    return False
                acquired = self._mixed_provider_lock.acquire(timeout=min(0.1, remaining))
            if self._mixed_fallback_model != model or self._mixed_fallback_guard is None:
                return True
            snapshot = self.loaded_model_inventory(should_stop=should_stop, deadline=limit, force_refresh=True, include_llama=False)
            if (not isinstance(snapshot, dict) or snapshot.get("complete") is not True
                    or not isinstance(snapshot.get("models"), list)
                    or any(not isinstance(row, dict) or row.get("name") == model for row in snapshot["models"])):
                return False
            if not self._mixed_fallback_preparing:
                self._release_mixed_fallback_guard(model)
            return True
        except Exception:
            return False
        finally:
            if acquired:
                self._mixed_provider_lock.release()

    def _request_stream_tracked(
        self, endpoint: str, payload: dict[str, Any] | None, on_chunk: Any,
        timeout: float | None = None, *, on_thinking: Any | None = None,
        should_stop: Any | None = None, deadline: float | None = None,
        single_attempt: bool = False,
        force_ollama: bool = False,
    ) -> dict[str, Any]:
        emitted = False

        if callable(on_chunk):
            def forward(text: str) -> None:
                nonlocal emitted
                emitted = emitted or bool(text)
                on_chunk(text)
        else:
            forward = None

        if callable(on_thinking):
            def forward_thinking(text: str) -> None:
                nonlocal emitted
                emitted = emitted or bool(text)
                on_thinking(text)
        else:
            forward_thinking = None

        def reserve_cuda_endpoint() -> bool:
            model = payload.get("model") if isinstance(payload, dict) else None
            # Only model preparation may reserve this port: it performs fresh
            # residency checks and VRAM admission before Ollama can load a runner.
            return bool(getattr(self, "_mixed_fallback_model", None) == model
                        and getattr(self, "_mixed_fallback_guard", None) is not None
                        and getattr(self, "_mixed_fallback_admitted", False))

        config = getattr(self, "config", None)
        llama_cfg = config.get("llama_cpp") if isinstance(config, dict) and isinstance(config.get("llama_cpp"), dict) else {}
        mixed_provider_lock = getattr(self, "_mixed_provider_lock", None)
        mixed_lock = (mixed_provider_lock if llama_cfg.get("managed_with_ollama") is True else None)
        acquired = False
        try:
            if mixed_lock is not None:
                default_timeout = getattr(self, "timeout", 300.0)
                limit = time.monotonic() + max(0.05, float(timeout if timeout is not None else default_timeout))
                if deadline is not None:
                    limit = min(limit, float(deadline))
                while not acquired:
                    if _stop_requested(should_stop):
                        return {"success": False, "preempted": True, "error": "request cancelled during provider admission"}
                    remaining = limit - time.monotonic()
                    if remaining <= 0:
                        return {"error": "provider admission timed out", "timed_out": True}
                    acquired = mixed_lock.acquire(timeout=min(0.1, remaining))
                deadline = limit
            result = self._request_stream_impl(endpoint, payload, forward, timeout,
                                               on_thinking=forward_thinking, should_stop=should_stop, deadline=deadline,
                                               single_attempt=single_attempt, force_ollama=force_ollama,
                                               fallback_guard=reserve_cuda_endpoint)
            if (mixed_lock is not None and not force_ollama and isinstance(payload, dict)
                    and payload.get("model") == llama_cfg.get("managed_model_logical")
                    and isinstance(result, dict) and "error" not in result and "_lah_provider" not in result):
                result = {**result, "_lah_provider": "ollama", "fallback_used": True}
        except Exception as exc:
            return {"success": False, "error": f"{type(exc).__name__}: {exc}",
                    "_lah_partial_response": emitted, "terminal": True, "retryable": False}
        finally:
            if acquired and mixed_lock is not None:
                mixed_lock.release()
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
        force_ollama: bool = False,
        fallback_guard: Any | None = None,
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
        llama_selected = not force_ollama and not bool(self.config.get("ollama", {}).get("enabled", False))
        llama_config = self.config.get("llama_cpp", {})
        mixed_selected = (
            not force_ollama and not llama_selected and isinstance(llama_config, dict)
            and llama_config.get("managed_with_ollama") is True
            and llama_config.get("mode") == "on" and llama_config.get("backend") == "cuda"
            and isinstance(payload, dict) and payload.get("model") == llama_config.get("managed_model_logical")
            and isinstance(llama_config.get("managed_model_logical"), str)
            and bool(llama_config.get("managed_model_logical"))
        )
        llama_emitted = False

        def llama_chunk(value: Any) -> None:
            nonlocal llama_emitted
            llama_emitted = llama_emitted or bool(value)
            if callable(on_chunk):
                on_chunk(value)

        def llama_thinking(value: Any) -> None:
            nonlocal llama_emitted
            llama_emitted = llama_emitted or bool(value)
            if callable(on_thinking):
                on_thinking(value)

        mixed_ready = False
        if mixed_selected:
            try:
                snapshot = self.loaded_model_inventory(should_stop=should_stop, deadline=request_deadline, force_refresh=True)
            except Exception:
                snapshot = None
            if isinstance(snapshot, dict) and snapshot.get("complete") is True and isinstance(snapshot.get("models"), list):
                configured = llama_config.get("models", {}).get(payload.get("model"), {})
                configured_url = str(configured.get("url", "")).rstrip("/") if isinstance(configured, dict) else ""
                rows = snapshot["models"]
                expected = lambda row: (isinstance(row, dict) and row.get("backend") == "llama.cpp-cuda"
                                        and row.get("name") == payload.get("model")
                                        and str(row.get("endpoint_url", "")).rstrip("/") == configured_url
                                        and row.get("status") == "loaded")
                if any(not expected(row) for row in rows) and not all(isinstance(row, dict) and row.get("backend") == "ollama" for row in rows):
                    return {"error": "mixed-provider model residency is not exclusive", "_lah_provider": "llama.cpp"}
                mixed_ready = len(rows) == 1 and expected(rows[0])
        llama_result = llama_router.request_stream(
            endpoint, payload, llama_chunk if callable(on_chunk) else None, timeout=remaining,
            on_thinking=llama_thinking if callable(on_thinking) else None,
            should_stop=should_stop, deadline=request_deadline,
        ) if (llama_selected or mixed_ready) and llama_router is not None else None
        if not (isinstance(llama_result, dict) and (llama_result.get("preempted") or llama_result.get("timed_out"))):
            provider = "llama.cpp" if llama_selected else "ollama"
            if _stop_requested(should_stop):
                return {"success": False, "preempted": True, "error": "request cancelled before backend fallback", "_lah_provider": provider}
            if time.monotonic() >= request_deadline:
                return {"error": "request deadline expired before backend fallback", "timed_out": True, "_lah_provider": provider}
        if llama_result is not None:
            if "_lah_backend_unavailable" not in llama_result:
                if llama_cpp_managed_selected(self.config) or mixed_selected:
                    device = str(self.llama_cpp_managed.status().get("mode", ""))
                    llama_result["_lah_provider"] = "llama.cpp-cuda" if device.startswith("CUDA") else "llama.cpp-cpu" if device == "none" else "llama.cpp-sycl" if device else "llama.cpp"
                return llama_result
            backend_fallback = str(llama_result.get("_lah_backend_unavailable", "SYCL unavailable"))
            if mixed_selected and (llama_emitted or llama_result.get("_lah_partial_response")):
                return {**llama_result, "error": llama_result.get("error", backend_fallback), "_lah_partial_response": True}
            if mixed_selected and any(llama_result.get(key) for key in ("timed_out", "preempted", "cancelled", "outcome_unknown")):
                return llama_result
            if mixed_selected and llama_config.get("fallback_to_ollama") is not True:
                return {"error": f"llama.cpp unavailable: {backend_fallback}", "_lah_provider": "llama.cpp"}
            if llama_selected:
                if _stop_requested(should_stop):
                    return {"success": False, "preempted": True, "error": "request cancelled while llama.cpp was unavailable", "_lah_provider": "llama.cpp"}
                if time.monotonic() >= request_deadline:
                    return {"error": "request deadline expired while llama.cpp was unavailable", "timed_out": True, "_lah_provider": "llama.cpp"}
                return {"error": f"llama.cpp unavailable: {backend_fallback}", "_lah_provider": "llama.cpp"}
        else:
            backend_fallback = ""
            if mixed_selected and llama_config.get("fallback_to_ollama") is not True:
                return {"error": "Selected llama.cpp route is unavailable for this model", "_lah_provider": "llama.cpp"}
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
        if mixed_selected:
            if not callable(fallback_guard) or not fallback_guard():
                return {"error": "CUDA endpoint state is not safely reserved; Ollama fallback blocked", "_lah_provider": "llama.cpp"}
            try:
                ollama_snapshot = self.loaded_model_inventory(should_stop=should_stop, deadline=request_deadline,
                                                              force_refresh=True, include_llama=False)
            except Exception:
                ollama_snapshot = None
            rows = ollama_snapshot.get("models") if isinstance(ollama_snapshot, dict) else None
            if (not isinstance(ollama_snapshot, dict) or ollama_snapshot.get("complete") is not True
                    or not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict)
                    or rows[0].get("backend") != "ollama" or rows[0].get("name") != payload.get("model")):
                return {"success": False, "error": "Ollama fallback residency is not verified; prepare the model again",
                        "error_code": "model_preparation_required", "operation_not_started": True, "_lah_provider": "ollama"}
            context = rows[0].get("context_length")
            if (not isinstance(context, int) or isinstance(context, bool)
                    or context < self.model_policy.profile(str(payload["model"])).num_ctx):
                return {"success": False, "error": "Ollama fallback context is not verified; prepare the model again",
                        "error_code": "model_preparation_required", "operation_not_started": True, "_lah_provider": "ollama"}
        clean = dict(_normalise_keep_alive(payload) or {})
        clean["stream"] = payload.get("stream") is not False
        body = json_dumps(clean).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        attempts = 1 if single_attempt else max(1, int(self.config.get("ollama", {}).get("request_attempts", 2)))
        retry_delay = max(0.0, float(self.config.get("ollama", {}).get("retry_delay_seconds", 0.6)))
        deadline = request_deadline
        last_error = "unknown Ollama error"
        last_error_backend_completed = False
        timed_out = False
        context_recovery: dict[str, Any] | None = None
        allowed_attempts = attempts
        generated: list[str] = []
        chat: list[str] = []
        thinking_parts: list[str] = []
        emitted_output = False
        for attempt in range(1, attempts + 2):
            remaining = request_deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            generated = []
            chat = []
            thinking_parts = []
            tool_calls: list[Any] = []
            emitted_output = False
            stream_error = False
            last_error_backend_completed = False
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
                        except (socket.timeout, TimeoutError):
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
                            continue
                        if not isinstance(chunk, dict):
                            continue
                        if chunk.get("error"):
                            last_error = str(chunk["error"])
                            stream_error = True
                            break
                        if watchdog.loop_detected:
                            # Drain within the original deadline without publishing
                            # more output, so a terminal backend response can prove
                            # GPU work has ended before the scheduler releases it.
                            if chunk.get("done") is True:
                                final.update(chunk)
                                break
                            continue
                        delta = chunk.get("response")
                        if delta is not None:
                            text = str(delta)
                            if text:
                                generated.append(text)
                                if on_chunk is not None:
                                    emitted_output = True
                                    try:
                                        on_chunk(text)
                                    except Exception as exc:
                                        logger.debug("on_chunk callback failed: %s", type(exc).__name__)
                                if watchdog.push(text):
                                    final["_lah_repetition_loop_detected"] = True
                                    if chunk.get("done") is True:
                                        final.update(chunk)
                                        break
                                    continue
                        message = chunk.get("message")
                        if isinstance(message, dict) and "tool_calls" in message:
                            calls = message["tool_calls"]
                            if not isinstance(calls, list):
                                return {"error": "invalid streamed tool_calls", "retryable": False}
                            tool_calls.extend(calls)
                        if isinstance(message, dict) and message.get("content") is not None:
                            text = str(message["content"])
                            if text:
                                chat.append(text)
                                if on_chunk is not None:
                                    emitted_output = True
                                    try:
                                        on_chunk(text)
                                    except Exception as exc:
                                        logger.debug("on_chunk callback failed: %s", type(exc).__name__)
                                if watchdog.push(text):
                                    final["_lah_repetition_loop_detected"] = True
                                    if chunk.get("done") is True:
                                        final.update(chunk)
                                        break
                                    continue
                        thinking_delta = chunk.get("thinking")
                        if thinking_delta is None and isinstance(message, dict):
                            thinking_delta = message.get("thinking")
                        if thinking_delta:
                            thinking_text = str(thinking_delta)
                            thinking_parts.append(thinking_text)
                            if on_thinking is not None:
                                emitted_output = True
                                try:
                                    on_thinking(thinking_text)
                                except Exception as exc:
                                    logger.debug("on_thinking callback failed: %s", type(exc).__name__)
                        final.update(chunk)
                        if chunk.get("done") is True:
                            break
                if timed_out:
                    return {
                        "error": last_error,
                        "_lah_retry_count": max(0, attempt - 1),
                        "timed_out": True,
                        **({"_lah_partial_response": True} if (emitted_output or generated or chat or thinking_parts) else {}),
                    }
                if watchdog.loop_detected:
                    result = {
                        "error": "model output repetition loop detected",
                        "_lah_repetition_loop_detected": True,
                        "_lah_retry_count": max(0, attempt - 1),
                        "model": str(clean.get("model", "")),
                    }
                    if final.get("done") is True and not stream_error:
                        result["_lah_backend_completed"] = True
                    return result
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
                if tool_calls:
                    message = dict(final.get("message") or {})
                    message["tool_calls"] = tool_calls
                    final["message"] = message
                if thinking_parts:
                    final["thinking"] = "".join(thinking_parts)
                if final.get("done") is True and not final.get("error") and not stream_error:
                    final["_lah_retry_count"] = max(0, attempt - 1)
                    final.setdefault("_lah_provider", provider)
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
                last_error_backend_completed = True
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
                    return {
                        "error": f"Ollama request timed out after {total_timeout:g}s",
                        "timed_out": True,
                        "_lah_provider": "ollama",
                        **({"_lah_partial_response": True} if (emitted_output or generated or chat or thinking_parts) else {}),
                    }
                last_error = f"Ollama request timed out: {exc}"
                timed_out = True
                break
            except Exception as exc:
                if _stop_requested(should_stop):
                    return {"success": False, "preempted": True, "error": "request cancelled during generation", "_lah_provider": "ollama"}
                if time.monotonic() >= deadline:
                    return {
                        "error": f"Ollama request timed out after {total_timeout:g}s",
                        "timed_out": True,
                        "_lah_provider": "ollama",
                        **({"_lah_partial_response": True} if (emitted_output or generated or chat or thinking_parts) else {}),
                    }
                last_error = f"{type(exc).__name__}: {exc}"
                if "timeout" in str(exc).lower() or "timed out" in str(exc).lower():
                    timed_out = True
                    break
            if timed_out:
                return {
                    "error": last_error,
                    "_lah_retry_count": max(0, attempt - 1),
                    "timed_out": True,
                    **({"_lah_partial_response": True} if (emitted_output or generated or chat or thinking_parts) else {}),
                }
            if emitted_output or (stream_error and (generated or chat or thinking_parts)):
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
        return {
            "error": last_error,
            "_lah_retry_count": max(0, attempt - 1),
            "timed_out": timed_out or time.monotonic() >= deadline,
            **({"_lah_partial_response": True} if (emitted_output or generated or chat or thinking_parts) else {}),
            **({"_lah_backend_completed": True} if last_error_backend_completed and not timed_out and not (emitted_output or generated or chat or thinking_parts) else {}),
            **({"context_recovery": context_recovery} if context_recovery is not None else {}),
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
        kv_cache = "q4_0"
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
        llama = self.config.get("llama_cpp", {})
        if (str(llama.get("mode", "auto")).strip().lower() != "off"
                and llama.get("managed_with_ollama") is not True
                and not bool(llama.get("fallback_to_ollama", True))):
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
            "kv_cache_type": "q4_0",
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
            raise ModelPreparationCancelled("model preparation cancelled while checking loaded models", operation_not_started=True)
        if deadline is not None and time.monotonic() >= deadline:
            raise ModelPreparationNotStarted("model preparation deadline expired while checking loaded models")
        if "error" in result or not isinstance(result, dict):
            if should_stop is not None or deadline is not None:
                llama_rows = self.llama_cpp.loaded_model_details(
                    should_stop=should_stop, deadline=deadline,
                )
                if _stop_requested(should_stop):
                    raise ModelPreparationCancelled("model preparation cancelled while checking adapter models", operation_not_started=True)
                if deadline is not None and time.monotonic() >= deadline:
                    raise ModelPreparationNotStarted("model preparation deadline expired while checking adapter models")
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
        payload: dict[str, Any] = {"model": model, "prompt": prompt, "stream": True, "options": options}
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
        _ensure_trained_preprocessing_model(self, model)
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
        payload: dict[str, Any] = {"model": model, "messages": messages, "stream": True, "options": options}
        if keep_alive:
            payload["keep_alive"] = keep_alive
        model, payload = self.model_policy.apply_project_settings(
            model, payload, settings=project_settings, role=role,
        )
        _ensure_trained_preprocessing_model(self, model)
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
