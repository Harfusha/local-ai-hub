from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlparse


def _normalise_keep_alive(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return an Ollama-valid keep_alive value without mutating caller input."""
    if payload is None:
        return None
    clean = dict(payload)
    if str(clean.get("keep_alive", "")).strip() == "-1":
        clean["keep_alive"] = "-1m"
    return clean

from .process_utils import hidden_run_kwargs, terminate_tree, pid_alive, process_executable
from .model_policy import ModelExecutionPolicy


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
        self._meta_cache: dict[str, Any] = {}
        self._meta_cache_at: dict[str, float] = {}
        self._ensure_lock = threading.Lock()

    def _is_embedding_model(self, model: str) -> bool:
        configured = str(self.config.get("models", {}).get("embedding", "") or "").strip()
        return bool(configured) and str(model or "").strip() == configured

    def request(self, endpoint: str, payload: dict[str, Any] | None = None, timeout: float | None = None) -> dict[str, Any]:
        payload = _normalise_keep_alive(payload)
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
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
                if attempt >= attempts:
                    return {"error": last_error, "_lah_retry_count": max(0, attempt - 1)}
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt >= attempts:
                    return {"error": last_error, "_lah_retry_count": max(0, attempt - 1)}
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if retry_delay:
                time.sleep(min(retry_delay, remaining))
        return {"error": last_error, "_lah_retry_count": max(0, attempts - 1), "timed_out": time.monotonic() >= deadline}

    def request_stream(self, endpoint: str, payload: dict[str, Any] | None, on_chunk: Any, timeout: float | None = None) -> dict[str, Any]:
        clean = dict(_normalise_keep_alive(payload) or {})
        clean["stream"] = True
        body = json.dumps(clean, ensure_ascii=False).encode("utf-8")
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
            final: dict[str, Any] = {}
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
                            text = str(delta); generated.append(text)
                            try: on_chunk(text)
                            except Exception: pass
                        message = chunk.get("message")
                        if isinstance(message, dict) and message.get("content") is not None:
                            text = str(message["content"]); chat.append(text)
                            try: on_chunk(text)
                            except Exception: pass
                        final.update(chunk)
                        if chunk.get("done") is True:
                            break
                if generated:
                    final["response"] = "".join(generated)
                if chat:
                    message = dict(final.get("message") or {})
                    message["content"] = "".join(chat)
                    final["message"] = message
                if final and not final.get("error"):
                    final["_lah_retry_count"] = max(0, attempt - 1)
                    return final
            except HTTPError as exc:
                raw = exc.read().decode("utf-8", errors="replace")
                last_error = f"HTTP {exc.code}: {raw}"
                if exc.code < 500:
                    break
            except URLError as exc:
                last_error = f"Ollama unavailable: {exc.reason}"
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
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

        clean = _normalise_keep_alive(payload) or {}
        clean = dict(clean)
        clean.setdefault("stream", True)
        body = json.dumps(clean, ensure_ascii=False).encode("utf-8")
        req = Request(f"{self.base_url}{endpoint}", data=body, headers={"Content-Type": "application/json"})
        total_timeout = max(0.05, float(timeout if timeout is not None else self.timeout))
        deadline = time.monotonic() + total_timeout
        text_parts: list[str] = []
        message_parts: list[str] = []
        final: dict[str, Any] = {}
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
                        text_parts.append(str(token))
                    message = chunk.get("message")
                    if isinstance(message, dict) and message.get("content") is not None:
                        message_parts.append(str(message.get("content")))
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

        if text_parts:
            final["response"] = "".join(text_parts)
        if message_parts:
            message = dict(final.get("message") or {})
            message["content"] = "".join(message_parts)
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
        env.setdefault("OLLAMA_KEEP_ALIVE", "-1m")
        return env

    def ensure_running(self) -> bool:
        if self.is_online():
            return True
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

            env = self._configured_environment()
            executable = self.config.get("ollama", {}).get("executable") or "ollama"
            args = [executable, "serve"]
            popen_kwargs: dict[str, Any] = hidden_run_kwargs(new_group=True)
            if os.name != "nt":
                popen_kwargs["start_new_session"] = True
            try:
                proc = subprocess.Popen(
                    args, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, **popen_kwargs,
                )
                self.managed_pid_path.write_text(str(proc.pid), encoding="utf-8")
            except Exception:
                return False

            startup_timeout = max(1.0, float(self.config.get("ollama", {}).get("startup_timeout_seconds", 12.0)))
            deadline = time.monotonic() + startup_timeout
            while time.monotonic() < deadline:
                if self.is_online():
                    return True
                if proc.poll() is not None:
                    break
                time.sleep(min(0.4, max(0.05, deadline - time.monotonic())))
            return self.is_online()

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
                "flash_attention": bool(cfg.get("flash_attention", True)),
                "kv_cache_type": str(cfg.get("kv_cache_type", "q8_0")),
                "gpu_overhead_bytes": int(cfg.get("gpu_overhead_bytes", 0) or 0),
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
        return v or self._meta_cache.get("version")

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
            return list(self._meta_cache.get("loaded_details", []))
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
