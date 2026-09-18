from __future__ import annotations

from .json_utils import dumps as json_dumps

import io
import json
import sqlite3
import threading
import time
import zipfile
from pathlib import Path
from typing import Any

from . import __version__
from .artifacts import ArtifactStore
from .config import load_config
from .embeddings import EmbeddingModel
from .ollama import OllamaRuntime
from .tiered_ollama import TieredOllamaRuntime
from .leases import ScopeLeaseStore
from .repo_state import RepoStateTracker
from .commands import CommandBroker
from .memory import WorkspaceMemoryStore
from .rag import RAGStore
from .repo_tools import RepositoryTools
from .reranker import Reranker
from .scheduler import AffinityScheduler
from .background_gpu import IdleGPUWorker
from .accelerators import accelerator_status
from .services import LocalAIServices
from .telemetry import TelemetryStore
from .token_router import LosslessTokenRouter
from .pipeline import LocalAgentPipeline
from .projection import AgentProjector
from .resilience import RecoveryJournal
from .preprocess import ProjectPreprocessor
from .tool_agent import ToolAwareLocalAgent
from .code_index import CodeIndex
from .evidence import EvidenceStore
from .learning import UsageLearner
from .autotune import RuntimeTuner
from .deterministic import DeterministicEngine
from .logging_setup import configure_logging, shutdown_logging
from .external_tools import ExternalCodeIntelligence
from .async_jobs import AsyncJobManager
from .speculative_lint import SpeculativeLintQueue
from .debug_traces import DebugTraceStore
from .agent_events import AgentStateStore
from .agent_tasks import TaskStore, TaskStatus
from .agent_identity import AgentScope
from .agent_memory import MemoryStore, MemoryKind, MemoryRecord, MemoryStatus, _normalise_scope_root
from .agent_incidents import IncidentStore
from .agent_verification import VerificationStore
from .agent_policy import PolicyEngine
from .agent_context import ContextCompiler
from .agent_consistency import AgentConsistencyGuard
from .agent_routing import RoutingEngine
from .agent_learning import LearningStore
from .agent_blackboard import BlackboardStore
from .vram_balancer import VRAMBalancer
from .swarm import SwarmCoordinator
from .benchmark import HardwareBenchmarkRunner
from .work_orchestrator import WorkOrchestrator


# Table whitelists for bundle import/restore — created once at module level.
_PREPROCESS_TABLES = frozenset({"file_refs", "module_cards", "project_cards", "external_index_state"})
_DET_TABLES = frozenset({"files", "facts", "dependencies", "scripts", "project_state", "query_cache"})


class BundleValidationError(ValueError):
    """Raised when bundle validation or scope verification fails."""


