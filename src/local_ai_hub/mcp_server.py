from __future__ import annotations

from .mcp_context_guard import _guarded_context_input, _guarded_field_is_safe  # noqa: F401

import atexit
import asyncio
import copy
import contextvars
import functools
import hashlib  # noqa: F401
import inspect
import json  # noqa: F401
import math
import ntpath
import os
import queue  # noqa: F401
import re
import threading
from concurrent.futures import ThreadPoolExecutor as ThreadPoolExecutor
import time  # noqa: F401
import uuid  # noqa: F401
from collections import OrderedDict
from collections.abc import Mapping  # noqa: F401
from pathlib import Path, PureWindowsPath  # noqa: F401
from typing import Any, Literal, TypeAlias
from urllib.parse import quote as quote

from local_ai_hub.client import CURRENT_REQUEST_CANCEL_EVENT, HubClient
from local_ai_hub.repository_scope import (
    RepositoryScopeError as RepositoryScopeError,
    canonical_repository_root as canonical_repository_root,
    reject_retired_tenancy_fields as reject_retired_tenancy_fields,
)
from local_ai_hub.compact import compact_result  # noqa: F401
from local_ai_hub.agent_diagnostics import (  # noqa: F401
    agent_diagnostics_enabled,
    detailed_diagnostics_enabled,
    project_agent_response,
    project_pubsub_poll_response,
    project_wait_event_response,
    project_status_response,
)
from local_ai_hub.agent_surface import diagnostic_mcp_operation, diagnostics_disabled_response  # noqa: F401
from local_ai_hub.response_budget import (
    LIFECYCLE_PROTECTED_KEYS,
    _CONTEXT_PROTECTED_KEYS,  # noqa: F401
    _budget_rejection,  # noqa: F401
    _reconcile_existing_budget,  # noqa: F401
    budget_response,  # noqa: F401
    delta_response,  # noqa: F401
    result_id,  # noqa: F401
)
from local_ai_hub.context_ledger import ContextLedger
from local_ai_hub.budget import RootFamilyBudget
from local_ai_hub.projection import AgentProjector
from local_ai_hub.config import load_config
from local_ai_hub.features import FeatureSet
from local_ai_hub.operation_contracts import (
    HARDWARE_PROFILE_ORDER as HARDWARE_PROFILE_ORDER,
    MAX_EVENT_SEQUENCE as MAX_EVENT_SEQUENCE,
    MAX_REPO_PIPELINE_PARALLEL_STEPS as MAX_REPO_PIPELINE_PARALLEL_STEPS,
    REPO_PHASES as REPO_PHASES,
    REPO_PIPELINE_MUTATING_ACTIONS as REPO_PIPELINE_MUTATING_ACTIONS,
    contract_error,
    repo_pipeline_step_schema,
    validate_repo_pipeline_step as validate_repo_pipeline_step,
)
from local_ai_hub.ollama_subagents import OllamaSubagentCatalog
from local_ai_hub.process_utils import canonical_root, canonical_workspace_id as canonical_workspace_id, is_rooted_path
from local_ai_hub.token_accounting import account_projection, attach_accounting, context_digest, finalize_tool_accounting, json_tokens, pop_accounting, tool_request_tokens  # noqa: F401
from local_ai_hub.trace_context import efficiency_metadata, reset_metadata, set_metadata  # noqa: F401
from local_ai_hub.search_pagination import MAX_PAGE_SIZE, pagination_bounds_error as pagination_bounds_error  # noqa: F401
from local_ai_hub.search_modes import default_agent_search_mode as default_agent_search_mode
from local_ai_hub.adoption_metrics import AdoptionMetricsStore
from local_ai_hub.endpoint_stats import BUCKET_INTERVALS, EndpointStatsStore
from local_ai_hub.state_lifecycle import ensure_state_version
from local_ai_hub.task_memory_wire import (
    mcp_wire_tokens as _task_memory_mcp_wire_tokens,  # noqa: F401
    normalize_task_memory_response as _normalize_task_memory_response,  # noqa: F401
    task_memory_essential_response as _task_memory_essential_response,  # noqa: F401
    task_memory_original_tokens as _task_memory_original_tokens,  # noqa: F401
    task_memory_projection as _task_memory_projection,  # noqa: F401
    task_private_state_projection as _task_private_state_projection,  # noqa: F401
)
from local_ai_hub.routing import semantic_handoff_hint, targeted_semantic_handoff  # noqa: F401
from local_ai_hub.mcp_lifecycle_contracts import (
    async_job_lifecycle_contract as _async_job_lifecycle_contract_impl,
    semantic_handoff_contract as _semantic_handoff_contract_impl,
    task_delivery_contract as _task_delivery_contract_impl,
)
from local_ai_hub.mcp_tool_descriptions import (
    describe_artifact,
    describe_coord,
    describe_rag,
    describe_repo,
    describe_status,
    describe_task,
    describe_work,
)
from local_ai_hub.mcp_wire import (
    _build_mcp_budget_payload,
    _compact_mcp_call_tool,
    _mcp_bounded_error,
    _mcp_budget_payload,
    _mcp_task_memory_wire,
    _mcp_wire_view,
)
from local_ai_hub.json_utils import dumps as json_dumps
from local_ai_hub.mcp_normalization import _normalize_deterministic  # noqa: F401
from local_ai_hub.operation_contracts import (
    operation_contract,
    operation_actions,
    operation_enabled as operation_enabled,
    operation_parameters_schema,
    operation_tool_output_schema,
    operation_tool_input_schema,
    validate_operation_arguments,  # noqa: F401
    validate_operation_call,  # noqa: F401
    validate_operation_output,  # noqa: F401
)
from local_ai_hub.state_paths import configured_state_dir
from local_ai_hub.semantic_quality import assess_semantic_result, constrain_semantic_quality  # noqa: F401
from local_ai_hub.evidence_contract import evidence_meta as evidence_meta
from local_ai_hub.telemetry import _safe_error_metadata  # noqa: F401
from local_ai_hub.operational_mode import (
    OperationalModeSnapshot,
    load_operational_mode,
    operational_mode_gate_error,
)

try:
    from mcp.server.fastmcp import FastMCP
    import mcp.types as mcp_types
except ImportError:
    FastMCP = None  # type: ignore[assignment,misc]
    mcp_types = None  # type: ignore[assignment]

