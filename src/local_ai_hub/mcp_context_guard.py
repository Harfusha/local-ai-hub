from __future__ import annotations

import re
from typing import Any

_GUARDED_CONTEXT_TOP_LEVEL = frozenset({
    "success", "status", "status_code", "terminal", "retryable", "error", "warning", "message", "stop_code",
    "context", "context_source", "continuation", "evidence", "evidence_ids", "warnings", "warning_ids",
    "adaptive_context_pack", "context_pack", "context_id", "repo_revision", "revision", "memory_revision", "degraded_reason",
    "changed_paths", "stale", "since_hash", "delta_from", "guarded", "delivery_mode", "degraded",
    "fallback_used", "requires_override", "requires_approval", "decision_recorded", "decision_persisted",
    "task_status", "waiting", "contract", "reuse", "reuse_candidates", "mappings", "model_warnings",
    "relevance", "model_degraded", "model_degraded_reason", "response_budget", "reuse_key", "reused",
    "unchanged", "preload_profile", "preload_evidence_ids",
    "task_context", "task_context_artifact_id", "task_id", "complete", "partial", "text", "source_layers", "agent_state", "repository",
    "provenance", "omitted_sections", "next_action", "estimated_tokens", "truncated",
})
_GUARDED_CONTEXT_PACK = frozenset({
    "success", "status", "status_code", "terminal", "retryable", "error", "warning", "message",
    "degraded", "fallback_used", "requires_override", "requires_approval", "decision_recorded",
    "decision_persisted", "task_status", "waiting",
    "contract", "reuse_candidates", "mappings", "warnings", "evidence", "evidence_ids", "repo_revision", "changed_paths",
    "stale", "context_id", "phase", "focus", "preload_profile", "memory_revision", "model_warnings",
    "delta_from", "since_hash", "unchanged", "reuse_pointer",
})
_GUARDED_RAW_FIELDS = frozenset({
    "raw", "prompt", "model_debug", "raw_model_output", "raw_output", "model_output", "model_response",
    "debug", "debug_trace", "trace", "full_trace", "completion", "response_raw",
})
def _guarded_field_is_safe(name: str, extra_fields: set[str]) -> bool:
    normalized = re.sub(r"[-\s]+", "_", name.strip().lower())
    if normalized in extra_fields:
        return True
    if normalized in _GUARDED_RAW_FIELDS:
        return False
    return not any(marker in normalized for marker in ("raw_", "_raw", "prompt", "debug", "trace"))
def _guarded_context_input(value: Any, *, extra_fields: list[str] | None = None, depth: int = 0, parent: str = "") -> Any:
    extra = {re.sub(r"[-\s]+", "_", str(item).strip().lower()) for item in (extra_fields or ()) if str(item).strip()}
    if isinstance(value, list):
        return [_guarded_context_input(item, extra_fields=list(extra), depth=depth + 1, parent=parent) for item in value[:64]]
    if not isinstance(value, dict):
        return value
    safe: dict[str, Any] = {}
    for raw_key, item in list(value.items())[:64]:
        key = str(raw_key)
        normalized = re.sub(r"[-\s]+", "_", key.strip().lower())
        if not _guarded_field_is_safe(key, extra):
            continue
        if depth == 0 and normalized not in _GUARDED_CONTEXT_TOP_LEVEL and normalized not in extra:
            continue
        if depth == 1 and parent in {"adaptive_context_pack", "context_pack"} and normalized not in _GUARDED_CONTEXT_PACK and normalized not in extra:
            continue
        safe[key] = _guarded_context_input(item, extra_fields=list(extra), depth=depth + 1, parent=normalized)
    return safe


def get_mcp_server_module() -> Any:
    import sys
    for mod_name, mod in list(sys.modules.items()):
        if mod_name.startswith("local_ai_hub._mcp_server_") and mod is not None:
            return mod
    from . import mcp_server
    return mcp_server
