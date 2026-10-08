from __future__ import annotations

import sqlite3
import time
from contextlib import closing

from local_ai_hub import telemetry


def test_resolution_deadline_rolls_back_an_already_updated_error(tmp_path, monkeypatch):
    store = telemetry.TelemetryStore(tmp_path / "telemetry", enabled=True)
    try:
        store.record_http(action="/slow", success=False, error_type="internal")
        assert store.flush(1)
        with closing(store._connect()) as con:
            con.execute("CREATE TRIGGER delay_resolution AFTER UPDATE OF success ON events "
                        "BEGIN SELECT resolution_delay(); END")
            con.commit()
        connect = telemetry.connect_sqlite

        def slow_resolution_connection(*args, **kwargs):
            con = connect(*args, **kwargs)
            con.create_function("resolution_delay", 0, lambda: time.sleep(0.08))
            return con

        monkeypatch.setattr(telemetry, "connect_sqlite", slow_resolution_connection)
        result = store.resolve_errors(timeout_seconds=0.03)
        assert result["success"] is False
        assert result["retryable"] is True
        with closing(store._connect()) as con:
            assert con.execute("SELECT COUNT(*) FROM events WHERE success=0").fetchone()[0] == 1
        assert any(not event["success"] for event in store._live_events)
    finally:
        store.close()


def test_resolution_deadline_bounds_a_busy_database(tmp_path):
    store = telemetry.TelemetryStore(tmp_path / "telemetry", enabled=True)
    try:
        store.record_http(action="/slow", success=False, error_type="internal")
        assert store.flush(1)
        with closing(sqlite3.connect(store.path)) as blocker:
            blocker.execute("BEGIN IMMEDIATE")
            started = time.monotonic()
            result = store.resolve_errors(timeout_seconds=0.05)
            elapsed = time.monotonic() - started
            blocker.rollback()
        assert result["success"] is False
        assert result["retryable"] is True
        assert elapsed < 0.5
        with closing(store._connect()) as con:
            assert con.execute("SELECT COUNT(*) FROM events WHERE success=0").fetchone()[0] == 1
    finally:
        store.close()
