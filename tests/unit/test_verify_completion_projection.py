from __future__ import annotations

import asyncio
import json

import pytest

from local_ai_hub import mcp_server


class DummyClient:
    def __init__(self, response):
        self.response = response
        self.posts = []

    def post(self, path, payload, timeout=None):
        self.posts.append((path, payload, timeout))
        return self.response


@pytest.mark.parametrize("missing,unverified,receipts", [
    ([], [], []),
    (["runtime"], ["clean install"], [{"receipt_id": "r_current", "criterion": "syntax"}]),
])
def test_verify_completion_preserves_criteria_and_receipts_through_mcp(
    monkeypatch, missing, unverified, receipts
):
    response = {
        "success": True,
        "task_id": "task-1",
        "complete": False,
        "missing_criteria": missing,
        "unverified_criteria": unverified,
        "receipts": receipts,
    }
    client = DummyClient(response)
    monkeypatch.setattr(mcp_server, "CLIENT", client)
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **_: None)

    wire_result = asyncio.run(mcp_server.mcp.call_tool("local_ai_coord", {
        "action": "verify_completion",
        "task_id": "task-1",
        "root": ".",
        "response_profile": "compact",
        "max_response_tokens": 512,
    }))
    contents = wire_result[0] if isinstance(wire_result, tuple) else wire_result
    projected = json.loads(next(item.text for item in contents if item.type == "text"))

    assert len(client.posts) == 1
    assert client.posts[0][0] == "/api/agent-state/verification"
    assert client.posts[0][1]["action"] == "completion"
    assert projected["missing_criteria"] == missing
    assert projected["unverified_criteria"] == unverified
    assert projected["receipts"] == receipts
