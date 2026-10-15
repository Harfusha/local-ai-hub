"""Small, dependency-free contracts for public hub operations."""

from __future__ import annotations

import json
import math
from copy import deepcopy
from typing import Any

from .search_pagination import MAX_PAGE_SIZE, MAX_PAGE_WINDOW, pagination_bounds_error

REPO_PHASES = ("", "plan", "edit", "review", "test", "handoff")
MAX_REPO_PIPELINE_PARALLEL_STEPS = 4
MAX_EVENT_SEQUENCE = (1 << 63) - 1
REPO_PIPELINE_MUTATING_ACTIONS = frozenset({
    "batch_replace", "ast_refactor", "preprocess", "preprocess_refresh",
    "preprocess_pause", "preprocess_resume", "preprocess_cancel", "preprocess_unregister",
})


def normalize_transport_error(status_code: int, payload: Any) -> dict[str, Any]:
    """Normalize errors without replacing explicit delivery/retry state."""
    result = dict(payload) if isinstance(payload, dict) else {"error": str(payload)}
    result["success"] = False
    result["status_code"] = int(status_code)
    retryable = status_code in {408, 425, 429, 500, 502, 503, 504}
    if "retryable" not in result and "terminal" not in result:
        result.update(retryable=retryable, terminal=not retryable)
    elif "retryable" not in result:
        result["retryable"] = not bool(result["terminal"])
    elif "terminal" not in result:
        result["terminal"] = not bool(result["retryable"])
    if isinstance(result.get("error"), str):
        result["error"] = result["error"][:500]
    return result


def contract_error(message: str, *, status_code: int = 400) -> dict[str, Any]:
    return normalize_transport_error(status_code, {"error": message[:500]})


def repo_pipeline_step_schema(repo_properties: dict[str, Any], repo_actions: Any) -> dict[str, Any]:
    """Preserve registry types and bounds in closed pipeline step inputs."""
    properties = deepcopy({key: value for key, value in repo_properties.items() if key not in {"steps", "action"}})
    properties["id"] = {"type": "string", "maxLength": 128}
    properties["action"] = {"type": "string", "enum": [action for action in repo_actions if action != "pipeline"]}
    return {"type": "object", "required": ["action"], "properties": properties, "additionalProperties": False}


def validate_repo_pipeline_step(step: Any, *, index: int, step_schema: dict[str, Any], features: Any = None) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(step, dict):
        return None, f"steps[{index}] must be an object"
    error = _validate_nested_schema(step, step_schema, f"steps[{index}]", "pipeline")
    if error:
        return None, error
    arguments = {key: value for key, value in step.items() if key != "id"}
    error = validate_operation_arguments("local_ai_repo", step.get("action"), arguments, features=features)
    return (None, error) if error else (dict(step), None)


def _action_contracts(
    actions: tuple[str, ...],
    *,
    default_effect: str = "read_only",
    read_only: tuple[str, ...] = (),
    effects: dict[str, str] | None = None,
    requirements: dict[str, tuple[str, ...]] | None = None,
    required: dict[str, tuple[str, ...]] | None = None,
    non_empty: dict[str, tuple[str, ...]] | None = None,
    allowed: dict[str, tuple[str, ...]] | None = None,
) -> dict[str, dict[str, Any]]:
    effects = effects or {}
    requirements = requirements or {}
    required = required or {}
    non_empty = non_empty or {}
    allowed = allowed or {}
    result: dict[str, dict[str, Any]] = {}
    for action in actions:
        side_effects = "read_only" if action in read_only else effects.get(action, default_effect)
        safe = side_effects == "read_only"
        result[action] = {
            "required": required.get(action, ()),
            "non_empty": non_empty.get(action, ()),
            "allowed": allowed.get(action),
            "side_effects": side_effects,
            "idempotent": safe,
            "retry_safe": safe,
            "automatic_replay": False,
            "requires": requirements.get(action, ()),
        }
    return result


_STATUS_ACTIONS = ("brief", "cache", "telemetry", "full", "agent_state", "traces", "guide")
_REPO_ACTIONS = (
    "profile", "search", "map", "code_index", "deterministic", "context", "route", "delegate",
    "solve", "review_diff", "impact", "refactor_impact", "resolve_imports", "generate_tests",
    "validate_patch", "audit_dependencies", "ast_outline", "test_matrix", "security_audit",
    "git_status", "repo_state", "synthesize_commit", "verify", "affected_tests", "topology",
    "ast_refactor", "generate_mocks", "split_changes", "synthesize_rules", "code_invariants",
    "generate_dataset", "profile_digest", "callers", "callees", "implementations", "declaration", "dead_code", "secret_scan", "schema_inspect",
    "explain_query", "env_compat", "circular_dependencies", "generate_types", "complexity", "api_spec",
    "dependency_slice", "migration_drift", "package_audit", "structural_search", "context_budget",
    "git_diff", "git_history_search", "hotspots", "generate_tests_for_diff", "cross_repo_contract",
    "reachability_dead_code", "mutation_test", "type_stubs", "skeletonize", "investigate", "diagnose",
    "briefing", "batch_replace", "semantic", "intelligence", "pipeline", "preprocess",
    "preprocess_status", "preprocess_refresh", "preprocess_pause", "preprocess_resume", "preprocess_cancel",
    "preprocess_unregister", "context_compile", "verify_receipt", "verify_completion", "call_graph_diff",
    "semantic_diff", "cross_project_graph", "cross_project_symbols", "cross_project_impact",
    "cross_repo_graph", "cross_repo_symbols", "cross_repo_impact",
)
_TASK_ACTIONS = (
    "delegate", "explore", "reason", "continue", "review", "second_opinion", "compress", "route", "batch",
    "benchmark", "hardware_benchmark", "evaluation_record", "evaluation_report", "submit", "status", "wait",
    "result", "cancel", "candidate_create", "candidate_promote", "speculative_draft", "vision", "transcribe", "browser",
    "eval_suite", "prompt_eval", "eval_drift", "complete_code", "scaffold",
)
_RAG_ACTIONS = ("index", "search", "list", "docset_index", "docset_search", "ingest_document", "ingest_diagram")
_COMMAND_ACTIONS = (
    "run", "cancel", "classify", "discover", "stats", "repair_loop", "auto_fix", "run_affected", "format",
    "lint_fix", "spawn_daemon", "daemon_status", "stop_daemon", "http_probe", "stash_save", "stash_restore",
    "record_mock", "replay_mock", "diff_hunk_stage", "flaky_detect", "webhook_replay", "mock_server",
    "mock_server_start", "mock_server_stop", "mock_server_status", "patch_and_verify", "preflight",
    "speculative_lint",
)
_COORD_ACTIONS = (
    "claim", "renew", "release", "leases", "memo_put", "memo_get", "memo_search", "memo_delete",
    "task_create", "task_get", "task_checkpoint", "task_rollback", "task_transition", "task_resume", "task_list",
    "task_complete", "task_fail", "task_heartbeat", "ask", "answer", "memory_record", "memory_get", "memory_find",
    "memory_promote", "context_compile",
    "verify_receipt", "verify_completion", "verify_export", "negative_knowledge_record", "negative_knowledge_find", "incident_decision",
    "blackboard_update", "blackboard_get", "blackboard_list", "blackboard_merge", "blackboard_delete",
    "swarm_dispatch", "swarm_step", "swarm_status", "swarm_list", "swarm_cancel", "worktree_lease",
    "worktree_release", "pubsub_publish", "pubsub_poll", "simulate_merge", "curate_dataset", "task_sync",
    "task_zombie_reap", "task_cleanup_worktree",
)
_WORK_ACTIONS = ("submit", "status", "wait", "get", "cancel", "continue")
_ARTIFACT_ACTIONS = ("get", "slice", "list")
_ADOPTION_TOOL_NAMES = (
    "local_ai_status", "local_ai_repo", "local_ai_task", "local_ai_rag",
    "local_ai_command", "local_ai_coord", "local_ai_artifact", "local_ai_work",
)

_RESPONSE_BUDGET_PROPERTIES = {
    "max_response_tokens": {"type": "integer", "minimum": 0, "default": 0},
    "response_profile": {
        "type": "string",
        "enum": ["minimal", "compact", "standard", "debug", "delta"],
        "default": "compact",
    },
    "reuse_key": {"type": "string", "default": ""},
}


