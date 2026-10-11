from __future__ import annotations

import asyncio
import json

import pytest

from local_ai_hub import mcp_server
from local_ai_hub.operation_contracts import validate_operation_output


@pytest.mark.parametrize("degraded", [False, True])
@pytest.mark.parametrize("selector", [{"detail": "full"}, {"action": "full"}])
def test_full_status_keeps_required_identity_through_live_mcp_projection(monkeypatch, degraded, selector):
    payload = {
        "success": not degraded,
        "degraded": degraded,
        "hub_online": True,
        "version": "4.0.0",
        "ollama_online": True,
        "runtime_stats": {"repo_cache": {"entries": 3}},
    }

    def get(path, **kwargs):
        if path == "/api/capabilities":
            return {
                "success": True,
                "tools": [
                    {"name": f"tool-{index}", "description": "capability detail " * 500}
                    for index in range(32)
                ],
            }
        assert path.startswith(("/api/status", "/api/live/status"))
        return dict(payload)

    monkeypatch.setattr(mcp_server.CLIENT, "get", get)
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, "record", lambda event: None)
    monkeypatch.setattr(mcp_server.FEATURES, "status", True)
    contents, structured = asyncio.run(mcp_server.mcp.call_tool(
        "local_ai_status",
        {**selector, "response_profile": "compact", "max_response_tokens": 3200},
    ))
    actual = json.loads(contents[0].text)
    assert actual["hub_online"] is True
    assert actual["version"] == "4.0.0"
    assert actual["success"] is (not degraded)
    assert actual["degraded"] is degraded
    assert validate_operation_output("local_ai_status", "full", actual) is None
    assert structured["hub_online"] is True
