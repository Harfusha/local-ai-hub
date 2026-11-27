from __future__ import annotations

import asyncio

from local_ai_hub import mcp_server
import mcp.types as t


def test_tools_list_wire_exposes_action_scoped_repo_steps() -> None:
    request = t.ListToolsRequest(method="tools/list")
    result = asyncio.run(
        mcp_server.mcp._mcp_server.request_handlers[t.ListToolsRequest](request)
    )

    tool = next(item for item in result.root.tools if item.name == "local_ai_repo")
    schema = tool.inputSchema
    pipeline_rule = next(
        constraint for constraint in schema.get("then", {}).get("allOf", [])
        if constraint.get("if", {}).get("properties", {}).get("action", {}).get("const") == "pipeline"
    )
    assert "steps" in pipeline_rule.get("then", {}).get("required", [])
    steps = schema["properties"]["steps"]
    assert steps["minItems"] == 1
    assert "Valid only for actions: pipeline." in steps["description"]
    assert "pipeline" not in steps["items"]["properties"]["action"]["enum"]
    from local_ai_hub.operation_contracts import validate_operation_arguments

    assert "steps" in (validate_operation_arguments("local_ai_repo", "pipeline", {
        "action": "pipeline", "root": "C:/repo",
    }) or "")
    assert validate_operation_arguments("local_ai_repo", "search", {
        "action": "search", "root": "C:/repo", "query": "x", "steps": [],
    }) == "steps is not valid for action='search'"