def _tool_contract(
    schema_key: str,
    feature_gate: str,
    selector_field: str,
    actions: tuple[str, ...],
    *,
    timeout: str,
    projection: str,
    default_effect: str = "read_only",
    feature_requirements: tuple[str, ...] = (),
    action_requirements: dict[str, tuple[str, ...]] | None = None,
    read_only: tuple[str, ...] = (),
    action_effects: dict[str, str] | None = None,
    required: dict[str, tuple[str, ...]] | None = None,
    non_empty: dict[str, tuple[str, ...]] | None = None,
    allowed: dict[str, tuple[str, ...]] | None = None,
    properties: dict[str, Any] | None = None,
    conditional_properties: dict[str, dict[str, Any]] | None = None,
    selector_required: bool = True,
) -> dict[str, Any]:
    return {
        "schema_key": schema_key,
        "feature_gate": feature_gate,
        "feature_requirements": feature_requirements,
        "selector_field": selector_field,
        "selector_required": selector_required,
        "timeout": timeout,
        "projection": projection,
        "properties": {
            **deepcopy(_RESPONSE_BUDGET_PROPERTIES),
            **deepcopy(properties or {}),
        },
        "conditional_properties": deepcopy(conditional_properties or {}),
        "action_order": actions,
        "actions": _action_contracts(
            actions,
            default_effect=default_effect,
            read_only=read_only,
            effects=action_effects,
            requirements=action_requirements,
            required=required,
            non_empty=non_empty,
            allowed=allowed,
        ),
    }