class LocalAIApp:
    vram_balancer: Any = None
    swarm: Any = None
    benchmark_runner: Any = None

    def __init__(self, config_path: str | None = None):
        self.config = load_config(config_path)
        state_dir = Path(self.config["server"]["state_dir"])
        saving = self.config.get("token_saving", {})
        self.started_at = time.time()
        self._shutdown = threading.Event()
        self._close_lock = threading.Lock()
        self._closed = False
        self._prewarm_thread: threading.Thread | None = None
        self._watchdog_thread: threading.Thread | None = None
        self._live_status_lock = threading.Lock()
        self._live_status_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._status_full_cache: dict[str, dict[str, Any]] = {}
        self._status_full_cache_lock = threading.Lock()

        self.logger = configure_logging(state_dir, self.config)
        fast_runtime = OllamaRuntime(self.config)
        self.runtime = TieredOllamaRuntime(self.config, fast_runtime=fast_runtime) if bool(self.config.get("smart_ollama", {}).get("enabled", False)) else fast_runtime
        self.scheduler = AffinityScheduler(self.runtime, self.config)
        self.background_gpu = IdleGPUWorker(self.config, self.scheduler)
        self.scheduler.set_foreground_preempt_hook(self.background_gpu.preempt_foreground)
        self.embeddings = EmbeddingModel(self.config)
        self.reranker = Reranker(self.config)
        bundles = self.config.get("bundles") or {}
        self.artifacts = ArtifactStore(
            state_dir,
            ttl_hours=int(saving.get("artifact_ttl_hours", 72)),
            max_inline_chars=int(saving.get("max_inline_chars", 6000)),
            max_binary_bytes=int(bundles.get("max_bundle_bytes", 4_000_000)),
            max_json_bytes=int(bundles.get("max_json_bytes", 4_000_000)),
        )
        obs = self.config.get("observability", {})
        self.telemetry = TelemetryStore(
            state_dir,
            enabled=bool(obs.get("enabled", True)),
            max_events=int(obs.get("max_events", 100000)),
            retention_days=int(obs.get("raw_retention_days", 30)),
            rollup_retention_days=int(obs.get("rollup_retention_days", 365)),
            cloud_token_cost_usd_per_million=float(saving.get("cloud_token_cost_usd_per_million", 3.0)),
            cloud_input_token_cost_usd_per_million=float(saving.get("cloud_input_token_cost_usd_per_million", saving.get("cloud_token_cost_usd_per_million", 3.0))),
            cloud_output_token_cost_usd_per_million=float(saving.get("cloud_output_token_cost_usd_per_million", saving.get("cloud_token_cost_usd_per_million", 3.0))),
            batch_size=int(obs.get("batch_size", 64)),
            flush_interval_seconds=float(obs.get("flush_interval_seconds", 0.5)),
            queue_size=int(obs.get("queue_size", 10000)),
            live_buffer_size=int(self.config.get("monitoring", {}).get("live_event_buffer", 2500)),
        )
        self.debug_traces = DebugTraceStore(self.config)
        self.debug_traces.recover_incomplete(reason="hub restarted")
        self.repo_tools = RepositoryTools(self.config)
        self.repo_state = RepoStateTracker(self.config)
        self.code_index = CodeIndex(self.config, self.repo_tools)
        self.evidence = EvidenceStore(state_dir, max_entries=int(self.config.get("evidence", {}).get("max_entries", 100000)))
        self.learner = UsageLearner(self.config)
        self.tuner = RuntimeTuner(self.config)
        self.deterministic = DeterministicEngine(self.config, self.repo_tools, self.code_index, self.evidence)
        self.external_tools = ExternalCodeIntelligence(self.config, self.telemetry)
        self.leases = ScopeLeaseStore(state_dir)
        self.memory = WorkspaceMemoryStore(state_dir)
        agent_state_cfg = self.config.get("agent_state", {})
        self.agent_state = AgentStateStore(
            state_dir / "agent_state.sqlite3",
            enabled=bool(agent_state_cfg.get("enabled", False)),
            max_payload_bytes=int(agent_state_cfg.get("max_payload_bytes", 65536)),
        )
        self.agent_tasks = TaskStore(self.agent_state)
        self.agent_memory = MemoryStore(self.agent_state)
        self.agent_incidents = IncidentStore(self.agent_state)
        self.agent_verification = VerificationStore(self.agent_state, task_store=self.agent_tasks)
        self.agent_policy = PolicyEngine(self.agent_state)
        self.agent_tasks.set_policy_engine(self.agent_policy)
        self.agent_blackboard = BlackboardStore(state_dir / "agent_state.sqlite3")
        self.agent_context = ContextCompiler(
            self.agent_state,
            task_store=self.agent_tasks,
            verification_store=self.agent_verification,
            memory_store=self.agent_memory,
            incident_store=self.agent_incidents,
            lease_store=self.leases,
            blackboard=self.agent_blackboard,
        )
        self.agent_routing = RoutingEngine(cfg=self.config, state_store=self.agent_state)
        self.agent_learning = LearningStore(self.agent_state)
        self.services = LocalAIServices(
            self.config, self.runtime, self.scheduler, self.embeddings,
            self.artifacts, self.telemetry, self.repo_tools, self.repo_state,
            code_index=self.code_index, evidence=self.evidence, learner=self.learner, tuner=self.tuner, deterministic=self.deterministic, external_tools=self.external_tools,
        )
        self.async_jobs = AsyncJobManager(
            self.config, self.scheduler, self.artifacts, self._execute_async_task,
            debug_traces=self.debug_traces,
            task_store=self.agent_tasks,
            verification_store=self.agent_verification,
            telemetry=self.telemetry,
        )
        self.speculative_lint = SpeculativeLintQueue(self.async_jobs, self.config)
        self.async_jobs.recover()
        self.commands = CommandBroker(self.config, self.artifacts, self.repo_state)
        self.commands.set_incident_store(self.agent_incidents)
        self.commands.set_verification_store(self.agent_verification)
        self.commands.set_policy_engine(self.agent_policy)
        self.commands.set_error_distiller(self.services.distill_command_error)
        self.services.set_commands(self.commands)
        self.services.set_task_store(self.agent_tasks)
        self.services.set_verification_store(self.agent_verification)
        self.services.set_incident_store(self.agent_incidents)
        self.services.set_agent_state(self.agent_state)
        self.services.set_blackboard(self.agent_blackboard)
        self.consistency_guard = AgentConsistencyGuard(
            self.repo_tools,
            task_store=self.agent_tasks,
            memory_store=self.agent_memory,
            verification_store=self.agent_verification,
        )
        self.services.set_consistency_guard(self.consistency_guard)
        self.swarm = SwarmCoordinator(state_dir / "agent_state.sqlite3", leases=self.leases, blackboard=self.agent_blackboard, verifications=self.agent_verification)
        self.services.set_swarm(self.swarm)
        self.rag = RAGStore(self.config, self.services, self.reranker)
        self.services.set_rag(self.rag)
        self.preprocessor = ProjectPreprocessor(self.config, self.services, self.rag, self.scheduler, self.runtime, self.repo_tools, self.code_index, self.learner, self.deterministic, telemetry=self.telemetry, background_gpu=self.background_gpu, external_tools=self.external_tools)
        self.services.set_preprocessor(self.preprocessor)
        self.token_router = LosslessTokenRouter(self.config, self.services)
        self.services.set_token_router(self.token_router)
        self.tool_agent = ToolAwareLocalAgent(self.config, self.services, self.preprocessor, self.rag, self.code_index, self.evidence, self.deterministic, external_tools=self.external_tools)
        self.services.set_tool_agent(self.tool_agent)
        self.pipeline = LocalAgentPipeline(self.config, self.services, self.token_router, self.tool_agent)
        self.services.set_pipeline(self.pipeline)
        self.work_orchestrator = WorkOrchestrator(self.config, state_dir, self.services, self.commands, self.leases, self.artifacts, telemetry=self.telemetry)
        self.projector = AgentProjector(self.config)
        self.vram_balancer = VRAMBalancer(self.config)
        self.services.set_vram_balancer(self.vram_balancer)
        self.benchmark_runner = HardwareBenchmarkRunner(
            state_dir / "benchmarks.json",
            runtime=self.runtime,
            vram_balancer=self.vram_balancer,
            config=self.config,
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
                            return
                    except Exception as exc:
                        self.telemetry.record_error("prewarm", "startup_model", exc, recovered=True)
                        self.logger.warning("prewarm attempt failed: %s", type(exc).__name__)
                    self._shutdown.wait(min(15.0, 1.5 + attempts * 0.5))
            self._prewarm_thread = threading.Thread(target=warm, name="local-ai-prewarm", daemon=True)
            self._prewarm_thread.start()

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
                        self.agent_state.tasks.reap_expired_heartbeats()
                    except Exception as exc:
                        self.logger.debug("watchdog: reap_expired_heartbeats failed: %s", type(exc).__name__)
                sched = self.scheduler.status()
                if (sched.get("queued", 0) or sched.get("inflight", 0)) and not self.runtime.is_online():
                    self.runtime.ensure_running()
                now = time.monotonic()
                if now - last_maintenance >= maintenance_interval:
                    if getattr(self, "agent_state", None) is not None and getattr(self.agent_state, "enabled", False):
                        try:
                            self.agent_state.cleanup(retention_days=30)
                            if hasattr(self.agent_state, "memory") and hasattr(self.agent_state.memory, "reap_expired"):
                                self.agent_state.memory.reap_expired()
                        except Exception as exc:
                            self.logger.debug("watchdog: agent_state maintenance failed: %s", type(exc).__name__)
                    try:
                        from .sqlite_support import optimize_db
                        state_dir = Path(self.config["server"]["state_dir"])
                        for db_name in (
                            "agent_state.sqlite3",
                            "async_jobs.sqlite3",
                            "code-index.sqlite3",
                            "cache.sqlite3",
                            "rag.sqlite3",
                            "preprocess.sqlite3",
                            "agent_blackboard.sqlite3",
                            "leases.sqlite3",
                            "artifacts.sqlite3",
                        ):
                            db_file = state_dir / db_name
                            if db_file.exists():
                                optimize_db(db_file, wal_checkpoint=True, vacuum=False, timeout_seconds=1.5)
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

    def _start_resilience_watchdog(self) -> None:
        cfg = self.config.get("resilience", {})
        if not bool(cfg.get("watchdog_enabled", True)):
            return
        self._watchdog_thread = threading.Thread(target=self._watchdog_loop, name="local-ai-watchdog", daemon=True)
        self._watchdog_thread.start()

    def _execute_async_task(self, action: str, payload: dict[str, Any], tenant: str) -> dict[str, Any]:
        if action == "delegate":
            return self.services.delegate(payload, tenant)
        if action == "reason":
            return self.services.reason({"problem": payload.get("task", ""), "context": payload.get("context", ""), "max_tokens": payload.get("max_tokens", 1200)}, tenant)
        if action == "review":
            return self.services.review({"code": payload.get("context", ""), "instructions": payload.get("task", "Report actionable defects only."), "complexity": payload.get("complexity", "auto"), "max_tokens": payload.get("max_tokens", 1300)}, tenant)
        if action == "second_opinion":
            return self.services.second_opinion({"question": payload.get("task", ""), "candidate": payload.get("candidate", ""), "context": payload.get("context", ""), "max_tokens": payload.get("max_tokens", 1100)}, tenant)
        if action == "compress":
            return self.services.compress({"text": payload.get("context", ""), "instruction": payload.get("task", "Compress while preserving facts."), "target_tokens": payload.get("max_tokens", 650)}, tenant)
        if action == "route":
            return self.services.route_context({"text": payload.get("context", ""), "query": payload.get("task", "")}, tenant)
        if action == "batch":
            return self.services.batch_delegate({"tasks": payload.get("tasks", [])}, tenant)
        if action == "speculative_lint":
            return self.services.speculative_lint(payload, tenant)
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
                "dashboard": fs.dashboard,
                "work_orchestrator": fs.work_orchestrator,
                "vision": fs.vision,
            },
            "models": {
                "vision": fs.vision_model,
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
                "managed Serena symbol intelligence and CodeGraph relationship analysis behind the compact hub surface",
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
                "local_ai_rag", "local_ai_command", "local_ai_coord", "local_ai_artifact",
            ],
            "code_intelligence": self.external_tools.status(),
            "hardware": dict(self.config.get("_hardware", {})),
        }

    def _agent_state_summary(self) -> dict[str, Any]:
        if not getattr(self, "agent_state", None) or not self.agent_state.enabled:
            return {"enabled": False}
        tasks = self.agent_tasks.list_tasks() if getattr(self, "agent_tasks", None) else []
        incidents = self.agent_incidents.list_incidents() if getattr(self, "agent_incidents", None) else []
        candidates = self.agent_learning.list_candidates() if getattr(self, "agent_learning", None) else []
        mem_count = self.agent_memory.count() if getattr(self, "agent_memory", None) else 0
        return {
            "enabled": True,
            "status": "healthy",
            "active_tasks_count": len([task for task in tasks if task.status == TaskStatus.ACTIVE]),
            "tasks_count": len(tasks),
            "incidents_count": len(incidents),
            "candidates_count": len(candidates),
            "memory_records_count": mem_count,
            "retention_days": int(self.config.get("agent_state", {}).get("retention_days", 30)),
        }

    def realtime_status(self, *, light: bool = False, scope: str = "process") -> dict[str, Any]:
        scope = str(scope).strip().lower()
        if scope not in {"process", "window"}:
            scope = "process"
        now = time.monotonic()
        cache_key = f"{'light' if light else 'full'}:{scope}"
        cache_ttl = 0.5 if light else 1.5
        with self._live_status_lock:
            cached = self._live_status_cache.get(cache_key)
            if cached and now - cached[0] < cache_ttl:
                result = dict(cached[1])
                result["agent_state"] = self._agent_state_summary()
                return result
            headless = self._headless_status()
            ollama = headless.get("ollama_online") if headless.get("supervisor") else None
            scheduler = self.scheduler.status()
            prep_stats = self.preprocessor.stats()
            try:
                prep_status = self.preprocessor.status()
            except Exception:
                prep_status = {"success": False, "projects": []}
            projects = []
            for item in prep_status.get("projects", []) if isinstance(prep_status, dict) else []:
                row = dict(item)
                root = str(row.get("root", ""))
                row["project"] = Path(root).name or root
                projects.append(row)
            from .features import FeatureSet
            fs = FeatureSet.from_config(self.config)
            observability = self.telemetry.realtime_summary(scope=scope)
            result = {
                "success": True, "hub_online": True, "version": __version__,
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
                },
                "models": dict(self.config.get("models", {})),
                "hardware": dict(self.config.get("_hardware", {})),
                "accelerators": accelerator_status(self.config),
                "code_intelligence": self.external_tools.status(),
                "runtime_profile": {
                    "tiered_models": self.config.get("models", {}).get("heavy_code") != self.config.get("models", {}).get("fast_code"),
                    "max_loaded_models": int(self.config.get("scheduler", {}).get("max_loaded_models", 1)),
                    "max_parallel": int(self.config.get("scheduler", {}).get("max_parallel", 1)),
                    "execution": self.services.model_policy.summary(),
                    "flash_attention": bool(self.config.get("ollama", {}).get("flash_attention", True)),
                    "kv_cache_type": str(self.config.get("ollama", {}).get("kv_cache_type", "q8_0")),
                },
                "ollama_online": ollama, "scheduler": scheduler,
                "headless": headless,
                "background_gpu": self.background_gpu.status(),
                "ollama_profile": self.runtime.managed_profile_status() if getattr(self, "runtime", None) else {},
                "model_execution": self.services.model_policy.summary() if getattr(self, "services", None) and getattr(self.services, "model_policy", None) else {},
                "vram_balancer": self.vram_balancer.status() if getattr(self, "vram_balancer", None) else {},
                "benchmark": self.benchmark_runner.get_latest_summary() if getattr(self, "benchmark_runner", None) else {"available": False},
                "debug_traces": self.debug_traces.stats(),
                "observability": observability,
                "preprocessing": {
                    **(prep_status if isinstance(prep_status, dict) else {}),
                    **prep_stats,
                    "projects": projects,
                    "paused": bool(prep_status.get("paused", False)) if isinstance(prep_status, dict) else False,
                    "global_diagnostic": str(prep_status.get("global_diagnostic", "")) if isinstance(prep_status, dict) else "",
                    "scheduler_background_allowed": prep_status.get("scheduler_background_allowed", True) if isinstance(prep_status, dict) else True,
                    "query_hit_rate": observability.get("preprocessed_query_hit_rate", 0.0),
                },
                "runtime_stats": {
                    "generation_cache": self.services.generation_cache.stats(),
                    "semantic_cache": self.services.semantic_cache.stats(),
                    "repo_cache": self.services.repo_cache.stats(),
                    "repo_state": self.repo_state.stats(),
                    "repo_snapshots": self.repo_tools.snapshot_stats(),
                    "commands": self.commands.stats(),
                    "pipeline": self.pipeline.stats(),
                    "tool_agent": self.tool_agent.stats(),
                    "deterministic": self.deterministic.status() if not light and self.deterministic is not None else {},
                    "code_index": self.code_index.status() if not light and self.code_index is not None else {},
                },
            }
            result["agent_state"] = self._agent_state_summary()
            self._live_status_cache[cache_key] = (now, result)
            return dict(result)

    def status(self, *, scope: str = "process") -> dict[str, Any]:
        scope = str(scope).strip().lower()
        if scope not in {"process", "window"}:
            scope = "process"
        import os
        now = time.monotonic()
        with self._status_full_cache_lock:
            cached = self._status_full_cache.get(scope)
            if cached and now - cached["time"] < 2.0:
                result = dict(cached["data"])
                result["agent_state"] = self._agent_state_summary()
                return result
        online = self.runtime.is_online()
        version = None
        installed: list[str] = []
        loaded: list[str] = []
        loaded_details: list[dict[str, Any]] = []
        if online:
            try:
                version = self.runtime.version()
                installed = self.runtime.installed_models()
                loaded_details = self.runtime.loaded_model_details()
                loaded = [str(row.get("name", "")) for row in loaded_details if row.get("name")]
            except Exception:
                pass
        telemetry_summary = self.telemetry.summary(scope=scope, _flush=False)
        res = {
            "success": True, "hub_pid": os.getpid(), "hub_online": True, "version": __version__,
            "ollama_online": online, "online": online, "ollama_version": version,
            "installed_models": installed, "loaded_models": loaded, "loaded_model_details": loaded_details, "models": dict(self.config["models"]),
            "model_execution": self.services.model_policy.summary(), "ollama_profile": self.runtime.managed_profile_status(),
            "background_gpu": self.background_gpu.status(),
            "scheduler": self.scheduler.status(), "generation_cache": self.services.generation_cache.stats(),
            "semantic_cache": self.services.semantic_cache.stats(), "repo_cache": self.services.repo_cache.stats(),
            "commands": self.commands.stats(), "repo_snapshots": self.repo_tools.snapshot_stats(),
            "lossless_router": self.token_router.stats(), "pipeline": self.pipeline.stats(),
            "preprocessing": self.preprocessor.stats(), "tool_agent": self.tool_agent.stats(),
            "code_index": self.code_index.status(), "deterministic": self.deterministic.status(), "evidence_store": self.evidence.stats(),
            "learning": self.learner.stats(), "autotune": self.tuner.stats(),
            "circuit_breakers": self.services.breakers.status(), "recovery": self.recovery.status(limit=8),
            "fallback_count": self.services.fallback_count, "embeddings": self.embeddings.status(),
            "reranker": self.reranker.status(), "features": dict(self.config.get("features", {})),
            "hardware": dict(self.config.get("_hardware", {})), "accelerators": accelerator_status(self.config),
            "code_intelligence": self.external_tools.status(),
            "observability": telemetry_summary, "token_saving": telemetry_summary, "debug_traces": self.debug_traces.stats(),
        }
        res["agent_state"] = self._agent_state_summary()
        with self._status_full_cache_lock:
            self._status_full_cache[scope] = {"time": now, "data": res}
        return res


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

    def agent_state_cleanup(self, now: float | None = None) -> int:
        """Remove expired terminal records (incidents, receipts, memories) without touching active tasks."""
        if not getattr(self, "agent_state", None) or not self.agent_state.enabled:
            return 0
        if not self.agent_state.db_path.exists():
            return 0
        current_time = float(time.time() if now is None else now)
        from .sqlite_support import connect_sqlite, retry_busy

        def _cleanup() -> int:
            cnt = 0
            con = connect_sqlite(self.agent_state.db_path, isolation_level=None)
            try:
                con.execute("BEGIN IMMEDIATE")
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

                con.execute("COMMIT")
                return cnt
            except Exception:
                try:
                    con.execute("ROLLBACK")
                except Exception:
                    pass
                raise
            finally:
                con.close()

        return retry_busy(_cleanup, retries=5, base_delay_seconds=0.02)

    def export_bundle(self, root: str = "", *, agent_state_record_ids: list[str] | None = None) -> bytes:
        """Export portable precomputed project state into a bounded ZIP bundle."""
        import hashlib
        from contextlib import closing

        max_bundle, max_json, max_rows = self._bundle_limits()

        exported_agent_records: list[dict[str, Any]] = []
        if agent_state_record_ids is not None:
            for rid in agent_state_record_ids:
                rec = None
                if getattr(self, "agent_memory", None):
                    rec = self.agent_memory.get(rid)
                if rec is not None:
                    scope_val = getattr(rec.scope, "value", rec.scope)
                    status_val = getattr(rec.status, "value", rec.status)
                    if (scope_val == "global" or scope_val == AgentScope.GLOBAL) and status_val not in ("active", "confirmed", MemoryStatus.ACTIVE, MemoryStatus.CONFIRMED):
                        raise BundleValidationError(f"disallowed scope: unapproved global record {rid}")
                    exported_agent_records.append({"type": "memory", "data": rec.to_dict()})
                else:
                    t = self.agent_tasks.get(rid) if getattr(self, "agent_tasks", None) else None
                    if t is not None:
                        exported_agent_records.append({"type": "task", "data": t.to_dict()})
                    else:
                        raise BundleValidationError(f"record {rid} not found")

            if not root:
                canonical = json_dumps(exported_agent_records, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                bundle_data: dict[str, Any] = {
                    "format": "local-ai-hub-agent-state-bundle",
                    "version": __version__,
                    "exported_at": time.time(),
                    "records_sha256": hashlib.sha256(canonical).hexdigest(),
                    "records": exported_agent_records,
                }
                raw_json = json_dumps(bundle_data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                if len(raw_json) > max_json:
                    raise ValueError(f"bundle.json exceeds configured limit ({max_json} bytes)")
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
                    info = zipfile.ZipInfo("bundle.json")
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o600 << 16
                    zf.writestr(info, raw_json)
                result = buf.getvalue()
                if len(result) > max_bundle:
                    raise ValueError(f"bundle exceeds configured compressed limit ({max_bundle} bytes)")
                return result

        root_obj = Path(root).expanduser().resolve()
        if not root_obj.is_dir():
            raise ValueError(f"root directory does not exist: {root_obj}")
        root_path = str(root_obj).replace("\\", "/")
        for item in exported_agent_records:
            if item.get("type") != "memory":
                continue
            record_data = item.get("data") or {}
            if str(record_data.get("scope", "")).strip().lower() not in {"repo", "repository"}:
                continue
            provenance = record_data.get("provenance")
            source_root = provenance.get("root") if isinstance(provenance, dict) else None
            if not source_root:
                raise BundleValidationError(
                    f"repository memory record {record_data.get('record_id', '')} requires provenance root"
                )
            if source_root and _normalise_scope_root(str(source_root)) != _normalise_scope_root(root_path):
                raise BundleValidationError(
                    f"repository root mismatch for agent memory record {record_data.get('record_id', '')}"
                )
        workspace = self.rag.workspace_id(root_path)
        tables: dict[str, list[dict[str, Any]]] = {}

        def checked(name: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            if len(rows) > max_rows:
                raise ValueError(f"bundle table {name} exceeds configured row limit ({max_rows})")
            return rows

        with closing(self.preprocessor._connect()) as con:
            con.row_factory = sqlite3.Row
            tables["projects"] = checked("projects", [dict(r) for r in con.execute("SELECT * FROM projects WHERE root=?", (root_path,)).fetchall()])
            tables["file_refs"] = checked("file_refs", [dict(r) for r in con.execute("SELECT * FROM file_refs WHERE root=?", (root_path,)).fetchall()])
            tables["content_cards"] = checked("content_cards", [
                dict(r) for r in con.execute(
                    "SELECT * FROM content_cards WHERE card_key IN (SELECT card_key FROM file_refs WHERE root=? AND card_key IS NOT NULL)",
                    (root_path,),
                ).fetchall()
            ])
            tables["module_cards"] = checked("module_cards", [dict(r) for r in con.execute("SELECT * FROM module_cards WHERE root=?", (root_path,)).fetchall()])
            tables["project_cards"] = checked("project_cards", [dict(r) for r in con.execute("SELECT * FROM project_cards WHERE root=?", (root_path,)).fetchall()])
            tables["external_index_state"] = checked("external_index_state", [dict(r) for r in con.execute("SELECT * FROM external_index_state WHERE root=?", (root_path,)).fetchall()])

        if self.deterministic is not None:
            with closing(self.deterministic._connect()) as con:
                con.row_factory = sqlite3.Row
                tables["deterministic_files"] = checked("deterministic_files", [dict(r) for r in con.execute("SELECT * FROM files WHERE root=?", (root_path,)).fetchall()])
                tables["deterministic_facts"] = checked("deterministic_facts", [dict(r) for r in con.execute("SELECT * FROM facts WHERE root=?", (root_path,)).fetchall()])
                tables["dependencies"] = checked("dependencies", [dict(r) for r in con.execute("SELECT * FROM dependencies WHERE root=?", (root_path,)).fetchall()])
                tables["scripts"] = checked("scripts", [dict(r) for r in con.execute("SELECT * FROM scripts WHERE root=?", (root_path,)).fetchall()])

        if self.rag is not None:
            scope_key = self.rag._scope_key("__preprocess__")
            with closing(self.rag._connect()) as con:
                con.row_factory = sqlite3.Row
                tables["rag_files"] = checked("rag_files", [dict(r) for r in con.execute("SELECT * FROM files WHERE tenant=? AND workspace=?", (scope_key, workspace)).fetchall()])
                tables["rag_chunks"] = checked("rag_chunks", [dict(r) for r in con.execute("SELECT * FROM chunks WHERE tenant=? AND workspace=?", (scope_key, workspace)).fetchall()])

        encoded_tables = self._bundle_encode(tables)
        canonical = json_dumps(encoded_tables, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        bundle_data: dict[str, Any] = {
            "format": "local-ai-hub-project-bundle",
            "version": __version__,
            "root": root_path,
            "workspace": workspace,
            "exported_at": time.time(),
            "tables_sha256": hashlib.sha256(canonical).hexdigest(),
            "tables": encoded_tables,
        }
        if exported_agent_records:
            bundle_data["agent_state_records"] = exported_agent_records
            agent_records_canonical = json_dumps(
                exported_agent_records,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            bundle_data["agent_state_records_sha256"] = hashlib.sha256(agent_records_canonical).hexdigest()
            all_state_canonical = json_dumps(
                {"agent_state_records": exported_agent_records, "tables": encoded_tables},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            bundle_data["tables_sha256"] = hashlib.sha256(all_state_canonical).hexdigest()
        raw_json = json_dumps(bundle_data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(raw_json) > max_json:
            raise ValueError(f"bundle.json exceeds configured limit ({max_json} bytes)")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            info = zipfile.ZipInfo("bundle.json")
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            zf.writestr(info, raw_json)
        result = buf.getvalue()
        if len(result) > max_bundle:
            raise ValueError(f"bundle exceeds configured compressed limit ({max_bundle} bytes)")
        return result

    def import_bundle(self, bundle_bytes: bytes, target_root: str | None = None) -> dict[str, Any]:
        """Validate and restore a project bundle without extracting archive paths."""
        import hashlib
        import hmac
        from contextlib import closing

        max_bundle, max_json, max_rows = self._bundle_limits()
        if not isinstance(bundle_bytes, (bytes, bytearray)) or not bundle_bytes:
            return {"success": False, "error": "bundle is empty"}
        if len(bundle_bytes) > max_bundle:
            return {"success": False, "error": f"bundle exceeds configured limit ({max_bundle} bytes)"}
        try:
            with zipfile.ZipFile(io.BytesIO(bytes(bundle_bytes)), "r") as zf:
                infos = zf.infolist()
                if len(infos) != 1 or infos[0].filename != "bundle.json":
                    return {"success": False, "error": "bundle must contain exactly one bundle.json member"}
                info = infos[0]
                if info.is_dir() or info.file_size > max_json:
                    return {"success": False, "error": f"bundle.json exceeds configured limit ({max_json} bytes)"}
                raw = zf.read(info)
                if len(raw) != info.file_size:
                    return {"success": False, "error": "bundle.json size mismatch"}
                data = json.loads(raw.decode("utf-8"))
        except (zipfile.BadZipFile, KeyError, UnicodeDecodeError, json.JSONDecodeError, OSError) as exc:
            return {"success": False, "error": f"invalid bundle zip: {exc}"}

        if not isinstance(data, dict):
            return {"success": False, "error": "bundle root must be an object"}

        version = str(data.get("version", ""))
        if version != __version__:
            return {"success": False, "error": f"bundle version must match Local AI Hub {__version__}"}

        bundle_format = str(data.get("format", ""))

        def restore_agent_memory_records(
            records: Any,
            target_root_path: str | None = None,
            source_root_path: str | None = None,
        ) -> tuple[int, str | None]:
            if not isinstance(records, list):
                return 0, "bundle records are missing"
            restored = 0
            for item in records:
                if not isinstance(item, dict):
                    return 0, "invalid agent-state bundle record"
                rtype = item.get("type")
                rdata = item.get("data", {})
                if not isinstance(rdata, dict):
                    return 0, "invalid agent-state bundle payload"
                if rtype == "memory" and getattr(self, "agent_memory", None):
                    record_data = dict(rdata)
                    scope_value = str(record_data.get("scope", "")).strip().lower()
                    provenance = record_data.get("provenance")
                    if target_root_path and scope_value in {"repo", "repository"}:
                        source_root = provenance.get("root") if isinstance(provenance, dict) else None
                        if not source_root:
                            return 0, "repository memory provenance root is required for project import"
                        if not source_root_path:
                            return 0, "project bundle root is required for repository memory import"
                        if _normalise_scope_root(str(source_root)) != _normalise_scope_root(source_root_path):
                            return 0, "repository memory provenance does not match bundle root"
                        rebased_provenance = dict(provenance)
                        rebased_provenance["source_root"] = str(source_root)
                        rebased_provenance["root"] = target_root_path
                        record_data["provenance"] = rebased_provenance
                    from_dict = getattr(MemoryRecord, "from_dict", None)
                    if callable(from_dict) and all(
                        field in record_data for field in ("record_id", "status", "provenance")
                    ):
                        try:
                            rec = from_dict(record_data)
                        except (KeyError, TypeError, ValueError):
                            rec = MemoryRecord.create(
                                kind=MemoryKind(record_data.get("kind", "fact")),
                                scope=AgentScope.parse(record_data.get("scope", "task")),
                                key=str(record_data.get("key", "")),
                                value=record_data.get("value"),
                                scope_id=str(record_data.get("scope_id", "")),
                                status=MemoryStatus(record_data.get("status", "candidate")),
                            )
                    else:
                        rec = MemoryRecord.create(
                            kind=MemoryKind(record_data.get("kind", "fact")),
                            scope=AgentScope.parse(record_data.get("scope", "task")),
                            key=str(record_data.get("key", "")),
                            value=record_data.get("value"),
                            scope_id=str(record_data.get("scope_id", "")),
                            status=MemoryStatus(record_data.get("status", "candidate")),
                        )
                    self.agent_memory.record(rec, actor="bundle_import")
                    restored += 1
            return restored, None

        if bundle_format == "local-ai-hub-agent-state-bundle":
            records = data.get("records", [])
            if not isinstance(records, list):
                return {"success": False, "error": "bundle records are missing"}
            canonical = json_dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            expected = str(data.get("records_sha256", ""))
            if not expected or not hmac.compare_digest(hashlib.sha256(canonical).hexdigest(), expected):
                return {"success": False, "error": "bundle integrity check failed"}
            restored, error = restore_agent_memory_records(records)
            if error:
                return {"success": False, "error": error}
            return {"success": True, "version": __version__, "restored_records": restored}

        if bundle_format != "local-ai-hub-project-bundle":
            return {"success": False, "error": "invalid Local AI Hub bundle marker"}

        encoded_tables: Any = data.get("tables")
        if not isinstance(encoded_tables, dict):
            return {"success": False, "error": "bundle tables are missing"}
        has_agent_records = "agent_state_records" in data
        has_agent_records_hash = "agent_state_records_sha256" in data
        if has_agent_records != has_agent_records_hash:
            return {"success": False, "error": "bundle integrity check failed"}
        canonical = json_dumps(encoded_tables, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        expected = str(data.get("tables_sha256", ""))
        table_hash_valid = bool(expected) and hmac.compare_digest(hashlib.sha256(canonical).hexdigest(), expected)
        if has_agent_records:
            agent_records = data.get("agent_state_records")
            if not isinstance(agent_records, list):
                return {"success": False, "error": "invalid agent-state bundle records"}
            agent_records_canonical = json_dumps(
                agent_records,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            agent_records_expected = str(data.get("agent_state_records_sha256", ""))
            if not agent_records_expected or not hmac.compare_digest(
                hashlib.sha256(agent_records_canonical).hexdigest(), agent_records_expected
            ):
                return {"success": False, "error": "bundle integrity check failed"}
            all_state_canonical = json_dumps(
                {"agent_state_records": agent_records, "tables": encoded_tables},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            table_hash_valid = table_hash_valid or hmac.compare_digest(
                hashlib.sha256(all_state_canonical).hexdigest(), expected
            )
        if not table_hash_valid:
            return {"success": False, "error": "bundle integrity check failed"}
        try:
            tables = self._bundle_decode(encoded_tables)
        except Exception as exc:
            return {"success": False, "error": f"invalid encoded bundle value: {exc}"}

        allowed_tables = {
            "projects", "file_refs", "content_cards", "module_cards", "project_cards", "external_index_state",
            "deterministic_files", "deterministic_facts", "dependencies", "scripts", "rag_files", "rag_chunks",
        }
        for name, tbl_rows in tables.items():
            if name not in allowed_tables:
                continue
            if not isinstance(tbl_rows, list) or len(tbl_rows) > max_rows or any(not isinstance(row, dict) for row in tbl_rows):
                return {"success": False, "error": f"invalid or oversized bundle table: {name}"}

        orig_root = str(data.get("root", ""))
        root = str(target_root or orig_root)
        root_obj = Path(root).expanduser().resolve(strict=False) if root else None
        if root_obj is None or not root_obj.is_dir():
            return {"success": False, "error": "target repository root does not exist"}
        root_path = str(root_obj).replace("\\", "/")
        workspace = self.rag.workspace_id(root_path)
        now = time.time()

        def rows(name: str) -> list[dict[str, Any]]:
            value = tables.get(name, [])
            return value if isinstance(value, list) else []

        def _str(d: dict[str, Any], key: str, default: str = "") -> str:
            """Type-safe string extraction — prevents empty-path bugs from malformed bundles."""
            v = d.get(key, default)
            return str(v) if v is not None else default

        def _int(d: dict[str, Any], key: str, default: int = 0) -> int:
            """Type-safe int extraction with graceful fallback."""
            try:
                return int(d.get(key) or default)
            except (TypeError, ValueError):
                return default

        # Restore root-scoped preprocessor state transactionally. Derived content
        # cards are content-addressed and therefore safe to upsert globally.
        with self.preprocessor._db_lock, closing(self.preprocessor._connect()) as con:
            con.execute("BEGIN IMMEDIATE")
            for table in ("file_refs", "module_cards", "project_cards", "external_index_state"):
                assert table in _PREPROCESS_TABLES, f"unexpected table name: {table}"  # defence-in-depth
                con.execute(f"DELETE FROM {table} WHERE root=?", (root_path,))  # noqa: S608
            con.execute("DELETE FROM projects WHERE root=?", (root_path,))
            project = rows("projects")[0] if rows("projects") else {}
            con.execute(
                """INSERT INTO projects(root,workspace,status,phase,generation,force_refresh,inventory_hash,structural_hash,registered_at,updated_at,last_complete_at,next_check_at,retry_after,last_error,stats_json,paused,last_requested_at,registration_source)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (root_path, workspace, "complete", "complete", int(project.get("generation", 1) or 1), 0,
                 project.get("inventory_hash"), project.get("structural_hash"), now, now, now, 0, 0, None,
                 str(project.get("stats_json", "{}") or "{}"), 0, now, "bundle-import"),
            )
            for f in rows("file_refs"):
                con.execute(
                    """INSERT INTO file_refs(root,path,content_hash,size,mtime_ns,needs_hash,rag_hash,last_accessed_at,generation,card_key,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (root_path, str(f.get("path", "")), str(f.get("content_hash", "")), int(f.get("size", 0) or 0),
                     int(f.get("mtime_ns", 0) or 0), 0, f.get("rag_hash"), now, int(f.get("generation", 1) or 1), f.get("card_key"), now),
                )
            for c in rows("content_cards"):
                con.execute(
                    """INSERT OR REPLACE INTO content_cards(card_key,content_hash,model,analyzer_version,card_json,created_at,accessed_at,hits)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    (str(c.get("card_key", "")), str(c.get("content_hash", "")), str(c.get("model", "")),
                     str(c.get("analyzer_version", "")), str(c.get("card_json", "{}")), float(c.get("created_at", now) or now), now, int(c.get("hits", 0) or 0)),
                )
            for m in rows("module_cards"):
                con.execute("INSERT INTO module_cards(root,module,revision_hash,card_json,updated_at) VALUES(?,?,?,?,?)",
                            (root_path, str(m.get("module", "")), str(m.get("revision_hash", "")), str(m.get("card_json", "{}")), now))
            for item in rows("project_cards")[:1]:
                con.execute("INSERT INTO project_cards(root,revision_hash,card_json,updated_at) VALUES(?,?,?,?)",
                            (root_path, str(item.get("revision_hash", "")), str(item.get("card_json", "{}")), now))
            for item in rows("external_index_state"):
                con.execute("INSERT INTO external_index_state(root,backend,revision_hash,status,updated_at,error) VALUES(?,?,?,?,?,?)",
                            (root_path, str(item.get("backend", "")), str(item.get("revision_hash", "")), str(item.get("status", "complete")), now, item.get("error")))
            con.commit()

        if self.deterministic is not None:
            with self.deterministic._lock, closing(self.deterministic._connect()) as con:
                con.execute("BEGIN IMMEDIATE")
                for table in ("files", "facts", "dependencies", "scripts", "project_state", "query_cache"):
                    assert table in _DET_TABLES, f"unexpected table name: {table}"  # defence-in-depth
                    con.execute(f"DELETE FROM {table} WHERE root=?", (root_path,))  # noqa: S608
                for f in rows("deterministic_files"):
                    con.execute(
                        "INSERT INTO files(root,path,content_hash,language,is_test,updated_at) VALUES(?,?,?,?,?,?)",
                        (root_path, str(f.get("path", "")), str(f.get("content_hash", "")), str(f.get("language", "")), int(f.get("is_test", 0) or 0), now),
                    )
                for ft in rows("deterministic_facts"):
                    extra = ft.get("extra_json")
                    if extra is None:
                        extra = json_dumps({k: ft[k] for k in ("method", "source", "confidence") if k in ft}, separators=(",", ":"))
                    elif not isinstance(extra, str):
                        extra = json_dumps(extra, ensure_ascii=False, separators=(",", ":"))
                    con.execute(
                        "INSERT INTO facts(root,path,kind,name,value,line,extra_json) VALUES(?,?,?,?,?,?,?)",
                        (root_path, str(ft.get("path", "")), str(ft.get("kind", "")), str(ft.get("name", "")), str(ft.get("value", "")), int(ft.get("line", 0) or 0), str(extra or "{}")),
                    )
                for d in rows("dependencies"):
                    con.execute("INSERT OR REPLACE INTO dependencies(root,source,name,version,scope) VALUES(?,?,?,?,?)",
                                (root_path, str(d.get("source", "")), str(d.get("name", "")), str(d.get("version", "")), str(d.get("scope", ""))))
                for item in rows("scripts"):
                    con.execute("INSERT OR REPLACE INTO scripts(root,source,name,command,purpose) VALUES(?,?,?,?,?)",
                                (root_path, str(item.get("source", "")), str(item.get("name", "")), str(item.get("command", "")), str(item.get("purpose", ""))))
                con.commit()

        if self.rag is not None:
            scope_key = self.rag._scope_key("__preprocess__")
            with self.rag._index_lock, closing(self.rag._connect()) as con:
                con.execute("BEGIN IMMEDIATE")
                con.execute("DELETE FROM chunks WHERE tenant=? AND workspace=?", (scope_key, workspace))
                con.execute("DELETE FROM files WHERE tenant=? AND workspace=?", (scope_key, workspace))
                for f in rows("rag_files"):
                    con.execute("INSERT INTO files(tenant,workspace,path,mtime_ns,size,content_hash) VALUES(?,?,?,?,?,?)",
                                (scope_key, workspace, str(f.get("path", "")), int(f.get("mtime_ns", 0) or 0), int(f.get("size", 0) or 0), str(f.get("content_hash", ""))))
                for c in rows("rag_chunks"):
                    con.execute("INSERT INTO chunks(tenant,workspace,path,chunk_no,content_hash,text,embedding) VALUES(?,?,?,?,?,?,?)",
                                (scope_key, workspace, str(c.get("path", "")), int(c.get("chunk_no", 0) or 0), str(c.get("content_hash", "")), str(c.get("text", "")), c.get("embedding", "")))
                con.commit()

        restored_agent_records = 0
        if "agent_state_records" in data:
            restored_agent_records, error = restore_agent_memory_records(
                data.get("agent_state_records"), root_path, str(data.get("root", ""))
            )
            if error:
                return {"success": False, "error": error}

        return {
            "success": True,
            "version": __version__,
            "root": root_path,
            "workspace": workspace,
            "files_imported": len(rows("file_refs")),
            "cards_imported": len(rows("content_cards")),
            "rag_chunks_imported": len(rows("rag_chunks")),
            "agent_state_records_imported": restored_agent_records,
        }

    def __enter__(self) -> "LocalAIApp":
        return self

    def __exit__(self, _exc_type: Any, _exc: Any, _tb: Any) -> None:
        self.close()

    def close(self) -> None:
        # ``close`` is intentionally idempotent: HTTP shutdown, service control and
        # embedded callers can race during teardown without double-closing workers.
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        self._shutdown.set()
        # Stop helper loops before tearing down the services they periodically touch.
        # They are daemon threads as a final safety net, but bounded joins make normal
        # restart/shutdown deterministic and avoid late telemetry/preprocessor calls.
        current = threading.current_thread()
        for thread in (self._prewarm_thread, self._watchdog_thread):
            if thread is not None and thread is not current and thread.is_alive():
                thread.join(timeout=1.5)
        try:
            self.preprocessor.close()
        except Exception:
            pass
        try:
            self.external_tools.close()
        except Exception:
            pass
        try:
            self.work_orchestrator.close()
        except Exception:
            pass
        try:
            self.async_jobs.close()
        except Exception:
            pass
        try:
            self.background_gpu.close()
        except Exception:
            pass
        try:
            self.scheduler.close()
        except Exception:
            pass
        try:
            self.telemetry.close()
        except Exception:
            pass
        try:
            shutdown_logging()
        except Exception:
            pass