class _MissingMCP:
    """Import-safe stand-in used only when the optional MCP SDK is unavailable.

    Keeping module import side-effect free lets diagnostics, tests, and packaging
    tooling inspect the MCP surface without requiring the transport dependency.
    Actual server execution still fails fast with an actionable dependency error.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.tools: list[Any] = []

    def tool(self):
        def decorator(fn: Any) -> Any:
            self.tools.append(fn)
            return fn

        return decorator

    def run(self) -> None:
        raise SystemExit("Missing MCP dependency. Re-run setup or install requirements-core.txt")

# Module-level initialisation: FastMCP requires tool decorators at import
# time, so HubClient, config and projectors must be created here. Any failure
# produces a clear SystemExit instead of a confusing AttributeError later.
AGENT_NAME = os.environ.get("LOCAL_AI_AGENT", "agent")
_workspace = canonical_root(Path.cwd())
if "LOCAL_AI_TENANT" in os.environ:
    raise SystemExit("LOCAL_AI_TENANT is retired; this installation has one local owner")
CONFIG_PATH = os.environ.get("LOCAL_AI_CONFIG")
_CURRENT_OPERATIONAL_CONTEXT: contextvars.ContextVar[tuple[str, bool]] = contextvars.ContextVar(
    "mcp_operational_context", default=("", True)
)






from .mcp_client_adapter import (
    _MCPHubClientAdapter as _MCPHubClientAdapter,
    _MCPHubClientPostProxy as _MCPHubClientPostProxy,
)

from local_ai_hub.mcp_response_budget import (
    _batch_items_retained as _batch_items_retained,  # noqa: F401
    _bound_context_json as _bound_context_json,  # noqa: F401
    _code_index_page_with_prefix as _code_index_page_with_prefix,  # noqa: F401
    _code_index_prefix_fitting as _code_index_prefix_fitting,  # noqa: F401
    _context_delta_budget_error as _context_delta_budget_error,  # noqa: F401
    _context_input_error as _context_input_error,  # noqa: F401
    _explicit_budget_rejection as _explicit_budget_rejection,  # noqa: F401
    _relation_page_with_prefix as _relation_page_with_prefix,  # noqa: F401
    _relation_prefix_fitting as _relation_prefix_fitting,  # noqa: F401
    _response_budget as _response_budget,  # noqa: F401
    _reuse_only as _reuse_only,  # noqa: F401
    _reuse_state as _reuse_state,  # noqa: F401
    _search_page_with_prefix as _search_page_with_prefix,  # noqa: F401
    _search_prefix_fitting as _search_prefix_fitting,  # noqa: F401
    _subminimum_budget_rejection as _subminimum_budget_rejection,  # noqa: F401
    _validate_context_pack_inputs as _validate_context_pack_inputs,  # noqa: F401
)

def _build_mcp_client(config_path: str | None) -> _MCPHubClientAdapter:
    client = HubClient(config_path=config_path, auto_start=True)
    return _MCPHubClientAdapter(client)


def _classify_mcp_operation(tool_name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
    if tool_name == "local_ai_status":
        action = arguments.get("detail", "brief")
    else:
        action = arguments.get("action", tool_name)
    if not isinstance(action, str):
        action = ""
    lightweight_read = (
        tool_name == "local_ai_artifact"
        or (tool_name == "local_ai_status" and action == "brief")
        or (tool_name == "local_ai_repo" and action in {"map", "code_index", "search"})
    )
    return action, not lightweight_read


def _operational_mode_rejection(
    action: str, *, requires_heavy_work: bool = True,
) -> dict[str, Any] | None:
    try:
        snapshot = load_operational_mode(configured_state_dir(CFG, create=False))
    except Exception:
        snapshot = OperationalModeSnapshot(
            "maintenance", 0, None, degraded=True,
            error="operational mode state is unavailable",
        )
    if (
        snapshot.mode == "gaming"
        and not snapshot.degraded
        and bool(getattr(FEATURES, "speculative_lint", False))
        and action == "speculative_lint"
    ):
        return None
    return operational_mode_gate_error(
        snapshot, action, requires_heavy_work=requires_heavy_work,
    )


try:
    CLIENT = _build_mcp_client(CONFIG_PATH)
    CFG = load_config(CONFIG_PATH, probe_hardware=False)
    atexit.register(CLIENT.close)
    FEATURES = FeatureSet.from_config(CFG)
    MCP_CFG = CFG.get("mcp", {})
    PROJECTOR = AgentProjector(CFG)
    PROFILE_CATALOG = OllamaSubagentCatalog(CFG)
    MAX_TEXT = int(MCP_CFG.get("compact_max_text_chars", 6000))
    MAX_EVIDENCE = int(MCP_CFG.get("compact_max_evidence", 16))
    LEAN_SCHEMAS = bool(MCP_CFG.get("lean_schemas", True))
    RESPONSE_BUDGET_CFG = MCP_CFG.get("response_budget", {}) if isinstance(MCP_CFG.get("response_budget", {}), dict) else {}
    RESPONSE_BUDGET_ENABLED = bool(RESPONSE_BUDGET_CFG.get("enabled", True))
    RESPONSE_DEFAULT_TOKENS = max(128, int(RESPONSE_BUDGET_CFG.get("default_tokens", 8192)))
    RESPONSE_TOOL_TOKENS = RESPONSE_BUDGET_CFG.get("tool_tokens", {}) if isinstance(RESPONSE_BUDGET_CFG.get("tool_tokens", {}), dict) else {}
    RESPONSE_REUSE_LIMIT = max(16, int(RESPONSE_BUDGET_CFG.get("reuse_cache_size", 256)))
    CONTEXT_LEDGER = ContextLedger(max_entries=int(RESPONSE_BUDGET_CFG.get("ledger_size", 512)))
    ROOT_FAMILY_BUDGET = RootFamilyBudget(
        default_limit=int(CFG.get("workflow", {}).get("root_family_token_budget", 0) or 0),
        max_active_scopes=int(CFG.get("workflow", {}).get("root_family_max_active_scopes", 1) or 1),
    )
    _mcp_state_dir = configured_state_dir(CFG)
    ensure_state_version(_mcp_state_dir)
    ADOPTION_METRICS = AdoptionMetricsStore(_mcp_state_dir)
    ENDPOINT_STATS = EndpointStatsStore(_mcp_state_dir)
except Exception as _init_exc:  # pragma: no cover
    import logging
    import sys
    logging.getLogger("local_ai_hub.mcp_server").critical("MCP server init failed: %s", _init_exc, exc_info=True)
    sys.stderr.write(f"[local-ai-hub] MCP server init failed: {_init_exc}\n")
    raise SystemExit(1) from _init_exc


def _timeout(kind: str) -> float:
    defaults = {"quick": 180.0, "context": 600.0, "model": 600.0, "long": 600.0}
    return max(1.0, float(MCP_CFG.get(f"{kind}_timeout_seconds", defaults[kind])))


def _client_root(r: str = "") -> str:
    cleaned = str(r or "").strip()
    if not cleaned or cleaned == ".":
        return _workspace
    try:
        p = Path(cleaned)
        if not is_rooted_path(cleaned):
            return canonical_root(Path(_workspace) / p)
        # Preserve foreign-platform rooted paths. Calling Path.resolve() on a
        # Windows drive path while running on POSIX would incorrectly prefix cwd.
        if not p.is_absolute():
            return cleaned.replace("\\", "/")
        return canonical_root(p)
    except Exception:
        return _workspace








mcp = FastMCP("Local AI Hub (compact)") if FastMCP is not None else _MissingMCP("Local AI Hub (compact)")


# ---------------------------------------------------------------------------
# Dynamic tool description builders — read FEATURES (from config) at import
# time so tool schemas reflect only the active backends.
# ---------------------------------------------------------------------------

from local_ai_hub.mcp_repo_input import (
    _bounded_search_summary_input as _bounded_search_summary_input,  # noqa: F401
    _normalize_repo_search_path_hints as _normalize_repo_search_path_hints,  # noqa: F401
    _validate_search_summary_citations as _validate_search_summary_citations,  # noqa: F401
)

def _actions_note(actions: list[str]) -> str:
    """Expose the action surface supported by this installation's feature gates."""
    return f" Supported actions: {', '.join(actions)}." if actions else " No actions are enabled."