_REPO_MUTATIONS = (
    "batch_replace", "preprocess", "preprocess_refresh", "preprocess_pause", "preprocess_resume",
    "preprocess_cancel", "preprocess_unregister",
)
_REPO_CONDITIONS = {
    "batch_replace": ("batch_replacement",),
    "semantic": ("serena",),
    "intelligence": ("has_semantic",),
    "preprocess": ("preprocessing",),
    "preprocess_status": ("preprocessing",),
    "preprocess_refresh": ("preprocessing",),
    "preprocess_pause": ("preprocessing",),
    "preprocess_resume": ("preprocessing",),
    "preprocess_cancel": ("preprocessing",),
    "preprocess_unregister": ("preprocessing",),
    "context_compile": ("agent_os",),
    "verify_receipt": ("agent_os",),
    "verify_completion": ("agent_os",),
    "call_graph_diff": ("agent_os",),
    "semantic_diff": ("agent_os",),
    "cross_project_graph": ("agent_os",),
    "cross_project_symbols": ("agent_os",),
    "cross_project_impact": ("agent_os",),
    "cross_repo_graph": ("agent_os",),
    "cross_repo_symbols": ("agent_os",),
    "cross_repo_impact": ("agent_os",),
}
_ACTION_SCOPED_FIELDS = {
    "local_ai_task": {
        "url": frozenset({"browser"}),
        **{
            name: frozenset({"delegate", "explore", "reason", "review", "second_opinion", "compress"})
            for name in ("phase", "focus", "preload_profile", "repository_revision", "changed_paths")
        },
    },
    "local_ai_repo": {
        **{
            name: frozenset({"context_compile"})
            for name in (
                "include_diagnostics", "clone_id", "worktree_id", "branch",
                "repository_id", "session_id", "repository_revision",
            )
        },
        "steps": frozenset({"pipeline"}),
        "is_worktree": frozenset({"preprocess"}),
        "parent_root": frozenset({"preprocess"}),
        "path_hints": frozenset({"search", "context"}),
        "limit": frozenset({"search", "code_index"}),
        "offset": frozenset({"search", "code_index"}),
        "directory_hints": frozenset({"context"}),
        "exclude_paths": frozenset({"context"}),
        "force_include_paths": frozenset({"context"}),
        "receipt": frozenset({"verify_receipt"}),
        "old_symbol": frozenset({"ast_refactor"}),
        "new_symbol": frozenset({"ast_refactor"}),
        "old_code": frozenset({"semantic_diff"}),
        "new_code": frozenset({"semantic_diff"}),
        "rev1": frozenset({"git_diff"}),
        "rev2": frozenset({"git_diff"}),
    },
}
OPERATION_CONTRACTS: dict[str, dict[str, Any]] = {
    "local_ai_status": _tool_contract(
        "local_ai_status", "status", "detail", _STATUS_ACTIONS, timeout="quick: 180 seconds by default; configured MCP timeout applies",
        projection="status", read_only=_STATUS_ACTIONS, selector_required=False,
        action_requirements={"agent_state": ("agent_os",)},
        properties={
            "action": {"type": "string", "enum": ["status", "health", "check", "info"], "default": ""},
            "detail": {"type": "string", "default": "brief"},
            "scope": {"type": "string", "enum": ["process", "window"], "default": "process"},
            "adoption_signal": {"type": "string", "enum": ["", "bypassed"], "default": ""},
            "target_tool": {"type": "string", "enum": list(_ADOPTION_TOOL_NAMES)},
            "target_action": {"type": "string", "minLength": 1, "maxLength": 80,
                               "pattern": "^[a-z][a-z0-9_]{0,79}$"},
            "min_duration_ms": {"type": "integer", "minimum": 0, "maximum": 86400000, "default": 0},
            "trace_action": {"type": "string", "maxLength": 64, "default": ""},
            "extra_fields": {"type": "array", "items": {"type": "string"}},
        },
    ),
    "local_ai_repo": _tool_contract(
        "local_ai_repo", "repo", "action", _REPO_ACTIONS, timeout="action-specific: search max 120s, other quick 180s, context 600s, model 1800s, long 2400s",
        projection="repository result", action_requirements=_REPO_CONDITIONS,
        required={"verify_receipt": ("receipt",)},
        action_effects={name: "repository_state" for name in _REPO_MUTATIONS},
        read_only=tuple(name for name in _REPO_ACTIONS if name not in _REPO_MUTATIONS),
        properties={
            "action": {"type": "string"},
            "root": {"type": "string", "default": "."},
            "cwd": {"type": "string"},
            "query": {"type": "string", "default": ""},
            "symbol": {"type": "string"},
            "old_symbol": {"type": ["string", "null"], "default": None, "maxLength": 512},
            "new_symbol": {"type": ["string", "null"], "default": None, "maxLength": 512},
            "old_code": {"type": ["string", "null"], "default": None, "maxLength": 1_048_576},
            "new_code": {"type": ["string", "null"], "default": None, "maxLength": 1_048_576},
            "rev1": {"type": ["string", "null"], "default": None, "maxLength": 512},
            "rev2": {"type": ["string", "null"], "default": None, "maxLength": 512},
            "path": {"type": "string", "default": ""},
            "task": {"type": "string", "default": ""},
            "task_id": {"type": "string", "default": ""},
            "include_code": {"type": "boolean", "default": False},
            "limit": {"type": "integer", "minimum": 1, "maximum": MAX_PAGE_SIZE, "default": 24},
            "offset": {"type": "integer", "minimum": 0, "maximum": MAX_PAGE_WINDOW - 1, "default": 0},
            "include_diagnostics": {"type": "boolean", "default": False},
            **{name: {"type": "string", "default": ""} for name in (
                "clone_id", "worktree_id", "branch", "repository_id", "session_id", "repository_revision",
            )},
            "steps": {"type": "array", "items": {"type": "object"}},
            "is_worktree": {"type": "boolean", "default": False},
            "parent_root": {"type": "string", "default": ""},
            "path_hints": {
                "type": "array",
                "maxItems": 64,
                "items": {
                    "type": "object",
                    "required": ["path", "purpose", "scope"],
                    "properties": {
                        "path": {"type": "string", "minLength": 1, "maxLength": 1024},
                        "purpose": {"type": "string", "minLength": 1},
                        "scope": {"type": "string", "minLength": 1},
                        "evidence_id": {"type": "string"},
                        "provenance": {"type": "string"},
                        "repository_revision": {"type": "string"},
                        "config_digest": {"type": "string"},
                        "expires_at": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            },
            **{
                name: {
                    "type": "array",
                    "maxItems": 64,
                    "items": {"type": "string", "minLength": 1},
                }
                for name in ("directory_hints", "exclude_paths", "force_include_paths")
            },
            "include_tests": {"type": "boolean", "default": False},
            "phase": {"type": "string", "default": ""},
            "focus": {"type": "array", "items": {"type": "string"}},
            "preload_profile": {"type": "string", "default": ""},
            "guarded": {"type": "boolean", "default": False},
            "changed_paths": {"type": "array", "items": {"type": "string"}},
            "paths": {"type": "array", "items": {"type": "string"}},
            "files": {"type": "array", "items": {"type": "string"}},
            "since_hash": {"type": "string", "default": ""},
            "approval": {"type": ["boolean", "string"], "default": ""},
            "override_reason": {"type": "string", "default": ""},
            "base": {"type": "string", "default": "HEAD"},
            "staged": {"type": "boolean", "default": False},
            "mode": {"type": "string", "default": "adaptive"},
            "language": {"type": "string", "default": "auto"},
            "relation": {"type": "string", "default": ""},
            "profile": {"type": "string", "default": ""},
            "max_tokens": {"type": "integer", "default": 0},
            "token_budget": {"type": "integer", "default": 0},
            "diff": {"type": "string", "default": ""},
            "workspace": {"type": "string", "default": ""},
            "evidence": {"type": "array", "items": {"type": "object"}},
            "receipt": {
                "type": "object",
                "properties": {
                    "receipt_id": {"type": "string", "minLength": 1},
                    "task_id": {"type": "string", "minLength": 1},
                    "criterion": {"type": "string", "minLength": 1},
                    "passed": {"type": "boolean"},
                    "change_intent_id": {"type": "string"},
                    "evidence_id": {"type": "string"},
                    "command_id": {"type": "string"},
                    "repository_revision": {"type": "string"},
                    "observed_at": {"type": "number"},
                    "expires_at": {"type": ["number", "null"]},
                    "details": {"type": "object"},
                },
                "required": ["task_id", "criterion", "passed"],
                "allOf": [{
                    "if": {
                        "properties": {"passed": {"enum": [True]}},
                        "required": ["passed"],
                    },
                    "then": {
                        "required": ["evidence_id"],
                        "properties": {"evidence_id": {"minLength": 1}},
                    },
                }],
            },
            "session_id": {"type": "string", "default": ""},
            "clone_id": {"type": "string", "default": ""},
            "worktree_id": {"type": "string", "default": ""},
            "branch": {"type": "string", "default": ""},
            "repository_id": {"type": "string", "default": ""},
            "repository_revision": {"type": "string", "default": ""},
            "extra_fields": {"type": "array", "items": {"type": "string"}},
        },
        conditional_properties={
            "batch_replacement": {
                "dry_run": {"type": "boolean", "default": False},
                "edits": {"type": "array", "items": {"type": "object"}},
            },
        },
    ),
    "local_ai_task": _tool_contract(
        "local_ai_task", "tasks", "action", _TASK_ACTIONS, timeout="model 1800 seconds or long 2400 seconds; HubClient cap applies",
        projection="semantic result", default_effect="local_model_execution",
        feature_requirements=("has_any_model",), action_requirements={"vision": ("vision",)},
        read_only=("status", "wait", "result", "evaluation_report"),
        action_effects={
            "submit": "durable_job", "cancel": "durable_job", "candidate_create": "candidate_store",
            "candidate_promote": "candidate_store", "evaluation_record": "evaluation_store",
            "browser": "browser_capture",
        },
        properties={
            "action": {"type": "string"},
            "url": {"type": "string", "maxLength": 4096, "description": "Loopback HTTP(S) URL for bounded DOM and screenshot capture in the shared daemon."},
            "delivery": {"type": "string", "enum": ["sync", "async", "auto"], "default": "sync"},
            "phase": {"type": "string", "default": ""},
            "focus": {"type": "array", "items": {"type": "string"}},
            "preload_profile": {"type": "string", "default": ""},
            "repository_revision": {"type": "string", "default": ""},
            "changed_paths": {"type": "array", "items": {"type": "string"}},
            **{name: {"type": "string", "default": ""} for name in (
                "task", "context", "root", "profile", "conversation_id", "prompt", "model", "candidate",
                "image_artifact_id", "screenshot_artifact_id", "baseline_screenshot_artifact_id", "bundle_artifact_id", "dom_artifact_id",
                "accessibility_artifact_id", "computed_styles_artifact_id", "runtime_artifact_id",
                "network_artifact_id", "source", "job_id", "evaluation_task_id", "evaluation_cohort",
                "workspace", "approver", "task_id", "language",
            )},
            "complexity": {"type": "string", "default": "auto"},
            "job_action": {"type": "string", "default": "reason"},
            "max_tokens": {"type": "integer", "default": 0},
            "evaluation_days": {"type": "integer", "default": 30},
            "latency_budget_ms": {"type": "number", "default": 0},
            "timeout_seconds": {"type": "number", "default": 90},
            "evaluation_duration_ms": {"type": "number", "default": 0},
            "conversation": {"type": "boolean", "default": False},
            "cloud_fallback": {"type": "boolean", "default": False},
            "quality_pass": {"type": ["boolean", "null"]},
            "test_pass": {"type": ["boolean", "null"]},
            **{name: {"type": ["string", "object"]} for name in (
                "dom", "accessibility", "computed_styles", "runtime", "bundle", "accessibility_snapshot",
                "computed_style_data", "runtime_context",
            )},
            "html": {"type": "string"},
            "viewport": {"type": "object"},
            "page": {"type": "object"},
            "candidate_data": {"type": "object"},
            "json_schema": {"type": "object"},
            "tasks": {"type": "array", "items": {"type": "object"}},
            "cases": {"type": "array", "items": {"type": "object"}},
            "format": {"type": ["string", "object"]},
            "extra_fields": {"type": "array", "items": {"type": "string"}},
        },
    ),
    "local_ai_rag": _tool_contract(
        "local_ai_rag", "rag", "action", _RAG_ACTIONS, timeout="action-specific MCP timeout; HubClient cap applies",
        projection="retrieval result", read_only=("search", "list", "docset_search"),
        action_effects={
            "index": "index_store", "docset_index": "index_store", "ingest_document": "index_store",
            "ingest_diagram": "index_store",
        },
        properties={
            "action": {"type": "string"},
            "query": {"type": "string", "default": ""},
            "root": {"type": "string", "default": "."},
            "top_k": {"type": "integer", "default": 6},
            "workspace": {"type": "string", "default": ""},
            "content": {"type": "string", "default": ""},
            "title": {"type": "string", "default": ""},
            "metadata": {"type": "object"},
            "image_path": {"type": "string", "default": ""},
            "caption": {"type": "string", "default": ""},
            "extra_fields": {"type": "array", "items": {"type": "string"}},
        },
    ),
    "local_ai_command": _tool_contract(
        "local_ai_command", "commands", "action", _COMMAND_ACTIONS, timeout="action-specific command budget; client cap applies",
        projection="command result", default_effect="command_or_workspace_effect",
        read_only=("classify", "discover", "stats", "daemon_status", "http_probe", "mock_server_status", "preflight"),
        action_effects={name: "command_or_workspace_effect" for name in _COMMAND_ACTIONS},
        action_requirements={"speculative_lint": ("speculative_lint",)},
        properties={
            "action": {"type": "string"},
            "command": {"type": "string", "default": ""},
            "cwd": {"type": "string", "default": "."},
            "root": {"type": "string"},
            "runs": {"type": "integer", "description": "Number of executions to run for flaky detection", "minimum": 1, "default": 5},
            "env": {
                "type": "object",
                "description": "Environment variable overrides",
                "additionalProperties": {"type": "string"},
                "default": {},
            },
            "task_id": {"type": "string", "default": ""},
            "criterion": {"type": "string", "default": ""},
            "timeout": {"type": "integer", "default": 0},
            "stream": {"type": "boolean", "default": False},
            "stream_id": {"type": "string", "default": ""},
            "execution_id": {"type": "string", "default": ""},
            "paths": {"type": "array", "items": {"type": "string"}},
            "changed_paths": {"type": "array", "items": {"type": "string"}},
            "files": {"type": "array", "items": {"type": "string"}},
            "patch": {"type": "string", "default": ""},
            "auto_rollback": {"type": "boolean", "default": True},
            "job_id": {"type": "string", "default": ""},
            "lint_action": {"type": "string", "default": "submit"},
            "force": {"type": "boolean", "default": False},
            "auto_fix": {"type": "boolean", "default": False},
            "max_attempts": {"type": "integer", "default": 3},
            "snapshot": {"type": "boolean", "default": False},
            "rollback_on_failure": {"type": "boolean", "default": False},
            "extra_fields": {"type": "array", "items": {"type": "string"}},
        },
    ),
    "local_ai_coord": _tool_contract(
        "local_ai_coord", "coord", "action", _COORD_ACTIONS, timeout="action-specific coordination budget; HubClient cap applies",
        projection="coordination result", default_effect="coordination_state", read_only=(
            "leases", "memo_get", "memo_search", "task_get", "task_list", "memory_get", "memory_find",
            "blackboard_get", "blackboard_list", "swarm_status", "swarm_list", "pubsub_poll", "verify_export",
        ),
        action_requirements={name: ("agent_os",) for name in _COORD_ACTIONS[8:]},
        required={"ask": ("root", "session_id"), "answer": ("root", "question_id", "answer")},
        non_empty={
            "ask": ("root", "session_id"),
            "answer": ("root", "question_id", "answer"),
        },
        action_effects={name: "coordination_state" for name in _COORD_ACTIONS if name not in {
            "leases", "memo_get", "memo_search", "task_get", "task_list", "memory_get", "memory_find",
            "blackboard_get", "blackboard_list", "swarm_status", "swarm_list", "pubsub_poll", "verify_export",
        }},
        properties={
            "action": {"type": "string"},
            "root": {"type": "string", "default": "."},
            "paths": {"type": "array", "items": {"type": "string"}},
            **{name: {"type": "string", "default": ""} for name in (
                "lease_id", "task_id", "key", "value", "query", "command", "task", "status", "reason",
                "record_id", "target_scope", "approver", "criterion", "board_id", "section", "scope",
                "scope_id", "clone_id", "worktree_id", "branch", "repository_id", "session_id", "tenant",
                "repository_revision", "phase", "preload_profile", "since_hash", "format",
                "question_id", "question", "answer",
            )},
            "session_id": {"type": "string", "default": "", "maxLength": 256},
            "question_id": {"type": "string", "default": "", "maxLength": 80},
            "question": {"type": "string", "default": "", "maxLength": 16_384},
            "answer": {"type": "string", "default": "", "maxLength": 16_384},
            "ttl_seconds": {"type": "integer", "default": 0},
            "max_tokens": {"type": "integer", "default": 0},
            "contract": {"type": "object"},
            "checkpoint": {"type": "object"},
            "record": {"type": "object"},
            "fingerprint": {"type": "object"},
            "tool_outcome": {"type": "object"},
            "focus": {"type": "array", "items": {"type": "string"}},
            "include_diagnostics": {"type": "boolean", "default": False},
            "base": {"type": "string", "default": "HEAD"},
            "after_seq": {"type": "integer", "minimum": 0, "maximum": MAX_EVENT_SEQUENCE, "default": 0},
            "topic": {"type": "string", "default": ""},
            "include_stale": {"type": "boolean", "default": False},
            "extra_fields": {"type": "array", "items": {"type": "string"}},
        },
    ),
    "local_ai_artifact": {
        **_tool_contract(
            "local_ai_artifact", "artifacts", "action", _ARTIFACT_ACTIONS,
            timeout="HubClient.post default 360 seconds; capped by configured max_request_timeout_seconds",
            projection="artifact", read_only=_ARTIFACT_ACTIONS,
            required={"get": ("artifact_id",), "slice": ("artifact_id",)},
            non_empty={"get": ("artifact_id",), "slice": ("artifact_id",)},
            allowed={
                "get": ("artifact_id", "offset", "max_chars", "section", "binary", "slices"),
                "slice": ("artifact_id", "offset", "max_chars", "section", "binary", "slices"),
                "list": (),
            },
            selector_required=False,
            properties={
                "action": {"type": "string", "default": "get"},
                "artifact_id": {"type": "string", "default": ""},
                "section": {"type": "string", "default": ""},
                "offset": {"type": "integer", "minimum": 0, "default": 0},
                "max_chars": {"type": "integer", "minimum": 512, "maximum": 12000, "default": 4000},
                "extra_fields": {"type": "array", "items": {"type": "string"}},
                "binary": {"type": "boolean", "default": False},
                "slices": {
                    "type": "array", "minItems": 1, "maxItems": 16,
                    "items": {
                        "type": "object", "required": ["offset", "max_chars"],
                        "properties": {
                            "offset": {"type": "integer", "minimum": 0},
                            "max_chars": {"type": "integer", "minimum": 1, "maximum": 50000},
                        },
                        "additionalProperties": False,
                    },
                },
            },
        ),
        "default_action": "get",
        "description": "Fetch exact source, evidence, or artifact content. Actions: {actions}.",
    },
    "local_ai_work": _tool_contract(
        "local_ai_work", "work_orchestrator", "action", _WORK_ACTIONS, timeout="work-order timeout is bounded by its request budget",
        projection="verified work-order handoff", read_only=("status", "wait", "get"),
        required={"submit": ("root", "task"), "status": ("work_id",), "wait": ("work_id",),
                  "get": ("work_id",), "cancel": ("work_id",), "continue": ("work_id", "answer")},
        non_empty={"submit": ("root", "task"), "status": ("work_id",), "wait": ("work_id",),
                   "get": ("work_id",), "cancel": ("work_id",), "continue": ("work_id", "answer")},
        action_effects={name: "work_order_state" for name in ("submit", "cancel", "continue")},
        properties={
            "action": {"type": "string"},
            "root": {"type": "string", "default": ""},
            "task": {"type": "string", "default": ""},
            "work_id": {"type": "string", "default": ""},
            "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
            "constraints": {"type": "array", "items": {"type": "string"}},
            "mode": {"type": "string", "enum": ["execute", "plan", "plan_only", "dry_run"], "default": "execute"},
            "permissions": {"type": "object"},
            "budget": {"type": "object"},
            "timeout_seconds": {"type": "number", "default": 90},
            "answer": {"type": "string", "default": ""},
            "return_fields": {"type": "array", "items": {"type": "string"}},
            "response_profile": deepcopy(_RESPONSE_BUDGET_PROPERTIES["response_profile"]),
            "extra_fields": {"type": "array", "items": {"type": "string"}},
            "max_output_tokens": {"type": "integer", "default": 0},
            "keep_failed_workspace": {"type": "boolean", "default": False},
        },
    ),
}


def operation_contract(tool: str) -> dict[str, Any] | None:
    """Return the authored contract for a tool, if it has one."""
    return OPERATION_CONTRACTS.get(tool)


def operation_guide_cards(features: Any = None) -> dict[str, Any]:
    """Small, feature-aware examples derived from the same public action contracts."""
    examples = {
        "local_ai_status": {"detail": "guide"},
        "local_ai_repo": {"action": "context", "root": "ABS_ROOT", "task": "Bounded repository question", "mode": "adaptive"},
        "local_ai_command": {"action": "classify", "command": "python -m pytest tests/unit/ -q"},
        "local_ai_task": {"action": "delegate", "task": "Summarize supplied evidence", "context": "EVIDENCE"},
        "local_ai_rag": {"action": "search", "root": "ABS_ROOT", "query": "Meaning to retrieve"},
        "local_ai_coord": {"action": "memo_search", "root": "ABS_ROOT", "query": "Known finding"},
        "local_ai_artifact": {"action": "slice", "artifact_id": "ARTIFACT_ID", "offset": 0, "max_chars": 1000},
        "local_ai_work": {"action": "status", "work_id": "WORK_ID"},
    }
    tips = {
        "local_ai_status": "One bounded check; guide is local and does not query runtime health.",
        "local_ai_repo": "Context first; reuse evidence; fetch exact slices only when needed.",
        "local_ai_command": "Reuse cached receipts; full output is artifact-backed when available.",
        "local_ai_task": "Supply bounded evidence; deterministic tools establish exact facts.",
        "local_ai_rag": "Use after indexed retrieval is insufficient; scope the repository.",
        "local_ai_coord": "Reuse existing tasks and findings; preserve ownership and scope.",
        "local_ai_artifact": "Slice exact evidence rather than replaying full payloads.",
        "local_ai_work": "Closed delegation only when explicitly requested; reuse the work ID.",
    }
    cards = []
    for tool, example in examples.items():
        if not operation_enabled(features, tool):
            continue
        contract = OPERATION_CONTRACTS[tool]
        selector = contract["selector_field"]
        selected = str(example.get(selector, ""))
        enabled = operation_actions(tool, features)
        if selected not in enabled:
            continue
        action_contract = contract["actions"][selected]
        cards.append({
            "tool": tool, "selector": selector,
            "required": ([selector] if contract["selector_required"] else []) + list(action_contract["required"]),
            "required_scope": selected,
            "example": dict(example),
            "action_count": len(enabled),
            "tip": tips[tool],
        })
    return {
        "success": True, "guide_cards": cards,
        "guide_scope": "enabled_tools_and_example_action_requirements",
        "guide_tips": ["Use response_profile=compact and stable reuse_key.",
                       "Examples contain placeholders; guide calls execute none of them.",
                       "Full schemas remain authoritative for other actions and optional fields."],
        "schema_token_reduction_verified": False,
    }


def operation_actions(tool: str, features: Any = None) -> tuple[str, ...]:
    """Return selector values enabled by a feature snapshot, in stable order."""
    contract = operation_contract(tool)
    if contract is None:
        return ()
    return tuple(
        action
        for action in contract["action_order"]
        if _requirements_met(features, contract["actions"][action].get("requires", ()))
    )


def operation_metadata(tool: str) -> dict[str, Any]:
    """Return the serializable contract metadata published with generated schemas."""
    contract = operation_contract(tool)
    if contract is None:
        return {}
    raw = {
        "schema_key": contract["schema_key"],
        "feature_gate": contract["feature_gate"],
        "feature_requirements": contract["feature_requirements"],
        "selector_field": contract["selector_field"],
        "timeout": contract["timeout"],
        "projection": contract["projection"],
        "actions": contract["actions"],
    }
    # Preserve the registry's exact Python contract shape (including tuples).
    # Tuples remain JSON-serializable as arrays, while the JSON round-trip here
    # made generated metadata compare differently from the authoritative registry.
    return deepcopy(raw)


def operation_input_schema(tool: str, action: str) -> dict[str, Any]:
    """Return permissive tool arguments narrowed to one registered action."""
    contract = operation_contract(tool)
    if contract is None or action not in contract["actions"]:
        return {"type": "object", "properties": {}}

    schema = operation_parameters_schema(tool)
    selector = str(contract.get("selector_field", "action"))
    properties = schema.setdefault("properties", {})
    properties[selector] = {**properties.get(selector, {}), "enum": [action]}
    for field, scoped_actions in _ACTION_SCOPED_FIELDS.get(tool, {}).items():
        if action not in scoped_actions:
            properties.pop(field, None)
    allowed = contract["actions"][action].get("allowed")
    if allowed is not None:
        common = set(_RESPONSE_BUDGET_PROPERTIES) | {"extra_fields", selector}
        schema["properties"] = {
            name: value for name, value in properties.items()
            if name in common or name in allowed
        }
    required = [selector, *contract["actions"][action].get("required", ())]
    schema["required"] = list(dict.fromkeys(required))
    return schema


def operation_tool_input_schema(tool: str, features: Any = None) -> dict[str, Any]:
    """Return the MCP tool schema with action-specific requirements encoded."""
    contract = operation_contract(tool)
    if contract is None:
        return {"type": "object", "properties": {}, "additionalProperties": False}

    actions = operation_actions(tool, features)
    schema = operation_parameters_schema(tool, features)
    selector = str(contract.get("selector_field", "action"))
    properties = schema.setdefault("properties", {})
    selector_schema = properties.setdefault(selector, {"type": "string"})
    selector_schema["enum"] = list(actions)
    schema["additionalProperties"] = False

    conditions: list[dict[str, Any]] = []
    for action in actions:
        action_contract = contract["actions"][action]
        required = list(action_contract.get("required", ()))
        allowed = action_contract.get("allowed")
        disallowed = (
            set(schema["properties"])
            - set(allowed)
            - set(_RESPONSE_BUDGET_PROPERTIES)
            - {"extra_fields", selector}
            if allowed is not None else set()
        )
        for field, scoped_actions in _ACTION_SCOPED_FIELDS.get(tool, {}).items():
            if action not in scoped_actions:
                disallowed.add(field)
        then: dict[str, Any] = {}
        if required:
            then["required"] = list(dict.fromkeys((selector, *required)))
        if disallowed:
            then["not"] = {"anyOf": [{"required": [field]} for field in sorted(disallowed)]}
        if not then:
            continue
        conditions.append({
            "if": {
                "properties": {selector: {"const": action}},
                "required": [selector],
            },
            "then": then,
        })
    if tool == "local_ai_repo" and "context" in actions:
        for field in ("path_hints", "directory_hints", "exclude_paths", "force_include_paths"):
            conditions.append({
                "if": {
                    "properties": {
                        "action": {"const": "context"},
                        "mode": {"not": {"const": "adaptive"}},
                    },
                    "required": ["action", "mode"],
                },
                "then": {"not": {"required": [field]}},
            })
    if conditions:
        schema["allOf"] = conditions
    else:
        schema.pop("allOf", None)
    return schema


def operation_output_schema(tool: str, action: str) -> dict[str, Any]:
    """Return an action-specific result schema grounded in known payload fields."""
    contract = operation_contract(tool)
    if contract is None or action not in contract["actions"]:
        return {"type": "object", "properties": {}, "additionalProperties": True}

    properties: dict[str, Any] = {
        "success": {"type": "boolean"},
        "error": {"type": "string"},
        "terminal": {"type": "boolean"},
        "retryable": {"type": "boolean"},
        "degraded": {"type": "boolean"},
        "stale": {"type": "boolean"},
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
        "cancelled": {"type": "boolean"},
        "cancel_requested": {"type": "boolean"},
        "cancel_reason": {"type": "string"},
    }
    schema = {
        "type": "object",
        "title": f"{tool}.{action} result",
        "description": f"{contract['projection']} result for action '{action}'.",
        "properties": properties,
        "additionalProperties": True,
    }
    if tool == "local_ai_artifact":
        schema["anyOf"] = _artifact_output_variants(action)
    elif tool == "local_ai_status":
        status_variants = _status_output_variants(action)
        if status_variants:
            schema["anyOf"] = status_variants
    elif tool == "local_ai_rag" and action == "search":
        schema["properties"].update({
            "workspace": {"type": "string"},
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "chunk_no": {"type": "integer"},
                        "text": {"type": "string"},
                        "content_hash": {"type": "string"},
                        "score": {"type": "number"},
                    },
                    "additionalProperties": True,
                },
            },
            "fallback": {"type": "string"},
            "retrieval_mode": {"type": "string"},
            "lexical_backend": {"type": "string"},
            "reason": {"type": "string"},
        })
    return schema


