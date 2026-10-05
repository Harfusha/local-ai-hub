"""Shared public operation contracts for MCP exposure and validation."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class HttpMutationContract:
    """One HTTP mutation whose outcome is safe and useful to replay by request ID."""

    method: str
    path: str
    action_field: str = ""
    action: str = ""
    default_action: str = ""

    def matches(self, method: str, path: str, payload: Mapping[str, Any]) -> bool:
        if method.upper() != self.method or path != self.path:
            return False
        if not self.action_field:
            return True
        value = payload.get(self.action_field, self.default_action)
        if self.action == "*":
            return isinstance(value, str) and bool(value.strip())
        actual = str(value).strip().lower().replace("-", "_")
        return actual == self.action


@dataclass(frozen=True)
class OperationContract:
    """Stable tool-level schema binding, gate, and transport metadata."""

    name: str
    feature_gate: str
    effects: str
    retry: str
    timeout: str
    projection: str
    # Key into T01's generated schemas and the MCP runtime schema catalog.
    schema_key: str
    http_mutations: tuple[HttpMutationContract, ...] = ()


# The eight public tools remain the single registered MCP surface. Detailed
# actions stay owned by FeatureSet; this table holds cross-transport contracts.
# Journal only explicit side-effecting mutations. Unlisted POSTs, including
# /api/context/pack, recompute fresh output and do not store compute results.
MCP_OPERATION_CONTRACTS = (
    OperationContract("local_ai_status", "status", "read-only", "safe", "quick", "status", schema_key="local_ai_status"),
    OperationContract("local_ai_repo", "repo", "action-dependent", "action-dependent", "action-dependent", "action-dependent", schema_key="local_ai_repo"),
    OperationContract("local_ai_task", "tasks", "action-dependent", "action-dependent", "action-dependent", "action-dependent", schema_key="local_ai_task"),
    OperationContract(
        "local_ai_rag", "rag", "action-dependent", "action-dependent", "action-dependent", "action-dependent",
        schema_key="local_ai_rag",
        http_mutations=(
            HttpMutationContract("POST", "/api/rag/index"),
            HttpMutationContract("POST", "/api/rag/ingest_document"),
            HttpMutationContract("POST", "/api/ingest_document"),
        ),
    ),
    OperationContract(
        "local_ai_command", "commands", "action-dependent", "action-dependent", "action-dependent", "action-dependent",
        schema_key="local_ai_command",
        http_mutations=(HttpMutationContract("POST", "/api/command", action_field="command", action="*"),),
    ),
    OperationContract(
        "local_ai_coord", "coord", "action-dependent", "action-dependent", "action-dependent", "action-dependent",
        schema_key="local_ai_coord",
        http_mutations=(
            HttpMutationContract("POST", "/api/coord/pubsub_publish"),
            HttpMutationContract("POST", "/api/pubsub_publish"),
            HttpMutationContract("POST", "/api/agent-state/tasks", action_field="action", action="checkpoint"),
        ),
    ),
    OperationContract("local_ai_artifact", "artifacts", "read-only", "safe", "quick", "artifact", schema_key="local_ai_artifact"),
    OperationContract(
        "local_ai_work", "work_orchestrator", "action-dependent", "action-dependent", "action-dependent", "action-dependent",
        schema_key="local_ai_work",
        http_mutations=(HttpMutationContract("POST", "/api/work-orders", action_field="action", action="submit", default_action="submit"),),
    ),
)


def http_operation_needs_replay(method: str, path: str, payload: Mapping[str, Any]) -> bool:
    """Return true only for an explicitly registered replayable HTTP mutation."""
    return any(
        operation.matches(method, path, payload)
        for contract in MCP_OPERATION_CONTRACTS
        for operation in contract.http_mutations
    )

STATUS_ACTIONS = ("", "brief", "cache", "telemetry", "full", "agent_state", "status", "health", "check", "info")
STATUS_DETAILS = ("brief", "cache", "telemetry", "full", "agent_state")
STATUS_ALIASES = ("status", "health", "check", "info")
REPO_PHASES = ("", "plan", "edit", "review", "test", "handoff")
MAX_REPO_PIPELINE_PARALLEL_STEPS = 4
MAX_EVENT_SEQUENCE = (1 << 63) - 1
ACTION_SPECIFIC_FIELDS: dict[str, dict[str, frozenset[str]]] = {
    # `action` is the detail alias. Reject two selectors so the caller's
    # explicit detail cannot be silently ignored when action is present.
    "local_ai_status": {"detail": frozenset({""})},
    "local_ai_task": {
        **{
            name: frozenset({"delegate", "explore", "reason", "review", "second_opinion", "compress"})
            for name in ("phase", "focus", "preload_profile", "repository_revision", "changed_paths")
        },
        **{
            name: frozenset({"vision"})
            for name in (
                "image_artifact_id", "screenshot_artifact_id", "bundle_artifact_id",
                "dom_artifact_id", "accessibility_artifact_id", "computed_styles_artifact_id",
                "runtime_artifact_id", "network_artifact_id", "source", "cloud_fallback",
                "dom", "accessibility", "computed_styles", "runtime", "viewport", "page",
                "bundle", "html", "accessibility_snapshot", "computed_style_data", "runtime_context",
            )
        },
        "candidate_data": frozenset({"candidate_create", "prompt_eval"}),
        "approver": frozenset({"candidate_promote"}),
        "evaluation_task_id": frozenset({"candidate_promote", "evaluation_record"}),
        "evaluation_cohort": frozenset({"evaluation_record"}),
        "quality_pass": frozenset({"evaluation_record"}),
        "test_pass": frozenset({"evaluation_record"}),
        "evaluation_duration_ms": frozenset({"evaluation_record"}),
        "evaluation_days": frozenset({"evaluation_report"}),
        "cases": frozenset({"eval_suite"}),
        "tasks": frozenset({"batch", "submit", "status", "wait", "result", "cancel"}),
        "job_action": frozenset({"submit", "status", "wait", "result", "cancel"}),
        "job_id": frozenset({"submit", "status", "wait", "result", "cancel"}),
        "timeout_seconds": frozenset({"submit", "status", "wait", "result", "cancel"}),
        "conversation_id": frozenset({"continue"}),
        "conversation": frozenset({"delegate", "explore", "reason"}),
        "delivery": frozenset({"delegate", "explore", "reason", "review", "second_opinion", "compress", "route", "batch"}),
        "latency_budget_ms": frozenset({"delegate", "explore", "reason", "review", "second_opinion", "compress", "route", "batch"}),
        "format": frozenset({"delegate", "explore", "reason", "review"}),
        "json_schema": frozenset({"delegate", "explore", "reason", "review", "vision"}),
        "language": frozenset({"scaffold"}),
    },
    "local_ai_rag": {
        "content": frozenset({"ingest_document"}),
        "title": frozenset({"ingest_document"}),
        "metadata": frozenset({"ingest_document", "ingest_diagram"}),
        "image_path": frozenset({"ingest_diagram"}),
        "caption": frozenset({"ingest_diagram"}),
        "top_k": frozenset({"search", "docset_search"}),
        "extra_fields": frozenset({"ingest_diagram"}),
    },
    "local_ai_command": {
        "rollback_on_failure": frozenset({"run"}),
        "lint_action": frozenset({"speculative_lint"}),
    },
    "local_ai_coord": {
        "paths": frozenset({"claim", "context_compile", "swarm_dispatch"}),
        "contract": frozenset({
            "task_create", "task_get", "task_checkpoint", "task_rollback", "task_transition",
            "task_resume", "task_list", "task_complete", "task_fail", "task_heartbeat",
        }),
        "include_stale": frozenset({
            "task_create", "task_get", "task_checkpoint", "task_rollback", "task_transition",
            "task_resume", "task_list", "task_complete", "task_fail", "task_heartbeat",
        }),
        "checkpoint": frozenset({
            "task_create", "task_get", "task_checkpoint", "task_rollback", "task_transition",
            "task_resume", "task_list", "task_complete", "task_fail", "task_heartbeat",
            "verify_receipt", "blackboard_update", "blackboard_get", "blackboard_list",
            "blackboard_merge", "blackboard_delete",
        }),
        "since_hash": frozenset({"context_compile"}),
        "include_diagnostics": frozenset({"context_compile"}),
        "focus": frozenset({"context_compile"}),
        "preload_profile": frozenset({"context_compile"}),
        "phase": frozenset({"context_compile"}),
        "repository_revision": frozenset({"context_compile"}),
        "fingerprint": frozenset({"incident_decision"}),
        "tool_outcome": frozenset({"incident_decision"}),
        "after_seq": frozenset({"pubsub_poll"}),
    },
    "local_ai_artifact": {
        "artifact_id": frozenset({"", "get", "slice"}),
    },
    "local_ai_work": {
        "root": frozenset({"submit"}),
        "task": frozenset({"submit"}),
        "acceptance_criteria": frozenset({"submit"}),
        "constraints": frozenset({"submit"}),
        "mode": frozenset({"submit"}),
        "permissions": frozenset({"submit"}),
        "budget": frozenset({"submit"}),
        "keep_failed_workspace": frozenset({"submit"}),
        "work_id": frozenset({"status", "wait", "get", "cancel", "continue"}),
        "timeout_seconds": frozenset({"wait"}),
        "answer": frozenset({"continue"}),
        "response_profile": frozenset({"submit", "get"}),
        "return_fields": frozenset({"submit", "get"}),
        "max_output_tokens": frozenset({"submit", "get"}),
    },
    # Pipeline and experimental batch fields only apply to their owning actions.
    "local_ai_repo": {
        **{
            name: frozenset({"context_compile"})
            for name in (
                "include_diagnostics", "clone_id", "worktree_id", "branch",
                "repository_id", "session_id", "repository_revision",
            )
        },
        "is_worktree": frozenset({"preprocess"}),
        "parent_root": frozenset({"preprocess"}),
        "steps": frozenset({"pipeline"}),
        "edits": frozenset({"batch_replace", "pipeline"}),
        "dry_run": frozenset({"batch_replace", "pipeline"}),
        "include_code": frozenset({"investigate", "search", "code_index", "pipeline"}),
        "include_tests": frozenset({"complexity", "pipeline"}),
        "language": frozenset({"resolve_imports", "pipeline"}),
        "path_hints": frozenset({"search"}),
        "directory_hints": frozenset({"context"}),
        "exclude_paths": frozenset({"context"}),
        "force_include_paths": frozenset({"context"}),
        "receipt": frozenset({"verify_receipt"}),
    },
}

ACTION_SPECIFIC_FIELD_DEFAULTS: dict[str, dict[str, Any]] = {
    "local_ai_task": {
        "phase": "", "focus": None, "preload_profile": "",
        "repository_revision": "", "changed_paths": None,
        "cloud_fallback": False, "candidate_data": None, "quality_pass": None,
        "test_pass": None, "evaluation_duration_ms": 0.0, "evaluation_days": 30,
        "cases": None, "tasks": None, "job_action": "reason", "job_id": "",
        "timeout_seconds": 90, "conversation_id": "", "conversation": False,
        "delivery": "sync", "latency_budget_ms": 0.0, "format": None,
        "json_schema": None, "language": "auto",
        **{name: "" for name in (
            "image_artifact_id", "screenshot_artifact_id", "bundle_artifact_id",
            "dom_artifact_id", "accessibility_artifact_id", "computed_styles_artifact_id",
            "runtime_artifact_id", "network_artifact_id", "source", "approver",
            "evaluation_task_id", "evaluation_cohort",
        )},
        **{name: None for name in (
            "dom", "accessibility", "computed_styles", "runtime", "viewport", "page",
            "bundle", "html", "accessibility_snapshot", "computed_style_data", "runtime_context",
        )},
    },
    "local_ai_rag": {
        "content": "", "title": "", "metadata": None, "image_path": "",
        "caption": "", "top_k": 6, "extra_fields": None,
    },
    "local_ai_command": {"rollback_on_failure": False, "lint_action": "submit"},
    "local_ai_coord": {
        "paths": None, "contract": None, "include_stale": False, "checkpoint": None,
        "since_hash": "", "include_diagnostics": False, "focus": None,
        "preload_profile": "", "phase": "", "repository_revision": "",
        "fingerprint": None, "tool_outcome": None, "after_seq": 0,
    },
    "local_ai_artifact": {"artifact_id": ""},
    "local_ai_repo": {
        "steps": None, "edits": None, "dry_run": False, "include_code": False,
        "include_tests": False, "language": "auto", "include_diagnostics": False,
        "clone_id": "", "worktree_id": "", "branch": "", "repository_id": "",
        "session_id": "", "repository_revision": "", "is_worktree": False,
        "parent_root": "", "directory_hints": None, "exclude_paths": None,
        "force_include_paths": None,
    },
    "local_ai_work": {
        "root": ".", "task": "", "acceptance_criteria": None, "constraints": None,
        "mode": "execute", "permissions": None, "budget": None, "work_id": "",
        "timeout_seconds": 90.0, "answer": "", "response_profile": "compact",
        "return_fields": None, "max_output_tokens": 0, "keep_failed_workspace": False,
    },
}

ACTION_DEFAULTS = {"local_ai_status": "", "local_ai_artifact": "get"}
ACTION_REQUIRED_FIELDS: dict[str, dict[str, tuple[str, ...]]] = {
    "local_ai_task": {"continue": ("conversation_id",)},
    "local_ai_repo": {"verify_receipt": ("receipt",)},
    "local_ai_artifact": {"get": ("artifact_id",), "slice": ("artifact_id",)},
    "local_ai_work": {
        "submit": ("task",),
        "status": ("work_id",),
        "wait": ("work_id",),
        "get": ("work_id",),
        "cancel": ("work_id",),
        "continue": ("work_id", "answer"),
    },
}
ACTION_REQUIRED_NONEMPTY_FIELDS = frozenset({"artifact_id", "conversation_id", "task", "work_id", "answer"})
ACTION_SPECIFIC_BOUNDS: dict[str, dict[str, dict[str, dict[str, int]]]] = {
    # `ttl_seconds` carries PubSub page size at this action boundary; zero keeps
    # the documented default while positive values match the HTTP limit range.
    "local_ai_coord": {"ttl_seconds": {"pubsub_poll": {"minimum": 0, "maximum": 1000}}},
}

_OPEN_OBJECT = {"type": "object", "additionalProperties": True}
_OUTPUT_ENVELOPE_PROPERTIES: dict[str, dict[str, Any]] = {
    "success": {"type": "boolean"},
    "status": {"type": "string"},
    "status_code": {"type": "integer"},
    "mode": {"type": "string"},
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
    "response_budget": _OPEN_OBJECT,
    "warnings": {"type": "array", "items": {"anyOf": [{"type": "string"}, _OPEN_OBJECT]}},
    "warning_ids": {"type": "array", "items": {"type": "string"}},
    "retry_after_seconds": {"type": "number"},
    "outcome_unknown": {"type": "boolean"},
    "request_not_sent": {"type": "boolean"},
    "retried": {"type": "boolean"},
    "evidence_ids": {"type": "array", "items": {"type": "string"}},
    "evidence": {"type": "array", "items": _OPEN_OBJECT},
    "cancel": _OPEN_OBJECT,
    "cancel_requested": {"type": "boolean"},
    "cancelled": {"type": "boolean"},
    "cancel_reason": {"type": "string"},
    "timed_out": {"type": "boolean"},
    "complete": {"type": "boolean"},
    "partial": {"type": "boolean"},
    "truncated": {"type": "boolean"},
    "estimated_tokens": {"type": "integer"},
    "reuse_key": {"type": "string"},
    "reused": {"type": "boolean"},
    "unchanged": {"type": "boolean"},
    "request_id": {"type": "string"},
    "unsupported": {"type": "boolean"},
}

_OUTPUT_ACTION_PROPERTIES: dict[str, dict[str, dict[str, Any]]] = {
    "local_ai_status": {
        "brief": {
            "version": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "ollama_online": {"anyOf": [{"type": "boolean"}, {"type": "null"}]},
            "active_model": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "queued": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
            "inflight": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
            "net_cloud_token_delta_est": {"type": "number"},
            "cache_hits": {"type": "integer"},
            "coalesced_waiters": {"type": "integer"},
            "vram_pressure": {"type": "string"},
            "context_budget_factor": {"type": "number"},
        },
        "cache": {
            **{name: {"anyOf": [_OPEN_OBJECT, {"type": "null"}]} for name in (
                "generation_cache", "semantic_cache", "repo_cache", "repo_snapshots",
                "commands", "lossless_router", "pipeline", "preprocessing", "tool_agent",
                "circuit_breakers", "embeddings", "reranker", "token_saving", "context_ledger",
            )},
        },
        "telemetry": {
            "window": _OPEN_OBJECT,
            "summary": {
                "type": "object",
                "properties": {name: {"type": "number"} for name in (
                    "events", "cache_hits", "coalesced", "input_tokens", "output_tokens",
                    "avoided_cloud_tokens", "avg_duration_ms", "failure_rate", "avg_queue_wait_ms",
                    "fallback_count", "degraded_count", "retry_count", "cache_hit_rate",
                    "net_cloud_token_delta_est",
                )},
                "additionalProperties": True,
            },
            "queue": _OPEN_OBJECT,
            "hotspots": {"type": "array", "items": _OPEN_OBJECT},
            "by_operation": {"type": "array", "items": _OPEN_OBJECT},
            "error_fingerprints": {"type": "array", "items": _OPEN_OBJECT},
            "detail": _OPEN_OBJECT,
            "decision_grade": _OPEN_OBJECT,
        },
        "full": {
            "hub_pid": {"type": "integer"},
            "hub_online": {"type": "boolean"},
            "version": {"type": "string"},
            "uptime_seconds": {"type": "integer"},
            "features": _OPEN_OBJECT,
            "models": _OPEN_OBJECT,
            "hardware": _OPEN_OBJECT,
            "accelerators": _OPEN_OBJECT,
            "ollama_online": {"anyOf": [{"type": "boolean"}, {"type": "null"}]},
            "online": {"type": "boolean"},
            "ollama_version": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "installed_models": {"type": "array", "items": {"type": "string"}},
            "loaded_models": {"type": "array", "items": {"type": "string"}},
            "loaded_model_details": {"type": "array", "items": _OPEN_OBJECT},
            **{name: _OPEN_OBJECT for name in (
                "capabilities", "code_intelligence", "runtime_profile", "scheduler", "headless",
                "background_gpu", "ollama_profile", "model_execution", "vram_balancer", "benchmark",
                "debug_traces", "observability", "preprocessing", "runtime_stats", "agent_state",
                "semantic_cache", "repo_cache", "commands", "repo_snapshots", "lossless_router",
                "pipeline", "tool_agent", "code_index", "deterministic", "evidence_store",
                "learning", "autotune", "circuit_breakers", "recovery", "embeddings", "reranker",
                "token_saving", "http_concurrency",
            )},
            "fallback_count": {"type": "integer"},
        },
        "agent_state": {
            "enabled": {"type": "boolean"},
            "active_tasks": {"type": "array", "items": {"type": "string"}},
            "tasks_count": {"type": "integer"},
            "incidents_count": {"type": "integer"},
            "candidates_count": {"type": "integer"},
            "status": {"type": "string"},
        },
    },
    "local_ai_task": {
        "candidate_create": {"candidate": _OPEN_OBJECT},
        "candidate_promote": {"decision": _OPEN_OBJECT},
    },
    "local_ai_coord": {
        **{
            action: {"task": _OPEN_OBJECT}
            for action in (
                "task_create", "task_get", "task_checkpoint", "task_transition",
                "task_resume", "task_rollback", "task_complete", "task_fail", "task_heartbeat",
            )
        },
        "task_list": {"tasks": {"type": "array", "items": _OPEN_OBJECT}},
        "task_zombie_reap": {
            "reaped": {"type": "array"},
            "count": {"type": "number"},
        },
        **{
            action: {"record": _OPEN_OBJECT}
            for action in ("memory_record", "memory_get", "memory_promote")
        },
        "memory_find": {"records": {"type": "array", "items": _OPEN_OBJECT}},
        "memory_reap": {"reaped_count": {"type": "number"}},
        "relation_record": {"relation": _OPEN_OBJECT},
        "relation_find": {"relations": {"type": "array"}},
        "context_compile": {
            "complete": {"type": "boolean"},
            "partial": {"type": "boolean"},
            "context_id": {"type": "string"},
            "etag": {"type": "string"},
            "context": _OPEN_OBJECT,
            "task_context": _OPEN_OBJECT,
            "text": {"type": "string"},
            "evidence_ids": {"type": "array", "items": {"type": "string"}},
            "repo_revision": {"type": "string"},
            "source_layers": {"type": "array"},
            "stale": {"type": "boolean"},
            "truncated": {"type": "boolean"},
            "omitted_sections": {"type": "array", "items": {"type": "string"}},
            "next_action": {"type": "string"},
            "estimated_tokens": {"type": "integer"},
            "warnings": {"type": "array"},
            "unchanged": {"type": "boolean"},
        },
        "verify_receipt": {"receipt": _OPEN_OBJECT},
        "verify_completion": {"completion": _OPEN_OBJECT},
        "incident_decision": {"decision": _OPEN_OBJECT},
        "negative_knowledge_record": {
            "incident": {"anyOf": [_OPEN_OBJECT, {"type": "null"}]}
        },
        "negative_knowledge_find": {
            "incidents": {"type": "array", "items": _OPEN_OBJECT}
        },
        **{
            action: {"incident": {"anyOf": [_OPEN_OBJECT, {"type": "null"}]}}
            for action in (
                "incident_record", "incident_resolve", "incident_ignore", "incident_unignore",
            )
        },
        "blackboard_list": {
            "boards": {"type": "array"},
            "count": {"type": "number"},
        },
    },
    # Pipeline results are stable; each step result remains open because the
    # selected repo action defines its payload.
    "local_ai_repo": {
        "pipeline": {
            "steps_total": {"type": "integer"},
            "steps_attempted": {"type": "integer"},
            "steps_completed": {"type": "integer"},
            "steps_failed": {"type": "integer"},
            "step_results": {"type": "array", "items": _OPEN_OBJECT},
            "results": {"type": "object", "additionalProperties": _OPEN_OBJECT},
        },
    },
    "local_ai_rag": {
        "search": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"chunk_no": {"type": "integer"}},
                    "additionalProperties": True,
                },
            },
        },
    },
    "local_ai_command": {"run": {"stdout": {"type": "string"}}},
    "local_ai_work": {
        "submit": {"work_id": {"type": "string"}, "status": {"type": "string"}},
        "status": {"status": {"type": "string"}},
    },
    "local_ai_artifact": {
        "slice": {
            "text": {"type": "string"},
            "next_offset": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
        },
    },
    "local_ai_command": {
        "speculative_lint": {
            "state": {"type": "string"},
            "job_id": {"type": "string"},
        },
    },
}

_STATUS_OUTPUT_ALIASES = {"": "brief", "status": "brief", "health": "brief", "check": "brief", "info": "brief"}
_ACTION_OUTPUT_ALIASES = {
    "local_ai_task": {"gen": "delegate", "rev": "review", "del": "delegate"},
    "local_ai_repo": {
        "idx": "code_index", "review": "review_diff", "sec": "security_audit",
        "ctx": "context",
    },
    "local_ai_command": {
        "patch": "patch_and_verify", "fix": "auto_fix", "repair": "repair_loop",
        "fmt": "format",
    },
    "local_ai_coord": {
        "ctx": "context_compile", "compile_ctx": "context_compile",
        "neg_rec": "negative_knowledge_record", "neg_find": "negative_knowledge_find",
        "mem_put": "memory_record", "mem_rec": "memory_record",
        "mem_get": "memory_get", "mem_find": "memory_find", "mem_search": "memory_find",
        "task_new": "task_create", "task_chk": "task_checkpoint",
        "task_done": "task_complete",
    },
}


def operation_output_schema(tool_name: str, action: str) -> dict[str, Any]:
    """Return typed known fields while keeping variable action payloads open."""
    if tool_name == "local_ai_status":
        canonical = _STATUS_OUTPUT_ALIASES.get(action, action)
    else:
        canonical = _ACTION_OUTPUT_ALIASES.get(tool_name, {}).get(action, action)
    properties = deepcopy(_OUTPUT_ENVELOPE_PROPERTIES)
    properties.update(deepcopy(_OUTPUT_ACTION_PROPERTIES.get(tool_name, {}).get(canonical, {})))
    if tool_name == "local_ai_task":
        properties.update({
            "task_context_id": {"type": "string"},
            "task_context_etag": {"type": "string"},
            "task_context_evidence_ids": {"type": "array", "items": {"type": "string"}},
        })
    return {
        "type": "object",
        "x-operation-action": action,
        "properties": properties,
        "additionalProperties": True,
    }


def operation_tool_output_schema(tool_name: str, actions: list[str] | tuple[str, ...]) -> dict[str, Any]:
    """Publish shared envelope and compact deltas for actions with output contracts."""
    action_contracts: dict[str, dict[str, Any]] = {}
    action_properties: dict[str, Any] = {}
    for action in actions:
        if tool_name == "local_ai_status":
            canonical = _STATUS_OUTPUT_ALIASES.get(action, action)
        else:
            canonical = _ACTION_OUTPUT_ALIASES.get(tool_name, {}).get(action, action)
        contracts = _OUTPUT_ACTION_PROPERTIES.get(tool_name, {})
        if canonical not in contracts and tool_name != "local_ai_task":
            continue
        delta = deepcopy(contracts.get(canonical, {}))
        if tool_name == "local_ai_task":
            delta.update({
                "task_context_id": {"type": "string"},
                "task_context_etag": {"type": "string"},
                "task_context_evidence_ids": {"type": "array", "items": {"type": "string"}},
            })
        action_contracts[action] = {
            "type": "object",
            "properties": delta,
            "additionalProperties": True,
        }
        action_properties.update(delta)
    if not action_contracts:
        return {"type": "object", "additionalProperties": True}
    properties = deepcopy(_OUTPUT_ENVELOPE_PROPERTIES)
    properties.update(action_properties)
    return {
        "type": "object",
        "properties": properties,
        "additionalProperties": True,
        "x-action-output-contracts": action_contracts,
    }


REPO_PIPELINE_MUTATING_ACTIONS = frozenset(
    {
        "batch_replace",
        "ast_refactor",
        "preprocess",
        "preprocess_refresh",
        "preprocess_pause",
        "preprocess_resume",
        "preprocess_cancel",
        "preprocess_unregister",
    }
)
RETRYABLE_HTTP_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})


def tool_enabled(features: Any, contract: OperationContract) -> bool:
    enabled = bool(getattr(features, contract.feature_gate, False))
    return enabled and (contract.name != "local_ai_task" or features.has_any_model())


def enabled_tool_names(features: Any) -> list[str]:
    return [contract.name for contract in MCP_OPERATION_CONTRACTS if tool_enabled(features, contract)]


def enabled_schema_keys(features: Any) -> list[str]:
    return [contract.schema_key for contract in MCP_OPERATION_CONTRACTS if tool_enabled(features, contract)]


def disabled_tool_names(features: Any) -> list[str]:
    return [contract.name for contract in MCP_OPERATION_CONTRACTS if not tool_enabled(features, contract)]


def operation_description(contract: OperationContract) -> str:
    return (
        f" Contract: effects={contract.effects}; retry={contract.retry}; "
        f"timeout={contract.timeout}; projection={contract.projection}."
    )


def _portable_property_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    value = deepcopy(dict(schema))
    value.pop("title", None)
    branches = value.get("anyOf")
    if isinstance(branches, list):
        non_null = [branch for branch in branches if branch.get("type") != "null"]
        if len(non_null) == 1:
            merged = _portable_property_schema(non_null[0])
            if value.get("default") is not None:
                merged["default"] = value["default"]
            for key in ("minimum", "maximum", "minLength", "maxLength", "enum", "items"):
                if key in value and key not in merged:
                    merged[key] = value[key]
            value = merged
        elif non_null:
            value.pop("anyOf", None)
            value["type"] = [branch["type"] for branch in non_null if "type" in branch]
    nested_properties = value.get("properties")
    if isinstance(nested_properties, Mapping):
        value["properties"] = {
            name: _portable_property_schema(child)
            if isinstance(child, Mapping) else child
            for name, child in nested_properties.items()
        }
    items = value.get("items")
    if isinstance(items, Mapping):
        value["items"] = _portable_property_schema(items)
    value.pop("$defs", None)
    value.pop("definitions", None)
    value.pop("description", None)
    value.pop("title", None)
    return value


def repo_pipeline_step_schema(
    repo_properties: Mapping[str, Any], repo_actions: list[str] | tuple[str, ...]
) -> dict[str, Any]:
    """Schema for one closed, independently validated repo pipeline step."""
    properties: dict[str, Any] = {
        "id": {"type": "string", "default": "", "maxLength": 128},
        "action": {
            "type": "string",
            "enum": [action for action in repo_actions if action != "pipeline"],
        },
    }
    properties.update(
        {
            name: _portable_property_schema(schema)
            for name, schema in repo_properties.items()
            if name not in {"action", "steps", "path_hints"}
        }
    )
    for name in ("max_tokens", "token_budget", "max_response_tokens"):
        if name in properties:
            properties[name].update({"minimum": 0, "maximum": 100000})
    if "phase" in properties:
        properties["phase"] = {"type": "string", "enum": list(REPO_PHASES), "default": ""}
    if "response_profile" in properties:
        properties["response_profile"] = {
            "type": "string",
            "enum": ["", "minimal", "compact", "standard", "debug", "delta"],
            "default": "",
        }
    return {
        "type": "object",
        "required": ["action"],
        "properties": properties,
        "additionalProperties": False,
    }


def repo_path_hints_schema() -> dict[str, Any]:
    """Closed, bounded path hints accepted by the public repository search action."""
    metadata = {
        name: {"type": "string"}
        for name in (
            "evidence_id", "provenance", "repository_revision", "config_digest", "expires_at",
        )
    }
    return {
        "type": "array",
        "maxItems": 64,
        "items": {
            "type": "object",
            "required": ["path", "purpose", "scope"],
            "properties": {
                "path": {"type": "string", "minLength": 1, "maxLength": 1024},
                "purpose": {"type": "string", "enum": ["repository_search"]},
                "scope": {"type": "string", "enum": ["repo_search"]},
                **metadata,
            },
            "additionalProperties": False,
        },
    }


def repo_verify_receipt_schema() -> dict[str, Any]:
    """Return the typed input contract for Agent OS verification receipts."""
    return {
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
    }
def validate_schema_value(value: Any, schema: Mapping[str, Any], path: str) -> str | None:
    """Small bounded JSON-schema subset for the MCP tool's declared inputs."""
    any_of = schema.get("anyOf")
    if isinstance(any_of, list) and any_of:
        if not any(validate_schema_value(value, branch, path) is None for branch in any_of):
            return f"{path} does not match any allowed schema"
    one_of = schema.get("oneOf")
    if isinstance(one_of, list) and one_of:
        matches = sum(validate_schema_value(value, branch, path) is None for branch in one_of)
        if matches != 1:
            return f"{path} must match exactly one schema"
    expected = schema.get("type")
    types = expected if isinstance(expected, list) else [expected]
    checks = {
        "string": lambda item: isinstance(item, str),
        "boolean": lambda item: isinstance(item, bool),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "object": lambda item: isinstance(item, Mapping),
        "array": lambda item: isinstance(item, list),
    }
    if expected and not any(checks.get(kind, lambda _: True)(value) for kind in types):
        return f"{path} must be {', '.join(str(kind) for kind in types)}"
    if "enum" in schema and value not in schema["enum"]:
        return f"{path} must be one of: {', '.join(map(str, schema['enum']))}"
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            return f"{path} must contain at least {schema['minLength']} characters"
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            return f"{path} exceeds {schema['maxLength']} characters"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            return f"{path} must be at least {schema['minimum']}"
        if "maximum" in schema and value > schema["maximum"]:
            return f"{path} must be at most {schema['maximum']}"
    if isinstance(value, Mapping) and isinstance(schema.get("properties"), Mapping):
        error = validate_schema_object(value, schema, path)
        if error:
            return error
    if isinstance(value, list) and isinstance(schema.get("items"), Mapping):
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            return f"{path} exceeds {schema['maxItems']} items"
        for index, item in enumerate(value):
            error = validate_schema_value(item, schema["items"], f"{path}[{index}]")
            if error:
                return error
    return None


