from __future__ import annotations

import sys
import types

# Keep app-module globals patchable while behavior lives in domain mixins.
# ruff: noqa: F401

from .json_utils import dumps as json_dumps

import stat
import io
import ipaddress
import json
import re
import sqlite3
import threading
import time
import traceback
import uuid
import zipfile
from contextlib import ExitStack
from concurrent.futures import CancelledError
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from . import __version__
from .artifacts import ArtifactStore
from .config import load_config
from .dashboard_updates import DashboardUpdates
from .embeddings import EmbeddingModel
from .ollama import OllamaRuntime
from .tiered_ollama import TieredOllamaRuntime
from .leases import ScopeLeaseStore
from .repo_state import RepoStateTracker
from .command_broker import CommandBroker
from .memory import WorkspaceMemoryStore
from .rag import RAGStore
from .repo_tools import RepositoryTools
from .reranker import Reranker
from .scheduler import AffinityScheduler
from .background_gpu import IdleGPUWorker
from .accelerators import accelerator_status
from .services import LocalAIServices
from .telemetry import TelemetryStore
from .endpoint_stats import EndpointStatsStore
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
from .sqlite_support import require_canonical_agent_state_database, write_transaction
from .state_lifecycle import ensure_state_version
from .external_tools import ExternalCodeIntelligence
from .async_jobs import AsyncJobManager
from .speculative_lint import SpeculativeLintQueue
from .debug_traces import DebugTraceStore
from .agent_events import AgentStateStore
from .agent_tasks import CompletionGateError, TaskStore, TaskStatus
from .laya_candidates import LayaCandidateStore
from .laya_lifecycle import DEFAULT_IDLE_UNLOAD_SECONDS, LayaSessionLifecycle
from .agent_identity import AgentScope
from .project_config import resolve_project_context
from .agent_memory import MemoryStore, MemoryRecord, MemoryStatus, _normalise_scope_root
from .agent_incidents import IncidentStore
from .agent_verification import VerificationStore
from .agent_policy import PolicyEngine
from .agent_context import ContextCompiler
from .agent_consistency import AgentConsistencyGuard
from .agent_routing import RoutingEngine
from .agent_learning import LearningStore
from .agent_blackboard import BlackboardStore
from .agent_semaphores import SemaphoreStore
from .agent_board import BoardStore
from .vram_balancer import VRAMBalancer
from .swarm import SwarmCoordinator
from .benchmark import HardwareBenchmarkRunner
from .work_orchestrator import WorkOrchestrator
from .status_executor import StatusDependencyExecutor


_LAYA_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----", re.DOTALL),
    re.compile(r"\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(
        r"\b((?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|password|passwd|secret|token|authorization|credential)\b\s*[:=]\s*)(?:(?:Bearer|Basic)\s+)?(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-(?:proj-)?[A-Za-z0-9_-]{20,})\b"),
    re.compile(r"(https?://[^/\s:@]+:)[^@\s/]+(@)", re.IGNORECASE),
)


def _laya_review_endpoint_is_loopback(value: Any) -> bool:
    """Return whether a configured HTTP endpoint has an explicitly local host."""
    if type(value) is not str or not value or len(value) > 2048:
        return False
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        # Avoid credentials, query/fragment ambiguity, non-HTTP transports, and
        # DNS names whose eventual address cannot be safely pinned here.
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or not host
            or "%" in host
        ):
            return False
        _ = parsed.port  # Validate malformed/out-of-range ports.
    except ValueError:
        return False
    if host.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _redact_laya_training_text(value: str) -> str:
    redacted = value
    for pattern in _LAYA_SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


_STATUS_DEPENDENCY_TIMEOUT_SECONDS = 0.25
_STATUS_RUNTIME_ONLINE_TIMEOUT_SECONDS = 2.0
_STATUS_TELEMETRY_SUMMARY_TIMEOUT_SECONDS = 1.0
_STATUS_OLLAMA_PROFILE_TIMEOUT_SECONDS = 1.0
_STATUS_PREPROCESSING_STATUS_TIMEOUT_SECONDS = 2.0
_STATUS_SCHEDULER_TIMEOUT_SECONDS = 1.0
_STATUS_AGENT_STATE_TIMEOUT_SECONDS = 2.0
_STATUS_RECOVERY_TIMEOUT_SECONDS = 1.0
_STATUS_MAX_WORKERS = 32
_STATUS_MAX_INFLIGHT_DEPENDENCIES = 32


