import sqlite3
from pathlib import Path

import pytest

from local_ai_hub.resilience import RecoveryJournal

def test_unsupported_existing_recovery_schema_is_preserved_and_journal_fails_closed(tmp_path: Path) -> None:
    database = tmp_path / "recovery.sqlite3"
    connection = sqlite3.connect(database, isolation_level=None)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute(
            """CREATE TABLE requests (
                request_id TEXT PRIMARY KEY, tenant TEXT NOT NULL, action TEXT NOT NULL,
                state TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
                detail TEXT NOT NULL DEFAULT '', status_code INTEGER NOT NULL DEFAULT 0,
                response_json TEXT NOT NULL DEFAULT ''
            )"""
        )
        connection.execute(
            "INSERT INTO requests(request_id,tenant,action,state,created_at,updated_at,status_code,response_json) "
            "VALUES('kept-request','tenant-a','/api/tasks','complete',1.0,2.0,200,'{\"kept\":true}')"
        )
        wal = Path(f"{database}-wal")
        shm = Path(f"{database}-shm")
        assert wal.exists() and shm.exists()
        assert connection.execute(
            "SELECT tenant,state,status_code,response_json FROM requests WHERE request_id='kept-request'"
        ).fetchone() == ("tenant-a", "complete", 200, '{"kept":true}')
        before = {path.name: path.read_bytes() for path in (database, wal, shm)}

        journal = RecoveryJournal(tmp_path)
        with pytest.raises(sqlite3.DatabaseError, match="incompatible recovery journal schema"):
            journal.begin("new-request", "tenant-a", "/api/tasks", identity="agent-a", payload={})

        assert {path.name: path.read_bytes() for path in (database, wal, shm)} == before
        assert (tmp_path / "recovery.unavailable").exists()
        assert not list(tmp_path.glob("recovery.corrupt-*.sqlite3"))
    finally:
        connection.close()


def test_supported_schema_in_wal_is_verified_without_changing_sidecars(tmp_path: Path) -> None:
    database = tmp_path / "recovery.sqlite3"
    connection = sqlite3.connect(database, isolation_level=None)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute(
            """CREATE TABLE requests (
                request_id TEXT PRIMARY KEY, tenant TEXT NOT NULL, identity TEXT NOT NULL,
                action TEXT NOT NULL, payload_fingerprint TEXT NOT NULL, state TEXT NOT NULL,
                created_at REAL NOT NULL, updated_at REAL NOT NULL, detail TEXT NOT NULL DEFAULT '',
                status_code INTEGER NOT NULL DEFAULT 0, response_json TEXT NOT NULL DEFAULT ''
            )"""
        )
        wal = Path(f"{database}-wal")
        shm = Path(f"{database}-shm")
        assert wal.exists() and shm.exists()
        paths = (database, wal, shm)
        before = {path.name: path.read_bytes() for path in paths}

        journal = RecoveryJournal.__new__(RecoveryJournal)
        journal.path = database
        journal._verify_existing_schema()

        assert {path.name: path.read_bytes() for path in paths} == before
    finally:
        connection.close()


def test_wal_schema_upgrade_completes_nonempty_main_schema_without_changing_sidecars(
    tmp_path: Path,
) -> None:
    database = tmp_path / "recovery.sqlite3"
    connection = sqlite3.connect(database, isolation_level=None)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute(
            """CREATE TABLE requests (
                request_id TEXT PRIMARY KEY, tenant TEXT NOT NULL, action TEXT NOT NULL,
                state TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
                detail TEXT NOT NULL DEFAULT '', status_code INTEGER NOT NULL DEFAULT 0,
                response_json TEXT NOT NULL DEFAULT ''
            )"""
        )
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        migration = "ALTER" + " TABLE requests ADD COLUMN "
        connection.execute(migration + "identity TEXT NOT NULL DEFAULT ''")
        connection.execute(
            migration + "payload_fingerprint TEXT NOT NULL DEFAULT ''"
        )

        wal = Path(f"{database}-wal")
        shm = Path(f"{database}-shm")
        assert wal.exists() and shm.exists() and wal.stat().st_size > 0
        paths = (database, wal, shm)
        before = {path.name: path.read_bytes() for path in paths}

        journal = RecoveryJournal.__new__(RecoveryJournal)
        journal.path = database
        journal._verify_existing_schema()

        assert {path.name: path.read_bytes() for path in paths} == before
        assert not list(tmp_path.glob(".recovery-schema-*"))
    finally:
        connection.close()
