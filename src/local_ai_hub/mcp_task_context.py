from __future__ import annotations

from typing import Any


def _load_task_context(
    *,
    task_id: str,
    root: str,
    context: str,
    phase: str = "",
    focus: list[str] | None = None,
    preload_profile: str = "",
    changed_paths: list[str] | None = None,
    repository_revision: str = "",
    token_budget: int = 0,
) -> tuple[str, dict[str, Any]]:
    """Fetch one unified Agent OS + repository context for a model call."""
    from . import mcp_server as services_module
    if not task_id.strip():
        return context, {}
    payload = {
        "action": "compile",
        "task_id": task_id,
        "token_budget": token_budget or 4000,
        "root": services_module._client_root(root),
        "phase": phase,
        "focus": list(focus or []),
        "preload_profile": preload_profile,
        "changed_paths": list(changed_paths or []),
        "repository_revision": repository_revision,
        "compact": True,
    }
    raw = services_module.CLIENT.post("/api/agent-state/context", payload, timeout=services_module._timeout("context"))
    if not isinstance(raw, dict):
        return "", {
            "success": False,
            "terminal": True,
            "retryable": True,
            "error": "task context response must be a JSON object",
        }
    task_context = raw.get("task_context")
    if type(raw.get("success")) is not bool or (
        raw.get("success") is True and type(raw.get("complete")) is not bool
    ):
        return "", {
            "success": False, "terminal": True, "retryable": False,
            "error": "task context response requires explicit boolean success and completeness",
        }
    if raw["success"] is False or raw["complete"] is False:
        return "", {
            "success": False,
            "terminal": bool(raw.get("terminal", False)),
            "retryable": bool(raw.get("retryable", True)),
            "error": str(raw.get("error") or "task context is incomplete"),
            "task_context": task_context if isinstance(task_context, dict) else {},
        }
    if not isinstance(task_context, dict) or (
        task_context.get("success") is not True or task_context.get("complete") is not True
    ):
        return "", {
            "success": False, "terminal": True, "retryable": False,
            "error": "task context response requires a complete canonical task_context object",
        }
    task_text = task_context.get("text")
    if not isinstance(task_text, str):
        return "", {
            "success": False, "terminal": True, "retryable": False,
            "error": "task_context.text must be a string",
        }
    task_text = task_text.strip()
    if not task_text:
        return "", {
            "success": False,
            "terminal": True,
            "retryable": False,
            "error": "task context is empty",
            "task_context": task_context,
        }
    context_id = str(task_context.get("context_id") or "")[:80]
    context_etag = str(task_context.get("etag") or "")[:80]
    evidence_ids = [str(item)[:120] for item in (task_context.get("evidence_ids") or [])[:64] if str(item)]
    receipt = (
        f"Task context receipt: context_id={context_id or 'unknown'} "
        f"etag={context_etag or 'unknown'} evidence_ids={','.join(evidence_ids) or 'none'}"
    )
    merged = "\n\n".join(part for part in (context.strip(), "Task-scoped context:\n" + task_text, receipt) if part)
    return merged, {
        "success": True,
        "context_id": context_id,
        "etag": context_etag,
        "evidence_ids": evidence_ids,
    }

def _attach_task_context_receipt(result: Any, metadata: dict[str, Any]) -> Any:
    """Expose the exact task-context receipt used by a semantic model call."""
    if not isinstance(result, dict) or not metadata.get("success"):
        return result
    enriched = dict(result)
    enriched["task_context_id"] = str(metadata.get("context_id") or "")[:80]
    enriched["task_context_etag"] = str(metadata.get("etag") or "")[:80]
    enriched["task_context_evidence_ids"] = [
        str(item)[:120] for item in (metadata.get("evidence_ids") or [])[:64] if str(item)
    ]
    return enriched

def _quality_check_semantic_result(
    result: Any,
    *,
    task: str,
    context: str,
    changed_paths: list[str] | None = None,
) -> Any:
    from . import mcp_server as services_module
    if not isinstance(result, dict) or type(result.get("success")) is not bool:
        return {
            "success": False, "terminal": True, "retryable": False,
            "error_code": "invalid_semantic_result",
            "error": "Local semantic backend must return an object with explicit boolean success.",
        }
    if result["success"] is False:
        return result
    # A semantic success is only meaningful when it carries a usable payload.
    # Empty model output used to leak through as success=true and poisoned
    # caches/async handoffs with no evidence for the caller.
    content_keys = ("text", "summary", "artifact_id", "job_id", "result", "results", "task_context", "candidate")
    has_content = any(
        key in result and result.get(key) not in (None, "", [], {})
        for key in content_keys
    )
    if not has_content:
        result = dict(result)
        result.update({
            "success": False,
            "terminal": False,
            "retryable": True,
            "error_code": "empty_semantic_result",
            "error": "Local semantic backend returned success without text, summary, result, or artifact reference.",
        })
        return result
    evidence_paths = [str(path) for path in (changed_paths or []) if str(path).strip()]
    if not evidence_paths:
        evidence_paths = list(dict.fromkeys(services_module._SEMANTIC_PATH_RE.findall(context)))[:64]
    if not evidence_paths:
        if "semantic_quality" not in result and "review_consistency" not in result:
            return result
        quality = services_module.constrain_semantic_quality(
            {"usable": False, "reason": "source_evidence_unavailable"}, result,
        )
    else:
        quality = services_module.constrain_semantic_quality(services_module.assess_semantic_result(task, evidence_paths, result), result)
    result["advisory_only"] = True
    result["semantic_quality"] = quality
    if not quality.get("usable", False):
        reason = quality.get("bypass_reason", quality.get("reason", "quality_gate"))
        result["quality_warning"] = f"advisory semantic output requires verification: {reason}"
        result["bypass_reason"] = reason
    return result
