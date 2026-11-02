from __future__ import annotations

from pathlib import Path
import pytest

from local_ai_hub.endpoint_stats import (
    EndpointStatsStore,
    calculate_percentiles,
    get_latency_bucket_index,
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


def test_endpoint_stats_read_failure_is_not_reported_as_zero(tmp_path, monkeypatch):
    import sqlite3
    store = EndpointStatsStore(tmp_path / "state")
    def fail_connect():
        raise sqlite3.OperationalError("unavailable")
    monkeypatch.setattr(store, "_connect", fail_connect)
    report = store.get_stats()
    assert report["success"] is False
    assert report["error"] == "endpoint stats unavailable"


def test_exact_scopes_preserve_legacy_counts_and_event_dedup_after_restart(tmp_path):
    import time
    from contextlib import closing

    state = tmp_path / "state"
    store = EndpointStatsStore(state)
    with closing(store._connect()) as con, con:
        con.execute("INSERT INTO endpoint_stats(scope_root,item_type,item_name,calls,success_calls,b0) VALUES(?,?,?,?,?,?)",
                    ("shared", "mcp", "tool", 1, 1, 1))
        con.execute("INSERT INTO endpoint_call_ids(event_id,created_at) VALUES(?,?)", ("legacy-event", time.time()))

    root = str(tmp_path / "a" / "shared")
    store.record_call(item_type="mcp", item_name="tool", duration_ms=1, root=root, event_id="legacy-event")
    store.record_call(item_type="mcp", item_name="tool", duration_ms=1, root=root, event_id="new-event")
    store.record_call(item_type="mcp", item_name="tool", duration_ms=1, root=root, event_id="new-event")
    store.record_call(item_type="mcp", item_name="tool", duration_ms=1, root="shared")

    reopened = EndpointStatsStore(state)
    assert reopened.get_stats(root=root, include_unused=False)["items"][0]["calls"] == 1
    assert reopened.get_stats(root="legacy:shared", include_unused=False)["items"][0]["calls"] == 1
    assert reopened.get_stats(include_unused=False)["items"][0]["calls"] == 3
    assert reopened.get_stats(root="shared")["success"] is False


def test_project_stats_disclose_basename_grouping_and_tool_call_semantics(tmp_path):
    from contextlib import closing
    from local_ai_hub.dashboard import DASHBOARD_HTML

    store = EndpointStatsStore(tmp_path / "state")
    with closing(store._connect()) as con, con:
        con.execute("INSERT INTO endpoint_stats(scope_root,item_type,item_name,calls,success_calls,b0) VALUES(?,?,?,?,?,?)",
                    ("shared", "mcp", "local_ai_task:review", 4, 4, 4))
    store.record_call(item_type="mcp", item_name="local_ai_task:review", duration_ms=1,
                      root="C:/one/shared")
    store.record_call(item_type="mcp", item_name="local_ai_task:review", duration_ms=1,
                      root="C:/two/shared")
    report = store.get_stats(root="C:/one/shared", include_unused=False)
    assert report["project_scope_precision"] == "exact_root"
    assert report["items"][0]["calls"] == 1
    other = store.get_stats(root="C:/two/shared", include_unused=False)
    assert other["root"] != report["root"] and other["items"][0]["calls"] == 1
    assert store.get_stats(root=report["root"], include_unused=False)["items"][0]["calls"] == 1
    assert store.get_stats(root="c:/ONE/shared/../shared", include_unused=False)["root"] == report["root"]
    legacy = store.get_stats(root="legacy:shared", include_unused=False)
    assert legacy["project_scope_precision"] == "historical_basename"
    assert legacy["items"][0]["calls"] == 4
    global_report = store.get_stats(include_unused=False)
    assert global_report["items"][0]["calls"] == 6
    assert store.reset(root="C:/one/shared") is True
    assert store.get_stats(root="C:/two/shared", include_unused=False)["items"][0]["calls"] == 1
    assert store.get_stats(root="legacy:shared", include_unused=False)["items"][0]["calls"] == 4
    assert store.get_stats(root="C:/one/shared", include_unused=False)["items"] == []
    assert store.get_stats(root="shared", include_unused=False)["success"] is False
    assert store.reset(root="shared") is False
    assert store.reset(root="legacy:shared") is True
    assert store.get_stats(root="C:/two/shared", include_unused=False)["items"][0]["calls"] == 1
    assert 'id="epStatsScopeNotice"' in DASHBOARD_HTML
    assert "historické" in DASHBOARD_HTML
    assert "neprokazuje spuštění modelu" in DASHBOARD_HTML
    assert "historickou skupinu" in DASHBOARD_HTML


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
    assert any(p.endswith(":project-a") for p in global_stats["projects"])
    assert any(p.endswith(":project-b") for p in global_stats["projects"])

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
    proj_a_stats = store.get_stats(root="C:/repo/project-a")
    assert proj_a_stats["is_global"] is False
    assert proj_a_stats["root"].endswith(":project-a")
    proj_a_items = {it["name"]: it for it in proj_a_stats["items"]}
    assert proj_a_items["/api/search"]["calls"] == 3
    assert proj_a_items["local_ai_repo:context"]["calls"] == 0

    # Reset project-a
    assert store.reset(root="C:/repo/project-a") is True
    after_reset_a = store.get_stats(root="C:/repo/project-a")
    assert {it["name"]: it for it in after_reset_a["items"]}["/api/search"]["calls"] == 0

    # project-b still has its stats
    proj_b_stats = store.get_stats(root="C:/repo/project-b")
    assert {it["name"]: it for it in proj_b_stats["items"]}["local_ai_repo:context"]["calls"] == 1

    # Global reset clears all
    assert store.reset() is True
    after_global_reset = store.get_stats()
    assert all(it["calls"] == 0 for it in after_global_reset["items"])


def test_endpoint_stats_compaction_options(tmp_path: Path):
    store = EndpointStatsStore(tmp_path / "state")
    store.record_call(item_type="endpoint", item_name="/api/status", duration_ms=15.0, success=True)

    # Default: include_unused=True, include_buckets=False
    stats_default = store.get_stats()
    assert stats_default["total_items"] > 10
    assert stats_default["unused_count"] > 10
    assert len(stats_default["items"]) == stats_default["total_items"]
    # Buckets omitted by default
    assert "bucket_counts" not in stats_default["items"][0]

    # Compact: include_unused=False
    stats_active = store.get_stats(include_unused=False)
    assert stats_active["total_items"] == stats_default["total_items"]
    assert stats_active["unused_count"] == stats_default["unused_count"]
    assert len(stats_active["items"]) == 1
    assert stats_active["items"][0]["name"] == "/api/status"
    assert "bucket_counts" not in stats_active["items"][0]

    # With buckets: include_buckets=True
    stats_with_buckets = store.get_stats(include_unused=False, include_buckets=True)
    assert len(stats_with_buckets["items"]) == 1
    assert "bucket_counts" in stats_with_buckets["items"][0]
    assert len(stats_with_buckets["items"][0]["bucket_counts"]) == 14

