from __future__ import annotations

from .app import (
    AffinityScheduler as AffinityScheduler,
    AgentConsistencyGuard as AgentConsistencyGuard,
    AgentProjector as AgentProjector,
    AgentStateStore as AgentStateStore,
    Any as Any,
    ArtifactStore as ArtifactStore,
    AsyncJobManager as AsyncJobManager,
    BlackboardStore as BlackboardStore,
    CodeIndex as CodeIndex,
    CommandBroker as CommandBroker,
    ContextCompiler as ContextCompiler,
    DEFAULT_IDLE_UNLOAD_SECONDS as DEFAULT_IDLE_UNLOAD_SECONDS,
    DesktopUpdates as DesktopUpdates,
    DebugTraceStore as DebugTraceStore,
    DeterministicEngine as DeterministicEngine,
    EmbeddingModel as EmbeddingModel,
    EndpointStatsStore as EndpointStatsStore,
    EvidenceStore as EvidenceStore,
    ExternalCodeIntelligence as ExternalCodeIntelligence,
    HardwareBenchmarkRunner as HardwareBenchmarkRunner,
    IdleGPUWorker as IdleGPUWorker,
    IncidentStore as IncidentStore,
    LayaCandidateStore as LayaCandidateStore,
    LayaSessionLifecycle as LayaSessionLifecycle,
    LearningStore as LearningStore,
    LocalAIServices as LocalAIServices,
    LocalAgentPipeline as LocalAgentPipeline,
    LosslessTokenRouter as LosslessTokenRouter,
    Mapping as Mapping,
    MemoryStore as MemoryStore,
    OllamaRuntime as OllamaRuntime,
    Path as Path,
    PolicyEngine as PolicyEngine,
    ProjectPreprocessor as ProjectPreprocessor,
    RAGStore as RAGStore,
    RecoveryJournal as RecoveryJournal,
    RepoStateTracker as RepoStateTracker,
    RepositoryTools as RepositoryTools,
    Reranker as Reranker,
    RoutingEngine as RoutingEngine,
    RuntimeTuner as RuntimeTuner,
    ScopeLeaseStore as ScopeLeaseStore,
    SemaphoreStore as SemaphoreStore,
    SpeculativeLintQueue as SpeculativeLintQueue,
    SwarmCoordinator as SwarmCoordinator,
    TaskStore as TaskStore,
    TelemetryStore as TelemetryStore,
    TieredOllamaRuntime as TieredOllamaRuntime,
    ToolAwareLocalAgent as ToolAwareLocalAgent,
    UsageLearner as UsageLearner,
    VRAMBalancer as VRAMBalancer,
    VerificationStore as VerificationStore,
    WorkOrchestrator as WorkOrchestrator,
    WorkspaceMemoryStore as WorkspaceMemoryStore,
    _PREWARM_RETRYABLE_GPU_STATES as _PREWARM_RETRYABLE_GPU_STATES,
    _STATUS_MAX_INFLIGHT_DEPENDENCIES as _STATUS_MAX_INFLIGHT_DEPENDENCIES,
    __version__ as __version__,
    _new_status_dependency_executor as _new_status_dependency_executor,
    _prewarm_admission_state as _prewarm_admission_state,
    _prewarm_route_is_eligible as _prewarm_route_is_eligible,
    _record_startup_prewarm_failure as _record_startup_prewarm_failure,
    _wait_for_prewarm_backend as _wait_for_prewarm_backend,
    configure_logging as configure_logging,
    ensure_state_version as ensure_state_version,
    load_config as load_config,
    require_canonical_agent_state_database as require_canonical_agent_state_database,
    shutdown_logging as shutdown_logging,
    threading as threading,
    time as time,
)


LocalAIApp = None


