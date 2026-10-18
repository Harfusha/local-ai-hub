from __future__ import annotations

import ast
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from local_ai_hub.http_route_registry import (
    GET_ROUTE_HANDLER_BOUNDARIES,
    POST_ROUTE_REGISTRY,
    TELEMETRY_SAFE_GET_ROUTE_LABELS,
)
from local_ai_hub.telemetry import TelemetryStore, _safe_metadata
from tools.surface_inventory import _extract_http


def test_summary_exposes_decision_grade_aggregates(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry", enabled=True, flush_interval_seconds=0.01)
    try:
        store.record_http(
            action="/api/repo/search",
            route="repo>deterministic",
            cache_layer="workspace",
            cache_hit=True,
            queue_age_ms=12,
            terminal=True,
            retryable=False,
            receipt_count=2,
            success=True,
        )
        store.record_http(
            action="/api/reason",
            route="semantic",
            cache_layer="miss",
            queue_age_ms=35,
            terminal=False,
            retryable=True,
            bypass_reason="quality_gate",
            success=False,
        )
        store.flush(1)
        summary = store.summary(1)
    finally:
        store.close()

    assert summary["counts"]["events"] == 2
    assert summary["counts"]["cache_hits"] == 1
    assert summary["counts"]["bypasses"] == 1
    assert summary["counts"]["terminal"] == 1
    assert summary["counts"]["retryable"] == 1
    assert summary["counts"]["receipts"] == 2
    assert {item["route"] for item in summary["routes"]} == {"repo>deterministic", "semantic"}
    assert summary["queue"]["max_age_ms"] == 35.0
    assert summary["detail"]["status"] == "complete"


def test_report_marks_bounded_detail_incomplete_when_lists_are_truncated(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry", enabled=True, flush_interval_seconds=0.01)
    try:
        for index in range(30):
            store.record_http(
                action=f"/api/{index}",
                route=f"route-{index}",
                bypass_reason=f"reason-{index}",
                success=True,
            )
        store.flush(1)
        report = store.report(1)
    finally:
        store.close()

    detail = report["decision_grade"]["detail"]
    assert detail["truncated"] is True
    assert detail["status"] == "incomplete"
    assert len(report["decision_grade"]["routes"]) <= 24
    assert len(report["decision_grade"]["bypass"]) <= 24


def test_telemetry_metadata_redacts_absolute_paths_and_payload_like_fields(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry", enabled=True, flush_interval_seconds=0.01)
    private_posix = "/" + "Users/" + "fixture/private/source.py"
    try:
        store.record_http(
            action="C:\\private\\prompt.txt",
            route=private_posix,
            prompt="do not persist this",
            source_text="do not persist this either",
            model_output="never persist output",
        )
        store.flush(1)
        report = store.report(1)
    finally:
        store.close()

    rendered = repr(report).lower()
    assert "c:\\users\\adam\\private" not in rendered
    assert private_posix.lower() not in rendered
    assert "prompt" not in rendered
    assert "source_text" not in rendered
    assert "model_output" not in rendered


def test_telemetry_metadata_preserves_registered_route_without_query_or_fragment():
    assert _safe_metadata(
        "/api/telemetry/report?days=7&token=query-secret#fragment",
        preserve_route=True,
    ) == "/api/telemetry/report"
    assert {
        _safe_metadata(route, preserve_route=True)
        for route in TELEMETRY_SAFE_GET_ROUTE_LABELS
    } == TELEMETRY_SAFE_GET_ROUTE_LABELS
    assert _safe_metadata("/Users/fixture/private/source.py", preserve_route=True) == "<path>"


def test_telemetry_debug_trace_route_hides_identifier_but_keeps_route_label():
    assert _safe_metadata(
        "/api/debug-traces/trace-secret?token=dynamic-secret",
        preserve_route=True,
    ) == "/api/debug-traces/{trace_id}"


def test_telemetry_preserves_all_source_discovered_exact_http_routes():
    root = Path(__file__).resolve().parents[1]
    source_path = root / "src" / "local_ai_hub" / "http_server.py"
    source = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    routes = _extract_http(source, "src/local_ai_hub/http_server.py")
    exact_routes = {
        route["path"]
        for route in routes
        if route["method"] in {"GET", "POST"} and route["match"] == "exact"
    }
    exact_routes.update(GET_ROUTE_HANDLER_BOUNDARIES)
    exact_routes.update(path for rule in POST_ROUTE_REGISTRY for path in rule.paths)
    # The coverage extractor intentionally excludes the context-pack handler body.
    exact_routes.add("/api/context/pack")

    unpreserved = sorted(
        route
        for route in exact_routes
        if _safe_metadata(route, preserve_route=True) != route
    )
    assert not unpreserved, f"exact HTTP route labels are redacted: {unpreserved}"


def test_unsupported_telemetry_schema_is_preserved_for_offline_conversion(tmp_path):
    state = tmp_path / "telemetry"
    store = TelemetryStore(state, enabled=True, flush_interval_seconds=0.01)
    store.record_http(action="/api/status", success=True)
    store.flush(1)
    store.close()

    db = state / "telemetry.sqlite3"
    con = sqlite3.connect(db)
    try:
        for column in (
            "queue_age_ms", "terminal", "retryable", "receipt_count", "root",
            "db_wait_ms", "exec_ms", "serialization_ms",
            "db_wait_measured", "exec_measured", "serialization_measured",
        ):
            ddl = "ALTER" + " TABLE"
            con.execute(f'{ddl} events DROP COLUMN "{column}"')
        con.commit()
    finally:
        con.close()

    try:
        TelemetryStore(state, enabled=True, flush_interval_seconds=0.01)
    except RuntimeError as exc:
        assert "explicit offline conversion required" in str(exc)
    else:
        raise AssertionError("unsupported telemetry schema was silently upgraded")

    with closing(sqlite3.connect(db)) as con:
        columns = {row[1] for row in con.execute("PRAGMA table_info(events)")}
        rows = con.execute("SELECT action FROM events ORDER BY id").fetchall()
    assert not set(TelemetryStore._EVENT_COLUMNS).issubset(columns)
    assert rows == [("/api/status",)]


def test_realtime_summary_preserves_pricing_and_writer_health(tmp_path, monkeypatch):
    store = TelemetryStore(tmp_path, enabled=True)
    summary = {
        "data_available": True, "estimated_savings_pricing_mode": "input_output",
        "estimated_input_savings_usd": 0.0008, "estimated_output_savings_usd": 0.0012,
        "cloud_input_token_cost_usd_per_million": 2.0,
        "cloud_output_token_cost_usd_per_million": 8.0,
        "net_cloud_token_delta_est": -42,
        "writer": {"dropped": 9, "writer_errors": 1},
    }
    monkeypatch.setattr(store, "dashboard_report", lambda *args, **kwargs: {"summary": summary})
    try:
        projected = store.realtime_summary()
        for key, value in summary.items():
            assert projected[key] == value
        assert projected["enabled"] is True
    finally:
        store.close()


def test_dashboard_report_marks_cached_metrics_unavailable_after_read_failure(tmp_path, monkeypatch):
    store = TelemetryStore(tmp_path, enabled=True)
    try:
        cached = store.dashboard_report(scope="process")
        store._dashboard_cache_at[(30, "process")] = 0

        def fail_report(*args, **kwargs):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(store, "report", fail_report)
        result = store.dashboard_report(scope="process")
        assert result["summary"]["data_available"] is False
        assert result["summary"]["stale"] is True
        assert cached["summary"]["data_available"] is True
        assert store.realtime_summary()["data_available"] is False
    finally:
        store.close()


def test_session_history_uses_signed_tool_accounting_delta(tmp_path):
    store = TelemetryStore(tmp_path, enabled=True)
    try:
        store.session_start()
        store.record(event_type="inference", avoided_cloud_tokens=900)
        store.record_tool_accounting({"tool": "local_ai_repo", "net_cloud_token_delta_est": -42})
        assert store.flush(2)
        assert store.sessions()[0]["tokens_saved"] == -42
    finally:
        store.close()


def test_window_token_totals_survive_raw_retention_pruning(tmp_path):
    store = TelemetryStore(tmp_path, enabled=True, max_events=100)
    try:
        for _ in range(150):
            store.record_tool_accounting({"tool": "local_ai_repo", "net_cloud_token_delta_est": 7})
        assert store.flush(3)
        store._prune()
        store._summary_cache.clear()
        with closing(store._connect()) as con:
            assert con.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 100
        summary = store.summary(30, scope="window")
        assert summary["tool_accounting_events"] == 150
        assert summary["net_cloud_token_delta_est"] == 1050
        assert summary["accounting_boundary_incomplete"] is False
    finally:
        store.close()


def test_rollup_accounting_keeps_exact_partial_day_boundary_without_overlap(tmp_path):
    store = TelemetryStore(tmp_path, enabled=True)
    cutoff = time.time() - 86400
    try:
        for created_at, delta in [(cutoff - 60, 100), (cutoff + 60, 7), (time.time(), 11)]:
            store.record(event_type="tool_accounting", created_at=created_at, net_cloud_token_delta=delta)
        assert store.flush(2)
        summary = store.summary(1, scope="window")
        assert summary["tool_accounting_events"] == 2
        assert summary["net_cloud_token_delta_est"] == 18
    finally:
        store.close()


def test_pruned_partial_boundary_day_is_reported_incomplete_not_invented(tmp_path, monkeypatch):
    store = TelemetryStore(tmp_path, enabled=True)
    cutoff = time.time() // 86400 * 86400 - 43200
    monkeypatch.setattr(store, "_cutoff", lambda days: cutoff)
    try:
        store.record(event_type="tool_accounting", created_at=cutoff + 60, net_cloud_token_delta=7)
        store.record(event_type="tool_accounting", net_cloud_token_delta=11)
        assert store.flush(2)
        with closing(store._connect()) as con:
            con.execute("DELETE FROM events WHERE created_at<?", (time.time() - 3600,))
            con.commit()
        summary = store.summary(1, scope="window")
        assert summary["net_cloud_token_delta_est"] == 11
        assert summary["accounting_boundary_incomplete"] is True
    finally:
        store.close()
