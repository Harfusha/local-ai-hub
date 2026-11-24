"""Scoped, rollbackable removal of persisted embedding payloads for Hub 8.0."""

from __future__ import annotations

import json
import os
import shutil
from contextlib import closing
from pathlib import Path
from pathlib import PurePosixPath
import sqlite3
import time
from typing import Any

RESET_VERSION = "8.0"
_DATABASES = (
    "rag.sqlite3", "cache.sqlite", "cache.sqlite3", "semantic-cache.sqlite3",
    "agent_state.sqlite", "agent_state.sqlite3",
)
_ARCHIVE_ROOT_NAMES = {"backups", "recovery"}
_ARCHIVE_PREFIXES = ("rag-", "state.embedding-reset-v8.0-")


def _is_link(path: Path) -> bool:
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


class EmbeddingResetMigrationError(RuntimeError):
    def __init__(self, backup_path: Path, cause: Exception) -> None:
        self.backup_path = backup_path
        super().__init__(f"embedding reset failed; scoped database backup retained at {backup_path}: {cause}")


def _connect(path: Path, *, read_only: bool = False) -> sqlite3.Connection:
    if read_only:
        uri = path.resolve().as_uri() + "?mode=ro"
        return sqlite3.connect(uri, uri=True, timeout=15.0)
    con = sqlite3.connect(path, timeout=15.0)
    con.execute("PRAGMA busy_timeout=15000")
    return con


def _tables(con: sqlite3.Connection) -> set[str]:
    return {str(row[0]) for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _embedding_databases(state: Path) -> tuple[Path, ...]:
    """Find active stores and known state snapshots without traversing model or project data."""
    candidates: set[Path] = set()
    archive_roots: list[Path] = []
    for name in _DATABASES:
        path = state / name
        if path.exists():
            if _is_link(path) or not path.is_file():
                raise RuntimeError(f"embedding reset refuses non-file database: {path}")
            candidates.add(path)
    for child in state.iterdir():
        if child.name.casefold() not in _ARCHIVE_ROOT_NAMES and not child.name.casefold().startswith(_ARCHIVE_PREFIXES):
            continue
        if _is_link(child) or not child.is_dir():
            raise RuntimeError(f"embedding reset refuses linked or invalid archive directory: {child}")
        archive_roots.append(child)
    state_identity = state.resolve()
    database_names = set(_DATABASES)
    for archive_root in archive_roots:
        for current, directories, files in os.walk(archive_root, followlinks=False):
            current_path = Path(current)
            for name in tuple(directories):
                child = current_path / name
                if _is_link(child):
                    raise RuntimeError(f"embedding reset refuses linked archive directory: {child}")
            for name in files:
                if name not in database_names:
                    continue
                path = current_path / name
                if _is_link(path) or not path.is_file():
                    raise RuntimeError(f"embedding reset refuses non-file archived database: {path}")
                if not path.resolve().is_relative_to(state_identity):
                    raise RuntimeError(f"embedding reset archive escaped state directory: {path}")
                candidates.add(path)
    return tuple(sorted(candidates))


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in con.execute(f'PRAGMA table_info("{table}")')}


def _require(con: sqlite3.Connection, table: str, columns: set[str]) -> bool:
    if table not in _tables(con):
        return False
    missing = columns - _columns(con, table)
    if missing:
        raise RuntimeError(f"embedding reset found an incompatible {table} schema: missing {sorted(missing)}")
    return True


