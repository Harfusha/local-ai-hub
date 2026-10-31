from __future__ import annotations

import json
from pathlib import Path
import pytest

from local_ai_hub.endpoint_stats import EndpointStatsStore


def test_endpoint_stats_api_lifecycle(tmp_path: Path):
    store = EndpointStatsStore(tmp_path / "state")

    # Record some calls
    store.record_call(item_type="endpoint", item_name="/api/search", duration_ms=25.0, success=True, root="proj-1")
    store.record_call(item_type="endpoint", item_name="/api/search", duration_ms=150.0, success=True, root="proj-1")
    store.record_call(item_type="mcp", item_name="local_ai_repo:context", duration_ms=45.0, success=True, root="proj-2")

    # Global stats
    global_res = store.get_stats()
    assert global_res["success"] is True
    assert global_res["is_global"] is True
    assert set(global_res["projects"]) == {"proj-1", "proj-2"}
    assert global_res["total_items"] > 0
    assert global_res["unused_count"] > 0

    items = {i["name"]: i for i in global_res["items"]}
    assert items["/api/search"]["calls"] == 2
    assert items["/api/search"]["success_rate"] == 100.0
    assert items["local_ai_repo:context"]["calls"] == 1

    # Project-specific stats
    proj1_res = store.get_stats(root="proj-1")
    assert proj1_res["success"] is True
    assert proj1_res["is_global"] is False
    assert proj1_res["root"] == "proj-1"
    proj1_items = {i["name"]: i for i in proj1_res["items"]}
    assert proj1_items["/api/search"]["calls"] == 2
    assert proj1_items["local_ai_repo:context"]["calls"] == 0

    # Reset single project
    assert store.reset(root="proj-1") is True
    proj1_res_after = store.get_stats(root="proj-1")
    proj1_items_after = {i["name"]: i for i in proj1_res_after["items"]}
    assert proj1_items_after["/api/search"]["calls"] == 0

    # Project 2 remains intact
    proj2_res = store.get_stats(root="proj-2")
    proj2_items = {i["name"]: i for i in proj2_res["items"]}
    assert proj2_items["local_ai_repo:context"]["calls"] == 1

    # Global reset
    assert store.reset() is True
    global_res_after = store.get_stats()
    assert all(i["calls"] == 0 for i in global_res_after["items"])
