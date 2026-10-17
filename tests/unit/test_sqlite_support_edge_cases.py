from __future__ import annotations

import sqlite3
import time
from pathlib import Path
import pytest

from local_ai_hub import sqlite_support


def test_sqlite_support_functions_accept_string_paths(tmp_path: Path) -> None:
    db_path = tmp_path / "str_test.sqlite"
    db_str = str(db_path)

    # connect_sqlite with str
    con = sqlite_support.connect_sqlite(db_str)
    con.execute("CREATE TABLE test (id INT)")
    con.commit()
    con.close()

    # ensure_incremental_vacuum with str
    res1 = sqlite_support.ensure_incremental_vacuum(db_str)
    assert res1["success"] is True

    # incremental_vacuum with str
    res2 = sqlite_support.incremental_vacuum(db_str)
    assert res2["success"] is True

    # optimize_db with str
    res3 = sqlite_support.optimize_db(db_str)
    assert res3["success"] is True

    # wal_checkpoint_truncate with str
    res4 = sqlite_support.wal_checkpoint_truncate(db_str)
    assert res4["success"] is True

    # auto_checkpoint_wal with str
    res5 = sqlite_support.auto_checkpoint_wal(db_str)
    assert res5["success"] is True


def test_wal_checkpoint_truncate_reports_false_when_no_wal(tmp_path: Path) -> None:
    db_path = tmp_path / "nowal.sqlite"
    con = sqlite3.connect(db_path)
    con.execute("CREATE TABLE t (x INT)")
    con.commit()
    con.close()

    res = sqlite_support.wal_checkpoint_truncate(db_path)
    assert res["success"] is True
    assert res["wal_size_before"] == 0
    # Must NOT report truncated: True when no WAL file was present
    assert res["truncated"] is False


def test_auto_checkpoint_wal_returns_not_found_on_missing_db(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.sqlite"
    res = sqlite_support.auto_checkpoint_wal(missing_path)
    assert res["success"] is False
    assert res["error"] == "file_not_found"
    # Ensure missing db was not accidentally created
    assert not missing_path.exists()


def test_clean_quarantined_files_removes_sidecars(tmp_path: Path) -> None:
    corrupt_db = tmp_path / "test.corrupt-12345.sqlite3"
    corrupt_wal = tmp_path / "test.corrupt-12345.sqlite3-wal"
    corrupt_shm = tmp_path / "test.corrupt-12345.sqlite3-shm"

    corrupt_db.write_bytes(b"corrupt")
    corrupt_wal.write_bytes(b"wal data")
    corrupt_shm.write_bytes(b"shm data")

    # Set old mtime to trigger age-based pruning
    old_time = time.time() - 86400 * 10
    for p in (corrupt_db, corrupt_wal, corrupt_shm):
        import os
        os.utime(p, (old_time, old_time))

    res = sqlite_support.clean_quarantined_files(tmp_path, max_age_seconds=86400 * 7)
    assert res["success"] is True
    assert not corrupt_db.exists()
    assert not corrupt_wal.exists()
    assert not corrupt_shm.exists()


def test_validate_durable_schema_detects_object_type_reliably(tmp_path: Path) -> None:
    db_path = tmp_path / "schema_test.sqlite"
    con = sqlite3.connect(db_path)
    con.execute("CREATE TABLE valid_table (id INTEGER PRIMARY KEY, name TEXT)")
    con.commit()

    expected = {"valid_table": (("id", "INTEGER", 0, 1), ("name", "TEXT", 0, 0))}
    # Should validate cleanly without misclassifying object_type
    sqlite_support.validate_durable_schema(con, db_path, expected)
    con.close()