def _plan_coord_note() -> str:
    """Explain the plan workflow only when its actions are exposed by this installation."""
    supported = set(FEATURES.supported_coord_actions())
    plan_actions = {"plan_list", "plan_get", "plan_board_view", "plan_task_edit"}
    if plan_actions.issubset(supported):
        return (
            " For existing project plans, use plan_list, plan_get, and plan_board_view; "
            "edit a task with plan_task_edit and the current expected_revision."
        )
    return ""


def _specialized_note(tool_name: str) -> str:
    """Expose enabled feature-specific triggers alongside compact tool names."""
    notes = [line[2:] for line in FEATURES.specialized_trigger_lines() if f"`{tool_name}" in line]
    return f" Specialized triggers: {'; '.join(notes)}." if notes else ""


def _desc_status() -> str:
    return describe_status(_specialized_note)


def _semantic_handoff_contract(enabled: bool, status_enabled: bool = True) -> str:
    return _semantic_handoff_contract_impl(enabled, status_enabled)


def _async_job_lifecycle_contract(*, include_mcp_tool: bool = True) -> str:
    return _async_job_lifecycle_contract_impl(include_mcp_tool=include_mcp_tool)


def _task_delivery_contract() -> str:
    return _task_delivery_contract_impl()


def _desc_task() -> str:
    return describe_task(
        FEATURES,
        LEAN_SCHEMAS,
        _actions_note,
        _semantic_handoff_contract,
        _specialized_note,
    )

def _tier_repo_description(description: str) -> str:
    repo_actions = set(FEATURES.supported_repo_actions())
    task_actions = set(FEATURES.supported_task_actions())
    if "solve" not in repo_actions:
        for phrase in (
            "`solve` preserves one bounded local pass for explicit semantic requests even when exact evidence is strong. ",
            " For implementation, diagnosis, refactoring or complex review, call `solve` after evidence and before native edits.",
            " context and solve for bounded evidence and implementation support.",
        ):
            description = description.replace(phrase, "")
        description = description.replace("context/solve", "context")
    if "review_diff" not in repo_actions:
        description = description.replace("`review_diff` and `security_audit`", "`security_audit`")
        description = description.replace("`review_diff`, `security_audit`", "`security_audit`")
    if not (task_actions & {"delegate", "explore", "reason", "review", "second_opinion", "continue", "batch"}):
        for phrase in (
            "use `local_ai_task` for semantic generation, reasoning, review, independent second opinions and compression. ",
            " After any needed indexed evidence, use `local_ai_task` for semantic generation, reasoning, review, independent second opinions and compression. `solve` preserves one bounded local pass for explicit semantic requests even when exact evidence is strong.",
            " Semantic generation, reasoning, review, independent second opinions and compression use `local_ai_task` after evidence;",
        ):
            description = description.replace(phrase, "")
    description = description.replace(
        "Actions: search, code_index, context, solve, review_diff, callers, dead_code, preprocess (idempotent registration of a stable repository root; do not force-refresh or poll).",
        "The current MCP schema action enum lists available actions.",
    )
    return description + " The current MCP schema action enum is authoritative."


def _desc_repo() -> str:
    return describe_repo(
        FEATURES,
        LEAN_SCHEMAS,
        _tier_repo_description,
        _actions_note,
        _semantic_handoff_contract,
        _specialized_note,
    )

def _desc_rag() -> str:
    return describe_rag(FEATURES, LEAN_SCHEMAS, _actions_note, _specialized_note)

def _desc_coord() -> str:
    return describe_coord(
        FEATURES,
        LEAN_SCHEMAS,
        _actions_note,
        _plan_coord_note,
        _specialized_note,
    )


def _desc_work() -> str:
    return describe_work(FEATURES, LEAN_SCHEMAS, operation_actions, _specialized_note)


def _desc_artifact() -> str:
    return describe_artifact(LEAN_SCHEMAS, operation_actions, _specialized_note)


TaskAction: TypeAlias = Literal.__getitem__(operation_actions("local_ai_task", None))


_REPO_ACTIONS = (
    "profile", "search", "map", "code_index", "semantic", "intelligence",
    "deterministic", "context", "route", "delegate", "solve", "review_diff", "impact",
    "refactor_impact", "resolve_imports", "generate_tests", "validate_patch",
    "audit_dependencies", "ast_outline", "test_matrix", "security_audit", "git_status", "repo_state",
    "synthesize_commit", "verify", "preprocess", "preprocess_status", "preprocess_refresh",
    "preprocess_pause", "preprocess_resume", "preprocess_cancel", "preprocess_unregister",
    "context_compile", "verify_receipt", "verify_completion",
    "cross_project_graph", "cross_project_symbols", "cross_project_impact",
    "call_graph_diff", "semantic_diff",
    "affected_tests", "topology", "ast_refactor",
    "generate_mocks", "split_changes", "synthesize_rules",
    "code_invariants", "profile_digest",
    "callers", "callees", "implementations", "declaration", "dead_code", "secret_scan", "schema_inspect", "explain_query", "env_compat",
    "circular_dependencies", "generate_types", "complexity", "api_spec", "dependency_slice", "migration_drift", "package_audit",
    "structural_search", "context_budget",
    "git_diff", "git_history_search", "hotspots", "generate_tests_for_diff", "cross_repo_contract",
    "investigate",
    "diagnose", "briefing", "pipeline", "definition", "references", "find_references", "find_symbol",
)


def _repo_action_type(features: Any) -> Any:
    return Literal.__getitem__(operation_actions("local_ai_repo", features))


RepoAction: TypeAlias = _repo_action_type(None)
RagAction: TypeAlias = Literal.__getitem__(operation_actions("local_ai_rag"))
CoordAction: TypeAlias = Literal.__getitem__(operation_actions("local_ai_coord", None))
StatusDetail: TypeAlias = Literal.__getitem__(operation_actions("local_ai_status"))
STATUS_DETAILS = operation_actions("local_ai_status")
RepoPhase: TypeAlias = Literal.__getitem__(REPO_PHASES)
StatusScope: TypeAlias = Literal["process", "window"]
WorkAction: TypeAlias = Literal.__getitem__(operation_actions("local_ai_work"))
ArtifactAction: TypeAlias = Literal[*operation_actions("local_ai_artifact")]


def _invalid_action(tool: str, action: str, valid: tuple[str, ...], guidance: str) -> dict[str, Any]:
    if tool == "local_ai_task":
        return contract_error(
            f"Unknown {tool} action '{action}'. Use the action enum advertised by the MCP schema. {guidance}"
        )
    return contract_error(
        f"Unknown {tool} action '{action}'. Valid actions: {', '.join(valid)}. {guidance}"
    )


