"""Preserve exact context in an artifact while making inline delivery explicit."""
from __future__ import annotations

from typing import Any

from .json_utils import dumps
from .response_budget import json_tokens


def persist_compiled_context(artifacts: Any, context: dict[str, Any], *, root: str,
                             coordination_id: str, session_id: str) -> str:
    if context.get("success") is not True or context.get("complete") is not True or not isinstance(context.get("text"), str):
        raise ValueError("only an explicitly complete compiled context can be persisted")
    record = {key: context[key] for key in (
        "task_id", "context_id", "etag", "success", "complete", "partial", "text",
        "repo_revision", "evidence_ids", "provenance", "source_layers", "truncated",
    ) if key in context}
    record.update({"schema_version": 1, "root": root, "coordination_id": coordination_id, "session_id": session_id})
    artifact_id = artifacts.put(dumps(record, ensure_ascii=False), kind="task-context")
    if not isinstance(artifact_id, str) or not artifact_id or artifact_id != artifact_id.strip():
        raise ValueError("compiled context artifact persistence unavailable")
    return artifact_id


def _prefix(text: str, tokens: int) -> str:
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if json_tokens(text[:middle]) <= tokens:
            low = middle
        else:
            high = middle - 1
    return text[:low]


def prepare_context_delivery(value: dict[str, Any], budget: int) -> dict[str, Any]:
    context = value.get("task_context")
    if not isinstance(context, dict):
        return value
    result = dict(value)
    # The compiled text already contains the selected state/repository context.
    # Preserve decision/identity metadata without duplicating both full source trees.
    context = {key: item for key, item in context.items() if key not in {"agent_state", "repository"}}
    decision_fields = (
        "success", "complete", "partial", "degraded", "degraded_reason",
        "status_code", "terminal", "retryable", "error", "warning",
    )
    for section in ("agent_state", "repository"):
        original = value["task_context"].get(section)
        if isinstance(original, dict):
            decisions = {key: original[key] for key in decision_fields if key in original}
            if decisions:
                context[section] = decisions
    state = value["task_context"].get("agent_state")
    if isinstance(state, dict) and isinstance(state.get("context"), dict):
        context.setdefault("agent_state", {})["context"] = state["context"]
    result["task_context"] = context
    valid = type(context.get("success")) is bool and type(context.get("complete")) is bool and isinstance(context.get("text"), str)
    if not valid:
        context.update({"success": False, "complete": False, "partial": True, "text": ""})
        result.update({"success": False, "complete": False, "partial": True,
                       "error": "compiled context requires explicit boolean flags and nested text",
                       "terminal": True, "retryable": False})
        return result
    pointers = [container[key] for container, key in (
        (result, "task_context_artifact_id"), (context, "artifact_id"),
    ) if key in container]
    invalid_pointer = any(
        not isinstance(pointer, str) or not pointer or pointer != pointer.strip()
        or "\0" in pointer for pointer in pointers
    )
    if invalid_pointer or (pointers and any(pointer != pointers[0] for pointer in pointers[1:])):
        result.pop("task_context_artifact_id", None)
        context.pop("artifact_id", None)
        context.update({"success": False, "complete": False, "partial": True})
        result.update({"success": False, "complete": False, "partial": True,
                       "error": "compiled context artifact identity is invalid or inconsistent",
                       "terminal": True, "retryable": False})
        return result
    artifact_id = pointers[0] if pointers else None
    if artifact_id is not None:
        result["task_context_artifact_id"] = artifact_id
    if context["success"] is not True or context["complete"] is not True:
        result.update({"success": False, "complete": False, "partial": True})
        if not result.get("error"):
            result["error"] = "compiled context is incomplete"
    # The MCP wire carries both structured content and its text envelope.
    # Reserve room for exact identities, decisions, citations and accounting.
    text_budget = max(32, int(budget) // 6)
    if json_tokens(context["text"]) > text_budget:
        context["text"] = _prefix(context["text"], text_budget)
        context.update({"success": False, "complete": False, "partial": True, "truncated": True})
        result.update({"success": False, "complete": False, "partial": True,
                       "terminal": True, "retryable": False, "context_truncated": True})
        if artifact_id:
            result["error"] = "compiled context requires artifact retrieval"
            result["next_action"] = "read_task_context_artifact"
        else:
            result["error"] = "compiled context exceeds inline budget; its artifact is unavailable"
            result["next_action"] = "request_smaller_context"
    return result
