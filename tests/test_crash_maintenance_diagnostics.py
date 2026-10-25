from __future__ import annotations

import io
import logging
import signal
import sqlite3
import threading
import time
from contextlib import closing
from types import SimpleNamespace

import pytest

from local_ai_hub import http_server, preprocess, sqlite_support, supervisor


def idle_preprocessor(tmp_path):
    instance = object.__new__(preprocess.ProjectPreprocessor)
    instance.db_path = tmp_path / "preprocess.sqlite3"
    instance.state_dir = tmp_path
    instance.cfg = {}
    instance._last_db_maintenance = 0
    instance._db_lock = threading.RLock()
    instance._stats_lock = threading.Lock()
    instance._stats = {}
    instance._yield = lambda: False
    instance._connect = lambda: sqlite3.connect(instance.db_path)
    instance.code_index = instance.deterministic = instance.rag = None
    instance.cleanup_deleted_projects = lambda: None
    instance.cleanup_orphaned_indexes = lambda: None
    with closing(sqlite3.connect(instance.db_path)) as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE content_cards(card_key TEXT PRIMARY KEY, accessed_at REAL)")
        con.execute("CREATE TABLE file_refs(card_key TEXT)")
        old = time.time() - 40 * 86400
        con.executemany("INSERT INTO content_cards VALUES (?, ?)", [("orphan", old), ("used", old)])
        con.execute("INSERT INTO file_refs VALUES ('used')")
        con.commit()
    return instance


def test_idle_maintenance_commits_pruning_before_checkpoint(tmp_path, caplog):
    instance = idle_preprocessor(tmp_path)
    with caplog.at_level(logging.WARNING):
        assert instance._run_idle_database_maintenance()
    with closing(sqlite3.connect(instance.db_path)) as con:
        assert con.execute("SELECT card_key FROM content_cards").fetchall() == [("used",)]
    assert "maintenance skipped" not in caplog.text
    assert instance._stats["db_maintenance_runs"] == 1


def test_idle_maintenance_logs_database_and_sqlite_message(tmp_path, caplog):
    instance = idle_preprocessor(tmp_path)

    def locked():
        raise sqlite3.OperationalError("database is locked")

    instance._connect = locked
    with caplog.at_level(logging.WARNING):
        assert instance._run_idle_database_maintenance()
    assert str(instance.db_path) in caplog.text
    assert "database is locked" in caplog.text
    assert "OperationalError" in caplog.text


def test_checkpoint_failure_does_not_roll_back_committed_pruning(tmp_path, caplog):
    instance = idle_preprocessor(tmp_path)

    class FailingCheckpoint:
        def __init__(self):
            self.connection = sqlite3.connect(instance.db_path)

        def execute(self, statement, *args):
            if statement == "PRAGMA wal_checkpoint(PASSIVE)":
                raise sqlite3.OperationalError("checkpoint failed")
            return self.connection.execute(statement, *args)

        def commit(self):
            self.connection.commit()

        def close(self):
            self.connection.close()

    instance._connect = FailingCheckpoint
    with caplog.at_level(logging.WARNING):
        assert instance._run_idle_database_maintenance()
    with closing(sqlite3.connect(instance.db_path)) as con:
        assert con.execute("SELECT card_key FROM content_cards").fetchall() == [("used",)]
    assert "checkpoint failed" in caplog.text


