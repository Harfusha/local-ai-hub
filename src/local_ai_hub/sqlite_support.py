from __future__ import annotations

import hashlib
import os
import random
import shutil
import sqlite3
import time
import uuid
from contextlib import closing
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
    timeout_seconds: float = 5.0,
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
    return backup_path


def _durable_database_signature(
    path: Path,
) -> tuple[int, str, tuple[tuple[str, int, str], ...]]:
    """Return integrity, schema hash, row counts, and row hashes for migration proof."""
    uri = f"{path.resolve().as_uri()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=5.0)) as con:
        integrity = con.execute("PRAGMA quick_check").fetchone()
        if not integrity or str(integrity[0]).lower() != "ok":
            raise sqlite3.DatabaseError(f"database integrity check failed: {path}")
        schema_rows = [
            tuple(row)
            for row in con.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
            )
        ]
        schema_hash = hashlib.sha256(repr(schema_rows).encode("utf-8")).hexdigest()
        tables = [
            str(row[0])
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        counts = []
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            row_hash = hashlib.sha256()
            count = 0
            for row in con.execute(f"SELECT * FROM {quoted}"):
                count += 1
                for value in row:
                    if value is None:
                        encoded = b"N"
                    elif isinstance(value, bytes):
                        encoded = b"B" + value
                    elif isinstance(value, str):
                        encoded = b"S" + value.encode("utf-8")
                    elif isinstance(value, int):
                        encoded = b"I" + str(value).encode("ascii")
                    elif isinstance(value, float):
                        encoded = b"F" + value.hex().encode("ascii")
                    else:
                        encoded = type(value).__name__.encode("utf-8") + repr(value).encode("utf-8")
                    row_hash.update(len(encoded).to_bytes(8, "big"))
                    row_hash.update(encoded)
            counts.append((table, count, row_hash.hexdigest()))
        user_version = int(con.execute("PRAGMA user_version").fetchone()[0])
    return user_version, schema_hash, tuple(counts)


def _database_has_rows(signature: tuple[int, str, tuple[tuple[str, int, str], ...]]) -> bool:
    return any(row_count for _table, row_count, _digest in signature[2])


def _signature_token(signature: tuple[int, str, tuple[tuple[str, int, str], ...]]) -> str:
    return hashlib.sha256(repr(signature).encode("utf-8")).hexdigest()


def _migration_markers(path: Path, prefix: str) -> set[str]:
    if not path.exists():
        return set()
    uri = f"{path.resolve().as_uri()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=5.0)) as con:
        table = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_state_migrations'"
        ).fetchone()
        if not table:
            return set()
        return {
            str(row[0])
            for row in con.execute(
                "SELECT migration_key FROM agent_state_migrations WHERE migration_key LIKE ?",
                (f"{prefix}%",),
            )
        }


def _record_migration_marker(path: Path, key: str) -> None:
    with closing(connect_sqlite(path, isolation_level=None)) as con:
        con.execute(
            "CREATE TABLE IF NOT EXISTS agent_state_migrations "
            "(migration_key TEXT PRIMARY KEY, applied_at REAL NOT NULL)"
        )
        con.execute(
            "INSERT OR IGNORE INTO agent_state_migrations(migration_key, applied_at) VALUES (?, ?)",
            (key, time.time()),
        )


