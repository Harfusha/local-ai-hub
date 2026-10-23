from __future__ import annotations

from contextlib import closing
import sqlite3
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


def test_telemetry_sessions_aggregates_all_session_windows_in_one_query(tmp_path: Path, monkeypatch):
    telemetry = TelemetryStore(tmp_path, enabled=True, flush_interval_seconds=0.05)
    try:
        first_id = telemetry.session_start(pid=3001, version="batch")
        second_id = telemetry.session_start(pid=3002, version="batch")
        empty_id = telemetry.session_start(pid=3003, version="batch")
        base = time.time() - 60.0

        telemetry.record(action="batch-inference", event_type="inference", cache_hit=True, success=True)
        telemetry.record(action="batch-http", event_type="http", cache_hit=True, success=False)
        telemetry.record(action="batch-accounting", event_type="tool_accounting", success=True)
        assert telemetry.flush(1.0)

        with closing(sqlite3.connect(telemetry.path)) as con, con:
            con.execute(
                "UPDATE process_sessions SET started_at=?,stopped_at=NULL,last_heartbeat=?,exit_clean=0 WHERE id=?",
                (base, base + 30.0, first_id),
            )
            con.execute(
                "UPDATE process_sessions SET started_at=?,stopped_at=NULL,last_heartbeat=?,exit_clean=0 WHERE id=?",
                (base + 10.0, base + 40.0, second_id),
            )
            con.execute(
                "UPDATE process_sessions SET started_at=?,stopped_at=?,last_heartbeat=?,exit_clean=1 WHERE id=?",
                (base + 80.0, base + 70.0, base + 70.0, empty_id),
            )
            con.execute(
                "UPDATE events SET created_at=? WHERE action='batch-inference'",
                (base,),
            )
            con.execute(
                "UPDATE events SET created_at=? WHERE action='batch-http'",
                (base + 15.0,),
            )
            con.execute(
                "UPDATE events SET created_at=?,net_cloud_token_delta=-7 WHERE action='batch-accounting'",
                (base + 30.0,),
            )

        telemetry._current_session_id = second_id
        statements = []
        original_connect = telemetry._connect

        class CountingConnection:
            def __init__(self, connection):
                self._connection = connection

            def execute(self, sql, parameters=()):
                statements.append(sql)
                return self._connection.execute(sql, parameters)

            def close(self):
                self._connection.close()

        with monkeypatch.context() as patch:
            patch.setattr(telemetry, "_connect", lambda: CountingConnection(original_connect()))
            sessions = telemetry.sessions(days=30)

        assert len([sql for sql in statements if "events" in sql.lower()]) == 1
        by_id = {session["session_id"]: session for session in sessions}
        assert by_id[first_id]["status"] == "crashed"
        assert by_id[first_id]["events"] == 3
        assert by_id[first_id]["cache_hits"] == 1
        assert by_id[first_id]["cache_hit_rate"] == 1.0
        assert by_id[first_id]["tokens_saved"] == -7
        assert by_id[first_id]["failures"] == 1

        assert by_id[second_id]["status"] == "active"
        assert by_id[second_id]["events"] == 2
        assert by_id[second_id]["cache_hits"] == 1
        assert by_id[second_id]["cache_hit_rate"] == 0.5
        assert by_id[second_id]["tokens_saved"] == -7
        assert by_id[second_id]["failures"] == 1

        assert by_id[empty_id]["status"] == "clean_stop"
        assert by_id[empty_id]["duration_seconds"] == 0.0
        assert by_id[empty_id]["events"] == 0
        assert by_id[empty_id]["cache_hit_rate"] == 0.0
    finally:
        telemetry.close()


def test_telemetry_sessions_limits_to_newest_100_in_order(tmp_path: Path):
    telemetry = TelemetryStore(tmp_path, enabled=True, flush_interval_seconds=0.05)
    try:
        base = time.time() - 1000.0
        with closing(sqlite3.connect(telemetry.path)) as con, con:
            con.executemany(
                "INSERT INTO process_sessions (pid,version,started_at,last_heartbeat,exit_clean) "
                "VALUES (?, ?, ?, ?, 0)",
                [
                    (pid, "bounded", base + pid, base + pid + 1.0)
                    for pid in range(102)
                ],
            )

        sessions = telemetry.sessions(days=30)

        assert len(sessions) == 100
        assert [session["pid"] for session in sessions] == list(range(101, 1, -1))
    finally:
        telemetry.close()


def test_telemetry_sessions_returns_empty_when_no_sessions(tmp_path: Path):
    telemetry = TelemetryStore(tmp_path, enabled=True, flush_interval_seconds=0.05)
    try:
        assert telemetry.sessions(days=30) == []
    finally:
        telemetry.close()


def test_preprocessed_query_hit_rate_telemetry(tmp_path: Path):
    telemetry = TelemetryStore(tmp_path, enabled=True, flush_interval_seconds=0.05)
    try:
        telemetry.record_http(
            action="/api/search",
            status_code=200,
            success=True,
            preprocessed_hit=True,
        )
        telemetry.record_http(
            action="/api/search",
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

