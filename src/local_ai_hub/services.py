from __future__ import annotations

# Retain module globals as monkeypatch targets for service mixins.
# ruff: noqa: F401

from .json_utils import dumps as json_dumps

import copy
import hashlib
import json
import keyword
import logging
import math
import os
import stat
import re
import shlex
import shutil
import sqlite3
import subprocess
import time
import threading
import sys
import types
from collections.abc import Sequence
from concurrent.futures import wait as wait
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any, Mapping

from . import __version__
from .artifacts import ArtifactStore
from .budget import estimate_tokens, fit_text
from .cache import MemoryLRUCache, SQLiteCache, TieredCache, SingleFlightCache, SingleFlightGroup, stable_hash
from .conversations import ConversationStore
from .repository_scope import reject_retired_tenancy_fields
from .features import rollout_feature_enabled
from .normalizer import normalize_query, postprocess_model_output
from .semantic_cache import SemanticGenerationCache
from .model_policy import ModelExecutionPolicy
from .ollama_subagents import OllamaSubagentCatalog
from .process_utils import canonical_root
from .retrieval import fuse_ranked_paths
from .repo_tools import RepositoryTools
from .search_pagination import MAX_PAGE_SIZE, MAX_PAGE_WINDOW, pagination_bounds_error
from .scheduler import SchedulerCancelledError, SchedulerTimeoutError
from .router import ModelRouter, review_diff_complexity
from .evidence_merge import (
    merge_overlapping_evidence as _merge_overlapping_evidence,
    merge_overlapping_line_ranges as _merge_overlapping_line_ranges,
)
from .sqlite_support import connect_sqlite
from .adoption_metrics import AdoptionMetricsStore
from .state_paths import configured_state_dir
from .speculative_lint import apply_path_coverage, normalize_changed_paths
from .lint_daemon import RuffDaemonPool, OwnedBiomeDaemonPool
from .async_jobs import capture_job_cancellation, current_job_should_stop
from .telemetry import TelemetryStore

logger = logging.getLogger(__name__)
from .agent_consistency import ConsistencyRequest, GuardWarning
from .agent_context import ContextCompiler, ContextRequest
from .agent_events import AgentStateStore
from .semantic_quality import assess_semantic_result
from .prompt_contracts import build_prompt


from .service_repo_search import (
    _SOURCE_FOCUS_TERMS as _SOURCE_FOCUS_TERMS,
    _SOURCE_SUFFIXES as _SOURCE_SUFFIXES,
    _context_path_priority as _context_path_priority,
    _rag_fragment_matches_source as _rag_fragment_matches_source,
    _source_focused_query as _source_focused_query,
    enclosing_symbol_at_line as enclosing_symbol_at_line,
)


from .service_cancellation import _LinkedCancelEvent


from . import service_hybrid_context as _service_hybrid_context
from .service_hybrid_context import _CONTEXT_BACKEND_POOLS as _CONTEXT_BACKEND_POOLS


def _safe_int(val: Any, default: int, min_val: int | None = None, max_val: int | None = None) -> int:
    if isinstance(val, bool) or val is None:
        return default
    try:
        if isinstance(val, float) and not math.isfinite(val):
            return default
        res = int(val)
    except (ValueError, TypeError, OverflowError):
        return default
    if min_val is not None and res < min_val:
        return min_val
    if max_val is not None and res > max_val:
        return max_val
    return res


def _safe_float(val: Any, default: float, min_val: float | None = None, max_val: float | None = None) -> float:
    if isinstance(val, bool) or val is None:
        return default
    try:
        res = float(val)
        if not math.isfinite(res):
            return default
    except (ValueError, TypeError, OverflowError):
        return default
    if min_val is not None and res < min_val:
        return min_val
    if max_val is not None and res > max_val:
        return max_val
    return res


def is_retryable_local_backend_error(value: Any) -> bool:
    """Recognize transport/runtime failures that must keep async work retryable."""
    if getattr(value, "retryable", None) is True:
        return True
    text = str(value or "").lower()
    return any(marker in text for marker in (
        "winerror 10054", "winerror 10061", "connection reset", "connection refused",
        "connection aborted", "broken pipe", "temporarily unavailable", "ollama unavailable",
        "timed out", "timeout", "eof", "queue limit reached", "queue full", "resource pressure",
    ))


def _generation_cache_dispatch(cache: Any, key: str, compute: Any, compute_inner: Any, *,
                               use_cache: bool, request_cancel_event: threading.Event | None) -> tuple[Any, bool, bool]:
    # Cancellation belongs to one request, so its in-flight computation must never
    # become the shared leader for another caller.
    if use_cache and request_cancel_event is None:
        return cache.get_or_compute(key, compute)
    return compute_inner(), False, False


def normalize_generation_cache_prompt(prompt: str) -> str:
    """Normalize only transport-level line endings for exact prompt reuse."""
    return str(prompt).replace("\r\n", "\n").replace("\r", "\n")


