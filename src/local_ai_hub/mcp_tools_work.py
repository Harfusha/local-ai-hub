from __future__ import annotations

from typing import Any, Literal, TypeAlias

from .operation_contracts import operation_actions

WorkAction: TypeAlias = Literal.__getitem__(operation_actions("local_ai_work", None))


def local_ai_work(
    action: WorkAction,
    root: str = ".",
    task: str = "",
    work_id: str = "",
    task_id: str = "",
    acceptance_criteria: list[str] | None = None,
    constraints: list[str] | None = None,
    mode: str = "bounded",
    allowed_paths: list[str] | None = None,
    approved_commands: list[str] | None = None,
    permissions: dict[str, Any] | None = None,
    budget: dict[str, Any] | None = None,
    timeout_seconds: float = 90.0,
    answer: str = "",
    response_profile: str = "compact",
    return_fields: list[str] | None = None,
    max_output_tokens: int = 0,
    keep_failed_workspace: bool = False,
    extra_fields: list[str] | None = None,
    max_response_tokens: int = 0,
    reuse_key: str = "",
) -> dict[str, Any]:
    """Whole-task local execution with durable verified handoff. See dynamic description for policy and response projection."""
    from . import mcp_server as services_module
    if not getattr(services_module.FEATURES, "work_orchestrator", False):
        return {"success": False, "unsupported": True, "error": "local_ai_work is disabled in configuration"}
    if action == "submit" and mode != "bounded":
        return {"success": False, "unsupported": True, "error": "local_ai_work submit requires mode='bounded'"}
    if action == "submit" and not getattr(services_module.FEATURES, "bounded_work_tier", False):
        return {"success": False, "unsupported": True, "error": "local_ai_work submit requires the high or max hardware profile"}
    if action == "submit" and not getattr(services_module.FEATURES, "bounded_work_qualified", False):
        return {
            "success": False, "unsupported": True, "error_code": "capability_feature_disabled",
            "required_feature": "bounded_local_work",
            "error": "local_ai_work submit requires features.bounded_local_work=true after task-specific evaluation",
        }
    valid_actions = tuple(services_module.WorkAction.__args__)
    if not isinstance(action, str) or action not in valid_actions:
        action_label = action if isinstance(action, str) else f"<{type(action).__name__}>"
        return services_module._invalid_action("local_ai_work", action_label, valid_actions, "Use submit for a closed task and one bounded wait/get for handoff.")
    raw_work_call = services_module._CURRENT_MCP_CALL_ARGUMENTS.get()
    budget_supplied = bool(raw_work_call and raw_work_call[0] == "local_ai_work" and "budget" in raw_work_call[1])
    permissions_supplied = bool(raw_work_call and raw_work_call[0] == "local_ai_work" and "permissions" in raw_work_call[1])
    payload: dict[str, Any] = {
        "action": action, "root": services_module._client_root(root), "task": task, "work_id": work_id, "task_id": task_id,
        "acceptance_criteria": acceptance_criteria or [], "constraints": constraints or [], "mode": mode,
        "permissions": permissions if permissions is not None or permissions_supplied else {}, "budget": budget if budget is not None or budget_supplied else {}, "timeout_seconds": timeout_seconds, "answer": answer,
        "response_profile": response_profile, "return_fields": return_fields or [], "max_output_tokens": max_output_tokens,
        "keep_failed_workspace": keep_failed_workspace,
    }
    if allowed_paths is not None:
        payload["allowed_paths"] = allowed_paths
    if approved_commands is not None:
        payload["approved_commands"] = approved_commands
    return services_module._compact(services_module.CLIENT.post("/api/work-orders", payload, timeout=services_module._timeout("long") if action in {"wait"} else services_module._timeout("quick")), "status")
