from __future__ import annotations

import json
from pathlib import Path
import pytest

from local_ai_hub.endpoint_stats import EndpointStatsStore
from local_ai_hub.mcp_server import _compact_endpoint_stats


def test_endpoint_stats_api_lifecycle(tmp_path: Path):
    store = EndpointStatsStore(tmp_path / "state")

    # Record some calls
    root1, root2 = str(tmp_path / "proj-1"), str(tmp_path / "proj-2")
    store.record_call(item_type="endpoint", item_name="/api/search", duration_ms=25.0, success=True, root=root1)
    store.record_call(item_type="endpoint", item_name="/api/search", duration_ms=150.0, success=True, root=root1)
    store.record_call(item_type="mcp", item_name="local_ai_repo:context", duration_ms=45.0, success=True, root=root2)

    # Global stats
    global_res = store.get_stats()
    assert global_res["success"] is True
    assert global_res["is_global"] is True
    assert global_res["window"] == "stored_since_reset"
    assert global_res["latency_method"] == "fixed_histogram_bucket_estimate"
    assert global_res["histogram_bucket_ceiling_ms"] == 120000
    assert global_res["histogram_top_bucket_open_ended"] is True
    assert global_res["last_used_unit"] == "unix_seconds"
    assert len(global_res["projects"]) == 2
    assert global_res["total_items"] > 0
    assert global_res["unused_count"] > 0

    items = {i["name"]: i for i in global_res["items"]}
    assert items["/api/search"]["calls"] == 2
    assert items["/api/search"]["success_rate"] == 100.0
    assert items["local_ai_repo:context"]["calls"] == 1

    # Project-specific stats
    proj1_res = store.get_stats(root=root1)
    assert proj1_res["success"] is True
    assert proj1_res["is_global"] is False
    assert proj1_res["window"] == "stored_since_reset"
    assert proj1_res["root"] in global_res["projects"]
    proj1_items = {i["name"]: i for i in proj1_res["items"]}
    assert proj1_items["/api/search"]["calls"] == 2
    assert proj1_items["local_ai_repo:context"]["calls"] == 0

    # Reset single project
    assert store.reset(root=root1) is True
    proj1_res_after = store.get_stats(root=root1)
    proj1_items_after = {i["name"]: i for i in proj1_res_after["items"]}
    assert proj1_items_after["/api/search"]["calls"] == 0

    # Project 2 remains intact
    proj2_res = store.get_stats(root=root2)
    proj2_items = {i["name"]: i for i in proj2_res["items"]}
    assert proj2_items["local_ai_repo:context"]["calls"] == 1

    # Global reset
    assert store.reset() is True
    global_res_after = store.get_stats()
    assert all(i["calls"] == 0 for i in global_res_after["items"])


def test_compact_endpoint_stats_preserves_all_issue_dimensions():
    response = _compact_endpoint_stats({
        "success": True,
        "items": [{
            "type": "mcp",
            "name": "local_ai_repo:search",
            "calls": 10,
            "success_rate": 80.0,
            "p50_ms": 1500.0,
            "p95_ms": 12000.0,
            "p99_ms": 20000.0,
            "last_used": 1794537000.0,
            "status": "failing",
            "issues": ["failing", "slow"],
        }, {
            "type": "http",
            "name": "/api/invalid-last-used",
            "calls": 1,
            "last_used": float("nan"),
        }],
    })

    assert response["items"][0]["status"] == "failing"
    assert response["items"][0]["issues"] == ["failing", "slow"]
    assert response["window"] == "stored_since_reset"
    assert response["latency_method"] == "fixed_histogram_bucket_estimate"
    assert response["histogram_bucket_ceiling_ms"] == 120000
    assert response["histogram_top_bucket_open_ended"] is True
    assert response["last_used_unit"] == "unix_seconds"
    assert response["items"][0]["last_used"] == 1794537000.0
    assert "last_used" not in response["items"][1]


def test_project_stats_skip_global_scans_and_project_list_payload(tmp_path, monkeypatch):
    store = EndpointStatsStore(tmp_path / "state")
    selected_root = str(tmp_path / "selected")
    other_root = str(tmp_path / "other")
    store.record_call(
        item_type="endpoint", item_name="/api/selected", duration_ms=20,
        success=True, root=selected_root,
    )
    store.record_call(
        item_type="endpoint", item_name="/api/other", duration_ms=30,
        success=False, root=other_root,
    )

    statements = []
    connect = store._connect

    def traced_connect(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(store, "_connect", traced_connect)
    result = store.get_stats(root=selected_root)

    assert result["success"] is True
    assert "projects" not in result
    assert not any("select distinct scope_root from endpoint_stats" in s.lower() for s in statements)
    assert not any("union select item_type, item_name" in s.lower() for s in statements)
    items = {item["name"]: item for item in result["items"]}
    assert items["/api/selected"]["calls"] == 1
    assert "/api/other" not in items


def test_project_stats_read_does_not_wait_for_telemetry_writer_lock(tmp_path):
    import threading

    store = EndpointStatsStore(tmp_path / "state")
    lock_held = threading.Event()
    release_lock = threading.Event()
    finished = threading.Event()
    result = []

    def hold_writer_lock():
        with store._lock:
            lock_held.set()
            release_lock.wait(timeout=3)

    def read_stats():
        result.append(store.get_stats(root=str(tmp_path)))
        finished.set()

    holder = threading.Thread(target=hold_writer_lock)
    holder.start()
    assert lock_held.wait(timeout=1)
    reader = threading.Thread(target=read_stats)
    reader.start()
    try:
        assert finished.wait(timeout=0.5), "read waited behind the telemetry writer lock"
    finally:
        release_lock.set()
        holder.join(timeout=2)
        reader.join(timeout=2)

    assert result[0]["success"] is True