def _release_root_family_reservation() -> None:
    reservation = _CURRENT_ROOT_FAMILY_RESERVATION.get()
    if not reservation:
        return
    ROOT_FAMILY_BUDGET.release(
        str(reservation.get("reservation_id", "")),
        owner=str(reservation.get("owner", "")),
    )


def _release_root_family_on_exit(fn: Any) -> Any:
    @functools.wraps(fn)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        reservation_token = _CURRENT_ROOT_FAMILY_RESERVATION.set(None)
        try:
            return fn(*args, **kwargs)
        finally:
            _release_root_family_reservation()
            _CURRENT_ROOT_FAMILY_RESERVATION.reset(reservation_token)

    return wrapped



_CURRENT_EXTRA_FIELDS: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar("_CURRENT_EXTRA_FIELDS", default=None)
_CURRENT_RESPONSE_OPTIONS: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar("_CURRENT_RESPONSE_OPTIONS", default={})
_CURRENT_MCP_CALL_ARGUMENTS: contextvars.ContextVar[tuple[str, dict[str, Any]] | None] = contextvars.ContextVar(
    "_CURRENT_MCP_CALL_ARGUMENTS", default=None
)
_PENDING_MCP_ACCOUNTING: contextvars.ContextVar[list[dict[str, Any]] | None] = contextvars.ContextVar("_PENDING_MCP_ACCOUNTING", default=None)
_CURRENT_ROOT_FAMILY_RESERVATION: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "_CURRENT_ROOT_FAMILY_RESERVATION", default=None
)
_STATUS_PROTECTED_KEYS = (
    "guide_cards", "guide_scope", "guide_tips", "schema_token_reduction_verified",
    "success", "status_code", "error", "warning", "version", "hub_online", "ollama_online",
    "active_model", "queued", "inflight", "cache_hits", "coalesced_waiters",
    "net_cloud_token_delta_est", "vram_pressure", "context_budget_factor",
    "gpu_admission_state", "vram_telemetry", "endpoint_stats",
    "summary", "window", "queue", "hotspots", "by_operation", "error_fingerprints",
    "job_id", "trace_id", "task_id", "state", "artifact_id", "cancel_requested",
    "expires_at", "wait_timeout_seconds", "outcome_unknown", "coalesced", "idempotent_replay",
    "admission_state", "terminal", "retryable", "in_progress",
    "mutation_applied", "operation_not_started", "dependency_status",
    "worktree_id", "worktree_path", "lease_id", "branch",
    "enabled", "active_tasks", "tasks_count", "incidents_count", "candidates_count", "status",
)
_HARDWARE_BENCHMARK_PROTECTED_KEYS = (
    "model", "model_digest", "model_digest_status",
    "loaded_model_vram_bytes", "loaded_model_vram_status",
    "tokens_generated", "token_count_estimated", "token_count_method",
    "ttft_ms", "call_latency_ms", "latency_basis", "tokens_per_second",
    "hardware_score", "generation_duration_ms", "load_duration_ms",
    "requested_context_tokens",
    "loaded_model_context_tokens", "context_qualified", "context_qualification_status",
    "prompt_eval_count", "prompt_eval_count_method", "prompt_eval_duration_ms",
    "prefill_tokens_per_second",
    "queue_wait_ms", "peak_vram_bytes", "peak_vram_scope",
    "initial_vram", "final_vram", "measurement_warning",
)
_SECURITY_PROTECTED_KEYS = (
    "clean", "leak_count", "real_leaks_count", "secrets_count", "test_findings_count",
    "scanned_git_history", "git_history_status", "coverage",
    "is_clean", "findings_present", "release_blocking_findings", "triage_complete",
    "scan_complete", "limit_reached", "findings_count", "scanned_files", "eligible_files",
    "eligible_files_total", "skipped_files", "scanned_bytes", "coverage_scope", "stop_reason",
)

_RELIABILITY_PROTECTED_KEYS = (
    *LIFECYCLE_PROTECTED_KEYS,
    "request_id", "context_id",
    "success", "terminal", "retryable", "unsupported", "degraded", "stale", "unchanged", "freshness",
    "fallback_used", "evidence", "evidence_ids", "cancelled", "cancel_requested", "cancel_reason",
    "mutation_applied", "operation_not_started",
    "retry_after_seconds",
    "semantic_quality", "review_consistency", "advisory_only", "quality_warning", "bypass_reason",
    "review_scope_complete", "untracked_inventory_complete", "review_source_sha256",
)
_COORD_PROTECTED_KEYS = (
    "tasks", "task", "records", "matches", "items", "negative_knowledge",
    "receipts", "missing_criteria", "unverified_criteria", "total_count",
    "active_count", "offset", "limit", "has_more", "next_offset",
    "board", "columns", "summary", "checkpoint_sync",
    "plan", "plans", "file_revision", "plan_id", "rel_path", "git_branch", "git_head",
    "project_root", "counts", "total_items", "plan_filter", "plan_task_id",
    "reason_code", "reaped",
    "client_id", "display_name", "hook_support", "hook_events", "instruction_targets",
    "has_token_tracking", "has_reasoning_tokens", "has_shadow_events",
    "has_goal_system", "prompt_cache_shield", "tool_filter", "mcp_surface", "adapter_version",
)
_REPO_PROTECTED_KEYS = (
    "symbols", "files", "results", "evidence", "findings", "issues", "diff",
)
_VERIFY_PROTECTED_KEYS = ("missing_criteria", "unverified_criteria", "receipts", "completion")
_TOPOLOGY_PROTECTED_KEYS = (
    "coverage", "architecture_pattern_hypothesis", "architecture_pattern_verified",
    "heuristic_layers", "module_graph", "import_scope",
)
_COMPLEXITY_PROTECTED_KEYS = (
    "complete", "scope", "coverage", "limits", "files_analyzed", "eligible_files",
    "skipped_files", "skipped_directories", "parse_error_count", "read_error_count",
    "total_functions", "high_risk_count", "include_tests",
)
_REUSE_DIGESTS: OrderedDict[str, str] = OrderedDict()
_REUSE_VALUES: OrderedDict[str, Any] = OrderedDict()
















_CONTEXT_DELTA_BUDGET_ERROR = "Context delta exceeds response budget; request compact context or increase max_response_tokens"

















from .mcp_response_compact import _compact as _compact


_TELEMETRY_DETAIL_LABELS = {
    "status": frozenset({"complete", "incomplete"}),
    "omitted_sections": frozenset({
        "decision_grade_lists", "pending_events", "writer_failures",
        "writer_activity_unobserved", "writer_accounting_unbalanced", "cached_summary_data",
    }),
}
_TELEMETRY_HOTSPOT_LABELS = {
    "type": frozenset({"reliability", "latency", "efficiency", "quality", "observability"}),
    "signal": frozenset({
        "inference_failure_rate", "queue_wait", "low_cache_hit_rate",
        "frequent_model_fallbacks", "frequent_ollama_retries", "telemetry_queue_drops",
    }),
}
_TELEMETRY_SENSITIVE_TEXT_FIELD_RE = re.compile(
    r"(?i)(error|message|exception|reason|prompt|source|body|payload|content|token|secret|password|authorization|note|raw)"
)












