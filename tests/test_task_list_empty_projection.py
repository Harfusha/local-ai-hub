import asyncio
import json

import pytest

from local_ai_hub import mcp_server


@pytest.mark.parametrize("limit", [128, 256, 3200])
def test_empty_task_list_is_explicit_in_mcp_response(monkeypatch, limit):
    monkeypatch.setattr(mcp_server.CLIENT, "coord", lambda **kwargs: {"success": True, "tasks": []})
    content, result = asyncio.run(mcp_server.mcp.call_tool(
        "local_ai_coord", {"action": "task_list", "root": "C:/fixture", "max_response_tokens": limit},
    ))
    assert result["success"] is True
    assert result["tasks"] == []
    assert json.loads(content[0].text)["tasks"] == []


def test_missing_backend_tasks_are_not_manufactured(monkeypatch):
    monkeypatch.setattr(mcp_server.CLIENT, "coord", lambda **kwargs: {"success": True})
    result = mcp_server.local_ai_coord(action="task_list", root="C:/fixture")
    assert "tasks" not in result