def test_vacuum_setup_retains_database_and_failure_detail(tmp_path, monkeypatch):
    database = tmp_path / "derived.sqlite3"

    def locked(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(sqlite_support.sqlite3, "connect", locked)
    result = sqlite_support.ensure_incremental_vacuum(database)
    assert result["success"] is False
    assert result["error"] == "OperationalError"
    assert result["error_message"] == "database is locked"
    assert result["path"] == str(database)


def test_deleted_project_vacuum_logs_path_and_failure_detail(tmp_path, monkeypatch, caplog):
    instance = idle_preprocessor(tmp_path)
    monkeypatch.setattr(preprocess, "ensure_incremental_vacuum", lambda path: {
        "success": False, "error": "OperationalError", "error_message": "database is locked",
    })
    with caplog.at_level(logging.WARNING):
        instance._vacuum_derived_databases()
    assert str(instance.db_path) in caplog.text
    assert "database is locked" in caplog.text


def test_supervised_worker_enables_native_crash_tracebacks(tmp_path, monkeypatch):
    instance = object.__new__(supervisor.Supervisor)
    instance.state_dir = tmp_path
    instance.config_path = str(tmp_path / "config.toml")
    monkeypatch.setattr(supervisor, "sys", SimpleNamespace(platform="linux", executable="python"))
    monkeypatch.setattr(supervisor, "hidden_run_kwargs", lambda **kwargs: {})
    commands = []
    monkeypatch.setattr(supervisor.subprocess, "Popen", lambda command, **kwargs: commands.append(command))
    instance.spawn_hub()
    command = commands[0]
    assert any(command[i:i + 2] == ["-X", "faulthandler"] for i in range(len(command)))


@pytest.mark.parametrize("exit_code", [-1073741819, 3221225477])
def test_reaped_child_logs_native_exit_before_identity_is_cleared(tmp_path, monkeypatch, exit_code):
    instance = object.__new__(supervisor.Supervisor)
    instance.state_dir = tmp_path
    instance.hub_owner_path = tmp_path / "hub.owner.json"
    instance.hub_pid_path = tmp_path / "hub.pid"
    instance.child_pidfd = None
    instance.child_owner = {"pid": 123}
    instance.child = SimpleNamespace(pid=123, poll=lambda: exit_code, wait=lambda **kwargs: exit_code)
    messages = []
    instance.log = messages.append
    instance._remove_stale_owner = lambda *args: None
    monkeypatch.setattr(supervisor, "close_pidfd", lambda handle: None)
    assert instance.terminate_child()
    assert instance.child is None
    assert any("pid=123" in text and f"exit_code={exit_code}" in text
               and "0xc0000005" in text and "already_exited" in text for text in messages)


def test_native_stderr_trace_is_bound_to_child_pid(tmp_path):
    instance = object.__new__(supervisor.Supervisor)
    instance.state_dir = tmp_path
    instance._log_lock = threading.Lock()
    stream = io.BytesIO(b"Fatal Python error: access violation\n  native_parser.py, line 12\n")
    instance._drain_hub_stderr(stream, 123)
    text = (tmp_path / "logs" / "hub_stderr.log").read_text(encoding="utf-8")
    assert "pid=123" in text
    assert "Fatal Python error: access violation" in text
    assert "native_parser.py, line 12" in text


def test_supervisor_signal_records_why_it_is_stopping():
    instance = object.__new__(supervisor.Supervisor)
    instance.stopping = False
    instance._signal_wake_writer = None
    messages = []
    instance.log = messages.append
    instance._handle_signal(signal.SIGTERM, None)
    assert instance.stopping
    assert str(int(signal.SIGTERM)) in instance._stop_reason
    assert messages == []  # Signal handlers must not acquire the log lock.


def supervisor_loop(tmp_path, monkeypatch, *, healthy=False):
    instance = object.__new__(supervisor.Supervisor)
    instance.cfg = {"manage_ollama": True}
    instance.config = {"server": {"port": 11435}}
    instance.state_dir = tmp_path
    instance.disabled_path = tmp_path / "service.disabled"
    instance.pid_path = tmp_path / "supervisor.pid"
    instance.owner_path = tmp_path / "supervisor.owner.json"
    instance.acquire = lambda: True
    instance.release_lock = lambda: None
    instance.terminate_child = lambda: True
    instance.write_status = lambda *args, **kwargs: None
    instance.hub_online = lambda: healthy
    instance.child = SimpleNamespace(pid=123) if healthy else None
    instance.child_ready = healthy
    instance.stopping = False
    instance._stop_event = threading.Event()
    instance._signal_wake_reader = None
    instance._signal_wake_writer = None
    instance._signal_wake_thread = None
    messages = []
    instance.log = messages.append
    monkeypatch.setattr(supervisor, "process_owner_record", lambda *args: None)
    monkeypatch.setattr(supervisor, "find_listening_pid", lambda *args: None)
    monkeypatch.setattr(supervisor.signal, "signal", lambda *args: None)
    monkeypatch.setattr(supervisor.time, "sleep", lambda *args: None)
    return instance, messages


def test_unhandled_supervisor_exception_keeps_traceback_and_stop_reason(tmp_path, monkeypatch):
    instance, messages = supervisor_loop(tmp_path, monkeypatch)

    def failed_runtime():
        raise RuntimeError("backend failed")

    instance.runtime = SimpleNamespace(ensure_running=failed_runtime)
    with pytest.raises(RuntimeError, match="backend failed"):
        instance.run()
    assert any("Traceback" in message and "failed_runtime" in message for message in messages)
    assert any("supervisor stopped pid=" in message and "reason=unhandled_exception" in message
               for message in messages)


def test_supervisor_shutdown_log_preserves_received_signal(tmp_path, monkeypatch):
    instance, messages = supervisor_loop(tmp_path, monkeypatch, healthy=True)

    def stop_runtime():
        instance._handle_signal(signal.SIGTERM)
        return True

    instance.runtime = SimpleNamespace(ensure_running=stop_runtime)
    assert instance.run() == 0
    assert any(f"reason=signal={int(signal.SIGTERM)}" in message for message in messages)


@pytest.mark.parametrize("failure", [RuntimeError, BrokenPipeError])
def test_post_failure_diagnostics_keep_stack_without_request_secrets(monkeypatch, caplog, failure):
    logger = logging.getLogger("test.http_crash_diagnostics")
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(logger=logger))
    monkeypatch.setattr(http_server, "select_http_routes", lambda *args: ("test_route",))
    monkeypatch.setattr(http_server, "select_post_handler", lambda *args: "dispatch_failure")
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *args: None)
    responses = []

    def dispatch_failure(payload):
        raise failure("private-error-message-537")

    handler = SimpleNamespace(
        path="/api/diagnostic-regression?token=private-query-token-537",
        headers={"Content-Type": "application/json"},
        _require_authorized=lambda: True,
        _begin_trace=lambda *args: None,
        _read_json=lambda: {"secret": "private-payload-token-537"},
        _validate_payload=lambda *args: None,
        _claim_recovery=lambda *args: True,
        _finish_debug_trace=lambda *args, **kwargs: None,
        _close_trace_context=lambda: None,
        _send=lambda status, payload: responses.append((status, payload)),
        dispatch_failure=dispatch_failure,
    )
    with caplog.at_level(logging.ERROR, logger=logger.name):
        http_server.Handler.do_POST(handler)
    if failure is BrokenPipeError:
        assert caplog.text == ""
        assert responses == []
    else:
        assert responses[0][0] == 500
        assert responses[0][1]["error"] == "internal server error"
        assert "path=/api/diagnostic-regression" in caplog.text
        assert "RuntimeError" in caplog.text
        assert "dispatch_failure" in caplog.text
        assert "private-" not in caplog.text
        assert "token=" not in caplog.text