_SEMANTIC_PATH_RE = re.compile(r"(?<![\w./-])[A-Za-z0-9_.-]+(?:[\\/][A-Za-z0-9_.-]+)+(?:\.[A-Za-z0-9_-]+)(?::\d+)?")




from .mcp_accounting import _ProtocolAccountingReporter as _ProtocolAccountingReporter


_ACCOUNTING_REPORTER = _ProtocolAccountingReporter()
atexit.register(_ACCOUNTING_REPORTER.close)












from local_ai_hub.mcp_instrumentation import (
    _agent_output as _agent_output,  # noqa: F401
    _instrumented_tool as _instrumented_tool,  # noqa: F401
    _preserve_contract_state as _preserve_contract_state,  # noqa: F401
    _record_tool_accounting as _record_tool_accounting,  # noqa: F401
    _sanitize_telemetry_payload as _sanitize_telemetry_payload,  # noqa: F401
    _schema_descriptor as _schema_descriptor,  # noqa: F401
    _telemetry_failure as _telemetry_failure,  # noqa: F401
    _telemetry_status_projection as _telemetry_status_projection,  # noqa: F401
    _tool_catalog_schema_tokens as _tool_catalog_schema_tokens,  # noqa: F401
)

from local_ai_hub.mcp_task_context import (
    _attach_task_context_receipt as _attach_task_context_receipt,  # noqa: F401
    _load_task_context as _load_task_context,  # noqa: F401
    _quality_check_semantic_result as _quality_check_semantic_result,  # noqa: F401
)

def _adoption_reason(value: Any) -> str:
    text = str(value or "").lower()
    if "timeout" in text: return "timeout"
    if "unsupported" in text or "disabled" in text: return "unsupported"
    if "policy" in text or "forbidden" in text or "denied" in text: return "policy"
    if "validation" in text or "invalid" in text or "required" in text: return "validation"
    if "unavailable" in text or "connection" in text: return "unavailable"
    return "other"


_ADOPTION_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_ADOPTION_TOOLS = {"local_ai_status", "local_ai_task", "local_ai_repo", "local_ai_rag", "local_ai_coord", "local_ai_work", "local_ai_artifact"}
_ADOPTION_ACTIONS = {
    "local_ai_status": set(operation_actions("local_ai_status")),
    "local_ai_task": set(operation_actions("local_ai_task")),
    "local_ai_repo": set(operation_actions("local_ai_repo")),
    "local_ai_rag": set(operation_actions("local_ai_rag")),
    "local_ai_coord": set(operation_actions("local_ai_coord")),
    "local_ai_work": set(operation_actions("local_ai_work")),
    "local_ai_artifact": set(operation_actions("local_ai_artifact")),
}


def _adoption_target(arguments: dict[str, Any]) -> tuple[str, str] | None:
    if arguments.get("adoption_signal") != "bypassed":
        return None
    tool = str(arguments.get("target_tool") or "").strip().lower()
    action = str(arguments.get("target_action") or "").strip().lower()
    if tool not in _ADOPTION_TOOLS or not _ADOPTION_IDENTIFIER.fullmatch(action) or action not in _ADOPTION_ACTIONS[tool]:
        return None
    return tool, action


def _record_adoption(tool: str, arguments: dict[str, Any], result: Any, duration_ms: float, *, failed: bool = False, failure_reason: str | None = None, recommended: bool = False, event_id: str = "") -> None:
    """Best-effort aggregate telemetry; never retain request/response values."""
    try:
        action = str(arguments.get("action") or "default").lower()
        called_tool, called_action = tool, action
        target = _adoption_target(arguments)
        if target is not None:
            tool, action = target
        intent = {"local_ai_repo": "repository", "local_ai_coord": "coordination"}.get(tool, "hub")
        payload = result if isinstance(result, dict) else {}
        if target is not None:
            outcome, reason = "bypassed", "explicit_client_signal"
        elif failed:
            outcome, reason = "failed", failure_reason or "other"
        elif payload.get("fallback_used") is True:
            outcome, reason = "fallback_used", _adoption_reason(payload.get("error"))
        elif payload.get("success") is True:
            outcome, reason = "used", None
        elif payload.get("blocked") is True or payload.get("unsupported") is True:
            outcome, reason = "blocked", _adoption_reason(payload.get("error"))
        else:
            outcome, reason = "failed", _adoption_reason(payload.get("error"))
        # Do not serialize payloads merely to measure them: they can contain source,
        # prompts, paths, or secrets.  A bounded structural estimate is enough for a
        # coarse output-size bucket and never reads any value.
        output_size = min(4096, len(payload) * 64)
        ADOPTION_METRICS.record(tool, action, intent, outcome, fallback_reason=reason, duration_ms=duration_ms, output_size=output_size)
        if recommended:
            ADOPTION_METRICS.record(tool, action, intent, "recommended", duration_ms=duration_ms, output_size=output_size)
        if ENDPOINT_STATS is not None:
            mcp_name = f"{called_tool}:{called_action}" if called_action and called_action != "default" else called_tool
            raw_root = arguments.get("root", "")
            mcp_root = raw_root if isinstance(raw_root, str) and (os.path.isabs(raw_root) or ntpath.isabs(raw_root)) else ""
            ENDPOINT_STATS.record_call(
                item_type="mcp",
                item_name=mcp_name,
                duration_ms=duration_ms,
                success=not failed and payload.get("success") is True,
                root=mcp_root,
                **({"event_id": event_id} if event_id else {}),
            )
    except Exception:
        pass


