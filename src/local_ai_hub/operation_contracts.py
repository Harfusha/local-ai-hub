"""Small, dependency-free contracts for public hub operations."""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

from .search_pagination import MAX_PAGE_SIZE, MAX_PAGE_WINDOW, pagination_bounds_error
from .automation import AUTOMATION_REQUEST_SCHEMA

REPO_PHASES = ("", "plan", "edit", "review", "test", "handoff")
MAX_REPO_PIPELINE_PARALLEL_STEPS = 4
MAX_EVENT_SEQUENCE = (1 << 63) - 1
_INCIDENT_RECORD_SCHEMA = {
    "type": "object",
    "properties": {
        "root_cause": {"type": "string", "maxLength": 4096},
        "verified_fix": {"type": "string", "maxLength": 4096},
        "message": {"type": "string", "maxLength": 4096},
        "operation_class": {"type": "string", "maxLength": 160},
        "exit_code": {"type": "integer", "minimum": -(1 << 31), "maximum": (1 << 32) - 1},
        "state_revision": {"type": "string", "maxLength": 256},
        "evidence_ids": {"type": "array", "maxItems": 64, "items": {"type": "string", "maxLength": 256}},
        "affected_paths": {"type": "array", "maxItems": 128, "items": {"type": "string", "maxLength": 4096}},
        "description": {"type": "string", "maxLength": 4096},
        "error_class": {"type": "string", "maxLength": 160},
        "category": {"type": "string", "maxLength": 160},
        "paths": {"type": "array", "maxItems": 128, "items": {"type": "string", "maxLength": 4096}},
        "reason": {"type": "string", "maxLength": 4096},
        "fix": {"type": "string", "maxLength": 4096},
    },
    "additionalProperties": False,
}
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


_STATUS_ACTIONS = ("brief",)
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
    "preprocess_unregister", "call_graph_diff",
    "semantic_diff", "cross_project_graph", "cross_project_symbols", "cross_project_impact",
    "patch", "call_graph", "revert", "diff", "find_files", "glob", "git_log", "file_info", "stat", "read_file", "source", "definition", "references", "find_references", "find_symbol",
)
_TASK_ACTIONS = (
    "delegate", "explore", "reason", "continue", "review", "second_opinion", "compress", "route", "batch",
    "benchmark", "hardware_benchmark", "evaluation_record", "evaluation_report", "submit", "status", "wait",
    "result", "cancel", "candidate_create", "candidate_promote", "speculative_draft", "vision", "transcribe", "browser",
    "eval_suite", "prompt_eval", "eval_drift", "complete_code", "scaffold", "automation",
)
_RAG_ACTIONS = ("index", "search", "list", "docset_index", "docset_search", "ingest_document", "ingest_diagram")
_COORD_BASE_ACTIONS = ("claim", "renew", "release", "leases")
_COORD_ACTIONS = (
    *_COORD_BASE_ACTIONS,
    "task_create", "task_get", "task_checkpoint", "task_rollback", "task_transition", "task_resume", "task_list", "task_budget_increase", "task_repair_session",
    "task_complete", "task_fail", "task_heartbeat", "ask", "answer", "memory_record", "memory_get", "memory_find",
    "memory_promote", "memory_delete", "context_compile",
    "verify_receipt", "verify_completion", "verify_export", "negative_knowledge_record", "negative_knowledge_find", "incident_decision",
    "blackboard_update", "blackboard_get", "blackboard_list", "blackboard_merge", "blackboard_delete",
    "swarm_dispatch", "swarm_step", "swarm_status", "swarm_list", "swarm_cancel", "worktree_lease",
    "worktree_release", "pubsub_publish", "pubsub_poll", "simulate_merge", "curate_dataset", "task_sync",
    "task_zombie_reap", "task_cleanup_worktree",
    "wait_for_event", "semaphore_acquire", "semaphore_release", "semaphore_status",
    "board_item_create", "board_item_update", "board_item_get", "board_item_delete", "board_item_list", "board_summary",
    "milestone_create", "milestone_status", "session_briefing",
    "task_claim", "record_native_receipt",
    "plan_init", "plan_list", "plan_get", "plan_create", "plan_update",
    "plan_task_edit", "plan_task_delete", "plan_validate", "plan_archive",
    "plan_board_view", "plan_adopt_legacy_board", "plan_bind_task", "plan_reconcile_steering",
)
_WORK_ACTIONS = ("submit", "status", "wait", "get", "cancel", "continue")
_ARTIFACT_ACTIONS = ("get", "slice", "list", "source")
_ADOPTION_TOOL_NAMES = (
    "local_ai_status", "local_ai_repo", "local_ai_task", "local_ai_rag",
    "local_ai_coord", "local_ai_artifact", "local_ai_work",
)

