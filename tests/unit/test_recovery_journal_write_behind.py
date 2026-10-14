from __future__ import annotations

import sqlite3
import threading
from contextlib import closing
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from local_ai_hub import http_server
from local_ai_hub.resilience import RecoveryJournal


def _claimed(journal: RecoveryJournal, request_id: str) -> None:
    result = journal.begin(
        request_id,
        "tenant",
        "/api/mutate",
        identity="agent-a",
        payload={"value": request_id},
    )
    assert result["claimed"] is True


def test_http_completion_is_sent_while_sqlite_journal_write_is_blocked(tmp_path: Path, monkeypatch: Any) -> None:
    journal = RecoveryJournal(tmp_path / "state")
    _claimed(journal, "request-1")
    write_entered = threading.Event()
    release_write = threading.Event()
    response_sent = threading.Event()
    original_connect = journal._connect

    class BlockedConnection:
        def __init__(self, connection: sqlite3.Connection):
            self.connection = connection

        def __enter__(self) -> "BlockedConnection":
            return self

        def __exit__(self, *args: object) -> None:
            self.connection.close()

        def executemany(self, sql: str, parameters: list[tuple[Any, ...]]):
            if sql.lstrip().upper().startswith("UPDATE REQUESTS SET STATE"):
                write_entered.set()
                assert release_write.wait(3)
            return self.connection.executemany(sql, parameters)

        def __getattr__(self, name: str) -> Any:
            return getattr(self.connection, name)

    monkeypatch.setattr(journal, "_connect", lambda: BlockedConnection(original_connect()))
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(recovery=journal, config={}))

    class ResponseWriter(BytesIO):
        def write(self, data: bytes) -> int:
            result = super().write(data)
            response_sent.set()
            return result

    handler = http_server.Handler.__new__(http_server.Handler)
    handler.headers = {}
    handler.path = "/api/mutate"
    handler._request_path = "/api/mutate"
    handler._journal_request_id = "request-1"
    handler._journal_finished = False
    handler._debug_trace_finished = True
    handler._telemetry_finished = True
    handler.close_connection = False
    handler.wfile = ResponseWriter()
    handler._finish_debug_trace = lambda *args, **kwargs: None
    handler._close_trace_context = lambda: None
    handler._common_headers = lambda: None
    handler.send_response = lambda status: None
    handler.send_header = lambda *args: None
    handler.end_headers = lambda: None

    caller = threading.Thread(target=lambda: handler._send(200, {"success": True}))
    caller.start()
    try:
        assert write_entered.wait(2)
        assert response_sent.wait(2), "HTTP response waited for the SQLite write"
    finally:
        release_write.set()
        caller.join(3)
        journal.close()
    assert not caller.is_alive()


def test_completion_batch_commits_multiple_updates_in_one_transaction(tmp_path: Path, monkeypatch: Any) -> None:
    journal = RecoveryJournal(tmp_path / "state")
    _claimed(journal, "request-1")
    _claimed(journal, "request-2")
    batch_committed = threading.Event()
    original_connect = journal._connect

    class TracedConnection:
        def __init__(self, connection: sqlite3.Connection):
            self.connection = connection
            self.updates = 0
            self.in_transaction = False

        def __enter__(self) -> "TracedConnection":
            return self

        def __exit__(self, *args: object) -> None:
            self.connection.close()

        def execute(self, sql: str, parameters: tuple[Any, ...] = ()):
            if sql.strip().upper() == "BEGIN IMMEDIATE":
                self.in_transaction = True
            return self.connection.execute(sql, parameters)

        def executemany(self, sql: str, parameters: list[tuple[Any, ...]]):
            rows = list(parameters)
            if sql.lstrip().upper().startswith("UPDATE REQUESTS SET STATE"):
                self.updates += len(rows)
            return self.connection.executemany(sql, rows)

        def commit(self) -> None:
            self.connection.commit()
            if self.in_transaction and self.updates >= 2:
                batch_committed.set()

        def __getattr__(self, name: str) -> Any:
            return getattr(self.connection, name)

    monkeypatch.setattr(journal, "_connect", lambda: TracedConnection(original_connect()))
    journal.finish("request-1", True, response={"id": 1})
    journal.finish("request-2", False, status_code=500, response={"id": 2})
    try:
        assert batch_committed.wait(3), "worker did not commit both completions together"
    finally:
        journal.close()


