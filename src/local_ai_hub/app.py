from __future__ import annotations

from .json_utils import dumps as json_dumps

import stat
import io
import json
import sqlite3
import threading
import time
import zipfile
from contextlib import ExitStack
from concurrent.futures import CancelledError
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

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
from .sqlite_support import migrate_agent_state_database
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
from .status_executor import StatusDependencyExecutor


_STATUS_DEPENDENCY_TIMEOUT_SECONDS = 0.25
_STATUS_MAX_WORKERS = 32
_STATUS_MAX_INFLIGHT_DEPENDENCIES = 32


def _new_status_dependency_executor() -> StatusDependencyExecutor:
    return StatusDependencyExecutor(
        max_workers=_STATUS_MAX_WORKERS,
        capacity=_STATUS_MAX_INFLIGHT_DEPENDENCIES,
    )


def _accelerator_status_fallback(config: dict[str, Any]) -> dict[str, Any]:
    models = config.get("models", {}) if isinstance(config, dict) else {}
    if not isinstance(models, dict):
        models = {}
    return {
        "openvino": {
            "installed": None,
            "available": None,
            "devices": [],
            "error": "status probe unavailable within request deadline",
        },
        "embedding": {
            "backend": models.get("embedding_backend", "sentence-transformers"),
            "requested_device": models.get("embedding_device", "cpu"),
            "candidates": [],
        },
        "reranker": {
            "backend": models.get("reranker_backend", "torch"),
            "requested_device": models.get("reranker_device", "cpu"),
            "candidates": [],
        },
    }


def _online_probe_status(value: Any, healthy: bool) -> str:
    if not healthy or value is None:
        return "unknown"
    return "online" if bool(value) else "offline"


_STATUS_METADATA_CACHE_SECONDS = 5.0
_STATUS_METADATA_KEYS = frozenset(
    f"{view}:{scope}:{name}"
    for view in ("live", "full") for scope in ("process", "window")
    for name in ("telemetry.summary", "preprocessing.status")
)


def _status_probe_key(view: str, scope: str, key: str) -> str:
    return f"{view}:{scope}:{key}" if key in {"telemetry.summary", "preprocessing.status"} else key


def _schedule_status_dependency(callback, fallback, *, key, lock, inflight, slots, executor, deadline, diagnostic=None, completed_cache=None):
    """Start or reuse bounded status work without waiting for its result."""
    def mark_degraded(reason, error=None):
        if diagnostic is None:
            return
        diagnostic["reason"] = reason
        if error is not None:
            diagnostic["error_type"] = type(error).__name__

    submitted = None
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        mark_degraded("deadline_exhausted")
        return {"fallback": fallback, "healthy": False}
    if not lock.acquire(timeout=remaining):
        mark_degraded("lock_timeout")
        return {"fallback": fallback, "healthy": False}
    try:
        cached = completed_cache.get(key) if completed_cache is not None and key in _STATUS_METADATA_KEYS else None
        if cached is not None:
            age = max(0.0, time.monotonic() - cached["completed_at"])
            if age < _STATUS_METADATA_CACHE_SECONDS:
                if diagnostic is not None:
                    diagnostic.update(dependency_cached=True, dependency_age_ms=int(age * 1000))
                return {"entry": cached, "fallback": fallback}
            del completed_cache[key]
        entry = inflight.get(key)
        if entry is None:
            if not slots.acquire(blocking=False):
                mark_degraded("worker_capacity_exhausted")
                return {"fallback": fallback, "healthy": False}
            entry = {"completed": threading.Event(), "outcome": {}}
            inflight[key] = entry

            def run() -> None:
                try:
                    entry["outcome"]["value"] = callback()
                except BaseException as exc:
                    entry["outcome"]["error"] = exc
                finally:
                    try:
                        slots.release()
                    finally:
                        with lock:
                            entry["completed_at"] = time.monotonic()
                            entry["completed"].set()
                            if inflight.get(key) is entry:
                                del inflight[key]
                            if completed_cache is not None and key in _STATUS_METADATA_KEYS and "error" not in entry["outcome"]:
                                completed_cache[key] = entry

            try:
                submitted = executor.submit(run)
            except Exception as exc:
                del inflight[key]
                slots.release()
                mark_degraded("executor_submit_error", exc)
                return {"fallback": fallback, "healthy": False}
    finally:
        lock.release()
    if submitted is not None:
        def submission_finished(future):
            error = CancelledError() if future.cancelled() else future.exception()
            if error is None:
                return
            with lock:
                if inflight.get(key) is not entry:
                    return
                del inflight[key]
            entry["outcome"]["error"] = error
            try:
                slots.release()
            finally:
                entry["completed"].set()

        submitted.add_done_callback(submission_finished)
    return {"entry": entry, "fallback": fallback}


