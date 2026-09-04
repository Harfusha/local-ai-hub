from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, TypeVar

T = TypeVar("T")


def is_busy_error(exc: BaseException) -> bool:
    """Return True only for transient SQLite lock/busy failures.

    Busy databases are healthy databases. Callers must not route these errors through
    corruption recovery/quarantine code because another process may simply own the WAL
    writer for a few milliseconds.
    """
    if not isinstance(exc, sqlite3.OperationalError):
        return False
    text = str(exc).lower()
    return "locked" in text or "busy" in text


def connect_sqlite(
    path: Path,
    *,
    timeout_seconds: float = 0.75,
    isolation_level: str | None = "DEFERRED",
    row_factory: Any | None = None,
) -> sqlite3.Connection:
    """Open a short-lived derived-state connection with bounded lock waits.

    WAL is deliberately *not* selected here. ``PRAGMA journal_mode=WAL`` can itself
    require an exclusive lock, so schemas enable WAL once during initialization and
    hot-path connections only apply non-exclusive pragmas.
    """
    timeout = max(0.01, float(timeout_seconds))
    con = sqlite3.connect(path, timeout=timeout, isolation_level=isolation_level)
    if row_factory is not None:
        con.row_factory = row_factory
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute(f"PRAGMA busy_timeout={max(1, int(timeout * 1000))}")
    con.execute("PRAGMA temp_store=MEMORY")
    con.execute("PRAGMA mmap_size=268435456")
    con.execute("PRAGMA cache_size=-16000")
    return con


def initialize_wal(con: sqlite3.Connection) -> None:
    """Enable WAL during cold initialization, never on every hot-path connection."""
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")


def retry_busy(
    operation: Callable[[], T],
    *,
    retries: int = 3,
    base_delay_seconds: float = 0.015,
) -> T:
    """Retry only transient lock/busy errors with a short exponential backoff."""
    attempts = max(1, int(retries))
    delay = max(0.0, float(base_delay_seconds))
    for attempt in range(attempts):
        try:
            return operation()
        except Exception as exc:
            if not is_busy_error(exc) or attempt + 1 >= attempts:
                raise
            if delay:
                time.sleep(min(0.20, delay * (2 ** attempt)))
    raise AssertionError("unreachable")


def optimize_db(
    path: Path,
    *,
    wal_checkpoint: bool = True,
    vacuum: bool = False,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    """Perform bounded maintenance on an SQLite database (WAL checkpoint truncate, pragma optimize, vacuum)."""
    if not path.exists():
        return {"success": False, "error": "file_not_found", "path": str(path)}

    timeout = max(0.1, float(timeout_seconds))
    result: dict[str, Any] = {
        "success": True,
        "path": str(path),
        "initial_size": path.stat().st_size if path.exists() else 0,
    }

    try:
        con = sqlite3.connect(path, timeout=timeout)
        try:
            con.execute(f"PRAGMA busy_timeout={int(timeout * 1000)}")
            if wal_checkpoint:
                row = con.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                if row:
                    result["wal_checkpoint"] = {
                        "busy": row[0],
                        "log_pages": row[1],
                        "checkpointed_pages": row[2],
                    }
            con.execute("PRAGMA optimize")
            if vacuum:
                con.execute("VACUUM")
        finally:
            con.close()
        result["final_size"] = path.stat().st_size if path.exists() else 0
        result["freed_bytes"] = max(0, result["initial_size"] - result["final_size"])
        return result
    except Exception as exc:
        return {"success": False, "error": str(exc), "path": str(path)}

