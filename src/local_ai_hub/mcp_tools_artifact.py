from __future__ import annotations

from typing import Any, Literal, TypeAlias

from .operation_contracts import operation_actions

ArtifactAction: TypeAlias = Literal[*operation_actions("local_ai_artifact")]


def local_ai_artifact(action: ArtifactAction = "get", artifact_id: str = "", offset: int = 0, max_chars: int = 4000, section: str = "", extra_fields: list[str] | None = None, max_response_tokens: int = 0, response_profile: str = "", reuse_key: str = "", binary: bool = False, slices: list[dict[str, int]] | None = None, path: str = "", line_start: int = 1, line_end: int = 0, root: str = "", expected_file_sha256: str = "") -> dict[str, Any]:
    """MCP public tool entrypoint. Fetch an artifact operation defined by the shared contract. Evidence IDs start with E."""
    from . import mcp_server as services_module
    if not services_module.operation_enabled(services_module.FEATURES, "local_ai_artifact"):
        return {"success": False, "unsupported": True, "error": "local_ai_artifact is disabled in configuration"}
    if action == "source":
        if not services_module.is_rooted_path(root):
            return {"success": False, "error": "source requires an explicit absolute root", "terminal": True, "retryable": False}
        target_workspace = services_module._client_root(root)
        from .source_slice import read_source_slice
        arguments = {"path": path, "line_start": line_start, "line_end": line_end, "max_chars": max_chars,
                     "offset": offset, "expected_file_sha256": expected_file_sha256, "root": root}
        if slices is not None:
            arguments["slices"] = slices
        error = services_module.validate_operation_arguments("local_ai_artifact", "source", arguments)
        if error is not None:
            return {"success": False, "error": error, "terminal": True, "retryable": False}
        arguments.pop("root")
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
    if path != "":
        validation_arguments["path"] = path
    if root != "":
        validation_arguments["root"] = root
    if line_start != 1:
        validation_arguments["line_start"] = line_start
    if line_end != 0:
        validation_arguments["line_end"] = line_end
    if expected_file_sha256 != "":
        validation_arguments["expected_file_sha256"] = expected_file_sha256
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
