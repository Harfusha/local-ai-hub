"""Deferred F36 error-reporting regressions; SQLite is in-memory only."""

import sqlite3
import threading
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import Mock

from local_ai_hub import preprocess as preprocess_module
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


def test_cpu_worker_backs_off_if_error_state_cannot_be_written(monkeypatch):
    monkeypatch.setattr(preprocess_module, "set_current_thread_priority", Mock())
    original_error = RuntimeError("synthetic preprocessing failure")
    row = {"root": "fixture", "phase": "files", "stats_json": "{}"}
    stop = threading.Event()
    wait = Mock(side_effect=lambda _delay: stop.set())
    processor = SimpleNamespace(
        cpu_priority="normal",
        cfg={"startup_delay_seconds": 0, "poll_seconds": 0.3},
        _stats_lock=threading.Lock(),
        _stats={"loops": 0, "errors": 0},
        _stop=SimpleNamespace(is_set=stop.is_set, wait=wait),
        _paused=threading.Event(),
        _background_work_allowed=lambda: True,
        cpu_runs_during_foreground=True,
        _is_locked_error=lambda _exc: False,
        _next_cpu_project=Mock(side_effect=[row, AssertionError("project selected again before waiting")]),
        _run_project_step=Mock(side_effect=original_error),
        _project_row=Mock(return_value=row),
        _set_project=Mock(side_effect=sqlite3.OperationalError("database is locked")),
        _record_failure_telemetry=Mock(),
    )

    ProjectPreprocessor._cpu_loop(processor)

    wait.assert_called_once_with(0.3)
    processor._next_cpu_project.assert_called_once_with(rebalance=True)
    processor._record_failure_telemetry.assert_called_once_with(row, original_error)
    assert processor._stats["errors"] == 1
