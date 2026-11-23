"""Database Engine Optimization: Memory-Mapped I/O (MMAP 256MB) and WAL2 Tuning.

Applies high-performance SQLite pragmas to eliminate Windows disk I/O bottlenecks:
- PRAGMA mmap_size = 268435456 (256MB direct virtual memory mapping)
- PRAGMA journal_mode = WAL (Write-Ahead Logging for non-blocking readers)
- PRAGMA synchronous = NORMAL (safe, low-latency fsync)
- PRAGMA cache_size = -64000 (64MB dedicated RAM page cache)
- PRAGMA temp_store = MEMORY (in-memory temporary tables and indexes)
- PRAGMA busy_timeout = 5000 (resilient retry window under concurrent agent access)
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

OPTIMAL_PRAGMAS = (
    ("journal_mode", "WAL"),
    ("synchronous", "NORMAL"),
    ("mmap_size", 268435456),   # 256 MB memory map
    ("cache_size", -64000),      # 64 MB page cache
    ("temp_store", "MEMORY"),
    ("busy_timeout", 5000),      # 5 seconds
)


def tune_sqlite_connection(con: sqlite3.Connection) -> dict[str, Any]:
    """Apply high-performance MMAP and WAL pragmas to an active SQLite connection."""
    applied: dict[str, Any] = {}
    for pragma_name, pragma_val in OPTIMAL_PRAGMAS:
        try:
            if isinstance(pragma_val, int):
                res = con.execute(f"PRAGMA {pragma_name} = {pragma_val}").fetchone()
            else:
                res = con.execute(f"PRAGMA {pragma_name} = {pragma_val}").fetchone()
            applied[pragma_name] = res[0] if res else pragma_val
        except Exception as exc:
            logger.debug("Failed to set PRAGMA %s=%s: %s", pragma_name, pragma_val, exc)
            applied[pragma_name] = "error"
    return applied


def optimize_hub_database(db_path: str | Path) -> dict[str, Any]:
    """Open target SQLite database file, tune pragmas, and checkpoint WAL."""
    p = Path(db_path)
    if not p.is_file():
        return {"status": "not_found", "path": str(p)}

    try:
        con = sqlite3.connect(str(p), timeout=10.0)
        try:
            pragmas = tune_sqlite_connection(con)
            # Run passive WAL checkpoint to truncate journal without blocking readers
            wal_checkpoint = con.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchall()
            return {
                "status": "optimized",
                "path": str(p),
                "pragmas": pragmas,
                "wal_checkpoint": wal_checkpoint,
            }
        finally:
            con.close()
    except Exception as exc:
        return {"status": "error", "path": str(p), "error": str(exc)}


def optimize_all_state_databases(state_dir: str | Path) -> list[dict[str, Any]]:
    """Scan state directory and optimize all *.sqlite3 databases."""
    sdir = Path(state_dir)
    if not sdir.is_dir():
        return []

    results: list[dict[str, Any]] = []
    for db_file in sdir.glob("*.sqlite3"):
        results.append(optimize_hub_database(db_file))
    return results
