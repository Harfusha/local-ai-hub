from __future__ import annotations

import random
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
    try:
        if row_factory is not None:
            con.row_factory = row_factory
        con.execute(f"PRAGMA busy_timeout={max(1, int(timeout * 1000))}")
        # SQLite disables foreign-key enforcement per connection by default.
        # All Local AI Hub stores are application-owned, so enabling it here
        # preserves declared cascade/integrity rules consistently on every path.
        con.execute("PRAGMA foreign_keys=ON")
        try:
            con.execute("PRAGMA synchronous=NORMAL")
            con.execute("PRAGMA temp_store=MEMORY")
            con.execute("PRAGMA mmap_size=268435456")
            con.execute("PRAGMA cache_size=-16000")
        except sqlite3.OperationalError as exc:
            if not is_busy_error(exc):
                raise
        return con
    except Exception:
        con.close()
        raise


def initialize_wal(con: sqlite3.Connection) -> None:
    """Enable WAL during cold initialization, never on every hot-path connection."""
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")


def retry_busy(
    operation: Callable[[], T],
    *,
    retries: int = 5,
    base_delay_seconds: float = 0.015,
    max_delay_seconds: float = 2.0,
    jitter: bool = True,
) -> T:
    """Retry only transient lock/busy errors with an exponential backoff and jitter."""
    attempts = max(1, int(retries))
    delay = max(0.0, float(base_delay_seconds))
    for attempt in range(attempts):
        try:
            return operation()
        except Exception as exc:
            if not is_busy_error(exc) or attempt + 1 >= attempts:
                raise
            if delay:
                backoff = min(max_delay_seconds, delay * (2 ** attempt))
                sleep_time = random.uniform(0.5 * backoff, backoff) if jitter else backoff
                time.sleep(sleep_time)
    raise AssertionError("unreachable")


