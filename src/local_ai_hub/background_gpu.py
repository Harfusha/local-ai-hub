from __future__ import annotations

import copy
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .budget import estimate_tokens, fit_text
from .model_policy import ModelExecutionPolicy
from .ollama import OllamaRuntime


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
        prep_cfg = config.get("preprocessing", {})
        prep_cfg = prep_cfg if isinstance(prep_cfg, dict) else {}
        self.model = str(prep_cfg.get("model") or config.get("models", {}).get("background_code", "") or "")
        self.idle_seconds = max(0.0, float(self.cfg.get("idle_seconds", 60.0)))
        self.parallel = max(1, int(self.cfg.get("parallel", config.get("model_execution", {}).get("background", {}).get("parallel", 4))))
        self._normal_parallel = self.parallel
        exclusive_cfg = prep_cfg.get("exclusive", {}) if isinstance(prep_cfg, dict) else {}
        exclusive_cfg = exclusive_cfg if isinstance(exclusive_cfg, dict) else {}
        try:
            self._exclusive_parallel = min(32, max(1, int(exclusive_cfg.get("model_parallel", self.parallel))))
        except (ValueError, TypeError, OverflowError):
            self._exclusive_parallel = self.parallel
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
        self._setup_lock = threading.RLock()
        self._idle_release_timer: threading.Timer | None = None
        self._idle_release_seconds = 30.0
        self._cpu_slot = threading.Lock()
        self._cancel = threading.Event()
        self._closed = False
        self._active = 0
        self._lease = False
        self._stop_unconfirmed = False
        self._cpu_lease = False
        self._cpu_retry_after = 0.0
        self._cpu_retry_interval = self.start_failure_retry_initial
        self._last_error: str | None = None
        self._model_details: list[dict[str, Any]] = []
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

    def _idle_grace(self) -> float:
        try:
            from .operational_mode import load_operational_mode, preprocessing_mode_ready
            snapshot = load_operational_mode(self.config.get("server", {}).get("state_dir"))
            if preprocessing_mode_ready(self.config.get("server", {}).get("state_dir"), snapshot):
                return 0.0
        except (AttributeError, ImportError, OSError, TypeError, ValueError):
            pass
        return self.idle_seconds

    def _foreground_requested(self) -> bool:
        if self._stop_unconfirmed:
            return True
        if self.scheduler.foreground_busy():
            return True
        if self._cancel.is_set():
            if self.scheduler.foreground_idle_seconds() >= self._idle_grace():
                self._cancel.clear()
                return False
            return True
        return False

    def reset_circuit(self) -> None:
        """Reset the startup failure circuit breaker and retry counters."""
        with self._lock:
            self._startup_circuit_open = False
            self._consecutive_start_failures = 0
            self._retry_after = 0.0
            self._last_error = None

    def _configure_parallel_for_mode(self) -> bool:
        """Switch a managed server profile only after all submitted work drains.

        Caller holds _setup_lock, which also fences new batch admission.
        """
        try:
            from .operational_mode import load_operational_mode, preprocessing_mode_ready
            snapshot = load_operational_mode(self.config.get("server", {}).get("state_dir"))
            if snapshot.degraded or snapshot.mode not in {"active", "preprocessing"}:
                return False
            if snapshot.mode == "preprocessing" and not preprocessing_mode_ready(self.config.get("server", {}).get("state_dir"), snapshot):
                return False
            desired = self._exclusive_parallel if snapshot.mode == "preprocessing" else self._normal_parallel
        except (AttributeError, ImportError, OSError, TypeError, ValueError):
            return False
        if desired == self.parallel:
            return True
        with self._lock:
            if self._active or self._stop_unconfirmed:
                return False
            leased = self._lease
        new_config = copy.deepcopy(self._bg_config)
        new_config.setdefault("scheduler", {})["max_parallel"] = desired
        new_config["scheduler"]["max_queue"] = max(desired * 4, int(self.cfg.get("max_queue", 32)))
        new_config.setdefault("ollama", {})["num_parallel"] = desired
        new_config.setdefault("model_execution", {}).setdefault("background", {})["parallel"] = desired
        try:
            new_runtime = OllamaRuntime(new_config, managed_name="ollama-background")
            new_policy = ModelExecutionPolicy(new_config)
            new_executor = ThreadPoolExecutor(max_workers=desired, thread_name_prefix="local-ai-bg-gpu")
        except Exception as exc:
            with self._lock:
                self._last_error = f"background profile setup failed: {type(exc).__name__}"
            return False
        if leased and not self._stop_and_release_gpu():
            new_executor.shutdown(wait=False, cancel_futures=True)
            return False
        old_executor = self._executor
        self._bg_config, self.runtime, self.policy, self._executor = new_config, new_runtime, new_policy, new_executor
        self.parallel = desired
        old_executor.shutdown(wait=False, cancel_futures=True)
        return True

    def _acquire_session(self) -> bool:
        from .opencode_boundary import generation_denial

        if generation_denial() is not None:
            return False
        if self._closed or not self.enabled or not self.model or self._startup_circuit_open or self._stop_unconfirmed:
            return False
        with self._lock:
            if time.monotonic() < self._retry_after:
                return False
            if self._lease and self.runtime.is_online():
                return not self._foreground_requested()

        with self._setup_lock:
            with self._lock:
                if self._startup_circuit_open or time.monotonic() < self._retry_after:
                    return False
                if self._lease and self.runtime.is_online():
                    return not self._foreground_requested()

            if not self.scheduler.acquire_background_gpu(self._idle_grace()):
                with self._lock:
                    self._stats["idle_rejections"] += 1
                return False

            with self._lock:
                self._lease = True
                self._cancel.clear()

            try:
                def reject_unmanaged() -> bool:
                    with self._lock:
                        self._stats["unmanaged_endpoint_rejections"] += 1
                    self._cool_down_after_start_failure(
                        f"background Ollama endpoint already in use by unmanaged process: {self.endpoint}"
                    )
                    self.scheduler.release_background_gpu()
                    with self._lock:
                        self._lease = False
                    return False

                # An unrelated service cannot be safely adopted or stopped.
                if self.runtime.is_online() and not self.runtime.managed_profile_status().get("managed"):
                    return reject_unmanaged()
                if not self.runtime.ensure_running():
                    raise RuntimeError("could not start dedicated background Ollama server")
                # ensure_running can borrow a listener that appeared after the
                # first probe. Do not load or unload any model without ownership.
                if not self.runtime.managed_profile_status().get("managed"):
                    return reject_unmanaged()
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
                with self._lock:
                    self._model_details = [dict(item) for item in details]
                row = next((x for x in details if str(x.get("name", "")) == self.model), None)
                if row is None:
                    with self._lock:
                        self._stats["profile_rejections"] += 1
                        self._last_error = f"background model '{self.model}' not found in loaded model details"
                        self._retry_after = time.monotonic() + self.profile_retry_cooldown
                    self._stop_and_release_gpu()
                    return False
                offload = float(row.get("cpu_offload_fraction", 0.0) or 0.0)
                if offload > self.max_cpu_offload_fraction:
                    with self._lock:
                        self._stats["profile_rejections"] += 1
                        self._last_error = (
                            f"background model CPU offload {offload:.1%} exceeds "
                            f"limit {self.max_cpu_offload_fraction:.1%}"
                        )
                        self._retry_after = time.monotonic() + self.profile_retry_cooldown
                    self._stop_and_release_gpu()
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
                self._stop_and_release_gpu()
                return False

    def ready(self, *, server_online: bool | None = None) -> bool:
        try:
            from .operational_mode import load_operational_mode, preprocessing_mode_ready
            state_dir = self.config.get("server", {}).get("state_dir")
            mode = load_operational_mode(state_dir)
            exclusive_ready = preprocessing_mode_ready(state_dir, mode)
            if mode.degraded or (mode.mode == "preprocessing" and not exclusive_ready):
                return False
        except (AttributeError, ImportError, OSError, TypeError, ValueError):
            return False
        cpu_available = exclusive_ready and bool(getattr(self, "cpu_fallback_enabled", False))
        if not self.model or self._stop_unconfirmed or (not cpu_available and (not self.enabled or self._startup_circuit_open)):
            return False
        if self.scheduler.foreground_busy():
            return False
        if cpu_available and (not self.enabled or self._startup_circuit_open):
            return time.monotonic() >= getattr(self, "_cpu_retry_after", 0.0)
        with self._lock:
            if time.monotonic() < self._retry_after:
                return False
            if self._lease:
                online = self.runtime.is_online() if server_online is None else bool(server_online)
                if online:
                    return not self._cancel.is_set()
        return self.scheduler.foreground_idle_seconds() >= self._idle_grace()

    def _defer_cpu_session(self, reason: str) -> None:
        with self._lock:
            self._last_error = reason
            self._cpu_lease = False
            self._cpu_retry_after = time.monotonic() + self._cpu_retry_interval

    def _acquire_cpu_session(self) -> bool:
        """Start the serial CPU fallback without reserving the foreground GPU."""
        from .opencode_boundary import generation_denial

        if generation_denial() is not None:
            return False
        if self._closed or not self.cpu_fallback_enabled or not self.model:
            return False
        with self._setup_lock:
            if time.monotonic() < self._cpu_retry_after:
                return False
            try:
                online = self.cpu_runtime.is_online()
                if online and not self.cpu_runtime.managed_profile_status().get("managed"):
                    self._defer_cpu_session(f"background CPU endpoint is unmanaged: {self.cpu_endpoint}")
                    return False
                if not online and not self.cpu_runtime.ensure_running():
                    self._defer_cpu_session("background CPU server failed to start")
                    return False
            except Exception as exc:
                self._defer_cpu_session(f"background CPU server unavailable: {type(exc).__name__}")
                return False
            # Startup may have borrowed an endpoint that appeared concurrently.
            try:
                managed = self.cpu_runtime.managed_profile_status().get("managed") is True
            except Exception as exc:
                self._defer_cpu_session(f"background CPU profile unavailable: {type(exc).__name__}")
                return False
            if not managed:
                self._defer_cpu_session(f"background CPU endpoint is unmanaged: {self.cpu_endpoint}")
                return False
            try:
                self.cpu_runtime.prepare_model(self.model, unload_others=True)
                details = self.cpu_runtime.loaded_model_details()
            except Exception as exc:
                self._defer_cpu_session(f"background CPU fallback unavailable: {exc}")
                return False
            row = next((x for x in details if str(x.get("name", "")) == self.model), None)
            if row is None or int(row.get("vram_bytes", 0) or 0) > 0:
                self._defer_cpu_session("background CPU fallback unexpectedly used VRAM")
                self.cpu_runtime.stop_managed_server()
                return False
            with self._lock:
                self._cpu_lease = True
                self._cpu_retry_after = 0.0
            return True

    def _cancel_idle_release_locked(self) -> None:
        timer = self._idle_release_timer
        self._idle_release_timer = None
        if timer is not None:
            timer.cancel()

    def _schedule_idle_release(self) -> None:
        with self._setup_lock:
            with self._lock:
                if self._closed or not self._lease or self._active:
                    return
            self._cancel_idle_release_locked()

            def release_if_idle() -> None:
                with self._setup_lock:
                    if self._idle_release_timer is not timer:
                        return
                    self._idle_release_timer = None
                    with self._lock:
                        if self._closed or not self._lease or self._active:
                            return
                    self._stop_and_release_gpu()

            timer = threading.Timer(self._idle_release_seconds, release_if_idle)
            timer.daemon = True
            self._idle_release_timer = timer
            timer.start()

    def _stop_and_release_gpu(self) -> bool:
        try:
            stopped = self.runtime.stop_managed_server() is True
        except Exception:
            stopped = False
        with self._lock:
            self._stop_unconfirmed = not stopped
            if not stopped:
                self._last_error = "background server stop unconfirmed; GPU reservation retained"
                return False
            self._lease = False
            self._model_details = []
        if self.scheduler.release_background_gpu() is False:
            with self._lock:
                self._last_error = "background GPU reservation release unconfirmed"
            return False
        return True

    def preempt_foreground(self) -> bool:
        """Synchronously release VRAM for an arriving foreground request."""
        # A foreground submit may call this hook even when the idle worker has not
        # started. Do not leave a stale cancellation flag behind: that would keep
        # the worker disabled forever after the foreground request completes.
        with self._setup_lock:
            self._cancel_idle_release_locked()
            with self._lock:
                leased = self._lease
                active = self._active
            if leased or active:
                self._cancel.set()
                # Only confirmed termination permits the GPU reservation to release.
                if self._stop_and_release_gpu():
                    with self._lock:
                        self._stats["preemptions"] += 1
                    return True
                return False
            return True

    def _generate_one(
        self,
        task: dict[str, Any],
        *,
        runtime: OllamaRuntime | None = None,
        policy: ModelExecutionPolicy | None = None,
        config: dict[str, Any] | None = None,
        preemptible: bool = True,
        preprocessing: bool = False,
    ) -> dict[str, Any]:
        runtime = runtime or self.runtime
        policy = policy or self.policy
        config = config or self._bg_config
        if preemptible and self._foreground_requested():
            return {"success": False, "preempted": True, "error": "foreground work pending"}
        prompt = str(task.get("prompt", ""))
        system = str(task.get("system", ""))
        schema = task.get("schema")
        fixed_input_tokens = estimate_tokens(system)
        if schema is not None:
            fixed_input_tokens += estimate_tokens(json.dumps(schema, ensure_ascii=False, separators=(",", ":")))
        max_tokens = max(32, int(task.get("max_tokens", 320)))
        profile_hint = policy.profile(
            self.model,
            role="background",
            input_tokens=estimate_tokens(prompt) + fixed_input_tokens,
            output_tokens=max_tokens,
            background=True,
        )
        prompt_budget = profile_hint.prompt_budget_tokens - fixed_input_tokens
        if prompt_budget < 64:
            return {"success": False, "error": "context cannot fit the system prompt, output schema and request prompt"}
        prepared = fit_text(prompt, prompt_budget)
        payload, profile = policy.apply_payload(
            self.model,
            {
                "model": self.model,
                "prompt": prepared.text,
                "system": system,
                "format": schema,
                "stream": True,
                "keep_alive": config.get("ollama", {}).get("keep_alive", "10m"),
                    "options": {"num_predict": max_tokens, "temperature": float(task.get("temperature", 0.2))},
            },
            role="background",
            input_tokens=prepared.estimated_tokens + fixed_input_tokens,
            output_tokens=max_tokens,
            background=True,
            preserve_explicit_think=False,
        )
        if prepared.estimated_tokens + fixed_input_tokens > getattr(profile, 'prompt_budget_tokens', getattr(profile_hint, 'prompt_budget_tokens', 8192)):
            return {"success": False, "error": "selected context cannot fit the prepared prompt and system input"}
        # Executor jobs can sit queued across a gaming/maintenance transition.
        try:
            from .operational_mode import load_operational_mode, preprocessing_mode_ready

            mode = load_operational_mode(self.config.get("server", {}).get("state_dir"))
            if mode.degraded or not (mode.mode == "active" or (preprocessing and preprocessing_mode_ready(self.config.get("server", {}).get("state_dir"), mode))):
                return {"success": False, "preempted": True, "error_code": "operational_mode_paused", "error": "background inference start blocked by operational mode"}
        except Exception:
            return {"success": False, "preempted": True, "error_code": "operational_mode_unavailable", "error": "background inference start blocked because operational mode is unavailable"}
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
            if not isinstance(data, dict):
                return {"success": False, "error": f"Generated output is not a JSON object: {type(data).__name__}"}
            if isinstance(schema, dict) and "required" in schema and isinstance(schema["required"], list):
                missing_keys = [k for k in schema["required"] if k not in data]
                if missing_keys:
                    return {"success": False, "error": f"Generated JSON missing required keys: {missing_keys}"}
        except Exception as exc:
            return {"success": False, "error": f"Invalid JSON response: {str(exc)}"}
        return {
            "success": True,
            "model": self.model,
            "data": data,
            "prompt_budget": {"estimated_tokens": prepared.estimated_tokens,
                              "original_estimated_tokens": prepared.original_tokens,
                              "truncated": prepared.truncated},
            "execution_profile": profile.cache_scope(),
            "load_duration_ns": response.get("load_duration", 0),
            "prompt_eval_count": response.get("prompt_eval_count", 0),
            "eval_count": response.get("eval_count", 0),
        }

    def generate_many(self, tasks: list[dict[str, Any]], *, preprocessing: bool = False) -> list[dict[str, Any]]:
        if not tasks:
            return []
        from .opencode_boundary import generation_denial

        denial = generation_denial()
        if denial is not None:
            return [dict(denial) for _ in tasks]
        all_results: list[dict[str, Any]] = []
        batch_start = 0
        while batch_start < len(tasks):
            # Fence profile replacement against session acquisition and batch
            # accounting. The active count includes queued executor work.
            with self._setup_lock:
                if not self._configure_parallel_for_mode():
                    all_results.extend({"success": False, "preempted": True, "idle_wait": True,
                                        "error": "background profile transition pending"} for _ in tasks[batch_start:])
                    break
                try:
                    from .operational_mode import load_operational_mode, preprocessing_mode_ready
                    mode = load_operational_mode(self.config.get("server", {}).get("state_dir"))
                    allowed = not mode.degraded and (mode.mode == "active" or
                                                     (preprocessing is True and preprocessing_mode_ready(self.config.get("server", {}).get("state_dir"), mode)))
                except (AttributeError, ImportError, OSError, TypeError, ValueError):
                    allowed = False
                if not allowed:
                    all_results.extend({"success": False, "preempted": True,
                                        "error_code": "operational_mode_paused",
                                        "error": "background inference blocked by operational mode"} for _ in tasks[batch_start:])
                    break
                using_gpu = self._acquire_session()
                cpu_slot_acquired = False
                using_cpu = False
                if not using_gpu and self._cpu_slot.acquire(blocking=False):
                    cpu_slot_acquired = True
                    try:
                        using_cpu = self._acquire_cpu_session()
                    except BaseException:
                        self._cpu_slot.release()
                        raise
                    if not using_cpu:
                        self._cpu_slot.release()
                        cpu_slot_acquired = False
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
                self._cancel_idle_release_locked()
                with self._lock:
                    self._active += len(work)
                    self._stats["batches"] += 1
                    self._stats["submitted"] += len(work)
            results: list[dict[str, Any] | None] = [None] * len(work)
            try:
                futures = {
                    self._executor.submit(
                        self._generate_one,
                        task,
                        runtime=self.runtime if using_gpu else self.cpu_runtime,
                        policy=self.policy if using_gpu else self.cpu_policy,
                        config=self._bg_config if using_gpu else self._cpu_config,
                        preemptible=using_gpu,
                        preprocessing=preprocessing,
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
                if cpu_slot_acquired:
                    self._cpu_slot.release()
                self._schedule_idle_release()
            if using_gpu and self._foreground_requested():
                self.preempt_foreground()
            all_results.extend([r or {"success": False, "error": "background worker returned no result"} for r in results])
        return all_results

    def generate(self, *, prompt: str, system: str, schema: dict[str, Any], max_tokens: int, source: str = "background", preprocessing: bool = False) -> dict[str, Any]:
        result = self.generate_many([{
            "prompt": prompt,
            "system": system,
            "schema": schema,
            "max_tokens": max_tokens,
            "source": source,
        }], preprocessing=preprocessing)
        return result[0] if result else {"success": False, "error": "background worker unavailable"}

    def status(self) -> dict[str, Any]:
        with self._lock:
            stats = dict(self._stats)
            lease = self._lease
            active = self._active
            last_error = self._last_error
            details = [dict(item) for item in self._model_details] if lease else []
        server_online = bool(lease and self.runtime.is_online())
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
            "ready": self.ready(server_online=server_online),
            "server_online": server_online,
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
        with self._setup_lock:
            self._cancel_idle_release_locked()
            self._stop_and_release_gpu()
        try:
            self.cpu_runtime.stop_managed_server()
        finally:
            self._executor.shutdown(wait=False, cancel_futures=True)
            with self._lock:
                self._cpu_lease = False
