from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlparse

from .llama_cpp import LlamaCppRouter
from .json_utils import dumps as json_dumps


def _normalise_keep_alive(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return an Ollama-valid keep_alive value without mutating caller input."""
    if payload is None:
        return None
    clean = dict(payload)
    if str(clean.get("keep_alive", "")).strip() == "-1":
        clean["keep_alive"] = "-1m"
    return clean

from .process_utils import (
    find_listening_pid,
    hidden_run_kwargs,
    pid_alive,
    process_executable,
    set_process_priority,
    terminate_tree,
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
        self.model_policy = ModelExecutionPolicy(config)
        self.llama_cpp = LlamaCppRouter(config)
        self._meta_cache: dict[str, Any] = {}
        self._meta_cache_at: dict[str, float] = {}
        self._ensure_lock = threading.Lock()

    def _is_embedding_model(self, model: str) -> bool:
        configured = str(self.config.get("models", {}).get("embedding", "") or "").strip()
        return bool(configured) and str(model or "").strip() == configured

    def request(self, endpoint: str, payload: dict[str, Any] | None = None, timeout: float | None = None) -> dict[str, Any]:
        if payload is not None and endpoint in {"/api/chat", "/api/generate"}:
            return self.request_stream(endpoint, payload, lambda _chunk: None, timeout)
        if endpoint == "/api/show":
            router = getattr(self, "llama_cpp", None)
            describe = getattr(router, "model_capabilities", None)
            model = payload.get("name", "") if isinstance(payload, dict) else ""
            if callable(describe):
                result = describe(str(model))
                if isinstance(result, dict):
                    return result
        if not bool(self.config.get("llama_cpp", {}).get("fallback_to_ollama", True)):
            if endpoint == "/api/version":
                router = getattr(self, "llama_cpp", None)
                return {"version": "llama.cpp SYCL"} if router is not None and router.is_online() else {"error": "llama.cpp SYCL router unavailable"}
            if endpoint == "/api/tags":
                return {"models": [{"name": model} for model in self.llama_cpp.available_models()]}
            if endpoint == "/api/ps":
                return {"models": [
                    {"name": row["name"], "model": row["name"], "context_length": row.get("context_length", 0), "size": 0, "size_vram": 0, "details": {"quantization_level": row.get("quantization", "GGUF")}}
                    for row in self.llama_cpp.loaded_model_details()
                ]}
            return {"error": "Ollama fallback is disabled and this endpoint is not provided by llama.cpp SYCL"}
        payload = _normalise_keep_alive(payload)
        body = json_dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"} if body is not None else {}
        attempts = max(1, int(self.config.get("ollama", {}).get("request_attempts", 2)))
        retry_delay = max(0.0, float(self.config.get("ollama", {}).get("retry_delay_seconds", 0.6)))
        total_timeout = max(0.05, float(timeout if timeout is not None else self.timeout))
        deadline = time.monotonic() + total_timeout
        last_error = "unknown Ollama error"
        for attempt in range(1, attempts + 1):
            remaining = deadline - time.monotonic()
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
                raw = exc.read().decode("utf-8", errors="replace")
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
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if retry_delay:
                time.sleep(min(retry_delay, remaining))
        return {"error": last_error, "_lah_retry_count": max(0, attempts - 1), "timed_out": time.monotonic() >= deadline}

    def request_stream(self, endpoint: str, payload: dict[str, Any] | None, on_chunk: Any, timeout: float | None = None, *, on_thinking: Any | None = None) -> dict[str, Any]:
        llama_router = getattr(self, "llama_cpp", None)
        llama_result = llama_router.request_stream(endpoint, payload, on_chunk, timeout=timeout, on_thinking=on_thinking) if llama_router is not None else None
        if llama_result is not None:
            if "_lah_backend_unavailable" not in llama_result:
                return llama_result
            backend_fallback = str(llama_result.get("_lah_backend_unavailable", "SYCL unavailable"))
            if not bool(self.config.get("llama_cpp", {}).get("fallback_to_ollama", True)):
                return {"error": f"llama.cpp SYCL unavailable: {backend_fallback}", "_lah_provider": "llama.cpp-sycl"}
        else:
            backend_fallback = ""
            if not bool(self.config.get("llama_cpp", {}).get("fallback_to_ollama", True)):
                return {"error": "Ollama fallback is disabled and no llama.cpp SYCL route matches this model", "_lah_provider": "llama.cpp-sycl"}
        clean = dict(_normalise_keep_alive(payload) or {})
        clean["stream"] = True
        body = json_dumps(clean).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        attempts = max(1, int(self.config.get("ollama", {}).get("request_attempts", 2)))
        retry_delay = max(0.0, float(self.config.get("ollama", {}).get("retry_delay_seconds", 0.6)))
        total_timeout = max(0.05, float(timeout if timeout is not None else self.timeout))
        deadline = time.monotonic() + total_timeout
        last_error = "unknown Ollama error"
        for attempt in range(1, attempts + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            generated: list[str] = []
            chat: list[str] = []
            thinking_parts: list[str] = []
            final: dict[str, Any] = {}
            watchdog = RepetitionWatchdog(max_repeat=3)
            req = Request(f"{self.base_url}{endpoint}", data=body, headers=headers)
            try:
                with urlopen(req, timeout=max(0.05, remaining)) as response:
                    for raw_line in response:
                        if time.monotonic() >= deadline:
                            last_error = f"Ollama request timed out after {total_timeout:g}s"
                            break
                        raw_line = raw_line.strip()
                        if not raw_line:
                            continue
                        try:
                            chunk = json.loads(raw_line.decode("utf-8", errors="replace"))
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(chunk, dict):
                            continue
                        if chunk.get("error"):
                            last_error = str(chunk["error"])
                            break
                        delta = chunk.get("response")
                        if delta is not None:
                            text = str(delta)
                            if text:
                                generated.append(text)
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
                                try: on_thinking(thinking_text)
                                except Exception: pass
                        final.update(chunk)
                        if chunk.get("done") is True:
                            break
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
                if final and not final.get("error"):
                    final["_lah_retry_count"] = max(0, attempt - 1)
                    if backend_fallback:
                        final["_lah_backend_fallback"] = backend_fallback
                    return final
            except HTTPError as exc:
                raw = exc.read().decode("utf-8", errors="replace")
                last_error = f"HTTP {exc.code}: {raw}"
                if exc.code < 500:
                    break
            except URLError as exc:
                last_error = f"Ollama unavailable: {exc.reason}"
                if isinstance(getattr(exc, "reason", None), (socket.timeout, TimeoutError)):
                    break
            except (socket.timeout, TimeoutError) as exc:
                last_error = f"Ollama request timed out: {exc}"
                break
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if "timeout" in str(exc).lower() or "timed out" in str(exc).lower():
                    break
            remaining = deadline - time.monotonic()
            if attempt < attempts and remaining > 0 and retry_delay:
                time.sleep(min(retry_delay, remaining))
        return {"error": last_error, "_lah_retry_count": max(0, attempts - 1), "timed_out": time.monotonic() >= deadline}

    def request_interruptible(
        self,
        endpoint: str,
        payload: dict[str, Any] | None,
        should_stop: Any,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Execute an Ollama streaming request that can yield to foreground work.

        Background preprocessing uses Ollama's NDJSON streaming mode so it can inspect
        cancellation between chunks. The dedicated background server is also killed by
        the foreground preemption hook, which interrupts a blocking socket read even
        before the next token arrives. This method intentionally does not retry: once a
        background request is cancelled or its server is recycled, retry belongs to the
        durable preprocessing scheduler rather than this network call.
        """
        try:
            if bool(should_stop()):
                return {"success": False, "preempted": True, "error": "background request preempted before start"}
        except Exception:
            pass

        llama_router = getattr(self, "llama_cpp", None)
        llama_result = (
            llama_router.request_stream(
                endpoint, payload, lambda _chunk: None, timeout=timeout, should_stop=should_stop,
            )
            if llama_router is not None else None
        )
        if llama_result is not None:
            if "_lah_backend_unavailable" not in llama_result:
                return llama_result
            if not bool(self.config.get("llama_cpp", {}).get("fallback_to_ollama", True)):
                return {"error": f"llama.cpp SYCL unavailable: {llama_result['_lah_backend_unavailable']}", "_lah_provider": "llama.cpp-sycl"}
        elif not bool(self.config.get("llama_cpp", {}).get("fallback_to_ollama", True)):
            return {"error": "Ollama fallback is disabled and no llama.cpp SYCL route matches this model", "_lah_provider": "llama.cpp-sycl"}

        clean = _normalise_keep_alive(payload) or {}
        clean = dict(clean)
        clean.setdefault("stream", True)
        body = json_dumps(clean).encode("utf-8")
        req = Request(f"{self.base_url}{endpoint}", data=body, headers={"Content-Type": "application/json"})
        total_timeout = max(0.05, float(timeout if timeout is not None else self.timeout))
        deadline = time.monotonic() + total_timeout
        text_parts: list[str] = []
        message_parts: list[str] = []
        final: dict[str, Any] = {}
        watchdog = RepetitionWatchdog(max_repeat=3)
        try:
            with urlopen(req, timeout=total_timeout) as response:
                for raw_line in response:
                    if time.monotonic() >= deadline:
                        return {"error": f"Ollama request timed out after {total_timeout:g}s", "timed_out": True}
                    try:
                        if bool(should_stop()):
                            return {"success": False, "preempted": True, "error": "background request preempted by foreground work"}
                    except Exception:
                        pass
                    raw_line = raw_line.strip()
                    if not raw_line:
                        continue
                    try:
                        chunk = json.loads(raw_line.decode("utf-8", errors="replace"))
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(chunk, dict):
                        continue
                    if chunk.get("error"):
                        return {"error": str(chunk.get("error"))}
                    token = chunk.get("response")
                    if token is not None:
                        text = str(token)
                        text_parts.append(text)
                        if watchdog.push(text):
                            final["_lah_repetition_loop_detected"] = True
                            break
                    message = chunk.get("message")
                    if isinstance(message, dict) and message.get("content") is not None:
                        text = str(message.get("content"))
                        message_parts.append(text)
                        if watchdog.push(text):
                            final["_lah_repetition_loop_detected"] = True
                            break
                    final.update(chunk)
                    if chunk.get("done") is True:
                        break
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            return {"error": f"HTTP {exc.code}: {raw}"}
        except URLError as exc:
            return {"error": f"Ollama unavailable: {exc.reason}"}
        except Exception as exc:
            try:
                if bool(should_stop()):
                    return {"success": False, "preempted": True, "error": "background request preempted by foreground work"}
            except Exception:
                pass
            return {"error": f"{type(exc).__name__}: {exc}"}

        if watchdog.loop_detected:
            return {
                "error": "model output repetition loop detected",
                "_lah_repetition_loop_detected": True,
                "_lah_retry_count": 0,
                "model": str(clean.get("model", "")),
            }
        if text_parts:
            resp_text = "".join(text_parts)
            if watchdog.loop_detected:
                resp_text = watchdog.trim_trailing_loop(resp_text)
            final["response"] = resp_text
        if message_parts:
            message = dict(final.get("message") or {})
            chat_text = "".join(message_parts)
            if watchdog.loop_detected:
                chat_text = watchdog.trim_trailing_loop(chat_text)
            message["content"] = chat_text
            final["message"] = message
        final["_lah_retry_count"] = 0
        return final

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
        # Vulkan is the portable Intel/AMD GPU path on Windows/Linux in Ollama.
        # It stays opt-in globally and is enabled by the conservative integrated
        # profile only; Ollama may still fall back to CPU when discovery fails.
        if bool(cfg.get("enable_vulkan", False)):
            env["OLLAMA_VULKAN"] = "1"
        if bool(cfg.get("flash_attention", True)):
            env["OLLAMA_FLASH_ATTENTION"] = "1"
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

    def _management_enabled(self) -> bool:
        headless = self.config.get("headless", {})
        return bool(headless.get("manage_ollama", False)) and bool(headless.get("autostart_ollama", True))

    def _managed_pid_alive(self) -> bool:
        try:
            pid = int(self.managed_pid_path.read_text(encoding="utf-8").strip() or 0)
        except Exception:
            return False
        executable = (process_executable(pid) or "").lower()
        return bool(pid_alive(pid) and "ollama" in Path(executable).name)

    def _local_external_pid(self) -> int | None:
        if not self._management_enabled() or self._managed_pid_alive():
            return None
        parsed = urlparse(self.base_url)
        if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            return None
        pid = find_listening_pid(int(parsed.port or 11434))
        if not pid or pid == os.getpid():
            return None
        executable = (process_executable(pid) or "").lower()
        return pid if "ollama" in Path(executable).name else None

    def _take_over_external_server(self) -> bool | None:
        """Stop a local unmanaged Ollama so the Hub can restart it with its profile.

        ``None`` means no safe local Ollama owner was found.  ``False`` means a
        takeover was attempted but the endpoint did not go offline.  The latter
        fails closed instead of killing an unknown process repeatedly.
        """
        pid = self._local_external_pid()
        if pid is None:
            return None
        if not terminate_tree(pid, grace_seconds=5.0):
            return False
        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline:
            if not self.is_online():
                return True
            time.sleep(0.1)
        return not self.is_online()

    def _cleanup_failed_start(self, proc: subprocess.Popen[Any]) -> None:
        """Reap a child whose endpoint never became healthy."""
        try:
            running = proc.poll() is None
        except Exception:
            running = True
        if running:
            try:
                terminate_tree(proc.pid, grace_seconds=2.0)
            except Exception:
                pass
        try:
            proc.wait(timeout=3.0)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
            try:
                proc.wait(timeout=1.0)
            except Exception:
                pass
        try:
            if self.managed_pid_path.read_text(encoding="utf-8").strip() == str(proc.pid):
                self.managed_pid_path.unlink(missing_ok=True)
        except (OSError, ValueError):
            pass

    def ensure_running(self) -> bool:
        if self.llama_cpp.is_online():
            return True
        if not bool(self.config.get("llama_cpp", {}).get("fallback_to_ollama", True)):
            return False
        if self.is_online():
            takeover = self._take_over_external_server()
            if takeover is None:
                return True
            if not takeover:
                return False
        if not bool(self.config.get("headless", {}).get("autostart_ollama", True)):
            return False
        with self._ensure_lock:
            # Re-check after waiting for another starter. This prevents watchdog,
            # scheduler and preprocessing threads from spawning parallel servers.
            if self.is_online():
                return True
            try:
                old_pid = int(self.managed_pid_path.read_text(encoding="utf-8").strip() or 0)
            except Exception:
                old_pid = 0
            if old_pid > 0 and pid_alive(old_pid):
                executable_path = (process_executable(old_pid) or "").lower()
                if executable_path and "ollama" not in Path(executable_path).name.lower():
                    # PID file was reused by an unrelated process. Never terminate it.
                    try:
                        self.managed_pid_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                else:
                    # A process we started exists but its endpoint is not healthy.
                    # Recycle it instead of leaving every caller behind a permanently
                    # alive-but-unresponsive PID file.
                    terminate_tree(old_pid, grace_seconds=2.0)
                    try:
                        self.managed_pid_path.unlink(missing_ok=True)
                    except OSError:
                        pass

            takeover = self._take_over_external_server()
            if takeover is False:
                return False

            env = self._configured_environment()
            executable = self.config.get("ollama", {}).get("executable") or "ollama"
            args = [executable, "serve"]
            popen_kwargs: dict[str, Any] = hidden_run_kwargs(new_group=True)
            if os.name != "nt":
                popen_kwargs["start_new_session"] = True
            proc: subprocess.Popen[Any] | None = None
            try:
                proc = subprocess.Popen(
                    args, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, **popen_kwargs,
                )
                priority = str(self.config.get("ollama", {}).get("process_priority", "") or "")
                if not priority and self.managed_name.startswith("ollama-background"):
                    priority = str(self.config.get("background_gpu", {}).get("process_priority", "") or "")
                set_process_priority(proc.pid, priority)
                self.managed_pid_path.write_text(str(proc.pid), encoding="utf-8")
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

    def managed_profile_status(self) -> dict[str, Any]:
        pid = 0
        try:
            if self.managed_pid_path.exists():
                pid = int(self.managed_pid_path.read_text(encoding="utf-8").strip() or 0)
        except Exception:
            pid = 0
        managed = bool(pid > 0 and pid_alive(pid))
        cfg = self.config.get("ollama", {})
        sched = self.config.get("scheduler", {})
        return {
            "managed": managed,
            "managed_name": self.managed_name,
            "url": self.base_url,
            "pid": pid if managed else None,
            "profile_verifiable": managed,
            "expected": {
                "num_parallel": int(cfg.get("num_parallel", sched.get("max_parallel", 1))),
                "max_loaded_models": int(sched.get("max_loaded_models", 1)),
                "allow_integrated_gpu": bool(cfg.get("allow_integrated_gpu", False)),
                "enable_vulkan": bool(cfg.get("enable_vulkan", False)),
                "flash_attention": bool(cfg.get("flash_attention", True)),
                "kv_cache_type": str(cfg.get("kv_cache_type", "q8_0")),
                "gpu_overhead_bytes": int(cfg.get("gpu_overhead_bytes", 0) or 0),
            },
            "llama_cpp": {
                "mode": str(self.config.get("llama_cpp", {}).get("mode", "auto")),
                "online_models": self.llama_cpp.available_models(),
            },
        }

    def stop_managed_server(self) -> bool:
        try:
            pid = int(self.managed_pid_path.read_text(encoding="utf-8").strip() or 0)
        except Exception:
            pid = 0
        if pid <= 0:
            return True
        if pid_alive(pid):
            executable = (process_executable(pid) or "").lower()
            if executable and "ollama" not in Path(executable).name.lower():
                try: self.managed_pid_path.unlink(missing_ok=True)
                except OSError: pass
                return False
            ok = terminate_tree(pid, grace_seconds=5.0)
        else:
            ok = True
        try: self.managed_pid_path.unlink(missing_ok=True)
        except OSError: pass
        return bool(ok)

    def version(self) -> str | None:
        now = time.monotonic()
        if now - self._meta_cache_at.get("version", 0) < 5.0 and "version" in self._meta_cache:
            return self._meta_cache.get("version")
        result = self.request("/api/version", timeout=1.0)
        v = result.get("version") if "error" not in result else None
        if v is not None:
            self._meta_cache["version"] = v
            self._meta_cache_at["version"] = now
        if v:
            return v
        if self.llama_cpp.is_online():
            self._meta_cache["version"] = "llama.cpp SYCL"
            self._meta_cache_at["version"] = now
            return "llama.cpp SYCL"
        return self._meta_cache.get("version")

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
        llama_models = self.llama_cpp.available_models()
        if llama_models:
            self._meta_cache["installed"] = llama_models
            self._meta_cache_at["installed"] = now
            return llama_models
        return list(self._meta_cache.get("installed", []))

    def loaded_models(self) -> list[str]:
        details = self.loaded_model_details()
        return [d["name"] for d in details if d.get("name")]

    def loaded_model_details(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        if now - self._meta_cache_at.get("loaded_details", 0) < 2.0 and "loaded_details" in self._meta_cache:
            return list(self._meta_cache.get("loaded_details", []))
        result = self.request("/api/ps", timeout=1.0)
        if "error" in result or not isinstance(result, dict):
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

    def prepare_model(self, model: str, *, unload_others: bool = True) -> list[str]:
        """Ensure ``model`` is resident with the execution policy's context size.

        The scheduler treats this as the authoritative model-switch primitive. Keep
        the method in the runtime rather than duplicating load/unload/context logic in
        scheduler/background callers so all adapters share one contract.
        """
        model = str(model or "").strip()
        if not model:
            raise ValueError("model is required")
        # llama.cpp loads the configured GGUF in its local server. Avoid also
        # loading that same model into Ollama when the SYCL endpoint is ready.
        if self.llama_cpp.ensure_model(model, timeout=float(self.config.get("llama_cpp", {}).get("model_load_timeout_seconds", 90))):
            return []
        if not bool(self.config.get("llama_cpp", {}).get("fallback_to_ollama", True)) and self.llama_cpp.supports_model(model):
            raise RuntimeError("configured llama.cpp SYCL model is not available")
        if not self.ensure_running():
            raise RuntimeError("Ollama is not available")

        profile = self.model_policy.profile(model)
        details = self.loaded_model_details()
        evicted: list[str] = []
        current = next((row for row in details if str(row.get("name", "")) == model), None)

        if unload_others:
            for row in details:
                name = str(row.get("name", "") or "")
                if name and name != model and self.unload_model(name):
                    evicted.append(name)

        if current is not None and int(current.get("context_length", 0) or 0) >= profile.num_ctx:
            return evicted

        # A runner loaded with a smaller context cannot be safely reused for a larger
        # request. Explicitly unload it so Ollama recreates the runner with num_ctx.
        if current is not None:
            self.unload_model(model)

        keep_alive = self.config.get("ollama", {}).get("keep_alive", "24h")
        if self._is_embedding_model(model):
            payload = {"model": model, "input": [""], "keep_alive": keep_alive}
            result = self.request("/api/embed", payload)
        else:
            payload = {
                "model": model,
                "prompt": "",
                "stream": False,
                "keep_alive": keep_alive,
                "options": {"num_ctx": profile.num_ctx},
            }
            result = self.request("/api/generate", payload)
        if "error" in result:
            raise RuntimeError(str(result.get("error", "model load failed")))
        self._invalidate_loaded_cache()
        return evicted

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

    def unload_model(self, model: str) -> bool:
        if self.llama_cpp.supports_model(model) and self.llama_cpp.ready_for_model(model):
            return self.llama_cpp.unload_model(model)
        if not bool(self.config.get("llama_cpp", {}).get("fallback_to_ollama", True)):
            return False
        endpoint = "/api/generate"
        payload: dict[str, Any] = {"model": model, "keep_alive": 0}
        if self._is_embedding_model(model):
            payload["input"] = [""]
            endpoint = "/api/embed"
        result = self.request(endpoint, payload)
        ok = "error" not in result
        if ok:
            self._invalidate_loaded_cache()
        return ok

    def generate(self, model: str, prompt: str, *, system: str | None = None, options: dict[str, Any] | None = None, keep_alive: str | None = None) -> dict[str, Any]:
        options = dict(options or {})
        payload: dict[str, Any] = {"model": model, "prompt": prompt, "stream": False, "options": options}
        # Ollama expects `think` at the request top level.  Accepting it in the
        # options mapping keeps small callers (benchmarks and probes) bounded and
        # prevents reasoning models from consuming the whole visible-output budget.
        if "think" in options:
            payload["think"] = bool(options.pop("think"))
        if system:
            payload["system"] = system
        if keep_alive:
            payload["keep_alive"] = keep_alive
        return self.request("/api/generate", payload)

    def chat(self, model: str, messages: list[dict[str, Any]], *, options: dict[str, Any] | None = None, keep_alive: str | None = None) -> dict[str, Any]:
        options = dict(options or {})
        payload: dict[str, Any] = {"model": model, "messages": messages, "stream": False, "options": options}
        if keep_alive:
            payload["keep_alive"] = keep_alive
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
