from __future__ import annotations

import asyncio
from types import SimpleNamespace

from local_ai_hub import mcp_server
from local_ai_hub.generator import generate_mcp_tool_schemas
from local_ai_hub.operation_contracts import (
    normalize_transport_error,
    operation_output_schema,
    operation_tool_output_schema,
    validate_schema_object,
)


def test_enabled_mcp_action_aliases_are_advertised() -> None:
    for tool_kind, aliases in mcp_server._ACTION_ALIASES.items():
        tool_name = f"local_ai_{tool_kind}"
        if tool_name not in mcp_server.FEATURES.enabled_tools:
            continue
        schema = mcp_server._mcp_contract_schema(tool_name)
        assert schema is not None
        enum = schema["properties"]["action"]["enum"]
        canonical_actions = set(mcp_server._ADOPTION_ACTIONS.get(tool_name, ())) & set(enum)
        for alias, canonical in aliases.items():
            if canonical in canonical_actions:
                assert alias in enum, (tool_name, alias)


def test_action_alias_output_metadata_uses_canonical_action() -> None:
    aliases = {
        "local_ai_task": (
            ("gen", "delegate"), ("rev", "review"), ("del", "delegate"),
        ),
        "local_ai_repo": (
            ("idx", "code_index"), ("review", "review_diff"),
            ("sec", "security_audit"), ("ctx", "context"),
        ),
        "local_ai_command": (
            ("patch", "patch_and_verify"), ("fix", "auto_fix"),
            ("repair", "repair_loop"), ("fmt", "format"),
        ),
        "local_ai_coord": (
            ("ctx", "context_compile"), ("compile_ctx", "context_compile"),
            ("neg_rec", "negative_knowledge_record"),
            ("neg_find", "negative_knowledge_find"),
            ("mem_put", "memory_record"), ("mem_rec", "memory_record"),
            ("mem_get", "memory_get"), ("mem_find", "memory_find"),
            ("mem_search", "memory_find"), ("task_new", "task_create"),
            ("task_chk", "task_checkpoint"), ("task_done", "task_complete"),
        ),
    }
    for tool_name, mappings in aliases.items():
        for alias_name, canonical_name in mappings:
            alias = operation_output_schema(tool_name, alias_name)
            canonical = operation_output_schema(tool_name, canonical_name)
            assert alias["x-operation-action"] == alias_name
            assert alias["properties"] == canonical["properties"]


def test_generated_outputs_publish_shared_typed_envelope() -> None:
    generated = generate_mcp_tool_schemas({})
    for name, tool in generated.items():
        schema = tool["output_schema"]
        assert schema["type"] == "object", name
        assert schema["additionalProperties"] is True, name
        assert "anyOf" not in schema, name
        properties = schema["properties"]
        for field, expected_type in {
            "success": "boolean", "status": "string", "status_code": "integer",
            "terminal": "boolean", "retryable": "boolean", "error": "string",
            "message": "string", "degraded": "boolean",
            "stale": "boolean", "fallback_used": "boolean",
            "requires_override": "boolean", "requires_approval": "boolean",
            "decision_recorded": "boolean", "decision_persisted": "boolean",
            "task_status": "string", "waiting": "boolean", "context_id": "string",
            "evidence_ids": "array", "response_budget": "object",
        }.items():
            assert properties[field]["type"] == expected_type, (name, field)
        assert properties["warning"]["anyOf"] == [
            {"type": "string"}, {"type": "null"}
        ], name


def test_live_mcp_outputs_match_generated_http_facing_contracts() -> None:
    generated = generate_mcp_tool_schemas(mcp_server.CFG)
    tools = mcp_server.mcp._tool_manager._tools
    for name in mcp_server.FEATURES.enabled_tools:
        assert tools[name].output_schema == generated[name]["output_schema"], name


def test_disabled_tool_error_conforms_to_registered_output_schema(monkeypatch) -> None:
    async def unexpected_call(*args, **kwargs):
        raise AssertionError("disabled MCP tool reached handler")

    monkeypatch.setattr(mcp_server, "FEATURES", SimpleNamespace(enabled_tools=set()))
    monkeypatch.setattr(mcp_server.mcp._tool_manager, "call_tool", unexpected_call)
    _, payload = asyncio.run(
        mcp_server._compact_mcp_call_tool("local_ai_repo", {"action": "search"})
    )

    assert payload["success"] is False
    assert payload["status_code"] == 403
    assert payload["unsupported"] is True
    assert validate_schema_object(
        payload, mcp_server.mcp._tool_manager._tools["local_ai_repo"].output_schema
    ) is None


def test_http_and_mcp_preserve_same_transport_error_contract() -> None:
    response = {
        "success": False,
        "status_code": 503,
        "error": "backend unavailable",
        "status": "unavailable",
        "warning": "cached result returned",
        "message": "retry later",
        "terminal": False,
        "retryable": True,
        "degraded": True,
        "stale": True,
        "fallback_used": True,
        "requires_override": False,
        "requires_approval": False,
        "decision_recorded": True,
        "decision_persisted": True,
        "task_status": "waiting",
        "waiting": True,
        "context_id": "ctx-1",
        "response_budget": {"requested_tokens": 512, "returned_tokens": 400},
        "evidence_ids": ["E-transport"],
        "evidence": [{"id": "E-transport"}],
        "cancelled": True,
    }
    http = normalize_transport_error(503, response)
    mcp = mcp_server._compact(response, "status")
    for field in (
        "success", "status_code", "error", "terminal", "retryable",
        "status", "warning", "message", "degraded", "stale", "fallback_used",
        "requires_override", "requires_approval", "decision_recorded", "decision_persisted",
        "task_status", "waiting", "context_id", "response_budget", "evidence_ids",
        "evidence", "cancelled",
    ):
        assert mcp[field] == http[field], field
    assert validate_schema_object(mcp, operation_tool_output_schema("local_ai_status", ["brief"])) is None

