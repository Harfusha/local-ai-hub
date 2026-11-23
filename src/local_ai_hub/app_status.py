from __future__ import annotations

from .app import (
    Any as Any,
    ExitStack as ExitStack,
    Path as Path,
    TaskStatus as TaskStatus,
    _STATUS_DEPENDENCY_TIMEOUT_SECONDS as _STATUS_DEPENDENCY_TIMEOUT_SECONDS,
    __version__ as __version__,
    _accelerator_status_fallback as _accelerator_status_fallback,
    _online_probe_status as _online_probe_status,
    _resolve_status_dependency as _resolve_status_dependency,
    _schedule_status_dependency as _schedule_status_dependency,
    _status_dependency as _status_dependency,
    _status_dependency_timeout_seconds as _status_dependency_timeout_seconds,
    _status_probe_affects_core_health as _status_probe_affects_core_health,
    _status_probe_key as _status_probe_key,
    accelerator_status as accelerator_status,
    deepcopy as deepcopy,
    json as json,
    time as time,
)


LocalAIApp = None


class AppStatusMixin:
    def _agent_state_summary(self) -> dict[str, Any]:
        if not getattr(self, "agent_state", None) or not self.agent_state.enabled:
            return {"enabled": False}
        task_store = getattr(self, "agent_tasks", None)
        incident_store = getattr(self, "agent_incidents", None)
        learning_store = getattr(self, "agent_learning", None)
        mem_count = self.agent_memory.count() if getattr(self, "agent_memory", None) else 0
        return {
            "enabled": True,
            "status": "healthy",
            "active_tasks_count": task_store.count(TaskStatus.ACTIVE, include_stale=False) if task_store else 0,
            "tasks_count": task_store.count(include_stale=False) if task_store else 0,
            "incidents_count": incident_store.summary_count() if incident_store else 0,
            "candidates_count": learning_store.candidate_count() if learning_store else 0,
            "memory_records_count": mem_count,
            "retention_days": int(self.config.get("agent_state", {}).get("retention_days", 30)),
        }

    def realtime_status(self, *, light: bool = False, scope: str = "process") -> dict[str, Any]:
        scope = str(scope).strip().lower()
        if scope not in {"process", "window"}:
            scope = "process"
        now = time.monotonic()
        cache_key = f"{'light' if light else 'full'}:{scope}"
        cache_ttl = 5.0 if light else 1.5

        def cached_snapshot(cached: tuple[float, dict[str, Any]], now: float, *, stale: bool = False) -> dict[str, Any]:
            result = dict(cached[1])
            result["snapshot_cached"] = True
            result["status_age_ms"] = max(0, int((now - cached[0]) * 1000))
            if stale:
                result["snapshot_stale"] = True
                result["success"] = False
                result["degraded"] = True
            return result

        cached = self._live_status_cache.get(cache_key)
        if cached and now - cached[0] < cache_ttl:
            return cached_snapshot(cached, now)
        cache_lock = ExitStack()
        if cached:
            # Stale snapshots are cheap and safe; never make dashboard polls
            # wait behind a slow refresh already owned by another request.
            if not self._live_status_lock.acquire(blocking=False):
                return cached_snapshot(cached, now, stale=True)
            cache_lock.callback(self._live_status_lock.release)
        else:
            if not self._live_status_lock.acquire(blocking=False):
                return self._snapshot_warming(scope)
            cache_lock.callback(self._live_status_lock.release)

        with cache_lock:
            now = time.monotonic()
            cached = self._live_status_cache.get(cache_key)
            if cached and now - cached[0] < cache_ttl:
                return cached_snapshot(cached, now)
            dependency_status: dict[str, dict[str, Any]] = {}

            def read(key: str, callback, fallback):
                diagnostic: dict[str, Any] = {}
                timeout_seconds = _status_dependency_timeout_seconds(key)
                dep_deadline = time.monotonic() + timeout_seconds
                value, healthy = _status_dependency(
                    callback,
                    fallback,
                    key=_status_probe_key("live", scope, key),
                    completed_cache=getattr(self, "_status_metadata_cache", None),
                    lock=self._status_dependency_lock,
                    inflight=self._status_dependency_inflight,
                    slots=self._status_dependency_slots,
                    executor=self._status_dependency_executor,
                    deadline=dep_deadline,
                    diagnostic=diagnostic,
                )
                dependency_status[key] = {
                    "degraded": not healthy,
                    "deadline_ms": int(timeout_seconds * 1000),
                    **diagnostic,
                }
                return value, healthy

            headless, headless_healthy = read("headless", self._headless_status, {})
            ollama = headless.get("ollama_online") if headless.get("supervisor") else None
            runtime_healthy = True
            profile_healthy = True
            # The supervisor status file is asynchronous and can lag behind a
            # live endpoint during restart/recovery. Prefer the runtime probe
            # for the public live/doctor status so stale supervisor state does
            # not report a healthy Ollama process as offline.
            runtime = getattr(self, "runtime", None)
            if runtime is not None:
                ollama, runtime_healthy = read("runtime.online", runtime.is_online, None)
                ollama = bool(ollama) if runtime_healthy else None
                if isinstance(headless, dict) and headless.get("supervisor"):
                    headless = dict(headless)
                    headless["ollama_online"] = ollama
                ollama_profile, profile_healthy = read("ollama_profile", runtime.managed_profile_status, {})
            else:
                ollama_profile = {}
            ollama_status = _online_probe_status(ollama, runtime_healthy)
            scheduler, scheduler_healthy = read("scheduler", self.scheduler.status, {})
            prep_stats, prep_stats_healthy = read("preprocessing.stats", self.preprocessor.stats, {})
            prep_status, prep_status_healthy = read("preprocessing.status", self.preprocessor.status, {"success": False, "projects": []})
            projects = []
            for item in prep_status.get("projects", []) if isinstance(prep_status, dict) else []:
                root = str(item.get("root", ""))
                proj_name = item.get("project") or Path(root).name or root
                if light:
                    row = {
                        "root": root,
                        "project": proj_name,
                    }
                    # The dashboard polls this compact projection. Keep its
                    # progress and worktree identity fields, but not arbitrary
                    # project stats or lists of paths, in the frequent response.
                    for key in (
                        "status", "phase", "overall_progress_pct",
                        "git_common_dir", "is_worktree", "paused", "waiting",
                        "last_error_short", "waiting_reason", "active_detail",
                        "phase_index", "total_phases", "phase_progress_pct", "phase_progress_measured",
                        "speed_str", "eta_str", "progress_age_seconds", "last_complete_at",
                        "files", "hashed_files", "code_index_files", "rag_files",
                        "rag_indexed_files", "rag_chunked_files", "rag_chunks", "file_cards",
                    ):
                        if key in item:
                            row[key] = item[key]
                    projects.append(row)
                else:
                    row = dict(item)
                    row["project"] = proj_name
                    projects.append(row)
            from .features import FeatureSet
            fs = FeatureSet.from_config(self.config)
            observability, telemetry_healthy = read("telemetry.summary", lambda: self.telemetry.realtime_summary(scope=scope, light=light), {})
            accelerators, accelerator_healthy = read("accelerators", lambda: accelerator_status(self.config), _accelerator_status_fallback(self.config))
            background_gpu, background_gpu_healthy = read("background_gpu", self.background_gpu.status, {})
            model_policy = getattr(getattr(self, "services", None), "model_policy", None)
            model_execution, model_execution_healthy = read("model_execution", model_policy.summary if model_policy else lambda: {}, {})
            from .model_lifecycle import lifecycle_status
            model_execution = {**model_execution, "lifecycle": lifecycle_status()}
            vram_balancer_obj = getattr(self, "vram_balancer", None)
            vram_balancer, vram_balancer_healthy = read("vram_balancer", (lambda: vram_balancer_obj.status(force=True)) if vram_balancer_obj else lambda: {}, {})
            benchmark_obj = getattr(self, "benchmark_runner", None)
            benchmark, benchmark_healthy = read("benchmark", benchmark_obj.get_latest_summary if benchmark_obj else lambda: {"available": False}, {"available": False})
            debug_traces, traces_healthy = read("debug_traces", self.debug_traces.stats, {})
            external_tools = getattr(self, "external_tools", None)
            code_intelligence, _ = read("code_intelligence", external_tools.status if external_tools else lambda: {}, {})
            agent_state, _ = read("agent_state", self._agent_state_summary, {"enabled": False})
            runtime_stats = {}
            for key, callback in (
                ("generation_cache", self.services.generation_cache.stats),
                ("semantic_cache", self.services.semantic_cache.stats),
                ("repo_cache", self.services.repo_cache.stats),
                ("repo_state", self.repo_state.stats),
                ("repo_snapshots", self.repo_tools.snapshot_stats),
                ("commands", self.commands.stats),
                ("pipeline", self.pipeline.stats),
                ("tool_agent", self.tool_agent.stats),
            ):
                runtime_stats[key], _ = read(f"runtime_stats.{key}", callback, {})
            if not light and self.deterministic is not None:
                runtime_stats["deterministic"], _ = read("runtime_stats.deterministic", self.deterministic.status, {})
            if not light and self.code_index is not None:
                runtime_stats["code_index"], _ = read("runtime_stats.code_index", self.code_index.status, {})
            core_degraded = any(
                _status_probe_affects_core_health(name, healthy=not item["degraded"])
                for name, item in dependency_status.items()
            )
            result = {
                "success": not core_degraded, "hub_online": True, "version": __version__,
                "snapshot_cached": False, "degraded": core_degraded,
                "dependency_status": dependency_status,
                "uptime_seconds": max(0, int(time.time() - self.started_at)),
                "features": {
                    "status": fs.status,
                    "repo": fs.repo,
                    "tasks": fs.tasks,
                    "rag": fs.rag,
                    "commands": fs.commands,
                    "coord": fs.coord,
                    "artifacts": fs.artifacts,
                    "code_intelligence": fs.code_intelligence,
                    "preprocessing": fs.preprocessing,
                    "subagents": fs.subagents,
                    "agent_os": fs.agent_os,
                    "dashboard": fs.dashboard,
                    "work_orchestrator": fs.work_orchestrator,
                    "laya": fs.laya,
                },
                "models": dict(self.config.get("models", {})),
                "hardware": dict(self.config.get("_hardware", {})),
                "hardware_profile": fs.hardware_profile,
                "capabilities": fs.capability_status(),
                "accelerators": accelerators,
                "code_intelligence": code_intelligence,
                "runtime_profile": {
                    "tiered_models": self.config.get("models", {}).get("heavy_code") != self.config.get("models", {}).get("fast_code"),
                    "max_loaded_models": int(self.config.get("scheduler", {}).get("max_loaded_models", 1)),
                    "max_parallel": int(self.config.get("scheduler", {}).get("max_parallel", 1)),
                    "execution": model_execution,
                    "flash_attention": bool(self.config.get("ollama", {}).get("flash_attention", True)),
                    "kv_cache_type": "q4_0",
                },
                "ollama_online": ollama, "ollama_status": ollama_status, "scheduler": scheduler,
                "headless": headless,
                "background_gpu": background_gpu,
                "ollama_profile": ollama_profile,
                "model_execution": model_execution,
                "vram_balancer": vram_balancer,
                "benchmark": benchmark,
                "debug_traces": debug_traces,
                "training_capture": self.training_collector.get_stats() if getattr(self, "training_collector", None) else {"enabled": False},
                "laya": dict(self.config.get("laya", {})),
                "laya_runtime": self.laya_lifecycle.status if getattr(self, "laya_lifecycle", None) else {
                    "available": False,
                    "model_configuration": "unconfigured",
                    "missing_configuration_fields": ["checkpoint_path", "revision", "expected_sha256"],
                    "provider_close_configured": False,
                    "idle_unload_seconds": 600.0,
                    "inflight": 0,
                    "loading": False,
                    "closing": False,
                    "shutdown": False,
                    "unload_count": 0,
                    "last_close_error": None,
                    "runtime_verification": "NOT_VERIFIED",
                },
                "observability": observability,
                "preprocessing": {
                    **({
                        "success": bool(prep_status.get("success", True)),
                        "enabled": bool(prep_status.get("enabled", True)),
                        "max_preprocessing_projects": prep_status.get(
                            "max_preprocessing_projects",
                            prep_stats.get("max_preprocessing_projects", 1)
                            if isinstance(prep_stats, dict) else 1,
                        ),
                    } if light and isinstance(prep_status, dict) else (prep_status if isinstance(prep_status, dict) else {})),
                    **({} if light else prep_stats),
                    "projects": projects,
                    "paused": bool(prep_status.get("paused", False)) if isinstance(prep_status, dict) else False,
                    "global_diagnostic": str(prep_status.get("global_diagnostic", "")) if isinstance(prep_status, dict) else "",
                    "scheduler_background_allowed": prep_status.get("scheduler_background_allowed", True) if isinstance(prep_status, dict) else True,
                    "query_hit_rate": observability.get("preprocessed_query_hit_rate", 0.0),
                },
                "runtime_stats": runtime_stats,
            }
            result["agent_state"] = agent_state
            for key, healthy in (("headless", headless_healthy), ("runtime.online", runtime_healthy), ("ollama_profile", profile_healthy), ("scheduler", scheduler_healthy), ("preprocessing.stats", prep_stats_healthy), ("preprocessing.status", prep_status_healthy), ("telemetry.summary", telemetry_healthy), ("accelerators", accelerator_healthy), ("background_gpu", background_gpu_healthy), ("model_execution", model_execution_healthy), ("vram_balancer", vram_balancer_healthy), ("benchmark", benchmark_healthy), ("debug_traces", traces_healthy)):
                if _status_probe_affects_core_health(key, healthy=healthy):
                    result["success"] = False
            self._live_status_cache[cache_key] = (now, result)
            return dict(result)

    def status(self, *, scope: str = "process") -> dict[str, Any]:
        deadline = time.monotonic() + max(0.0, float(_STATUS_DEPENDENCY_TIMEOUT_SECONDS))
        scope = str(scope).strip().lower()
        if scope not in {"process", "window"}:
            scope = "process"
        import os

        def dependency(key, callback, fallback, diagnostic=None):
            dependency_deadline = deadline
            if key in {"telemetry.summary", "scheduler", "runtime.online", "agent_state", "recovery"}:
                dependency_deadline = time.monotonic() + _status_dependency_timeout_seconds(key)
            return _status_dependency(
                callback,
                fallback,
                key=_status_probe_key("full", scope, key),
                completed_cache=getattr(self, "_status_metadata_cache", None),
                lock=self._status_dependency_lock,
                inflight=self._status_dependency_inflight,
                slots=self._status_dependency_slots,
                executor=self._status_dependency_executor,
                deadline=dependency_deadline,
                diagnostic=diagnostic,
            )

        def cached_snapshot(cached: dict[str, Any], now: float, *, stale: bool = False) -> dict[str, Any]:
            result = deepcopy(cached["data"])
            if "agent_state" in result:
                result["agent_state"], _ = dependency(
                    "agent_state",
                    self._agent_state_summary,
                    result["agent_state"],
                )
            result["snapshot_cached"] = True
            result["status_age_ms"] = max(0, int((now - cached["time"]) * 1000))
            if stale:
                result["snapshot_stale"] = True
                result["success"] = False
                result["degraded"] = True
            return result

        now = time.monotonic()
        cached = self._status_full_cache.get(scope)
        if cached and now - cached["time"] < 2.0:
            return cached_snapshot(cached, now)
        cache_lock = ExitStack()
        if cached:
            if not self._status_full_cache_lock.acquire(blocking=False):
                return cached_snapshot(cached, now, stale=True)
            cache_lock.callback(self._status_full_cache_lock.release)
        else:
            if not self._status_full_cache_lock.acquire(blocking=False):
                return self._snapshot_warming(scope)
            cache_lock.callback(self._status_full_cache_lock.release)

        with cache_lock:
            now = time.monotonic()
            cached = self._status_full_cache.get(scope)
            if cached and now - cached["time"] < 2.0:
                return cached_snapshot(cached, now)
            degraded = False
            dependency_status: dict[str, dict[str, Any]] = {}
            pending_dependencies: dict[str, tuple[dict[str, Any], Any, dict[str, Any], float]] = {}

            def read(key, callback, fallback):
                nonlocal degraded
                probe_started = time.monotonic()
                pending = pending_dependencies.pop(key, None)
                if pending is None:
                    diagnostic: dict[str, Any] = {}
                    value, healthy = dependency(key, callback, fallback, diagnostic)
                else:
                    handle, fallback, diagnostic, dependency_deadline = pending
                    value, healthy = _resolve_status_dependency(
                        handle, deadline=dependency_deadline, diagnostic=diagnostic
                    )
                degraded = degraded or _status_probe_affects_core_health(key, healthy=healthy)
                dependency_status[key] = {
                    "degraded": not healthy,
                    "deadline_ms": int(_status_dependency_timeout_seconds(key) * 1000),
                    "duration_ms": max(0, int((time.monotonic() - probe_started) * 1000)),
                    **diagnostic,
                }
                return value

            # Start the scheduler before the runtime probe so its bounded
            # status work proceeds independently of the runtime's own budget.
            scheduler_diagnostic: dict[str, Any] = {}
            scheduler_deadline = time.monotonic() + _status_dependency_timeout_seconds("scheduler")
            scheduler_handle = _schedule_status_dependency(
                self.scheduler.status,
                {},
                key=_status_probe_key("full", scope, "scheduler"),
                completed_cache=getattr(self, "_status_metadata_cache", None),
                lock=self._status_dependency_lock,
                inflight=self._status_dependency_inflight,
                slots=self._status_dependency_slots,
                executor=self._status_dependency_executor,
                deadline=scheduler_deadline,
                diagnostic=scheduler_diagnostic,
            )
            pending_dependencies["scheduler"] = (
                scheduler_handle, {}, scheduler_diagnostic, scheduler_deadline
            )

            runtime_diagnostic: dict[str, Any] = {}
            runtime_probe_started = time.monotonic()
            online, runtime_healthy = dependency("runtime.online", self.runtime.is_online, False, runtime_diagnostic)
            degraded = degraded or not runtime_healthy
            dependency_status["runtime.online"] = {
                "degraded": not runtime_healthy,
                "deadline_ms": max(0, int(_STATUS_DEPENDENCY_TIMEOUT_SECONDS * 1000)),
                "duration_ms": max(0, int((time.monotonic() - runtime_probe_started) * 1000)),
                **runtime_diagnostic,
            }
            ollama_status = _online_probe_status(online, runtime_healthy)
            version = read("runtime.version", self.runtime.version, None) if online else None
            installed: list[str] = read("runtime.installed_models", self.runtime.installed_models, []) if online else []
            loaded_details: list[dict[str, Any]] = read("runtime.loaded_model_details", self.runtime.loaded_model_details, []) if online else []
            loaded = [str(row.get("name", "")) for row in loaded_details if row.get("name")]
            # Every full-snapshot probe shares the deadline created at entry.
            # Runtime availability cannot silently grant later probes a fresh budget.
            status_probes = {
                "accelerators": (lambda: accelerator_status(self.config), _accelerator_status_fallback(self.config)),
                "telemetry.summary": (lambda: self.telemetry.summary(scope=scope, _flush=False, session_limit=5), {}),
                "model_execution": (self.services.model_policy.summary, {}),
                "ollama_profile": (self.runtime.managed_profile_status, {}),
                "background_gpu": (self.background_gpu.status, {}),
                "generation_cache": (self.services.generation_cache.stats, {}),
                "semantic_cache": (self.services.semantic_cache.stats, {}),
                "repo_cache": (self.services.repo_cache.stats, {}),
                "commands": (self.commands.stats, {}),
                "repo_snapshots": (self.repo_tools.snapshot_stats, {}),
                "lossless_router": (self.token_router.stats, {}),
                "pipeline": (self.pipeline.stats, {}),
                "preprocessing": (self.preprocessor.stats, {}),
                "tool_agent": (self.tool_agent.stats, {}),
                "code_index": (self.code_index.status, {}),
                "deterministic": (self.deterministic.status, {}),
                "evidence_store": (self.evidence.stats, {}),
                "learning": (self.learner.stats, {}),
                "autotune": (self.tuner.stats, {}),
                "circuit_breakers": (self.services.breakers.status, {}),
                "recovery": (lambda: self.recovery.status(limit=8), {}),
                "embeddings": (self.embeddings.status, {}),
                "reranker": (self.reranker.status, {}),
                "code_intelligence": (self.external_tools.status, {}),
                "debug_traces": (self.debug_traces.stats, {}),
                "agent_state": (self._agent_state_summary, {"enabled": False}),
            }
            for key, (callback, fallback) in status_probes.items():
                diagnostic: dict[str, Any] = {}
                dependency_deadline = deadline
                if key in {"telemetry.summary", "agent_state", "recovery"}:
                    dependency_deadline = time.monotonic() + _status_dependency_timeout_seconds(key)
                handle = _schedule_status_dependency(
                    callback,
                    fallback,
                    key=_status_probe_key("full", scope, key),
                    completed_cache=getattr(self, "_status_metadata_cache", None),
                    lock=self._status_dependency_lock,
                    inflight=self._status_dependency_inflight,
                    slots=self._status_dependency_slots,
                    executor=self._status_dependency_executor,
                    deadline=dependency_deadline,
                    diagnostic=diagnostic,
                )
                pending_dependencies[key] = (handle, fallback, diagnostic, dependency_deadline)
            scheduler = read("scheduler", self.scheduler.status, {})
            accelerators = read(
                "accelerators",
                lambda: accelerator_status(self.config),
                _accelerator_status_fallback(self.config),
            )
            telemetry_summary = read("telemetry.summary", lambda: self.telemetry.summary(scope=scope, _flush=False, session_limit=5), {})
            model_execution = read("model_execution", self.services.model_policy.summary, {})
            ollama_profile = read("ollama_profile", self.runtime.managed_profile_status, {})
            background_gpu = read("background_gpu", self.background_gpu.status, {})
            generation_cache = read("generation_cache", self.services.generation_cache.stats, {})
            semantic_cache = read("semantic_cache", self.services.semantic_cache.stats, {})
            repo_cache = read("repo_cache", self.services.repo_cache.stats, {})
            commands = read("commands", self.commands.stats, {})
            repo_snapshots = read("repo_snapshots", self.repo_tools.snapshot_stats, {})
            lossless_router = read("lossless_router", self.token_router.stats, {})
            pipeline = read("pipeline", self.pipeline.stats, {})
            preprocessing = read("preprocessing", self.preprocessor.stats, {})
            tool_agent = read("tool_agent", self.tool_agent.stats, {})
            code_index = read("code_index", self.code_index.status, {})
            deterministic = read("deterministic", self.deterministic.status, {})
            evidence_store = read("evidence_store", self.evidence.stats, {})
            learning = read("learning", self.learner.stats, {})
            autotune = read("autotune", self.tuner.stats, {})
            circuit_breakers = read("circuit_breakers", self.services.breakers.status, {})
            recovery = read("recovery", lambda: self.recovery.status(limit=8), {})
            embeddings = read("embeddings", self.embeddings.status, {})
            reranker = read("reranker", self.reranker.status, {})
            code_intelligence = read("code_intelligence", self.external_tools.status, {})
            debug_traces = read("debug_traces", self.debug_traces.stats, {})
            agent_state = read("agent_state", self._agent_state_summary, {"enabled": False})
            res = {
                "success": not degraded, "snapshot_cached": False, "degraded": degraded, "dependency_status": dependency_status,
                "hub_pid": os.getpid(), "hub_online": True, "version": __version__,
                "uptime_seconds": max(0, int(time.time() - self.started_at)),
                "ollama_online": online, "ollama_status": ollama_status, "online": online, "ollama_version": version,
                "installed_models": installed, "loaded_models": loaded, "loaded_model_details": loaded_details, "models": dict(self.config["models"]),
                "model_execution": model_execution, "ollama_profile": ollama_profile,
                "background_gpu": background_gpu,
                "scheduler": scheduler, "generation_cache": generation_cache,
                "semantic_cache": semantic_cache, "repo_cache": repo_cache,
                "commands": commands, "repo_snapshots": repo_snapshots,
                "lossless_router": lossless_router, "pipeline": pipeline,
                "preprocessing": preprocessing, "tool_agent": tool_agent,
                "code_index": code_index, "deterministic": deterministic, "evidence_store": evidence_store,
                "learning": learning, "autotune": autotune,
                "circuit_breakers": circuit_breakers, "recovery": recovery,
                "fallback_count": self.services.fallback_count, "embeddings": embeddings,
                "reranker": reranker, "features": dict(self.config.get("features", {})),
                "hardware": dict(self.config.get("_hardware", {})), "accelerators": accelerators,
                "code_intelligence": code_intelligence,
                "laya_runtime": self.laya_lifecycle.status,
                "training_capture": self.training_collector.get_stats() if getattr(self, "training_collector", None) else {"enabled": False},
                "observability": telemetry_summary, "token_saving": ({k: v for k, v in telemetry_summary.items() if k != "sessions"} if isinstance(telemetry_summary, dict) else telemetry_summary), "debug_traces": debug_traces,
            }
            res["agent_state"] = agent_state
            self._status_full_cache[scope] = {"time": time.monotonic(), "data": deepcopy(res)}
            return deepcopy(res)

    def _snapshot_warming(self, scope: str) -> dict[str, Any]:
        return {
            "success": False,
            "error": "status snapshot is warming",
            "retryable": True,
            "terminal": False,
            "degraded": True,
            "snapshot_warming": True,
            "snapshot_cached": False,
            "status_age_ms": 0,
            "retry_after_ms": 100,
            "scope": scope,
            "hub_online": True,
            "version": __version__,
            "uptime_seconds": max(0, int(time.time() - self.started_at)),
            "dependency_status": {
                "snapshot": {"deadline_ms": 0, "degraded": True, "status": "warming"}
            },
        }

    def _headless_status(self) -> dict[str, Any]:
        import json
        state_dir = Path(self.config["server"]["state_dir"])
        path = state_dir / "supervisor.status.json"
        data: dict[str, Any] = {"enabled": bool(self.config.get("headless", {}).get("enabled", True)), "supervisor": False}
        try:
            if path.exists():
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    data.update(raw)
                    data["supervisor"] = True
                    heartbeat = float(raw.get("heartbeat", 0) or 0)
                    stale_after = max(10.0, float(self.config.get("headless", {}).get("health_check_interval_seconds", 2.0)) * 4)
                    if heartbeat and time.time() - heartbeat > stale_after:
                        data["state"] = "stale"
                        data["heartbeat_stale"] = True
        except Exception:
            data["status_error"] = True
        return data

    @staticmethod
    def _bundle_encode(value: Any) -> Any:
        """Convert SQLite values to a lossless JSON representation."""
        import base64
        if isinstance(value, memoryview):
            value = value.tobytes()
        if isinstance(value, (bytes, bytearray)):
            return {"__local_ai_hub_bytes__": base64.b64encode(bytes(value)).decode("ascii")}
        if isinstance(value, dict):
            return {str(k): LocalAIApp._bundle_encode(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [LocalAIApp._bundle_encode(v) for v in value]
        return value

    @staticmethod
    def _bundle_decode(value: Any) -> Any:
        import base64
        if isinstance(value, dict):
            if set(value) == {"__local_ai_hub_bytes__"} and isinstance(value.get("__local_ai_hub_bytes__"), str):
                return base64.b64decode(value["__local_ai_hub_bytes__"], validate=True)
            return {str(k): LocalAIApp._bundle_decode(v) for k, v in value.items()}
        if isinstance(value, list):
            return [LocalAIApp._bundle_decode(v) for v in value]
        return value

    def _bundle_limits(self) -> tuple[int, int, int]:
        cfg = self.config.get("bundles", {})
        return (
            max(1024, int(cfg.get("max_bundle_bytes", 128 * 1024 * 1024))),
            max(1024, int(cfg.get("max_json_bytes", 256 * 1024 * 1024))),
            max(1, int(cfg.get("max_rows_per_table", 1_000_000))),
        )

    def export_diagnostics(self, *, cancelled: Any = None, candidate_export: Any = None) -> Any:
        """Build a large installation-wide support archive without project filtering."""
        from .diagnostics_export import (
            DEFAULT_MAX_ARCHIVE_BYTES,
            DEFAULT_MAX_SOURCE_BYTES,
            create_diagnostics_archive,
        )

        limits = self.config.get("diagnostics_export", {})
        max_archive_bytes = int(limits.get("max_archive_bytes", DEFAULT_MAX_ARCHIVE_BYTES))
        max_source_bytes = int(limits.get("max_source_bytes", DEFAULT_MAX_SOURCE_BYTES))
        state_dir = Path(self.config["server"]["state_dir"])
        flush_complete = self.telemetry.flush(1.0) if getattr(self, "telemetry", None) else False
        laya_candidate_payload = None
        if candidate_export is not None:
            if type(candidate_export) is not dict or set(candidate_export) != {"root", "laya_candidate_export"}:
                raise ValueError("candidate ZIP export requires root and laya_candidate_export")
            if (type(candidate_export["root"]) is not str or not candidate_export["root"]
                    or not Path(candidate_export["root"]).expanduser().is_absolute()):
                raise ValueError("candidate ZIP export root must be an absolute repository path")
            laya_candidate_payload = self.laya_candidates.export_train_payload(
                candidate_export["laya_candidate_export"],
                root=candidate_export["root"],
                task_store=self.agent_tasks,
            )
        laya_telemetry = {"status": "unavailable"}
        if getattr(self, "telemetry", None):
            telemetry_report = self.telemetry.report(_flush=False)
            laya_telemetry = {
                "generated_at": telemetry_report.get("generated_at"),
                "window_days": telemetry_report.get("window_days"),
                "decisions": telemetry_report.get("laya_decisions", {"status": "unavailable"}),
                "runtime": self.laya_lifecycle.status,
            }
        return create_diagnostics_archive(
            state_dir,
            max_archive_bytes=max_archive_bytes,
            max_source_bytes=max_source_bytes,
            config=self.config,
            telemetry_flush_complete=flush_complete,
            laya_candidate_payload=laya_candidate_payload,
            laya_telemetry=laya_telemetry,
            cancelled=cancelled,
        )

    def agent_state_cleanup(self, now: float | None = None) -> int:
        """Remove expired terminal records (incidents, receipts, memories) without touching active tasks."""
        if not getattr(self, "agent_state", None) or not self.agent_state.enabled:
            return 0
        if not self.agent_state.db_path.exists():
            return 0
        current_time = float(time.time() if now is None else now)
        from .sqlite_support import connect_sqlite, retry_busy, write_transaction

        def _cleanup() -> int:
            cnt = 0
            con = connect_sqlite(self.agent_state.db_path, isolation_level=None)
            try:
                with write_transaction(
                    con, max_duration_seconds=2.0, rollback_label="expired agent state cleanup"
                ):
                    cur = con.execute(
                        "DELETE FROM agent_incidents WHERE expires_at IS NOT NULL AND expires_at <= ?",
                        (current_time,)
                    )
                    cnt += cur.rowcount if cur.rowcount > 0 else 0

                    cur2 = con.execute(
                        "DELETE FROM agent_verification_receipts WHERE expires_at IS NOT NULL AND expires_at <= ?",
                        (current_time,)
                    )
                    cnt += cur2.rowcount if cur2.rowcount > 0 else 0

                    cur3 = con.execute(
                        "DELETE FROM agent_memory_records WHERE expires_at IS NOT NULL AND expires_at <= ?",
                        (current_time,)
                    )
                    cnt += cur3.rowcount if cur3.rowcount > 0 else 0
                    return cnt
            finally:
                con.close()

        return retry_busy(_cleanup, retries=5, base_delay_seconds=0.02)

    def _recover_pending_bundle_imports(self) -> None:
        """Replay durable bundle imports before the app starts serving requests."""
        import hashlib

        journal_dir = Path(self.config["server"]["state_dir"]) / "bundle-imports"
        recovered = 0
        cleanup_pending = False
        if not journal_dir.exists() and not journal_dir.is_symlink():
            self._bundle_import_recovery = {"status": "complete", "recovered": 0}
            return
        max_bundle, _, _ = self._bundle_limits()
        try:
            if journal_dir.is_symlink() or not journal_dir.is_dir():
                raise RuntimeError("bundle import journal path is not a regular directory")
            journaled_payload_ids: set[str] = set()
            for journal_path in sorted(journal_dir.glob("*.json")):
                if journal_path.is_symlink() or not journal_path.is_file():
                    raise RuntimeError("bundle import journal is not a regular file")
                if journal_path.stat().st_size > 16_384:
                    raise RuntimeError("bundle import journal exceeds its metadata limit")
                manifest = json.loads(journal_path.read_text(encoding="utf-8"))
                import_id = str(manifest.get("import_id", "")) if isinstance(manifest, dict) else ""
                if len(import_id) != 64 or any(ch not in "0123456789abcdef" for ch in import_id):
                    raise RuntimeError("bundle import journal has an invalid import id")
                if manifest.get("schema_version") != 1 or manifest.get("status") not in {"staging", "incomplete", "complete"}:
                    raise RuntimeError("bundle import journal has an unsupported schema or status")
                if not isinstance(manifest.get("completed_phases"), list):
                    raise RuntimeError("bundle import journal progress is invalid")
                if journal_path.stem != import_id:
                    raise RuntimeError("bundle import journal filename does not match its import id")
                journaled_payload_ids.add(import_id)
                payload_path = journal_dir / f"{import_id}.bundle"
                if payload_path.is_symlink():
                    raise RuntimeError("bundle import staged payload cannot be a symlink")
                if str(manifest.get("status", "")) == "complete":
                    try:
                        payload_path.unlink(missing_ok=True)
                        journal_path.unlink(missing_ok=True)
                    except OSError:
                        cleanup_pending = True
                    recovered += 1
                    continue
                if not payload_path.is_file() or payload_path.stat().st_size > max_bundle:
                    raise RuntimeError("bundle import staged payload is missing or exceeds the configured limit")
                payload = payload_path.read_bytes()
                expected = str(manifest.get("bundle_sha256", ""))
                if not expected or hashlib.sha256(payload).hexdigest() != expected:
                    raise RuntimeError("bundle import staged payload failed its integrity check")
                target_root = manifest.get("target_root")
                if target_root is not None and (not isinstance(target_root, str) or not target_root):
                    raise RuntimeError("bundle import journal target root is invalid")
                normalized_target_root = (
                    str(Path(target_root).resolve(strict=False)).replace("\\", "/")
                    if target_root is not None
                    else None
                )
                if target_root != normalized_target_root:
                    raise RuntimeError("bundle import journal target root is not canonical")
                expected_import_id = hashlib.sha256(
                    f"{expected}\0{normalized_target_root or ''}".encode("utf-8")
                ).hexdigest()
                if import_id != expected_import_id:
                    raise RuntimeError("bundle import journal target root does not match import identity")
                result = self.import_bundle(payload, normalized_target_root)
                if not result.get("success") or result.get("recovery_pending"):
                    raise RuntimeError(str(result.get("error", "bundle import replay did not complete")))
                recovered += 1
            for payload_path in journal_dir.glob("*.bundle"):
                if payload_path.is_symlink() or not payload_path.is_file():
                    raise RuntimeError("bundle import staged payload is not a regular file")
                if payload_path.stem not in journaled_payload_ids:
                    raise RuntimeError("untracked staged bundle payload has no journal")
        except Exception as exc:
            self._bundle_import_recovery = {
                "status": "incomplete",
                "degraded": True,
                "recovered": recovered,
                "error": f"{type(exc).__name__}: {exc}",
            }
            raise RuntimeError(f"bundle import recovery incomplete: {exc}") from exc
        self._bundle_import_recovery = {"status": "complete", "recovered": recovered}
        if cleanup_pending:
            self._bundle_import_recovery["cleanup_pending"] = True