def _status_dependency_timeout_seconds(key: str) -> float:
    timeout = float(_STATUS_DEPENDENCY_TIMEOUT_SECONDS)
    if key == "telemetry.summary":
        timeout = max(timeout, float(_STATUS_TELEMETRY_SUMMARY_TIMEOUT_SECONDS))
    elif key == "runtime.online":
        timeout = max(timeout, float(_STATUS_RUNTIME_ONLINE_TIMEOUT_SECONDS))
    elif key == "agent_state":
        timeout = max(timeout, float(_STATUS_AGENT_STATE_TIMEOUT_SECONDS))
    elif key == "recovery":
        timeout = max(timeout, float(_STATUS_RECOVERY_TIMEOUT_SECONDS))
    elif key == "ollama_profile":
        timeout = max(timeout, float(_STATUS_OLLAMA_PROFILE_TIMEOUT_SECONDS))
    elif key in {"preprocessing.status", "preprocessing.stats", "background_gpu"}:
        timeout = max(timeout, float(_STATUS_PREPROCESSING_STATUS_TIMEOUT_SECONDS))
    elif key == "scheduler":
        timeout = max(timeout, float(_STATUS_SCHEDULER_TIMEOUT_SECONDS))
    return max(0.0, timeout)


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


_STATUS_METADATA_CACHE_SECONDS = 15.0
_STATUS_METADATA_KEYS = frozenset(
    f"{view}:{scope}:{name}"
    for view in ("live", "full") for scope in ("process", "window")
    for name in ("telemetry.summary", "preprocessing.status")
) | frozenset({
    # These read-only counters are diagnostic and can be reused across the
    # short dashboard refresh window when their probe outlives its deadline.
    "debug_traces",
    "runtime_stats.generation_cache",
    "runtime_stats.repo_cache",
})


def _status_probe_key(view: str, scope: str, key: str) -> str:
    return f"{view}:{scope}:{key}" if key in {"telemetry.summary", "preprocessing.status"} else key


_CORE_STATUS_PROBES = frozenset({"headless", "runtime.online", "ollama_profile", "scheduler"})


def _status_probe_affects_core_health(key: str, *, healthy: bool) -> bool:
    """Only required availability probes decide overall Hub health."""
    return not healthy and key in _CORE_STATUS_PROBES


def _schedule_status_dependency(callback, fallback, *, key, lock, inflight, slots, executor, deadline, diagnostic=None, completed_cache=None):
    """Start or reuse bounded status work without waiting for its result."""
    def mark_degraded(reason, error=None):
        if diagnostic is None:
            return
        diagnostic["reason"] = reason
        if error is not None:
            diagnostic["error_type"] = type(error).__name__

    submitted = None
    refresh_entry = None
    refresh_age = 0.0
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
                if age < _STATUS_METADATA_CACHE_SECONDS / 3:
                    if diagnostic is not None:
                        diagnostic.update(dependency_cached=True, dependency_age_ms=int(age * 1000))
                    return {"entry": cached, "fallback": fallback}
                # Refresh inside the validity window. A report slower than the
                # per-probe deadline must not make every dashboard poll fail.
                refresh_entry, refresh_age = cached, age
            else:
                del completed_cache[key]
        entry = inflight.get(key)
        if entry is None:
            if not slots.acquire(blocking=False):
                if refresh_entry is not None:
                    if diagnostic is not None:
                        diagnostic.update(dependency_cached=True, dependency_age_ms=int(refresh_age * 1000), dependency_refreshing=False)
                    return {"entry": refresh_entry, "fallback": fallback}
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
    if refresh_entry is not None:
        if diagnostic is not None:
            diagnostic.update(dependency_cached=True, dependency_age_ms=int(refresh_age * 1000), dependency_refreshing=True)
        return {"entry": refresh_entry, "fallback": fallback}
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
            config = getattr(candidate, "config", {})
            llama = config.get("llama_cpp", {})
            fallback = bool(llama.get("fallback_to_ollama", True))
            if str(llama.get("mode", "auto")).strip().lower() == "off" and bool(config.get("ollama", {}).get("enabled", False)):
                continue
            if bool(supports(model)) and not bool(hardware_enabled()) and not fallback:
                return False
        except Exception:
            continue
    return True


_PREWARM_RETRYABLE_GPU_STATES = frozenset({
    "available",
    "external_reservation",
    "background_lease",
    "preparing_model",
    "inference_active",
})


