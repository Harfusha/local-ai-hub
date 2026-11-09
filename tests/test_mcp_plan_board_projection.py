"""Regression tests for file-backed plan board MCP projections."""

import asyncio
import json
from types import SimpleNamespace

from local_ai_hub import mcp_server


class CoordBackend:
    def __init__(self, response):
        self.response = response

    def coord(self, **_payload):
        return self.response


def test_plan_board_view_keeps_all_cards_below_response_budget(monkeypatch, tmp_path):
    cards = [{"task_id": f"task_{index}", "title": f"Task {index}"} for index in range(60)]
    columns = {
        "planned": cards,
        "ready": [],
        "in_progress": [],
        "blocked": [],
        "source_ready": [],
        "done": [],
    }
    backend = CoordBackend({
        "success": True,
        "project_root": str(tmp_path),
        "git_branch": "master",
        "git_head": "abc123",
        "plan_filter": "plan_x",
        "columns": columns,
        "counts": {name: len(items) for name, items in columns.items()},
        "total_items": len(cards),
    })
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server, "CLIENT", backend)
    monkeypatch.setattr(
        mcp_server,
        "load_operational_mode",
        lambda *_args, **_kwargs: SimpleNamespace(mode="active", revision=1, degraded=False),
    )
    original_compact_result = mcp_server.compact_result
    compact_item_limits = []

    def capture_compact_limit(value, **kwargs):
        compact_item_limits.append(kwargs.get("max_items"))
        return original_compact_result(value, **kwargs)

    monkeypatch.setattr(mcp_server, "compact_result", capture_compact_limit)

    raw = asyncio.run(mcp_server.mcp.call_tool("local_ai_coord", {
        "action": "plan_board_view",
        "root": str(tmp_path),
        "plan_id": "plan_x",
        "max_response_tokens": 8192,
        "response_profile": "compact",
    }))
    content = raw[0][0] if isinstance(raw, tuple) else raw[0]
    result = json.loads(content.text)

    assert 60 in compact_item_limits, compact_item_limits
    assert result["success"] is True, result
    assert result["total_items"] == 60
    assert len(result["columns"]["planned"]) == 60