def cache_decision_reason(cache_layer: str, *, semantic_query: str, semantic_miss_reason: str = "") -> str:
    layer = str(cache_layer or "").strip().lower()
    query = str(semantic_query or "").strip()
    if layer == "semantic":
        return "semantic_reuse"
    if layer == "single-flight":
        return "singleflight_reuse"
    if layer == "stale-on-error":
        return "stale_on_error"
    if layer == "ollama" and query:
        reason = str(semantic_miss_reason or "").strip().lower()
        if reason and all(char.isalnum() or char == "_" for char in reason):
            return f"semantic_miss_{reason}"
        return "semantic_not_reused"
    if layer == "ollama":
        return "new_exact_key"
    return "exact_reuse"


# enclosing_symbol_at_line re-exported above


from .service_review_diff import (
    _MAX_REVIEW_DIFF_CHUNKS,
    _REVIEW_DIFF_CONTEXT_FRACTION,
    _REVIEW_DIFF_MIN_CHUNK_TOKENS,
    _REVIEW_SYNTHESIS_CONTEXT_TOKENS,
    _merge_review_segment_results,
    _review_failure_details,
    _review_model_identity,
    _review_text_error,
    _split_review_diff,
)
_GUARD_REASON_SECRET_RE = re.compile(
    r"(?i)\b((?:token|api[-_]?key|access[-_]?token|refresh[-_]?token|auth(?:orization)?|bearer|secret|password|passwd|credential|cookie|private[-_]?key)\b\s*[:=]\s*)(?!Bearer\b)([\"']?)([^\"'\s,;]+)\2"
)
_GUARD_REASON_PROMPT_RE = re.compile(r"(?is)\b(?:system\s+|user\s+)?(?:prompt|instructions?)\s*[:=].*$")


def _redact_guard_reason(reason: Any) -> str:
    """Keep a short operator reason without persisting secret or prompt content."""
    text = str(reason or "").replace("\x00", "").strip()
    if not text:
        return ""
    text = re.sub(r"(?i)\bBearer\s+\S+", "Bearer [REDACTED]", text)
    text = _GUARD_REASON_SECRET_RE.sub(lambda match: f"{match.group(1)}[REDACTED]", text)
    text = _GUARD_REASON_PROMPT_RE.sub("prompt: [REDACTED]", text)
    return text[:500]


def generation_cache_key(
    *,
    model: str,
    prompt: str,
    system: str,
    options: dict[str, Any],
    think: Any,
    execution: Any,
    format: Any = None,
    repository_revision: str = "",
    phase: str = "",
    memory_revision: str = "",
    focus: Any = None,
    preload_profile: str = "",
    project_config_digest: str = "",
    project_namespace: str = "",
) -> str:
    key_data = {
        "model": model,
        "prompt": normalize_generation_cache_prompt(prompt),
        "system": normalize_generation_cache_prompt(system),
        "options": options,
        "think": think,
        "execution": execution,
        "format": format,
        "repository_revision": repository_revision,
        "phase": phase,
        "memory_revision": memory_revision,
        "focus": focus,
        "preload_profile": preload_profile,
        "app_version": __version__,
    }
    if project_config_digest or project_namespace:
        key_data["project_config_digest"] = project_config_digest
        key_data["project_namespace"] = project_namespace
    return stable_hash(key_data)


def normalize_context_for_hash(context: str) -> str:
    """Strip variable whitespace from context to ensure identical code/evidence matches fingerprint."""
    raw = str(context).replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    return "\n".join(lines)
from .resilience import CircuitBreakerRegistry

_GLOBAL_VRAM_LOCK = threading.RLock()


@contextmanager
def vram_priority(is_generation: bool = True):
    """Global lock to serialize heavy batch operations and prioritize LLM inference against VRAM thrashing."""
    with _GLOBAL_VRAM_LOCK:
        yield


def _active_sqlite_databases(state_dir: Path) -> list[Path]:
    legacy_names = {"agent_state.sqlite3", "cache.sqlite3", "leases.sqlite3", "agent_blackboard.sqlite3"}
    recovery_markers = (".path-migration-", ".schema-mismatch-", ".corrupt-")
    return sorted(
        db
        for pattern in ("*.sqlite", "*.sqlite3")
        for db in state_dir.glob(pattern)
        if db.name not in legacy_names and not any(marker in db.name for marker in recovery_markers)
    )


def merge_overlapping_line_ranges(
    ranges: list[tuple[int, int]], *, max_gap: int = 1
) -> list[tuple[int, int]]:
    return _merge_overlapping_line_ranges(ranges, max_gap=max_gap)


def merge_overlapping_evidence(
    evidence: list[dict[str, Any]], root: str | Path | None = None
) -> list[dict[str, Any]]:
    return _merge_overlapping_evidence(evidence, root=root)


# _SOURCE_FOCUS_TERMS / _context_path_priority re-exported above


def _backend_completion_metadata(response: Mapping[str, Any]) -> dict[str, bool]:
    """Propagate backend completion only from an explicit terminal marker."""
    return {"_lah_backend_completed": True} if (
        response.get("done") is True or response.get("_lah_backend_completed") is True
    ) else {}


from . import service_generation as _service_generation
from .service_generation import ServiceGenerationMixin
from . import service_delegation as _service_delegation
from .service_delegation import ServiceDelegationMixin
from . import service_repository as _service_repository
from .service_repository import ServiceRepositoryMixin
from . import service_coordination as _service_coordination
from .service_coordination import ServiceCoordinationMixin
from . import service_context as _service_context
from .service_context import ServiceContextMixin
from . import service_review as _service_review
from .service_review import ServiceReviewMixin
from . import service_commands as _service_commands
from .service_commands import ServiceCommandMixin

