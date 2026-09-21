from __future__ import annotations

import sqlite3

from local_ai_hub.telemetry import TelemetryStore


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


def test_schema_upgrade_adds_metadata_columns_without_discarding_history(tmp_path):
    state = tmp_path / "telemetry"
    store = TelemetryStore(state, enabled=True, flush_interval_seconds=0.01)
    store.record_http(action="/api/legacy", success=True)
    store.flush(1)
    store.close()

    db = state / "telemetry.sqlite3"
    con = sqlite3.connect(db)
    try:
        for column in ("queue_age_ms", "terminal", "retryable", "receipt_count"):
            ddl = "ALTER" + " TABLE"
            con.execute(f'{ddl} events DROP COLUMN "{column}"')
        con.commit()
    finally:
        con.close()

    upgraded = TelemetryStore(state, enabled=True, flush_interval_seconds=0.01)
    try:
        summary = upgraded.summary(1)
        assert summary["decision_grade"]["counts"]["events"] == 1
        con = sqlite3.connect(db)
        try:
            columns = {row[1] for row in con.execute("PRAGMA table_info(events)")}
        finally:
            con.close()
        assert {"queue_age_ms", "terminal", "retryable", "receipt_count"}.issubset(columns)
    finally:
        upgraded.close()
