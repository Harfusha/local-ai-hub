"""Shared public operation contracts for MCP exposure and validation."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class OperationContract:
    """Stable tool-level gate and transport metadata."""

    name: str
    feature_gate: str
    effects: str
    retry: str
    timeout: str
    projection: str


# The eight public tools remain the single registered MCP surface. Detailed
# actions stay owned by FeatureSet; this table holds cross-transport contracts.
MCP_OPERATION_CONTRACTS = (
    OperationContract("local_ai_status", "status", "read-only", "safe", "quick", "status"),
    OperationContract("local_ai_repo", "repo", "action-dependent", "action-dependent", "action-dependent", "action-dependent"),
    OperationContract("local_ai_task", "tasks", "action-dependent", "action-dependent", "action-dependent", "action-dependent"),
    OperationContract("local_ai_rag", "rag", "action-dependent", "action-dependent", "action-dependent", "action-dependent"),
    OperationContract("local_ai_command", "commands", "action-dependent", "action-dependent", "action-dependent", "action-dependent"),
    OperationContract("local_ai_coord", "coord", "action-dependent", "action-dependent", "action-dependent", "action-dependent"),
    OperationContract("local_ai_artifact", "artifacts", "read-only", "safe", "quick", "artifact"),
    OperationContract("local_ai_work", "work_orchestrator", "action-dependent", "action-dependent", "action-dependent", "action-dependent"),
)

STATUS_ACTIONS = ("", "brief", "cache", "telemetry", "full", "agent_state", "status", "health", "check", "info")
STATUS_DETAILS = ("brief", "cache", "telemetry", "full", "agent_state")
STATUS_ALIASES = ("status", "health", "check", "info")
REPO_PHASES = ("", "plan", "edit", "review", "test", "handoff")
MAX_REPO_PIPELINE_PARALLEL_STEPS = 4
MAX_EVENT_SEQUENCE = (1 << 63) - 1
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
            if name not in {"action", "steps"}
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


def validate_schema_value(value: Any, schema: Mapping[str, Any], path: str) -> str | None:
    """Small bounded JSON-schema subset for the MCP tool's declared inputs."""
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