class LocalAIServices(ServiceGenerationMixin, ServiceDelegationMixin, ServiceRepositoryMixin, ServiceCoordinationMixin, ServiceContextMixin, ServiceReviewMixin, ServiceCommandMixin):
    commands: Any = None
    task_store: Any = None
    verification_store: Any = None
    incident_store: Any = None
    adoption_metrics: Any = None
    rag: Any = None
    token_router: Any = None
    pipeline: Any = None
    preprocessor: Any = None
    tool_agent: Any = None
    blackboard: Any = None
    agent_state: Any = None
    semaphores: Any = None
    _VISION_MAX_OUTPUT_TOKENS = 4096
    consistency_guard: Any = None
    _adaptive_relevance_backoff_init_lock = threading.Lock()
    _ADAPTIVE_RELEVANCE_QUEUE_BACKOFF_SECONDS = 5.0
    _ADAPTIVE_RELEVANCE_TIMEOUT_BACKOFF_SECONDS = 30.0

    def _adaptive_relevance_queue_state(self) -> dict[str, Any]:
        state = getattr(self, "_adaptive_relevance_queue_backoff", None)
        if isinstance(state, dict):
            return state
        with self._adaptive_relevance_backoff_init_lock:
            state = getattr(self, "_adaptive_relevance_queue_backoff", None)
            if not isinstance(state, dict):
                state = {"lock": threading.Lock(), "until": 0.0, "reason": "backend_queue_full"}
                self._adaptive_relevance_queue_backoff = state
        return state

    @staticmethod
    def merge_overlapping_evidence(evidence: list[dict[str, Any]], root: str | Path | None = None) -> list[dict[str, Any]]:
        return merge_overlapping_evidence(evidence, root=root)

    def __init__(
        self,
        config: dict[str, Any],
        runtime: Any,
        scheduler: Any,
        embeddings: Any,
        artifacts: ArtifactStore,
        telemetry: TelemetryStore,
        repo_tools: RepositoryTools,
        repo_state: Any | None = None,
        code_index: Any | None = None,
        evidence: Any | None = None,
        learner: Any | None = None,
        tuner: Any | None = None,
        deterministic: Any | None = None,
        external_tools: Any | None = None,
    ):
        self.config = config
        self.runtime = runtime
        self.scheduler = scheduler
        self.embeddings = embeddings
        self.artifacts = artifacts
        self.telemetry = telemetry
        self.repo_tools = repo_tools
        if repo_state is None:
            from .repo_state import RepoStateTracker
            repo_state = RepoStateTracker(config)
        self.repo_state = repo_state
        self.code_index = code_index
        self.evidence_store = evidence
        self.learner = learner
        self.tuner = tuner
        self.deterministic = deterministic
        self.external_tools = external_tools
        self.commands: Any | None = None
        lint_config = config.get("speculative_lint", {})
        self._lint_daemons = RuffDaemonPool(
            max_sessions=lint_config.get("max_daemon_sessions", 4),
            idle_ttl=lint_config.get("daemon_idle_ttl_seconds", 300),
        )
        self._biome_daemons = OwnedBiomeDaemonPool(
            max_sessions=lint_config.get("max_daemon_sessions", 4),
            idle_ttl=lint_config.get("daemon_idle_ttl_seconds", 300),
        )
        self.task_store: Any | None = None
        self.laya_decision_evaluator: Any | None = None
        self.verification_store: Any | None = None
        self.incident_store: Any | None = None
        self.adoption_metrics = AdoptionMetricsStore(configured_state_dir(config))
        self.router = ModelRouter(config)
        self.model_policy = ModelExecutionPolicy(config)
        self.profile_catalog = OllamaSubagentCatalog(config)
        self.rag: Any | None = None
        self.token_router: Any | None = None
        self.pipeline: Any | None = None
        self.preprocessor: Any | None = None
        self.tool_agent: Any | None = None
        self.swarm: Any | None = None
        self.blackboard: Any | None = None
        self.agent_state: Any | None = None
        self.consistency_guard: Any | None = None
        self.flight_group = SingleFlightGroup(shards=32, default_timeout_seconds=60.0)

        cache_cfg = config.get("cache", {})
        persistent = SQLiteCache(
            Path(config["server"]["state_dir"]) / "cache.sqlite",
            namespace="generation",
            ttl_seconds=int(cache_cfg.get("generation_ttl_seconds", 7 * 86400)),
            max_entries=int(cache_cfg.get("generation_max_entries", 5000)),
        )
        generation_tier = TieredCache(
            persistent,
            l1_entries=int(cache_cfg.get("l1_generation_entries", 512)),
            l1_ttl_seconds=int(cache_cfg.get("l1_generation_ttl_seconds", 1800)),
        )
        self.generation_cache = SingleFlightCache(generation_tier, enabled=bool(cache_cfg.get("generation", True)), wait_timeout_seconds=float(config.get("resilience", {}).get("singleflight_wait_timeout_seconds", 45)))
        embedding_cache = SQLiteCache(
            Path(config["server"]["state_dir"]) / "cache.sqlite",
            namespace="embeddings",
            ttl_seconds=int(cache_cfg.get("embedding_ttl_seconds", 30 * 86400)),
            max_entries=int(cache_cfg.get("embedding_max_entries", 100000)),
        )
        self.embedding_cache = TieredCache(
            embedding_cache,
            l1_entries=int(cache_cfg.get("l1_embedding_entries", 16384)),
            l1_ttl_seconds=int(cache_cfg.get("l1_embedding_ttl_seconds", 7200)),
        )
        self.embedding_cache_enabled = bool(cache_cfg.get("embeddings", True))
        workspace_cfg = config.get("workspace_cache", {})
        self.repo_cache = TieredCache(
            SQLiteCache(
                Path(config["server"]["state_dir"]) / "cache.sqlite",
                namespace="repo-results",
                ttl_seconds=int(workspace_cfg.get("repo_result_ttl_seconds", 7 * 86400)),
                max_entries=int(workspace_cfg.get("repo_result_max_entries", 20000)),
            ),
            l1_entries=int(cache_cfg.get("l1_repo_entries", 512)),
            l1_ttl_seconds=int(cache_cfg.get("l1_repo_ttl_seconds", 900)),
        )
        self.repo_flight = SingleFlightCache(self.repo_cache, enabled=True, wait_timeout_seconds=float(config.get("resilience", {}).get("singleflight_wait_timeout_seconds", 45)))
        from .context_warmup import ContextWarmup
        self._context_warmup = ContextWarmup()
        self.semantic_cache = SemanticGenerationCache(config, embeddings)
        resilience = config.get("resilience", {})
        self.breakers = CircuitBreakerRegistry(
            failure_threshold=int(resilience.get("circuit_failure_threshold", 3)),
            cooldown_seconds=float(resilience.get("circuit_cooldown_seconds", 20)),
        )
        self.stale_generation_cache = SQLiteCache(
            Path(config["server"]["state_dir"]) / "cache.sqlite",
            namespace="generation-stale",
            ttl_seconds=int(resilience.get("stale_generation_ttl_seconds", 30 * 86400)),
            max_entries=int(resilience.get("stale_generation_max_entries", 10000)),
        )
        self._recent_focus_symbols: dict[tuple[str, str], list[str]] = {}
        self._focus_lock = threading.Lock()
        self._vram_model_lock = threading.RLock()
        self.fallback_count = 0
        self._semantic_lock_guard = threading.Lock()
        self._semantic_scope_locks: dict[str, threading.Lock] = {}
        self._index_refresh_lock = threading.Lock()
        self._index_refresh_state: dict[str, str] = {}
        self._query_expansion_l1 = MemoryLRUCache(1024, ttl_seconds=3600)
        conversation_cfg = config.get("model_conversations", {})
        self.conversations = ConversationStore(
            idle_ttl_seconds=float(conversation_cfg.get("idle_ttl_seconds", 900)),
            max_turns=int(conversation_cfg.get("max_turns", 12)),
            max_conversations=int(conversation_cfg.get("max_conversations", 1000)),
        )

    def set_rag(self, rag: Any) -> None:
        self.rag = rag

    @contextmanager
    def vram_priority(self, is_generation: bool = True):
        """Acquire lock to serialize heavy batch operations and prioritize LLM inference against VRAM thrashing."""
        with self._vram_model_lock:
            yield

    def set_commands(self, commands: Any) -> None:
        self.commands = commands

    def set_task_store(self, task_store: Any) -> None:
        self.task_store = task_store

    def set_laya_decision_evaluator(self, evaluator: Any) -> None:
        if evaluator is not None and not callable(evaluator):
            raise TypeError("Laya decision evaluator must be callable")
        self.laya_decision_evaluator = evaluator

    def evaluate_laya_advisory(
        self, operation: Mapping[str, Any], *, root: str, baseline: Mapping[str, str],
    ) -> str | None:
        """Return a validated active advisory choice; unavailable paths use deterministic routing."""
        cfg = self.config.get("laya", {})
        if not isinstance(cfg, Mapping) or cfg.get("enabled") is not True:
            return None
        runtime_cfg = cfg.get("runtime", {})
        if not isinstance(runtime_cfg, Mapping):
            return None
        checkpoint = runtime_cfg.get("checkpoint_path")
        if isinstance(checkpoint, str) and checkpoint:
            revision = runtime_cfg.get("revision")
            hashes = runtime_cfg.get("expected_sha256")
            checkpoint_configured = (
                Path(checkpoint).is_absolute()
                and Path(checkpoint).is_dir()
                and isinstance(revision, str)
                and bool(revision)
                and isinstance(hashes, Mapping)
                and bool(hashes)
            )
        else:
            repo_id = runtime_cfg.get("hf_repo_id")
            revision = runtime_cfg.get("hf_revision")
            hashes = runtime_cfg.get("hf_sha256")
            # Only admit a pinned allowlisted config here; checkpoint resolution below the evaluator
            # handles cache lookup, download consent, and file hash verification.
            from .trained_models import TRAINED_MODEL_FILES

            checkpoint_configured = (
                isinstance(repo_id, str)
                and repo_id in TRAINED_MODEL_FILES
                and isinstance(revision, str)
                and re.fullmatch(r"[0-9a-f]{40}", revision) is not None
                and isinstance(hashes, Mapping)
                and bool(hashes)
            )
        if not checkpoint_configured:
            return None
        evaluator = getattr(self, "laya_decision_evaluator", None)
        if not callable(evaluator):
            return None
        try:
            result = evaluator(operation, root=root, _server_baseline=baseline)
        except Exception as exc:
            logger.debug("Laya advisory unavailable: %s", type(exc).__name__)
            return None
        decision = result.get("decision") if isinstance(result, Mapping) else None
        data = operation.get("decision") if isinstance(operation, Mapping) else None
        options = data.get("options") if isinstance(data, Mapping) else None
        suggestion = decision.get("suggestion") if isinstance(decision, Mapping) else None
        if (
            not isinstance(result, Mapping)
            or result.get("success") is not True
            or not isinstance(decision, Mapping)
            or decision.get("mode") != "advisory"
            or decision.get("status") != "success"
            or not isinstance(options, list)
            or suggestion not in options
        ):
            return None
        return suggestion

    def set_verification_store(self, verification_store: Any) -> None:
        self.verification_store = verification_store

    def set_incident_store(self, incident_store: Any) -> None:
        self.incident_store = incident_store

    def set_token_router(self, token_router: Any) -> None:
        self.token_router = token_router

    def set_pipeline(self, pipeline: Any) -> None:
        self.pipeline = pipeline

    def set_preprocessor(self, preprocessor: Any) -> None:
        self.preprocessor = preprocessor

    def set_tool_agent(self, tool_agent: Any) -> None:
        self.tool_agent = tool_agent

    def set_blackboard(self, blackboard: Any) -> None:
        self.blackboard = blackboard

    def set_swarm(self, swarm: Any) -> None:
        self.swarm = swarm

    def set_vram_balancer(self, vram_balancer: Any) -> None:
        self.vram_balancer = vram_balancer

    def set_agent_state(self, store: Any) -> None:
        self.agent_state = store
        from .agent_events import SwarmPubSub
        SwarmPubSub.get_default(state_store=store)

    def set_consistency_guard(self, guard: Any) -> None:
        self.consistency_guard = guard

    def set_semaphores(self, semaphores: Any) -> None:
        self.semaphores = semaphores

    @staticmethod
    def _guard_truthy(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        return str(value or "").strip().lower() not in {"", "0", "false", "no", "off", "none"}

    def _guard_decision(self, request: ConsistencyRequest, revision: str, *, reason: str = "", approval: Any = "") -> tuple[bool, bool]:
        """Persist bounded operator decisions through the guard's existing memory store."""
        reason_text = str(reason or "").strip()
        if not reason_text and not self._guard_truthy(approval):
            return False, False
        store = getattr(self.consistency_guard, "memory_store", None)
        if store is None or not callable(getattr(store, "record", None)):
            return True, False
        state_store = getattr(store, "state_store", None)
        if state_store is not None and getattr(state_store, "enabled", True) is False:
            return True, False
        if getattr(store, "enabled", True) is False:
            return True, False
        try:
            token = hashlib.sha256(
                f"{request.root}:{request.task_id}:{request.phase}:{revision}:{reason_text}:{approval}".encode("utf-8", "replace")
            ).hexdigest()[:16]
            recorder = getattr(self.consistency_guard, "record_decision", None)
            if not callable(recorder):
                return True, False
            saved = recorder(
                request, decision="override", reason=_redact_guard_reason(reason_text),
                approved=self._guard_truthy(approval),
                repository_revision=revision,
                path_refs=tuple(request.changed_paths), stable_key=f"consistency_decision:{token}",
            )
            return True, saved is not None and saved is not False
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("Consistency decision persistence unavailable (%s)", type(exc).__name__)
            return True, False
        except Exception as exc:
            logger.error("Unexpected consistency decision failure (%s)", type(exc).__name__)
            return True, False

    def _guard_existing_approval(self, request: ConsistencyRequest) -> bool:
        store = getattr(self.consistency_guard, "memory_store", None)
        finder = getattr(store, "find", None)
        if not callable(finder) or not request.task_id:
            return False
        try:
            from .agent_identity import AgentScope
            from .agent_memory import MemoryStatus
            from .project_config import resolve_project_context

            project = resolve_project_context(request.root, configured_state_dir(self.config, create=False))
            repository_id = project.coordination_id
            if (
                not isinstance(repository_id, str) or not repository_id
                or repository_id != repository_id.strip() or "\x00" in repository_id
            ):
                return False
            records = finder(
                root=request.root, repository_id=repository_id,
                scope=AgentScope.REPOSITORY, scope_id=repository_id,
                status=MemoryStatus.CONFIRMED,
                limit=12, semantic=False,
            )
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("Consistency approval lookup unavailable (%s)", type(exc).__name__)
            return False
        except Exception as exc:
            logger.error("Unexpected consistency approval lookup failure (%s)", type(exc).__name__)
            return False
        for record in records or ():
            kind = getattr(getattr(record, "kind", None), "value", getattr(record, "kind", ""))
            scope = getattr(getattr(record, "scope", None), "value", getattr(record, "scope", ""))
            status = getattr(getattr(record, "status", None), "value", getattr(record, "status", ""))
            value = getattr(record, "value", {})
            provenance = getattr(record, "provenance", {}) or {}
            if (
                kind != "decision" or scope != "repository" or status != "confirmed"
                or getattr(record, "scope_id", None) != repository_id
                or not isinstance(provenance, dict)
                or provenance.get("repository_id") != repository_id
                or provenance.get("related_task") != request.task_id
            ):
                continue
            if isinstance(value, dict) and value.get("approved") is True:
                return True
        return False

    def preflight_guard_task_state(self, request: ConsistencyRequest) -> dict[str, Any] | None:
        """Reject unavailable guarded task state before repository retrieval starts."""
        store = getattr(self.consistency_guard, "task_store", None)
        getter = getattr(store, "get", None)
        if store is None or not callable(getter):
            return {
                "status_code": 503,
                "success": False,
                "terminal": False,
                "retryable": True,
                "stop_code": "context_task_state_unavailable",
                "error": "context task state store unavailable",
            }
        try:
            state = getter(request.task_id)
        except Exception as exc:
            return {
                "status_code": 503,
                "success": False,
                "terminal": False,
                "retryable": True,
                "stop_code": "context_task_state_unavailable",
                "error": f"context task state unavailable: {type(exc).__name__}",
            }
        if state is None:
            return {
                "status_code": 404,
                "success": False,
                "terminal": True,
                "retryable": False,
                "stop_code": "context_task_state_missing",
                "error": "context task does not exist",
            }
        return None

    def _guard_task_state(self, request: ConsistencyRequest, warnings: tuple[GuardWarning, ...], revision: str) -> tuple[str, bool]:
        store = getattr(self.consistency_guard, "task_store", None)
        if store is None or not request.task_id or not callable(getattr(store, "get", None)):
            return "", False
        try:
            state = store.get(request.task_id)
        except Exception as exc:
            raise RuntimeError("context task state could not be read") from exc
        if state is None:
            raise RuntimeError("context task state is missing")
        status = getattr(getattr(state, "status", None), "value", getattr(state, "status", ""))
        boundary = tuple(item for item in warnings if item.requires_approval or item.severity.lower() in {"boundary", "high", "high-risk"})
        checkpoint_data = getattr(getattr(state, "checkpoint", None), "state_data", {}) or {}
        checkpoint_approval = checkpoint_data.get("approval") or checkpoint_data.get("approved") or checkpoint_data.get("coordinator_decision")
        approved = self._guard_truthy(request.approval) or self._guard_existing_approval(request) or self._guard_truthy(checkpoint_approval)
        if boundary and not approved and status == "active":
            warning_ids = tuple(dict.fromkeys(evidence_id for item in boundary for evidence_id in item.evidence_ids))[:24]
            try:
                from .agent_tasks import TaskCheckpoint, TaskStatus

                store.transition(
                    request.task_id,
                    TaskStatus.WAITING,
                    reason="consistency guard boundary warning",
                    actor="consistency_guard",
                    idempotency_key=f"guard-wait:{request.task_id}:{revision}",
                )
                store.checkpoint(
                    request.task_id,
                    TaskCheckpoint(
                        phase=request.phase,
                        next_action=boundary[0].recommended_action or "obtain approval before continuing",
                        affected_paths=tuple(request.changed_paths),
                        evidence_ids=warning_ids,
                        blockers=tuple(item.code for item in boundary)[:24],
                        state_data={"warning_ids": list(warning_ids), "repository_revision": revision},
                    ),
                    actor="consistency_guard",
                    idempotency_key=f"guard-checkpoint:{request.task_id}:{revision}",
                )
            except Exception as exc:
                raise RuntimeError("context guard checkpoint could not be persisted") from exc
        elif approved and status == "waiting":
            try:
                store.resume(request.task_id, actor="consistency_guard", idempotency_key=f"guard-resume:{request.task_id}:{revision}")
            except Exception as exc:
                raise RuntimeError("context guard resume could not be persisted") from exc
        try:
            refreshed = store.get(request.task_id)
            refreshed_status = getattr(getattr(refreshed, "status", None), "value", getattr(refreshed, "status", ""))
            refreshed_status = str(refreshed_status)
            return refreshed_status, bool(refreshed_status.lower() == "waiting" or (boundary and not approved))
        except Exception as exc:
            raise RuntimeError("refreshed context task state could not be read") from exc

    def _guard_stop_code(self, request: ConsistencyRequest, boundary: bool) -> str:
        """Return terminal stop code when high-risk delivery lacks Agent OS state."""
        if not boundary:
            return ""
        if not request.task_id:
            return "guard_task_id_required"
        agent_state = getattr(self, "agent_state", None)
        if agent_state is not None and getattr(agent_state, "enabled", True) is False:
            return "agent_os_disabled"
        store = getattr(self.consistency_guard, "task_store", None)
        if store is None or getattr(store, "enabled", True) is False:
            return "agent_os_disabled"
        state_store = getattr(store, "state_store", None)
        if state_store is not None and getattr(state_store, "enabled", True) is False:
            return "agent_os_disabled"
        getter = getattr(store, "get", None)
        if not callable(getter):
            return "guard_task_state_unavailable"
        try:
            if getter(request.task_id) is None:
                return "guard_task_state_unavailable"
        except Exception:
            return "guard_task_state_unavailable"
        return ""

    def _touch_project(self, root: str) -> None:
        # Local AI: repository reads refresh only explicitly registered projects.
        if self.preprocessor is not None:
            self.preprocessor.touch_if_registered(root)

    def _repo_cache_state(self, root: str) -> dict[str, Any]:
        """Prefer watcher-backed preprocessing state over spawning Git on hot reads."""
        if self.preprocessor is not None:
            fast = self.preprocessor.cache_fingerprint(root)
            if isinstance(fast, dict) and fast.get("fingerprint"):
                return fast
        tracker = getattr(self, "repo_state", None)
        if tracker is not None and hasattr(tracker, "fingerprint"):
            return tracker.fingerprint(root)
        return {}

    def _resident_optimize(self, route: dict[str, Any], task_type_override: str, complexity_override: str) -> dict[str, Any]:
        cfg = self.config.get("routing", {})
        if not cfg.get("prefer_resident_model", True):
            return route
        try:
            active = self.scheduler.status().get("active_model")
        except Exception:
            active = None
        if not active:
            return route

        models = self.config["models"]
        desired = route["model"]
        reason = None
        resident_execution_role = None
        if route["task_type"] in {"code", "review"}:
            if desired == models.get("fast_code") and active == models.get("heavy_code"):
                # Heavy meets the fast tier quality gate. Once benchmark history exists,
                # keep it resident only when that is actually expected to be faster.
                tuner_ready = bool(self.tuner is not None and self.tuner.ready(str(desired), str(active)))
                if tuner_ready and self.tuner.prefer_resident(str(desired), str(active)):
                    desired = active
                    reason = "resident-heavy-substitutes-fast-autotuned"
            elif desired == models.get("heavy_code") and active == models.get("fast_code"):
                margin = int(cfg.get("resident_fast_margin", 1))
                threshold = int(cfg.get("heavy_min_score", 3))
                # Do not override an explicit heavy request. Only collapse borderline auto-routing.
                borderline = complexity_override == "auto" and route.get("complexity_score", 0) < threshold + margin
                if borderline:
                    tuner_ready = bool(self.tuner is not None and self.tuner.ready(str(desired), str(active)))
                    if tuner_ready and self.tuner.prefer_resident(str(desired), str(active)):
                        desired = active
                        reason = "resident-fast-borderline-heavy-autotuned"
        elif (
            route["task_type"] == "reasoning"
            and cfg.get("reasoning_resident_fallback", False)
            and task_type_override == "auto"
            and active in {models.get("heavy_code"), models.get("fast_code")}
        ):
            desired = active
            reason = (
                "resident-heavy-reasoning-fallback"
                if active == models.get("heavy_code")
                else "resident-fast-reasoning-fallback"
            )
            if active == models.get("fast_code"):
                resident_execution_role = "fast_code"

        if desired != route["model"]:
            route = dict(route)
            route["original_model"] = route["model"]
            route["model"] = desired
            route["resident_optimization"] = reason
            if resident_execution_role is not None:
                route["resident_execution_role"] = resident_execution_role
        return route

    def _fallback_models(self, requested: str) -> list[str]:
        cfg = self.config.get("resilience", {})
        if not bool(cfg.get("model_fallback_enabled", True)):
            return []
        models = self.config.get("models", {})
        preprocessing = self.config.get("preprocessing", {})
        preprocessing_model = preprocessing.get("model") if isinstance(preprocessing, dict) else None
        if requested == preprocessing_model:
            return []
        mapping = {
            models.get("heavy_code"): [models.get("reasoning"), models.get("fast_code"), models.get("general")],
            models.get("reasoning"): [models.get("heavy_code"), models.get("fast_code")],
            models.get("fast_code"): [models.get("general")],
            models.get("general"): [models.get("fast_code")],
        }
        out: list[str] = []
        for candidate in mapping.get(requested, []):
            if candidate and candidate != requested and candidate not in out:
                out.append(str(candidate))
        return out[: int(cfg.get("max_model_fallbacks", 2))]

    def _semantic_scope_lock(self, scope: str) -> threading.Lock:
        with self._semantic_lock_guard:
            lock = self._semantic_scope_locks.get(scope)
            if lock is None:
                lock = threading.Lock()
                self._semantic_scope_locks[scope] = lock
                # Bound lock registry; correctness does not depend on preserving old unlocked keys.
                if len(self._semantic_scope_locks) > 2048:
                    for key in list(self._semantic_scope_locks)[:512]:
                        candidate = self._semantic_scope_locks.get(key)
                        if candidate is not None and not candidate.locked():
                            self._semantic_scope_locks.pop(key, None)
            return lock

    def _available_vram_mb(self) -> Any:
        balancer = getattr(self, "vram_balancer", None)
        if not balancer:
            return None
        status = balancer.status()
        if status.get("available", "vram_available_mb" in status):
            return status.get("vram_available_mb")
        return None

    def _observe_tuner_safely(self, model: str, result: dict[str, Any], elapsed_ms: float) -> None:
        try:
            self.tuner.observe(model, result, elapsed_ms)
        except (TypeError, ValueError, OverflowError) as tuner_exc:
            logger.debug(
                "Model tuning observation skipped (%s)",
                type(tuner_exc).__name__,
            )








































































































































































    DOMAIN_SYNONYMS = {
        "save": ["Save", "Store", "Persist", "Write", "Dump"],
        "load": ["Load", "Read", "Fetch", "Get", "Parse"],
        "database": ["SQLite", "Database", "ExecuteQuery", "Connection", "Transaction", "Query"],
        "auth": ["Auth", "Login", "Token", "User", "Session", "Authenticate", "Permission"],
        "api": ["Endpoint", "Route", "Handler", "Request", "Response", "Client"],
        "cache": ["Cache", "LRU", "Evict", "TTL", "Hit", "Miss"],
        "config": ["Config", "Settings", "Options", "Environment", "Params"],
        "test": ["Test", "Assert", "Fixture", "Mock", "Suite"],
        "logging": ["Logger", "Log", "Info", "Warning", "Error", "Debug"],
        "event": ["Event", "Emit", "Subscribe", "Publish", "Listener", "Handler"],
    }





















class _ServicesModuleProxy(types.ModuleType):
    def __setattr__(self, name: str, value: Any) -> None:
        super().__setattr__(name, value)
        for module in (_service_generation, _service_delegation, _service_repository, _service_coordination, _service_context, _service_review, _service_commands, _service_hybrid_context):
            if hasattr(module, name):
                setattr(module, name, value)

sys.modules[__name__].__class__ = _ServicesModuleProxy


__all__ = [
    'AdoptionMetricsStore',
    'AgentStateStore',
    'Any',
    'ArtifactStore',
    'CircuitBreakerRegistry',
    'ConsistencyRequest',
    'ContextCompiler',
    'ContextRequest',
    'ConversationStore',
    'GuardWarning',
    'LocalAIServices',
    'MAX_PAGE_SIZE',
    'MAX_PAGE_WINDOW',
    'Mapping',
    'MemoryLRUCache',
    'ModelExecutionPolicy',
    'ModelRouter',
    'OllamaSubagentCatalog',
    'OwnedBiomeDaemonPool',
    'Path',
    'RepositoryTools',
    'RuffDaemonPool',
    'SQLiteCache',
    'SchedulerCancelledError',
    'SchedulerTimeoutError',
    'SemanticGenerationCache',
    'Sequence',
    'ServiceCommandMixin',
    'ServiceContextMixin',
    'ServiceCoordinationMixin',
    'ServiceDelegationMixin',
    'ServiceGenerationMixin',
    'ServiceRepositoryMixin',
    'ServiceReviewMixin',
    'SingleFlightCache',
    'SingleFlightGroup',
    'TelemetryStore',
    'TieredCache',
    '_CONTEXT_BACKEND_POOLS',
    '_GLOBAL_VRAM_LOCK',
    '_GUARD_REASON_PROMPT_RE',
    '_GUARD_REASON_SECRET_RE',
    '_LinkedCancelEvent',
    '_MAX_REVIEW_DIFF_CHUNKS',
    '_REVIEW_DIFF_CONTEXT_FRACTION',
    '_REVIEW_DIFF_MIN_CHUNK_TOKENS',
    '_REVIEW_SYNTHESIS_CONTEXT_TOKENS',
    '_SOURCE_FOCUS_TERMS',
    '_SOURCE_SUFFIXES',
    '_ServicesModuleProxy',
    '__version__',
    '_active_sqlite_databases',
    '_backend_completion_metadata',
    '_context_path_priority',
    '_generation_cache_dispatch',
    '_merge_overlapping_evidence',
    '_merge_overlapping_line_ranges',
    '_merge_review_segment_results',
    '_rag_fragment_matches_source',
    '_redact_guard_reason',
    '_review_failure_details',
    '_review_model_identity',
    '_review_text_error',
    '_safe_float',
    '_safe_int',
    '_service_commands',
    '_service_context',
    '_service_coordination',
    '_service_delegation',
    '_service_generation',
    '_service_hybrid_context',
    '_service_repository',
    '_service_review',
    '_source_focused_query',
    '_split_review_diff',
    'annotations',
    'apply_path_coverage',
    'assess_semantic_result',
    'build_prompt',
    'cache_decision_reason',
    'canonical_root',
    'capture_job_cancellation',
    'closing',
    'configured_state_dir',
    'connect_sqlite',
    'contextmanager',
    'copy',
    'current_job_should_stop',
    'enclosing_symbol_at_line',
    'estimate_tokens',
    'fit_text',
    'fuse_ranked_paths',
    'generation_cache_key',
    'hashlib',
    'is_retryable_local_backend_error',
    'json',
    'json_dumps',
    'keyword',
    'logger',
    'logging',
    'math',
    'merge_overlapping_evidence',
    'merge_overlapping_line_ranges',
    'normalize_changed_paths',
    'normalize_context_for_hash',
    'normalize_generation_cache_prompt',
    'normalize_query',
    'os',
    'pagination_bounds_error',
    'postprocess_model_output',
    're',
    'reject_retired_tenancy_fields',
    'review_diff_complexity',
    'rollout_feature_enabled',
    'shlex',
    'shutil',
    'sqlite3',
    'stable_hash',
    'stat',
    'subprocess',
    'sys',
    'threading',
    'time',
    'types',
    'vram_priority',
    'wait',
]