def incremental_vacuum(
    path: Path,
    *,
    pages: int = 100,
    freelist_threshold: int = 50,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    """Perform bounded incremental vacuum and freelist reclamation if freelist pages exceed threshold."""
    if not path.exists():
        return {"success": False, "error": "file_not_found", "path": str(path)}
    timeout = max(0.1, float(timeout_seconds))
    try:
        con = sqlite3.connect(path, timeout=timeout)
        try:
            con.execute(f"PRAGMA busy_timeout={int(timeout * 1000)}")
            freelist_row = con.execute("PRAGMA freelist_count").fetchone()
            freelist_count = int(freelist_row[0]) if freelist_row else 0
            auto_vac_row = con.execute("PRAGMA auto_vacuum").fetchone()
            auto_vac = int(auto_vac_row[0]) if auto_vac_row else 0
            pages_freed = 0
            if freelist_count >= freelist_threshold:
                if auto_vac == 2:  # 2 == INCREMENTAL
                    con.execute(f"PRAGMA incremental_vacuum({max(1, int(pages))})")
                    after_row = con.execute("PRAGMA freelist_count").fetchone()
                    after_count = int(after_row[0]) if after_row else 0
                    pages_freed = max(0, freelist_count - after_count)
                else:
                    con.execute("PRAGMA optimize")
            return {
                "success": True,
                "path": str(path),
                "freelist_count": freelist_count,
                "auto_vacuum": auto_vac,
                "pages_freed": pages_freed,
                "vacuumed": pages_freed > 0,
            }
        finally:
            con.close()
    except Exception as exc:
        return {"success": False, "error": str(exc), "path": str(path)}


def optimize_db(
    path: Path,
    *,
    wal_checkpoint: bool = True,
    vacuum: bool = False,
    incremental_vacuum_pages: int = 100,
    freelist_maintenance: bool = True,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    """Perform bounded maintenance on an SQLite database (WAL checkpoint truncate, pragma optimize, vacuum, freelist)."""
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
            if freelist_maintenance:
                freelist_row = con.execute("PRAGMA freelist_count").fetchone()
                freelist_before = int(freelist_row[0]) if freelist_row else 0
                auto_vac_row = con.execute("PRAGMA auto_vacuum").fetchone()
                if auto_vac_row and int(auto_vac_row[0]) == 2 and freelist_before > 0:
                    con.execute(f"PRAGMA incremental_vacuum({max(1, int(incremental_vacuum_pages))})")
                result["freelist_pages"] = freelist_before
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


def wal_checkpoint_truncate(
    path: Path,
    *,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    """Explicitly checkpoint and truncate the WAL file for an SQLite database."""
    if not path.exists():
        return {"success": False, "error": "file_not_found", "path": str(path)}
    wal_path = path.parent / f"{path.name}-wal"
    wal_size_before = wal_path.stat().st_size if wal_path.exists() else 0
    timeout = max(0.1, float(timeout_seconds))
    try:
        con = sqlite3.connect(path, timeout=timeout)
        try:
            con.execute(f"PRAGMA busy_timeout={int(timeout * 1000)}")
            row = con.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            busy = int(row[0]) if row else 0
            log_pages = int(row[1]) if row else 0
            checkpointed_pages = int(row[2]) if row else 0
        finally:
            con.close()
        wal_size_after = wal_path.stat().st_size if wal_path.exists() else 0
        return {
            "success": True,
            "path": str(path),
            "busy": busy,
            "log_pages": log_pages,
            "checkpointed_pages": checkpointed_pages,
            "wal_size_before": wal_size_before,
            "wal_size_after": wal_size_after,
            "bytes_reclaimed": max(0, wal_size_before - wal_size_after),
            "truncated": wal_size_after < wal_size_before or wal_size_after == 0,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc), "path": str(path)}


def auto_checkpoint_wal(
    path: Path,
    *,
    max_wal_bytes: int = 10 * 1024 * 1024,
    timeout_seconds: float = 3.0,
) -> dict[str, Any]:
    """Conditionally checkpoint and truncate WAL only if WAL file size exceeds max_wal_bytes."""
    wal_path = path.parent / f"{path.name}-wal"
    if not wal_path.exists():
        return {"success": True, "path": str(path), "triggered": False, "wal_size": 0}
    try:
        sz = wal_path.stat().st_size
        if sz >= max_wal_bytes:
            res = wal_checkpoint_truncate(path, timeout_seconds=timeout_seconds)
            res["triggered"] = True
            return res
        return {"success": True, "path": str(path), "triggered": False, "wal_size": sz}
    except Exception as exc:
        return {"success": False, "error": str(exc), "path": str(path)}


def clean_quarantined_files(
    state_dir: Path | str,
    *,
    max_age_seconds: float = 86400 * 7,
    remove_empty: bool = True,
) -> dict[str, Any]:
    """Prune abandoned .corrupt-* SQLite quarantine files in state_dir."""
    p_state = Path(state_dir)
    if not p_state.is_dir():
        return {"success": True, "pruned_count": 0, "pruned_bytes": 0, "files": []}

    now = time.time()
    pruned_count = 0
    pruned_bytes = 0
    pruned_files = []

    try:
        for p in p_state.glob("*.corrupt-*"):
            if not p.is_file():
                continue
            try:
                st = p.stat()
                age = now - st.st_mtime
                is_empty = st.st_size == 0
                if (remove_empty and is_empty) or age >= max_age_seconds:
                    size = st.st_size
                    p.unlink(missing_ok=True)
                    pruned_count += 1
                    pruned_bytes += size
                    pruned_files.append(p.name)
            except Exception:
                continue
    except Exception as exc:
        return {"success": False, "error": str(exc), "pruned_count": pruned_count, "pruned_bytes": pruned_bytes}

    return {
        "success": True,
        "pruned_count": pruned_count,
        "pruned_bytes": pruned_bytes,
        "files": pruned_files,
    }