def _status_output_variants(action: str) -> list[dict[str, Any]]:
    """Describe stable fields emitted by the MCP status projections."""
    failure = {
        "type": "object",
        "required": ["success", "error"],
        "properties": {"success": {"const": False}, "error": {"type": "string"}},
        "additionalProperties": True,
    }
    if action == "guide":
        return [{
            "type": "object", "required": ["success", "guide_cards", "guide_scope"],
            "properties": {
                "success": {"const": True}, "guide_scope": {"type": "string"},
                "guide_cards": {"type": "array", "maxItems": 8, "items": {
                    "type": "object", "required": ["tool", "selector", "required", "example", "tip"],
                    "properties": {
                        "tool": {"type": "string"}, "selector": {"type": "string"},
                        "required": {"type": "array", "items": {"type": "string"}},
                        "example": {"type": "object"}, "tip": {"type": "string"},
                    }, "additionalProperties": True,
                }},
                "schema_token_reduction_verified": {"const": False},
            }, "additionalProperties": True,
        }, failure]
    if action == "brief":
        return [{
            "type": "object",
            "required": ["success", "version", "ollama_online", "active_model", "queued", "inflight"],
            "properties": {
                "success": {"type": "boolean"},
                "version": {"type": ["string", "null"]},
                "ollama_online": {"type": ["boolean", "null"]},
                "active_model": {"type": ["string", "null"]},
                "queued": {"type": ["integer", "null"]},
                "inflight": {"type": ["integer", "null"]},
                "net_cloud_token_delta_est": {"type": "number"},
                "cache_hits": {"type": "integer"},
                "coalesced_waiters": {"type": "integer"},
                "vram_pressure": {"type": "string"},
                "context_budget_factor": {"type": "number"},
            },
            "additionalProperties": True,
        }, failure]
    if action == "cache":
        object_or_null = {"type": ["object", "null"]}
        return [{
            "type": "object",
            "required": ["success", "generation_cache", "semantic_cache", "repo_cache", "repo_snapshots",
                         "commands", "lossless_router", "pipeline", "preprocessing", "tool_agent",
                         "circuit_breakers", "fallback_count", "embeddings", "reranker", "token_saving", "context_ledger"],
            "properties": {
                "success": {"type": "boolean"},
                "generation_cache": object_or_null, "semantic_cache": object_or_null,
                "repo_cache": object_or_null, "repo_snapshots": object_or_null,
                "commands": object_or_null, "lossless_router": object_or_null,
                "pipeline": object_or_null, "preprocessing": object_or_null,
                "tool_agent": object_or_null, "circuit_breakers": object_or_null,
                "fallback_count": {"type": ["integer", "null"]},
                "embeddings": object_or_null, "reranker": object_or_null,
                "token_saving": object_or_null, "context_ledger": {"type": "object"},
            },
            "additionalProperties": True,
        }, failure]
    if action == "telemetry":
        summary_fields = {
            name: {"type": "number"}
            for name in ("events", "cache_hits", "coalesced", "input_tokens", "output_tokens",
                         "avoided_cloud_tokens", "avg_duration_ms", "failure_rate", "avg_queue_wait_ms",
                         "fallback_count", "degraded_count", "retry_count", "cache_hit_rate",
                         "net_cloud_token_delta_est")
        }
        return [{
            "type": "object",
            "required": ["success", "window", "summary", "queue", "hotspots", "by_operation",
                         "error_fingerprints", "detail", "decision_grade"],
            "properties": {
                "success": {"type": "boolean"}, "window": {"type": "object"},
                "summary": {"type": "object", "properties": summary_fields, "additionalProperties": True},
                "queue": {"type": "object"}, "hotspots": {"type": "array", "items": {"type": "object"}},
                "by_operation": {"type": "array", "items": {"type": "object"}},
                "error_fingerprints": {"type": "array", "items": {"type": "object"}},
                "detail": {"type": "object"}, "decision_grade": {"type": "object"},
            },
            "additionalProperties": True,
        }, failure]
    if action == "full":
        return [{
            "type": "object",
            "required": ["success", "hub_online", "version"],
            "properties": {
                "success": {"type": "boolean"},
                "hub_online": {"type": "boolean"},
                "version": {"type": "string"},
                **{name: {} for name in (
                    "uptime_seconds", "features", "runtime_stats", "capabilities", "ollama_online",
                    "models", "hardware", "accelerators", "code_intelligence", "runtime_profile",
                    "scheduler", "headless", "background_gpu", "ollama_profile", "model_execution",
                    "vram_balancer", "benchmark", "debug_traces", "observability", "preprocessing",
                    "agent_state", "http_concurrency",
                )},
            },
            # Diagnostic keys are versioned independently by the status API. Keep
            # the stable identity contract above, but preserve forward-compatible
            # diagnostics without rejecting null or newly shaped values.
            "additionalProperties": True,
        }, failure]
    if action == "agent_state":
        return [{
            "type": "object",
            "required": ["success", "enabled", "active_tasks", "tasks_count", "incidents_count",
                         "candidates_count", "status"],
            "properties": {
                "success": {"type": "boolean"},
                "enabled": {"type": "boolean"},
                "active_tasks": {"type": "array", "items": {"type": "string"}},
                "tasks_count": {"type": "integer"},
                "incidents_count": {"type": "integer"},
                "candidates_count": {"type": "integer"},
                "status": {"type": "string"},
            },
            "additionalProperties": True,
        }, failure]
    return []


