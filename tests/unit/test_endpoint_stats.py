from __future__ import annotations

from pathlib import Path
import pytest

from local_ai_hub.endpoint_stats import (
    EndpointStatsStore,
    calculate_percentiles,
    get_latency_bucket_index,
    clean_project_root,
    get_registered_surface_catalog,
)


def test_bucket_index():
    assert get_latency_bucket_index(2.0) == 0      # < 5ms
    assert get_latency_bucket_index(5.0) == 1      # 5 - 10ms
    assert get_latency_bucket_index(9.9) == 1
    assert get_latency_bucket_index(10.0) == 2     # 10 - 25ms
    assert get_latency_bucket_index(500.0) == 7    # 500 - 1000ms
    assert get_latency_bucket_index(1200.0) == 8   # 1000 - 2500ms
    assert get_latency_bucket_index(70000.0) == 13 # >= 60000ms


def test_percentile_calculation():
    # Synthetic distribution: 100 calls in bucket 1 (5-10ms)
    b_counts = [0] * 14
    b_counts[1] = 100
    p50, p95, p99 = calculate_percentiles(b_counts, 100)
    assert 5.0 <= p50 <= 10.0
    assert 5.0 <= p95 <= 10.0
    assert 5.0 <= p99 <= 10.0

    # Half in bucket 0 (0-5ms), half in bucket 7 (500-1000ms)
    b_counts = [0] * 14
    b_counts[0] = 50
    b_counts[7] = 50
    p50, p95, p99 = calculate_percentiles(b_counts, 100)
    # p50 is at the boundary of b0 and b7
    assert p50 <= 500.0
    assert 500.0 <= p95 <= 1000.0
    assert 500.0 <= p99 <= 1000.0


def test_clean_project_root():
    assert clean_project_root("C:\\Users\\Adam\\my-project") == "my-project"
    assert clean_project_root("/home/user/project/") == "project"
    assert clean_project_root("all") == ""
    assert clean_project_root(None) == ""


def test_endpoint_stats_store_lifecycle(tmp_path: Path):
    store = EndpointStatsStore(tmp_path / "state")

    # Record calls for project-a
    store.record_call(item_type="endpoint", item_name="/api/search", duration_ms=45.0, success=True, root="C:/repo/project-a")
    store.record_call(item_type="endpoint", item_name="/api/search", duration_ms=120.0, success=True, root="C:/repo/project-a")
    store.record_call(item_type="endpoint", item_name="/api/search", duration_ms=1500.0, success=False, root="C:/repo/project-a")

    # Record calls for project-b
    store.record_call(item_type="mcp", item_name="local_ai_repo:context", duration_ms=80.0, success=True, root="C:/repo/project-b")

    # Query global stats
    global_stats = store.get_stats()
    assert global_stats["success"] is True
    assert global_stats["is_global"] is True
    assert "project-a" in global_stats["projects"]
    assert "project-b" in global_stats["projects"]

    items_by_name = {it["name"]: it for it in global_stats["items"]}
    assert "/api/search" in items_by_name
    search_item = items_by_name["/api/search"]
    assert search_item["calls"] == 3
    assert search_item["success_calls"] == 2
    assert search_item["fail_calls"] == 1
    assert round(search_item["success_rate"], 1) == 66.7
    assert search_item["p50_ms"] > 0
    assert search_item["status"] == "failing"  # < 90%

    mcp_item = items_by_name["local_ai_repo:context"]
    assert mcp_item["calls"] == 1
    assert mcp_item["success_rate"] == 100.0

    # Check uncalled catalog items have calls == 0
    catalog = get_registered_surface_catalog()
    assert len(catalog) > 10
    health_item = items_by_name.get("/health")
    assert health_item is not None
    assert health_item["calls"] == 0
    assert health_item["status"] == "unused"

    # Query project-a specific stats
    proj_a_stats = store.get_stats(root="project-a")
    assert proj_a_stats["is_global"] is False
    assert proj_a_stats["root"] == "project-a"
    proj_a_items = {it["name"]: it for it in proj_a_stats["items"]}
    assert proj_a_items["/api/search"]["calls"] == 3
    assert proj_a_items["local_ai_repo:context"]["calls"] == 0

    # Reset project-a
    assert store.reset(root="project-a") is True
    after_reset_a = store.get_stats(root="project-a")
    assert {it["name"]: it for it in after_reset_a["items"]}["/api/search"]["calls"] == 0

    # project-b still has its stats
    proj_b_stats = store.get_stats(root="project-b")
    assert {it["name"]: it for it in proj_b_stats["items"]}["local_ai_repo:context"]["calls"] == 1

    # Global reset clears all
    assert store.reset() is True
    after_global_reset = store.get_stats()
    assert all(it["calls"] == 0 for it in after_global_reset["items"])