def _prewarm_admission_state(scheduler: Any) -> str:
    """Return the admission reason used to decide whether startup prewarm can retry."""
    try:
        status = scheduler.status()
    except Exception:
        return "status_unavailable"
    if not isinstance(status, dict):
        return "status_unavailable"
    state = status.get("gpu_admission_state")
    if not isinstance(state, str) or not state:
        return "unknown"
    if state == "available":
        capacity_sharing_active = getattr(scheduler, "_capacity_sharing_active", None)
        if callable(capacity_sharing_active):
            try:
                if capacity_sharing_active():
                    return "capacity_sharing"
            except Exception:
                return "status_unavailable"
    return state


def _prewarm_should_retry(scheduler: Any) -> bool:
    """Retry prewarm only when scheduler admission reports a recoverable state."""
    return _prewarm_admission_state(scheduler) in _PREWARM_RETRYABLE_GPU_STATES


def _wait_for_prewarm_backend(runtime: Any, shutdown: threading.Event, max_wait_seconds: float) -> bool:
    """Let scheduler admission start an offline backend before prewarming it."""
    if not _runtime_is_available(runtime):
        ensure_running = getattr(runtime, "ensure_running", None)
        if callable(ensure_running):
            # Starting here would acquire GPU resources outside the scheduler's
            # admission fence. Runtime preparation starts it after admission.
            return not shutdown.is_set()
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


def _has_retired_bundle_tenant_field(value: Any) -> bool:
    if isinstance(value, dict):
        if any(key in value for key in (
            "tenant", "tenant_id", "tenant_identity", "tenant_partition", "tenant_scope", "tenant_key",
        )):
            return True
        # Record values and document bodies are opaque project content, not Hub
        # scope selectors. A project's own domain model may legitimately say tenant.
        return any(
            _has_retired_bundle_tenant_field(item)
            for key, item in value.items()
            if key not in {"value", "text", "content", "blob"}
        )
    if isinstance(value, list):
        return any(_has_retired_bundle_tenant_field(item) for item in value)
    return False


class BundleValidationError(ValueError):
    """Raised when bundle validation or scope verification fails."""


def _record_startup_prewarm_failure(debug_traces: Any, model: str, error: BaseException) -> str:
    """Retain startup prewarm exception details only in opt-in local traces."""
    if getattr(debug_traces, "enabled", False) is not True:
        return ""
    try:
        trace_id = debug_traces.start(
            kind="system",
            action="startup_prewarm",
            source="startup",
            model=str(model),
            initial_event=("prewarm_attempt_failed", {
                "exception_type": type(error).__name__,
                "exception_message": str(error),
                "traceback": "".join(traceback.format_exception(error)),
            }),
        )
        if trace_id:
            debug_traces.finish(trace_id, state="failed")
        return trace_id
    except Exception:
        # Diagnostics must never change startup or scheduler behavior.
        return ""


from . import app_runtime as _app_runtime
from .app_runtime import AppRuntimeMixin
from . import app_status as _app_status
from .app_status import AppStatusMixin
from . import app_bundle as _app_bundle
from .app_bundle import AppBundleMixin
from . import app_laya_runtime as _app_laya_runtime
from .app_laya_runtime import AppLayaRuntimeMixin
from . import app_laya_observation as _app_laya_observation
from .app_laya_observation import AppLayaObservationMixin
from . import app_capture as _app_capture
from .app_capture import AppCaptureMixin

class LocalAIApp(AppRuntimeMixin, AppStatusMixin, AppBundleMixin, AppLayaRuntimeMixin, AppLayaObservationMixin, AppCaptureMixin):
    vram_balancer: Any = None
    swarm: Any = None
    benchmark_runner: Any = None














































for _app_module in (_app_runtime, _app_status, _app_bundle, _app_laya_runtime, _app_laya_observation, _app_capture):
    _app_module.LocalAIApp = LocalAIApp


class _AppModuleProxy(types.ModuleType):
    def __setattr__(self, name: str, value: Any) -> None:
        super().__setattr__(name, value)
        for module in (_app_runtime, _app_status, _app_bundle, _app_laya_runtime, _app_laya_observation, _app_capture):
            if hasattr(module, name):
                setattr(module, name, value)

sys.modules[__name__].__class__ = _AppModuleProxy


