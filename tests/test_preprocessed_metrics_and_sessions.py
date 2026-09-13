from __future__ import annotations

import time
from pathlib import Path

from local_ai_hub.telemetry import TelemetryStore
from local_ai_hub.preprocess import ProjectPreprocessor
from local_ai_hub.dashboard import DASHBOARD_HTML


def test_preprocess_ingestion_reuse_rate():
    # Empty stats
    preprocessor = object.__new__(ProjectPreprocessor)
    preprocessor._stats = {
        "file_card_hits": 0,
        "deterministic_card_hits": 0,
        "file_card_generations": 0,
        "deterministic_module_hits": 0,
        "deterministic_project_hits": 0,
    }
    assert preprocessor.ingestion_reuse_rate() == 0.0

    # 10 hits, 0 generations -> 100%
    preprocessor._stats["file_card_hits"] = 8
    preprocessor._stats["deterministic_card_hits"] = 2
    preprocessor._stats["file_card_generations"] = 0
    assert preprocessor.ingestion_reuse_rate() == 1.0

    # 10 hits, 10 generations -> 50%
    preprocessor._stats["file_card_generations"] = 10
    assert preprocessor.ingestion_reuse_rate() == 0.5


def test_telemetry_process_sessions_lifecycle(tmp_path: Path):
    telemetry = TelemetryStore(tmp_path, enabled=True, flush_interval_seconds=0.05)
    try:
        # Start session 1
        s1_id = telemetry.session_start(pid=1001, version="1.0.0")
        assert s1_id > 0

        # Record an inference event in session 1
        telemetry.record(action="solve", cache_hit=True, input_tokens=100, output_tokens=50, avoided_cloud_tokens=150)
        telemetry.flush(1.0)

        sessions = telemetry.sessions(days=30)
        assert len(sessions) == 1
        active = sessions[0]
        assert active["pid"] == 1001
        assert active["version"] == "1.0.0"
        assert active["status"] == "active"
        assert active["events"] == 1
        assert active["cache_hits"] == 1
        assert active["cache_hit_rate"] == 1.0

        # Heartbeat update
        telemetry.session_heartbeat()

        # Clean stop
        telemetry.session_stop()
        stopped_sessions = telemetry.sessions(days=30)
        assert len(stopped_sessions) == 1
        stopped = stopped_sessions[0]
        assert stopped["status"] == "clean_stop"
        assert stopped["exit_clean"] == 1
        assert stopped["duration_seconds"] >= 0.0

    finally:
        telemetry.close()


def test_telemetry_process_sessions_crashed_detection(tmp_path: Path):
    telemetry = TelemetryStore(tmp_path, enabled=True, flush_interval_seconds=0.05)
    try:
        # Start session 1 that does NOT cleanly stop (simulating crash)
        telemetry.session_start(pid=2001, version="1.0.0")
        time.sleep(0.05)
        telemetry.session_heartbeat()

        # Now simulate hub restarting with new PID
        telemetry.session_start(pid=2002, version="1.0.0")

        sessions = telemetry.sessions(days=30)
        assert len(sessions) == 2

        # First in list is newest (active), second is older (crashed)
        by_pid = {s["pid"]: s for s in sessions}
        assert by_pid[2002]["status"] == "active"
        assert by_pid[2001]["status"] == "crashed"
        assert by_pid[2001]["exit_clean"] == 0

    finally:
        telemetry.close()


def test_preprocessed_query_hit_rate_telemetry(tmp_path: Path):
    telemetry = TelemetryStore(tmp_path, enabled=True, flush_interval_seconds=0.05)
    try:
        telemetry.record_http(
            action="/api/repo/search",
            status_code=200,
            success=True,
            preprocessed_hit=True,
        )
        telemetry.record_http(
            action="/api/repo/search",
            status_code=200,
            success=True,
            preprocessed_hit=False,
        )
        telemetry.flush(1.0)

        summary = telemetry.summary(days=30)
        assert summary.get("preprocessed_query_hits") == 1
        assert summary.get("preprocessed_query_events") == 2
        assert summary.get("preprocessed_query_hit_rate") == 0.5
    finally:
        telemetry.close()


def test_dashboard_sessions_and_preprocessed_metrics():
    assert 'id="sessionRows"' in DASHBOARD_HTML
    assert 'id="hubHealthCard"' in DASHBOARD_HTML
    assert "Process session &amp; restart history" in DASHBOARD_HTML
    assert "card reuse" in DASHBOARD_HTML
    assert "index hit" in DASHBOARD_HTML
    assert "session_id" in DASHBOARD_HTML
    assert "Process Session Details" in DASHBOARD_HTML

