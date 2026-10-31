from __future__ import annotations

import time
from pathlib import Path
import pytest

from local_ai_hub.endpoint_stats import EndpointStatsStore, get_registered_surface_catalog


def test_endpoint_and_mcp_stats_integration(tmp_path: Path):
    state_dir = tmp_path / "state"
    store = EndpointStatsStore(state_dir)

    # Simulate HTTP endpoints recording
    endpoints = ["/api/search", "/api/models", "/api/chat", "/health"]
    for i, ep in enumerate(endpoints):
        for call_idx in range(i + 1):
            succ = (call_idx % 2 == 0) or ep == "/health"
            dur = 15.0 * (call_idx + 1)
            store.record_call(item_type="endpoint", item_name=ep, duration_ms=dur, success=succ, root="demo-proj")

    # Simulate MCP tool recording
    mcp_tools = ["local_ai_status", "local_ai_repo:context", "local_ai_coord:task_create"]
    for tool in mcp_tools:
        store.record_call(item_type="mcp", item_name=tool, duration_ms=120.0, success=True, root="demo-proj")

    stats = store.get_stats(root="demo-proj")
    assert stats["success"] is True
    assert stats["is_global"] is False
    assert stats["root"] == "demo-proj"

    items_map = {it["name"]: it for it in stats["items"]}
    assert items_map["/health"]["calls"] == 4
    assert items_map["/health"]["success_rate"] == 100.0
    assert items_map["/api/search"]["calls"] == 1
    assert items_map["local_ai_status"]["calls"] == 1
    assert items_map["local_ai_repo:context"]["calls"] == 1
    assert items_map["local_ai_coord:task_create"]["calls"] == 1

    # Verify uncalled registered items show 0 calls
    catalog = get_registered_surface_catalog()
    assert len(catalog) > 10
    uncalled = [it for it in stats["items"] if it["calls"] == 0]
    assert len(uncalled) > 0
    for u in uncalled:
        assert u["status"] == "unused"
        assert u["p50_ms"] == 0.0
        assert u["success_rate"] is None