_RESPONSE_BUDGET_PROPERTIES = {
    "max_response_tokens": {"type": ["integer", "null"], "minimum": 128, "default": None},
    "response_profile": {
        "type": "string",
        "enum": ["minimal", "compact", "standard", "debug", "delta", "dense"],
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
    "preprocess_cancel", "preprocess_unregister", "patch", "revert",
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
    "call_graph_diff": ("agent_os",),
    "semantic_diff": ("agent_os",),
    "cross_project_graph": ("agent_os",),
    "cross_project_symbols": ("agent_os",),
    "cross_project_impact": ("agent_os",),
}
_ACTION_SCOPED_FIELDS = {
    "local_ai_status": {},
    "local_ai_task": {
        "automation": frozenset({"automation"}),
        "url": frozenset({"browser"}),
        "request_id": frozenset({"submit"}),
        "image_path": frozenset({"vision"}),
        "audio_path": frozenset({"transcribe"}),
        "file": frozenset({"transcribe"}),
        "problem": frozenset({"reason"}),
        "query": frozenset({"delegate", "explore", "reason"}),
        "question": frozenset({"second_opinion"}),
        "text": frozenset({"compress"}),
        "items": frozenset({"batch"}),
        "code": frozenset({"review", "code_review"}),
        "diff": frozenset({"review", "code_review"}),
        **{
            name: frozenset({"delegate", "explore", "reason", "review", "second_opinion", "compress"})
            for name in ("phase", "focus", "preload_profile", "repository_revision", "changed_paths")
        },
    },
    "local_ai_repo": {
        **{
            name: frozenset({"git_history_search", "git_log"})
            for name in ("max_commits", "author", "since", "until")
        },
        "pattern": frozenset({"find_files", "glob", "structural_search"}),
        "target": frozenset({"patch"}),
        "replacement": frozenset({"patch"}),
        "days": frozenset({"hotspots"}),
        **{
            name: frozenset({"context"})
            for name in (
                "include_diagnostics", "clone_id", "worktree_id", "branch",
                "repository_id", "session_id", "repository_revision",
            )
        },
        "steps": frozenset({"pipeline"}),
        "is_worktree": frozenset({"preprocess"}),
        "parent_root": frozenset({"preprocess"}),
        "path_hints": frozenset({"search", "context"}),
        "limit": frozenset({"search", "code_index", "callers", "callees", "implementations", "hotspots", "call_graph", "find_files", "glob", "git_log"}),
        "offset": frozenset({"search", "code_index", "callers", "callees", "implementations", "find_files", "glob"}),
        "directory_hints": frozenset({"context"}),
        "exclude_paths": frozenset({"context"}),
        "force_include_paths": frozenset({"context"}),
        "old_symbol": frozenset({"ast_refactor"}),
        "new_symbol": frozenset({"ast_refactor"}),
        "old_code": frozenset({"semantic_diff", "patch"}),
        "new_code": frozenset({"semantic_diff", "patch"}),
        "depth": frozenset({"call_graph"}),
        "rev1": frozenset({"git_diff", "diff"}),
        "rev2": frozenset({"git_diff", "diff"}),
        "base": frozenset({"git_diff", "diff", "context", "solve"}),
        "head": frozenset({"git_diff", "diff"}),
        "start_line": frozenset({"read_file", "source"}),
        "end_line": frozenset({"read_file", "source"}),
        "line_start": frozenset({"read_file", "source"}),
        "line_end": frozenset({"read_file", "source"}),
        "max_chars": frozenset({"read_file", "source"}),
        "language": frozenset({"circular_dependencies", "resolve_imports"}),
        "symbol": frozenset({"callers", "callees", "implementations", "declaration", "refactor_impact", "code_index"}),
        "file": frozenset({"source", "read_file", "file_info", "stat", "git_diff", "diff", "generate_tests", "generate_tests_for_diff", "mutation_test", "type_stubs"}),
        "changed_paths": frozenset({"generate_tests_for_diff", "context"}),
    },
    "local_ai_coord": {
        "sync_action": frozenset({"task_sync"}),
        "budget": frozenset({"task_budget_increase"}),
        "stream_id": frozenset({"task_sync"}),
        "events": frozenset({"task_sync"}),
        "limit": frozenset({"task_sync", "pubsub_poll", "negative_knowledge_find", "board_item_list", "plan_list"}),
        "after_seq": frozenset({"task_sync", "pubsub_poll"}),
        "receipt": frozenset({"verify_receipt"}),
        "since_hash": frozenset({"context_compile"}),
        "format": frozenset({"verify_export", "curate_dataset"}),
        "content": frozenset({"blackboard_update"}),
        "author": frozenset({"blackboard_update", "swarm_dispatch"}),
        "remote_sections": frozenset({"blackboard_merge"}),
        "expected_version": frozenset({"blackboard_update"}),
        "message": frozenset({"pubsub_publish", "task_fail"}),
        "publisher": frozenset({"pubsub_publish"}),
        "topic": frozenset({"pubsub_publish", "pubsub_poll", "wait_for_event"}),
        "after_ts": frozenset({"pubsub_poll"}),
        "goal": frozenset({"swarm_dispatch", "task_create", "task_update"}),
        "acceptance_criteria": frozenset({"task_create", "task_update", "plan_reconcile_steering"}),
        "criteria": frozenset({"task_create", "task_update"}),
        "kind": frozenset({"memory_record", "memory_find", "memory_get", "memory_list"}),
        "error": frozenset({"task_fail"}),
        "target_paths": frozenset({"swarm_dispatch"}),
        "test_command": frozenset({"swarm_dispatch"}),
        "swarm_id": frozenset({"swarm_step", "swarm_status", "swarm_cancel"}),
        "role": frozenset({"swarm_step"}),
        "swarm_action": frozenset({"swarm_step"}),
        "payload": frozenset({"swarm_step"}),
        "state": frozenset({"swarm_list", "task_list"}),
        "resource": frozenset({"semaphore_acquire", "semaphore_release", "semaphore_status"}),
        "notes": frozenset({"task_checkpoint", "task_update"}),
        "state_data": frozenset({"task_checkpoint", "task_update"}),
        "source_branch": frozenset({"simulate_merge"}),
        "target_branch": frozenset({"simulate_merge"}),
        "worktree_path": frozenset({"worktree_release"}),
        "delete_branch": frozenset({"worktree_release"}),
        "output_path": frozenset({"curate_dataset"}),
        "min_receipts": frozenset({"curate_dataset"}),
        "command_id": frozenset({"record_native_receipt"}),
        "changed_paths": frozenset({"context_compile", "task_checkpoint", "task_create", "task_update", "claim", "release"}),
        "path": frozenset({"claim", "release", "renew", "task_create", "task_checkpoint", "task_update"}),
        "file": frozenset({"claim", "release", "renew", "task_create", "task_checkpoint", "task_update"}),
        "next_action": frozenset({"task_checkpoint", "task_update"}),
        "blockers": frozenset({"task_checkpoint", "task_update"}),
        "evidence_ids": frozenset({"task_checkpoint", "task_update"}),
        "summary": frozenset({"task_complete", "task_fail", "record_native_receipt", "plan_reconcile_steering"}),
        "result": frozenset({"task_complete", "task_fail", "record_native_receipt"}),
        "timeout_seconds": frozenset({"wait_for_event", "semaphore_acquire"}),
        "id": frozenset({"task_get", "task_resume", "task_cleanup_worktree", "task_zombie_reap", "board_item_get", "board_item_delete", "board_item_update"}),
    },
}
OPERATION_CONTRACTS: dict[str, dict[str, Any]] = {
    "local_ai_status": _tool_contract(
        "local_ai_status", "status", "detail", _STATUS_ACTIONS, timeout="quick: 180 seconds by default; configured MCP timeout applies",
        projection="status", read_only=_STATUS_ACTIONS, selector_required=False,
        properties={
            "detail": {"type": "string", "default": "brief"},
            "extra_fields": {"type": "array", "items": {"type": "string"}},
        },
    ),
    "local_ai_repo": _tool_contract(
        "local_ai_repo", "repo", "action", _REPO_ACTIONS, timeout="action-specific: search max 120s, other quick 180s, context 600s, model 1800s, long 2400s",
        projection="repository result", action_requirements=_REPO_CONDITIONS,
        required={
            "revert": ("path",),
            "patch": ("path",),
            "call_graph": ("query",),
            "ast_outline": ("path",),
            "profile_digest": ("path",),
            "generate_types": ("path",),
            "declaration": ("query",),
            "ast_refactor": ("old_symbol", "new_symbol"),
            "context": ("query",),
            "solve": ("task",),
            "delegate": ("task",),
            "diagnose": ("query",),
            "resolve_imports": ("query",),
            "validate_patch": ("query",),
            "generate_mocks": ("query", "path"),
            "cross_project_impact": ("query",),
            "generate_dataset": ("query",),
            "explain_query": ("query",),
            "dependency_slice": ("query",),
            "structural_search": ("query",),
            # git_history_search allows query to be empty for full commit log
            "cross_repo_contract": ("path",),
            "route": ("path",),
            "refactor_impact": ("path",),
            "type_stubs": ("path",),
        },
        non_empty={
            "patch": ("path",),
            "call_graph": ("query",),
            "ast_outline": ("path",),
            "profile_digest": ("path",),
            "generate_types": ("path",),
            "declaration": ("query",),
            "ast_refactor": ("old_symbol", "new_symbol"),
            "synthesize_commit": ("task_id",),
            "context": ("query",),
            "solve": ("task",),
            "delegate": ("task",),
            "diagnose": ("query",),
            "resolve_imports": ("query",),
            "validate_patch": ("query",),
            "generate_mocks": ("query", "path"),
            "cross_project_impact": ("query",),
            "generate_dataset": ("query",),
            "explain_query": ("query",),
            "dependency_slice": ("query",),
            "structural_search": ("query",),
            "git_history_search": ("query",),
            "cross_repo_contract": ("path",),
            "route": ("path",),
            "refactor_impact": ("path",),
            "type_stubs": ("path",),
        },
        allowed={
            "git_history_search": (
                "root", "query", "max_commits", "author", "since", "until", "path",
            ),
            "hotspots": ("root", "days", "limit"),
            "ast_outline": ("root", "path"),
            "affected_tests": ("root", "path"),
            "code_invariants": ("root", "path"),
            "profile_digest": ("root", "path", "max_tokens"),
            "schema_inspect": ("root", "path"),
            "generate_types": ("root", "path"),
            "complexity": ("root", "path", "max_tokens", "include_tests"),
            "declaration": ("root", "query", "path"),
            "patch": ("root", "path", "old_code", "new_code", "target", "replacement"),
            "call_graph": ("root", "query", "path", "limit", "depth"),
            "ast_refactor": ("root", "path", "old_symbol", "new_symbol", "staged"),
            "context": ("root", "query", "workspace", "mode", "max_tokens", "token_budget", "task_id", "session_id", "phase", "focus", "preload_profile", "repository_revision", "changed_paths", "base", "staged", "guarded", "since_hash", "approval", "override_reason", "clone_id", "worktree_id", "branch", "repository_id", "include_diagnostics", "path_hints", "directory_hints", "exclude_paths", "force_include_paths"),
            "solve": ("root", "task", "workspace", "mode", "max_tokens", "base", "staged"),
            "delegate": ("root", "task", "workspace", "profile", "max_tokens"),
            "investigate": ("root", "query", "path", "include_code"),
            "secret_scan": ("root", "path", "staged"),
            "diagnose": ("root", "query"),
            "search": ("root", "query", "path", "include_code", "path_hints", "limit", "offset"),
            "code_index": ("root", "query", "limit", "offset", "include_code"),
            "semantic": ("root", "query", "path", "relation"),
            "intelligence": ("root", "query", "path", "relation"),
            "deterministic": ("root", "query"),
            "route": ("root", "query", "path"),
            "refactor_impact": ("root", "query", "path"),
            "resolve_imports": ("root", "query", "language", "extra_fields"),
            "generate_tests": ("root", "query", "path"),
            "validate_patch": ("root", "query"),
            "generate_mocks": ("root", "query", "path"),
            "synthesize_commit": ("root", "query", "task_id"),
            "cross_project_symbols": ("root", "query"),
            "cross_project_impact": ("root", "query"),
            "generate_dataset": ("root", "query", "max_tokens", "relation"),
            "explain_query": ("root", "query", "path"),
            "api_spec": ("root", "query"),
            "dependency_slice": ("root", "query", "path", "max_tokens"),
            "structural_search": ("root", "query", "path", "max_tokens", "pattern"),
            "migration_drift": ("root", "path"),
            "package_audit": ("root", "path"),
            "git_diff": ("root", "path", "staged", "max_tokens", "rev1", "rev2", "base", "head"),
            "file_info": ("root", "path"),
            "stat": ("root", "path"),
            "read_file": ("root", "path", "line_start", "line_end", "start_line", "end_line", "max_chars"),
            "source": ("root", "path", "line_start", "line_end", "start_line", "end_line", "max_chars"),
            "diff": ("root", "path", "staged", "max_tokens", "rev1", "rev2", "base", "head"),
            "git_status": ("root", "path"),
            "revert": ("root", "path"),
            "find_files": ("root", "query", "pattern", "limit", "offset"),
            "glob": ("root", "query", "pattern", "limit", "offset"),
            "git_log": ("root", "query", "max_commits", "author", "since", "until", "path", "limit"),
            "mutation_test": ("root", "path", "diff"),
            "type_stubs": ("root", "path"),
            "split_changes": ("root", "path"),
            "generate_tests_for_diff": ("root", "diff", "path", "changed_paths"),
            "cross_repo_contract": ("root", "path"),
            "circular_dependencies": ("root", "language"),
            "skeletonize": ("root", "query", "path"),
        },
        action_effects={name: "repository_state" for name in _REPO_MUTATIONS},
        read_only=tuple(name for name in _REPO_ACTIONS if name not in _REPO_MUTATIONS),
        properties={
            "action": {"type": "string"},
            "id": {"type": "string", "default": ""},
            "goal": {"type": "string", "default": ""},
            "prompt": {"type": "string", "default": ""},
            "workspace": {"type": "string", "default": ""},
            "root": {"type": "string", "default": "."},
            "query": {"type": "string", "default": ""},
            "max_commits": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50},
            "author": {"type": "string", "maxLength": 256, "default": "", "pattern": r"^[^\x00-\x1F\x7F]*$"},
            "since": {
                "type": "string", "maxLength": 64, "default": "",
                "pattern": r"^(?:\d{4}-\d{2}-\d{2}|\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2}))?$",
            },
            "until": {
                "type": "string", "maxLength": 64, "default": "",
                "pattern": r"^(?:\d{4}-\d{2}-\d{2}|\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2}))?$",
            },
            "old_symbol": {"type": "string", "maxLength": 512},
            "new_symbol": {"type": "string", "maxLength": 512},
            "base": {"type": "string", "default": "HEAD", "maxLength": 512},
            "head": {"type": "string", "default": "", "maxLength": 512},
            "start_line": {"type": "integer", "minimum": 1, "default": 1},
            "end_line": {"type": "integer", "minimum": 0, "default": 0},
            "line_start": {"type": "integer", "minimum": 1, "default": 1},
            "line_end": {"type": "integer", "minimum": 0, "default": 0},
            "max_chars": {"type": "integer", "minimum": 1, "maximum": 50000, "default": 4000},
            "old_code": {"type": ["string", "null"], "default": None, "maxLength": 1_048_576},
            "new_code": {"type": ["string", "null"], "default": None, "maxLength": 1_048_576},
            "rev1": {"type": ["string", "null"], "default": None, "maxLength": 512},
            "rev2": {"type": ["string", "null"], "default": None, "maxLength": 512},
            "path": {"type": "string", "maxLength": 4096, "default": ""},
            "file": {"type": "string", "maxLength": 4096, "default": ""},
            "task": {"type": "string", "default": ""},
            "task_id": {"type": "string", "default": ""},
            "include_code": {"type": "boolean", "default": False},
            "limit": {"type": "integer", "minimum": 1, "maximum": MAX_PAGE_SIZE, "default": 24},
            "days": {"type": "integer", "minimum": 1, "maximum": 3650, "default": 30},
            "depth": {"type": "integer", "minimum": 1, "maximum": 5, "default": 1},
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
            "since_hash": {"type": "string", "default": ""},
            "approval": {"type": ["boolean", "string"], "default": ""},
            "override_reason": {"type": "string", "default": ""},
            "staged": {"type": "boolean", "default": False},
            "mode": {"type": "string", "default": "adaptive"},
            "language": {"type": "string", "default": "auto"},
            "relation": {"type": "string", "default": ""},
            "profile": {"type": "string", "default": ""},
            "max_tokens": {"type": "integer", "default": 0},
            "token_budget": {"type": "integer", "default": 0},
            "diff": {"type": "string", "default": ""},
            "name": {"type": "string", "default": ""},
            "text": {"type": "string", "default": ""},
            "evidence": {"type": "array", "items": {"type": "object"}},
            "session_id": {"type": "string", "default": ""},
            "clone_id": {"type": "string", "default": ""},
            "worktree_id": {"type": "string", "default": ""},
            "branch": {"type": "string", "default": ""},
            "repository_id": {"type": "string", "default": ""},
            "repository_revision": {"type": "string", "default": ""},
            "pattern": {"type": "string", "default": "*"},
            "target": {"type": "string", "default": ""},
            "replacement": {"type": "string", "default": ""},
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
        required={
            "submit": ("task",),
            "automation": ("root", "task_id", "automation"),
            "candidate_create": ("candidate_data",),
            "candidate_promote": ("candidate", "approver"),
        },
        non_empty={
            "submit": ("task",),
            "automation": ("root", "task_id"),
            "candidate_promote": ("candidate", "approver"),
        },
        action_effects={
            "submit": "durable_job", "cancel": "durable_job", "candidate_create": "candidate_store",
            "candidate_promote": "candidate_store", "evaluation_record": "evaluation_store",
            "browser": "browser_capture",
            "automation": "browser_desktop_mutation",
        },
        allowed={
            "submit": (
                "job_action", "task", "context", "candidate", "complexity", "max_tokens",
                "tasks", "profile", "root", "workspace", "timeout_seconds", "request_id",
            ),
            "automation": ("root", "task_id", "automation"),
            "candidate_create": ("candidate_data",),
            "candidate_promote": ("candidate", "approver"),
            "hardware_benchmark": ("model", "prompt", "max_tokens"),
            "speculative_draft": ("task", "candidate", "context", "root"),
            "vision": (
                "prompt", "candidate", "model", "image_artifact_id", "screenshot_artifact_id",
                "baseline_screenshot_artifact_id", "bundle_artifact_id", "dom_artifact_id",
                "accessibility_artifact_id", "computed_styles_artifact_id", "runtime_artifact_id",
                "network_artifact_id", "source", "cloud_fallback", "root", "dom", "accessibility",
                "computed_styles", "runtime", "viewport", "page", "bundle", "html",
                "accessibility_snapshot", "computed_style_data", "runtime_context", "json_schema",
            ),
            "eval_drift": ("task",),
            "complete_code": ("prompt", "candidate", "max_tokens"),
            "scaffold": ("prompt", "context", "language", "max_tokens", "model"),
            "transcribe": ("candidate", "model", "language"),
            "eval_suite": ("task", "model", "cases"),
            "prompt_eval": ("prompt", "candidate_data"),
        },
        properties={
            "automation": AUTOMATION_REQUEST_SCHEMA,
            "action": {"type": "string"},
            "url": {"type": "string", "maxLength": 4096, "description": "Loopback HTTP(S) URL for bounded DOM and screenshot capture in the shared daemon."},
            "delivery": {"type": "string", "enum": ["sync", "async", "auto"], "default": "sync"},
            "phase": {"type": "string", "default": ""},
            "focus": {"type": "array", "items": {"type": "string"}},
            "preload_profile": {"type": "string", "default": ""},
            "repository_revision": {"type": "string", "default": ""},
            "changed_paths": {"type": "array", "items": {"type": "string"}},
            **{name: {"type": "string", "default": ""} for name in (
                "task", "context", "root", "profile", "conversation_id", "prompt", "model", "candidate", "code", "diff", "problem", "query", "question", "text",
                "image_artifact_id", "screenshot_artifact_id", "baseline_screenshot_artifact_id", "bundle_artifact_id", "dom_artifact_id",
                "accessibility_artifact_id", "computed_styles_artifact_id", "runtime_artifact_id",
                "network_artifact_id", "source", "job_id", "evaluation_task_id", "evaluation_cohort",
                "workspace", "approver", "task_id", "language", "request_id",
            )},
            "complexity": {"type": "string", "default": "auto"},
            "job_action": {
                "type": "string", "default": "reason",
                "description": "Operation to run for action=submit; submit itself is asynchronous.",
            },
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
            "items": {"type": "array", "items": {"type": "object"}},
            "cases": {"type": "array", "items": {"type": "object"}},
            "format": {"type": ["string", "object"]},
            "extra_fields": {"type": "array", "items": {"type": "string"}},
        },
    ),
    "local_ai_rag": _tool_contract(
        "local_ai_rag", "rag", "action", _RAG_ACTIONS, timeout="action-specific MCP timeout; HubClient cap applies",
        projection="retrieval result", read_only=("search", "list", "docset_search", "query"),
        action_effects={
            "index": "index_store", "docset_index": "index_store", "ingest_document": "index_store",
            "ingest_diagram": "index_store",
        },
        properties={
            "action": {"type": "string"},
            "query": {"type": "string", "default": ""},
            "root": {"type": "string", "description": "Explicit absolute authorized repository root required for index, search, docset_index, ingest_document and ingest_diagram; never inferred from adapter cwd."},
            "top_k": {"type": "integer", "default": 6},
            "limit": {"type": "integer", "default": 6},
            "task": {"type": "string", "default": ""},
            "workspace": {"type": "string", "default": ""},
            "content": {"type": "string", "default": ""},
            "title": {"type": "string", "default": ""},
            "metadata": {"type": "object"},
            "image_path": {"type": "string", "default": ""},
            "caption": {"type": "string", "default": ""},
            "path": {"type": "string", "default": ""},
            "file": {"type": "string", "default": ""},
            "extra_fields": {"type": "array", "items": {"type": "string"}},
        },
    ),
    "local_ai_coord": _tool_contract(
        "local_ai_coord", "coord", "action", _COORD_ACTIONS, timeout="action-specific coordination budget; HubClient cap applies",
        projection="coordination result", default_effect="coordination_state", read_only=(
            "leases", "task_get", "task_list", "memory_get", "memory_find",
            "blackboard_get", "blackboard_list", "swarm_status", "swarm_list", "pubsub_poll", "verify_export",
            "wait_for_event", "semaphore_status", "board_item_get", "board_item_list", "board_summary", "milestone_status", "session_briefing",
            "plan_list", "plan_get", "plan_validate", "plan_board_view",
        ),
        action_requirements={name: ("agent_os",) for name in _COORD_ACTIONS[len(_COORD_BASE_ACTIONS):]},
        allowed={
            "ask": ("root", "session_id", "question_id", "question", "task_id"),
            "task_budget_increase": ("root", "task_id", "reason", "budget"),
            "answer": ("root", "question_id", "answer", "task_id"),
            "task_cleanup_worktree": ("root", "task_id"),
            "task_zombie_reap": ("root", "task_id"),
            "context_compile": (
                "root", "task_id", "since_hash", "max_tokens", "paths", "include_diagnostics",
                "clone_id", "worktree_id", "branch", "repository_id", "session_id",
                "repository_revision", "phase", "focus", "preload_profile",
            ),
            "verify_receipt": ("root", "receipt"),
            "verify_completion": ("root", "task_id", "repository_revision"),
            "verify_export": ("root", "task_id", "format"),
            "swarm_dispatch": ("root", "goal", "target_paths", "test_command", "author"),
            "swarm_step": ("root", "swarm_id", "role", "swarm_action", "payload"),
            "swarm_status": ("root", "swarm_id"),
            "swarm_list": ("root", "state"),
            "swarm_cancel": ("root", "swarm_id", "reason"),
            "worktree_lease": ("root", "branch"),
            "worktree_release": ("root", "worktree_path", "worktree_id", "delete_branch", "branch"),
            "simulate_merge": ("root", "source_branch", "target_branch"),
            "curate_dataset": ("root", "output_path", "min_receipts", "format"),
            "negative_knowledge_record": ("root", "record"),
            "negative_knowledge_find": ("root", "query", "limit"),
            "incident_decision": ("root", "fingerprint", "state_revision"),
            "task_sync": ("root", "sync_action", "stream_id", "after_seq", "limit", "events"),
            "blackboard_update": ("root", "task_id", "board_id", "section", "content", "author", "expected_version"),
            "blackboard_get": ("root", "task_id", "board_id", "section"),
            "blackboard_list": ("root", "task_id"),
            "blackboard_merge": ("root", "task_id", "board_id", "remote_sections"),
            "blackboard_delete": ("root", "task_id", "board_id", "section"),
            "pubsub_publish": ("root", "topic", "message", "publisher"),
            "pubsub_poll": ("root", "topic", "after_seq", "limit", "after_ts"),
            "wait_for_event": ("root", "topic", "timeout", "filter", "filter_payload"),
            "semaphore_acquire": ("root", "name", "capacity", "timeout", "ttl_seconds", "purpose", "owner"),
            "semaphore_release": ("root", "name", "lease_id", "owner"),
            "semaphore_status": ("root", "name"),
            "board_item_create": ("root", "title", "status", "priority", "labels", "assignee", "milestone", "linked_task_id", "details", "name", "description", "task_id"),
            "board_item_update": ("root", "item_id", "title", "status", "priority", "labels", "assignee", "milestone", "linked_task_id", "details", "name", "description", "id", "task_id"),
            "board_item_get": ("root", "item_id"),
            "board_item_delete": ("root", "item_id"),
            "board_item_list": ("root", "status", "priority", "milestone", "assignee", "limit"),
            "board_summary": ("root",),
            "milestone_create": ("root", "name", "target_date", "description"),
            "milestone_status": ("root", "name"),
            "session_briefing": ("root", "session_id", "include"),
            "task_claim": ("root", "task_id", "owner"),
            "task_create": ("root", "task_id", "goal", "task", "paths", "contract", "scope", "acceptance_criteria", "criteria", "title", "description", "path", "file"),
            "task_update": ("root", "task_id", "checkpoint", "contract", "goal", "acceptance_criteria", "criteria"),
            "memory_list": ("root", "scope", "query", "limit", "kind"),
            "memory_find": ("root", "scope", "query", "limit", "kind", "key", "status"),
            "memory_record": ("root", "scope", "key", "value", "kind", "status", "confidence", "ttl_seconds", "name", "content"),
            "task_fail": ("root", "task_id", "reason", "error", "message"),
            "task_list": ("root", "query", "status", "owner", "limit", "offset", "include_stale"),
            "record_native_receipt": ("root", "task_id", "criterion", "command_id"),
            "plan_init": ("root",),
            "plan_list": ("root", "query", "lifecycle", "limit"),
            "plan_get": ("root", "plan_id"),
            "plan_create": ("root", "plan_id", "title", "description", "lifecycle", "default_target_ref", "spec_refs", "tasks", "accountable_role", "owner", "idempotency_key"),
            "plan_update": ("root", "plan_id", "expected_revision", "title", "description", "lifecycle", "default_target_ref", "spec_refs", "accountable_role", "owner", "idempotency_key"),
            "plan_task_edit": ("root", "plan_id", "expected_revision", "task_id", "task_data", "idempotency_key", "owner"),
            "plan_task_delete": ("root", "plan_id", "expected_revision", "task_id", "idempotency_key", "owner"),
            "plan_validate": ("root", "plan_id"),
            "plan_archive": ("root", "plan_id", "expected_revision", "idempotency_key", "owner"),
            "plan_board_view": ("root", "plan_id", "query", "worktree_id"),
            "plan_adopt_legacy_board": ("root", "plan_id", "title", "owner", "idempotency_key"),
            "plan_bind_task": ("root", "task_id", "plan_id", "plan_task_id", "expected_revision", "session_id"),
            "plan_reconcile_steering": ("root", "task_id", "steering_id", "spec_rel_path", "spec_content", "acceptance_criteria", "expected_revision", "expected_spec_revision", "summary"),
        },
        required={
            "ask": ("root", "session_id"),
            "curate_dataset": ("root",),
            "task_budget_increase": ("root", "task_id", "reason", "budget"),
            "answer": ("root", "question_id", "answer"),
            "task_cleanup_worktree": ("task_id",),
            "task_zombie_reap": ("task_id",),
            "context_compile": ("task_id",),
            "verify_receipt": ("receipt",),
            "verify_completion": ("task_id",),
            "verify_export": ("task_id",),
            "blackboard_update": ("content",),
            "blackboard_merge": ("remote_sections",),
            "pubsub_publish": ("message",),
            "swarm_dispatch": ("goal",),
            "swarm_step": ("swarm_id",),
            "swarm_status": ("swarm_id",),
            "swarm_cancel": ("swarm_id",),
            "simulate_merge": ("source_branch",),
            "negative_knowledge_record": ("root", "record"),
            "negative_knowledge_find": ("root", "query"),
            "incident_decision": ("root", "fingerprint"),
            "wait_for_event": ("topic",),
            "semaphore_acquire": ("name",),
            "semaphore_release": ("name", "lease_id"),
            "board_item_create": ("title",),
            "board_item_update": ("item_id",),
            "board_item_get": ("item_id",),
            "board_item_delete": ("item_id",),
            "milestone_create": ("name",),
            "milestone_status": ("name",),
            "task_claim": ("task_id",),
            "record_native_receipt": ("task_id", "criterion", "command_id"),
        },
        non_empty={
            "ask": ("root", "session_id"),
            "curate_dataset": ("root",),
            "task_budget_increase": ("root", "task_id", "reason"),
            "answer": ("root", "question_id", "answer"),
            "task_cleanup_worktree": ("task_id",),
            "task_zombie_reap": ("task_id",),
            "context_compile": ("task_id",),
            "verify_completion": ("task_id",),
            "verify_export": ("task_id",),
            "swarm_dispatch": ("goal",),
            "swarm_step": ("swarm_id",),
            "swarm_status": ("swarm_id",),
            "swarm_cancel": ("swarm_id",),
            "simulate_merge": ("source_branch",),
            "negative_knowledge_record": ("root",),
            "negative_knowledge_find": ("root", "query"),
            "incident_decision": ("root", "fingerprint"),
            "wait_for_event": ("topic",),
            "semaphore_acquire": ("name",),
            "semaphore_release": ("name", "lease_id"),
            "board_item_create": ("title",),
            "board_item_update": ("item_id",),
            "board_item_get": ("item_id",),
            "board_item_delete": ("item_id",),
            "milestone_create": ("name",),
            "milestone_status": ("name",),
            "task_claim": ("task_id",),
            "record_native_receipt": ("task_id", "criterion", "command_id"),
            "plan_init": ("root",),
            "plan_list": ("root",),
            "plan_get": ("root", "plan_id"),
            "plan_create": ("root", "plan_id", "title"),
            "plan_update": ("root", "plan_id", "expected_revision"),
            "plan_task_edit": ("root", "plan_id", "task_id", "task_data", "expected_revision"),
            "plan_task_delete": ("root", "plan_id", "task_id", "expected_revision"),
            "plan_validate": ("root", "plan_id"),
            "plan_archive": ("root", "plan_id", "expected_revision"),
            "plan_board_view": ("root",),
            "plan_adopt_legacy_board": ("root", "plan_id"),
            "plan_bind_task": ("root", "task_id", "plan_id", "plan_task_id"),
            "plan_reconcile_steering": ("root", "task_id", "steering_id", "spec_rel_path", "spec_content", "acceptance_criteria", "expected_revision", "expected_spec_revision"),
        },
        action_effects={name: "coordination_state" for name in _COORD_ACTIONS if name not in {
            "leases", "task_get", "task_list", "memory_get", "memory_find",
            "blackboard_get", "blackboard_list", "swarm_status", "swarm_list", "pubsub_poll", "verify_export",
            "wait_for_event", "semaphore_status", "board_item_get", "board_item_list", "board_summary", "milestone_status", "session_briefing",
            "plan_list", "plan_get", "plan_validate", "plan_board_view",
        }},
        properties={
            "action": {"type": "string"},
            "root": {"type": "string", "default": "."},
            "paths": {"type": "array", "items": {"type": "string"}},
            "path": {"type": "string", "default": ""},
            "file": {"type": "string", "default": ""},
            "next_action": {"type": "string", "default": ""},
            "blockers": {"type": "array", "items": {"type": "string"}},
            "evidence_ids": {"type": "array", "items": {"type": "string"}},
            "summary": {"type": "string", "default": ""},
            "result": {"type": "string", "default": ""},
            "timeout_seconds": {"type": "number", "minimum": 0.0, "default": 0.0},
            "id": {"type": "string", "default": ""},
            **{name: {"type": "string", "default": ""} for name in (
                "lease_id", "task_id", "key", "value", "query", "command", "command_id", "task", "status", "reason",
                "record_id", "target_scope", "approver", "criterion", "board_id", "section", "scope",
                "scope_id", "clone_id", "worktree_id", "branch", "repository_id", "session_id",
                "repository_revision", "phase", "preload_profile", "since_hash",
                "question_id", "question", "answer", "state_revision",
                "name", "item_id", "title", "priority", "assignee", "milestone", "linked_task_id",
                "target_date", "description", "purpose", "owner", "resource", "notes",
                "plan_id", "idempotency_key", "plan_task_id", "steering_id", "spec_rel_path", "spec_content", "expected_spec_revision", "accountable_role",
            )},
            "expected_revision": {"type": "string", "minLength": 1},
            "lifecycle": {"type": "string", "enum": ["draft", "active", "paused", "completed", "cancelled", "archived"]},
            "default_target_ref": {"type": ["string", "null"]},
            "spec_refs": {"type": "array", "items": {"type": "object"}},
            "task_data": {"type": "object"},
            "tasks": {"type": ["object", "null"]},
            "confidence": {"type": ["number", "null"], "minimum": 0, "maximum": 1, "default": None},
            "output_summary": {"type": "string", "default": ""},
            "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
            "criteria": {"type": "array", "items": {"type": "string"}},
            "error": {"type": "string", "default": ""},
            "kind": {"type": "string", "default": ""},
            "allow_adopt": {"type": "boolean", "default": False},
            "passed": {"type": "boolean", "default": True},
            "format": {"type": ["string", "null"], "default": None},
            "state_data": {"type": ["object", "null"]},
            "budget": {"type": "object", "additionalProperties": False, "minProperties": 1,
                       "properties": {"max_tokens": {"type": "integer", "minimum": 0},
                                      "max_compute_seconds": {"type": "number", "minimum": 0},
                                      "max_external_calls": {"type": "integer", "minimum": 0}}},
            "goal": {"type": "string", "default": ""},
            "target_paths": {"type": ["array", "null"], "items": {"type": "string"}},
            "test_command": {"type": "string", "default": ""},
            "author": {"type": "string", "default": "agent"},
            "swarm_id": {"type": "string", "default": ""},
            "role": {"type": "string", "default": "Coder"},
            "swarm_action": {"type": "string", "default": "submit_patch"},
            "payload": {"type": ["object", "null"]},
            "state": {"type": "string", "default": ""},
            "source_branch": {"type": "string", "default": ""},
            "target_branch": {"type": "string", "default": "HEAD"},
            "worktree_path": {"type": "string", "default": ""},
            "delete_branch": {"type": "boolean", "default": True},
            "output_path": {"type": "string", "default": "training_dataset.jsonl"},
            "min_receipts": {"type": "integer", "default": 1},
            "session_id": {"type": "string", "default": "", "maxLength": 256},
            "question_id": {"type": "string", "default": "", "maxLength": 80},
            "question": {"type": "string", "default": "", "maxLength": 16_384},
            "answer": {"type": "string", "default": "", "maxLength": 16_384},
            "content": {},
            "remote_sections": {"type": "object"},
            "expected_version": {"type": "integer", "minimum": 0},
            "message": {},
            "publisher": {"type": "string", "default": "agent"},
            "topic": {"type": "string", "default": "default"},
            "after_ts": {"type": "number", "minimum": 0, "maximum": 1_000_000_000_000},
            "ttl_seconds": {"type": ["integer", "number"], "description": "Optional explicit lifetime; omitted values preserve the selected action's default."},
            "max_tokens": {"type": "integer", "default": 0},
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
                    "if": {"properties": {"passed": {"enum": [True]}}, "required": ["passed"]},
                    "then": {"required": ["evidence_id"], "properties": {"evidence_id": {"minLength": 1}}},
                }],
            },
            "sync_action": {"type": "string", "enum": ["export", "import"], "default": "export"},
            "stream_id": {"type": "string", "default": ""},
            "events": {"type": "array", "items": {"type": "object"}},
            "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 1000},
            "contract": {"type": "object"},
            "checkpoint": {
                "type": "object",
                "description": "TaskCheckpoint. When server memory items or warnings exist, every checkpoint must include state_data.memory_audit; completion checks the same audit.",
                "properties": {"state_data": {
                    "type": "object",
                    "properties": {"memory_audit": {
                        "type": "object",
                        "description": "Cite only supplied memory IDs actually used; otherwise provide a nonempty not_used_reason. Used volatile IDs require a current-source check.",
                        "properties": {
                            "used_ids": {"type": "array", "items": {"type": "string"}},
                            "not_used_reason": {"type": "string"},
                            "source_checks": {
                                "type": "object",
                                "additionalProperties": {"type": "object", "properties": {
                                    "source": {"type": "string"},
                                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                                }},
                            },
                        },
                    }},
                }},
            },
            "record": {"type": "object"},
            "fingerprint": {
                "type": "object",
                "properties": {
                    "error_class": {"type": "string", "minLength": 1, "maxLength": 160},
                    "operation_class": {"type": "string", "minLength": 1, "maxLength": 160},
                    "signature_hash": {"type": "string", "minLength": 1, "maxLength": 128},
                },
                "required": ["error_class", "operation_class", "signature_hash"],
                "additionalProperties": False,
            },
            "tool_outcome": {"type": "object"},
            "focus": {"type": "array", "items": {"type": "string"}},
            "include_diagnostics": {"type": "boolean", "default": False},
            "base": {"type": "string", "default": "HEAD"},
            "after_seq": {"type": "integer", "minimum": 0, "maximum": MAX_EVENT_SEQUENCE, "default": 0},
            "include_stale": {"type": "boolean", "default": False},
            "capacity": {"type": "integer", "minimum": 1, "default": 1},
            "timeout": {"type": "number", "minimum": 0, "default": 0},
            "labels": {"type": "array", "items": {"type": "string"}},
            "details": {"type": "object"},
            "filter": {"type": "object"},
            "filter_payload": {"type": "object"},
            "include": {"type": "array", "items": {"type": "string"}},
            "extra_fields": {"type": "array", "items": {"type": "string"}},
        },
    ),
    "local_ai_artifact": {
        **_tool_contract(
            "local_ai_artifact", "artifacts", "action", _ARTIFACT_ACTIONS,
            timeout="HubClient.post default 360 seconds; capped by configured max_request_timeout_seconds",
            projection="artifact", read_only=_ARTIFACT_ACTIONS,
            required={"get": ("artifact_id",), "slice": ("artifact_id",), "source": ("path",)},
            non_empty={"get": ("artifact_id",), "slice": ("artifact_id",), "source": ("path",)},
            allowed={
                "get": ("artifact_id", "offset", "max_chars", "section", "binary", "slices", "root", "workspace"),
                "slice": ("artifact_id", "offset", "max_chars", "section", "binary", "slices", "root", "workspace"),
                "list": (),
                "source": ("path", "file", "line_start", "line_end", "start_line", "end_line", "max_chars", "slices", "root", "workspace"),
            },
            selector_required=False,
            properties={
                "action": {"type": "string", "default": "get"},
                "artifact_id": {"type": "string", "default": ""},
                "file": {"type": "string", "maxLength": 32768, "default": ""},
                "root": {"type": "string", "default": "."},
                "workspace": {"type": "string", "default": ""},
                "path": {"type": "string", "maxLength": 32768, "default": ""},
                "line_start": {"type": "integer", "minimum": 1, "maximum": 2147483647, "default": 1},
                "line_end": {"type": "integer", "minimum": 0, "maximum": 2147483647, "default": 0},
                "start_line": {"type": "integer", "minimum": 1, "maximum": 2147483647, "default": 1},
                "end_line": {"type": "integer", "minimum": 0, "maximum": 2147483647, "default": 0},
                "section": {"type": "string", "maxLength": 512, "default": ""},
                "offset": {"type": "integer", "minimum": 0, "default": 0},
                "max_chars": {"type": "integer", "minimum": 1, "maximum": 50000, "default": 4000},
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
            "task_id": {"type": "string", "default": ""},
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
        "local_ai_status": {"detail": "brief"},
        "local_ai_repo": {"action": "context", "root": "ABS_ROOT", "query": "Bounded repository question", "mode": "adaptive"},
        "local_ai_task": {"action": "delegate", "task": "Summarize supplied evidence", "context": "EVIDENCE"},
        "local_ai_rag": {"action": "search", "root": "ABS_ROOT", "query": "Meaning to retrieve"},
        "local_ai_coord": {"action": "memory_find", "root": "ABS_ROOT", "query": "Known finding"},
        "local_ai_artifact": {"action": "slice", "artifact_id": "ARTIFACT_ID", "offset": 0, "max_chars": 1000},
        "local_ai_work": {"action": "status", "work_id": "WORK_ID"},
    }
    tips = {
        "local_ai_status": "One bounded readiness check before local-model work.",
        "local_ai_repo": "Context first; reuse evidence; fetch exact slices only when needed.",
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
            "required": ([selector] if contract["selector_required"] else []) + list(dict.fromkeys(
                (*action_contract["required"], *action_contract["non_empty"])
            )),
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
    if tool == "local_ai_status":
        return _STATUS_ACTIONS
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
    # Publish effective required fields, including non-empty requirements used
    # by the generated action schema, while retaining the registry's tuples.
    result = deepcopy(raw)
    for action_metadata in result["actions"].values():
        action_metadata["required"] = tuple(dict.fromkeys((
            *action_metadata.get("required", ()),
            *action_metadata.get("non_empty", ()),
        )))
    return result


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
    if tool == "local_ai_coord" and action == "context_compile":
        schema["properties"]["max_tokens"] = {
            "type": "integer", "minimum": 0, "maximum": 100000, "default": 4000,
        }
    action_contract = contract["actions"][action]
    required = [
        selector,
        *action_contract.get("required", ()),
        *action_contract.get("non_empty", ()),
    ]
    schema["required"] = list(dict.fromkeys(required))
    return schema


def operation_action_guide(tool: str, action: str, features: Any = None) -> dict[str, Any]:
    """Return one exact action's fields; examples are data and execute nothing."""
    contract = operation_contract(tool)
    if contract is None or not isinstance(action, str) or action not in operation_actions(tool, features):
        return contract_error("unsupported or disabled guide tool/action")
    raw = operation_input_schema(tool, action)
    # Global union conditions are redundant once the selector is fixed.
    schema = {key: deepcopy(raw[key]) for key in ("type", "properties", "required") if key in raw}
    schema["additionalProperties"] = False

    def example_value(spec: dict[str, Any]) -> Any:
        if spec.get("enum"):
            return next((item for item in spec["enum"] if item != ""), spec["enum"][0])
        kind = spec.get("type")
        kind = kind[0] if isinstance(kind, list) else kind
        if kind == "object":
            return {name: example_value(spec.get("properties", {}).get(name, {})) for name in spec.get("required", [])}
        if kind == "array":
            return [example_value(spec.get("items", {})) for _ in range(spec.get("minItems", 0))]
        if kind == "boolean":
            return False
        if kind in {"integer", "number"}:
            return spec.get("minimum", 0)
        return "example"

    example = {name: example_value(schema["properties"][name]) for name in schema.get("required", [])}
    example[contract["selector_field"]] = action
    for name in ("root", "cwd"):
        if name in schema["properties"]:
            example[name] = "/absolute/project"
    return {"success": True, "tool": tool, "action": action, "input_schema": schema,
            "example": example, "examples_execute": False,
            "validation_note": "Server validation also enforces ownership, feature gates and cross-field constraints."}


def operation_argument_hint(tool: str, action: str) -> dict[str, Any]:
    contract = operation_contract(tool)
    if contract is None or not isinstance(action, str) or action not in contract["actions"]:
        return {}
    schema = operation_input_schema(tool, action)
    return {"allowed_arguments": sorted(schema.get("properties", {})),
            "required_arguments": schema.get("required", [])}


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
    existing_all_of = list(schema.get("allOf", []))
    combined_all_of = [*existing_all_of, *conditions]
    if combined_all_of:
        schema["allOf"] = combined_all_of
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
    elif tool == "local_ai_task" and action == "automation":
        properties.update({
            "error_code": {"type": "string"}, "outcome_unknown": {"type": "boolean"},
            "automation": {"type": "object", "properties": {
                **{name: {"type": "string"} for name in ("session_id", "session_key", "mode", "isolation", "url", "title", "text", "tab_id", "artifact_id", "mime_type")},
                **{name: {"type": "boolean"} for name in ("closed", "fenced", "network_egress_isolated")},
                "expires_in_seconds": {"type": "number"}, "size_bytes": {"type": "integer"},
                "tabs": {"type": "array", "items": {"type": "object"}},
            }, "additionalProperties": True},
        })
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
    """Describe the compact readiness response and its error envelope."""
    failure = {
        "type": "object",
        "required": ["success", "error"],
        "properties": {"success": {"const": False}, "error": {"type": "string"}},
        "additionalProperties": True,
    }
    if action != "brief":
        return []
    return [{
        "type": "object",
        "required": ["success", "version", "ollama_online", "active_model", "degraded"],
        "properties": {
            "success": {"type": "boolean"},
            "version": {"type": ["string", "null"]},
            "ollama_online": {"type": ["boolean", "null"]},
            "active_model": {"type": ["string", "null"]},
            "degraded": {"type": "boolean"},
            "vram_pressure": {"type": "string"},
            "context_budget_factor": {"type": "number"},
            "dependency_status": {"type": "object"},
        },
        "additionalProperties": True,
    }, failure]


def _artifact_output_variants(action: str) -> list[dict[str, Any]]:
    """Return result variants from the artifact, evidence, and HTTP handlers."""
    failure = {
        "type": "object",
        "required": ["success", "error"],
        "properties": {"success": {"const": False}, "error": {"type": "string"}},
        "additionalProperties": True,
    }
    source_result = {
        "type": "object",
        "required": ["success", "action", "path", "relative_path", "file_sha256",
                     "line_start", "line_end", "requested_line_end", "total_lines",
                     "text", "truncated", "complete"],
        "properties": {
            "success": {"const": True}, "action": {"const": "source"},
            **{key: {"type": "string"} for key in ("path", "relative_path", "file_sha256", "text")},
            **{key: {"type": "integer"} for key in ("line_start", "line_end", "requested_line_end", "total_lines")},
            "truncated": {"type": "boolean"}, "complete": {"type": "boolean"},
        },
        "additionalProperties": True,
    }
    batch_source_result = {
        "type": "object",
        "required": ["success", "slices", "count"],
        "properties": {
            "success": {"const": True},
            "slices": {"type": "array"},
            "count": {"type": "integer"},
        },
        "additionalProperties": True,
    }
    if action == "source":
        return [source_result, batch_source_result, failure]
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
        "required": [
            "success", "artifact_id", "kind", "mime_type", "encoding", "size_bytes",
            "checksum", "sha256", "identity", "binary_payload",
        ],
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
    return [text_result, multi_slice_result, evidence_result, binary_result, source_result, batch_source_result, failure]


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
    "mutation_applied": {"type": "boolean"},
    "operation_not_started": {"type": "boolean"},
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
    # Validate every published envelope field before FastMCP serializes it.
    # Unknown optional booleans are not silently converted to false.
    for field, schema in _OUTPUT_ENVELOPE_PROPERTIES.items():
        if field in result:
            error = _validate_output_schema(result[field], schema, f"result.{field}")
            if error:
                return f"{error} for action='{action}'"
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
    if tool == "local_ai_repo" and "hotspots" in available_actions:
        parameters.setdefault("allOf", []).append({
            "if": {
                "properties": {selector_field: {"const": "hotspots"}},
                "required": [selector_field],
            },
            "then": {
                "properties": {
                    "days": {"type": "integer", "minimum": 1, "maximum": 3650, "default": 30},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
                },
            },
        })
    if tool == "local_ai_artifact":
        parameters.setdefault("allOf", []).append({
            "if": {
                "properties": {selector_field: {"const": "source"}},
                "required": [selector_field],
            },
            "then": {
                "properties": {"max_chars": {"minimum": 512, "maximum": 12000}},
            },
        })
    if tool == "local_ai_coord" and "task_sync" in available_actions:
        parameters.setdefault("allOf", []).extend((
            {
                "if": {
                    "properties": {
                        selector_field: {"const": "task_sync"},
                        "sync_action": {"const": "import"},
                    },
                    "required": [selector_field, "sync_action"],
                },
                "then": {"required": ["events"]},
            },
            {
                "if": {
                    "properties": {selector_field: {"const": "task_sync"}},
                    "required": [selector_field],
                },
                "then": {"allOf": [{
                    "if": {
                        "properties": {"sync_action": {"const": "import"}},
                        "required": ["sync_action"],
                    },
                    "then": {},
                    "else": {"not": {"required": ["events"]}},
                }]},
            },
            {
                "if": {
                    "properties": {
                        selector_field: {"const": "task_sync"},
                        "sync_action": {"const": "import"},
                    },
                    "required": [selector_field, "sync_action"],
                },
                "then": {"not": {"anyOf": [
                    {"required": ["stream_id"]},
                    {"required": ["after_seq"]},
                    {"required": ["limit"]},
                ]}},
            },
        ))
    if tool == "local_ai_coord" and "context_compile" in available_actions:
        parameters.setdefault("allOf", []).append({
            "if": {
                "properties": {selector_field: {"const": "context_compile"}},
                "required": [selector_field],
            },
            "then": {"properties": {"max_tokens": {"default": 4000}}},
        })
    if tool == "local_ai_coord" and "negative_knowledge_find" in available_actions:
        parameters.setdefault("allOf", []).append({
            "if": {
                "properties": {selector_field: {"const": "negative_knowledge_find"}},
                "required": [selector_field],
            },
            "then": {
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 100},
                },
            },
        })
    if tool == "local_ai_coord" and "negative_knowledge_record" in available_actions:
        parameters.setdefault("allOf", []).append({
            "if": {
                "properties": {selector_field: {"const": "negative_knowledge_record"}},
                "required": [selector_field],
            },
            "then": {"properties": {"record": deepcopy(_INCIDENT_RECORD_SCHEMA)}},
        })
    return parameters


def validate_operation_call(
    tool: str,
    arguments: dict[str, Any],
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
    if selector not in arguments:
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
    if tool == "local_ai_repo" and action in {"search", "code_index", "callers", "callees", "implementations"}:
        bounds_error = pagination_bounds_error(
            arguments.get("limit", properties.get("limit", {}).get("default", 24)),
            arguments.get("offset", properties.get("offset", {}).get("default", 0)),
        )
        if bounds_error:
            return bounds_error
    if tool == "local_ai_repo" and action == "hotspots":
        days = arguments.get("days", 30)
        limit = arguments.get("limit", 20)
        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 3650:
            return "days must be an integer from 1 to 3650 for action='hotspots'"
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
            return "limit must be an integer from 1 to 50 for action='hotspots'"
    if tool == "local_ai_coord" and action.startswith("plan_"):
        from .repository_scope import canonical_repository_root
        try:
            canonical_repository_root(arguments.get("root"))
        except ValueError as exc:
            return str(exc)
        if action == "plan_list":
            limit = arguments.get("limit", 50)
            if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
                return "limit must be an integer from 1 to 1000 for plan_list"
        if "expected_revision" in arguments:
            revision = arguments["expected_revision"]
            if not isinstance(revision, str) or not revision or revision != revision.strip():
                return "expected_revision must be a nonempty content revision string"
    if tool == "local_ai_coord" and action == "task_sync":
        sync_action = arguments.get("sync_action", "export")
        if not isinstance(sync_action, str) or sync_action not in {"export", "import"}:
            return "sync_action must be 'export' or 'import' for action='task_sync'"
        if sync_action == "export" and "events" in arguments:
            return "events is only valid for sync_action='import'"
        if sync_action == "import":
            if "events" not in arguments:
                return "events is required for sync_action='import'"
            irrelevant = {"stream_id", "after_seq", "limit"} & set(arguments)
            if irrelevant:
                return f"{sorted(irrelevant)[0]} is not valid for sync_action='import'"
        limit = arguments.get("limit", 1000)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            return "limit must be an integer from 1 to 1000 for action='task_sync'"
    if tool == "local_ai_coord" and action == "negative_knowledge_find":
        for field in ("root", "query"):
            value = arguments.get(field, properties.get(field, {}).get("default"))
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
                or "\x00" in value
            ):
                return f"{field} must be a canonical non-empty string for action='negative_knowledge_find'"
        limit = arguments.get("limit", 100)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            return "limit must be an integer from 1 to 100 for action='negative_knowledge_find'"
    if tool == "local_ai_coord" and action in {"negative_knowledge_record", "incident_decision"}:
        field = "record" if action == "negative_knowledge_record" else "fingerprint"
        if field in arguments:
            nested_schema = _INCIDENT_RECORD_SCHEMA if action == "negative_knowledge_record" else properties[field]
            nested_error = _validate_nested_schema(arguments[field], nested_schema, field, action)
            if nested_error:
                return nested_error
    if tool == "local_ai_artifact" and action == "source" and "max_chars" in arguments:
        max_chars = arguments["max_chars"]
        if isinstance(max_chars, bool) or not isinstance(max_chars, int) or not 512 <= max_chars <= 12000:
            return "max_chars must be between 512 and 12000 for action='source'"
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
            if value not in allowed_values:
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
    if tool == "local_ai_coord" and action == "ask":
        question_id = arguments.get("question_id", "")
        question = arguments.get("question", "")
        if not question_id.strip() and not question.strip():
            return "question or question_id is required for action='ask'"
    if tool == "local_ai_coord" and action == "verify_receipt":
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