def _compact_endpoint_stats(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("success") is not True:
        return {"available": False, "error": "endpoint_stats_unavailable", "items": []}
    raw_items = value.get("items")
    if not isinstance(raw_items, list):
        return {"available": False, "error": "endpoint_stats_unavailable", "items": []}

    items: list[dict[str, Any]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        kind = raw.get("type")
        name = raw.get("name")
        calls = raw.get("calls")
        if (not isinstance(kind, str) or kind not in {"http", "mcp"} or not isinstance(name, str)
                or isinstance(calls, bool) or not isinstance(calls, int) or calls <= 0):
            continue
        item: dict[str, Any] = {"type": kind, "name": name[:160], "calls": calls}
        for key in ("success_rate", "p50_ms", "p95_ms", "p99_ms"):
            metric = raw.get(key)
            if metric is None and key == "success_rate":
                item[key] = None
            elif isinstance(metric, (int, float)) and not isinstance(metric, bool) and math.isfinite(metric):
                item[key] = round(float(metric), 1)
        last_used = raw.get("last_used")
        if isinstance(last_used, (int, float)) and not isinstance(last_used, bool) and math.isfinite(last_used):
            item["last_used"] = round(float(last_used), 3)
        status = raw.get("status")
        item["status"] = status if isinstance(status, str) and status in {"failing", "slow", "active"} else "unknown"
        raw_issues = raw.get("issues")
        if isinstance(raw_issues, (list, tuple)):
            item["issues"] = list(dict.fromkeys(issue for issue in raw_issues if issue in {"failing", "slow"}))
        else:
            item["issues"] = [item["status"]] if item["status"] in {"failing", "slow"} else []
        items.append(item)

    priority = {"failing": 0, "slow": 1, "active": 2, "unknown": 3}
    items.sort(key=lambda item: (
        priority[item["status"]],
        -(item.get("p95_ms") if isinstance(item.get("p95_ms"), (int, float)) else 0.0),
    ))
    return {
        "available": True,
        "window": "stored_since_reset",
        "latency_method": "fixed_histogram_bucket_estimate",
        "histogram_bucket_ceiling_ms": int(BUCKET_INTERVALS[-1][1]),
        "histogram_top_bucket_open_ended": True,
        "last_used_unit": "unix_seconds",
        "items": items[:8],
        "truncated": len(items) > 8,
    }


def _compact_scheduler_status(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not any(
        key in value for key in ("background_allowed", "gpu_admission_state", "queued", "foreground_queued")
    ):
        return {"available": False, "error": "scheduler_status_unavailable"}
    result: dict[str, Any] = {"available": True}
    for key in ("background_allowed", "switching"):
        if type(value.get(key)) is bool:
            result[key] = value[key]
    for key in (
        "active_parallel_limit", "global_parallel_limit", "inflight",
        "inflight_background", "foreground_inflight", "queued",
        "background_queued", "foreground_queued", "last_foreground_activity_ms",
    ):
        item = value.get(key)
        if type(item) is int and item >= 0:
            result[key] = item
    admission = value.get("gpu_admission_state")
    result["gpu_admission_state"] = (
        admission if isinstance(admission, str) and admission in {
            "available", "external_reservation", "background_lease",
            "preparing_model", "inference_active", "outcome_unknown",
        } else "unknown"
    )
    blockers = []
    if result["gpu_admission_state"] == "external_reservation":
        blockers.append("external_reservation")
    if result["gpu_admission_state"] == "background_lease":
        blockers.append("background_lease")
    if result["gpu_admission_state"] == "preparing_model":
        blockers.append("preparing_model")
    if result["gpu_admission_state"] == "outcome_unknown":
        blockers.append("gpu_outcome_unknown")
    if result.get("switching") is True:
        blockers.append("model_switch")
    if result.get("foreground_inflight", 0) > 0:
        blockers.append("foreground_inflight")
    if result.get("foreground_queued", 0) > 0:
        blockers.append("foreground_queued")
    result["visible_background_blockers"] = blockers
    if result.get("background_allowed") is False and not blockers:
        result["background_block_reason_incomplete"] = True
    return result


def _effective_mcp_capabilities(
    backend: dict[str, Any], adapter: dict[str, Any],
) -> dict[str, Any]:
    """Report backend capabilities only when the current MCP adapter exposes them."""
    effective = copy.deepcopy(backend)
    for name, local in adapter.items():
        remote = effective.get(name)
        if (isinstance(local, dict) and local.get("available") is False
                and isinstance(remote, dict) and remote.get("available") is True):
            remote.update(available=False, state=local.get("state", "disabled"),
                          reason="disabled_in_mcp_adapter")
    return effective


from .mcp_tools_status import local_ai_status as _local_ai_status
local_ai_status = _instrumented_tool()(_local_ai_status)
local_ai_status = mcp.tool()(local_ai_status)




from .mcp_tools_task import local_ai_task as _local_ai_task
local_ai_task = _release_root_family_on_exit(_local_ai_task)
local_ai_task = _instrumented_tool()(local_ai_task)
local_ai_task = mcp.tool()(local_ai_task)








from .mcp_context_projection import _context_pack_projection as _context_pack_projection


def _repo_pipeline_step_contract() -> dict[str, Any]:
    tool_manager = getattr(mcp, "_tool_manager", None)
    tools = getattr(tool_manager, "_tools", {}) if tool_manager is not None else {}
    repo_tool = tools.get("local_ai_repo") if isinstance(tools, dict) else None
    parameters = getattr(repo_tool, "parameters", {}) if repo_tool is not None else {}
    properties = parameters.get("properties", {}) if isinstance(parameters, dict) else {}
    return repo_pipeline_step_schema(properties, FEATURES.supported_repo_actions())


def _repo_validation_arguments(action: str, candidates: dict[str, Any]) -> dict[str, Any]:
    """Keep action-required canonical inputs in every scoped validation call."""
    contract = operation_contract("local_ai_repo")
    action_contract = contract.get("actions", {}).get(action) if contract else None
    if not isinstance(action_contract, dict):
        return candidates
    allowed = action_contract.get("allowed")
    scoped_names = {"max_commits", "author", "since", "until", "days", "limit"}
    required_names = tuple(action_contract.get("required", ()))
    if allowed is None:
        relevant_names = set(required_names) | scoped_names
        return {
            name: value for name, value in candidates.items()
            if name in relevant_names and value is not None
        }
    allowed_names = set(allowed)
    selected = {
        name: candidates[name]
        for name in required_names
        if name in candidates and name in allowed_names
    }
    selected.update({
        name: value for name, value in candidates.items()
        if (name in allowed_names or name in scoped_names) and value is not None
    })
    return selected


from .mcp_tools_repo import _local_ai_repo_impl


from .mcp_tools_repo import local_ai_repo
local_ai_repo = mcp.tool()(_instrumented_tool()(local_ai_repo))


local_ai_repo.__doc__ = _local_ai_repo_impl.__doc__


def _project_repo_batch_schema(mcp_runtime: Any, tool: Any) -> None:
    """Keep rollout-only fields and action typing aligned with the public schema."""
    if hasattr(mcp_runtime, "_tool_manager") and hasattr(mcp_runtime._tool_manager, "_tools"):
        repo_tool = mcp_runtime._tool_manager._tools.get("local_ai_repo")
        if repo_tool is not None:
            properties = repo_tool.parameters.get("properties", {})
            schema = operation_tool_input_schema("local_ai_repo", FEATURES)
            repo_tool.parameters.clear()
            repo_tool.parameters.update(schema)
            properties = repo_tool.parameters.get("properties", {})
            if not FEATURES.batch_replacement:
                properties.pop("edits", None)
                properties.pop("dry_run", None)
    action_type = _repo_action_type(FEATURES)
    annotations = getattr(tool, "__annotations__", None)
    if isinstance(annotations, dict):
        annotations["action"] = action_type
    parameters = []
    for parameter in inspect.signature(tool).parameters.values():
        if not FEATURES.batch_replacement and parameter.name in {"edits", "dry_run"}:
            continue
        if parameter.name == "action":
            parameter = parameter.replace(annotation=action_type)
        parameters.append(parameter)
    tool.__signature__ = inspect.Signature(parameters)


# Keep one public MCP tool while exposing rollout fields only in enabled schemas.
# FastMCP builds its schema at decoration time, so both feature states need a
# runtime-schema and introspection-signature projection after registration.
_project_repo_batch_schema(mcp, local_ai_repo)


from .mcp_tools_rag import local_ai_rag
local_ai_rag = mcp.tool()(_instrumented_tool()(local_ai_rag))





from .mcp_tools_coord import local_ai_coord
local_ai_coord = mcp.tool()(_instrumented_tool()(local_ai_coord))




from local_ai_hub.mcp_tools_work import local_ai_work as _local_ai_work
local_ai_work = mcp.tool()(_instrumented_tool()(_local_ai_work))

from .mcp_tools_artifact import local_ai_artifact as _local_ai_artifact
local_ai_artifact = _instrumented_tool()(_local_ai_artifact)
local_ai_artifact = mcp.tool()(local_ai_artifact)


# Unregister tools that are disabled in current configuration so MCP clients do not receive them
_ALL_REGISTERED_TOOLS: dict[str, Any] = (
    dict(mcp._tool_manager._tools)
    if hasattr(mcp, "_tool_manager") and hasattr(mcp._tool_manager, "_tools")
    else {}
)
from local_ai_hub.client_adapters.registry import (
    ClientRegistry,
)
_client_adapter = ClientRegistry.get(agent_header=os.environ.get("LOCAL_AI_AGENT"))
_client_filtered = set(_client_adapter.filter_tools(list(_ALL_REGISTERED_TOOLS.keys())))
_adapter_disabled = set(_ALL_REGISTERED_TOOLS.keys()) - _client_filtered


def _mcp_input_schema_for_client(tool_name: str) -> dict[str, Any]:
    """Project a bounded client schema while keeping dispatch validation authoritative."""
    if not _client_adapter.capabilities.compact_mcp_schemas:
        return operation_tool_input_schema(tool_name, FEATURES)
    contract = operation_contract(tool_name)
    schema = operation_parameters_schema(tool_name, FEATURES)
    if contract is None:
        return schema
    selector = str(contract.get("selector_field", "action"))
    properties = schema.setdefault("properties", {})
    selector_schema = properties.setdefault(selector, {"type": "string"})
    selector_schema["enum"] = list(operation_actions(tool_name, FEATURES))
    # Per-action required/forbidden fields are enforced by validate_operation_call.
    # The MCP schema stays compact enough for OpenCode's initial tools/list handshake.
    schema.pop("allOf", None)
    schema["required"] = list(dict.fromkeys([*schema.get("required", []), selector]))
    schema["additionalProperties"] = False
    return schema

for _disabled in set(FEATURES.disabled_tools) | _adapter_disabled:
    if hasattr(mcp, "_tool_manager") and hasattr(mcp._tool_manager, "_tools"):
        mcp._tool_manager._tools.pop(_disabled, None)
    if hasattr(mcp, "tools") and isinstance(mcp.tools, list):
        mcp.tools = [t for t in mcp.tools if getattr(t, "__name__", "") != _disabled]
    _ALL_REGISTERED_TOOLS.pop(_disabled, None)


# Ensure tool descriptions registered in FastMCP carry the complete dynamic guidance
_all_desc_map = {
    "local_ai_status": _desc_status,
    "local_ai_task": _desc_task,
    "local_ai_repo": _desc_repo,
    "local_ai_rag": _desc_rag,
    "local_ai_coord": _desc_coord,
    "local_ai_artifact": _desc_artifact,
    "local_ai_work": _desc_work,
}
if hasattr(mcp, "_tool_manager") and hasattr(mcp._tool_manager, "_tools"):
    def _async_mcp_adapter(sync_fn: Any) -> Any:
        @functools.wraps(sync_fn)
        async def _call(*args: Any, **kwargs: Any) -> Any:
            cancel_event = threading.Event()
            token = CURRENT_REQUEST_CANCEL_EVENT.set(cancel_event)
            try:
                return await asyncio.to_thread(sync_fn, *args, **kwargs)
            finally:
                cancel_event.set()
                CURRENT_REQUEST_CANCEL_EVENT.reset(token)

        return _call

    # FastMCP invokes sync callables on its event loop. Keep direct Python
    # functions synchronous, but offload registered MCP callables so one
    # blocking tool cannot stall other requests on the same server.
    for _registered_tool in _ALL_REGISTERED_TOOLS.values():
        if not _registered_tool.is_async:
            _registered_tool.fn = _async_mcp_adapter(_registered_tool.fn)
            _registered_tool.is_async = True

    for _tool_name, _desc_fn in _all_desc_map.items():
        if _tool_name in _ALL_REGISTERED_TOOLS:
            description = _desc_fn()
            description = _client_adapter.mutate_tool_description(_tool_name, description)
            _ALL_REGISTERED_TOOLS[_tool_name].description = description

if hasattr(mcp, "_tool_manager") and hasattr(mcp, "_mcp_server") and mcp_types is not None:
    # FastMCP 1.x reads `parameters` and `fn_metadata.output_schema` when listing
    # tools. Publish the feature-aware conditional input schema and shared output
    # envelope while keeping per-action output contracts in operation metadata.
    for _tool_name in _all_desc_map:
        _registered_tool = _ALL_REGISTERED_TOOLS.get(_tool_name)
        _actions = operation_actions(_tool_name, FEATURES)
        if _registered_tool is None or not _actions:
            continue
        if hasattr(_registered_tool, "parameters"):
            _input_schema = _mcp_input_schema_for_client(_tool_name)
            if _tool_name == "local_ai_task":
                _input_schema.setdefault("properties", {})["request_id"] = {
                    "type": "string", "default": "",
                    "description": "Stable async-job idempotency key and request correlation ID.",
                }
                _non_async_actions = sorted(set(_actions) - {"submit", "status", "wait", "result", "cancel"})
                if _non_async_actions:
                    _input_schema.setdefault("if", {})
                    _input_schema.setdefault("then", {}).setdefault("allOf", []).append({
                        "if": {
                            "properties": {"action": {"enum": _non_async_actions}},
                            "required": ["action"],
                        },
                        "then": {"not": {"required": ["request_id"]}},
                    })
            _registered_tool.parameters = _input_schema
        _output_schema = operation_tool_output_schema(_tool_name, FEATURES)
        _fn_metadata = getattr(_registered_tool, "fn_metadata", None)
        if hasattr(_fn_metadata, "output_schema"):
            _fn_metadata.output_schema = _output_schema
            getattr(_registered_tool, "__dict__", {}).pop("output_schema", None)







    mcp.call_tool = _compact_mcp_call_tool
    mcp._mcp_server.call_tool(validate_input=False)(_compact_mcp_call_tool)


def main() -> None:
    """Run MCP stdio; HubClient starts the HTTP daemon when a tool needs it."""
    mcp.run()


if __name__ == "__main__":
    main()




__all__ = [
    'AGENT_NAME',
    'AdoptionMetricsStore',
    'AgentProjector',
    'Any',
    'BUCKET_INTERVALS',
    'CONFIG_PATH',
    'CURRENT_REQUEST_CANCEL_EVENT',
    'ClientRegistry',
    'ContextLedger',
    'EndpointStatsStore',
    'FeatureSet',
    'HARDWARE_PROFILE_ORDER',
    'HubClient',
    'LIFECYCLE_PROTECTED_KEYS',
    'Literal',
    'MAX_EVENT_SEQUENCE',
    'MAX_PAGE_SIZE',
    'MAX_REPO_PIPELINE_PARALLEL_STEPS',
    'Mapping',
    'OllamaSubagentCatalog',
    'OperationalModeSnapshot',
    'OrderedDict',
    'Path',
    'PureWindowsPath',
    'REPO_PHASES',
    'REPO_PIPELINE_MUTATING_ACTIONS',
    'RepositoryScopeError',
    'RootFamilyBudget',
    'STATUS_DETAILS',
    'ThreadPoolExecutor',
    'TypeAlias',
    '_ACCOUNTING_REPORTER',
    '_ADOPTION_ACTIONS',
    '_ADOPTION_IDENTIFIER',
    '_ADOPTION_TOOLS',
    '_COMPLEXITY_PROTECTED_KEYS',
    '_CONTEXT_DELTA_BUDGET_ERROR',
    '_CONTEXT_PROTECTED_KEYS',
    '_COORD_PROTECTED_KEYS',
    '_HARDWARE_BENCHMARK_PROTECTED_KEYS',
    '_MCPHubClientAdapter',
    '_MCPHubClientPostProxy',
    '_MissingMCP',
    '_ProtocolAccountingReporter',
    '_RELIABILITY_PROTECTED_KEYS',
    '_REPO_ACTIONS',
    '_REPO_PROTECTED_KEYS',
    '_SECURITY_PROTECTED_KEYS',
    '_SEMANTIC_PATH_RE',
    '_STATUS_PROTECTED_KEYS',
    '_TELEMETRY_DETAIL_LABELS',
    '_TELEMETRY_HOTSPOT_LABELS',
    '_TELEMETRY_SENSITIVE_TEXT_FIELD_RE',
    '_TOPOLOGY_PROTECTED_KEYS',
    '_VERIFY_PROTECTED_KEYS',
    '_actions_note',
    '_adapter_disabled',
    '_adoption_reason',
    '_adoption_target',
    '_agent_output',
    '_all_desc_map',
    '_async_job_lifecycle_contract',
    '_async_job_lifecycle_contract_impl',
    '_attach_task_context_receipt',
    '_batch_items_retained',
    '_bound_context_json',
    '_bounded_search_summary_input',
    '_budget_rejection',
    '_build_mcp_budget_payload',
    '_build_mcp_client',
    '_classify_mcp_operation',
    '_client_adapter',
    '_client_filtered',
    '_client_root',
    '_code_index_page_with_prefix',
    '_code_index_prefix_fitting',
    '_compact',
    '_compact_endpoint_stats',
    '_compact_mcp_call_tool',
    '_compact_scheduler_status',
    '_context_delta_budget_error',
    '_context_input_error',
    '_context_pack_projection',
    '_desc_artifact',
    '_desc_coord',
    '_desc_rag',
    '_desc_repo',
    '_desc_status',
    '_desc_task',
    '_desc_work',
    '_effective_mcp_capabilities',
    '_explicit_budget_rejection',
    '_guarded_context_input',
    '_guarded_field_is_safe',
    '_project_repo_batch_schema',
    '_instrumented_tool',
    '_invalid_action',
    '_load_task_context',
    '_local_ai_artifact',
    '_local_ai_repo_impl',
    '_local_ai_status',
    '_local_ai_task',
    '_local_ai_work',
    '_mcp_bounded_error',
    '_mcp_budget_payload',
    '_mcp_task_memory_wire',
    '_mcp_wire_view',
    '_normalize_deterministic',
    '_normalize_repo_search_path_hints',
    '_normalize_task_memory_response',
    '_operational_mode_rejection',
    '_plan_coord_note',
    '_preserve_contract_state',
    '_quality_check_semantic_result',
    '_reconcile_existing_budget',
    '_record_adoption',
    '_record_tool_accounting',
    '_relation_page_with_prefix',
    '_relation_prefix_fitting',
    '_release_root_family_on_exit',
    '_release_root_family_reservation',
    '_repo_action_type',
    '_repo_pipeline_step_contract',
    '_repo_validation_arguments',
    '_response_budget',
    '_reuse_only',
    '_reuse_state',
    '_safe_error_metadata',
    '_sanitize_telemetry_payload',
    '_schema_descriptor',
    '_search_page_with_prefix',
    '_search_prefix_fitting',
    '_semantic_handoff_contract',
    '_semantic_handoff_contract_impl',
    '_specialized_note',
    '_subminimum_budget_rejection',
    '_task_delivery_contract',
    '_task_delivery_contract_impl',
    '_task_memory_essential_response',
    '_task_memory_mcp_wire_tokens',
    '_task_memory_original_tokens',
    '_task_memory_projection',
    '_task_private_state_projection',
    '_telemetry_failure',
    '_telemetry_status_projection',
    '_tier_repo_description',
    '_timeout',
    '_tool_catalog_schema_tokens',
    '_validate_context_pack_inputs',
    '_validate_search_summary_citations',
    '_workspace',
    'account_projection',
    'annotations',
    'assess_semantic_result',
    'asyncio',
    'atexit',
    'attach_accounting',
    'budget_response',
    'canonical_repository_root',
    'canonical_root',
    'canonical_workspace_id',
    'compact_result',
    'configured_state_dir',
    'constrain_semantic_quality',
    'context_digest',
    'contextvars',
    'contract_error',
    'copy',
    'default_agent_search_mode',
    'delta_response',
    'describe_artifact',
    'describe_coord',
    'describe_rag',
    'describe_repo',
    'describe_status',
    'describe_task',
    'describe_work',
    'agent_diagnostics_enabled',
    'detailed_diagnostics_enabled',
    'diagnostic_mcp_operation',
    'diagnostics_disabled_response',
    'efficiency_metadata',
    'ensure_state_version',
    'evidence_meta',
    'finalize_tool_accounting',
    'functools',
    'hashlib',
    'inspect',
    'is_rooted_path',
    'json',
    'json_dumps',
    'json_tokens',
    'load_config',
    'load_operational_mode',
    'local_ai_artifact',
    'local_ai_coord',
    'local_ai_rag',
    'local_ai_repo',
    'local_ai_status',
    'local_ai_task',
    'local_ai_work',
    'main',
    'math',
    'mcp',
    'ntpath',
    'operation_actions',
    'operation_contract',
    'operation_enabled',
    'operation_tool_input_schema',
    'operation_tool_output_schema',
    'operational_mode_gate_error',
    'os',
    'pagination_bounds_error',
    'pop_accounting',
    'project_agent_response',
    'project_status_response',
    'project_pubsub_poll_response',
    'project_wait_event_response',
    'queue',
    'quote',
    're',
    'reject_retired_tenancy_fields',
    'repo_pipeline_step_schema',
    'reset_metadata',
    'result_id',
    'semantic_handoff_hint',
    'set_metadata',
    'targeted_semantic_handoff',
    'threading',
    'time',
    'tool_request_tokens',
    'uuid',
    'validate_operation_arguments',
    'validate_operation_call',
    'validate_operation_output',
    'validate_repo_pipeline_step',
]
