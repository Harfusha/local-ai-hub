from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from local_ai_hub import mcp_server


INCIDENT = {
    "incident_id": "inc-1",
    "error_class": "TimeoutError",
    "message": "Command timed out",
}


class DummyClient:
    def __init__(self, response):
        self.response = response
        self.posts = []

    def post(self, path, payload, timeout=None):
        self.posts.append((path, payload, timeout))
        return self.response


@pytest.mark.parametrize(
    ("matches", "incidents"),
    [([INCIDENT], []), ([], [INCIDENT])],
)
def test_negative_knowledge_find_preserves_incidents_through_public_dispatch(
    monkeypatch, tmp_path, matches, incidents,
):
    client = DummyClient({
        "success": True,
        "degraded": True,
        "error": "Partial incident index unavailable",
        "terminal": False,
        "retryable": True,
        "matches": matches,
        "incidents": incidents,
        "count": 1,
    })
    monkeypatch.setattr(mcp_server, "CLIENT", client)
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **_: None)

    wire_result = asyncio.run(mcp_server.mcp.call_tool("local_ai_coord", {
        "action": "negative_knowledge_find",
        "root": str(tmp_path),
        "query": "Command timed out",
        "response_profile": "compact",
        "max_response_tokens": 512,
    }))
    contents = wire_result[0] if isinstance(wire_result, tuple) else wire_result
    projected = json.loads(next(item.text for item in contents if item.type == "text"))

    checkout = Path(__file__).resolve().parents[2]
    assert Path(mcp_server.__file__).resolve().is_relative_to(checkout / "src")
    assert len(client.posts) == 1
    assert client.posts[0][0] == "/api/agent-state/incidents"
    assert client.posts[0][1]["action"] == "find"
    assert client.posts[0][1]["root"] == str(tmp_path)
    assert client.posts[0][1]["query"] == "Command timed out"
    assert projected["matches"] == matches
    assert projected["incidents"] == incidents
    assert projected["count"] == 1
    assert projected["success"] is True
    assert projected["degraded"] is True
    assert projected["error"] == "Partial incident index unavailable"
    assert projected["terminal"] is False
    assert projected["retryable"] is True
    assert mcp_server.json_tokens(projected) <= 512


# Retain the prior direct-projection regressions alongside public-wire coverage.
from local_ai_hub.mcp_server import _compact

def test_negative_knowledge_find_preserves_incidents():
    raw_response = {
        "success": True,
        "matches": [
            {"incident_id": "inc-1", "error_class": "TimeoutError", "message": "Command timed out"}
        ],
        "count": 1
    }
    projected = _compact(raw_response, "task_memory")
    assert "matches" in projected or "incidents" in projected
    assert len(projected.get("matches", [])) == 1

def test_negative_knowledge_find_preserves_empty_matches():
    raw_response = {
        "success": True,
        "matches": [],
        "incidents": [],
        "negative_knowledge": [],
        "count": 0
    }
    projected = _compact(raw_response, "task_memory")
    assert "matches" in projected
    assert projected["matches"] == []
    assert "incidents" in projected
    assert projected["incidents"] == []


@pytest.mark.parametrize("scoped", [[], [INCIDENT]])
def test_negative_knowledge_find_preserves_actual_http_response_shape(
    monkeypatch, tmp_path, scoped,
):
    root = str(tmp_path)
    query = "Command timed out"
    client = DummyClient({
        "success": True,
        "negative_knowledge": scoped,
        "incidents": scoped,
        "provenance": {"root": root, "query": query},
        "degraded": True,
        "error": "Partial incident index unavailable",
        "terminal": False,
        "retryable": True,
    })
    monkeypatch.setattr(mcp_server, "CLIENT", client)
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **_: None)

    wire_result = asyncio.run(mcp_server.mcp.call_tool("local_ai_coord", {
        "action": "negative_knowledge_find",
        "query": query,
        "root": root,
        "response_profile": "compact",
        "max_response_tokens": 512,
    }))
    contents = wire_result[0] if isinstance(wire_result, tuple) else wire_result
    projected = json.loads(next(item.text for item in contents if item.type == "text"))

    checkout = Path(__file__).resolve().parents[2]
    assert Path(mcp_server.__file__).resolve().is_relative_to(checkout / "src")
    assert len(client.posts) == 1
    assert client.posts[0][0] == "/api/agent-state/incidents"
    assert client.posts[0][1]["action"] == "find"
    assert client.posts[0][1]["query"] == query
    assert client.posts[0][1]["root"] == root
    assert projected["negative_knowledge"] == scoped
    assert projected["incidents"] == scoped
    assert projected["provenance"] == {"root": root, "query": query}
    assert projected["success"] is True
    assert projected["degraded"] is True
    assert projected["error"] == "Partial incident index unavailable"
    assert projected["terminal"] is False
    assert projected["retryable"] is True
    assert mcp_server.json_tokens(projected) <= 512
