"""Regression tests for file-backed plan board MCP projections."""

import asyncio
import json
from types import SimpleNamespace

import pytest

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


@pytest.mark.parametrize("diagnostics_enabled", [False, True])
@pytest.mark.parametrize(("requested", "plan_count"), [(1200, 20), (4096, 50)])
def test_plan_list_budget_rejection_reports_size_before_inner_clipping(
    monkeypatch, tmp_path, requested, plan_count, diagnostics_enabled,
):
    plans = [
        {"id": f"plan_{index}", "title": f"Plan {index}", "description": "Plan details. " * 24}
        for index in range(plan_count)
    ]
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server, "CLIENT", CoordBackend({"success": True, "plans": plans}))
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, "record", lambda _event: None)
    monkeypatch.setattr(mcp_server, "detailed_diagnostics_enabled", lambda _cfg: diagnostics_enabled)
    content, result = asyncio.run(mcp_server.mcp.call_tool("local_ai_coord", {
        "action": "plan_list",
        "root": str(tmp_path),
        "max_response_tokens": requested,
        "response_profile": "minimal",
    }))

    assert result["success"] is False
    assert result["status_code"] == 413
    assert "Reduce limit or narrow query" in result["error"]
    assert "plans" not in result
    budget = result["response_budget"]
    if diagnostics_enabled:
        assert budget["original_tokens"] > requested
    else:
        assert "original_tokens" not in budget
    assert budget["rejected"] is True
    assert budget["truncated"] is True
    wire = {
        "content": [item.model_dump(mode="json", exclude_none=True) for item in content],
        "structuredContent": result,
        "isError": False,
    }
    assert budget["returned_tokens"] == mcp_server.json_tokens(wire) <= requested
