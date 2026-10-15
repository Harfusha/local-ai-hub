"""Pure helpers for projecting and measuring task-memory MCP responses."""

from __future__ import annotations

import copy
from typing import Any

from .json_utils import dumps as json_dumps
from .token_accounting import json_tokens


def task_memory_audit_projection(value: Any) -> Any:
    """Current usage receipt only; never expose history, prompts or source bodies."""
    if value is None:
        return None
    if not isinstance(value, dict):
        return {"invalid": True}
    out: dict[str, Any] = {}
    truncated = False
    used = value.get("used_ids")
    if isinstance(used, (list, tuple)):
        out["used_ids"] = [item for item in used[:8] if isinstance(item, str)]
        truncated = len(used) > 8
    reason = value.get("not_used_reason")
    if isinstance(reason, str):
        out["not_used_reason"] = reason[:512]
        truncated |= len(reason) > 512
    if isinstance(value.get("source_checked"), bool):
        out["source_checked"] = value["source_checked"]
    checks = value.get("source_checks")
    if isinstance(checks, dict):
        out["source_checks"] = {}
        for memory_id, check in list(checks.items())[:8]:
            if not isinstance(memory_id, str):
                continue
            if isinstance(check, bool):
                out["source_checks"][memory_id] = check
            elif isinstance(check, dict):
                projected = {key: check[key] for key in ("checked", "source_checked")
                             if isinstance(check.get(key), bool)}
                if isinstance(check.get("evidence_id"), str):
                    projected["evidence_id"] = check["evidence_id"]
                if isinstance(check.get("evidence_ids"), (list, tuple)):
                    projected["evidence_ids"] = [item for item in check["evidence_ids"][:8]
                                                 if isinstance(item, str)]
                    truncated |= len(check["evidence_ids"]) > 8
                out["source_checks"][memory_id] = projected
        truncated |= len(checks) > 8
    if truncated:
        out["truncated"] = True
    return out


def normalize_task_memory_response(value: Any) -> Any:
    """Apply the deterministic key ordering used by the MCP memory projection."""
    if isinstance(value, dict):
        return {key: normalize_task_memory_response(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [normalize_task_memory_response(item) for item in value]
    return value


def task_memory_projection(value: Any) -> dict[str, Any] | None:
    """Carry the server-selected adoption bundle, not the whole task checkpoint."""
    if not isinstance(value, dict):
        return None
    task = value.get("task")
    checkpoint = task.get("checkpoint") if isinstance(task, dict) else None
    state = checkpoint.get("state_data") if isinstance(checkpoint, dict) else None
    memory = state.get("memory_context") if isinstance(state, dict) else None
    if not isinstance(memory, dict):
        return None
    bundle = {key: copy.deepcopy(memory[key]) for key in (
        "schema_version", "tenant_key", "instruction", "items", "warnings", "estimated_tokens",
    ) if key in memory}
    projected_task = {key: copy.deepcopy(task[key]) for key in (
        "task_id", "status", "owner", "lease_id", "created_at", "updated_at",
        "heartbeat_expires_at", "stale",
    ) if key in task}
    # The producer owns relevance and bounded content. Preserve item wrappers
    # and metadata exactly; do not rerank or truncate advice here.
    if isinstance(task.get("context"), dict):
        projected_task["context"] = {
            key: task["context"][key] for key in (
                "repository_id", "clone_id", "worktree_id", "branch", "task_id", "session_id",
            ) if isinstance(task["context"].get(key), str)
        }
    projected_task["checkpoint"] = {"state_data": {"memory_context": bundle}}
    if "memory_audit" in state:
        projected_task["checkpoint"]["state_data"]["memory_audit"] = task_memory_audit_projection(
            state["memory_audit"]
        )
    if "phase" in checkpoint:
        projected_task["checkpoint"]["phase"] = checkpoint["phase"]
    projected = {key: copy.deepcopy(value[key]) for key in (
        "success", "status", "status_code", "error", "terminal", "retryable",
        "context_id", "task_id", "request_id", "artifact_id", "evidence_ids",
        "stale", "degraded", "partial", "supported", "unsupported", "outcome_unknown",
        "request_not_sent", "in_progress", "cancelled", "timed_out", "fallback_used",
        "mutation_applied", "operation_not_started",
    ) if key in value}
    projected["task"] = projected_task
    if "task_id" in projected_task:
        projected["task_id"] = projected_task["task_id"]
    return projected


def task_memory_essential_response(value: dict[str, Any]) -> dict[str, Any]:
    """Return the success/error envelope used as the MCP memory fallback."""
    essential = {key: copy.deepcopy(value[key]) for key in (
        "success", "status", "status_code", "error", "terminal", "retryable",
        "context_id", "task_id", "request_id", "stale", "degraded", "partial", "task",
        "supported", "unsupported", "outcome_unknown", "request_not_sent",
        "in_progress", "cancelled", "timed_out", "fallback_used",
        "mutation_applied", "operation_not_started",
    ) if key in value}
    task = essential.get("task")
    if isinstance(task, dict):
        essential["task"] = {key: task[key] for key in ("task_id", "status", "checkpoint") if key in task}
    return essential


def mcp_wire_tokens(payload: dict[str, Any], *, text_payload: Any = None) -> int:
    """Measure the serialized MCP text-plus-structured response envelope."""
    visible = payload if text_payload is None else text_payload
    return json_tokens({
        "content": [{"type": "text", "text": json_dumps(visible)}],
        "structuredContent": payload,
        "isError": False,
    })


def task_memory_wire_tokens(value: dict[str, Any], requested: int) -> int:
    """Measure the smallest successful MCP wire candidate, including budget metadata."""
    original = mcp_wire_tokens(value)
    minimum: int | None = None
    for source in (value, task_memory_essential_response(value)):
        payload = copy.deepcopy(source)
        payload["response_budget"] = {
            "requested_tokens": requested,
            "original_tokens": original,
            "returned_tokens": 0,
            "unit": "estimated_tokens",
        }
        for _ in range(16):
            returned = mcp_wire_tokens(payload, text_payload=payload)
            payload["response_budget"]["returned_tokens"] = returned
            measured = mcp_wire_tokens(payload, text_payload=payload)
            if measured == returned:
                minimum = measured if minimum is None else min(minimum, measured)
                break
        else:
            minimum = measured if minimum is None else min(minimum, measured)
    return minimum if minimum is not None else 0