def _resolve_status_dependency(handle, *, deadline, diagnostic=None):
    fallback = handle["fallback"]
    if "healthy" in handle:
        return fallback, handle["healthy"]
    entry = handle["entry"]
    if not entry["completed"].is_set():
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not entry["completed"].wait(remaining):
            if diagnostic is not None:
                diagnostic["reason"] = "probe_timeout"
            return fallback, False
    outcome = entry["outcome"]
    if "error" in outcome:
        if diagnostic is not None:
            diagnostic["reason"] = "probe_error"
            diagnostic["error_type"] = type(outcome["error"]).__name__
        return fallback, False
    return deepcopy(outcome.get("value", fallback)), True


def _status_dependency(callback, fallback, *, key, lock, inflight, slots, executor, deadline=None, diagnostic=None, completed_cache=None):
    """Reuse active status work and cap workers that remain stuck past their deadline."""
    if deadline is None:
        deadline = time.monotonic() + max(0.0, float(_STATUS_DEPENDENCY_TIMEOUT_SECONDS))
    handle = _schedule_status_dependency(
        callback,
        fallback,
        key=key,
        lock=lock,
        inflight=inflight,
        slots=slots,
        executor=executor,
        deadline=deadline,
        diagnostic=diagnostic,
        completed_cache=completed_cache,
    )
    return _resolve_status_dependency(handle, deadline=deadline, diagnostic=diagnostic)


def _runtime_is_available(runtime: Any) -> bool:
    """Return false only when an adapter explicitly reports no backend."""
    check = getattr(runtime, "is_online", None)
    if not callable(check):
        return True
    try:
        return bool(check())
    except Exception:
        return True


def _prewarm_route_is_eligible(runtime: Any, model: str) -> bool:
    """Avoid retrying a model whose explicit adapter cannot run on this host."""
    candidates = [runtime, getattr(runtime, "fast", None), getattr(runtime, "smart", None)]
    seen: set[int] = set()
    for candidate in candidates:
        if candidate is None or id(candidate) in seen:
            continue
        seen.add(id(candidate))
        router = getattr(candidate, "llama_cpp", None)
        supports = getattr(router, "supports_model", None)
        hardware_enabled = getattr(router, "hardware_enabled", None)
        if not callable(supports) or not callable(hardware_enabled):
            continue
        try:
            fallback = bool(getattr(candidate, "config", {}).get("llama_cpp", {}).get("fallback_to_ollama", True))
            if bool(supports(model)) and not bool(hardware_enabled()) and not fallback:
                return False
        except Exception:
            continue
    return True


