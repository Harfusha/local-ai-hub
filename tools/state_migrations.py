"""Backup-protected, consecutive offline state migrations for setup/update."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import shutil
import stat
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path
from typing import Any, Callable

from local_ai_hub.state_lifecycle import (
    BOOTSTRAP_STATE_ENTRIES,
    CURRENT_STATE_VERSION,
    ensure_state_version,
    read_state_version,
    write_state_version,
)
from local_ai_hub.project_identity import project_scope_id, worktree_scope_id
from local_ai_hub.legacy_board_archive import migrate_legacy_board_database, read_legacy_board_archive
from local_ai_hub.endpoint_stats import ENDPOINT_CALL_IDS_TABLE_SIGNATURE, ENDPOINT_STATS_TABLE_SIGNATURE
from local_ai_hub.telemetry_contracts import (
    _LAYA_DECISION_FIELDS,
    _LAYA_DECISION_PRE_RUNTIME_FIELDS,
    load_telemetry_json,
    normalize_laya_decision_metadata,
)

_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class StateMigration:
    """Callbacks must close state handles before returning so Windows can swap the staged directory."""

    def __init__(
        self,
        source_version: int,
        target_version: int,
        migrate: Callable[[Path], None],
        verify: Callable[[Path], bool],
    ) -> None:
        self.source_version = source_version
        self.target_version = target_version
        self.migrate = migrate
        self.verify = verify


class StateMigrationError(RuntimeError):
    """A migration failed after creating a verified backup."""

    def __init__(self, backup_path: Path, cause: Exception) -> None:
        self.backup_path = backup_path
        super().__init__(f"state migration failed. Verified original backup retained at {backup_path}. {cause}")


_RELATION_V6 = (
    ("relation_id", "TEXT", 0, None, 1), ("source_entity", "TEXT", 1, None, 0),
    ("relation", "TEXT", 1, None, 0), ("target_entity", "TEXT", 1, None, 0),
    ("weight", "REAL", 1, "1.0", 0), ("metadata", "TEXT", 1, "'{}'", 0),
    ("created_at", "REAL", 1, None, 0), ("updated_at", "REAL", 1, None, 0),
)
_RELATION_V7 = (*_RELATION_V6, ("repository_id", "TEXT", 1, "''", 0))
_EMBEDDINGS_V5 = (
    ("record_id", "TEXT", 0, None, 1), ("embedding", "TEXT", 1, None, 0),
    ("created_at", "REAL", 1, None, 0),
)
_EMBEDDINGS_V7 = (
    *_EMBEDDINGS_V5,
    ("embedding_space_id", "TEXT", 1, "''", 0), ("model_name", "TEXT", 1, "''", 0),
    ("dimension", "INTEGER", 1, "0", 0),
)


def _table_signature(con: sqlite3.Connection, table: str) -> tuple[tuple[str, str, int, str | None, int], ...] | None:
    rows = con.execute(f'PRAGMA table_info("{table}")').fetchall()
    if not rows:
        return None
    return tuple(
        (str(row[1]), str(row[2]).upper(), int(row[3]), None if row[4] is None else str(row[4]), int(row[5]))
        for row in rows
    )


_ENDPOINT_STATS_ALLOWED_TABLES = {
    "endpoint_stats", "endpoint_stats_basename_archive", "endpoint_stats_exact", "endpoint_call_ids",
}


def _endpoint_stats_row_digest(con: sqlite3.Connection, table: str) -> str:
    rows = con.execute(
        f'SELECT * FROM "{table}" ORDER BY scope_root, item_type, item_name'
    ).fetchall()
    return hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()


_SOURCE_INDEX_V6 = ("root", "path", "content_hash", "text", "updated_at")
_SOURCE_INDEX_V7 = (*_SOURCE_INDEX_V6, "text_origin")
_FILE_CARD_V6 = (
    "content_hash", "model", "pipeline_version", "status", "attempts", "retry_after",
    "lease_until", "last_error", "updated_at",
)
_FILE_CARD_V7 = (*_FILE_CARD_V6[:7], "claim_id", *_FILE_CARD_V6[7:])
_FILE_CARD_V7_APPENDED = (*_FILE_CARD_V6, "claim_id")
_FILE_REFS_V6 = (
    "root", "path", "content_hash", "size", "mtime_ns", "needs_hash", "rag_hash",
    "last_accessed_at", "generation", "card_key", "updated_at",
)
_FILE_REFS_V7 = (*_FILE_REFS_V6, "centrality_score")
_FILE_REFS_V7_CENTRALITY_BEFORE_UPDATED = (
    *_FILE_REFS_V6[:-1], "centrality_score", _FILE_REFS_V6[-1],
)
_EXTERNAL_INDEX_V6 = ("root", "backend", "revision_hash", "status", "updated_at", "error")
_EXTERNAL_INDEX_V7 = (*_EXTERNAL_INDEX_V6, "retry_count")


def _table_columns(con: sqlite3.Connection, table: str) -> tuple[str, ...] | None:
    rows = con.execute(f'PRAGMA table_info("{table}")').fetchall()
    return tuple(str(row[1]) for row in rows) if rows else None


def _is_supported_unversioned_v5_state(root: Path) -> bool:
    """Recognize the last unversioned v5 layout by exact durable schema, never by filename alone."""
    agent_db = root / "agent_state.sqlite"
    board_db = root / "agent_board.sqlite"
    if not agent_db.is_file() or agent_db.is_symlink() or not board_db.is_file() or board_db.is_symlink():
        return False
    uri = agent_db.resolve().as_uri() + "?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True, timeout=2.0)) as con:
            if con.execute("PRAGMA quick_check").fetchone() != ("ok",):
                raise RuntimeError("unversioned v5 agent state failed integrity check; state is unchanged")
            if con.execute("PRAGMA user_version").fetchone() != (1,):
                return False
            if (_table_signature(con, "agent_entity_relations") != _RELATION_V6
                    or _table_signature(con, "agent_memory_embeddings") != _EMBEDDINGS_V5):
                return False
            if con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_memory_records'"
            ).fetchone():
                tenant = con.execute(
                    "SELECT 1 FROM agent_memory_records WHERE "
                    "json_type(CASE WHEN json_valid(provenance) THEN provenance ELSE '{}' END, '$.tenant') IS NOT NULL "
                    "OR json_type(CASE WHEN json_valid(provenance) THEN provenance ELSE '{}' END, '$.tenant_key') IS NOT NULL "
                    "LIMIT 1"
                ).fetchone()
                if tenant:
                    raise RuntimeError(
                        "unversioned v5 state contains retired tenant identity; state is unchanged"
                    )
    except sqlite3.Error as exc:
        raise RuntimeError(f"unversioned v5 agent state is unreadable; state is unchanged: {exc}") from exc
    return True


def _create_file_card_enrichment_v7(con: sqlite3.Connection, *, appended_claim_id: bool) -> None:
    con.execute("ALTER TABLE file_card_enrichment RENAME TO file_card_enrichment_migration_v6")
    con.execute("""CREATE TABLE file_card_enrichment (
        content_hash TEXT NOT NULL,
        model TEXT NOT NULL,
        pipeline_version TEXT NOT NULL,
        status TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        retry_after REAL NOT NULL DEFAULT 0,
        lease_until REAL NOT NULL DEFAULT 0,
        claim_id TEXT,
        last_error TEXT,
        updated_at REAL NOT NULL,
        PRIMARY KEY(content_hash,model,pipeline_version)
    )""")
    if appended_claim_id:
        source = "content_hash,model,pipeline_version,status,attempts,retry_after,lease_until,claim_id,last_error,updated_at"
        target = source
    else:
        source = "content_hash,model,pipeline_version,status,attempts,retry_after,lease_until,last_error,updated_at"
        target = "content_hash,model,pipeline_version,status,attempts,retry_after,lease_until,last_error,updated_at"
        con.execute(f"INSERT INTO file_card_enrichment({target}) SELECT {source} FROM file_card_enrichment_migration_v6")
        con.execute("DROP TABLE file_card_enrichment_migration_v6")
        return
    con.execute(f"INSERT INTO file_card_enrichment({target}) SELECT {source} FROM file_card_enrichment_migration_v6")
    con.execute("DROP TABLE file_card_enrichment_migration_v6")


def _preprocess_schema_v7(state: Path) -> bool:
    database = state / "preprocess.sqlite3"
    if not database.exists():
        return True
    from local_ai_hub.preprocess_lexical import has_canonical_shared_fts

    with closing(sqlite3.connect(database)) as con:
        tables = {str(row[0]) for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "source_index" in tables and _table_columns(con, "source_index") != _SOURCE_INDEX_V7:
            return False
        if "file_card_enrichment" in tables and _table_columns(con, "file_card_enrichment") != _FILE_CARD_V7:
            return False
        if "file_refs" in tables and _table_columns(con, "file_refs") not in {
            _FILE_REFS_V7, _FILE_REFS_V7_CENTRALITY_BEFORE_UPDATED,
        }:
            return False
        if "external_index_state" in tables and _table_columns(con, "external_index_state") != _EXTERNAL_INDEX_V7:
            return False
        return has_canonical_shared_fts(con)


def _migrate_preprocess_schema_6_to_7(state: Path) -> None:
    database = state / "preprocess.sqlite3"
    if not database.exists():
        return
    if not database.is_file() or database.is_symlink():
        raise RuntimeError(f"preprocess state path is not a regular database file: {database}")
    from local_ai_hub.preprocess_lexical import (
        SHARED_FTS_ROWS, advance_fts_migration, fts_layout, has_canonical_shared_fts, initialize_fts_rows,
    )

    with closing(sqlite3.connect(database, timeout=15.0)) as con:
        con.execute("PRAGMA busy_timeout=15000")
        tables = {str(row[0]) for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        con.execute("BEGIN IMMEDIATE")
        if "source_index" in tables:
            columns = _table_columns(con, "source_index")
            if columns == _SOURCE_INDEX_V6:
                con.execute("ALTER TABLE source_index ADD COLUMN text_origin TEXT NOT NULL DEFAULT 'unknown'")
            elif columns != _SOURCE_INDEX_V7:
                raise RuntimeError("unsupported source_index schema for state 6->7 migration")

        if "file_card_enrichment" in tables:
            columns = _table_columns(con, "file_card_enrichment")
            if columns == _FILE_CARD_V6:
                _create_file_card_enrichment_v7(con, appended_claim_id=False)
            elif columns == _FILE_CARD_V7_APPENDED:
                _create_file_card_enrichment_v7(con, appended_claim_id=True)
            elif columns != _FILE_CARD_V7:
                raise RuntimeError("unsupported file_card_enrichment schema for state 6->7 migration")

        if "file_refs" in tables:
            columns = _table_columns(con, "file_refs")
            if columns == _FILE_REFS_V6:
                con.execute("ALTER TABLE file_refs ADD COLUMN centrality_score REAL NOT NULL DEFAULT 0.0")
            elif columns not in {_FILE_REFS_V7, _FILE_REFS_V7_CENTRALITY_BEFORE_UPDATED}:
                raise RuntimeError("unsupported file_refs schema for state 6->7 migration")

        if "external_index_state" in tables:
            columns = _table_columns(con, "external_index_state")
            if columns == _EXTERNAL_INDEX_V6:
                con.execute("ALTER TABLE external_index_state ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0")
            elif columns != _EXTERNAL_INDEX_V7:
                raise RuntimeError("unsupported external_index_state schema for state 6->7 migration")
        con.commit()

        # FTS copy is resumable in batches, but runs only against the staged copy
        # while the update owns the state. Startup refuses to perform this work.
        if con.execute("SELECT 1 FROM sqlite_master WHERE name='source_fts'").fetchone() is None:
            initialize_fts_rows(con)
        while advance_fts_migration(con, write_timeout_seconds=30.0):
            pass
        if fts_layout(con) != SHARED_FTS_ROWS or not has_canonical_shared_fts(con):
            raise RuntimeError("preprocess FTS migration did not reach the canonical schema")
        if con.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise RuntimeError("preprocess database failed integrity check after 6->7 migration")


def _state_schema_v7(state: Path) -> bool:
    database = state / "agent_state.sqlite"
    if database.exists():
        with closing(sqlite3.connect(database)) as con:
            tables = {str(row[0]) for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            expected = {
                "agent_entity_relations": _RELATION_V7,
                "agent_memory_embeddings": _EMBEDDINGS_V7,
            }
            if not all(table not in tables or _table_signature(con, table) == signature for table, signature in expected.items()):
                return False
    return _preprocess_schema_v7(state)


def _state_schema_v8(state: Path) -> bool:
    database = state / "agent_board.sqlite"
    sidecars = (state / "agent_board.sqlite-wal", state / "agent_board.sqlite-shm")
    if not _state_schema_v7(state) or database.exists() or any(path.exists() for path in sidecars):
        return False
    try:
        read_legacy_board_archive(state)
    except (OSError, ValueError):
        return False
    return True


def _endpoint_stats_schema_v9(state: Path) -> bool:
    database = state / "endpoint_stats.sqlite3"
    if not database.exists():
        return not any((state / f"{database.name}{suffix}").exists() for suffix in ("-wal", "-shm"))
    if not database.is_file() or database.is_symlink():
        return False
    try:
        uri = database.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=3.0)) as con:
            if con.execute("PRAGMA quick_check").fetchone() != ("ok",):
                return False
            tables = {
                str(row[0]) for row in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            if tables - _ENDPOINT_STATS_ALLOWED_TABLES or "endpoint_stats" in tables:
                return False
            for table in ("endpoint_stats_basename_archive", "endpoint_stats_exact"):
                if table in tables and _table_signature(con, table) != ENDPOINT_STATS_TABLE_SIGNATURE:
                    return False
            if "endpoint_call_ids" in tables and _table_signature(con, "endpoint_call_ids") != ENDPOINT_CALL_IDS_TABLE_SIGNATURE:
                return False
        return True
    except (OSError, sqlite3.Error, ValueError):
        return False


def _state_schema_v9(state: Path) -> bool:
    return _state_schema_v8(state) and _endpoint_stats_schema_v9(state)


_TELEMETRY_SNAPSHOT_SIGNATURE = (
    ("id", "INTEGER", 0, None, 1),
    ("created_at", "REAL", 1, None, 0),
    ("name", "TEXT", 1, None, 0),
    ("metrics_json", "TEXT", 1, None, 0),
)


def _telemetry_snapshots_are_v10(con: sqlite3.Connection) -> bool:
    tables = {
        str(row[0]) for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    if "snapshots" not in tables:
        return True
    if _table_signature(con, "snapshots") != _TELEMETRY_SNAPSHOT_SIGNATURE:
        return False
    for (raw,) in con.execute("SELECT metrics_json FROM snapshots WHERE name='laya_decision'"):
        try:
            metadata = normalize_laya_decision_metadata(load_telemetry_json(raw))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(metadata, dict) and frozenset(metadata) == _LAYA_DECISION_PRE_RUNTIME_FIELDS:
            return False
    return True


def _telemetry_laya_schema_v10(state: Path) -> bool:
    database = state / "telemetry.sqlite3"
    if not database.exists():
        return not any((state / f"{database.name}{suffix}").exists() for suffix in ("-wal", "-shm"))
    if not database.is_file() or database.is_symlink():
        return False
    try:
        uri = database.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=3.0)) as con:
            if con.execute("PRAGMA quick_check").fetchone() != ("ok",):
                return False
            return _telemetry_snapshots_are_v10(con)
    except (OSError, sqlite3.Error, ValueError):
        return False


def _state_schema_v10(state: Path) -> bool:
    return _state_schema_v9(state) and _telemetry_laya_schema_v10(state)


_AGENT_INCIDENTS_SIGNATURE = (
    ("incident_id", "TEXT", 0, None, 1),
    ("operation_class", "TEXT", 1, None, 0),
    ("error_class", "TEXT", 1, None, 0),
    ("signature_hash", "TEXT", 1, None, 0),
    ("redacted_message", "TEXT", 1, None, 0),
    ("state_revision", "TEXT", 1, None, 0),
    ("attempts", "INTEGER", 1, None, 0),
    ("evidence_ids", "TEXT", 1, None, 0),
    ("root_cause", "TEXT", 0, None, 0),
    ("verified_fix", "TEXT", 0, None, 0),
    ("confidence", "REAL", 1, None, 0),
    ("resolved", "INTEGER", 1, None, 0),
    ("created_at", "REAL", 1, None, 0),
    ("updated_at", "REAL", 1, None, 0),
    ("expires_at", "REAL", 0, None, 0),
    ("affected_paths", "TEXT", 1, "'[]'", 0),
    ("ignored", "INTEGER", 1, "0", 0),
    ("repository_key", "TEXT", 1, "''", 0),
)


def _agent_incidents_v11(state: Path, *, migrate: bool) -> bool:
    database = state / "agent_state.sqlite"
    if not database.exists():
        if any((state / f"{database.name}{suffix}").exists() for suffix in ("-wal", "-shm")):
            if migrate:
                raise RuntimeError("agent incident sidecar exists without its database")
            return False
        return True
    if not database.is_file() or database.is_symlink():
        if migrate:
            raise RuntimeError("agent state path is not a regular database file")
        return False
    try:
        uri = database.resolve().as_uri() + ("?mode=rw" if migrate else "?mode=ro")
        with closing(sqlite3.connect(uri, uri=True, timeout=15.0 if migrate else 3.0)) as con:
            if con.execute("PRAGMA quick_check").fetchone() != ("ok",):
                if migrate:
                    raise RuntimeError("agent state database failed integrity check")
                return False
            tables = {str(row[0]) for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "agent_incidents" not in tables:
                return True
            if _table_signature(con, "agent_incidents") != _AGENT_INCIDENTS_SIGNATURE:
                if migrate:
                    raise RuntimeError("unsupported agent_incidents schema for state 10->11 migration")
                return False
            if migrate:
                con.execute("PRAGMA busy_timeout=15000")
                con.execute("BEGIN IMMEDIATE")
                before = int(con.execute(
                    "SELECT COUNT(*) FROM agent_incidents "
                    "WHERE lower(trim(coalesce(verified_fix, ''))) = 'resolved'"
                ).fetchone()[0])
                updated = 0
                if before:
                    updated = con.execute(
                        "UPDATE agent_incidents SET verified_fix=NULL, resolved=0 "
                        "WHERE lower(trim(coalesce(verified_fix, ''))) = 'resolved'"
                    ).rowcount
                remaining = int(con.execute(
                    "SELECT COUNT(*) FROM agent_incidents "
                    "WHERE lower(trim(coalesce(verified_fix, ''))) = 'resolved'"
                ).fetchone()[0])
                if remaining or updated != before:
                    raise RuntimeError("agent incident placeholder migration failed row verification")
                con.commit()
            else:
                if con.execute(
                    "SELECT 1 FROM agent_incidents "
                    "WHERE lower(trim(coalesce(verified_fix, ''))) = 'resolved' LIMIT 1"
                ).fetchone():
                    return False
            return con.execute("PRAGMA quick_check").fetchone() == ("ok",)
    except (OSError, sqlite3.Error, ValueError):
        if migrate:
            raise
        return False


def _state_schema_v11(state: Path) -> bool:
    return _state_schema_v10(state) and _agent_incidents_v11(state, migrate=False)


def _migrate_incident_placeholder_10_to_11(state: Path) -> None:
    if not _agent_incidents_v11(state, migrate=True):
        raise RuntimeError("agent incident state failed verification after 10->11 migration")


def _task_scopes_v12(state: Path, *, migrate: bool) -> bool:
    database = state / "agent_state.sqlite"
    if not database.exists():
        return True
    if not database.is_file() or database.is_symlink():
        raise RuntimeError(f"agent state path is not a regular database file: {database}")
    with closing(sqlite3.connect(database, timeout=15.0)) as con:
        con.execute("PRAGMA busy_timeout=15000")
        tables = {str(row[0]) for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "agent_tasks_projection" not in tables:
            return True
        rows = con.execute("SELECT task_id, checkpoint FROM agent_tasks_projection").fetchall()
        converted: list[tuple[str, str]] = []
        for task_id, raw in rows:
            try:
                checkpoint = json.loads(raw or "{}")
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"task checkpoint is invalid during 11->12 migration: {task_id}") from exc
            if not isinstance(checkpoint, dict):
                raise RuntimeError(f"task checkpoint is invalid during 11->12 migration: {task_id}")
            state_data = checkpoint.get("state_data", {})
            if not isinstance(state_data, dict) or "_agent_task_scope" not in state_data:
                continue
            scope = state_data["_agent_task_scope"]
            if not isinstance(scope, dict):
                raise RuntimeError(f"task scope is invalid during 11->12 migration: {task_id}")
            if scope.get("version") == 2 and set(scope) == {"version", "repo_root"}:
                root = Path(scope["repo_root"]).expanduser().resolve(strict=True)
                if not root.is_dir():
                    raise RuntimeError(f"task checkout is unavailable during 11->12 migration: {task_id}")
                next_scope = {
                    "version": 3,
                    "project_id": project_scope_id(root),
                    "worktree_id": worktree_scope_id(root),
                    "repo_root": str(root),
                }
                state_data["_agent_task_scope"] = next_scope
                converted.append((json.dumps(checkpoint, ensure_ascii=False), str(task_id)))
            elif (
                scope.get("version") == 3
                and set(scope) == {"version", "project_id", "worktree_id", "repo_root"}
            ):
                root = Path(scope["repo_root"]).expanduser().resolve(strict=True)
                if (
                    scope["project_id"] != project_scope_id(root)
                    or scope["worktree_id"] != worktree_scope_id(root)
                ):
                    raise RuntimeError(f"task scope identity mismatch during 11->12 migration: {task_id}")
            else:
                raise RuntimeError(f"unsupported task scope during 11->12 migration: {task_id}")
        if migrate:
            con.execute("BEGIN IMMEDIATE")
            try:
                for checkpoint_json, task_id in converted:
                    changed = con.execute(
                        "UPDATE agent_tasks_projection SET checkpoint=? WHERE task_id=?",
                        (checkpoint_json, task_id),
                    ).rowcount
                    if changed != 1:
                        raise RuntimeError(f"task changed during 11->12 migration: {task_id}")
                con.commit()
            except Exception:
                con.rollback()
                raise
        elif converted:
            return False
        return con.execute("PRAGMA quick_check").fetchone() == ("ok",)


def _state_schema_v12(state: Path) -> bool:
    return _state_schema_v11(state) and _task_scopes_v12(state, migrate=False)


def _migrate_task_scopes_11_to_12(state: Path) -> None:
    if not _task_scopes_v12(state, migrate=True):
        raise RuntimeError("task scope migration failed verification after 11->12 conversion")


def _task_scopes_v13(state: Path, *, migrate: bool) -> bool:
    database = state / "agent_state.sqlite"
    if migrate:
        from local_ai_hub.agent_state_migration import migrate_runtime_task_scopes_on_update

        migrate_runtime_task_scopes_on_update(state)
    if not database.is_file():
        return True
    if database.is_symlink():
        return False
    try:
        with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=2.0)) as con:
            if con.execute("PRAGMA quick_check").fetchone() != ("ok",):
                return False
            tables = {str(row[0]) for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "agent_tasks_projection" not in tables:
                return True
            for (raw,) in con.execute("SELECT checkpoint FROM agent_tasks_projection"):
                try:
                    checkpoint = json.loads(raw or "{}")
                except (TypeError, ValueError):
                    return False
                if not isinstance(checkpoint, dict):
                    return False
                state_data = checkpoint.get("state_data", {})
                if not isinstance(state_data, dict):
                    return False
                scope = state_data.get("_agent_task_scope")
                if scope is None:
                    continue
                if not isinstance(scope, dict):
                    return False
                if set(scope) != {"version", "project_id", "worktree_id", "repo_root", "snapshot_id"}:
                    return False
                if scope.get("version") != 4 or any(
                    not isinstance(scope.get(key), str) or not scope[key]
                    for key in ("project_id", "worktree_id", "repo_root", "snapshot_id")
                ):
                    return False
    except (OSError, sqlite3.Error):
        return False
    return True


def _state_schema_v13(state: Path) -> bool:
    return _state_schema_v11(state) and _task_scopes_v13(state, migrate=False)


def _migrate_task_scopes_12_to_13(state: Path) -> None:
    if not _task_scopes_v13(state, migrate=True):
        raise RuntimeError("task scope migration failed verification after 12->13 conversion")


def _migrate_agent_schema_6_to_7(state: Path) -> None:
    database = state / "agent_state.sqlite"
    if database.exists():
        if not database.is_file() or database.is_symlink():
            raise RuntimeError(f"agent state path is not a regular database file: {database}")
        with closing(sqlite3.connect(database, timeout=15.0)) as con:
            con.execute("PRAGMA busy_timeout=15000")
            con.execute("BEGIN IMMEDIATE")
            tables = {str(row[0]) for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            relation = _table_signature(con, "agent_entity_relations") if "agent_entity_relations" in tables else None
            if relation == _RELATION_V6:
                con.execute(
                    "ALTER TABLE agent_entity_relations ADD COLUMN repository_id TEXT NOT NULL DEFAULT ''"
                )
            elif relation is not None and relation != _RELATION_V7:
                raise RuntimeError("unsupported agent_entity_relations schema for state 6->7 migration")

            embeddings = _table_signature(con, "agent_memory_embeddings") if "agent_memory_embeddings" in tables else None
            if embeddings == _EMBEDDINGS_V5:
                for definition in (
                    "embedding_space_id TEXT NOT NULL DEFAULT ''",
                    "model_name TEXT NOT NULL DEFAULT ''",
                    "dimension INTEGER NOT NULL DEFAULT 0",
                ):
                    con.execute(f"ALTER TABLE agent_memory_embeddings ADD COLUMN {definition}")
            elif embeddings is not None and embeddings != _EMBEDDINGS_V7:
                raise RuntimeError("unsupported agent_memory_embeddings schema for state 6->7 migration")
            con.commit()
            if con.execute("PRAGMA quick_check").fetchone() != ("ok",):
                raise RuntimeError("agent state database failed integrity check after 6->7 migration")
    _migrate_preprocess_schema_6_to_7(state)


def _migrate_legacy_board_7_to_8(state: Path) -> None:
    migrate_legacy_board_database(state)


def _migrate_endpoint_stats_8_to_9(state: Path) -> None:
    database = state / "endpoint_stats.sqlite3"
    if not database.exists():
        if any((state / f"{database.name}{suffix}").exists() for suffix in ("-wal", "-shm")):
            raise RuntimeError("endpoint statistics sidecar exists without its database")
        return
    if not database.is_file() or database.is_symlink():
        raise RuntimeError("endpoint statistics path is not a regular database file")
    uri = database.resolve().as_uri() + "?mode=rw"
    with closing(sqlite3.connect(uri, uri=True, timeout=15.0)) as con:
        con.execute("PRAGMA busy_timeout=15000")
        if con.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise RuntimeError("endpoint statistics database failed integrity check")
        tables = {
            str(row[0]) for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        if tables - _ENDPOINT_STATS_ALLOWED_TABLES:
            raise RuntimeError("endpoint statistics database has unsupported tables")
        if "endpoint_stats_exact" in tables and _table_signature(con, "endpoint_stats_exact") != ENDPOINT_STATS_TABLE_SIGNATURE:
            raise RuntimeError("unsupported exact endpoint statistics schema for state 8->9 migration")
        if "endpoint_call_ids" in tables and _table_signature(con, "endpoint_call_ids") != ENDPOINT_CALL_IDS_TABLE_SIGNATURE:
            raise RuntimeError("unsupported endpoint call-id schema for state 8->9 migration")

        legacy = "endpoint_stats" in tables
        archived = "endpoint_stats_basename_archive" in tables
        if legacy and archived:
            raise RuntimeError("endpoint statistics legacy table and archive both exist")
        if legacy and _table_signature(con, "endpoint_stats") != ENDPOINT_STATS_TABLE_SIGNATURE:
            raise RuntimeError("unsupported basename endpoint statistics schema for state 8->9 migration")
        if archived and _table_signature(con, "endpoint_stats_basename_archive") != ENDPOINT_STATS_TABLE_SIGNATURE:
            raise RuntimeError("unsupported endpoint statistics archive schema for state 8->9 migration")

        if legacy:
            con.execute("BEGIN IMMEDIATE")
            try:
                before = _endpoint_stats_row_digest(con, "endpoint_stats")
                before_count = con.execute("SELECT COUNT(*) FROM endpoint_stats").fetchone()[0]
                for index in ("idx_ep_stats_root", "idx_ep_stats_item"):
                    row = con.execute(
                        "SELECT tbl_name FROM sqlite_master WHERE type='index' AND name=?", (index,)
                    ).fetchone()
                    if row is not None:
                        if row[0] != "endpoint_stats":
                            raise RuntimeError(f"unexpected endpoint statistics index owner: {index}")
                        con.execute(f'DROP INDEX "{index}"')
                con.execute("ALTER TABLE endpoint_stats RENAME TO endpoint_stats_basename_archive")
                after = _endpoint_stats_row_digest(con, "endpoint_stats_basename_archive")
                after_count = con.execute("SELECT COUNT(*) FROM endpoint_stats_basename_archive").fetchone()[0]
                if before != after or before_count != after_count:
                    raise RuntimeError("endpoint statistics archive verification failed")
                con.commit()
            except Exception:
                con.rollback()
                raise
        if con.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise RuntimeError("endpoint statistics database failed integrity check after 8->9 migration")


def _migrate_laya_telemetry_9_to_10(state: Path) -> None:
    database = state / "telemetry.sqlite3"
    if not database.exists():
        if any((state / f"{database.name}{suffix}").exists() for suffix in ("-wal", "-shm")):
            raise RuntimeError("telemetry sidecar exists without its database")
        return
    if not database.is_file() or database.is_symlink():
        raise RuntimeError("telemetry path is not a regular database file")
    uri = database.resolve().as_uri() + "?mode=rw"
    with closing(sqlite3.connect(uri, uri=True, timeout=15.0)) as con:
        con.execute("PRAGMA busy_timeout=15000")
        if con.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise RuntimeError("telemetry database failed integrity check")
        tables = {
            str(row[0]) for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        if "snapshots" not in tables:
            return
        if _table_signature(con, "snapshots") != _TELEMETRY_SNAPSHOT_SIGNATURE:
            raise RuntimeError("unsupported snapshots table schema for state 9->10 migration")

        rows = con.execute(
            "SELECT id, metrics_json FROM snapshots WHERE name='laya_decision'"
        ).fetchall()
        converted: list[tuple[int, str, str]] = []
        for row_id, raw in rows:
            try:
                metadata = normalize_laya_decision_metadata(load_telemetry_json(raw))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if not isinstance(metadata, dict) or frozenset(metadata) != _LAYA_DECISION_PRE_RUNTIME_FIELDS:
                continue
            upgraded = {**metadata, **{field: None for field in _LAYA_DECISION_FIELDS - _LAYA_DECISION_PRE_RUNTIME_FIELDS}}
            encoded = json.dumps(upgraded, ensure_ascii=False, separators=(",", ":"))
            converted.append((int(row_id), str(raw), encoded))

        if converted:
            con.execute("BEGIN IMMEDIATE")
            try:
                for row_id, before, after in converted:
                    result = con.execute(
                        "UPDATE snapshots SET metrics_json=? WHERE id=? AND name='laya_decision' AND metrics_json=?",
                        (after, row_id, before),
                    )
                    if result.rowcount != 1:
                        raise RuntimeError("Laya telemetry row changed during state 9->10 migration")
                if not _telemetry_snapshots_are_v10(con):
                    raise RuntimeError("Laya telemetry migration output failed verification")
                con.commit()
            except Exception:
                con.rollback()
                raise
        if con.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise RuntimeError("telemetry database failed integrity check after 9->10 migration")


# Add only verified N -> N+1 transformations. Runtime startup never guesses a schema.
MIGRATIONS: tuple[StateMigration, ...] = (
    StateMigration(6, 7, _migrate_agent_schema_6_to_7, _state_schema_v7),
    StateMigration(7, 8, _migrate_legacy_board_7_to_8, _state_schema_v8),
    StateMigration(8, 9, _migrate_endpoint_stats_8_to_9, _state_schema_v9),
    StateMigration(9, 10, _migrate_laya_telemetry_9_to_10, _state_schema_v10),
    StateMigration(10, 11, _migrate_incident_placeholder_10_to_11, _state_schema_v11),
    StateMigration(11, 12, _migrate_task_scopes_11_to_12, _state_schema_v12),
    StateMigration(12, 13, _migrate_task_scopes_12_to_13, _state_schema_v13),
)


def _is_link(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & _REPARSE_POINT)


def _reject_links(root: Path) -> None:
    if _is_link(root):
        raise ValueError(f"state migration path is a symlink or junction: {root}")
    for base, dirs, files in os.walk(root, followlinks=False):
        parent = Path(base)
        for name in (*dirs, *files):
            item = parent / name
            if _is_link(item):
                raise ValueError(f"state migration refuses symlink or junction: {item}")


def _reject_link_components(path: Path) -> None:
    absolute = Path(os.path.abspath(os.fspath(path)))
    if any(_is_link(component) for component in (absolute, *absolute.parents)):
        raise ValueError(f"state migration path contains a symlink or junction: {absolute}")


def _is_process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, pid)
            if handle:
                try:
                    exit_code = ctypes.c_ulong()
                    if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                        return exit_code.value == 259  # STILL_ACTIVE
                    return False
                finally:
                    kernel32.CloseHandle(handle)
        except Exception:
            pass
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _estimate_required_space(source: Path) -> int:
    total = 0
    if source.is_dir():
        for item in source.rglob("*"):
            if item.is_file() and not _is_link(item):
                try:
                    total += item.stat().st_size
                except OSError:
                    pass
    return max(10 * 1024 * 1024, int(total * 2.5))


def _check_disk_space(path: Path, required_bytes: int) -> None:
    usage = None
    try:
        usage = shutil.disk_usage(path)
    except Exception:
        pass
    if usage is not None and usage.free < required_bytes:
        raise OSError(
            f"insufficient disk space at {path}: {usage.free} bytes free, "
            f"{required_bytes} bytes required"
        )


def _is_sqlite_database(path: Path) -> bool:
    if path.suffix in {".sqlite", ".sqlite3", ".db"}:
        return True
    try:
        if path.is_file() and path.stat().st_size >= 16:
            with path.open("rb") as f:
                return f.read(16) == b"SQLite format 3\x00"
    except OSError:
        pass
    return False


def discard_stale_migration_artifacts(
    state_dir: Path | str,
    *,
    retention_count: int = 1,
) -> list[str]:
    """Delete stale staging dirs and verified migration backups exceeding retention.

    Never deletes:
    - The last functional recovery snapshot (keeps at least 1 verified backup).
    - Unverified or unknown directories (spoofed prefix, missing or invalid manifest).
    - Active migration staging directories with running processes.
    - Symlinks or junctions (raises ValueError).
    """
    state = Path(state_dir).absolute()
    _reject_link_components(state)
    if not state.exists():
        return []
    if not state.is_dir():
        raise ValueError(f"state migration cleanup requires an existing directory: {state}")

    _ = read_state_version(state)
    removed: list[str] = []

    # 1. Clean up stale staging directories (.{state.name}.migration-*)
    for candidate in sorted(state.parent.iterdir()):
        if candidate.name.startswith(f".{state.name}.migration-") and candidate.is_dir():
            _reject_links(candidate)
            lock_file = candidate / ".migration_lock.json"
            if lock_file.is_file():
                try:
                    lock_data = json.loads(lock_file.read_text(encoding="utf-8"))
                    pid = lock_data.get("pid")
                    if isinstance(pid, int) and _is_process_alive(pid):
                        # Migration process is actively running, do not touch
                        continue
                    # Process is confirmed dead, lock is stale -> delete
                    shutil.rmtree(candidate, ignore_errors=True)
                    removed.append(str(candidate))
                    continue
                except Exception:
                    pass
            # If no lock file, skip if modified within last 10 seconds to prevent race
            try:
                if time.time() - candidate.stat().st_mtime < 10:
                    continue
            except OSError:
                pass
            shutil.rmtree(candidate, ignore_errors=True)
            removed.append(str(candidate))

    # 2. Inspect candidate backups ({state.name}.backup-v*)
    verified_backups: list[tuple[int, int, Path]] = []  # (version, timestamp_ns, path)
    for candidate in sorted(state.parent.iterdir()):
        if candidate.name.startswith(f"{state.name}.backup-v") and candidate.is_dir():
            _reject_links(candidate)
            suffix = candidate.name.removeprefix(f"{state.name}.backup-v")
            version_text, separator, timestamp_text = suffix.partition("-")
            if not separator or not version_text.isdigit() or not timestamp_text.isdigit():
                continue
            manifest_file = candidate / "manifest.json"
            if not manifest_file.is_file():
                continue
            try:
                manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
                if manifest.get("format") != 1 or manifest.get("kind") != "state_migration_backup":
                    continue
                manifest_files = manifest.get("files", {})
                if not isinstance(manifest_files, dict) or not manifest_files:
                    continue
                files_ok = True
                for rel_path, file_meta in manifest_files.items():
                    target_file = candidate / rel_path
                    if not target_file.is_file() or target_file.stat().st_size != file_meta.get("size_bytes"):
                        files_ok = False
                        break
                if not files_ok:
                    continue
                verified_backups.append((int(version_text), int(timestamp_text), candidate))
            except Exception:
                continue

    # 3. Apply retention policy:
    # Always keep at least 1 functional recovery snapshot
    keep_count = max(1, retention_count)
    verified_backups.sort(key=lambda item: item[1])  # sort by timestamp_ns ascending

    if len(verified_backups) > keep_count:
        to_prune = verified_backups[:-keep_count]
        for _, _, backup_path in to_prune:
            _reject_links(backup_path)
            shutil.rmtree(backup_path, ignore_errors=True)
            removed.append(str(backup_path))

    return removed


def _tree_digest(root: Path, *, exclude_names: set[str] | None = None) -> str:
    digest = hashlib.sha256()
    exclude = exclude_names or set()
    for item in sorted(root.rglob("*"), key=lambda path: path.relative_to(root).as_posix()):
        if _is_link(item):
            raise ValueError(f"state migration refuses symlink or junction: {item}")
        if item.name in exclude or item.name.endswith("-shm"):
            continue
        relative = item.relative_to(root).as_posix().encode("utf-8")
        if item.is_dir():
            digest.update(b"D\0" + relative + b"\0")
        elif item.is_file():
            digest.update(b"F\0" + relative + b"\0")
            with item.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            digest.update(b"\0")
        else:
            raise ValueError(f"unsupported state entry: {item}")
    return digest.hexdigest()


def _make_backup(source: Path, version: int) -> Path:
    _reject_link_components(source)
    _reject_links(source)
    _check_disk_space(source.parent, _estimate_required_space(source))

    timestamp_ns = time.time_ns()
    backup = source.with_name(f"{source.name}.backup-v{version}-{timestamp_ns}")
    backup.mkdir(parents=False, exist_ok=False)

    try:
        # Copy files: use SQLite backup API for databases to produce clean, consistent snapshots
        for root_dir, dirnames, filenames in os.walk(source, followlinks=False):
            rel_dir = Path(root_dir).relative_to(source)
            target_dir = backup / rel_dir
            target_dir.mkdir(parents=True, exist_ok=True)

            for fn in filenames:
                src_file = Path(root_dir) / fn
                dst_file = target_dir / fn

                # SQLite WAL sidecars (-wal, -shm) are integrated via backup API into main DB, skip loose sidecars
                if fn.endswith("-wal") or fn.endswith("-shm"):
                    base_db = Path(root_dir) / fn.removesuffix("-wal").removesuffix("-shm")
                    if base_db.is_file() and _is_sqlite_database(base_db):
                        continue

                if _is_sqlite_database(src_file):
                    # Historical `.corrupt-*` snapshots are retained as evidence,
                    # not migrated databases. SQLite's backup API refuses damaged
                    # files, so preserve these byte-for-byte in the verified archive.
                    if ".corrupt-" in fn.casefold():
                        shutil.copy2(src_file, dst_file)
                        continue
                    with closing(sqlite3.connect(f"file:{src_file.resolve()}?mode=ro", uri=True)) as src_con, \
                         closing(sqlite3.connect(dst_file)) as dst_con:
                        src_con.backup(dst_con)
                        row = dst_con.execute("PRAGMA quick_check").fetchone()
                        if row != ("ok",):
                            raise OSError(f"SQLite backup failed quick check: {src_file} ({row})")
                else:
                    shutil.copy2(src_file, dst_file)

        # Record verified file manifest
        manifest_files: dict[str, dict[str, Any]] = {}
        for item in sorted(backup.rglob("*"), key=lambda p: p.relative_to(backup).as_posix()):
            if item.is_file():
                rel = item.relative_to(backup).as_posix()
                hasher = hashlib.sha256()
                with item.open("rb") as f:
                    for chunk in iter(lambda: f.read(1024 * 1024), b""):
                        hasher.update(chunk)
                manifest_files[rel] = {
                    "sha256": hasher.hexdigest(),
                    "size_bytes": item.stat().st_size,
                }

        import datetime as dt
        manifest = {
            "format": 1,
            "kind": "state_migration_backup",
            "source_version": version,
            "timestamp_ns": timestamp_ns,
            "created_at_iso": dt.datetime.now(dt.timezone.utc).isoformat(),
            "files": manifest_files,
        }
        (backup / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        return backup
    except Exception:
        shutil.rmtree(backup, ignore_errors=True)
        raise


def _apply_chain(
    state_dir: Path,
    migrations: tuple[StateMigration, ...],
    current: int,
) -> tuple[Path, list[str]]:
    backup = _make_backup(state_dir, current)
    source_digest = _tree_digest(state_dir, exclude_names={"manifest.json", ".migration_lock.json"})
    stage: Path | None = None
    try:
        stage = Path(tempfile.mkdtemp(prefix=f".{state_dir.name}.migration-", dir=state_dir.parent))
        (stage / ".migration_lock.json").write_text(
            json.dumps({"pid": os.getpid(), "timestamp_ns": time.time_ns(), "state": str(state_dir)}),
            encoding="utf-8",
        )
        stage_work = stage / "work"
        shutil.copytree(backup, stage_work, symlinks=False)
        (stage_work / "manifest.json").unlink(missing_ok=True)

        step_version = current
        for migration in migrations:
            if migration.source_version != step_version or migration.target_version != step_version + 1:
                raise ValueError("state migrations must be consecutive N-to-N+1 steps")
            migration.migrate(stage_work)
            if migration.verify(stage_work) is not True:
                raise ValueError(f"state migration verification failed for {step_version}->{step_version + 1}")
            write_state_version(stage_work, version=step_version + 1, migrated_from=step_version)
            _reject_links(stage_work)
            if migration.verify(stage_work) is not True:
                raise ValueError(f"state migration post-marker verification failed for {step_version}->{step_version + 1}")
            step_version += 1

        if _tree_digest(state_dir) != source_digest:
            raise OSError(
                f"state changed after verified backup {backup}; "
                "refusing to replace the original state"
            )
        swap = state_dir.with_name(f".{state_dir.name}.pre-migration-{time.time_ns()}")
        os.replace(state_dir, swap)
        try:
            os.replace(stage_work, state_dir)
        except OSError as install_error:
            try:
                os.replace(swap, state_dir)
            except OSError as restore_error:
                raise RuntimeError(
                    f"staged state install failed and original could not be restored; "
                    f"original is at {swap}, verified backup at {backup}: {restore_error}"
                ) from install_error
            raise
        cleanup_warnings: list[str] = []
        try:
            shutil.rmtree(swap)
        except OSError as exc:
            cleanup_warnings.append(f"old-state swap retained at {swap}: {exc}")
        return backup, cleanup_warnings
    except Exception as exc:
        raise StateMigrationError(backup, exc) from exc
    finally:
        if stage is not None and stage.exists():
            shutil.rmtree(stage, ignore_errors=True)



def _apply_chain_in_place(
    state_dir: Path,
    migrations: tuple[StateMigration, ...],
    current: int,
) -> list[str]:
    """Apply an explicitly unbacked operator migration without copying the state tree."""
    for migration in migrations:
        if migration.source_version != current or migration.target_version != current + 1:
            raise ValueError("state migrations must be consecutive N-to-N+1 steps")
        migration.migrate(state_dir)
        if migration.verify(state_dir) is not True:
            raise ValueError(f"state migration verification failed for {current}->{current + 1}")
        write_state_version(state_dir, version=current + 1, migrated_from=current)
        _reject_links(state_dir)
        if migration.verify(state_dir) is not True:
            raise ValueError(f"state migration post-marker verification failed for {current}->{current + 1}")
        current += 1
    return []


def inspect_state_migration_path(
    state_dir: Path | str,
    *,
    migrations: tuple[StateMigration, ...] = MIGRATIONS,
    target_version: int = CURRENT_STATE_VERSION,
) -> dict[str, object]:
    """Validate state and the full migration chain without changing state."""
    if type(target_version) is not int or target_version < 1:
        raise ValueError("target_version must be a positive integer")
    root = Path(state_dir)
    _reject_link_components(root)
    if not root.exists():
        return {"status": "initialize", "version": target_version, "backups": []}
    _reject_links(root)
    if not root.is_dir():
        raise RuntimeError(f"state path is not a directory; state unchanged: {root}")
    current = read_state_version(root)
    if current is None:
        if (root / "state_version.json").exists():
            raise RuntimeError("state version marker is corrupt; state is unchanged. See docs/INSTALLER_RECOVERY.md.")
        unexpected = sorted(item.name for item in root.iterdir() if item.name not in BOOTSTRAP_STATE_ENTRIES)
        if unexpected:
            if not _is_supported_unversioned_v5_state(root):
                raise RuntimeError(
                    f"unversioned state contains unsupported data {unexpected}; state is unchanged. "
                    "See docs/INSTALLER_RECOVERY.md."
                )
            current = 6
        else:
            return {"status": "initialize", "version": target_version, "backups": []}
    if current > target_version:
        raise RuntimeError(f"state version {current} is newer than supported version {target_version}; state unchanged")
    if current == target_version:
        return {"status": "current", "version": current, "backups": []}
    by_source: dict[int, StateMigration] = {}
    for migration in migrations:
        if migration.source_version in by_source or migration.target_version != migration.source_version + 1:
            raise ValueError("migration registry has duplicate or non-consecutive versions")
        by_source[migration.source_version] = migration
    missing = [version for version in range(current, target_version) if version not in by_source]
    if missing:
        version = missing[0]
        raise RuntimeError(
            f"no verified state migration registered for {version}->{version + 1}; "
            "state is unchanged. See docs/INSTALLER_RECOVERY.md."
        )
    return {"status": "migratable", "version": current, "backups": [], "migration_count": target_version - current}


def run_state_migrations(
    state_dir: Path | str,
    *,
    migrations: tuple[StateMigration, ...] = MIGRATIONS,
    target_version: int = CURRENT_STATE_VERSION,
    backup_current: bool = False,
    create_backup: bool = True,
) -> dict[str, object]:
    root = Path(state_dir)
    plan = inspect_state_migration_path(root, migrations=migrations, target_version=target_version)
    if plan["status"] == "initialize":
        result = ensure_state_version(root, target_version)
        return {**result, "backups": []}
    current = int(plan["version"])
    if plan["status"] == "current":
        backups = [str(_make_backup(root, current))] if backup_current and create_backup else []
        return {"status": "current", "version": current, "backups": backups}
    by_source: dict[int, StateMigration] = {}
    for migration in migrations:
        by_source[migration.source_version] = migration
    steps = tuple(by_source[version] for version in range(current, target_version))
    if create_backup:
        backup, cleanup_warnings = _apply_chain(root, steps, current)
        backups = [str(backup)]
    else:
        cleanup_warnings = _apply_chain_in_place(root, steps, current)
        backups = []
    return {
        "status": "migrated",
        "version": target_version,
        "backups": backups,
        "warnings": cleanup_warnings,
    }


def restore_state_backup(state_dir: Path, backup: Path) -> Path | None:
    """Restore a copy of the verified backup, retaining failed candidate state."""
    _reject_link_components(state_dir)
    _reject_link_components(backup)
    _reject_links(backup)
    manifest_file = backup / "manifest.json"
    if manifest_file.is_file():
        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            if manifest.get("format") == 1 and manifest.get("kind") == "state_migration_backup":
                files = manifest.get("files", {})
                for rel, meta in files.items():
                    target_file = backup / rel
                    if not target_file.is_file() or target_file.stat().st_size != meta.get("size_bytes"):
                        raise OSError(f"state backup verification failed for {rel}: corrupt or missing file")
        except (json.JSONDecodeError, KeyError) as exc:
            raise OSError(f"state backup manifest is corrupt: {backup}: {exc}") from exc

    with tempfile.TemporaryDirectory(prefix=f".{state_dir.name}.restore-", dir=state_dir.parent) as temporary:
        restored = Path(temporary) / "state"
        shutil.copytree(backup, restored, symlinks=False)
        (restored / "manifest.json").unlink(missing_ok=True)
        if _tree_digest(backup, exclude_names={"manifest.json"}) != _tree_digest(restored, exclude_names={"manifest.json"}):
            raise OSError(f"state restore staging failed verification: {backup}")
        failed = None
        if state_dir.exists():
            failed = state_dir.with_name(f".{state_dir.name}.failed-update-{time.time_ns()}")
            os.replace(state_dir, failed)
        try:
            os.replace(restored, state_dir)
        except OSError:
            if failed is not None:
                os.replace(failed, state_dir)
            raise
    return failed
