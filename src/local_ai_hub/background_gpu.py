from __future__ import annotations

import copy
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urlparse

from .budget import estimate_tokens, fit_text
from .model_policy import ModelExecutionPolicy
from .ollama import OllamaRuntime
from .process_utils import find_listening_pid, terminate_tree, process_executable


class IdleGPUWorker:
    """Disposable high-throughput GPU preprocessing on a dedicated Ollama server.

    The foreground scheduler owns the GPU until it has been idle for the configured
    grace window. Only then is its resident model unloaded and a secondary Ollama
    process is allowed to load the small background coder. Any foreground submission
    synchronously kills this managed background process before the foreground
    dispatcher may load fast/smart tier again.

    CPU embeddings/reranking never pass through this worker or the GPU scheduler.
    """

    def __init__(self, config: dict[str, Any], foreground_scheduler: Any):
        self.config = config
        self.scheduler = foreground_scheduler
        self.cfg = config.get("background_gpu", {})
        self.enabled = bool(self.cfg.get("enabled", True))
        self.model = str(config.get("models", {}).get("background_code", "") or "")
        self.idle_seconds = max(0.0, float(self.cfg.get("idle_seconds", 60.0)))
        self.parallel = max(1, int(self.cfg.get("parallel", config.get("model_execution", {}).get("background", {}).get("parallel", 4))))
        self.cpu_fallback_enabled = bool(self.cfg.get("cpu_fallback_enabled", False))
        self.cpu_parallel = 1
        self.cpu_endpoint = str(self.cfg.get("cpu_ollama_url", "http://127.0.0.1:11439")).rstrip("/")
        self.request_timeout = max(5.0, float(self.cfg.get("request_timeout_seconds", 75.0)))
        self.max_cpu_offload_fraction = max(0.0, min(1.0, float(self.cfg.get("max_cpu_offload_fraction", 0.12))))
        self.profile_retry_cooldown = max(5.0, float(self.cfg.get("profile_retry_cooldown_seconds", 120.0)))
        self.start_failure_retry_initial = max(15.0, float(self.cfg.get("start_failure_retry_initial_seconds", 120.0)))
        self.start_failure_retry_max = max(self.start_failure_retry_initial, float(self.cfg.get("start_failure_retry_max_seconds", 900.0)))
        self.start_failure_max_attempts = max(1, int(self.cfg.get("start_failure_max_attempts", 3)))
        self.endpoint = str(self.cfg.get("ollama_url", "http://127.0.0.1:11436")).rstrip("/")
        self._lock = threading.RLock()
        self._setup_lock = threading.Lock()
        self._cancel = threading.Event()
        self._closed = False
        self._active = 0
        self._lease = False
        self._cpu_lease = False
        self._last_error: str | None = None
        self._retry_after = 0.0
        self._consecutive_start_failures = 0
        self._startup_circuit_open = False
        self._stats = {
            "sessions": 0,
            "batches": 0,
            "submitted": 0,
            "completed": 0,
            "failed": 0,
            "preemptions": 0,
            "idle_rejections": 0,
            "unmanaged_endpoint_rejections": 0,
            "profile_rejections": 0,
            "start_failures": 0,
        }

        bg_config = copy.deepcopy(config)
        bg_config.setdefault("server", {})["ollama_url"] = self.endpoint
        # Never auto-restart a preempted background server from inside a request.
        # Session startup is owned by this class only.
        bg_config["server"]["auto_start_ollama"] = False
        bg_config.setdefault("scheduler", {})["max_parallel"] = self.parallel
        bg_config["scheduler"]["max_loaded_models"] = 1
        bg_config["scheduler"]["max_queue"] = max(self.parallel * 4, int(self.cfg.get("max_queue", 32)))
        bg_ollama = bg_config.setdefault("ollama", {})
        bg_ollama["num_parallel"] = self.parallel
        bg_ollama["keep_alive"] = str(self.cfg.get("keep_alive", "10m"))
        bg_ollama["request_attempts"] = 1
        bg_ollama["flash_attention"] = bool(self.cfg.get("flash_attention", bg_ollama.get("flash_attention", True)))
        bg_ollama["kv_cache_type"] = str(self.cfg.get("kv_cache_type", bg_ollama.get("kv_cache_type", "q8_0")))
        bg_ollama["gpu_overhead_bytes"] = int(self.cfg.get("gpu_overhead_bytes", bg_ollama.get("gpu_overhead_bytes", 268435456)))
        self.runtime = OllamaRuntime(bg_config, managed_name="ollama-background")
        self.policy = ModelExecutionPolicy(bg_config)
        self._bg_config = bg_config
        cpu_config = copy.deepcopy(config)
        cpu_config.setdefault("server", {})["ollama_url"] = self.cpu_endpoint
        cpu_config["server"]["auto_start_ollama"] = False
        cpu_config.setdefault("scheduler", {})["max_parallel"] = self.cpu_parallel
        cpu_config["scheduler"]["max_loaded_models"] = 1
        cpu_ollama = cpu_config.setdefault("ollama", {})
        cpu_ollama["num_parallel"] = self.cpu_parallel
        cpu_ollama["keep_alive"] = str(self.cfg.get("cpu_keep_alive", "10m"))
        cpu_ollama["request_attempts"] = 1
        cpu_ollama["llm_library"] = "cpu"
        cpu_profile = cpu_config.setdefault("model_execution", {}).setdefault("background", {})
        cpu_context = max(4096, int(self.cfg.get("cpu_context_tokens", cpu_profile.get("background_context_tokens", 16384))))
        cpu_profile.update({
            "context_tokens": cpu_context,
            "large_context_tokens": cpu_context,
            "max_context_tokens": cpu_context,
            "background_context_tokens": cpu_context,
            "parallel": self.cpu_parallel,
            "max_prompt_tokens": max(1024, int(self.cfg.get("cpu_max_prompt_tokens", cpu_context - 2048))),
        })
        self.cpu_runtime = OllamaRuntime(cpu_config, managed_name="ollama-background-cpu")
        self.cpu_policy = ModelExecutionPolicy(cpu_config)
        self._cpu_config = cpu_config
        # Reuse worker threads across preprocessing batches. Creating a fresh pool
        # for every four files was measurable overhead on warm repositories and also
        # churned thread stacks during long-running sessions.
        self._executor = ThreadPoolExecutor(max_workers=self.parallel, thread_name_prefix="local-ai-bg-gpu")

    def _cool_down_after_start_failure(self, error: str) -> None:
        """Prevent a broken dedicated server from repeatedly spawning processes."""
        with self._lock:
            self._consecutive_start_failures += 1
            exponent = min(self._consecutive_start_failures - 1, 8)
            delay = min(self.start_failure_retry_max, self.start_failure_retry_initial * (2 ** exponent))
            self._retry_after = max(self._retry_after, time.monotonic() + delay)
            if self._consecutive_start_failures >= self.start_failure_max_attempts:
                self._startup_circuit_open = True
                error = f"background GPU startup disabled after {self._consecutive_start_failures} failures: {error}"
            self._last_error = error
            self._stats["start_failures"] += 1

    def _foreground_requested(self) -> bool:
        if self.scheduler.foreground_busy():
            return True
        if self._cancel.is_set():
            if self.scheduler.foreground_idle_seconds() >= self.idle_seconds:
                self._cancel.clear()
                return False
            return True
        return False

    def _acquire_session(self) -> bool:
        if self._closed or not self.enabled or not self.model or self._startup_circuit_open:
            return False
        with self._lock:
            if time.monotonic() < self._retry_after:
                return False
            if self._lease and self.runtime.is_online():
                return not self._foreground_requested()

        with self._setup_lock:
            with self._lock:
                if time.monotonic() < self._retry_after:
                    return False
                if self._lease and self.runtime.is_online():
                    return not self._foreground_requested()

            if not self.scheduler.acquire_background_gpu(self.idle_seconds):
                with self._lock:
                    self._stats["idle_rejections"] += 1
                return False

            with self._lock:
                self._lease = True
                self._cancel.clear()

            try:
                # Do not hijack or rely on an unrelated service occupying the dedicated
                # port: we would be unable to guarantee NUM_PARALLEL or preempt it safely.
                if self.runtime.is_online() and not self.runtime.managed_profile_status().get("managed"):
                    parsed_port = urlparse(self.endpoint).port or 11436
                    listening_pid = find_listening_pid(parsed_port)
                    if listening_pid and "ollama" in (process_executable(listening_pid) or "").lower():
                        # Orphaned background Ollama from a prior hub run -> terminate and start clean
                        terminate_tree(listening_pid, grace_seconds=2.0)
                        time.sleep(0.4)
                    elif self.runtime.is_online():
                        with self._lock:
                            self._stats["unmanaged_endpoint_rejections"] += 1
                        self._cool_down_after_start_failure(
                            f"background Ollama endpoint already in use by unmanaged process: {self.endpoint}"
                        )
                        self.scheduler.release_background_gpu()
                        with self._lock:
                            self._lease = False
                        return False
                if not self.runtime.ensure_running():
                    raise RuntimeError("could not start dedicated background Ollama server")
                if self._foreground_requested():
                    self.preempt_foreground()
                    return False
                self.runtime.prepare_model(self.model, unload_others=True)
                if self._foreground_requested():
                    self.preempt_foreground()
                    return False
                # Enforce the measured profile, not merely the configured one. If another
                # GPU-heavy process leaves too little VRAM and Ollama spills too much of
                # the idle worker to CPU, abort the disposable session and cool down.
                details = self.runtime.loaded_model_details()
                row = next((x for x in details if str(x.get("name", "")) == self.model), None)
                offload = float((row or {}).get("cpu_offload_fraction", 0.0) or 0.0)
                if row is not None and offload > self.max_cpu_offload_fraction:
                    with self._lock:
                        self._stats["profile_rejections"] += 1
                        self._last_error = (
                            f"background model CPU offload {offload:.1%} exceeds "
                            f"limit {self.max_cpu_offload_fraction:.1%}"
                        )
                        self._retry_after = time.monotonic() + self.profile_retry_cooldown
                    self.runtime.stop_managed_server()
                    self.scheduler.release_background_gpu()
                    with self._lock:
                        self._lease = False
                    return False
                with self._lock:
                    self._stats["sessions"] += 1
                    self._last_error = None
                    self._consecutive_start_failures = 0
                    self._startup_circuit_open = False
                return True
            except Exception as exc:
                self._cool_down_after_start_failure(str(exc))
                with self._lock:
                    self._stats["failed"] += 1
                self.runtime.stop_managed_server()
                self.scheduler.release_background_gpu()
                with self._lock:
                    self._lease = False
                return False

    def ready(self) -> bool:
        if not self.enabled or not self.model or self._startup_circuit_open:
            return False
        if self.scheduler.foreground_busy():
            return False
        with self._lock:
            if time.monotonic() < self._retry_after:
                return False
            if self._lease and self.runtime.is_online():
                return not self._cancel.is_set()
        return self.scheduler.foreground_idle_seconds() >= self.idle_seconds

    def _acquire_cpu_session(self) -> bool:
        """Start the serial CPU fallback without reserving the foreground GPU."""
        if self._closed or not self.cpu_fallback_enabled or not self.model:
            return False
        with self._setup_lock:
            if self.cpu_runtime.is_online() and not self.cpu_runtime.managed_profile_status().get("managed"):
                with self._lock:
                    self._last_error = f"background CPU endpoint is unmanaged: {self.cpu_endpoint}"
                return False
            if not self.cpu_runtime.is_online() and not self.cpu_runtime.ensure_running():
                return False
            try:
                self.cpu_runtime.prepare_model(self.model, unload_others=True)
                details = self.cpu_runtime.loaded_model_details()
            except Exception as exc:
                with self._lock:
                    self._last_error = f"background CPU fallback unavailable: {exc}"
                return False
            row = next((x for x in details if str(x.get("name", "")) == self.model), None)
            if row is None or int(row.get("vram_bytes", 0) or 0) > 0:
                with self._lock:
                    self._last_error = "background CPU fallback unexpectedly used VRAM"
                self.cpu_runtime.stop_managed_server()
                return False
            with self._lock:
                self._cpu_lease = True
            return True

    def preempt_foreground(self) -> None:
        """Synchronously release VRAM for an arriving foreground request."""
        # A foreground submit may call this hook even when the idle worker has not
        # started. Do not leave a stale cancellation flag behind: that would keep
        # the worker disabled forever after the foreground request completes.
        with self._lock:
            leased = self._lease
            active = self._active
        if leased or active:
            self._cancel.set()
            # Killing only our dedicated managed server aborts all parallel disposable
            # jobs at once and releases its runner/KV allocation deterministically.
            self.runtime.stop_managed_server()
            with self._lock:
                self._stats["preemptions"] += 1
                self._lease = False
            self.scheduler.release_background_gpu()

    def _generate_one(
        self,
        task: dict[str, Any],
        *,
        runtime: OllamaRuntime | None = None,
        policy: ModelExecutionPolicy | None = None,
        config: dict[str, Any] | None = None,
        preemptible: bool = True,
    ) -> dict[str, Any]:
        runtime = runtime or self.runtime
        policy = policy or self.policy
        config = config or self._bg_config
        if preemptible and self._foreground_requested():
            return {"success": False, "preempted": True, "error": "foreground work pending"}
        prompt = str(task.get("prompt", ""))
        system = str(task.get("system", ""))
        max_tokens = max(32, int(task.get("max_tokens", 320)))
        profile_hint = policy.profile(
            self.model,
            role="background",
            input_tokens=estimate_tokens(prompt) + estimate_tokens(system),
            output_tokens=max_tokens,
            background=True,
        )
        prepared = fit_text(prompt, profile_hint.prompt_budget_tokens)
        payload, profile = policy.apply_payload(
            self.model,
            {
                "model": self.model,
                "prompt": prepared.text,
                "system": system,
                "format": task.get("schema"),
                "stream": True,
                "keep_alive": config.get("ollama", {}).get("keep_alive", "10m"),
                "options": {"num_predict": max_tokens, "temperature": float(task.get("temperature", 0.0))},
            },
            role="background",
            input_tokens=prepared.estimated_tokens,
            output_tokens=max_tokens,
            background=True,
            preserve_explicit_think=False,
        )
        response = runtime.request_interruptible(
            "/api/generate", payload,
            self._foreground_requested if preemptible else (lambda: False), timeout=self.request_timeout,
        )
        if (preemptible and self._foreground_requested()) or response.get("preempted"):
            return {"success": False, "preempted": True, "error": "background request preempted by foreground work"}
        if "error" in response:
            return {"success": False, "error": str(response["error"])}
        text = str(response.get("response", "")).strip()
        try:
            data = json.loads(text)
        except Exception:
            data = {"purpose": text[:1200], "symbols": [], "dependencies": [], "side_effects": [], "risks": [], "tests": [], "keywords": []}
        return {
            "success": True,
            "model": self.model,
            "data": data,
            "execution_profile": profile.cache_scope(),
            "load_duration_ns": response.get("load_duration", 0),
            "prompt_eval_count": response.get("prompt_eval_count", 0),
            "eval_count": response.get("eval_count", 0),
        }

    def generate_many(self, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not tasks:
            return []
        all_results: list[dict[str, Any]] = []
        batch_start = 0
        while batch_start < len(tasks):
            using_gpu = self._acquire_session()
            using_cpu = not using_gpu and self._acquire_cpu_session()
            batch_size = self.parallel if using_gpu else 1
            work = tasks[batch_start:batch_start + batch_size]
            batch_start += len(work)
            if not using_gpu and not using_cpu:
                all_results.extend([{"success": False, "preempted": True, "idle_wait": True, "error": "background GPU and CPU fallback unavailable"} for _ in work])
                continue
            if using_gpu and self._foreground_requested():
                self.preempt_foreground()
                all_results.extend([{"success": False, "preempted": True, "error": "foreground work pending"} for _ in work])
                continue

            results: list[dict[str, Any] | None] = [None] * len(work)
            with self._lock:
                self._active += len(work)
                self._stats["batches"] += 1
                self._stats["submitted"] += len(work)
            try:
                futures = {
                    self._executor.submit(
                        self._generate_one,
                        task,
                        runtime=self.runtime if using_gpu else self.cpu_runtime,
                        policy=self.policy if using_gpu else self.cpu_policy,
                        config=self._bg_config if using_gpu else self._cpu_config,
                        preemptible=using_gpu,
                    ): idx
                    for idx, task in enumerate(work)
                }
                for future in as_completed(futures):
                    idx = futures[future]
                    try:
                        result = future.result()
                    except Exception as exc:
                        result = {"success": False, "error": str(exc)}
                    results[idx] = result
                    with self._lock:
                        if result.get("success"):
                            self._stats["completed"] += 1
                        elif not result.get("preempted"):
                            self._stats["failed"] += 1
            finally:
                with self._lock:
                    self._active = max(0, self._active - len(work))
            if using_gpu and self._foreground_requested():
                self.preempt_foreground()
            all_results.extend([r or {"success": False, "error": "background worker returned no result"} for r in results])
        return all_results

    def generate(self, *, prompt: str, system: str, schema: dict[str, Any], max_tokens: int, source: str = "background") -> dict[str, Any]:
        result = self.generate_many([{
            "prompt": prompt,
            "system": system,
            "schema": schema,
            "max_tokens": max_tokens,
            "source": source,
        }])
        return result[0] if result else {"success": False, "error": "background worker unavailable"}

    def status(self) -> dict[str, Any]:
        with self._lock:
            stats = dict(self._stats)
            lease = self._lease
            active = self._active
            last_error = self._last_error
        details: list[dict[str, Any]] = []
        if lease:
            try:
                details = self.runtime.loaded_model_details()
            except Exception:
                details = []
        return {
            "enabled": self.enabled,
            "model": self.model,
            "endpoint": self.endpoint,
            "idle_seconds": self.idle_seconds,
            "foreground_idle_seconds": round(self.scheduler.foreground_idle_seconds(), 3),
            "parallel": self.parallel,
            "cpu_fallback": {
                "enabled": self.cpu_fallback_enabled,
                "endpoint": self.cpu_endpoint,
                "parallel": self.cpu_parallel,
                "server_online": bool(self._cpu_lease and self.cpu_runtime.is_online()),
            },
            "lease": lease,
            "active": active,
            "ready": self.ready(),
            "server_online": bool(lease and self.runtime.is_online()),
            "models": details,
            "last_error": last_error,
            "retry_after_seconds": round(max(0.0, self._retry_after - time.monotonic()), 2),
            "startup_circuit_open": self._startup_circuit_open,
            "max_cpu_offload_fraction": self.max_cpu_offload_fraction,
            "stats": stats,
        }

    def close(self) -> None:
        self._closed = True
        self._cancel.set()
        self.runtime.stop_managed_server()
        self.cpu_runtime.stop_managed_server()
        self._executor.shutdown(wait=False, cancel_futures=True)
        with self._lock:
            self._lease = False
        self.scheduler.release_background_gpu()
