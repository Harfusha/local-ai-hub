from __future__ import annotations

import asyncio
import json

from local_ai_hub import mcp_server
from local_ai_hub.operation_contracts import OPERATION_CONTRACTS
from local_ai_hub.http_route_registry import select_http_routes


def test_mcp_browser_action_calls_browser_bridge(monkeypatch):
    calls = []
    monkeypatch.setattr(mcp_server.FEATURES, "tasks", True)
    monkeypatch.setattr(mcp_server.FEATURES, "has_any_model", lambda: True)
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, "record", lambda _event: None)
    monkeypatch.setattr(mcp_server.mcp._tool_manager, "_tools", dict(mcp_server.mcp._tool_manager._tools))
    if "local_ai_task" not in mcp_server.mcp._tool_manager._tools:
        mcp_server.mcp.add_tool(mcp_server.local_ai_task, name="local_ai_task")

    class DummyClient:
        def post(self, path, payload, **kwargs):
            calls.append((path, payload))
            return {
                "success": True,
                "title": "Test Page",
                "dom_snapshot": "<html><body>ready</body></html>",
                "screenshot_artifact_id": "art_browser_screen",
            }

    monkeypatch.setattr(mcp_server, "CLIENT", DummyClient())
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **_: None)

    wire_result = asyncio.run(mcp_server.mcp.call_tool("local_ai_task", {
        "action": "browser",
        "url": "http://localhost:3000",
        "max_response_tokens": 1024,
        "response_profile": "compact",
    }))
    blocks = wire_result[0] if isinstance(wire_result, tuple) else wire_result
    projected = json.loads(blocks[0].text)

    assert projected["success"] is True, projected
    assert calls == [("/api/task/browser", {"url": "http://localhost:3000", "viewport": None})]
    assert projected["title"] == "Test Page"
    assert projected["dom_snapshot"] == "<html><body>ready</body></html>"
    assert projected["screenshot_artifact_id"] == "art_browser_screen"


def test_browser_url_is_only_in_task_contract():
    assert "url" in OPERATION_CONTRACTS["local_ai_task"]["properties"]
    assert "url" not in OPERATION_CONTRACTS["local_ai_repo"]["properties"]


def test_browser_capture_has_one_post_route():
    assert select_http_routes("POST", "/api/task/browser") == ("post_task_browser_1",)
    assert select_http_routes("GET", "/api/task/browser") == ()
