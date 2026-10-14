from __future__ import annotations

import sqlite3
from pathlib import Path
import pytest

from local_ai_hub import sqlite_counts


def test_global_row_counts_raises_database_error_when_table_missing(tmp_path: Path):
    db_path = tmp_path / "fresh.sqlite"
    con = sqlite3.connect(db_path)
    try:
        # Table hub_row_counts has not been created at all
        with pytest.raises(sqlite3.DatabaseError, match="derived row counts are not initialized"):
            sqlite_counts.global_row_counts(con, ("users",))
    finally:
        con.close()


def test_is_row_counts_initialized_predicate(tmp_path: Path):
    db_path = tmp_path / "test_init.sqlite"
    con = sqlite3.connect(db_path)
    try:
        con.execute("CREATE TABLE users(id INT)")
        con.execute("CREATE TABLE orders(id INT)")
        con.commit()

        # Before initialization: should return False cleanly without raising
        assert sqlite_counts.is_row_counts_initialized(con, ("users", "orders")) is False

        # Initialize only "users"
        sqlite_counts.initialize_row_counts(con, ("users",))
        assert sqlite_counts.is_row_counts_initialized(con, ("users",)) is True
        # "orders" is not initialized yet
        assert sqlite_counts.is_row_counts_initialized(con, ("users", "orders")) is False

        # Initialize both
        sqlite_counts.initialize_row_counts(con, ("orders",))
        assert sqlite_counts.is_row_counts_initialized(con, ("users", "orders")) is True
    finally:
        con.close()