def validate_repo_pipeline_step(
    step: Any,
    *,
    index: int,
    step_schema: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(step, Mapping):
        return None, f"steps[{index}] must be an object"
    value = dict(step)
    properties = step_schema["properties"]
    unknown = sorted(set(value) - set(properties))
    if unknown:
        return None, f"steps[{index}] contains unsupported fields: {', '.join(unknown)}"
    missing = [name for name in step_schema.get("required", []) if name not in value]
    if missing:
        return None, f"steps[{index}] requires: {', '.join(missing)}"
    for name, item in value.items():
        error = validate_schema_value(item, properties[name], f"steps[{index}].{name}")
        if error:
            return None, error
    if not value.get("action", "").strip():
        return None, f"steps[{index}].action must not be empty"
    return value, None


def validate_schema_object(value: Any, schema: Mapping[str, Any], path: str = "arguments") -> str | None:
    """Validate declared arguments before dispatching a tool handler."""
    if not isinstance(value, Mapping):
        return f"{path} must be an object"
    properties = schema.get("properties", {})
    if not isinstance(properties, Mapping):
        return None
    missing = [name for name in schema.get("required", []) if name not in value]
    if missing:
        return f"{path} requires: {', '.join(missing)}"
    unknown = sorted(set(value) - set(properties))
    if schema.get("additionalProperties") is False and unknown:
        return f"{path} contains unsupported fields: {', '.join(unknown)}"
    for name, item in value.items():
        if name not in properties:
            continue
        error = validate_schema_value(item, properties[name], f"{path}.{name}")
        if error:
            return error
    return None


def action_specific_schema_constraints(
    tool_name: str,
    available_fields: set[str] | None = None,
    available_actions: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Return standard JSON Schema rules for fields scoped to one action."""
    constraints: list[dict[str, Any]] = []
    field_defaults = ACTION_SPECIFIC_FIELD_DEFAULTS.get(tool_name, {})
    default_action = ACTION_DEFAULTS.get(tool_name)
    for field, allowed_actions in ACTION_SPECIFIC_FIELDS.get(tool_name, {}).items():
        if available_fields is not None and field not in available_fields:
            continue
        if available_actions is not None:
            allowed_actions = allowed_actions & available_actions
            if not allowed_actions:
                constraints.append({"not": {"required": [field]}})
                continue
        if len(allowed_actions) == 1:
            condition: dict[str, Any] = {"const": next(iter(allowed_actions))}
        else:
            condition = {"enum": sorted(allowed_actions)}
        action_condition: dict[str, Any] = {
            "properties": {"action": condition}, "required": ["action"]
        }
        if default_action in allowed_actions:
            action_condition = {"anyOf": [action_condition, {"not": {"required": ["action"]}}]}
        otherwise = (
            {"properties": {field: {"const": field_defaults[field]}}}
            if field in field_defaults else {"not": {"required": [field]}}
        )
        constraints.append({
            "if": action_condition,
            "then": {"properties": {field: {}}},
            "else": otherwise,
        })
    if tool_name == "local_ai_repo":
        for field in ("directory_hints", "exclude_paths", "force_include_paths"):
            if available_fields is not None and field not in available_fields:
                continue
            constraints.append({
                "if": {
                    "properties": {
                        "action": {"const": "context"},
                        "mode": {"not": {"const": "adaptive"}},
                    },
                    "required": ["action", "mode"],
                },
                "then": {"not": {"required": [field]}},
            })
    for action, required_fields in ACTION_REQUIRED_FIELDS.get(tool_name, {}).items():
        if available_actions is not None and action not in available_actions:
            continue
        action_condition = {
            "properties": {"action": {"const": action}}, "required": ["action"]
        }
        if ACTION_DEFAULTS.get(tool_name) == action:
            action_condition = {"anyOf": [action_condition, {"not": {"required": ["action"]}}]}
        constraints.append({
            "if": action_condition,
            "then": {
                "required": list(required_fields),
                "properties": {
                    field: {"minLength": 1}
                    for field in required_fields
                    if field in ACTION_REQUIRED_NONEMPTY_FIELDS
                },
            },
        })
    for field, actions in ACTION_SPECIFIC_BOUNDS.get(tool_name, {}).items():
        if available_fields is not None and field not in available_fields:
            continue
        for action, bounds in actions.items():
            if available_actions is not None and action not in available_actions:
                continue
            constraints.append({
                "if": {"properties": {"action": {"const": action}}, "required": ["action"]},
                "then": {"properties": {field: dict(bounds)}},
            })
    return constraints


def validate_action_specific_fields(
    tool_name: str,
    arguments: Mapping[str, Any],
    path: str = "arguments",
    schema: Mapping[str, Any] | None = None,
) -> str | None:
    """Reject known fields when their owning action is not selected."""
    action = str(arguments.get("action", ACTION_DEFAULTS.get(tool_name, ""))).strip().lower().replace("-", "_")
    available_fields: set[str] | None = None
    available_actions: set[str] | None = None
    if isinstance(schema, Mapping):
        properties = schema.get("properties", {})
        if isinstance(properties, Mapping):
            available_fields = set(properties)
            action_property = properties.get("action", {})
            if isinstance(action_property, Mapping):
                enum = action_property.get("enum")
                if isinstance(enum, list):
                    available_actions = {str(item) for item in enum}
        for field in ACTION_SPECIFIC_FIELDS.get(tool_name, {}):
            if field in arguments and available_fields is not None and field not in available_fields:
                return f"{path}.{field} is not supported by this configuration"
    for required_action, required_fields in ACTION_REQUIRED_FIELDS.get(tool_name, {}).items():
        if available_actions is not None and required_action not in available_actions:
            continue
        if action != required_action:
            continue
        missing = [field for field in required_fields if field not in arguments]
        if missing:
            return f"{path} requires for action {action}: {', '.join(missing)}"
        empty = [
            field for field in required_fields
            if field in ACTION_REQUIRED_NONEMPTY_FIELDS
            and (not isinstance(arguments[field], str) or not arguments[field].strip())
        ]
        if empty:
            return f"{path}.{empty[0]} must not be empty for action {action}"
    for field, action_bounds in ACTION_SPECIFIC_BOUNDS.get(tool_name, {}).items():
        if available_fields is not None and field not in available_fields:
            continue
        bounds = action_bounds.get(action)
        if bounds is None or field not in arguments:
            continue
        value = arguments[field]
        if isinstance(value, bool) or not isinstance(value, int):
            return f"{path}.{field} must be an integer for action {action}"
        if "minimum" in bounds and value < bounds["minimum"]:
            return f"{path}.{field} must be at least {bounds['minimum']} for action {action}"
        if "maximum" in bounds and value > bounds["maximum"]:
            return f"{path}.{field} must be at most {bounds['maximum']} for action {action}"
    field_defaults = ACTION_SPECIFIC_FIELD_DEFAULTS.get(tool_name, {})
    for field, allowed_actions in ACTION_SPECIFIC_FIELDS.get(tool_name, {}).items():
        if available_fields is not None and field not in available_fields:
            continue
        if available_actions is not None:
            allowed_actions = allowed_actions & available_actions
            if not allowed_actions:
                if field in arguments:
                    return f"{path}.{field} is not supported by this configuration"
                continue
        if field in arguments and action not in allowed_actions:
            if field in field_defaults and arguments[field] == field_defaults[field]:
                continue
            allowed = ", ".join(sorted(allowed_actions))
            return f"{path}.{field} is only valid for action {allowed}"
    if tool_name == "local_ai_repo" and action == "context":
        if arguments.get("mode", "adaptive") != "adaptive":
            for field in ("directory_hints", "exclude_paths", "force_include_paths"):
                if field in arguments:
                    return f"{path}.{field} requires mode adaptive for action context"
    if tool_name == "local_ai_repo" and action == "verify_receipt" and "receipt" in arguments:
        receipt = arguments["receipt"]
        if not isinstance(receipt, Mapping):
            return f"{path}.receipt must be an object"
        receipt_schema = schema.get("properties", {}).get("receipt") if isinstance(schema, Mapping) else None
        if not isinstance(receipt_schema, Mapping):
            receipt_schema = repo_verify_receipt_schema()
        error = validate_schema_value(receipt, receipt_schema, f"{path}.receipt")
        if error:
            return error
        for field in ("task_id", "criterion"):
            value = receipt.get(field)
            if not isinstance(value, str) or not value.strip():
                return f"{path}.receipt.{field} is required for action verify_receipt"
        if receipt.get("passed") is True:
            evidence_id = receipt.get("evidence_id")
            if not isinstance(evidence_id, str) or not evidence_id.strip():
                return f"{path}.receipt.evidence_id is required for passed verification receipts"
    return None


def contract_error(message: str, *, status_code: int = 400) -> dict[str, Any]:
    return normalize_transport_error(status_code, {"error": message[:500]})


def normalize_transport_error(status_code: int, payload: Any) -> dict[str, Any]:
    """Give every HTTP error one status and retry contract while preserving details."""
    result = dict(payload) if isinstance(payload, Mapping) else {"error": str(payload)}
    result["success"] = False
    result["status_code"] = int(status_code)
    retryable_default = status_code in RETRYABLE_HTTP_STATUS_CODES
    if "retryable" not in result and "terminal" not in result:
        result["retryable"] = retryable_default
        result["terminal"] = not retryable_default
    elif "retryable" not in result:
        result["retryable"] = not bool(result["terminal"])
    elif "terminal" not in result:
        result["terminal"] = not bool(result["retryable"])
    if isinstance(result.get("error"), str):
        result["error"] = result["error"][:500]
    return result
