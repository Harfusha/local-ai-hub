"""Exact global counts for large derived indexes, maintained in the writer transaction."""
from __future__ import annotations

import re
import sqlite3


def initialize_row_counts(con: sqlite3.Connection, tables: tuple[str, ...]) -> None:
    """Backfill once; INSERT/DELETE triggers also cover REPLACE with recursive triggers.

    Every writer of these derived stores must enable recursive_triggers, including
    connections opened after initialization. The savepoint makes first backfill and
    trigger installation atomic without committing a caller's transaction.
    """
    if any(not re.fullmatch(r"[a-z][a-z0-9_]*", table) for table in tables):
        raise ValueError("invalid count table name")
    con.execute("PRAGMA recursive_triggers=ON")
    con.execute("SAVEPOINT hub_row_counts")
    try:
        con.execute("CREATE TABLE IF NOT EXISTS hub_row_counts ("
                    "table_name TEXT PRIMARY KEY, row_count INTEGER NOT NULL CHECK(row_count>=0))")
        for table in tables:
            # DDL takes the writer lock before the backfill: concurrent mutations
            # cannot fall between the snapshot and trigger installation.
            con.execute(f"CREATE TRIGGER IF NOT EXISTS hub_count_{table}_insert AFTER INSERT ON {table} "
                        f"BEGIN UPDATE hub_row_counts SET row_count=row_count+1 WHERE table_name='{table}'; END")
            con.execute(f"CREATE TRIGGER IF NOT EXISTS hub_count_{table}_delete AFTER DELETE ON {table} "
                        f"BEGIN UPDATE hub_row_counts SET row_count=row_count-1 WHERE table_name='{table}'; END")
            if con.execute("SELECT 1 FROM hub_row_counts WHERE table_name=?", (table,)).fetchone() is None:
                con.execute(f"INSERT INTO hub_row_counts SELECT ?, COUNT(*) FROM {table}", (table,))
        con.execute("RELEASE hub_row_counts")
    except BaseException:
        con.execute("ROLLBACK TO hub_row_counts")
        con.execute("RELEASE hub_row_counts")
        raise


def global_row_counts(con: sqlite3.Connection, tables: tuple[str, ...]) -> dict[str, int]:
    counts = {str(row[0]): int(row[1]) for row in con.execute("SELECT table_name,row_count FROM hub_row_counts")}
    if any(table not in counts for table in tables):
        raise sqlite3.DatabaseError("derived row counts are not initialized")
    return {table: counts[table] for table in tables}