def _install_database_copy(source: Path, target: Path) -> None:
    expected = _durable_database_signature(source)
    temporary = target.with_name(f"{target.name}.migrating-{uuid.uuid4().hex}")
    try:
        shutil.copyfile(source, temporary)
        if _durable_database_signature(temporary) != expected:
            raise sqlite3.DatabaseError("durable database migration verification mismatch")
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def migrate_legacy_agent_blackboard_database(state_dir: Path | str) -> Path:
    """Merge legacy standalone blackboard rows into the durable Agent State DB."""
    root = Path(state_dir)
    target = root / "agent_state.sqlite"
    legacy = root / "agent_blackboard.sqlite3"
    if not legacy.exists():
        return target

    marker_prefix = "agent-blackboard-sqlite3-to-agent-state-v1:"
    signature = _durable_database_signature(legacy)
    migration_key = marker_prefix + _signature_token(signature)
    existing_markers = _migration_markers(target, marker_prefix)
    if migration_key in existing_markers:
        return target
    if existing_markers:
        source_backup = backup_durable_database(legacy, purpose="path-migration")
        target_backup = backup_durable_database(target, purpose="path-migration-target")
        raise sqlite3.DatabaseError(
            "legacy blackboard changed after migration; both histories preserved; "
            f"target backup={target_backup}; legacy backup={source_backup}"
        )
    backup = backup_durable_database(legacy, purpose="path-migration")
    expected_columns = (
        "board_id", "section", "content", "author", "vector_clock", "timestamp", "version",
    )
    with closing(connect_sqlite(target, isolation_level=None)) as con:
        con.execute("ATTACH DATABASE ? AS legacy_blackboard", (str(backup),))
        try:
            con.execute("BEGIN IMMEDIATE")
            con.execute(
                "CREATE TABLE IF NOT EXISTS agent_state_migrations "
                "(migration_key TEXT PRIMARY KEY, applied_at REAL NOT NULL)"
            )
            if con.execute(
                "SELECT 1 FROM agent_state_migrations WHERE migration_key = ?",
                (migration_key,),
            ).fetchone():
                con.execute("COMMIT")
                return target

            source_columns = tuple(
                str(row[1]) for row in con.execute("PRAGMA legacy_blackboard.table_info(agent_blackboard)")
            )
            if source_columns != expected_columns:
                raise sqlite3.DatabaseError("legacy blackboard schema mismatch")
            con.execute(
                """CREATE TABLE IF NOT EXISTS agent_blackboard (
                       board_id TEXT NOT NULL, section TEXT NOT NULL, content TEXT NOT NULL,
                       author TEXT NOT NULL, vector_clock TEXT NOT NULL, timestamp REAL NOT NULL,
                       version INTEGER NOT NULL, PRIMARY KEY(board_id, section))"""
            )
            columns = ", ".join(expected_columns)
            keys = "legacy.board_id = current.board_id AND legacy.section = current.section"
            different = " OR ".join(
                f"legacy.{column} IS NOT current.{column}"
                for column in expected_columns if column not in ("board_id", "section")
            )
            conflict_count = int(con.execute(
                "SELECT COUNT(*) FROM legacy_blackboard.agent_blackboard AS legacy "
                f"JOIN main.agent_blackboard AS current ON {keys} WHERE {different}"
            ).fetchone()[0])
            if conflict_count:
                raise sqlite3.DatabaseError("legacy blackboard conflicts with Agent State rows")
            con.execute(
                f"INSERT OR IGNORE INTO main.agent_blackboard ({columns}) "
                f"SELECT {columns} FROM legacy_blackboard.agent_blackboard"
            )
            missing = int(con.execute(
                "SELECT COUNT(*) FROM legacy_blackboard.agent_blackboard AS legacy "
                "LEFT JOIN main.agent_blackboard AS current ON " + keys +
                " WHERE current.board_id IS NULL"
            ).fetchone()[0])
            if missing:
                raise sqlite3.DatabaseError("legacy blackboard migration verification failed")
            con.execute("CREATE INDEX IF NOT EXISTS idx_blackboard_board ON agent_blackboard(board_id)")
            con.execute(
                """CREATE TABLE IF NOT EXISTS agent_state_schema_versions (
                       component TEXT PRIMARY KEY, version INTEGER NOT NULL, updated_at REAL NOT NULL)"""
            )
            con.execute(
                """INSERT INTO agent_state_schema_versions(component, version, updated_at)
                   VALUES ('agent_blackboard', 1, ?) ON CONFLICT(component) DO UPDATE SET
                   version = MAX(agent_state_schema_versions.version, excluded.version),
                   updated_at = excluded.updated_at""",
                (time.time(),),
            )
            con.execute(
                "INSERT INTO agent_state_migrations(migration_key, applied_at) VALUES (?, ?)",
                (migration_key, time.time()),
            )
            con.execute("COMMIT")
        except Exception:
            if con.in_transaction:
                con.execute("ROLLBACK")
            raise
        finally:
            con.execute("DETACH DATABASE legacy_blackboard")
    return target


def migrate_agent_state_database(state_dir: Path | str) -> Path:
    """Copy legacy ``agent_state.sqlite3`` to ``agent_state.sqlite`` with verified backup.

    Legacy source is retained. Identical/empty pairs are idempotent; conflicting
    non-empty histories fail closed after backing up both files.
    """
    root = Path(state_dir)
    root.mkdir(parents=True, exist_ok=True)
    target = root / "agent_state.sqlite"
    legacy = root / "agent_state.sqlite3"
    if legacy.exists():
        legacy_signature = _durable_database_signature(legacy)
        marker_prefix = "agent-state-sqlite3-to-agent-state-v1:"
        migration_key = marker_prefix + _signature_token(legacy_signature)
        existing_markers = _migration_markers(target, marker_prefix)
        if migration_key not in existing_markers:
            if existing_markers:
                target_backup = backup_durable_database(target, purpose="path-migration-target")
                legacy_backup = backup_durable_database(legacy, purpose="path-migration")
                raise sqlite3.DatabaseError(
                    "legacy Agent State changed after migration; both histories preserved; "
                    f"target backup={target_backup}; legacy backup={legacy_backup}"
                )
            if not target.exists():
                backup = backup_durable_database(legacy, purpose="path-migration")
                _install_database_copy(backup, target)
            else:
                target_signature = _durable_database_signature(target)
                if target_signature != legacy_signature:
                    target_has_rows = _database_has_rows(target_signature)
                    legacy_has_rows = _database_has_rows(legacy_signature)
                    if not target_has_rows and legacy_has_rows:
                        backup_durable_database(target, purpose="path-migration-target")
                        backup = backup_durable_database(legacy, purpose="path-migration")
                        _install_database_copy(backup, target)
                    elif target_has_rows and legacy_has_rows:
                        target_backup = backup_durable_database(target, purpose="path-migration-target")
                        legacy_backup = backup_durable_database(legacy, purpose="path-migration")
                        raise sqlite3.DatabaseError(
                            "durable filename migration conflict; both histories preserved; "
                            f"target backup={target_backup}; legacy backup={legacy_backup}"
                        )
            _record_migration_marker(target, migration_key)
    migrate_legacy_agent_blackboard_database(root)
    return target


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


def ensure_incremental_vacuum(path: Path, *, timeout_seconds: float = 5.0) -> dict[str, Any]:
    """Enable incremental auto-vacuum, converting an existing database once if needed."""
    timeout = max(0.1, float(timeout_seconds))
    deadline = time.monotonic() + timeout
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(path, timeout=timeout)
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