__all__ = [
    'AffinityScheduler',
    'AgentConsistencyGuard',
    'AgentProjector',
    'AgentScope',
    'AgentStateStore',
    'Any',
    'AppBundleMixin',
    'AppCaptureMixin',
    'AppLayaObservationMixin',
    'AppLayaRuntimeMixin',
    'AppRuntimeMixin',
    'AppStatusMixin',
    'ArtifactStore',
    'AsyncJobManager',
    'BlackboardStore',
    'BoardStore',
    'BundleValidationError',
    'CancelledError',
    'CodeIndex',
    'CommandBroker',
    'CompletionGateError',
    'ContextCompiler',
    'DEFAULT_IDLE_UNLOAD_SECONDS',
    'DashboardUpdates',
    'DebugTraceStore',
    'DeterministicEngine',
    'EmbeddingModel',
    'EndpointStatsStore',
    'EvidenceStore',
    'ExitStack',
    'ExternalCodeIntelligence',
    'HardwareBenchmarkRunner',
    'IdleGPUWorker',
    'IncidentStore',
    'LayaCandidateStore',
    'LayaSessionLifecycle',
    'LearningStore',
    'LocalAIApp',
    'LocalAIServices',
    'LocalAgentPipeline',
    'LosslessTokenRouter',
    'Mapping',
    'MemoryRecord',
    'MemoryStatus',
    'MemoryStore',
    'OllamaRuntime',
    'Path',
    'PolicyEngine',
    'ProjectPreprocessor',
    'RAGStore',
    'RecoveryJournal',
    'RepoStateTracker',
    'RepositoryTools',
    'Reranker',
    'RoutingEngine',
    'RuntimeTuner',
    'ScopeLeaseStore',
    'SemaphoreStore',
    'SpeculativeLintQueue',
    'StatusDependencyExecutor',
    'SwarmCoordinator',
    'TaskStatus',
    'TaskStore',
    'TelemetryStore',
    'TieredOllamaRuntime',
    'ToolAwareLocalAgent',
    'UsageLearner',
    'VRAMBalancer',
    'VerificationStore',
    'WorkOrchestrator',
    'WorkspaceMemoryStore',
    '_AppModuleProxy',
    '_CORE_STATUS_PROBES',
    '_DET_TABLES',
    '_LAYA_SECRET_PATTERNS',
    '_PREPROCESS_TABLES',
    '_PREWARM_RETRYABLE_GPU_STATES',
    '_STATUS_AGENT_STATE_TIMEOUT_SECONDS',
    '_STATUS_DEPENDENCY_TIMEOUT_SECONDS',
    '_STATUS_MAX_INFLIGHT_DEPENDENCIES',
    '_STATUS_MAX_WORKERS',
    '_STATUS_METADATA_CACHE_SECONDS',
    '_STATUS_METADATA_KEYS',
    '_STATUS_OLLAMA_PROFILE_TIMEOUT_SECONDS',
    '_STATUS_PREPROCESSING_STATUS_TIMEOUT_SECONDS',
    '_STATUS_RECOVERY_TIMEOUT_SECONDS',
    '_STATUS_RUNTIME_ONLINE_TIMEOUT_SECONDS',
    '_STATUS_SCHEDULER_TIMEOUT_SECONDS',
    '_STATUS_TELEMETRY_SUMMARY_TIMEOUT_SECONDS',
    '__version__',
    '_accelerator_status_fallback',
    '_app_bundle',
    '_app_capture',
    '_app_laya_observation',
    '_app_laya_runtime',
    '_app_runtime',
    '_app_status',
    '_has_retired_bundle_tenant_field',
    '_laya_review_endpoint_is_loopback',
    '_new_status_dependency_executor',
    '_normalise_scope_root',
    '_online_probe_status',
    '_prewarm_admission_state',
    '_prewarm_route_is_eligible',
    '_prewarm_should_retry',
    '_record_startup_prewarm_failure',
    '_redact_laya_training_text',
    '_resolve_status_dependency',
    '_runtime_is_available',
    '_schedule_status_dependency',
    '_status_dependency',
    '_status_dependency_timeout_seconds',
    '_status_probe_affects_core_health',
    '_status_probe_key',
    '_wait_for_prewarm_backend',
    'accelerator_status',
    'annotations',
    'configure_logging',
    'deepcopy',
    'ensure_state_version',
    'io',
    'ipaddress',
    'json',
    'json_dumps',
    'load_config',
    're',
    'require_canonical_agent_state_database',
    'resolve_project_context',
    'shutdown_logging',
    'sqlite3',
    'stat',
    'sys',
    'threading',
    'time',
    'traceback',
    'types',
    'urlsplit',
    'uuid',
    'write_transaction',
    'zipfile',
]