def _artifact_output_variants(action: str) -> list[dict[str, Any]]:
    """Return result variants from the artifact, evidence, and HTTP handlers."""
    failure = {
        "type": "object",
        "required": ["success", "error"],
        "properties": {"success": {"const": False}, "error": {"type": "string"}},
        "additionalProperties": True,
    }
    if action == "list":
        item = {
            "type": "object",
            "required": ["artifact_id", "kind", "size_bytes", "created_at", "mime_type"],
            "properties": {
                "artifact_id": {"type": "string"},
                "kind": {"type": "string"},
                "size_bytes": {"type": "integer"},
                "created_at": {"type": "number"},
                "mime_type": {"type": "string"},
            },
            "additionalProperties": True,
        }
        return [
            {
                "type": "object",
                "required": ["success", "artifacts"],
                "properties": {
                    "success": {"const": True},
                    "artifacts": {"type": "array", "items": item},
                },
                "additionalProperties": True,
            },
            failure,
        ]

    text_result = {
        "type": "object",
        "required": ["success", "artifact_id", "kind", "text", "offset", "next_offset", "total_chars", "sections"],
        "properties": {
            "success": {"const": True}, "artifact_id": {"type": "string"},
            "kind": {"type": "string"}, "text": {"type": "string"},
            "offset": {"type": "integer"}, "next_offset": {"type": ["integer", "null"]},
            "total_chars": {"type": "integer"},
            "sections": {"type": "array", "items": {"type": "string"}},
        },
        "additionalProperties": True,
    }
    evidence_result = {
        "type": "object",
        "required": ["success", "evidence_id", "root", "path", "file_sha256", "start_line", "end_line", "text", "stale"],
        "properties": {
            "success": {"const": True}, "evidence_id": {"type": "string"},
            "root": {"type": "string"}, "path": {"type": "string"},
            "file_sha256": {"type": "string"}, "start_line": {"type": "integer"},
            "end_line": {"type": "integer"}, "text": {"type": "string"},
            "stale": {"type": "boolean"},
        },
        "additionalProperties": True,
    }
    binary_result = {
        "type": "object",
        "required": ["success", "artifact_id", "kind", "mime_type", "encoding", "size_bytes", "checksum", "sha256", "identity", "binary_payload"],
        "properties": {
            "success": {"const": True}, "artifact_id": {"type": "string"},
            "kind": {"type": "string"}, "mime_type": {"type": "string"},
            "encoding": {"type": "string"}, "size_bytes": {"type": "integer"},
            "checksum": {"type": "string"}, "sha256": {"type": "string"},
            "identity": {"type": "object"}, "binary_payload": {"type": "string"},
        },
        "additionalProperties": True,
    }
    multi_slice_result = {
        "type": "object",
        "required": ["success", "artifact_id", "kind", "slices", "total_chars", "sections", "truncated", "budget_limited"],
        "properties": {
            "success": {"const": True}, "artifact_id": {"type": "string"},
            "kind": {"type": "string"}, "total_chars": {"type": "integer"},
            "sections": {"type": "array", "items": {"type": "string"}},
            "truncated": {"type": "boolean"}, "budget_limited": {"type": "boolean"},
            "slices": {"type": "array", "maxItems": 16, "items": {
                "type": "object", "required": ["offset", "text"],
                "properties": {"offset": {"type": "integer"}, "text": {"type": "string"}},
                "additionalProperties": True,
            }},
        },
        "additionalProperties": True,
    }
    return [text_result, multi_slice_result, evidence_result, binary_result, failure]


