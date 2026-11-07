"""Strict dispatch validation for the disposable case 098 MCP client."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


COORD_ACTIONS = {
    "task_create", "task_get", "task_list", "task_checkpoint",
    "verify_completion", "task_complete", "context_compile",
}
ARTIFACT_ACTIONS = {"get", "slice"}


def validate_invocation(raw: Any, workspace: Path) -> tuple[str, dict[str, Any]]:
    if not isinstance(raw, dict):
        raise ValueError("JSON object required")
    tool = raw.get("tool", "local_ai_coord")
    action = raw.get("action")
    allowed = COORD_ACTIONS if tool == "local_ai_coord" else ARTIFACT_ACTIONS if tool == "local_ai_artifact" else set()
    if not isinstance(action, str) or action not in allowed:
        raise ValueError("fixture tool/action is not allowed")
    supplied_root = raw.get("root")
    if not isinstance(supplied_root, str) or not Path(supplied_root).is_absolute():
        raise ValueError("explicit absolute fixture workspace root required")
    root_path = Path(supplied_root)
    try:
        resolved_root = root_path.resolve(strict=True)
        resolved_workspace = Path(workspace).resolve(strict=True)
    except OSError as exc:
        raise ValueError("fixture workspace root must exist") from exc
    if root_path.is_symlink() or not resolved_workspace.is_dir() or resolved_root != resolved_workspace:
        raise ValueError("fixture workspace root mismatch")
    if tool == "local_ai_coord" and action == "context_compile":
        task_id = raw.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("context_compile requires task_id")
    if tool == "local_ai_artifact":
        artifact_id = raw.get("artifact_id")
        if not isinstance(artifact_id, str) or not artifact_id:
            raise ValueError("artifact action requires artifact_id")
    arguments = {key: value for key, value in raw.items() if key != "tool"}
    return tool, arguments


def serialize_result(result: Any) -> str:
    """Emit bounded tool data directly and preserve terminal null metadata."""
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return json.dumps(structured, ensure_ascii=False, separators=(",", ":"))
    return result.model_dump_json(exclude_none=False)
