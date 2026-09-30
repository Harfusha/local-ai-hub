from __future__ import annotations

from local_ai_hub import mcp_server
from local_ai_hub.generator import generate_mcp_tool_schemas
from local_ai_hub.operation_contracts import normalize_transport_error


def test_generated_outputs_stay_general_until_every_action_is_contracted() -> None:
    generated = generate_mcp_tool_schemas({})
    for name, tool in generated.items():
        assert tool["output_schema"] == {"type": "object", "additionalProperties": True}, name


def test_generated_tool_outputs_do_not_publish_partial_action_fields() -> None:
    generated = generate_mcp_tool_schemas({})
    assert all(
        tool["output_schema"].get("properties") is None
        for tool in generated.values()
    )


def test_live_mcp_outputs_match_generated_http_facing_contracts() -> None:
    generated = generate_mcp_tool_schemas(mcp_server.CFG)
    tools = mcp_server.mcp._tool_manager._tools
    for name in mcp_server.FEATURES.enabled_tools:
        assert tools[name].output_schema == generated[name]["output_schema"], name


def test_http_and_mcp_preserve_same_transport_error_contract() -> None:
    response = {
        "success": False,
        "status_code": 503,
        "error": "backend unavailable",
        "terminal": False,
        "retryable": True,
        "degraded": True,
        "stale": True,
        "evidence": [{"id": "E-transport"}],
        "cancelled": True,
    }
    http = normalize_transport_error(503, response)
    mcp = mcp_server._compact(response, "status")
    for field in (
        "success", "status_code", "error", "terminal", "retryable",
        "degraded", "stale", "evidence", "cancelled",
    ):
        assert mcp[field] == http[field], field

