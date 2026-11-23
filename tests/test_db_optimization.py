"""Tests for Memory-Mapped I/O and WAL SQLite tuning."""

import sqlite3
import tempfile
from pathlib import Path

from src.local_ai_hub.db_optimization import (
    optimize_hub_database,
    tune_sqlite_connection,
)


def test_tune_sqlite_connection_pragmas():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = str(Path(tmpdir) / "test_pragmas.sqlite3")
        con = sqlite3.connect(tmp_path)
        try:
            pragmas = tune_sqlite_connection(con)
            assert pragmas.get("journal_mode", "").lower() == "wal"
            assert int(pragmas.get("mmap_size", 0)) >= 0
            assert pragmas.get("synchronous", "").upper() in ("NORMAL", "1")
        finally:
            con.close()


def test_optimize_hub_database():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = Path(tmpdir) / "test.sqlite3"
        con = sqlite3.connect(str(db_file))
        try:
            con.execute("CREATE TABLE test (id INT, val TEXT)")
            con.execute("INSERT INTO test VALUES (1, 'hello')")
            con.commit()
        finally:
            con.close()

        res = optimize_hub_database(db_file)
        assert res["status"] == "optimized"
        assert "pragmas" in res
