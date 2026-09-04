from __future__ import annotations

import sqlite3
from local_ai_hub.sqlite_support import initialize_wal, optimize_db


def test_optimize_db_basic(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    con = sqlite3.connect(db_path)
    initialize_wal(con)
    con.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
    con.executemany("INSERT INTO users (name) VALUES (?)", [(f"user_{i}",) for i in range(1000)])
    con.commit()
    con.close()

    # Verify WAL file exists
    wal_path = tmp_path / "test.sqlite3-wal"

    # Optimize DB with WAL checkpoint truncate and vacuum
    res = optimize_db(db_path, wal_checkpoint=True, vacuum=True)
    assert res["success"] is True
    assert "wal_checkpoint" in res
    assert res["wal_checkpoint"]["busy"] == 0
    assert "initial_size" in res
    assert "final_size" in res


def test_optimize_db_nonexistent_file(tmp_path):
    db_path = tmp_path / "nonexistent.sqlite3"
    res = optimize_db(db_path)
    assert res["success"] is False
    assert res["error"] == "file_not_found"
