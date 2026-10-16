from __future__ import annotations

import asyncio
import json

from local_ai_hub import mcp_server


class DummyClient:
    def __init__(self, response):
        self.response = response
        self.coord_calls = []

    def coord(self, **kwargs):
        self.coord_calls.append(kwargs)
        return self.response


def test_simulate_merge_preserves_mergeability_and_conflicts_through_mcp(monkeypatch, tmp_path):
    response = {
        "success": True,
        "mergeable": True,
        "conflicts": [],
        "exit_code": 0,
    }
    client = DummyClient(response)
    monkeypatch.setattr(mcp_server, "CLIENT", client)
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **_: None)
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server.FEATURES, "agent_os", True)
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, "record", lambda _event: None)

    wire_result = asyncio.run(mcp_server.mcp.call_tool("local_ai_coord", {
        "action": "simulate_merge",
        "source_branch": "feature/example",
        "target_branch": "master",
        "root": str(tmp_path),
        "response_profile": "compact",
        "max_response_tokens": 1024,
    }))
    blocks = wire_result[0] if isinstance(wire_result, tuple) else wire_result
    projected = json.loads(blocks[0].text)
    assert projected["success"], projected

    assert len(client.coord_calls) == 1
    assert client.coord_calls[0]["source_branch"] == "feature/example"
    assert client.coord_calls[0]["target_branch"] == "master"
    assert projected["mergeable"] is True
    assert projected["conflicts"] == []
    assert projected["exit_code"] == 0