_OPEN_OUTPUT_OBJECT = {"type": "object", "additionalProperties": True}
_OUTPUT_ENVELOPE_PROPERTIES: dict[str, dict[str, Any]] = {
    "success": {"type": "boolean"},
    "status": {"type": "string"},
    "status_code": {"type": "integer"},
    "error": {"type": "string"},
    "warning": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    "message": {"type": "string"},
    "hub_online": {"type": "boolean"},
    "terminal": {"type": "boolean"},
    "retryable": {"type": "boolean"},
    "degraded": {"type": "boolean"},
    "stale": {"type": "boolean"},
    "fallback_used": {"type": "boolean"},
    "requires_override": {"type": "boolean"},
    "requires_approval": {"type": "boolean"},
    "decision_recorded": {"type": "boolean"},
    "decision_persisted": {"type": "boolean"},
    "task_status": {"type": "string"},
    "waiting": {"type": "boolean"},
    "context_id": {"type": "string"},
    "response_budget": _OPEN_OUTPUT_OBJECT,
    "warnings": {"type": "array", "items": {"anyOf": [{"type": "string"}, _OPEN_OUTPUT_OBJECT]}},
    "warning_ids": {"type": "array", "items": {"type": "string"}},
    "retry_after_seconds": {"type": "number"},
    "outcome_unknown": {"type": "boolean"},
    "request_not_sent": {"type": "boolean"},
    "retried": {"type": "boolean"},
    "evidence_ids": {"type": "array", "items": {"type": "string"}},
    "evidence": {"type": "array", "items": _OPEN_OUTPUT_OBJECT},
    "cancel": _OPEN_OUTPUT_OBJECT,
    "cancel_requested": {"type": "boolean"},
    "cancelled": {"type": "boolean"},
    "cancel_reason": {"type": "string"},
    "timed_out": {"type": "boolean"},
    "complete": {"type": "boolean"},
    "partial": {"type": "boolean"},
    "truncated": {"type": "boolean"},
    "budget_limited": {"type": "boolean"},
    "estimated_tokens": {"type": "integer"},
    "reuse_key": {"type": "string"},
    "reused": {"type": "boolean"},
    "unchanged": {"type": "boolean"},
    "request_id": {"type": "string"},
    "unsupported": {"type": "boolean"},
}


