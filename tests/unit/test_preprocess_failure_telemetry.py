"""Deferred F36 error-reporting regressions; SQLite is in-memory only."""

import hashlib
import sqlite3
import threading
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import Mock
import pytest

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


def test_terminal_preprocessing_failure_is_not_reported_retryable():
    class TerminalError(RuntimeError):
        retryable = False

    telemetry = Mock()
    processor = _preprocessor(telemetry)
    error = TerminalError("embedding space needs an operator rebuild")

    ProjectPreprocessor._record_failure_telemetry(processor, {"phase": "rag"}, error)

    telemetry.record_error.assert_called_once_with(
        "preprocess", "rag", error, retryable=False, recovered=False,
    )


def test_failure_telemetry_preserves_structured_error_code():
    telemetry = Mock()
    processor = _preprocessor(telemetry)
    error = RuntimeError("safe message intentionally omitted")
    error.error_code = "gpu_reserved"

    ProjectPreprocessor._record_failure_telemetry(processor, {"phase": "rag"}, error)

    telemetry.record_error.assert_called_once_with(
        "preprocess", "rag", error, retryable=True, recovered=False,
        error_code_override="gpu_reserved",
    )


def test_rag_step_preserves_structured_error_code_from_indexer(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "source.py").write_text("value = 1\n", encoding="utf-8")
    content_hash = hashlib.sha256(b"value = 1\n").hexdigest()

    class FailingRAG:
        def paths_needing_reindex(self, *_args, **_kwargs):
            return []

        def index_paths_step(self, *_args, **_kwargs):
            return {
                "success": False,
                "error": "GPU admission is unavailable",
                "error_code": "gpu_reserved",
                "retryable": True,
            }

    pre = ProjectPreprocessor.__new__(ProjectPreprocessor)
    pre.cfg = {"rag_files_per_step": 1}
    pre.rag = FailingRAG()
    pre.deterministic = None
    pre._db_lock = threading.RLock()
    pre._stats_lock = threading.RLock()
    pre._stats = {"rag_steps": 0}
    pre._yield = lambda: False
    pre._root = lambda value: str(value)
    def connect():
        connection = sqlite3.connect(tmp_path / "preprocess.sqlite3")
        connection.row_factory = sqlite3.Row
        return connection

    pre._connect = connect
    with closing(pre._connect()) as connection:
        connection.execute(
            "CREATE TABLE file_refs(root TEXT, path TEXT, content_hash TEXT, size INTEGER, generation INTEGER, updated_at REAL, needs_hash INTEGER DEFAULT 0, rag_hash TEXT, last_accessed_at REAL DEFAULT 0, centrality_score REAL DEFAULT 0)"
        )
        connection.execute(
            "INSERT INTO file_refs(root,path,content_hash,size,generation,updated_at,needs_hash) VALUES(?,?,?,?,?,?,0)",
            (str(root), "source.py", content_hash, 11, 0, 1.0),
        )
        connection.commit()

    with pytest.raises(preprocess_module._RetryablePreprocessingError) as raised:
        pre._step_rag({"root": str(root), "workspace": str(root)})

    assert raised.value.error_code == "gpu_reserved"
    assert raised.value.retryable is True


def test_cpu_worker_pauses_terminal_preprocessing_failure(monkeypatch):
    monkeypatch.setattr(preprocess_module, "set_current_thread_priority", Mock())
    class TerminalError(RuntimeError):
        retryable = False

    error = TerminalError("embedding space needs an operator rebuild")
    row = {"root": "fixture", "phase": "rag", "stats_json": "{}"}
    stop = threading.Event()
    wakeup_wait = Mock(side_effect=lambda _delay: stop.set())
    processor = SimpleNamespace(
        cpu_priority="normal",
        cfg={"startup_delay_seconds": 0, "poll_seconds": 0.3},
        _stats_lock=threading.Lock(),
        _stats={"loops": 0, "errors": 0},
        _stop=SimpleNamespace(is_set=stop.is_set, wait=Mock()),
        _paused=threading.Event(),
        _background_work_allowed=lambda: True,
        cpu_runs_during_foreground=True,
        _is_locked_error=lambda _exc: False,
        _next_cpu_project=Mock(side_effect=[row, None]),
        _run_project_step=Mock(side_effect=error),
        _project_row=Mock(return_value=row),
        _set_project=Mock(),
        _record_failure_telemetry=Mock(),
        _run_idle_database_maintenance=Mock(),
        _cpu_wakeup=SimpleNamespace(wait=wakeup_wait, clear=Mock()),
    )

    ProjectPreprocessor._cpu_loop(processor)

    processor._set_project.assert_called_once()
    saved = processor._set_project.call_args.kwargs
    assert saved["status"] == "error"
    assert saved["paused"] is True
    assert saved["retry_after"] == 0
    assert processor._next_cpu_project.call_count == 2
    processor._run_project_step.assert_called_once_with(row)
    processor._record_failure_telemetry.assert_called_once_with(row, error)


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
