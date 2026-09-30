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
    assert any(
        constraint.get("if", {}).get("properties", {}).get("action", {}).get("const") == "pipeline"
        and "steps" in constraint.get("then", {}).get("properties", {})
        for constraint in schema.get("allOf", [])
    )