def _output_payload_delta(schema: dict[str, Any]) -> dict[str, Any]:
    properties = schema.get("properties", {})
    delta = {
        name: value for name, value in properties.items()
        if name not in _OUTPUT_ENVELOPE_PROPERTIES
    }
    if "anyOf" in schema:
        delta["anyOf"] = schema["anyOf"]
    return delta


def operation_tool_output_schema(tool: str, features: Any = None) -> dict[str, Any]:
    """Publish the common envelope and compact action-specific output contracts."""
    enabled_actions = operation_actions(tool, features) if operation_enabled(features, tool) else ()
    action_schemas = {
        action: delta
        for action in enabled_actions
        if (delta := _output_payload_delta(operation_output_schema(tool, action)))
    }
    return {
        "type": "object",
        "properties": {key: dict(value) for key, value in _OUTPUT_ENVELOPE_PROPERTIES.items()},
        "additionalProperties": True,
        "x-action-output-contracts": action_schemas,
    }


def _validate_output_schema(value: Any, schema: dict[str, Any], path: str = "result") -> str | None:
    expected = schema.get("type")
    if expected is not None and not _matches_json_type(value, expected):
        return f"{path} has the wrong JSON type"
    if "const" in schema and value != schema["const"]:
        return f"{path} must equal {schema['const']!r}"
    if isinstance(value, dict):
        for field in schema.get("required", ()):
            if field not in value:
                return f"{path}.{field} is required"
        for field, field_schema in schema.get("properties", {}).items():
            if field in value and isinstance(field_schema, dict):
                error = _validate_output_schema(value[field], field_schema, f"{path}.{field}")
                if error:
                    return error
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            error = _validate_output_schema(item, schema["items"], f"{path}[{index}]")
            if error:
                return error
    variants = schema.get("anyOf")
    if isinstance(variants, list) and variants:
        if not any(_validate_output_schema(value, branch, path) is None for branch in variants):
            return f"{path} does not match a declared output variant"
    return None


def validate_operation_output(tool: str, action: str, result: Any) -> str | None:
    """Validate shared response-envelope fields while preserving payload fields."""
    contract = operation_contract(tool)
    if contract is None or action not in contract["actions"]:
        return None
    if not isinstance(result, dict):
        return "result must be an object"
    for field in ("success", "terminal", "retryable"):
        if field in result and not isinstance(result[field], bool):
            return f"{field} must be boolean for action='{action}'"
    if "error" in result and not isinstance(result["error"], str):
        return f"error must be string for action='{action}'"
    if tool in {"local_ai_artifact", "local_ai_status"}:
        error = _validate_output_schema(result, operation_output_schema(tool, action))
        if error:
            return f"{error} for action='{action}'"
    return None


def operation_enabled(features: Any, tool: str) -> bool:
    """Resolve a contract's named feature gate against a FeatureSet-like object."""
    contract = operation_contract(tool)
    gate = contract.get("feature_gate") if contract else None
    if not gate or not _requirements_met(features, (str(gate),)):
        return False
    return _requirements_met(features, contract.get("feature_requirements", ()))


def _requirements_met(features: Any, requirements: tuple[str, ...] | list[str]) -> bool:
    if features is None:
        return True
    for requirement in requirements:
        value = getattr(features, str(requirement), False)
        if callable(value):
            value = value()
        if not value:
            return False
    return True


def operation_parameters_schema(tool: str, features: Any = None) -> dict[str, Any]:
    """Build a feature-filtered JSON Schema parameter object from the registry."""
    contract = operation_contract(tool)
    if contract is None:
        return {"type": "object", "properties": {}}

    properties = deepcopy(contract.get("properties", {}))
    if not properties:
        return {"type": "object", "properties": {}}
    selector_field = str(contract.get("selector_field", "action"))
    available_actions = operation_actions(tool, features)
    for field in {selector_field, "action"}:
        if field in properties:
            field_actions = list(available_actions)
            if field == "action" and field != selector_field:
                field_actions.extend(
                    action for action in properties[field].get("enum", ())
                    if action not in field_actions
                )
            properties[field]["enum"] = field_actions
    for requirements, conditional_properties in contract.get("conditional_properties", {}).items():
        if _requirements_met(features, (str(requirements),)):
            properties.update(deepcopy(conditional_properties))

    if tool == "local_ai_repo":
        properties["phase"] = {"type": "string", "enum": list(REPO_PHASES), "default": ""}
        for field in ("max_tokens", "token_budget"):
            properties[field].update(minimum=0, maximum=100000)
        properties["steps"] = {
            "type": "array", "items": repo_pipeline_step_schema(properties, available_actions),
        }
    if tool == "local_ai_coord":
        properties["max_tokens"].update(minimum=0, maximum=100000)

    parameters: dict[str, Any] = {"type": "object", "properties": properties}
    if contract.get("selector_required", True):
        parameters["required"] = [selector_field]

    action_contracts = [
        (action, contract["actions"][action])
        for action in available_actions
        if action in contract["actions"]
    ]
    required_actions = [(action, row) for action, row in action_contracts if row["required"]]
    optional_actions = [action for action, row in action_contracts if not row["required"]]
    required_sets = {tuple(row["required"]) for _, row in required_actions}
    non_empty_sets = {tuple(row.get("non_empty", ())) for _, row in required_actions}
    if (
        required_actions
        and optional_actions
        and len(required_actions) > 1
        and len(required_sets) == 1
        and len(non_empty_sets) == 1
    ):
        required_fields = sorted(next(iter(required_sets)))
        non_empty_fields = sorted(next(iter(non_empty_sets)))
        parameters["allOf"] = [{
            "if": {
                "properties": {selector_field: {"enum": optional_actions}},
                "required": [selector_field],
            },
            "then": {},
            "else": {
                "required": required_fields,
                "properties": {field: {"minLength": 1} for field in non_empty_fields},
            },
        }]
    elif required_actions:
        parameters["allOf"] = [
            {
                "if": {
                    "properties": {selector_field: {"enum": [action]}},
                    "required": [selector_field],
                },
                "then": {
                    "required": list(row["required"]),
                    "properties": {
                        field: {"minLength": 1}
                        for field in row.get("non_empty", ())
                    },
                },
            }
            for action, row in required_actions
        ]
    return parameters


def validate_operation_call(
    tool: str,
    arguments: dict[str, Any],
    *,
    features: Any = None,
) -> tuple[int, str] | None:
    """Validate a registered MCP call before its handler is dispatched."""
    contract = operation_contract(tool)
    if contract is None:
        return None
    if not isinstance(arguments, dict):
        return 400, "arguments must be an object"
    if not operation_enabled(features, tool):
        return 403, f"{tool} is disabled in configuration"

    selector = str(contract.get("selector_field", "action"))
    if tool == "local_ai_status" and "action" in arguments:
        alias = arguments.get("action")
        normalized_alias = alias.strip().lower() if isinstance(alias, str) else ""
        if normalized_alias in contract["actions"]:
            selector_value = normalized_alias
        else:
            selector_value = arguments.get(selector, "brief")
    elif selector not in arguments:
        selector_schema = operation_parameters_schema(tool, features).get("properties", {}).get(selector, {})
        selector_value = selector_schema.get("default")
    else:
        selector_value = arguments[selector]
    error = validate_operation_arguments(
        tool,
        selector_value,
        arguments,
        features=features,
    )
    return (400, error) if error is not None else None


def _matches_json_type(value: Any, expected: Any) -> bool:
    expected_types = expected if isinstance(expected, list) else [expected]
    recognized = False
    for expected_type in expected_types:
        if expected_type not in {"string", "integer", "number", "boolean", "object", "array", "null"}:
            continue
        recognized = True
        if expected_type == "string" and isinstance(value, str):
            return True
        if expected_type == "integer" and type(value) is int:
            return True
        if expected_type == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
            try:
                if math.isfinite(value):
                    return True
            except OverflowError:
                pass
        if expected_type == "boolean" and type(value) is bool:
            return True
        if expected_type == "object" and isinstance(value, dict):
            return True
        if expected_type == "array" and isinstance(value, list):
            return True
        if expected_type == "null" and value is None:
            return True
    return not recognized


def _non_finite_number_path(value: Any, path: str) -> str | None:
    pending = [(value, path)]
    while pending:
        current, current_path = pending.pop()
        if isinstance(current, float) and not math.isfinite(current):
            return current_path
        if isinstance(current, dict):
            pending.extend((item, f"{current_path}.{key}") for key, item in current.items())
        elif isinstance(current, list):
            pending.extend((item, f"{current_path}[{index}]") for index, item in enumerate(current))
    return None


