from __future__ import annotations

import asyncio
import json
from pathlib import Path
import pytest

from local_ai_hub import mcp_server as local_ai_mcp
import mcp.types as t


def test_python_direct_invocation_returns_dict() -> None:
    res = local_ai_mcp.local_ai_status()
    assert isinstance(res, dict)
    assert "success" in res


def test_mcp_call_tool_returns_compact_minified_json(monkeypatch) -> None:
    monkeypatch.setattr(local_ai_mcp, "CLIENT", local_ai_mcp.HubClient(tenant="test", auto_start=False))
    monkeypatch.setattr(local_ai_mcp.CLIENT, "get", lambda path, timeout=None: {"hub_online": True, "scheduler": {}, "observability": {}})

    # Call via FastMCP call_tool (the MCP protocol entrypoint)
    result = asyncio.run(local_ai_mcp.mcp.call_tool("local_ai_status", {"detail": "brief"}))

    if isinstance(result, tuple):
        content = result[0][0]
    else:
        assert isinstance(result, list)
        assert len(result) >= 1
        content = result[0]
    assert isinstance(content, t.TextContent)
    assert content.type == "text"

    # Text must be compact (no newline formatting, no spacing around separators)
    assert "\n" not in content.text
    assert ": " not in content.text
    assert ", " not in content.text

    parsed = json.loads(content.text)
    assert isinstance(parsed, dict)
    assert parsed["success"] is True


def test_lowlevel_request_handler_returns_compact_minified_json(monkeypatch) -> None:
    monkeypatch.setattr(local_ai_mcp, "CLIENT", local_ai_mcp.HubClient(tenant="test", auto_start=False))
    monkeypatch.setattr(local_ai_mcp.CLIENT, "get", lambda path, timeout=None: {"hub_online": True, "scheduler": {}, "observability": {}})

    req = t.CallToolRequest(method="tools/call", params=t.CallToolRequestParams(name="local_ai_status", arguments={"detail": "brief"}))
    server_res = asyncio.run(local_ai_mcp.mcp._mcp_server.request_handlers[t.CallToolRequest](req))

    assert hasattr(server_res, "root")
    tool_res = server_res.root
    assert isinstance(tool_res, t.CallToolResult)
    assert len(tool_res.content) >= 1
    content = tool_res.content[0]
    assert isinstance(content, t.TextContent)

    assert "\n" not in content.text
    assert ": " not in content.text
    assert ", " not in content.text

    parsed = json.loads(content.text)
    assert parsed["success"] is True
