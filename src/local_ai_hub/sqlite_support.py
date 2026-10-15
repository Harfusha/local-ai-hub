from __future__ import annotations

import logging
import os
import random
import re
import sqlite3
import stat
import time
import threading
import weakref
from contextlib import closing
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence, TypeVar


_LOGGER = logging.getLogger(__name__)

T = TypeVar("T")


def sqlite_batches(items: Sequence[T]) -> Iterator[Sequence[T]]:
    """Bound dynamic SQL lists, including pairs, below legacy SQLite limits."""
    for offset in range(0, len(items), 250):
        yield items[offset:offset + 250]


class SQLiteChangeObserver:
    """Observe commits on one persistent, bounded, read-only SQLite connection."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._connection: sqlite3.Connection | None = None
        self._finalizer: Any = None
        self._identity: tuple[int, int, int] | None = None
        self._data_version: int | None = None
        self._epoch = 0
        self._closed = False

    def _disconnect_locked(self) -> None:
        if self._finalizer is not None:
            try:
                self._finalizer()
            except sqlite3.Error:
                pass
        self._finalizer = None
        self._connection = None
        self._data_version = None

    def version(self) -> int | None:
        """Return a local monotonic epoch, or None when cache reuse is unsafe."""
        with self._lock:
            if self._closed:
                return None
            try:
                metadata = self.path.stat()
                identity = (metadata.st_dev, metadata.st_ino, metadata.st_ctime_ns)
                if identity != self._identity or self._connection is None:
                    self._disconnect_locked()
                    connection = sqlite3.connect(
                        self.path.resolve().as_uri() + "?mode=ro", uri=True,
                        timeout=0.05, check_same_thread=False,
                    )
                    self._connection = connection
                    self._finalizer = weakref.finalize(self, sqlite3.Connection.close, connection)
                    self._identity = identity
                    self._epoch += 1
                value = int(self._connection.execute("PRAGMA data_version").fetchone()[0])
                if self._data_version is not None and value != self._data_version:
                    self._epoch += 1
                self._data_version = value
                return self._epoch
            except (OSError, sqlite3.Error, ValueError, TypeError, IndexError):
                self._disconnect_locked()
                return None

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._disconnect_locked()


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
    path: Path | str,
    *,
    timeout_seconds: float = 5.0,
    isolation_level: str | None = "DEFERRED",
    row_factory: Any | None = None,
) -> sqlite3.Connection:
    """Open a short-lived derived-state connection with bounded lock waits.

    WAL is deliberately *not* selected here. ``PRAGMA journal_mode=WAL`` can itself
    require an exclusive lock, so schemas enable WAL once during initialization and
    hot-path connections only apply non-exclusive pragmas.
    """
    p = Path(path)
    timeout = max(0.01, float(timeout_seconds))
    con = sqlite3.connect(p, timeout=timeout, isolation_level=isolation_level)

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
            con.execute("PRAGMA mmap_size=67108864")
            con.execute("PRAGMA cache_size=-8000")
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


def quick_sanity_check(con: sqlite3.Connection) -> bool:
    """Fast integrity check (<1ms) testing that SQLite can read headers and schema version.

    Avoids full-table B-tree scans on multi-gigabyte files during cold process startup.
    """
    try:
        row = con.execute("PRAGMA schema_version").fetchone()
        return bool(row is not None)
    except Exception:
        return False


class DurableSchemaMismatchError(RuntimeError):
    """Durable database schema differs from this release; data stays preserved."""

    def __init__(
        self,
        database_path: Path | str,
        mismatches: list[str],
        backup_path: Path | None,
        backup_error: str = "",
    ) -> None:
        self.database_path = Path(database_path)
        self.mismatches = tuple(mismatches)
        self.backup_path = backup_path
        self.backup_error = backup_error
        self.recovery_required = True
        backup_detail = f"; backup={backup_path}" if backup_path else "; original database retained"
        if backup_error:
            backup_detail += f"; backup error={backup_error}"
        super().__init__(
            "durable database schema mismatch at "
            f"{self.database_path}; explicit recovery required; no migration applied"
            f"{backup_detail}: {'; '.join(mismatches)}"
        )


_BACKUP_PATTERNS = (
    re.compile(
        r"^(?P<base>.+?\.(?:sqlite3|sqlite|db))\.(?:schema-mismatch|path-migration(?:-target)?)-\d{19}\.sqlite3$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?P<base>.+?\.(?:sqlite3|sqlite|db))\.migration-v0-v1-(?:\d{19}|[0-9a-f]{32})\.bak$",
        re.IGNORECASE,
    ),
)


def rotate_database_backups(
    directory: Path | str,
    *,
    prefix: str | None = None,
    max_copies: int = 3,
    max_age_seconds: float = 7 * 86400,
) -> list[Path]:
    """Prune excess or stale database backup files to prevent disk accumulation.

    Keeps at most ``max_copies`` newest snapshots per database series and removes
    snapshots older than ``max_age_seconds`` (default 7 days).
    """
    root = Path(directory)
    if not root.is_dir():
        return []

    error_counts: dict[tuple[str, str, int | None], int] = {}

    def record_error(operation: str, exc: OSError) -> None:
        key = (operation, type(exc).__name__, exc.errno)
        error_counts[key] = error_counts.get(key, 0) + 1

    def report_errors() -> None:
        if not error_counts:
            return
        total = sum(error_counts.values())
        details = "; ".join(
            f"operation={operation},count={count},exception_type={error_type},errno={error_number}"
            for (operation, error_type, error_number), count in sorted(error_counts.items())
        )
        _LOGGER.warning(
            "Database backup rotation encountered filesystem errors: "
            "operation=rotate_database_backups,error_count=%d,%s",
            total,
            details,
        )

    groups: dict[str, list[Path]] = {}
    now = time.time()

    try:
        entries = list(root.iterdir())
    except OSError as exc:
        record_error("scan", exc)
        report_errors()
        return []

    for entry in entries:
        name = entry.name
        # SQLite may be actively using any of these files beside its database.
        if name.endswith(("-wal", "-shm", "-journal")) or "-mj" in name:
            continue

        group_key: str | None = None
        for pat in _BACKUP_PATTERNS:
            m = pat.match(name)
            if m:
                candidate_key = m.group("base")
                if prefix is None or candidate_key == prefix:
                    group_key = candidate_key
                break

        if group_key is not None:
            try:
                metadata = entry.lstat()
            except OSError as exc:
                record_error("lstat", exc)
                continue
            if not stat.S_ISREG(metadata.st_mode):
                continue
            if getattr(metadata, "st_file_attributes", 0) & 0x400:
                continue
            groups.setdefault(group_key, []).append(entry)

    pruned: list[Path] = []
    for key, candidates in groups.items():
        try:
            candidates.sort(key=lambda p: (p.stat().st_mtime, p.name))
        except OSError as exc:
            record_error("sort_stat", exc)
            continue

        to_prune: set[Path] = set()

        if max_copies is not None and max_copies >= 0 and len(candidates) > max_copies:
            excess_count = len(candidates) - max_copies
            for p in candidates[:excess_count]:
                to_prune.add(p)

        if max_age_seconds is not None and max_age_seconds > 0:
            for p in candidates:
                try:
                    if (now - p.stat().st_mtime) > max_age_seconds:
                        to_prune.add(p)
                except OSError as exc:
                    record_error("age_stat", exc)

        for p in sorted(to_prune, key=lambda x: x.name):
            try:
                p.unlink(missing_ok=True)
                for ext in ("-wal", "-shm"):
                    sidecar = p.with_name(f"{p.name}{ext}")
                    if sidecar.exists():
                        try:
                            sidecar.unlink(missing_ok=True)
                        except OSError as exc:
                            record_error("unlink_sidecar", exc)
                pruned.append(p)
            except OSError as exc:
                record_error("unlink_snapshot", exc)

    report_errors()
    return pruned


def backup_durable_database(path: Path | str, *, purpose: str = "schema-mismatch") -> Path:
    """Create a consistent SQLite backup without changing the durable source."""
    source_path = Path(path)
    backup_path = source_path.with_name(
        f"{source_path.name}.{purpose}-{time.time_ns()}.sqlite3"
    )
    source = sqlite3.connect(str(source_path), timeout=5.0)
    destination = sqlite3.connect(str(backup_path), timeout=5.0)
    try:
        source.backup(destination)
        check = destination.execute("PRAGMA quick_check").fetchone()
        if not check or str(check[0]).lower() != "ok":
            raise sqlite3.DatabaseError("schema recovery backup failed quick_check")
        destination.commit()
    except Exception:
        destination.close()
        source.close()
        backup_path.unlink(missing_ok=True)
        raise
    destination.close()
    source.close()
    try:
        rotate_database_backups(source_path.parent, prefix=source_path.name, max_copies=3)
    except Exception as exc:
        _LOGGER.warning(
            "Database backup rotation raised after snapshot creation: "
            "operation=rotate_database_backups,error_count=1,exception_type=%s,errno=%s",
            type(exc).__name__,
            getattr(exc, "errno", None),
        )
    return backup_path


class UnsupportedLegacyStateDatabase(sqlite3.DatabaseError):
    """Raised when only an unsupported standalone durable state file exists."""


def require_canonical_agent_state_database(state_dir: Path | str) -> Path:
    """Return the canonical state path, rejecting legacy-only state without touching it."""
    root = Path(state_dir)
    canonical = root / "agent_state.sqlite"
    if canonical.exists():
        return canonical
    for name in ("agent_state.sqlite3", "leases.sqlite3", "agent_blackboard.sqlite3"):
        legacy = root / name
        if legacy.exists():
            raise UnsupportedLegacyStateDatabase(
                f"unsupported legacy durable state database: {legacy}; "
                f"expected canonical database: {canonical}"
            )
    return canonical


def validate_durable_schema(
    con: sqlite3.Connection,
    db_path: Path | str,
    expected_tables: dict[str, list[str | tuple[Any, ...]]],
    *,
    complete_groups: tuple[tuple[str, ...], ...] = (),
    required_unique: dict[str, tuple[tuple[str, ...], ...]] | None = None,
    required_if_event_kinds: dict[str, tuple[str, ...]] | None = None,
) -> None:
    """Fail closed on existing durable table drift, preserving a verified backup."""
    existing = {
        str(row[0])
        for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        if not str(row[0]).startswith("sqlite_")
    }
    mismatches: list[str] = []
    for group in complete_groups:
        present = set(group) & existing
        if present and present != set(group):
            missing = sorted(set(group) - existing)
            mismatches.append(f"incomplete durable table group; missing={','.join(missing)}")
    for table, expected_columns in expected_tables.items():
        if table not in existing:
            event_kinds = (required_if_event_kinds or {}).get(table, ())
            if event_kinds and "agent_events" in existing:
                predicate = " OR ".join("kind LIKE ?" for _ in event_kinds)
                found = con.execute(
                    f"SELECT 1 FROM agent_events WHERE {predicate} LIMIT 1",
                    tuple(event_kinds),
                ).fetchone()
                if found:
                    mismatches.append(
                        f"durable projection {table} is missing while related events remain"
                    )
            continue
        actual_info = list(con.execute(f"PRAGMA table_info({table})"))
        actual_names = [str(row[1]) for row in actual_info]
        expected_names = [str(item[0]) if not isinstance(item, str) else item for item in expected_columns]
        if actual_names != expected_names:
            mismatches.append(
                f"{table} columns differ; expected={expected_names}; actual={actual_names}"
            )
            continue
        for expected, actual in zip(expected_columns, actual_info):
            if isinstance(expected, str):
                continue
            name = str(expected[0])
            declared_type = str(expected[1]).upper() if len(expected) > 1 and expected[1] is not None else None
            not_null = expected[2] if len(expected) > 2 else None
            primary_key_order = expected[3] if len(expected) > 3 else None
            default_value = expected[4] if len(expected) > 4 else None
            differences: list[str] = []
            if declared_type is not None and str(actual[2]).upper() != declared_type:
                differences.append(f"type={actual[2]!r}, expected={declared_type!r}")
            if not_null is not None and int(actual[3]) != int(not_null):
                differences.append(f"notnull={actual[3]}, expected={not_null}")
            if primary_key_order is not None and int(actual[5]) != int(primary_key_order):
                differences.append(f"pk={actual[5]}, expected={primary_key_order}")
            if len(expected) > 4 and actual[4] != default_value:
                differences.append(f"default={actual[4]!r}, expected={default_value!r}")
            if differences:
                mismatches.append(f"{table}.{name} differs; " + "; ".join(differences))

    for table, unique_sets in (required_unique or {}).items():
        if table not in existing:
            continue
        actual_unique: set[tuple[str, ...]] = set()
        for index in con.execute(f"PRAGMA index_list({table})"):
            if not int(index[2]) or (len(index) > 4 and int(index[4])):
                continue
            columns = tuple(
                str(row[2])
                for row in con.execute(f"PRAGMA index_info({index[1]})")
            )
            actual_unique.add(columns)
        for columns in unique_sets:
            if tuple(columns) not in actual_unique:
                mismatches.append(f"{table} missing required unique constraint on {tuple(columns)}")
    if not mismatches:
        return

    con.close()
    backup_path: Path | None = None
    backup_error = ""
    try:
        backup_path = backup_durable_database(db_path)
    except Exception as exc:
        backup_error = str(exc)
    raise DurableSchemaMismatchError(db_path, mismatches, backup_path, backup_error)


def retry_busy(
    operation: Callable[[], T],
    *,
    retries: int = 5,
    base_delay_seconds: float = 0.015,
    max_delay_seconds: float = 2.0,
    jitter: bool = True,
    fallback_degraded: bool = False,
    degraded_value: Any = None,
) -> T:
    """Retry only transient lock/busy errors with an exponential backoff and jitter.

    If fallback_degraded is True and retries are exhausted due to lock/busy error,
    returns degraded_value if provided, or {"success": False, "degraded": True, "error": "database_locked"}.
    """
    attempts = max(1, int(retries))
    delay = max(0.0, float(base_delay_seconds))
    for attempt in range(attempts):
        try:
            return operation()
        except Exception as exc:
            if not is_busy_error(exc):
                raise
            if attempt + 1 >= attempts:
                if fallback_degraded:
                    if degraded_value is not None:
                        return degraded_value
                    return {"success": False, "degraded": True, "error": "database_locked", "error_code": "database_locked"}  # type: ignore[return-value]
                raise
            if delay:
                backoff = min(max_delay_seconds, delay * (2 ** attempt))
                sleep_time = random.uniform(0.5 * backoff, backoff) if jitter else backoff
                time.sleep(sleep_time)
    raise AssertionError("unreachable")


def with_degraded_fallback(
    operation: Callable[[], T],
    *,
    retries: int = 5,
    base_delay_seconds: float = 0.015,
    max_delay_seconds: float = 2.0,
    jitter: bool = True,
    degraded_value: Any = None,
) -> T | dict[str, Any]:
    """Execute operation with retry_busy and return a graceful degraded response on persistent locks."""
    return retry_busy(
        operation,
        retries=retries,
        base_delay_seconds=base_delay_seconds,
        max_delay_seconds=max_delay_seconds,
        jitter=jitter,
        fallback_degraded=True,
        degraded_value=degraded_value,
    )


def ensure_incremental_vacuum(path: Path | str, *, timeout_seconds: float = 5.0) -> dict[str, Any]:
    """Enable incremental auto-vacuum, converting an existing database once if needed."""
    p = Path(path)
    timeout = max(0.1, float(timeout_seconds))
    deadline = time.monotonic() + timeout
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(p, timeout=timeout)
        try:
            con.execute(f"PRAGMA busy_timeout={int(timeout * 1000)}")
            current = con.execute("PRAGMA auto_vacuum").fetchone()
            mode = int(current[0]) if current else 0
            if mode != 2:
                con.execute("PRAGMA auto_vacuum=INCREMENTAL")
                con.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
                con.execute("VACUUM")
                con.set_progress_handler(None, 0)
                current = con.execute("PRAGMA auto_vacuum").fetchone()
                mode = int(current[0]) if current else 0
            return {"success": mode == 2, "auto_vacuum": mode}
        finally:
            con.close()
    except (OSError, sqlite3.Error) as exc:
        return {"success": False, "error": type(exc).__name__}


def incremental_vacuum(
    path: Path | str,
    *,
    pages: int = 100,
    freelist_threshold: int = 50,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    """Perform bounded incremental vacuum and freelist reclamation if freelist pages exceed threshold."""
    p = Path(path)
    if not p.exists():
        return {"success": False, "error": "file_not_found", "path": str(p)}
    timeout = max(0.1, float(timeout_seconds))
    try:
        con = sqlite3.connect(p, timeout=timeout)
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
                "path": str(p),
                "freelist_count": freelist_count,
                "auto_vacuum": auto_vac,
                "pages_freed": pages_freed,
                "vacuumed": pages_freed > 0,
            }
        finally:
            con.close()
    except Exception as exc:
        return {"success": False, "error": str(exc), "path": str(p)}


def optimize_db(
    path: Path | str,
    *,
    wal_checkpoint: bool = True,
    vacuum: bool = False,
    incremental_vacuum_pages: int = 100,
    freelist_maintenance: bool = True,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    """Perform bounded maintenance on an SQLite database (WAL checkpoint truncate, pragma optimize, vacuum, freelist)."""
    p = Path(path)
    if not p.exists():
        return {"success": False, "error": "file_not_found", "path": str(p)}

    timeout = max(0.1, float(timeout_seconds))
    result: dict[str, Any] = {
        "success": True,
        "path": str(p),
        "initial_size": p.stat().st_size if p.exists() else 0,
    }

    try:
        con = sqlite3.connect(p, timeout=timeout)
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
        result["final_size"] = p.stat().st_size if p.exists() else 0
        result["freed_bytes"] = max(0, result["initial_size"] - result["final_size"])
        return result
    except Exception as exc:
        return {"success": False, "error": str(exc), "path": str(p)}


def wal_checkpoint_truncate(
    path: Path | str,
    *,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    """Explicitly checkpoint and truncate the WAL file for an SQLite database."""
    p = Path(path)
    if not p.exists():
        return {"success": False, "error": "file_not_found", "path": str(p)}
    wal_path = p.parent / f"{p.name}-wal"
    wal_size_before = wal_path.stat().st_size if wal_path.exists() else 0
    timeout = max(0.1, float(timeout_seconds))
    try:
        con = sqlite3.connect(p, timeout=timeout)
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
            "path": str(p),
            "busy": busy,
            "log_pages": log_pages,
            "checkpointed_pages": checkpointed_pages,
            "wal_size_before": wal_size_before,
            "wal_size_after": wal_size_after,
            "bytes_reclaimed": max(0, wal_size_before - wal_size_after),
            "truncated": bool(wal_size_before > 0 and (wal_size_after < wal_size_before or wal_size_after == 0)),
        }
    except Exception as exc:
        return {"success": False, "error": str(exc), "path": str(p)}


def auto_checkpoint_wal(
    path: Path | str,
    *,
    max_wal_bytes: int = 10 * 1024 * 1024,
    timeout_seconds: float = 3.0,
) -> dict[str, Any]:
    """Conditionally checkpoint and truncate WAL only if WAL file size exceeds max_wal_bytes."""
    p = Path(path)
    if not p.exists():
        return {"success": False, "error": "file_not_found", "path": str(p)}
    wal_path = p.parent / f"{p.name}-wal"
    if not wal_path.exists():
        return {"success": True, "path": str(p), "triggered": False, "wal_size": 0}
    try:
        sz = wal_path.stat().st_size
        if sz >= max_wal_bytes:
            res = wal_checkpoint_truncate(p, timeout_seconds=timeout_seconds)
            res["triggered"] = True
            return res
        return {"success": True, "path": str(p), "triggered": False, "wal_size": sz}
    except Exception as exc:
        return {"success": False, "error": str(exc), "path": str(p)}


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
                    # Also unlink any associated WAL and SHM sidecars
                    for ext in ("-wal", "-shm"):
                        p.with_name(f"{p.name}{ext}").unlink(missing_ok=True)
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