def test_saturated_queue_keeps_http_completion_nonblocking_and_fails_closed(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    journal = RecoveryJournal(tmp_path / "state")
    journal._write_queue_capacity = 1
    for request_id in ("request-1", "request-2", "request-3"):
        _claimed(journal, request_id)
    write_entered = threading.Event()
    release_write = threading.Event()
    third_returned = threading.Event()
    original_connect = journal._connect

    class BlockedConnection:
        def __init__(self, connection: sqlite3.Connection):
            self.connection = connection

        def __enter__(self) -> "BlockedConnection":
            return self

        def __exit__(self, *args: object) -> None:
            self.connection.close()

        def executemany(self, sql: str, parameters: list[tuple[Any, ...]]):
            if sql.lstrip().upper().startswith("UPDATE REQUESTS SET STATE"):
                write_entered.set()
                assert release_write.wait(3)
            return self.connection.executemany(sql, parameters)

        def __getattr__(self, name: str) -> Any:
            return getattr(self.connection, name)

    def finish_third() -> None:
        journal.finish("request-3", True, response={"id": 3})
        third_returned.set()

    caller = threading.Thread(target=finish_third)
    monkeypatch.setattr(journal, "_connect", lambda: BlockedConnection(original_connect()))
    journal.finish("request-1", True, response={"id": 1})
    assert write_entered.wait(2)
    journal.finish("request-2", True, response={"id": 2})

    caller.start()
    try:
        assert third_returned.wait(2), "HTTP completion waited for a blocked journal batch"
        assert not release_write.is_set()
        assert "request-3" not in journal._pending_completions
        assert journal._journal_unavailable is True
        with pytest.raises(sqlite3.DatabaseError, match="refusing mutation dispatch"):
            _claimed(journal, "request-4")
    finally:
        release_write.set()
        caller.join(3)
        journal.close()
    assert not caller.is_alive()
    reopened = RecoveryJournal(tmp_path / "state")
    try:
        replay = reopened.begin(
            "request-3",
            "tenant",
            "/api/mutate",
            identity="agent-a",
            payload={"value": "request-3"},
        )
        assert replay["claimed"] is False
        assert replay["state"] == "abandoned"
        assert replay["outcome_unknown"] is True
    finally:
        reopened.close()


def test_pending_completion_replays_immediately_and_close_flushes(tmp_path: Path) -> None:
    journal = RecoveryJournal(tmp_path / "state")
    _claimed(journal, "request-1")
    response = {"success": True, "value": "saved"}
    journal.finish("request-1", True, response=response)

    replay = journal.begin(
        "request-1",
        "tenant",
        "/api/mutate",
        identity="agent-a",
        payload={"value": "request-1"},
    )
    conflict = journal.begin(
        "request-1",
        "tenant",
        "/api/mutate",
        identity="agent-b",
        payload={"value": "request-1"},
    )
    journal.close()
    journal.close()

    assert replay["state"] == "done"
    assert replay["response"] == response
    assert replay["claimed"] is False
    assert conflict["state"] == "conflict"
    with closing(sqlite3.connect(journal.path)) as connection:
        row = connection.execute(
            "SELECT state,response_json FROM requests WHERE request_id=?", ("request-1",)
        ).fetchone()
    assert row is not None and row[0] == "done"
    assert journal._decode_response(str(row[1])) == response
    assert journal._writer_thread is None


def test_background_write_failure_preserves_unknown_boundary_and_blocks_new_claims(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    journal = RecoveryJournal(tmp_path / "state")
    _claimed(journal, "request-1")
    write_failed = threading.Event()
    original_connect = journal._connect

    class FailingConnection:
        def __init__(self, connection: sqlite3.Connection):
            self.connection = connection

        def __enter__(self) -> "FailingConnection":
            return self

        def __exit__(self, *args: object) -> None:
            self.connection.close()

        def executemany(self, sql: str, parameters: list[tuple[Any, ...]]):
            write_failed.set()
            raise sqlite3.OperationalError("simulated journal disk failure")

        def __getattr__(self, name: str) -> Any:
            return getattr(self.connection, name)

    monkeypatch.setattr(journal, "_connect", lambda: FailingConnection(original_connect()))
    journal.finish("request-1", True, response={"success": True})
    try:
        assert write_failed.wait(2)
        with journal._changed:
            assert journal._changed.wait_for(lambda: journal._journal_unavailable, timeout=2)
        with pytest.raises(sqlite3.DatabaseError, match="refusing mutation dispatch"):
            _claimed(journal, "request-2")
        pending = journal.lookup(
            "request-1",
            "tenant",
            "/api/mutate",
            identity="agent-a",
            payload_fingerprint=journal.fingerprint_payload({"value": "request-1"}),
        )
        assert pending is not None and pending["state"] == "done"
        assert pending["response"] == {"success": True}
    finally:
        journal.close()
