"""Deferred F36 error-reporting regressions; SQLite is in-memory only."""

import sqlite3
import threading
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import Mock

from local_ai_hub.preprocess import ProjectPreprocessor


def _preprocessor(telemetry):
    return SimpleNamespace(telemetry=telemetry, _stats_lock=threading.Lock(), _stats={"lost_error_count": 0})


def test_sqlite_row_phase_reaches_callback_and_failed_project_is_not_recovered():
    telemetry = Mock()
    error = FileNotFoundError("synthetic missing file")
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute("SELECT 'files' AS phase").fetchone()
    processor = _preprocessor(telemetry)
    ProjectPreprocessor._record_failure_telemetry(processor, row, error)
    telemetry.record_error.assert_called_once_with("preprocess", "files", error, retryable=True, recovered=False)
    assert processor._stats["lost_error_count"] == 0


def test_callback_failure_counted_without_leaking_exception_message(caplog):
    telemetry = Mock()
    telemetry.record_error.side_effect = AttributeError("private-path-or-secret")
    processor = _preprocessor(telemetry)
    ProjectPreprocessor._record_failure_telemetry(processor, {"phase": "files"}, FileNotFoundError())
    assert processor._stats["lost_error_count"] == 1
    assert "phase=files type=AttributeError fingerprint=" in caplog.text
    assert "private-path-or-secret" not in caplog.text


def test_absent_telemetry_does_not_claim_lost_callback():
    processor = _preprocessor(None)
    ProjectPreprocessor._record_failure_telemetry(processor, None, RuntimeError())
    assert processor._stats["lost_error_count"] == 0