class AppRuntimeMixin:
    def __init__(self, config_path: str | None = None):
        self.config = load_config(config_path)
        self.desktop_updates = DesktopUpdates(self.config.get("_config_path"))
        state_dir = Path(self.config["server"]["state_dir"])
        ensure_state_version(state_dir)
        require_canonical_agent_state_database(state_dir)
        saving = self.config.get("token_saving", {})
        self.started_at = time.time()
        self._shutdown = threading.Event()
        self._close_lock = threading.Lock()
        self._closed = False
        self._prewarm_thread: threading.Thread | None = None
        self._watchdog_thread: threading.Thread | None = None
        self._live_status_lock = threading.Lock()
        self._live_status_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._live_status_refresh_locks: dict[str, threading.Lock] = {}
        self._status_full_cache: dict[str, dict[str, Any]] = {}
        self._status_full_cache_lock = threading.Lock()
        self._status_dependency_lock = threading.Lock()
        self._status_dependency_inflight: dict[str, dict[str, Any]] = {}
        self._status_metadata_cache: dict[str, dict[str, Any]] = {}
        self._status_dependency_slots = threading.BoundedSemaphore(_STATUS_MAX_INFLIGHT_DEPENDENCIES)
        self._status_dependency_executor = _new_status_dependency_executor()

        self.logger = configure_logging(state_dir, self.config)
        fast_runtime = OllamaRuntime(self.config)
        self.runtime = TieredOllamaRuntime(self.config, fast_runtime=fast_runtime) if bool(self.config.get("smart_ollama", {}).get("enabled", False)) else fast_runtime
        from .execution_pool import ExecutionPool
        pool_config = self.config.get("worker_pool", {})
        pool_config = pool_config if isinstance(pool_config, dict) else {}
        self.execution_pool = ExecutionPool(
            cpu_workers=int(pool_config.get("cpu_workers", self.config.get("work_orchestrator", {}).get("parallel_deterministic_steps", 2))),
            io_workers=int(pool_config.get("io_workers", self.config.get("async_jobs", {}).get("max_workers", 16))),
            inference_workers=int(pool_config.get("inference_workers", self.config.get("scheduler", {}).get("max_parallel", 1))),
        )
        self.scheduler = AffinityScheduler(self.runtime, self.config, execution_pool=self.execution_pool)
        self.background_gpu = IdleGPUWorker(self.config, self.scheduler)
        self.scheduler.set_foreground_preempt_hook(self.background_gpu.preempt_foreground)
        self.embeddings = EmbeddingModel(self.config)
        training_capture_cfg = self.config.get("training_capture", {})
        training_capture_enabled = bool(training_capture_cfg.get("enabled", False))
        from .laya_training_collector import LayaTrainingCollector
        self.training_collector = LayaTrainingCollector(
            laya_inbox_path=state_dir / "laya_training_inbox.jsonl",
            dpo_inbox_path=state_dir / "dpo_training_inbox.jsonl",
            triplet_inbox_path=state_dir / "retrieval_triplets.jsonl",
            enabled=training_capture_enabled,
        )
        self.reranker = Reranker(self.config, training_collector=self.training_collector)
        bundles = self.config.get("bundles") or {}
        self.artifacts = ArtifactStore(
            state_dir,
            ttl_hours=int(saving.get("artifact_ttl_hours", 72)),
            max_inline_chars=int(saving.get("max_inline_chars", 6000)),
            max_binary_bytes=int(bundles.get("max_bundle_bytes", 4_000_000)),
            max_json_bytes=int(bundles.get("max_json_bytes", 4_000_000)),
        )
        obs = self.config.get("observability", {})
        telemetry_cfg = self.config.get("telemetry", {})
        raw_telemetry_mode = telemetry_cfg.get("mode")
        telemetry_mode = str(raw_telemetry_mode or "").lower()
        if obs.get("enabled") is False:
            telemetry_enabled = False
            endpoint_stats_enabled = False
            telemetry_mode = "off"
        elif obs.get("enabled") is True and raw_telemetry_mode in (None, "off", ""):
            telemetry_enabled = True
            endpoint_stats_enabled = True
            telemetry_mode = "full"
        elif telemetry_mode == "off":
            telemetry_enabled = False
            endpoint_stats_enabled = False
        elif telemetry_mode == "minimal":
            telemetry_enabled = True
            endpoint_stats_enabled = False
        elif telemetry_mode == "full":
            telemetry_enabled = True
            endpoint_stats_enabled = True
        else:
            telemetry_enabled = bool(obs.get("enabled", True))
            endpoint_stats_enabled = bool(obs.get("enabled", True))

        self.telemetry = TelemetryStore(
            state_dir,
            enabled=telemetry_enabled,
            mode=telemetry_mode,
            max_events=int(obs.get("max_events", 100000)),
            retention_days=int(obs.get("raw_retention_days", 30)),
            rollup_retention_days=int(obs.get("rollup_retention_days", 365)),
            cloud_input_token_cost_usd_per_million=saving.get("cloud_input_token_cost_usd_per_million", 3.0),
            cloud_output_token_cost_usd_per_million=saving.get("cloud_output_token_cost_usd_per_million", 3.0),
            pricing_profile=str(saving.get("pricing_profile", "claude-5-sonnet")),
            cloud_cache_read_token_cost_usd_per_million=saving.get("cloud_cache_read_token_cost_usd_per_million", 0.30),
            cloud_cache_write_token_cost_usd_per_million=saving.get("cloud_cache_write_token_cost_usd_per_million", 3.75),
            config=self.config,
            batch_size=int(obs.get("batch_size", 128)),
            flush_interval_seconds=float(obs.get("flush_interval_seconds", 1.0)),
            queue_size=int(obs.get("queue_size", 10000)),
            live_buffer_size=int(self.config.get("monitoring", {}).get("live_event_buffer", 2500)),
        )
        self.endpoint_stats = EndpointStatsStore(state_dir, enabled=endpoint_stats_enabled)
        self.debug_traces = DebugTraceStore(self.config)
        self.debug_traces.recover_incomplete(reason="hub restarted")
        self.repo_tools = RepositoryTools(self.config)
        self.repo_state = RepoStateTracker(self.config)
        self.code_index = CodeIndex(self.config, self.repo_tools)
        self.evidence = EvidenceStore(state_dir, max_entries=int(self.config.get("evidence", {}).get("max_entries", 100000)))
        self.learner = UsageLearner(self.config)
        self.tuner = RuntimeTuner(self.config)
        self.deterministic = DeterministicEngine(self.config, self.repo_tools, self.code_index, self.evidence)
        self.external_tools = ExternalCodeIntelligence(self.config, self.telemetry, code_index=self.code_index)
        self.leases = ScopeLeaseStore(state_dir)
        self.memory = WorkspaceMemoryStore(state_dir)
        agent_state_cfg = self.config.get("agent_state", {})
        self.agent_state = AgentStateStore(
            state_dir / "agent_state.sqlite",
            enabled=bool(agent_state_cfg.get("enabled", False)),
            max_payload_bytes=int(agent_state_cfg.get("max_payload_bytes", 65536)),
        )
        self.agent_tasks = TaskStore(self.agent_state)
        laya_cfg = self.config.get("laya", {})
        reviewer_cfg = laya_cfg.get("reviewers", {}) if isinstance(laya_cfg, dict) else {}
        reviewer_public_keys = reviewer_cfg.get("public_keys", []) if isinstance(reviewer_cfg, dict) else []
        self.laya_candidates = LayaCandidateStore(
            state_dir,
            reviewer_public_keys=reviewer_public_keys,
            local_model_reviewer=self._review_laya_candidate_locally,
        )
        from .laya_unified_coordinator import LayaUnifiedCoordinator
        self.laya_coordinator = LayaUnifiedCoordinator(
            default_budget=int(self.config.get("token_saving", {}).get("max_response_tokens", 8192) or 8192),
            training_collector=self.training_collector,
            model_roles=self.config.get("models"),
            training_capture_enabled=training_capture_enabled,
        )
        runtime_cfg = laya_cfg.get("runtime", {}) if isinstance(laya_cfg, dict) else {}
        self.laya_lifecycle = LayaSessionLifecycle(
            DEFAULT_IDLE_UNLOAD_SECONDS,
            runtime_configuration=runtime_cfg if isinstance(runtime_cfg, dict) else {},
            close_session=self._close_laya_runtime_session,
        )
        self._laya_runtime_adapter_lock = threading.Lock()
        self._laya_runtime_adapter = None
        self.scheduler.add_idle_maintenance_callback(self.laya_lifecycle.poll_idle_unload)
        from .automation_service import create_automation_broker
        self.automation = create_automation_broker(self.config, self.artifacts)
        self.agent_memory = MemoryStore(self.agent_state)
        self.agent_incidents = IncidentStore(self.agent_state)
        self.agent_verification = VerificationStore(
            self.agent_state,
            task_store=self.agent_tasks,
            artifact_store=self.artifacts,
            evidence_store=self.evidence,
        )
        self.agent_policy = PolicyEngine(self.agent_state)
        self.agent_tasks.set_policy_engine(self.agent_policy)
        self.agent_blackboard = BlackboardStore(state_dir / "agent_state.sqlite", state_store=self.agent_state)
        self.agent_context = ContextCompiler(
            self.agent_state,
            task_store=self.agent_tasks,
            verification_store=self.agent_verification,
            memory_store=getattr(self, "agent_memory", None),
            incident_store=self.agent_incidents,
            lease_store=self.leases,
            blackboard=self.agent_blackboard,
        )
        self.agent_task_memory_context = ContextCompiler(
            self.agent_state,
            task_store=self.agent_tasks,
            memory_store=self.agent_memory,
        )
        self.agent_tasks.set_memory_adoption(
            memory_store=self.agent_memory,
            context_compiler=self.agent_task_memory_context,
            incident_store=self.agent_incidents,
        )
        self.agent_routing = RoutingEngine(cfg=self.config, state_store=self.agent_state)
        self.agent_learning = LearningStore(self.agent_state)
        self.services = LocalAIServices(
            self.config, self.runtime, self.scheduler, self.embeddings,
            self.artifacts, self.telemetry, self.repo_tools, self.repo_state,
            code_index=self.code_index, evidence=self.evidence, learner=self.learner, tuner=self.tuner, deterministic=self.deterministic, external_tools=self.external_tools,
        )
        self.services.set_laya_decision_evaluator(self.evaluate_laya_decision)
        self.async_jobs = AsyncJobManager(
            self.config, self.scheduler, self.artifacts, self._execute_async_task,
            debug_traces=self.debug_traces,
            task_store=self.agent_tasks,
            verification_store=self.agent_verification,
            telemetry=self.telemetry,
            execution_pool=self.execution_pool,
        )
        self._bind_service_inference_admission()
        self.speculative_lint = SpeculativeLintQueue(self.async_jobs, self.config)
        self.commands = CommandBroker(self.config, self.artifacts, self.repo_state)
        self.commands.set_incident_store(self.agent_incidents)
        self.commands.set_verification_store(self.agent_verification)
        self.agent_verification.set_command_execution_record_lookup(
            getattr(self.commands, "get_command_execution_record", None)
        )
        self.commands.set_policy_engine(self.agent_policy)
        self.commands.set_task_store(self.agent_tasks)
        self.commands.set_error_distiller(self.services.distill_command_error)
        self.services.set_commands(self.commands)
        self.services.set_task_store(self.agent_tasks)
        self.services.set_verification_store(self.agent_verification)
        self.services.set_incident_store(self.agent_incidents)
        self.services.set_agent_state(self.agent_state)
        self.services.set_blackboard(self.agent_blackboard)
        from .agent_events import SwarmPubSub
        self.agent_semaphores = SemaphoreStore(state_dir / "agent_semaphores.sqlite", pubsub=SwarmPubSub.get_default(state_store=self.agent_state))
        self.services.set_semaphores(self.agent_semaphores)
        self.consistency_guard = AgentConsistencyGuard(
            self.repo_tools,
            task_store=self.agent_tasks,
            memory_store=self.agent_memory,
            verification_store=self.agent_verification,
        )
        self.services.set_consistency_guard(self.consistency_guard)
        self.swarm = SwarmCoordinator(state_dir / "agent_state.sqlite", leases=self.leases, blackboard=self.agent_blackboard, verifications=self.agent_verification)
        self.services.set_swarm(self.swarm)
        self.rag = RAGStore(self.config, self.services, self.reranker)
        self.services.set_rag(self.rag)
        self.preprocessor = ProjectPreprocessor(self.config, self.services, self.rag, self.scheduler, self.runtime, self.repo_tools, self.code_index, self.learner, self.deterministic, telemetry=self.telemetry, background_gpu=self.background_gpu, external_tools=self.external_tools, debug_traces=self.debug_traces)
        self.services.set_preprocessor(self.preprocessor)
        self.code_index.set_reindex_callback(self.preprocessor.notify_path_changed)
        self._recover_pending_bundle_imports()
        self.token_router = LosslessTokenRouter(self.config, self.services)
        self.services.set_token_router(self.token_router)
        self.tool_agent = ToolAwareLocalAgent(self.config, self.services, self.preprocessor, self.rag, self.code_index, self.evidence, self.deterministic, external_tools=self.external_tools)
        self.services.set_tool_agent(self.tool_agent)
        self.pipeline = LocalAgentPipeline(self.config, self.services, self.token_router, self.tool_agent)
        self.services.set_pipeline(self.pipeline)
        self.work_orchestrator = WorkOrchestrator(self.config, state_dir, self.services, self.commands, self.leases, self.artifacts, telemetry=self.telemetry, execution_pool=self.execution_pool)
        self.projector = AgentProjector(self.config)
        self.vram_balancer = VRAMBalancer(self.config)
        self.runtime.vram_balancer = self.vram_balancer
        self.services.set_vram_balancer(self.vram_balancer)
        self.benchmark_runner = HardwareBenchmarkRunner(
            state_dir / "benchmarks.json",
            runtime=self.runtime,
            vram_balancer=self.vram_balancer,
            config=self.config,
            scheduler=self.scheduler,
        )
        self.recovery = RecoveryJournal(state_dir, stale_seconds=int(self.config.get("resilience", {}).get("journal_stale_seconds", 900)))
        self._start_resilience_watchdog()
        prewarm = self.config.get("prewarm", {})
        if bool(prewarm.get("enabled", True)):
            def warm() -> None:
                if self._shutdown.wait(max(0.0, float(prewarm.get("delay_seconds", 1.5)))):
                    return
                model_ref = str(prewarm.get("startup_model", "fast_code"))
                model = self.config.get("models", {}).get(model_ref, model_ref)
                backend_wait = max(0.0, float(prewarm.get("backend_wait_seconds", 30.0)))
                if model and not _wait_for_prewarm_backend(self.runtime, self._shutdown, backend_wait):
                    self.logger.warning("prewarm skipped: local model backend unavailable")
                    self.telemetry.record_system("prewarm_skipped_backend_unavailable", model=str(model))
                    return
                if model and not _prewarm_route_is_eligible(self.runtime, str(model)):
                    self.logger.warning("prewarm skipped: model route unavailable on this host: %s", model)
                    self.telemetry.record_system("prewarm_skipped_route_unavailable", model=str(model))
                    return
                # Prewarm is opportunistic but persistent: if startup is busy, retry
                # during later idle windows instead of silently giving up forever.
                # Cap attempts to avoid indefinite CPU spin when model doesn't exist.
                max_attempts = max(1, int(prewarm.get("max_attempts", 120)))
                attempts = 0
                while model and not self._shutdown.is_set():
                    attempts += 1
                    if attempts > max_attempts:
                        self.logger.warning("prewarm giving up after %d attempts for model %s", attempts - 1, model)
                        self.telemetry.record_system("prewarm_abandoned", model=str(model), attempts=attempts - 1)
                        return
                    try:
                        if self.scheduler.prewarm(str(model)):
                            self.telemetry.record_system("prewarm_ready", model=str(model), attempts=attempts)
                            break
                    except Exception as exc:
                        self.telemetry.record_error("prewarm", "startup_model", exc, recovered=False)
                        _record_startup_prewarm_failure(self.debug_traces, str(model), exc)
                        self.logger.warning("prewarm attempt failed: %s", type(exc).__name__)
                    admission_state = _prewarm_admission_state(self.scheduler)
                    if admission_state not in _PREWARM_RETRYABLE_GPU_STATES:
                        if admission_state == "capacity_sharing":
                            self.logger.info("prewarm skipped: GPU capacity is shared")
                            self.telemetry.record_system(
                                "prewarm_skipped_shared_capacity", model=str(model),
                                gpu_admission_state="available",
                            )
                        else:
                            self.logger.warning(
                                "prewarm stopped: gpu_admission_state=%s", admission_state,
                            )
                            self.telemetry.record_system(
                                "prewarm_stopped_gpu_admission_unavailable",
                                model=str(model), gpu_admission_state=admission_state,
                            )
                        return
                    self._shutdown.wait(min(15.0, 1.5 + attempts * 0.5))
                if bool(prewarm.get("reranker", False)) and not self._shutdown.is_set():
                    try:
                        reranker = getattr(self, "reranker", None)
                        if reranker is not None and reranker.is_enabled():
                            if reranker.prewarm():
                                self.logger.info("reranker prewarm ready: %s on %s", reranker.active_model_name(), reranker.active_device)
                                self.telemetry.record_system("reranker_prewarm_ready", model=reranker.active_model_name())
                    except Exception as exc:
                        self.logger.warning("reranker prewarm failed: %s", type(exc).__name__)
            self._prewarm_thread = threading.Thread(target=warm, name="local-ai-prewarm", daemon=True)
            self._prewarm_thread.start()
        self.async_jobs.recover()
        try:
            from .hardware import detect_hardware
            threading.Thread(target=detect_hardware, name="local-ai-hardware-warmup", daemon=True).start()
            def _status_ticker() -> None:
                # Avoid making periodic refreshes compete with MCP/desktop
                # callers when a status collection runs longer than its cache TTL.
                while not self._shutdown.wait(30.0):
                    try:
                        self.realtime_status(light=True)
                    except Exception:
                        pass
            threading.Thread(target=_status_ticker, name="local-ai-status-ticker", daemon=True).start()
        except Exception:
            pass

    def _reap_expired_task_scopes(self) -> list[str]:
        """Reap bounded authorized repository scopes without a global bypass."""
        from .repository_scope import RepositoryScopeError, authorized_repository_root

        state = getattr(self, "agent_state", None)
        if state is None or not state.enabled or self._shutdown.is_set():
            return []
        now = time.time()
        deadline = time.monotonic() + 2.0
        cursor = getattr(self, "_task_reap_after_root", "")
        roots = state.tasks._expired_repository_roots(now=now, limit=16, after_root=cursor)
        if not roots and cursor:
            self._task_reap_after_root = ""
            roots = state.tasks._expired_repository_roots(now=now, limit=16)
        reaped: list[str] = []
        for root in roots:
            if self._shutdown.is_set() or time.monotonic() >= deadline:
                break
            self._task_reap_after_root = root
            try:
                authorized_root = authorized_repository_root(self.config, root)
            except RepositoryScopeError:
                self.logger.debug("watchdog: task root unavailable or outside allowed scope")
                continue
            try:
                reaped.extend(state.tasks.reap_expired_heartbeats(
                    now=now, repo_root=authorized_root,
                    _deadline_monotonic=deadline, _cancel_event=self._shutdown,
                ))
            except Exception as exc:
                self.logger.debug("watchdog: scoped task reaping failed: %s", type(exc).__name__)
        return reaped

    def _watchdog_loop(self) -> None:
        cfg = self.config.get("resilience", {})
        interval = max(1.0, float(cfg.get("watchdog_interval_seconds", 5.0)))
        snapshot_interval = max(interval, float(self.config.get("observability", {}).get("snapshot_interval_seconds", 60.0)))
        last_snapshot = 0.0
        last_maintenance = 0.0
        maintenance_interval = max(60.0, float(cfg.get("maintenance_interval_seconds", 1800.0)))
        while not self._shutdown.wait(interval):
            try:
                self.recovery.mark_abandoned()
                self.async_jobs.tick()
                self.debug_traces.cleanup()
                self.scheduler.ensure_dispatcher()
                self.preprocessor.ensure_running()
                if getattr(self, "agent_state", None) is not None and getattr(self.agent_state, "enabled", False):
                    try:
                        self._reap_expired_task_scopes()
                    except Exception as exc:
                        self.logger.debug("watchdog: reap_expired_heartbeats failed: %s", type(exc).__name__)
                sched = self.scheduler.status()
                if (sched.get("queued", 0) or sched.get("inflight", 0)) and not self.runtime.is_online():
                    self.runtime.ensure_running()
                now = time.monotonic()
                if now - last_maintenance >= maintenance_interval:
                    if getattr(self, "agent_state", None) is not None and getattr(self.agent_state, "enabled", False):
                        try:
                            from .operational_mode import load_operational_mode
                            mode = load_operational_mode(self.config.get("server", {}).get("state_dir", "state"))
                            if (
                                mode.mode == "active" and not mode.degraded
                                and not int(sched.get("queued", 0) or 0)
                                and not int(sched.get("inflight", 0) or 0)
                            ):
                                self.agent_state.tasks.cleanup_idle_worktrees()
                            self.agent_state.cleanup(retention_days=30)
                            if hasattr(self.agent_state, "memory") and hasattr(self.agent_state.memory, "reap_expired"):
                                self.agent_state.memory.reap_expired()
                        except Exception as exc:
                            self.logger.debug("watchdog: agent_state maintenance failed: %s", type(exc).__name__)
                    try:
                        from .sqlite_support import optimize_db
                        state_dir = Path(self.config["server"]["state_dir"])
                        for db_name in (
                            "agent_state.sqlite",
                            "async_jobs.sqlite3",
                            "code-index.sqlite3",
                            "cache.sqlite",
                            "rag.sqlite3",
                            "preprocess.sqlite3",
                            "artifacts.sqlite3",
                        ):
                            db_file = state_dir / db_name
                            if db_file.exists():
                                res = optimize_db(db_file, wal_checkpoint=True, vacuum=False, quick_check=True, timeout_seconds=2.5)
                                if res.get("quick_check") and res["quick_check"] != "ok":
                                    self.logger.error("watchdog: SQLite database %s reported corruption: %s", db_name, res["quick_check"])
                                    self.telemetry.record_system("sqlite_corruption_detected", database=db_name, error=res["quick_check"])
                    except Exception:
                        pass
                    last_maintenance = now
                if now - last_snapshot >= snapshot_interval:
                    stats = sched.get("stats", {}) if isinstance(sched, dict) else {}
                    prep = self.preprocessor.stats()
                    self.telemetry.record_snapshot("runtime", {
                        "queued": int(sched.get("queued", 0)), "inflight": int(sched.get("inflight", 0)),
                        "background_queued": int(sched.get("background_queued", 0)),
                        "model_switches": int(stats.get("model_switches", 0)), "queue_rejections": int(stats.get("queue_rejections", 0)),
                        "caller_timeouts": int(stats.get("caller_timeouts", 0)), "background_yields": int(stats.get("background_yields", 0)),
                        "preprocess_steps": int(prep.get("steps", 0)), "preprocess_errors": int(prep.get("errors", 0)),
                        "preprocess_yields": int(prep.get("yields", 0)), "active_model": str(sched.get("active_model") or ""),
                        "fallback_count": int(self.services.fallback_count),
                    })
                    last_snapshot = now
            except Exception as exc:
                self.telemetry.record_error("watchdog", "health_loop", exc, retryable=True, recovered=True)
                self.logger.warning("watchdog iteration failed: %s", type(exc).__name__)

    def _bind_service_inference_admission(self) -> None:
        if hasattr(self, "services") and hasattr(self, "async_jobs"):
            self.services.inference_admission = self.async_jobs.inference_admission

    def _start_resilience_watchdog(self) -> None:
        cfg = self.config.get("resilience", {})
        if not bool(cfg.get("watchdog_enabled", True)):
            return
        self._watchdog_thread = threading.Thread(target=self._watchdog_loop, name="local-ai-watchdog", daemon=True)
        self._watchdog_thread.start()

    def close(self, timeout: float = 5.0) -> bool:
        """Run each shutdown phase once, report failures, and retry only failures."""
        close_lock = getattr(self, "_close_lock", None)
        shutdown = getattr(self, "_shutdown", None)
        if close_lock is None or shutdown is None:
            return False

        phases = (
            "lint_daemons", "context_warmup", "status_dependencies", "helper_threads",
            "recovery", "preprocessor", "external_tools", "work_orchestrator",
            "async_jobs", "execution_pool", "background_gpu", "scheduler", "telemetry",
            "deterministic", "code_index", "logging",
        )

        def snapshot(coordinator: dict[str, Any]) -> dict[str, Any]:
            components = {
                name: dict(detail)
                for name, detail in coordinator["components"].items()
            }
            failed = [name for name in phases if components[name]["state"] == "failed"]
            pending = [name for name in phases if components[name]["state"] in {"pending", "running"}]
            return {
                "success": not failed and not pending,
                "failed": failed,
                "pending": pending,
                "components": components,
            }

        def run_phase(name: str, deadline: float) -> None:
            remaining = max(0.0, deadline - time.monotonic())
            if name == "lint_daemons":
                callback = getattr(getattr(self, "services", None), "close_lint_daemons", None)
                result = callback() if callable(callback) else None
            elif name == "context_warmup":
                callback = getattr(getattr(self, "services", None), "close_context_warmup", None)
                result = callback() if callable(callback) else None
            elif name == "status_dependencies":
                executor = getattr(self, "_status_dependency_executor", None)
                result = executor.shutdown(wait=True, cancel_futures=True) if executor is not None else None
            elif name == "helper_threads":
                for worker_name in ("_prewarm_thread", "_watchdog_thread"):
                    worker = getattr(self, worker_name, None)
                    if worker is None or worker is threading.current_thread():
                        continue
                    is_alive = getattr(worker, "is_alive", None)
                    join = getattr(worker, "join", None)
                    if callable(is_alive) and is_alive() and callable(join):
                        join(timeout=max(0.0, min(1.0, remaining)))
                        if is_alive():
                            raise TimeoutError(f"{worker_name} is still running")
                result = None
            elif name == "background_gpu":
                # Release Laya's model lease before stopping GPU admission.
                laya = getattr(self, "laya_lifecycle", None)
                close_laya = getattr(laya, "close", None)
                if callable(close_laya):
                    laya_result = close_laya(timeout=remaining)
                    if laya_result is False:
                        raise RuntimeError("Laya shutdown remains unconfirmed")
                component = getattr(self, name, None)
                callback = getattr(component, "close", None)
                result = callback() if callable(callback) else None
            elif name == "telemetry":
                result = None
                for component_name in ("endpoint_stats", "agent_incidents", "telemetry"):
                    component = getattr(self, component_name, None)
                    callback = getattr(component, "close", None)
                    if not callable(callback):
                        continue
                    value = callback(timeout=remaining) if component_name == "agent_incidents" else callback()
                    if value is False or (
                        isinstance(value, Mapping)
                        and (value.get("cleanup_unconfirmed") is True or value.get("success") is False)
                    ):
                        raise RuntimeError(f"{component_name} cleanup was not confirmed")
            elif name == "logging":
                result = shutdown_logging()
            else:
                component = getattr(self, name, None)
                callback = getattr(component, "close", None)
                result = callback() if callable(callback) else None

            if result is False or (
                isinstance(result, Mapping)
                and (result.get("cleanup_unconfirmed") is True or result.get("success") is False)
            ):
                raise RuntimeError(f"{name} cleanup was not confirmed")

        with close_lock:
            shutdown.set()
            coordinator = getattr(self, "_close_coordinator", None)
            if not isinstance(coordinator, dict):
                coordinator = {
                    "components": {
                        name: {"state": "pending", "attempts": 0, "error_type": ""}
                        for name in phases
                    },
                    "thread": None,
                }
                self._close_coordinator = coordinator
            worker = coordinator.get("thread")
            if not getattr(self, "_closed", False) and not (
                isinstance(worker, threading.Thread) and worker.is_alive()
            ):
                incomplete = any(
                    detail["state"] != "completed"
                    for detail in coordinator["components"].values()
                )
                if incomplete:
                    phase_timeout = max(0.0, float(timeout))

                    def coordinate_shutdown() -> None:
                        for phase_name in phases:
                            with close_lock:
                                detail = coordinator["components"][phase_name]
                                if detail["state"] == "completed":
                                    continue
                                detail["state"] = "running"
                                detail["attempts"] += 1
                                self.close_report = snapshot(coordinator)
                            try:
                                run_phase(phase_name, time.monotonic() + phase_timeout)
                            except Exception as exc:
                                with close_lock:
                                    detail["state"] = "failed"
                                    detail["error_type"] = type(exc).__name__
                                    self.close_report = snapshot(coordinator)
                                logger = getattr(self, "logger", None)
                                log_error = getattr(logger, "error", None)
                                if callable(log_error):
                                    try:
                                        log_error("Hub shutdown phase %s failed: %s", phase_name, type(exc).__name__)
                                    except Exception:
                                        pass
                            else:
                                with close_lock:
                                    detail["state"] = "completed"
                                    detail["error_type"] = ""
                                    self.close_report = snapshot(coordinator)
                        with close_lock:
                            self._closed = bool(self.close_report.get("success"))
                            self.close_report = snapshot(coordinator)

                    worker = threading.Thread(
                        target=coordinate_shutdown,
                        name="local-ai-close-coordinator",
                        daemon=True,
                    )
                    coordinator["thread"] = worker
                    self.close_report = snapshot(coordinator)
                    worker.start()
            self.close_report = snapshot(coordinator)

        if isinstance(worker, threading.Thread) and worker is not threading.current_thread():
            worker.join(timeout=max(0.0, float(timeout)))
        with close_lock:
            self.close_report = snapshot(coordinator)
            return self.close_report["success"] is True

    def _execute_async_task(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self.async_jobs.inference_admission(action) as rejection:
            if rejection is not None:
                return rejection
            runner = getattr(self, "_execute_async_task_admitted", None)
            if callable(runner):
                return runner(action, payload)
            return self._execute_async_task_admitted(self, action, payload)

    def _execute_async_task_admitted(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        from .async_jobs import report_job_progress
        report_job_progress(0.0, f"executing:{action}")
        async_payload = dict(payload)
        async_payload["priority"] = 1
        for untrusted_context in ("project_context", "project_model_profile", "system_prefix"):
            async_payload.pop(untrusted_context, None)
        if action == "rag_index":
            from .repository_scope import RepositoryScopeError, authorized_repository_root
            raw_root = payload.get("root")
            workspace = payload.get("workspace")
            try:
                root = authorized_repository_root(self.config, raw_root)
            except RepositoryScopeError as exc:
                return {
                    "success": False,
                    "error": str(exc),
                    "error_code": exc.code,
                    "terminal": True,
                    "retryable": False,
                    "operation_not_started": True,
                }
            if not isinstance(workspace, str) or not workspace.strip():
                return {
                    "success": False,
                    "error": "workspace is required for asynchronous RAG indexing",
                    "terminal": True,
                    "retryable": False,
                    "operation_not_started": True,
                }
            try:
                self.rag.require_workspace_root(workspace=workspace, root=str(root))
            except (TypeError, ValueError) as exc:
                return {
                    "success": False,
                    "error": str(exc),
                    "terminal": True,
                    "retryable": False,
                    "operation_not_started": True,
                }
            return self.rag.index(str(root), workspace=workspace)
        if action == "delegate":
            return self.services.delegate(async_payload)
        if action == "reason":
            reason_payload = {key: value for key, value in async_payload.items() if key != "task"}
            reason_payload.update({"problem": async_payload.get("task", ""), "context": async_payload.get("context", ""), "max_tokens": async_payload.get("max_tokens", 1200), "priority": 1})
            return self.services.reason(reason_payload)
        if action == "review":
            review_payload = {key: value for key, value in async_payload.items() if key not in {"task", "context"}}
            review_payload.update({"code": async_payload.get("context", ""), "instructions": async_payload.get("task", "Report actionable defects only."), "complexity": async_payload.get("complexity", "auto"), "max_tokens": async_payload.get("max_tokens", 1300), "priority": 1})
            return self.services.review(review_payload)
        if action == "review_diff":
            review_payload = dict(async_payload)
            review_payload["_async_job"] = True
            return self.services.review_diff(review_payload)
        if action == "second_opinion":
            opinion_payload = dict(async_payload)
            opinion_payload.update({"question": async_payload.get("task", ""), "candidate": async_payload.get("candidate", ""), "context": async_payload.get("context", ""), "max_tokens": async_payload.get("max_tokens", 1100), "priority": 1})
            return self.services.second_opinion(opinion_payload)
        if action == "compress":
            compress_payload = dict(async_payload)
            compress_payload.update({"text": async_payload.get("context", ""), "instruction": async_payload.get("task", "Compress while preserving facts."), "target_tokens": async_payload.get("max_tokens", 650), "priority": 1})
            return self.services.compress(compress_payload)
        if action == "route":
            route_payload = dict(async_payload)
            route_payload.pop("task", None)
            route_payload.pop("context", None)
            route_payload.update({"text": async_payload.get("context", ""), "query": async_payload.get("task", "")})
            return self.services.route_context(route_payload)
        if action == "batch":
            raw_tasks = async_payload.get("tasks")
            if not isinstance(raw_tasks, list) or not raw_tasks:
                return {"success": False, "error": "tasks must be a non-empty array", "terminal": True, "retryable": False}
            inherited_context = {key: async_payload[key] for key in ("root", "cwd") if key in async_payload}
            tasks = []
            for raw_task in raw_tasks:
                task_payload = dict(raw_task) if isinstance(raw_task, dict) else {"task": str(raw_task)}
                for untrusted_context in ("project_context", "project_model_profile", "system_prefix"):
                    task_payload.pop(untrusted_context, None)
                child_has_workspace = any(
                    str(task_payload.get(key) or "").strip()
                    for key in ("root", "cwd")
                )
                if not child_has_workspace:
                    for key, value in inherited_context.items():
                        if str(value or "").strip():
                            task_payload[key] = value
                tasks.append(task_payload)
            return self.services.batch_delegate({"tasks": tasks, "priority": 1})
        if action == "speculative_lint":
            return self.services.speculative_lint(async_payload)
        return {"success": False, "error": f"unsupported async task action: {action}", "terminal": True, "retryable": False}

    def capabilities(self) -> dict[str, Any]:
        from .features import FeatureSet
        fs = FeatureSet.from_config(self.config)
        return {
            "success": True,
            "version": __version__,
            "mcp_surface": "compact",
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
                "work_orchestrator": fs.work_orchestrator,
                "vision": fs.vision,
            },
            "models": {
                "vision": fs.vision_model or (
                    str(self.config.get("models", {}).get("vision", ""))
                    if bool(self.config.get("features", {}).get("vision", True))
                    and isinstance(self.config.get("models", {}).get("vision"), str)
                    and self.config.get("models", {}).get("vision", "").strip() == self.config.get("models", {}).get("vision")
                    and "\x00" not in self.config.get("models", {}).get("vision")
                    else ""
                ),
            },
            "token_saving": [
                "compact MCP surface with agent-specific final projection and field-selectable work handoffs",
                "durable whole-task work orders with DAG planning, transactional edits, validation and final handoff",
                "deterministic-first execution DAG that resolves common repo questions without Ollama",
                "content-addressed manifest/config/route/test/dependency fact engine before semantic retrieval",
                "deterministic symbol/reference/call/import index before semantic retrieval",
                "content-addressed exact evidence IDs with lazy source disclosure",
                "idle-only durable preprocessing: snapshots, RAG, FTS, code index, semantic cards and learned task capsules",
                "read-only tool-aware Ollama explorer/worker/critic loops using the same shared caches",
                "Local AI deterministic tool bootstrap before local-model reasoning, with explicit project registration",
                "CPU-only code embeddings/reranking run outside the GPU queue and stay usable during foreground inference",
                "hardware-aware model concurrency/context defaults with explicit user overrides",
                "preemptive background-runtime leasing: foreground requests synchronously evict disposable background runners",
                "managed Serena symbol intelligence behind the compact hub surface",
                "evidence-driven fast-tier completion gate and direct smart-tier path when a scout would be redundant",
                "lossless exact-line token routing for oversized source/log/reference context",
                "canonical local stage cache shared across Codex/Claude/Gemini before projection",
                "L1 RAM plus self-healing persistent SQLite caches",
                "conservative semantic generation reuse and concurrent semantic-scope coalescing",
                "repo-state cached search/profile/map/context/diff/impact/RAG results",
                "repo-state-aware CLI command cache, negative cache and single-flight",
                "content snapshot reuse across different repository queries",
                "model-affinity scheduling, explicit residency/preload and runtime latency self-tuning",
                "bounded map-reduce compression and artifact-backed verbose output",
                "workspace memos, evidence freshness and advisory write-scope leases",
                "asynchronous metadata-only observability with long-term rollups and diagnostic export",
            ],
            "genericized_features": [
                "bounded context envelopes", "adaptive capability routing", "hierarchical retrieval",
                "metadata-only audit/usage learning", "bounded runtime recovery",
                "stale-context fingerprints", "advisory write-scope leases",
                "deterministic code intelligence", "deterministic manifest/route/config/test fact engine", "content-addressed evidence store",
                "project profiling", "impact analysis", "test targeting", "cross-agent handoff memos",
                "learned idle task capsules", "self-healing derived state", "runtime self-tuning",
            ],
            "compact_tools": [
                "local_ai_status", "local_ai_task", "local_ai_repo",
                "local_ai_rag", "local_ai_coord", "local_ai_artifact",
            ],
            "code_intelligence": self.external_tools.status(),
            "hardware": dict(self.config.get("_hardware", {})),
        }

