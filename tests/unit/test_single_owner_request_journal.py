"""Request-id journal contracts without tenant partitions."""

from __future__ import annotations

import inspect
import sqlite3
from contextlib import closing

import pytest

from local_ai_hub.resilience import RecoveryJournal, _IncompatibleRecoveryJournalSchema


def test_request_journal_api_rejects_retired_partition_arguments() -> None:
    for method_name in ("begin", "lookup", "lookup_metadata", "wait_for", "finish"):
        signature = inspect.signature(getattr(RecoveryJournal, method_name))
        assert "tenant" not in signature.parameters
        assert "identity" not in signature.parameters
        with pytest.raises(TypeError):
            signature.bind_partial(object(), tenant=None, identity="")


def test_request_id_conflicts_on_action_or_payload_and_replays_completion(tmp_path) -> None:
    journal = RecoveryJournal(tmp_path)
    try:
        first = journal.begin("request-1", action="write", payload={"value": 1})
        assert first["claimed"] is True

        duplicate = journal.begin("request-1", action="write", payload={"value": 1})
        assert duplicate["claimed"] is False
        assert duplicate["state"] == "running"

        assert journal.begin("request-1", action="delete", payload={"value": 1})["state"] == "conflict"
        assert journal.begin("request-1", action="write", payload={"value": 2})["state"] == "conflict"

        journal.finish("request-1", True, status_code=200, response={"ok": True})
        journal.close()
        replay = journal.lookup(
            "request-1",
            action="write",
            payload_fingerprint=journal.fingerprint_payload({"value": 1}),
        )
        assert replay is not None
        assert replay["state"] == "done"
        assert replay["response"] == {"ok": True}
    finally:
        journal.close()


def test_legacy_request_schema_is_rejected_read_only(tmp_path) -> None:
    database = tmp_path / "recovery.sqlite3"
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute(
            "CREATE TABLE requests("
            "request_id TEXT PRIMARY KEY, tenant TEXT NOT NULL, identity TEXT NOT NULL DEFAULT '', "
            "action TEXT NOT NULL, payload_fingerprint TEXT NOT NULL DEFAULT '', state TEXT NOT NULL, "
            "created_at REAL NOT NULL, updated_at REAL NOT NULL, detail TEXT NOT NULL DEFAULT '', "
            "status_code INTEGER NOT NULL DEFAULT 0, response_json TEXT NOT NULL DEFAULT '')"
        )
        connection.execute(
            "INSERT INTO requests(request_id,tenant,identity,action,payload_fingerprint,state,created_at,updated_at) "
            "VALUES('request-1','retired','credential','write','fingerprint','running',1,1)"
        )

    journal = RecoveryJournal.__new__(RecoveryJournal)
    journal.path = database
    with pytest.raises(_IncompatibleRecoveryJournalSchema, match="explicit offline conversion required"):
        journal._verify_existing_schema()

    with closing(sqlite3.connect(database)) as connection, connection:
        row = connection.execute(
            "SELECT tenant,identity,state FROM requests WHERE request_id='request-1'"
        ).fetchone()
    assert row == ("retired", "credential", "running")