def _wait_for_prewarm_backend(runtime: Any, shutdown: threading.Event, max_wait_seconds: float) -> bool:
    """Give a managed backend a short startup grace period without blocking requests."""
    deadline = time.monotonic() + max(0.0, float(max_wait_seconds))
    while not shutdown.is_set():
        if _runtime_is_available(runtime):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        shutdown.wait(min(1.0, remaining))
    return False


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
        migrate_agent_state_database(state_dir)
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
        self._status_dependency_lock = threading.Lock()
        self._status_dependency_inflight: dict[str, dict[str, Any]] = {}
        self._status_metadata_cache: dict[str, dict[str, Any]] = {}
        self._status_dependency_slots = threading.BoundedSemaphore(_STATUS_MAX_INFLIGHT_DEPENDENCIES)
        self._status_dependency_executor = _new_status_dependency_executor()

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
            memory_store=self.agent_memory,
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
        self.async_jobs = AsyncJobManager(
            self.config, self.scheduler, self.artifacts, self._execute_async_task,
            debug_traces=self.debug_traces,
            task_store=self.agent_tasks,
            verification_store=self.agent_verification,
            telemetry=self.telemetry,
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
        self.preprocessor = ProjectPreprocessor(self.config, self.services, self.rag, self.scheduler, self.runtime, self.repo_tools, self.code_index, self.learner, self.deterministic, telemetry=self.telemetry, background_gpu=self.background_gpu, external_tools=self.external_tools)
        self.services.set_preprocessor(self.preprocessor)
        self.code_index.set_reindex_callback(self.preprocessor.notify_path_changed)
        self._recover_pending_bundle_imports()
        self.token_router = LosslessTokenRouter(self.config, self.services)
        self.services.set_token_router(self.token_router)
        self.tool_agent = ToolAwareLocalAgent(self.config, self.services, self.preprocessor, self.rag, self.code_index, self.evidence, self.deterministic, external_tools=self.external_tools)
        self.services.set_tool_agent(self.tool_agent)
        self.pipeline = LocalAgentPipeline(self.config, self.services, self.token_router, self.tool_agent)
        self.services.set_pipeline(self.pipeline)
        self.work_orchestrator = WorkOrchestrator(self.config, state_dir, self.services, self.commands, self.leases, self.artifacts, telemetry=self.telemetry)
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
                            return
                    except Exception as exc:
                        self.telemetry.record_error("prewarm", "startup_model", exc, recovered=True)
                        self.logger.warning("prewarm attempt failed: %s", type(exc).__name__)
                    self._shutdown.wait(min(15.0, 1.5 + attempts * 0.5))
            self._prewarm_thread = threading.Thread(target=warm, name="local-ai-prewarm", daemon=True)
            self._prewarm_thread.start()
        self.async_jobs.recover()

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

    def _bind_service_inference_admission(self) -> None:
        if hasattr(self, "services") and hasattr(self, "async_jobs"):
            self.services.inference_admission = self.async_jobs.inference_admission

    def _start_resilience_watchdog(self) -> None:
        cfg = self.config.get("resilience", {})
        if not bool(cfg.get("watchdog_enabled", True)):
            return
        self._watchdog_thread = threading.Thread(target=self._watchdog_loop, name="local-ai-watchdog", daemon=True)
        self._watchdog_thread.start()

    def _execute_async_task(self, action: str, payload: dict[str, Any], tenant: str) -> dict[str, Any]:
        with self.async_jobs.inference_admission(action) as rejection:
            if rejection is not None:
                return rejection
            runner = getattr(self, "_execute_async_task_admitted", None)
            if callable(runner):
                return runner(action, payload, tenant)
            return LocalAIApp._execute_async_task_admitted(self, action, payload, tenant)

    def _execute_async_task_admitted(self, action: str, payload: dict[str, Any], tenant: str) -> dict[str, Any]:
        from .async_jobs import report_job_progress
        report_job_progress(0.0, f"executing:{action}")
        async_payload = dict(payload)
        async_payload["priority"] = 1
        for untrusted_context in ("project_context", "project_model_profile", "system_prefix"):
            async_payload.pop(untrusted_context, None)
        if action == "delegate":
            return self.services.delegate(async_payload, tenant)
        if action == "reason":
            reason_payload = dict(async_payload)
            reason_payload.update({"problem": async_payload.get("task", ""), "context": async_payload.get("context", ""), "max_tokens": async_payload.get("max_tokens", 1200), "priority": 1})
            return self.services.reason(reason_payload, tenant)
        if action == "review":
            review_payload = dict(async_payload)
            review_payload.update({"code": async_payload.get("context", ""), "instructions": async_payload.get("task", "Report actionable defects only."), "complexity": async_payload.get("complexity", "auto"), "max_tokens": async_payload.get("max_tokens", 1300), "priority": 1})
            return self.services.review(review_payload, tenant)
        if action == "review_diff":
            review_payload = dict(async_payload)
            review_payload["_async_job"] = True
            return self.services.review_diff(review_payload, tenant)
        if action == "second_opinion":
            opinion_payload = dict(async_payload)
            opinion_payload.update({"question": async_payload.get("task", ""), "candidate": async_payload.get("candidate", ""), "context": async_payload.get("context", ""), "max_tokens": async_payload.get("max_tokens", 1100), "priority": 1})
            return self.services.second_opinion(opinion_payload, tenant)
        if action == "compress":
            compress_payload = dict(async_payload)
            compress_payload.update({"text": async_payload.get("context", ""), "instruction": async_payload.get("task", "Compress while preserving facts."), "target_tokens": async_payload.get("max_tokens", 650), "priority": 1})
            return self.services.compress(compress_payload, tenant)
        if action == "route":
            route_payload = dict(async_payload)
            route_payload.update({"text": async_payload.get("context", ""), "query": async_payload.get("task", "")})
            return self.services.route_context(route_payload, tenant)
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
            return self.services.batch_delegate({"tasks": tasks, "priority": 1}, tenant)
        if action == "speculative_lint":
            return self.services.speculative_lint(async_payload, tenant)
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
        cache_ttl = 5.0 if light else 1.5

        def cached_snapshot(cached: tuple[float, dict[str, Any]], now: float, *, stale: bool = False) -> dict[str, Any]:
            result = deepcopy(cached[1])
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
            deadline = time.monotonic() + max(0.0, float(_STATUS_DEPENDENCY_TIMEOUT_SECONDS))
            dependency_status: dict[str, dict[str, Any]] = {}

            def read(key: str, callback, fallback):
                diagnostic: dict[str, Any] = {}
                dep_deadline = time.monotonic() + max(0.0, float(_STATUS_DEPENDENCY_TIMEOUT_SECONDS))
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
                    "deadline_ms": max(0, int(_STATUS_DEPENDENCY_TIMEOUT_SECONDS * 1000)),
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
                row = dict(item)
                root = str(row.get("root", ""))
                row["project"] = Path(root).name or root
                projects.append(row)
            from .features import FeatureSet
            fs = FeatureSet.from_config(self.config)
            observability, telemetry_healthy = read("telemetry.summary", lambda: self.telemetry.realtime_summary(scope=scope), {})
            accelerators, accelerator_healthy = read("accelerators", lambda: accelerator_status(self.config), _accelerator_status_fallback(self.config))
            background_gpu, background_gpu_healthy = read("background_gpu", self.background_gpu.status, {})
            model_policy = getattr(getattr(self, "services", None), "model_policy", None)
            model_execution, model_execution_healthy = read("model_execution", model_policy.summary if model_policy else lambda: {}, {})
            vram_balancer_obj = getattr(self, "vram_balancer", None)
            vram_balancer, vram_balancer_healthy = read("vram_balancer", vram_balancer_obj.status if vram_balancer_obj else lambda: {}, {})
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
            result = {
                "success": not any(item["degraded"] for item in dependency_status.values()), "hub_online": True, "version": __version__,
                "snapshot_cached": False, "degraded": any(item["degraded"] for item in dependency_status.values()),
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
                },
                "models": dict(self.config.get("models", {})),
                "hardware": dict(self.config.get("_hardware", {})),
                "accelerators": accelerators,
                "code_intelligence": code_intelligence,
                "runtime_profile": {
                    "tiered_models": self.config.get("models", {}).get("heavy_code") != self.config.get("models", {}).get("fast_code"),
                    "max_loaded_models": int(self.config.get("scheduler", {}).get("max_loaded_models", 1)),
                    "max_parallel": int(self.config.get("scheduler", {}).get("max_parallel", 1)),
                    "execution": model_execution,
                    "flash_attention": bool(self.config.get("ollama", {}).get("flash_attention", True)),
                    "kv_cache_type": str(self.config.get("ollama", {}).get("kv_cache_type", "q8_0")),
                },
                "ollama_online": ollama, "ollama_status": ollama_status, "scheduler": scheduler,
                "headless": headless,
                "background_gpu": background_gpu,
                "ollama_profile": ollama_profile,
                "model_execution": model_execution,
                "vram_balancer": vram_balancer,
                "benchmark": benchmark,
                "debug_traces": debug_traces,
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
                "runtime_stats": runtime_stats,
            }
            result["agent_state"] = agent_state
            for key, healthy in (("headless", headless_healthy), ("runtime.online", runtime_healthy), ("ollama_profile", profile_healthy), ("scheduler", scheduler_healthy), ("preprocessing.stats", prep_stats_healthy), ("preprocessing.status", prep_status_healthy), ("telemetry.summary", telemetry_healthy), ("accelerators", accelerator_healthy), ("background_gpu", background_gpu_healthy), ("model_execution", model_execution_healthy), ("vram_balancer", vram_balancer_healthy), ("benchmark", benchmark_healthy), ("debug_traces", traces_healthy)):
                if not healthy:
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
            return _status_dependency(
                callback,
                fallback,
                key=_status_probe_key("full", scope, key),
                completed_cache=getattr(self, "_status_metadata_cache", None),
                lock=self._status_dependency_lock,
                inflight=self._status_dependency_inflight,
                slots=self._status_dependency_slots,
                executor=self._status_dependency_executor,
                deadline=deadline,
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
            pending_dependencies: dict[str, tuple[dict[str, Any], Any, dict[str, Any]]] = {}

            def read(key, callback, fallback):
                nonlocal degraded
                probe_started = time.monotonic()
                pending = pending_dependencies.pop(key, None)
                if pending is None:
                    diagnostic: dict[str, Any] = {}
                    value, healthy = dependency(key, callback, fallback, diagnostic)
                else:
                    handle, fallback, diagnostic = pending
                    value, healthy = _resolve_status_dependency(handle, deadline=deadline, diagnostic=diagnostic)
                degraded = degraded or not healthy
                dependency_status[key] = {
                    "degraded": not healthy,
                    "deadline_ms": max(0, int(_STATUS_DEPENDENCY_TIMEOUT_SECONDS * 1000)),
                    "duration_ms": max(0, int((time.monotonic() - probe_started) * 1000)),
                    **diagnostic,
                }
                return value

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
            # Runtime availability is a separate probe phase. A slow runtime must
            # not consume the status snapshot's budget for independent Hub state.
            deadline = time.monotonic() + max(0.0, float(_STATUS_DEPENDENCY_TIMEOUT_SECONDS))
            status_probes = {
                "scheduler": (self.scheduler.status, {}),
                "accelerators": (lambda: accelerator_status(self.config), _accelerator_status_fallback(self.config)),
                "telemetry.summary": (lambda: self.telemetry.summary(scope=scope, _flush=False), {}),
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
                handle = _schedule_status_dependency(
                    callback,
                    fallback,
                    key=_status_probe_key("full", scope, key),
                    completed_cache=getattr(self, "_status_metadata_cache", None),
                    lock=self._status_dependency_lock,
                    inflight=self._status_dependency_inflight,
                    slots=self._status_dependency_slots,
                    executor=self._status_dependency_executor,
                    deadline=deadline,
                    diagnostic=diagnostic,
                )
                pending_dependencies[key] = (handle, fallback, diagnostic)
            scheduler = read("scheduler", self.scheduler.status, {})
            accelerators = read(
                "accelerators",
                lambda: accelerator_status(self.config),
                _accelerator_status_fallback(self.config),
            )
            telemetry_summary = read("telemetry.summary", lambda: self.telemetry.summary(scope=scope, _flush=False), {})
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
                "observability": telemetry_summary, "token_saving": telemetry_summary, "debug_traces": debug_traces,
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

    def export_bundle(
        self,
        root: str = "",
        *,
        tenant: str | None = None,
        agent_state_record_ids: list[str] | None = None,
        agent_state_contexts: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> bytes:
        """Export portable precomputed project state into a bounded ZIP bundle."""
        import hashlib
        from contextlib import closing

        max_bundle, max_json, max_rows = self._bundle_limits()

        exported_agent_records: list[dict[str, Any]] = []
        if agent_state_record_ids is not None:
            for rid in agent_state_record_ids:
                rec = None
                if getattr(self, "agent_memory", None):
                    supplied_context = (agent_state_contexts or {}).get(rid, {})
                    lookup_context = {
                        key: supplied_context[key]
                        for key in (
                            "scope", "scope_id", "root", "repository_id", "tenant",
                            "task_id", "session_id", "clone_id", "worktree_id", "branch",
                        )
                        if key in supplied_context
                    }
                    lookup_context.setdefault("root", root or None)
                    lookup_context.setdefault("tenant", tenant)
                    scope_value = getattr(lookup_context.get("scope"), "value", lookup_context.get("scope"))
                    if scope_value in ("repo", "repository") and not str(lookup_context.get("root") or "").strip():
                        raise BundleValidationError("repository memory requires provenance root")
                    if rid in (agent_state_contexts or {}):
                        rec = self.agent_memory.get(rid, **lookup_context)
                    else:
                        rec = self.agent_memory.get(
                            rid, scope=AgentScope.GLOBAL, tenant=tenant,
                        )
                        if rec is None and root and tenant:
                            rec = self.agent_memory.get(
                                rid, scope=AgentScope.REPOSITORY,
                                root=root, tenant=tenant,
                            )
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
        import os
        import tempfile
        import uuid
        from dataclasses import replace
        from contextlib import closing, contextmanager

        max_bundle, max_json, max_rows = self._bundle_limits()
        if not isinstance(bundle_bytes, (bytes, bytearray)) or not bundle_bytes:
            return {"success": False, "error": "bundle is empty"}
        if len(bundle_bytes) > max_bundle:
            return {"success": False, "error": f"bundle exceeds configured limit ({max_bundle} bytes)"}
        raw_bundle = bytes(bundle_bytes)
        bundle_sha256 = hashlib.sha256(raw_bundle).hexdigest()

        def sync_directory(path: Path) -> None:
            if os.name == "nt":
                return
            directory_fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)

        def atomic_write(path: Path, value: bytes) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile("wb", dir=path.parent, prefix=f".{path.name}.", delete=False) as stream:
                    temp_path = Path(stream.name)
                    stream.write(value)
                    stream.flush()
                    os.fsync(stream.fileno())
                if os.name == "nt":
                    import ctypes

                    move_file_ex = ctypes.WinDLL("kernel32", use_last_error=True).MoveFileExW
                    move_file_ex.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
                    move_file_ex.restype = ctypes.c_int
                    if not move_file_ex(str(temp_path), str(path), 0x1 | 0x8):
                        raise ctypes.WinError(ctypes.get_last_error())
                else:
                    os.replace(temp_path, path)
                    sync_directory(path.parent)
            except Exception:
                if temp_path is not None:
                    temp_path.unlink(missing_ok=True)
                raise

        def create_import_intent(root_path: str | None) -> dict[str, Any]:
            normalized_root = str(Path(root_path).resolve(strict=False)).replace("\\", "/") if root_path else None
            import_id = hashlib.sha256(f"{bundle_sha256}\0{normalized_root or ''}".encode("utf-8")).hexdigest()
            journal_dir = Path(self.config["server"]["state_dir"]) / "bundle-imports"
            payload_path = journal_dir / f"{import_id}.bundle"
            journal_path = journal_dir / f"{import_id}.json"
            if journal_dir.is_symlink():
                raise OSError("bundle import journal directory cannot be a symlink")
            missing_directories: list[Path] = []
            directory = journal_dir
            while not directory.exists():
                if directory.is_symlink():
                    raise OSError("bundle import journal path cannot be a symlink")
                missing_directories.append(directory)
                parent = directory.parent
                if parent == directory:
                    break
                directory = parent
            journal_dir.mkdir(parents=True, exist_ok=True)
            for created_directory in reversed(missing_directories):
                sync_directory(created_directory.parent)
            if journal_path.exists():
                if journal_path.is_symlink() or not journal_path.is_file():
                    raise OSError("bundle import journal is not a regular file")
                if journal_path.stat().st_size > 16_384:
                    raise OSError("existing bundle import journal exceeds its metadata limit")
                manifest = json.loads(journal_path.read_text(encoding="utf-8"))
                if (
                    not isinstance(manifest, dict)
                    or manifest.get("import_id") != import_id
                    or manifest.get("bundle_sha256") != bundle_sha256
                    or manifest.get("target_root") != normalized_root
                    or manifest.get("schema_version") != 1
                    or manifest.get("status") not in {"staging", "incomplete", "complete"}
                    or not isinstance(manifest.get("completed_phases"), list)
                ):
                    raise OSError("existing bundle import journal does not match this payload")
                if payload_path.is_symlink() or not payload_path.is_file():
                    raise OSError("existing bundle import staged payload is unavailable")
                if payload_path.stat().st_size > max_bundle:
                    raise OSError("existing bundle import staged payload exceeds the configured limit")
                if hashlib.sha256(payload_path.read_bytes()).hexdigest() != bundle_sha256:
                    raise OSError("existing bundle import staged payload failed its integrity check")
                return manifest
            manifest = {
                "schema_version": 1,
                "import_id": import_id,
                "bundle_sha256": bundle_sha256,
                "target_root": normalized_root,
                "status": "staging",
                "completed_phases": [],
                "updated_at": time.time(),
            }
            atomic_write(journal_path, json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
            atomic_write(payload_path, raw_bundle)
            manifest["status"] = "incomplete"
            manifest["updated_at"] = time.time()
            atomic_write(journal_path, json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
            return manifest

        def staging_failure(root_path: str | None, exc: Exception) -> dict[str, Any]:
            recovery_pending = False
            try:
                normalized_root = str(Path(root_path).resolve(strict=False)).replace("\\", "/") if root_path else None
                import_id = hashlib.sha256(f"{bundle_sha256}\0{normalized_root or ''}".encode("utf-8")).hexdigest()
                journal_dir = Path(self.config["server"]["state_dir"]) / "bundle-imports"
                if journal_dir.is_symlink():
                    recovery_pending = True
                elif journal_dir.is_dir():
                    journal_path = journal_dir / f"{import_id}.json"
                    payload_path = journal_dir / f"{import_id}.bundle"
                    recovery_pending = any(
                        path.exists() or path.is_symlink()
                        for path in (journal_path, payload_path)
                    )
            except Exception:
                recovery_pending = True
            return {
                "success": False,
                "status": "incomplete" if recovery_pending else "not_started",
                "degraded": recovery_pending,
                "recovery_pending": recovery_pending,
                "error": f"bundle import could not be staged: {type(exc).__name__}: {exc}",
            }

        def mark_import_phase(manifest: dict[str, Any], phase: str) -> None:
            phases = manifest.setdefault("completed_phases", [])
            if phase not in phases:
                phases.append(phase)
            manifest["status"] = "incomplete"
            manifest["updated_at"] = time.time()
            journal_path = Path(self.config["server"]["state_dir"]) / "bundle-imports" / f"{manifest['import_id']}.json"
            atomic_write(journal_path, json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))

        def finish_import_intent(manifest: dict[str, Any]) -> bool:
            manifest["status"] = "complete"
            manifest["updated_at"] = time.time()
            journal_dir = Path(self.config["server"]["state_dir"]) / "bundle-imports"
            journal_path = journal_dir / f"{manifest['import_id']}.json"
            payload_path = journal_dir / f"{manifest['import_id']}.bundle"
            atomic_write(journal_path, json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
            try:
                payload_path.unlink(missing_ok=True)
                journal_path.unlink(missing_ok=True)
            except OSError:
                return True
            return False

        def incomplete_result(manifest: dict[str, Any], exc: Exception) -> dict[str, Any]:
            return {
                "success": False,
                "status": "incomplete",
                "degraded": True,
                "recovery_pending": True,
                "import_id": str(manifest.get("import_id", "")),
                "error": f"bundle import incomplete; recovery is pending: {type(exc).__name__}: {exc}",
            }

        @contextmanager
        def capture_import_phase(manifest: dict[str, Any], phase: str, errors: list[Exception]):
            try:
                yield
            except Exception as exc:
                errors.append(exc)
            else:
                try:
                    mark_import_phase(manifest, phase)
                except Exception as exc:
                    errors.append(exc)
        try:
            with zipfile.ZipFile(io.BytesIO(raw_bundle), "r") as zf:
                infos = zf.infolist()
                if len(infos) != 1 or infos[0].filename != "bundle.json":
                    return {"success": False, "error": "bundle must contain exactly one bundle.json member"}
                info = infos[0]
                mode = (info.external_attr >> 16) & 0xFFFF
                file_type = stat.S_IFMT(mode)
                if stat.S_ISLNK(mode):
                    return {"success": False, "error": "bundle.json symlink members are not allowed"}
                if file_type not in {0, stat.S_IFREG}:
                    return {"success": False, "error": "bundle.json must be a regular file"}
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

        def prepare_agent_memory_records(
            records: Any,
            target_root_path: str | None = None,
            source_root_path: str | None = None,
        ) -> tuple[list[MemoryRecord] | None, str | None]:
            if not isinstance(records, list):
                return None, "bundle records are missing"
            prepared_records: list[MemoryRecord] = []
            for record_index, item in enumerate(records):
                if not isinstance(item, dict):
                    return None, "invalid agent-state bundle record"
                rtype = item.get("type")
                rdata = item.get("data", {})
                if not isinstance(rdata, dict):
                    return None, "invalid agent-state bundle payload"
                if rtype == "memory" and getattr(self, "agent_memory", None):
                    try:
                        record_data = dict(rdata)
                        scope_value = str(record_data.get("scope", "")).strip().lower()
                        provenance = record_data.get("provenance")
                        if scope_value in {"repo", "repository"}:
                            source_root = provenance.get("root") if isinstance(provenance, dict) else None
                            if not source_root:
                                return None, "repository memory provenance root is required for import"
                            if target_root_path:
                                if not source_root_path:
                                    return None, "project bundle root is required for repository memory import"
                                if _normalise_scope_root(str(source_root)) != _normalise_scope_root(source_root_path):
                                    return None, "repository memory provenance does not match bundle root"
                                imported_root = target_root_path
                            else:
                                imported_root = str(
                                    Path(str(source_root)).expanduser().resolve(strict=False)
                                ).replace("\\", "/")
                            rebased_provenance = dict(provenance)
                            rebased_provenance.setdefault("source_root", str(source_root))
                            rebased_provenance["root"] = imported_root
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
                    except (KeyError, OSError, TypeError, ValueError):
                        return None, "invalid agent-state bundle memory record"
                    if not str(record_data.get("record_id", "")).strip():
                        stable_id = uuid.uuid5(
                            uuid.NAMESPACE_URL,
                            f"{bundle_sha256}\0{target_root_path or ''}\0{record_index}",
                        )
                        rec = replace(rec, record_id=str(stable_id))
                    prepared_records.append(rec)
            return prepared_records, None

        def restore_agent_memory_records(
            records: list[MemoryRecord],
            manifest: dict[str, Any],
        ) -> None:
            for record_index, rec in enumerate(records):
                self.agent_memory.record(
                    rec,
                    actor="bundle_import",
                    idempotency_key=f"bundle-import:{manifest['import_id']}:memory:{record_index}",
                )

        if bundle_format == "local-ai-hub-agent-state-bundle":
            records = data.get("records", [])
            if not isinstance(records, list):
                return {"success": False, "error": "bundle records are missing"}
            canonical = json_dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            expected = str(data.get("records_sha256", ""))
            if not expected or not hmac.compare_digest(hashlib.sha256(canonical).hexdigest(), expected):
                return {"success": False, "error": "bundle integrity check failed"}
            prepared_records, error = prepare_agent_memory_records(records)
            if error:
                return {"success": False, "error": error}
            try:
                manifest: dict[str, Any] | None = None
                manifest = create_import_intent(None)
                restore_agent_memory_records(prepared_records or [], manifest)
                mark_import_phase(manifest, "agent_memory")
                cleanup_pending = finish_import_intent(manifest)
            except Exception as exc:
                if manifest is None:
                    return staging_failure(None, exc)
                return incomplete_result(manifest, exc)
            return {
                "success": True,
                "status": "complete",
                "recovery_pending": False,
                "cleanup_pending": cleanup_pending,
                "import_id": manifest["import_id"],
                "version": __version__,
                "restored_records": len(prepared_records or []),
            }

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
        if any(
            "embedding" in row
            and row["embedding"] is not None
            and not isinstance(row["embedding"], (str, bytes, bytearray, memoryview))
            for row in tables.get("rag_chunks", [])
        ):
            return {"success": False, "error": "invalid RAG chunk embedding"}

        orig_root = str(data.get("root", ""))
        root = str(target_root or orig_root)
        root_obj = Path(root).expanduser().resolve(strict=False) if root else None
        if root_obj is None or not root_obj.is_dir():
            return {"success": False, "error": "target repository root does not exist"}
        root_path = str(root_obj).replace("\\", "/")
        workspace = self.rag.workspace_id(root_path)
        prepared_project_agent_records: list[MemoryRecord] = []
        if has_agent_records:
            prepared, error = prepare_agent_memory_records(
                data.get("agent_state_records"), root_path, str(data.get("root", ""))
            )
            if error:
                return {"success": False, "error": error}
            prepared_project_agent_records = prepared or []
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

        try:
            manifest = create_import_intent(root_path)
        except Exception as exc:
            return staging_failure(root_path, exc)
        phase_errors: list[Exception] = []

        # Restore root-scoped preprocessor state transactionally. Derived content
        # cards are content-addressed and therefore safe to upsert globally.
        with capture_import_phase(manifest, "preprocessor", phase_errors), self.preprocessor._db_lock, closing(self.preprocessor._connect()) as con:
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
        if phase_errors:
            return incomplete_result(manifest, phase_errors[0])

        if self.deterministic is not None:
            with capture_import_phase(manifest, "deterministic", phase_errors), self.deterministic._lock, closing(self.deterministic._connect()) as con:
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
            if phase_errors:
                return incomplete_result(manifest, phase_errors[0])
        else:
            mark_import_phase(manifest, "deterministic")

        if self.rag is not None:
            scope_key = self.rag._scope_key("__preprocess__")
            with capture_import_phase(manifest, "rag", phase_errors), self.rag._index_lock, closing(self.rag._connect()) as con:
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
            if phase_errors:
                return incomplete_result(manifest, phase_errors[0])
        else:
            mark_import_phase(manifest, "rag")

        with capture_import_phase(manifest, "agent_memory", phase_errors):
            for record_index, rec in enumerate(prepared_project_agent_records):
                self.agent_memory.record(
                    rec,
                    actor="bundle_import",
                    idempotency_key=f"bundle-import:{manifest['import_id']}:memory:{record_index}",
                )
        if phase_errors:
            return incomplete_result(manifest, phase_errors[0])
        restored_agent_records = len(prepared_project_agent_records)

        try:
            cleanup_pending = finish_import_intent(manifest)
        except Exception as exc:
            return incomplete_result(manifest, exc)

        return {
            "success": True,
            "status": "complete",
            "recovery_pending": False,
            "cleanup_pending": cleanup_pending,
            "import_id": manifest["import_id"],
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
        try:
            self.services.close_lint_daemons()
        except Exception:
            pass
        try:
            self.services.close_context_warmup()
        except Exception:
            pass
        try:
            self._status_dependency_executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        # Stop helper loops before tearing down the services they periodically touch.
        # They are daemon threads as a final safety net, but bounded joins make normal
        # restart/shutdown deterministic and avoid late telemetry/preprocessor calls.
        current = threading.current_thread()
        for thread in (self._prewarm_thread, self._watchdog_thread):
            if thread is not None and thread is not current and thread.is_alive():
                thread.join(timeout=1.5)
        try:
            self.recovery.close()
        except Exception:
            pass
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
        for name in ("deterministic", "code_index"):
            try:
                component = getattr(self, name, None)
                if component is not None:
                    component.close()
            except Exception:
                pass
        try:
            shutdown_logging()
        except Exception:
            pass