def _backup(state: Path, databases: tuple[Path, ...]) -> Path:
    backup = state.with_name(f"{state.name}.embedding-reset-v{RESET_VERSION}-{time.time_ns()}")
    backup.mkdir(parents=False, exist_ok=False)
    manifest: dict[str, Any] = {"format": 1, "migration": RESET_VERSION, "databases": []}
    try:
        for source in databases:
            relative = source.relative_to(state).as_posix()
            if source.is_symlink() or not source.is_file():
                raise RuntimeError(f"embedding reset refuses linked or missing database: {source}")
            target = backup.joinpath(*PurePosixPath(relative).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with closing(_connect(source, read_only=True)) as src, closing(sqlite3.connect(target)) as dst:
                src.backup(dst)
                if dst.execute("PRAGMA quick_check").fetchone() != ("ok",):
                    raise RuntimeError(f"embedding reset backup failed quick check: {relative}")
            manifest["databases"].append(relative)
        (backup / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        return backup
    except Exception:
        shutil.rmtree(backup)
        raise


def _restore_database(target: Path, source: Path) -> None:
    with closing(sqlite3.connect(source)) as src, closing(sqlite3.connect(target)) as dst:
        src.backup(dst)
        if dst.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise RuntimeError(f"restored database failed quick check: {target.name}")


def restore_embedding_reset_backup(state_dir: Path | str, backup_dir: Path | str) -> None:
    """Restore only databases named by a verified migration backup manifest."""
    state, backup = Path(state_dir).absolute(), Path(backup_dir).absolute()
    if state.is_symlink() or backup.is_symlink() or backup.parent != state.parent:
        raise RuntimeError("embedding reset restore refuses linked paths")
    manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    names = manifest.get("databases") if manifest.get("format") == 1 else None
    if (manifest.get("migration") != RESET_VERSION or not backup.name.startswith(f"{state.name}.embedding-reset-v{RESET_VERSION}-")
            or not isinstance(names, list)):
        raise RuntimeError("embedding reset backup manifest is invalid")
    relative_paths = [_validated_database_relative_path(name) for name in names]
    if len(set(relative_paths)) != len(relative_paths):
        raise RuntimeError("embedding reset backup manifest contains duplicate databases")
    for name in names:
        relative = _validated_database_relative_path(name)
        source, target = backup.joinpath(*relative.parts), state.joinpath(*relative.parts)
        if _path_has_link(backup, relative) or not source.is_file():
            raise RuntimeError(f"embedding reset backup is incomplete: {name}")
        if _path_has_link(state, relative) or not target.parent.is_dir():
            raise RuntimeError(f"embedding reset restore target is invalid: {name}")
        _restore_database(target, source)


def discard_embedding_reset_backup(state_dir: Path | str, backup_dir: Path | str) -> None:
    """Remove only a complete, generated v8 reset backup after successful activation."""
    state, backup = Path(state_dir).absolute(), Path(backup_dir).absolute()
    if state.is_symlink() or _is_link(backup) or backup.parent != state.parent:
        raise RuntimeError("embedding reset cleanup refuses linked or out-of-scope paths")
    manifest_path = backup / "manifest.json"
    if _is_link(manifest_path) or not manifest_path.is_file():
        raise RuntimeError("embedding reset cleanup requires a regular migration manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    names = manifest.get("databases") if manifest.get("format") == 1 else None
    if (manifest.get("migration") != RESET_VERSION
            or not backup.name.startswith(f"{state.name}.embedding-reset-v{RESET_VERSION}-")
            or not isinstance(names, list)):
        raise RuntimeError("embedding reset cleanup refused an invalid backup manifest")
    relative_paths = [_validated_database_relative_path(name) for name in names]
    if len(set(relative_paths)) != len(relative_paths):
        raise RuntimeError("embedding reset cleanup found duplicate databases")
    expected_files = set(relative_paths) | {PurePosixPath("manifest.json")}
    actual_files: set[PurePosixPath] = set()
    expected_directories = {parent for item in expected_files for parent in item.parents if str(parent) != "."}
    for current, directories, files in os.walk(backup, followlinks=False):
        current_path = Path(current)
        current_relative = PurePosixPath(current_path.relative_to(backup).as_posix())
        if str(current_relative) == ".":
            current_relative = PurePosixPath()
        for directory in directories:
            path = current_path / directory
            relative = current_relative / directory
            if _is_link(path) or relative not in expected_directories:
                raise RuntimeError(f"embedding reset cleanup found unexpected backup directory: {relative}")
        for filename in files:
            path = current_path / filename
            relative = current_relative / filename
            if _is_link(path) or relative not in expected_files:
                raise RuntimeError(f"embedding reset cleanup found unexpected backup content: {relative}")
            actual_files.add(relative)
    if actual_files != expected_files:
        raise RuntimeError("embedding reset cleanup found an incomplete backup")
    shutil.rmtree(backup)


def _validated_database_relative_path(value: Any) -> PurePosixPath:
    if not isinstance(value, str) or "\\" in value:
        raise RuntimeError("embedding reset backup manifest contains an invalid database path")
    relative = PurePosixPath(value)
    parts = relative.parts
    if (relative.is_absolute() or not parts or any(part in {"", ".", ".."} for part in parts)
            or parts[-1] not in _DATABASES):
        raise RuntimeError("embedding reset backup manifest contains an invalid database path")
    if len(parts) > 1 and (
        parts[0].casefold() not in _ARCHIVE_ROOT_NAMES
        and not parts[0].casefold().startswith(_ARCHIVE_PREFIXES)
    ):
        raise RuntimeError("embedding reset backup manifest contains an out-of-scope database path")
    return relative


def _path_has_link(root: Path, relative: PurePosixPath) -> bool:
    current = root
    for part in relative.parts:
        current /= part
        if _is_link(current):
            return True
    return False


def _clear_database(path: Path, *, is_rag: bool = False) -> None:
    with closing(_connect(path)) as con:
        con.execute("PRAGMA secure_delete=ON")
        tables = _tables(con)
        if is_rag:
            if _require(con, "chunks", {"embedding", "embedding_space"}):
                con.execute("UPDATE chunks SET embedding='[]', embedding_space='' WHERE embedding<>'[]' OR embedding_space<>''")
            if _require(con, "content_rag_chunks", {"embedding_blob", "embedding_space"}):
                con.execute("UPDATE content_rag_chunks SET embedding_blob=X'' WHERE length(embedding_blob)>0")
            if _require(con, "rag_meta", {"key", "value"}):
                con.execute("DELETE FROM rag_meta WHERE key LIKE 'workspace_embedding_space:%' OR key LIKE 'workspace_reindex_target:%'")
                con.execute("INSERT INTO rag_meta(key,value) VALUES('embedding_reset_version',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (RESET_VERSION,))
        elif path.name in {"cache.sqlite", "cache.sqlite3"} and "cache_entries" in tables:
            _require(con, "cache_entries", {"namespace"})
            con.execute("DELETE FROM cache_entries WHERE namespace='embeddings' OR namespace LIKE '%:embeddings'")
        elif path.name == "semantic-cache.sqlite3" and _require(con, "semantic_entries", {"vector_blob"}):
            con.execute("UPDATE semantic_entries SET vector_blob=X'' WHERE length(vector_blob)>0")
        elif path.name in {"agent_state.sqlite", "agent_state.sqlite3"} and _require(con, "agent_memory_embeddings", {"embedding"}):
            con.execute("DELETE FROM agent_memory_embeddings")
        con.commit()
        checkpoint = con.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if checkpoint and int(checkpoint[0]) != 0:
            raise RuntimeError(f"embedding reset could not checkpoint {path.name}: {checkpoint}")


def verify_embedding_reset(state_dir: Path | str) -> bool:
    state = Path(state_dir)
    if state.is_symlink() or not state.is_dir():
        return False
    try:
        paths = _embedding_databases(state)
    except (OSError, RuntimeError, ValueError):
        return False
    for path in paths:
        with closing(_connect(path, read_only=True)) as con:
            tables = _tables(con)
            if path.name == "rag.sqlite3":
                if path == state / "rag.sqlite3":
                    marker = con.execute("SELECT value FROM rag_meta WHERE key='embedding_reset_version'").fetchone() if "rag_meta" in tables else None
                    if marker != (RESET_VERSION,):
                        return False
                if "chunks" in tables and con.execute("SELECT 1 FROM chunks WHERE embedding<>'[]' OR embedding_space<>'' LIMIT 1").fetchone():
                    return False
                if "content_rag_chunks" in tables and con.execute("SELECT 1 FROM content_rag_chunks WHERE length(embedding_blob)>0 LIMIT 1").fetchone():
                    return False
            elif path.name in {"cache.sqlite", "cache.sqlite3"}:
                if "cache_entries" in tables and con.execute(
                    "SELECT 1 FROM cache_entries WHERE namespace='embeddings' OR namespace LIKE '%:embeddings' LIMIT 1"
                ).fetchone():
                    return False
            elif path.name == "semantic-cache.sqlite3":
                if "semantic_entries" in tables and con.execute(
                    "SELECT 1 FROM semantic_entries WHERE length(vector_blob)>0 LIMIT 1"
                ).fetchone():
                    return False
            elif path.name in {"agent_state.sqlite", "agent_state.sqlite3"}:
                if "agent_memory_embeddings" in tables and con.execute(
                    "SELECT 1 FROM agent_memory_embeddings LIMIT 1"
                ).fetchone():
                    return False
    return True


def clear_embedding_payloads(state_dir: Path | str) -> bool:
    """Clear vectors in a verified state snapshot that already has an updater backup."""
    state = Path(state_dir).absolute()
    if not state.is_dir() or state.is_symlink():
        raise ValueError("embedding cleanup requires an existing, unlinked state directory")
    for path in _embedding_databases(state):
        _clear_database(path, is_rag=path.name == "rag.sqlite3")
    if not verify_embedding_reset(state):
        raise RuntimeError(f"embedding cleanup verification failed: {state}")
    return True


def _reset_marker_present(state_dir: Path) -> bool:
    rag = state_dir / "rag.sqlite3"
    if not rag.exists():
        return False
    with closing(_connect(rag, read_only=True)) as con:
        marker = "rag_meta" in _tables(con) and con.execute(
            "SELECT 1 FROM rag_meta WHERE key='embedding_reset_version' AND value=?",
            (RESET_VERSION,),
        ).fetchone() is not None
    return bool(marker and verify_embedding_reset(state_dir))


def apply_embedding_reset(state_dir: Path | str) -> dict[str, Any]:
    """Clear stored vectors with a scoped snapshot and automatic rollback on error."""
    state = Path(state_dir).absolute()
    if not state.is_dir() or state.is_symlink():
        raise ValueError("embedding reset requires an existing, unlinked state directory")
    if _reset_marker_present(state):
        return {"status": "already_applied", "backup": None}
    databases = _embedding_databases(state)
    backup = _backup(state, databases)
    try:
        for path in databases:
            _clear_database(path, is_rag=path.name == "rag.sqlite3")
        if not verify_embedding_reset(state):
            raise RuntimeError("embedding reset postcondition failed")
    except Exception as exc:
        try:
            restore_embedding_reset_backup(state, backup)
        except Exception as restore_error:
            raise EmbeddingResetMigrationError(backup, RuntimeError(
                f"migration failed ({exc}); automatic rollback failed ({restore_error})"
            )) from exc
        raise EmbeddingResetMigrationError(backup, exc) from exc
    return {"status": "migrated", "backup": str(backup)}
