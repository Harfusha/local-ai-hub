from pathlib import Path
import sqlite3
import pytest

from local_ai_hub.sqlite_support import connect_sqlite, is_busy_error

def test_connect_sqlite_basic(tmp_path: Path):
    db_path = tmp_path / "test_basic.sqlite3"
    con = connect_sqlite(db_path, timeout_seconds=2.5)
    try:
        busy = con.execute("PRAGMA busy_timeout").fetchone()[0]
        assert busy == 2500
        fk = con.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk == 1
    finally:
        con.close()

def test_connect_sqlite_wal(tmp_path: Path):
    db_path = tmp_path / "test_wal.sqlite3"
    con = connect_sqlite(db_path, wal=True)
    try:
        mode = con.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"
    finally:
        con.close()

def test_connect_sqlite_read_only(tmp_path: Path):
    db_path = tmp_path / "test_ro.sqlite3"
    init_con = connect_sqlite(db_path, wal=True)
    try:
        init_con.execute("CREATE TABLE t (id INT)")
        init_con.commit()
    finally:
        init_con.close()

    ro_con = connect_sqlite(db_path, read_only=True)
    try:
        query_only = ro_con.execute("PRAGMA query_only").fetchone()[0]
        assert query_only == 1
        with pytest.raises(sqlite3.OperationalError):
            ro_con.execute("INSERT INTO t VALUES (1)")
    finally:
        ro_con.close()

def test_connect_sqlite_memory():
    con = connect_sqlite(":memory:", timeout_seconds=1.0)
    try:
        busy = con.execute("PRAGMA busy_timeout").fetchone()[0]
        assert busy == 1000
        con.execute("CREATE TABLE m (x INT)")
    finally:
        con.close()

def test_connect_sqlite_null_byte_rejected():
    with pytest.raises(ValueError, match="embedded null byte"):
        connect_sqlite("db\x00bad.sqlite3")