def _validate_nested_schema(value: Any, schema: dict[str, Any], path: str, action: str) -> str | None:
    """Validate declared constraints recursively for nested registry values."""
    expected = schema.get("type")
    if expected is not None and not _matches_json_type(value, expected):
        expected_types = expected if isinstance(expected, list) else [expected]
        expected_label = " or ".join(str(item) for item in expected_types)
        return f"{path} must be {expected_label} for action='{action}'"

    allowed_values = schema.get("enum")
    if allowed_values is not None and value not in allowed_values:
        values = ", ".join(str(item) for item in allowed_values)
        return f"{path} must be one of {values} for action='{action}'"
    if isinstance(value, str):
        if "minLength" in schema and len(value) < int(schema["minLength"]):
            return f"{path} must have at least {schema['minLength']} characters for action='{action}'"
        if "maxLength" in schema and len(value) > int(schema["maxLength"]):
            return f"{path} must have at most {schema['maxLength']} characters for action='{action}'"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and not math.isfinite(value):
            return f"{path} must be finite for action='{action}'"
        if "minimum" in schema and value < schema["minimum"]:
            return f"{path} must be >= {schema['minimum']} for action='{action}'"
        if "maximum" in schema and value > schema["maximum"]:
            return f"{path} must be <= {schema['maximum']} for action='{action}'"
    if isinstance(value, list):
        if "minItems" in schema and len(value) < int(schema["minItems"]):
            return f"{path} must have at least {schema['minItems']} items for action='{action}'"
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            return f"{path} must have at most {schema['maxItems']} items for action='{action}'"
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                error = _validate_nested_schema(item, item_schema, f"{path}[{index}]", action)
                if error:
                    return error
    if isinstance(value, dict):
        for field in schema.get("required", ()):
            if field not in value:
                return f"{path}.{field} is required for action='{action}'"
        if schema.get("additionalProperties") is False:
            unknown = sorted(set(value) - set(schema.get("properties", {})))
            if unknown:
                return f"{path} contains unsupported fields: {', '.join(unknown)}"
        for field, field_schema in schema.get("properties", {}).items():
            if field in value and isinstance(field_schema, dict):
                error = _validate_nested_schema(value[field], field_schema, f"{path}.{field}", action)
                if error:
                    return error
    return None


def validate_operation_arguments(
    tool: str,
    action: Any,
    arguments: dict[str, Any],
    *,
    features: Any = None,
) -> str | None:
    """Validate supported action, per-action required fields, and declared JSON types."""
    contract = operation_contract(tool)
    if contract is None:
        return f"no operation contract is registered for {tool!r}"
    available_actions = operation_actions(tool, features)
    if not isinstance(action, str) or action not in available_actions:
        supported = ", ".join(available_actions)
        return f"invalid action for {tool}: expected one of {supported}"

    properties = operation_parameters_schema(tool, features).get("properties", {})
    if isinstance(properties, dict):
        unknown = sorted(set(arguments) - set(properties))
        if unknown:
            return f"unexpected argument for {tool}: {unknown[0]}"

    action_contract = contract["actions"][action]
    allowed = action_contract.get("allowed")
    if allowed is not None:
        common = set(_RESPONSE_BUDGET_PROPERTIES) | {"extra_fields", contract["selector_field"]}
        unexpected = sorted(set(arguments) - set(allowed) - common)
        if unexpected:
            return f"{unexpected[0]} is not valid for action='{action}'"
    for field, scoped_actions in _ACTION_SCOPED_FIELDS.get(tool, {}).items():
        if field in arguments and action not in scoped_actions:
            scoped_names = sorted(scoped_actions)
            if len(scoped_names) == 1:
                return f"{field} is only valid for action='{scoped_names[0]}'"
            return f"{field} is only valid for actions {scoped_names}"
    if tool == "local_ai_repo" and action == "context":
        mode = arguments.get("mode", properties.get("mode", {}).get("default", "adaptive"))
        if mode != "adaptive":
            for field in ("path_hints", "directory_hints", "exclude_paths", "force_include_paths"):
                if field in arguments:
                    return f"{field} requires mode='adaptive' for action='context'"
    if tool == "local_ai_repo" and action in {"search", "code_index"}:
        bounds_error = pagination_bounds_error(
            arguments.get("limit", properties.get("limit", {}).get("default", 24)),
            arguments.get("offset", properties.get("offset", {}).get("default", 0)),
        )
        if bounds_error:
            return bounds_error
    for field in action_contract["required"]:
        if field not in arguments or (field in action_contract["non_empty"] and not arguments[field]):
            return f"{field} is required for action='{action}'"

    for field, value in arguments.items():
        non_finite_path = _non_finite_number_path(value, field)
        if non_finite_path is not None:
            return f"{non_finite_path} must be finite for action='{action}'"
        schema = properties.get(field) if isinstance(properties, dict) else None
        if not isinstance(schema, dict):
            continue
        expected = schema.get("type")
        if not _matches_json_type(value, expected):
            expected_types = expected if isinstance(expected, list) else [expected]
            expected_label = " or ".join(str(item) for item in expected_types)
            return f"{field} must be {expected_label} for action='{action}'"
        items_schema = schema.get("items")
        if isinstance(value, list) and isinstance(items_schema, dict):
            item_type = items_schema.get("type")
            if any(not _matches_json_type(item, item_type) for item in value):
                return f"{field} items must be {item_type} for action='{action}'"
        allowed_values = schema.get("enum")
        if allowed_values is not None and field != contract.get("selector_field"):
            if tool == "local_ai_status" and field == "action":
                allowed_values = list(dict.fromkeys((*operation_actions(tool, features), *allowed_values)))
            if not (tool == "local_ai_status" and field == "action" and value == "") and value not in allowed_values:
                values = ", ".join(str(item) for item in allowed_values)
                return f"{field} must be one of {values} for action='{action}'"
        if isinstance(value, str) and "minLength" in schema and len(value) < int(schema["minLength"]):
            return f"{field} must have at least {schema['minLength']} characters for action='{action}'"
        if isinstance(value, str) and "maxLength" in schema and len(value) > int(schema["maxLength"]):
            return f"{field} must have at most {schema['maxLength']} characters for action='{action}'"
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in schema and value < schema["minimum"]:
                return f"{field} must be >= {schema['minimum']} for action='{action}'"
            if "maximum" in schema and value > schema["maximum"]:
                return f"{field} must be <= {schema['maximum']} for action='{action}'"
        if isinstance(value, list):
            if "minItems" in schema and len(value) < int(schema["minItems"]):
                return f"{field} must have at least {schema['minItems']} items for action='{action}'"
            if "maxItems" in schema and len(value) > int(schema["maxItems"]):
                return f"{field} must have at most {schema['maxItems']} items for action='{action}'"
    if tool == "local_ai_repo" and "path_hints" in arguments:
        error = _validate_nested_schema(
            arguments["path_hints"], properties["path_hints"], "path_hints", action
        )
        if error:
            return error
    if tool == "local_ai_status":
        adoption_signal = arguments.get("adoption_signal", "")
        target_tool = arguments.get("target_tool", "")
        target_action = arguments.get("target_action", "")
        if adoption_signal == "bypassed":
            if not target_tool or not target_action:
                return "bypass report requires supported target_tool and safe target_action"
            if target_action not in operation_actions(target_tool):
                return f"target_action is not supported for target_tool='{target_tool}'"
        elif target_tool or target_action:
            return "target_tool requires adoption_signal='bypassed'"
    if tool == "local_ai_repo" and action == "verify_receipt":
        receipt = arguments.get("receipt")
        if not isinstance(receipt, dict):
            return "receipt must be an object for action='verify_receipt'"
        receipt_schema = contract.get("properties", {}).get("receipt", {})
        error = _validate_nested_schema(receipt, receipt_schema, "receipt", action)
        if error:
            return error
        for field in ("task_id", "criterion"):
            if not receipt[field].strip():
                return f"receipt.{field} is required for action='verify_receipt'"
        if receipt["passed"]:
            evidence_id = receipt.get("evidence_id")
            if not isinstance(evidence_id, str) or not evidence_id.strip():
                return "receipt.evidence_id is required for passed verification receipts"
    return None


for _tool_name, _tool in OPERATION_CONTRACTS.items():
    for _action_name, _action in _tool["actions"].items():
        _action["input_schema"] = operation_input_schema(_tool_name, _action_name)
        _action["output_schema"] = operation_output_schema(_tool_name, _action_name)
