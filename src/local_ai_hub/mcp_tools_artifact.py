from __future__ import annotations

from typing import Any, Literal, TypeAlias

from .operation_contracts import operation_actions

ArtifactAction: TypeAlias = Literal[*operation_actions("local_ai_artifact")]


def local_ai_artifact(action: ArtifactAction = "get", artifact_id: str = "", offset: int = 0, max_chars: int = 4000, section: str = "", extra_fields: list[str] | None = None, max_response_tokens: int = 0, response_profile: str = "", reuse_key: str = "", binary: bool = False, slices: list[dict[str, int]] | None = None, path: str = "", line_start: int = 1, line_end: int = 0, start_line: int = 1, end_line: int = 0, id: str = "", file: str = "", root: str = "", workspace: str = "", expected_file_sha256: str = "") -> dict[str, Any]:
    from . import mcp_server as services_module
    """Fetch an artifact operation defined by the shared contract. Evidence IDs start with E."""
    if not services_module.operation_enabled(services_module.FEATURES, "local_ai_artifact"):
        return {"success": False, "unsupported": True, "error": "local_ai_artifact is disabled in configuration"}
    if id and not artifact_id:
        artifact_id = id
    if file and not path:
        path = file
    is_source_slices = bool(slices and isinstance(slices, list) and len(slices) > 0 and isinstance(slices[0], dict) and ("path" in slices[0] or "file" in slices[0]))
    if action in {"get", "slice"} and (path or is_source_slices) and not artifact_id:
        action = "source"
    target_workspace = root or workspace or services_module._workspace
    if action == "source":
        from .source_slice import read_source_slice
        eff_start = start_line if start_line > 1 else line_start
        eff_end = end_line if end_line > 0 else line_end
        if is_source_slices:
            if offset or expected_file_sha256:
                return {"success": False, "error": "source pagination requires a single path", "terminal": True, "retryable": False}
            results = []
            for item in slices[:16]:
                if not isinstance(item, dict):
                    continue
                s_path = str(item.get("path") or item.get("file") or "")
                s_start = int(item.get("start_line") or item.get("line_start") or 1)
                s_end = int(item.get("end_line") or item.get("line_end") or 0)
                s_chars = int(item.get("max_chars", 4000))
                results.append(read_source_slice(target_workspace, path=s_path, line_start=s_start, line_end=s_end, max_chars=s_chars))
            return services_module._compact({"success": True, "slices": results, "count": len(results)}, "artifact")
        eff_chars = max(512, min(max_chars, 12000)) if max_chars else 4000
        arguments = {"path": path, "line_start": eff_start, "line_end": eff_end, "max_chars": eff_chars,
                     "offset": offset, "expected_file_sha256": expected_file_sha256}
        error = services_module.validate_operation_arguments("local_ai_artifact", "source", arguments)
        if error is not None:
            return {"success": False, "error": error, "terminal": True, "retryable": False}
        return services_module._compact(read_source_slice(target_workspace, **arguments), "artifact")
    if slices is not None:
        if action not in {"get", "slice"}:
            return {"success": False, "error": "slices are only valid for get or slice actions"}
        if not isinstance(slices, list) or not slices or len(slices) > 16:
            return {"success": False, "error": "slices must contain 1 to 16 ranges"}
        aggregate_max_chars = min(services_module.MAX_TEXT, 50_000)
        total_requested = 0
        for item in slices:
            if not isinstance(item, dict) or set(item) != {"offset", "max_chars"}:
                return {"success": False, "error": "each slice must contain only offset and max_chars"}
            item_offset, item_max_chars = item["offset"], item["max_chars"]
            if isinstance(item_offset, bool) or not isinstance(item_offset, int) or item_offset < 0:
                return {"success": False, "error": "slice offset must be a non-negative integer"}
            if isinstance(item_max_chars, bool) or not isinstance(item_max_chars, int) or not 1 <= item_max_chars <= 50_000:
                return {"success": False, "error": "slice max_chars must be between 1 and 50000"}
            total_requested += item_max_chars
            if total_requested > aggregate_max_chars:
                return {"success": False, "error": f"combined slice max_chars cannot exceed {aggregate_max_chars}"}
    validation_arguments: dict[str, Any] = {}
    if action in {"get", "slice"}:
        validation_arguments.update({
            "artifact_id": artifact_id,
            "offset": offset,
            "max_chars": max_chars,
            "section": section,
            "binary": binary,
        })
        if slices is not None:
            validation_arguments["slices"] = slices
    if extra_fields is not None:
        validation_arguments["extra_fields"] = extra_fields
    validation_error = services_module.validate_operation_arguments("local_ai_artifact", action, validation_arguments)
    if validation_error is not None:
        return {"success": False, "error": validation_error}
    if action in {"get", "slice"}:
        if not isinstance(binary, bool):
            return {"success": False, "error": "binary must be a boolean"}
        if slices is None and not binary and max_chars > min(services_module.MAX_TEXT, 50_000):
            return {"success": False, "error": f"max_chars cannot exceed the MCP text limit of {min(services_module.MAX_TEXT, 50_000)}"}
    if slices is not None:
        if section or binary or offset != 0 or max_chars != 4000:
            return {"success": False, "error": "multi-slice retrieval cannot be combined with section, binary, offset, or max_chars"}
    if action == "list":
        return services_module._compact(services_module.CLIENT.post("/api/artifact/list", {"limit": 20}), "artifact")
    if artifact_id.startswith("E"):
        if slices is not None:
            return {"success": False, "error": "multi-slice retrieval does not support evidence IDs"}
        return services_module._compact(services_module.CLIENT.post("/api/evidence/get", {"evidence_id": artifact_id, "verify": True}), "artifact")
    if slices is not None:
        return services_module._compact(services_module.CLIENT.post("/api/artifact/get", {
            "artifact_id": artifact_id,
            "slices": slices,
            "binary": False,
        }), "artifact")
    result = services_module.CLIENT.post("/api/artifact/get", {
        "artifact_id": artifact_id,
        "offset": offset,
        "max_chars": max_chars,
        "section": section,
        "binary": binary,
    })
    if binary and isinstance(result, dict) and result.get("success"):
        result = {key: value for key, value in result.items() if key != "data_base64"}
        result["binary_payload"] = "available through /api/artifact/get with binary=true"
    return services_module._compact(result, "artifact")
