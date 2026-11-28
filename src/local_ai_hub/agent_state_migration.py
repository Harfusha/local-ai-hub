"""Bounded, updater-only import of portable project records from SQLite."""
from __future__ import annotations

import json
import hashlib
import os
import re
import sqlite3
import subprocess
import tempfile
import time
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .agent_state_inventory import _identity, _sidecars_absent
from .repo_knowledge import RepoKnowledgeStore, _encode, _path_for, validate_knowledge_file
from .repo_knowledge_batch import preview_knowledge_batch
from .repo_plan.schema_validation import RepoPlanConflictError, RepoPlanValidationError
from .project_identity import project_scope_id, repository_snapshot_id, worktree_scope_id

_MAX_BATCH = 16
_MAX_JSON_BYTES = 65536
_MAX_DATABASE_BYTES = 512 * 1024 * 1024
_MAX_DATABASE_ROWS = 100_000
_MAX_DATABASE_SNAPSHOT_SECONDS = 15.0
_MIGRATED_TABLES = ("agent_tasks_projection", "agent_memory_records", "agent_incidents")
_CHECKPOINT = "CASE WHEN json_valid(checkpoint) THEN checkpoint ELSE '{}' END"
_SCOPE = "$.state_data._agent_task_scope"
# Exact v2 scope marker only; no inference from user-supplied context, worktree,
# session, task ID, or a legacy path string.
_SCOPED = (
    f"json_type({_CHECKPOINT}, '{_SCOPE}') = 'object' "
    f"AND json_type({_CHECKPOINT}, '{_SCOPE}.version') = 'integer' "
    f"AND json_extract({_CHECKPOINT}, '{_SCOPE}.version') = 2 "
    f"AND json_type({_CHECKPOINT}, '{_SCOPE}.repo_root') = 'text' "
    f"AND length(json_extract({_CHECKPOINT}, '{_SCOPE}.repo_root')) > 0 "
    f"AND (SELECT COUNT(*) FROM json_each({_CHECKPOINT}, '{_SCOPE}')) = 2"
)


def _database_snapshot(db: Path) -> str:
    """Hash bounded migration inputs, not unrelated or free SQLite pages."""
    if (
        db.is_symlink() or getattr(db, "is_junction", lambda: False)()
        or not db.is_file() or not _sidecars_absent(db)
    ):
        raise RepoPlanValidationError("Legacy project state requires a clean regular database file")

    def identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(db, flags)
        with os.fdopen(fd, "rb", closefd=True) as stream:
            started = time.monotonic()
            before_fd = os.fstat(stream.fileno())
            before_path = db.stat()
            initial_fd = identity(before_fd)
            initial_path = identity(before_path)
            # Windows can report slightly different ctime_ns values through
            # fstat and path stat; compare identity, size, and mtime across
            # those views, then fence each view independently across the read.
            if initial_fd[:4] != initial_path[:4]:
                raise RepoPlanValidationError("Legacy project database path changed before snapshot")
            digest = hashlib.sha256()
            total = 0
            rows_seen = 0
            with closing(sqlite3.connect(db.as_uri() + "?mode=ro&immutable=1", uri=True, timeout=1.0)) as con:
                con.execute("PRAGMA query_only=ON")
                con.execute("PRAGMA trusted_schema=OFF")
                tables = {
                    str(row[0]): str(row[1] or "")
                    for row in con.execute(
                        "SELECT name,sql FROM sqlite_master WHERE type='table' AND name IN (?,?,?)",
                        _MIGRATED_TABLES,
                    )
                }
                for table in _MIGRATED_TABLES:
                    name = table.encode("ascii")
                    schema = tables.get(table, "").encode("utf-8")
                    total += len(schema) + len(name) + 12
                    if total > _MAX_DATABASE_BYTES:
                        raise RepoPlanValidationError("Legacy project migration inputs exceed the 512 MiB content limit")
                    digest.update(len(name).to_bytes(4, "big"))
                    digest.update(name)
                    digest.update(len(schema).to_bytes(8, "big"))
                    digest.update(schema)
                    if table not in tables:
                        continue
                    count = int(con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
                    if rows_seen + count > _MAX_DATABASE_ROWS:
                        raise RepoPlanValidationError("Legacy project migration inputs exceed the row limit")
                    rows_seen += count
                    cursor = con.execute(f'SELECT * FROM "{table}" ORDER BY rowid')
                    while True:
                        batch = cursor.fetchmany(256)
                        if not batch:
                            break
                        for row in batch:
                            digest.update(b"R")
                            for value in row:
                                if value is None:
                                    tag, encoded = b"N", b""
                                elif isinstance(value, int):
                                    tag, encoded = b"I", str(value).encode("ascii")
                                elif isinstance(value, float):
                                    tag, encoded = b"F", value.hex().encode("ascii")
                                elif isinstance(value, str):
                                    tag, encoded = b"T", value.encode("utf-8")
                                elif isinstance(value, bytes):
                                    tag, encoded = b"B", value
                                else:
                                    raise RepoPlanValidationError("Legacy project database contains an unsupported value")
                                total += len(encoded) + 9
                                if total > _MAX_DATABASE_BYTES:
                                    raise RepoPlanValidationError("Legacy project migration inputs exceed the 512 MiB content limit")
                                digest.update(tag)
                                digest.update(len(encoded).to_bytes(8, "big"))
                                digest.update(encoded)
                            digest.update(b"\0")
                        if time.monotonic() - started > _MAX_DATABASE_SNAPSHOT_SECONDS:
                            raise RepoPlanValidationError("Legacy project database snapshot exceeded the 15 second time limit")
            if time.monotonic() - started > _MAX_DATABASE_SNAPSHOT_SECONDS:
                raise RepoPlanValidationError("Legacy project database snapshot exceeded the 15 second time limit")

            after_fd = os.fstat(stream.fileno())
            after_path = db.stat()
            if (
                identity(after_fd) != initial_fd
                or identity(after_path) != initial_path or identity(after_fd)[:4] != identity(after_path)[:4]
                or db.is_symlink()
                or getattr(db, "is_junction", lambda: False)() or not _sidecars_absent(db)
            ):
                raise RepoPlanValidationError("Legacy project database changed during snapshot")
            return digest.hexdigest()
    except RepoPlanValidationError:
        raise
    except sqlite3.Error as exc:
        raise RepoPlanValidationError("Legacy project migration inputs are unreadable") from exc
    except OSError as exc:
        raise RepoPlanValidationError("Legacy project database snapshot is unavailable") from exc


def _git_origin_identity(root: Path) -> str:
    """Return a credential-free origin key for one-time checkout attribution."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=2.0, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    value = result.stdout.strip()
    if result.returncode != 0 or not value or len(value) > 2048 or any(not char.isprintable() for char in value):
        return ""
    if "://" in value:
        try:
            parsed = urlsplit(value)
            if parsed.scheme.casefold() not in {"http", "https", "ssh", "git"} or not parsed.hostname:
                return ""
            host = parsed.hostname.casefold()
            if parsed.port is not None:
                host += f":{parsed.port}"
            path = parsed.path.strip("/")
        except ValueError:
            return ""
    else:
        # Git's SCP-style SSH syntax is user@host:owner/repository.git.
        match = re.fullmatch(r"(?:[^@/:]+@)?([^:/]+):(.+)", value)
        if match is None:
            return ""
        host, path = match.group(1).casefold(), match.group(2).strip("/")
    if path.casefold().endswith(".git"):
        path = path[:-4]
    return f"{host}:{path}" if host and path else ""


def _same_git_origin(left: Path, right: Path) -> bool:
    left_origin = _git_origin_identity(left)
    return bool(left_origin) and left_origin == _git_origin_identity(right)


def _is_project_checkout(candidate: Path, canonical_root: Path, project_id: str) -> bool:
    if not candidate.is_absolute() or candidate.is_symlink() or getattr(candidate, "is_junction", lambda: False)():
        return False
    try:
        candidate = candidate.resolve(strict=True)
        if candidate == canonical_root.resolve(strict=True):
            return True
    except (OSError, RuntimeError, TypeError, ValueError):
        return False
    manifest = candidate / ".local-ai-hub" / "project.json"
    if manifest.is_file() and not manifest.is_symlink() and not getattr(manifest, "is_junction", lambda: False)():
        try:
            return project_scope_id(candidate) == project_id
        except (OSError, RuntimeError, TypeError, ValueError):
            return False
    # This origin match is migration-only enrollment for an old checkout.
    return _same_git_origin(candidate, canonical_root)


def _registered_project_roots(root: Path, project_id: str) -> tuple[str, ...]:
    roots = {str(root.resolve(strict=True))}
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "worktree", "list", "--porcelain"],
            capture_output=True, text=True, timeout=3.0, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return tuple(sorted(roots))
    if result.returncode != 0:
        return tuple(sorted(roots))
    for line in result.stdout.splitlines():
        if not line.startswith("worktree "):
            continue
        candidate = Path(line[len("worktree "):])
        try:
            candidate = candidate.resolve(strict=True)
            if candidate.is_dir() and _is_project_checkout(candidate, root, project_id):
                roots.add(str(candidate))
        except (OSError, RuntimeError, TypeError, ValueError):
            continue
    return tuple(sorted(roots))


def _database_project_roots(state_dir: Path, root: Path, project_id: str) -> tuple[str, ...]:
    db = state_dir / "agent_state.sqlite"
    if not db.is_file():
        return ()
    if db.is_symlink() or getattr(db, "is_junction", lambda: False)() or not _sidecars_absent(db):
        raise RepoPlanValidationError("Legacy project roots require a clean offline database")
    deadline = time.monotonic() + 2.0
    roots: set[str] = set()
    try:
        with closing(sqlite3.connect(db.as_uri() + "?mode=ro&immutable=1", uri=True, timeout=1.0)) as con:
            con.execute("PRAGMA query_only=ON")
            con.execute("PRAGMA trusted_schema=OFF")
            con.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "agent_tasks_projection" in tables:
                roots.update(str(row[0]) for row in con.execute(
                    f"SELECT DISTINCT json_extract({_CHECKPOINT}, '{_SCOPE}.repo_root') "
                    f"FROM agent_tasks_projection WHERE ({_SCOPED}) LIMIT 65"
                ) if row[0])
            if "agent_memory_records" in tables:
                roots.update(str(row[0]) for row in con.execute(
                    "SELECT DISTINCT json_extract(CASE WHEN json_valid(provenance) THEN provenance ELSE '{}' END, '$.root') "
                    "FROM agent_memory_records WHERE json_type(CASE WHEN json_valid(provenance) THEN provenance ELSE '{}' END, '$.root')='text' LIMIT 65"
                ) if row[0])
    except sqlite3.Error as exc:
        raise RepoPlanValidationError("Legacy project root inventory unavailable") from exc
    if len(roots) > 64:
        raise RepoPlanValidationError("Legacy project root inventory exceeds the migration bound")
    accepted = {str(root.resolve(strict=True))}
    for value in roots:
        candidate = Path(value)
        try:
            if not candidate.is_absolute() or candidate.is_symlink() or getattr(candidate, "is_junction", lambda: False)():
                continue
            candidate = candidate.resolve(strict=True)
            manifest_file = candidate / ".local-ai-hub" / "project.json"
            has_safe_manifest = (
                manifest_file.is_file() and not manifest_file.is_symlink()
                and not getattr(manifest_file, "is_junction", lambda: False)()
            )
            if has_safe_manifest and project_scope_id(candidate) == project_id:
                accepted.add(str(candidate))
                continue
            if _same_git_origin(candidate, root):
                accepted.add(str(candidate))
        except (OSError, RuntimeError, TypeError, ValueError):
            continue
    return tuple(sorted(accepted))


def preview_legacy_canonical_task_batch(
    state_dir: Path | str, store: RepoKnowledgeStore, *, limit: int = 8,
    after_task_id: str = "", expected_snapshot: str = "", repository_roots: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Prepare reviewed canonical task record batch from clean offline database."""
    from .repo_project_tasks import build_project_task_record

    if (
        type(limit) is not int or not 1 <= limit <= _MAX_BATCH
        or not isinstance(after_task_id, str) or len(after_task_id) > 256 or "\x00" in after_task_id
        or (after_task_id and not expected_snapshot)
    ):
        raise RepoPlanValidationError("Invalid offline task migration pagination")
    db = Path(state_dir).resolve(strict=True) / "agent_state.sqlite"
    if db.is_symlink() or getattr(db, "is_junction", lambda: False)() or not db.is_file():
        raise RepoPlanValidationError("Offline Agent OS database unavailable")
    if not _sidecars_absent(db):
        raise RepoPlanValidationError("Stop the Hub or use a clean offline backup")
    before = _identity(db)
    snapshot = _database_snapshot(db)
    if expected_snapshot and snapshot != expected_snapshot:
        raise RepoPlanValidationError("Offline database snapshot changed; restart migration inventory")
    epoch = store.read_epoch()
    manifest, manifest_revision = store.manifest()
    roots = repository_roots or (str(store.root),)
    if not roots or len(roots) > 64 or any(
        not _is_project_checkout(Path(item), store.root, manifest["project_id"]) for item in roots
    ):
        raise RepoPlanValidationError("Legacy task roots do not match the current project identity")
    root_placeholders = ",".join("?" for _ in roots)
    deadline = time.monotonic() + 3.0
    try:
        with closing(sqlite3.connect(db.as_uri() + "?mode=ro&immutable=1", uri=True, timeout=1.0)) as con:
            con.execute("PRAGMA query_only=ON")
            con.execute("PRAGMA trusted_schema=OFF")
            con.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            rows = con.execute(
                f"""SELECT task_id, status, lease_id <> '',
                    CASE WHEN length(CAST(contract AS BLOB)) <= ? THEN contract END,
                    CASE WHEN length(CAST(checkpoint AS BLOB)) <= ? THEN checkpoint END
                    FROM agent_tasks_projection
                    WHERE ({_SCOPED})
                    AND json_extract({_CHECKPOINT}, '{_SCOPE}.repo_root') IN ({root_placeholders})
                    AND task_id > ?
                    ORDER BY task_id LIMIT ?""",
                (_MAX_JSON_BYTES, _MAX_JSON_BYTES, *roots, after_task_id, limit + 1),
            ).fetchall()
            unscoped = con.execute(
                f"SELECT COUNT(*) FROM agent_tasks_projection WHERE NOT COALESCE(({_SCOPED}), 0)"
            ).fetchone()[0]
    except sqlite3.Error as exc:
        raise RepoPlanValidationError("Offline task inventory unavailable or scan bound reached") from exc

    records: list[dict[str, Any]] = []
    states: list[dict[str, Any]] = []
    for task_id, status, leased, contract_raw, checkpoint_raw in rows[:limit]:
        entry: dict[str, Any] = {"state": "blocked_invalid_or_oversized_task"}
        if not isinstance(task_id, str) or not task_id or len(task_id) > 256 or "\x00" in task_id:
            raise RepoPlanValidationError("Legacy task identity requires explicit offline conversion")
        if leased or status in {"active", "verifying"}:
            states.append({"state": "blocked_live_attempt"})
            continue
        try:
            contract, checkpoint = json.loads(contract_raw), json.loads(checkpoint_raw)
            if not isinstance(contract, dict) or not isinstance(checkpoint, dict):
                raise ValueError("Invalid task payload")
            task = {"task_id": task_id, "status": status, "contract": contract, "checkpoint": checkpoint}
            record = build_project_task_record(store, task)
            validate_knowledge_file(_path_for("task", record["id"]), _encode(record))
            entry["task_id"] = record["id"]
            try:
                existing = store.get("task", record["id"], verify_sources=False)
            except FileNotFoundError:
                existing = None
            if existing is not None:
                entry["state"] = ("already_published" if existing["record"] == record
                                  else "blocked_existing_record_differs")
            elif manifest["mode"] == "read_only":
                entry["state"] = "blocked_read_only"
            else:
                records.append({"record": record, "expected_revision": ""})
                entry["state"] = "review_required"
        except (OSError, ValueError, TypeError, RepoPlanValidationError, RecursionError):
            pass
        states.append(entry)
    if (
        _identity(db) != before or _database_snapshot(db) != snapshot
        or not _sidecars_absent(db) or db.is_symlink()
    ):
        raise RepoPlanValidationError("Offline database changed during migration preview")
    if store.manifest()[1] != manifest_revision:
        raise RepoPlanValidationError("Project manifest changed during migration preview")
    preview = preview_knowledge_batch(store, records) if records else None
    store.require_read_epoch(epoch)
    return {
        "success": True, "snapshot": snapshot, "project_id": manifest["project_id"],
        "page_complete": len(rows) <= limit, "inventory_complete": len(rows) <= limit and not after_task_id and not unscoped,
        "next_after_task_id": rows[limit - 1][0] if len(rows) > limit else "",
        "unscoped_rows_require_separate_review": unscoped,
        "states": states, "batch": {"records": records}, "preview": preview,
        "canonical_cutover_supported": True, "runtime_state_imported": False,
        "publication_requires_review": True,
    }


def preview_legacy_memory_batch(
    state_dir: Path | str, store: RepoKnowledgeStore, *, limit: int = 16,
    after_record_id: str = "", expected_snapshot: str = "", repository_roots: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Prepare reviewed memory records batch from clean offline database."""
    from .repo_project_memory import build_project_memory_record

    if (
        type(limit) is not int or not 1 <= limit <= _MAX_BATCH
        or not isinstance(after_record_id, str) or len(after_record_id) > 256
        or (after_record_id and not expected_snapshot)
    ):
        raise RepoPlanValidationError("Invalid offline memory migration pagination")
    db = Path(state_dir).resolve(strict=True) / "agent_state.sqlite"
    if db.is_symlink() or getattr(db, "is_junction", lambda: False)() or not db.is_file():
        raise RepoPlanValidationError("Offline Agent OS database unavailable")
    if not _sidecars_absent(db):
        raise RepoPlanValidationError("Stop the Hub or use a clean offline backup")
    before = _identity(db)
    snapshot = _database_snapshot(db)
    if expected_snapshot and snapshot != expected_snapshot:
        raise RepoPlanValidationError("Offline database snapshot changed; restart migration inventory")
    epoch = store.read_epoch()
    manifest, manifest_revision = store.manifest()
    roots = repository_roots or (str(store.root),)
    if not roots or len(roots) > 64 or any(
        not _is_project_checkout(Path(item), store.root, manifest["project_id"]) for item in roots
    ):
        raise RepoPlanValidationError("Legacy memory roots do not match the current project identity")
    root_placeholders = ",".join("?" for _ in roots)
    deadline = time.monotonic() + 3.0
    try:
        with closing(sqlite3.connect(db.as_uri() + "?mode=ro&immutable=1", uri=True, timeout=1.0)) as con:
            con.execute("PRAGMA query_only=ON")
            con.execute("PRAGMA trusted_schema=OFF")
            con.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            rows = con.execute(
                f"""SELECT record_id, kind, scope, key, value, confidence, source, sensitivity, quarantine_reason
                   FROM agent_memory_records
                   WHERE record_id > ? AND sensitivity != 'confidential' AND status = 'active'
                     AND COALESCE(json_extract(
                             CASE WHEN json_valid(provenance) THEN provenance ELSE '{{}}' END, '$.root'
                     ), '') IN ({root_placeholders})
                   ORDER BY record_id LIMIT ?""",
                (after_record_id, *roots, limit + 1),
            ).fetchall()
    except sqlite3.Error as exc:
        raise RepoPlanValidationError("Offline memory inventory unavailable") from exc

    records: list[dict[str, Any]] = []
    states: list[dict[str, Any]] = []
    for rec_id, kind, scope, key, val_raw, conf, src, sens, quar in rows[:limit]:
        entry: dict[str, Any] = {"state": "blocked_invalid_memory"}
        try:
            val = json.loads(val_raw) if (isinstance(val_raw, str) and val_raw.startswith(("{", "["))) else val_raw
            mem_data = {
                "record_id": rec_id, "kind": kind, "scope": scope, "key": key,
                "value": val, "confidence": conf, "source": src, "sensitivity": sens,
                "quarantine_reason": quar or "",
            }
            rec = build_project_memory_record(store, mem_data)
            validate_knowledge_file(_path_for("memory", rec["id"]), _encode(rec))
            entry["record_id"] = rec["id"]
            try:
                existing = store.get("memory", rec["id"], verify_sources=False)
            except FileNotFoundError:
                existing = None
            if existing is not None:
                entry["state"] = ("already_published" if existing["record"] == rec
                                  else "blocked_existing_record_differs")
            elif manifest["mode"] == "read_only":
                entry["state"] = "blocked_read_only"
            else:
                records.append({"record": rec, "expected_revision": ""})
                entry["state"] = "review_required"
        except (OSError, ValueError, TypeError, RepoPlanValidationError):
            pass
        states.append(entry)

    if (
        _identity(db) != before or _database_snapshot(db) != snapshot
        or not _sidecars_absent(db) or db.is_symlink()
    ):
        raise RepoPlanValidationError("Offline database changed during memory preview")
    preview = preview_knowledge_batch(store, records) if records else None
    store.require_read_epoch(epoch)
    return {
        "success": True, "snapshot": snapshot, "project_id": manifest["project_id"],
        "page_complete": len(rows) <= limit, "inventory_complete": len(rows) <= limit and not after_record_id,
        "next_after_record_id": rows[limit - 1][0] if len(rows) > limit else "",
        "states": states, "batch": {"records": records}, "preview": preview,
        "canonical_cutover_supported": True, "publication_requires_review": True,
    }


def preview_legacy_incident_batch(
    state_dir: Path | str, store: RepoKnowledgeStore, *, limit: int = 16,
    after_incident_id: str = "", expected_snapshot: str = "", repository_roots: tuple[str, ...] | None = None,
    repository_key_aliases: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Prepare reviewed incident records batch from clean offline database."""
    from .agent_incidents import _incident_scope_key
    from .repo_project_incidents import build_project_incident_record

    if (
        type(limit) is not int or not 1 <= limit <= _MAX_BATCH
        or not isinstance(after_incident_id, str) or len(after_incident_id) > 256
        or (after_incident_id and not expected_snapshot)
    ):
        raise RepoPlanValidationError("Invalid offline incident migration pagination")
    db = Path(state_dir).resolve(strict=True) / "agent_state.sqlite"
    if db.is_symlink() or getattr(db, "is_junction", lambda: False)() or not db.is_file():
        raise RepoPlanValidationError("Offline Agent OS database unavailable")
    if not _sidecars_absent(db):
        raise RepoPlanValidationError("Stop the Hub or use a clean offline backup")
    before = _identity(db)
    snapshot = _database_snapshot(db)
    if expected_snapshot and snapshot != expected_snapshot:
        raise RepoPlanValidationError("Offline database snapshot changed; restart migration inventory")
    epoch = store.read_epoch()
    manifest, manifest_revision = store.manifest()
    roots = repository_roots or (str(store.root),)
    if not roots or len(roots) > 64 or any(
        not _is_project_checkout(Path(item), store.root, manifest["project_id"]) for item in roots
    ):
        raise RepoPlanValidationError("Legacy incident roots do not match the current project identity")
    repository_keys = tuple(_incident_scope_key("repository", item) for item in roots)
    if (
        not isinstance(repository_key_aliases, tuple) or len(repository_key_aliases) > 8
        or any(not isinstance(item, str) or not re.fullmatch(r"[0-9a-f]{64}", item)
               for item in repository_key_aliases)
    ):
        raise RepoPlanValidationError("Invalid one-time incident migration key aliases")
    repository_keys = tuple(dict.fromkeys((*repository_keys, *repository_key_aliases)))
    key_placeholders = ",".join("?" for _ in repository_keys)
    deadline = time.monotonic() + 3.0
    try:
        with closing(sqlite3.connect(db.as_uri() + "?mode=ro&immutable=1", uri=True, timeout=1.0)) as con:
            con.execute("PRAGMA query_only=ON")
            con.execute("PRAGMA trusted_schema=OFF")
            con.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            rows = con.execute(
                f"""SELECT incident_id, operation_class, error_class, signature_hash,
                          resolved, redacted_message, root_cause, verified_fix, confidence, affected_paths
                   FROM agent_incidents
                   WHERE incident_id > ? AND resolved = 1 AND length(verified_fix) > 0
                         AND trim(lower(verified_fix)) != 'resolved'
                         AND repository_key IN ({key_placeholders})
                   ORDER BY incident_id LIMIT ?""",
                (after_incident_id, *repository_keys, limit + 1),
            ).fetchall()
    except sqlite3.Error as exc:
        raise RepoPlanValidationError("Offline incident inventory unavailable") from exc

    records: list[dict[str, Any]] = []
    states: list[dict[str, Any]] = []
    for inc_id, op, err, sig, res, msg, root, fix, conf, paths_raw in rows[:limit]:
        entry: dict[str, Any] = {"state": "blocked_invalid_incident"}
        try:
            paths = json.loads(paths_raw) if (isinstance(paths_raw, str) and paths_raw.startswith("[")) else []
            inc_data = {
                "incident_id": inc_id, "operation_class": op, "error_class": err,
                "signature_hash": sig, "resolved": bool(res), "redacted_message": msg or "",
                "root_cause": root or "", "verified_fix": fix or "", "confidence": conf,
                "affected_paths": paths,
            }
            rec = build_project_incident_record(store, inc_data)
            validate_knowledge_file(_path_for("incident", rec["id"]), _encode(rec))
            entry["incident_id"] = rec["id"]
            try:
                existing = store.get("incident", rec["id"], verify_sources=False)
            except FileNotFoundError:
                existing = None
            if existing is not None:
                entry["state"] = ("already_published" if existing["record"] == rec
                                  else "blocked_existing_record_differs")
            elif manifest["mode"] == "read_only":
                entry["state"] = "blocked_read_only"
            else:
                records.append({"record": rec, "expected_revision": ""})
                entry["state"] = "review_required"
        except (OSError, ValueError, TypeError, RepoPlanValidationError):
            pass
        states.append(entry)

    if (
        _identity(db) != before or _database_snapshot(db) != snapshot
        or not _sidecars_absent(db) or db.is_symlink()
    ):
        raise RepoPlanValidationError("Offline database changed during incident preview")
    preview = preview_knowledge_batch(store, records) if records else None
    store.require_read_epoch(epoch)
    return {
        "success": True, "snapshot": snapshot, "project_id": manifest["project_id"],
        "page_complete": len(rows) <= limit, "inventory_complete": len(rows) <= limit and not after_incident_id,
        "next_after_incident_id": rows[limit - 1][0] if len(rows) > limit else "",
        "states": states, "batch": {"records": records}, "preview": preview,
        "canonical_cutover_supported": True, "publication_requires_review": True,
    }


def migrate_project_state_on_update(state_dir: Path | str, repo_root: Path | str) -> dict[str, Any]:
    """One-time, restartable import of portable records during an explicit Hub update."""
    from .repo_knowledge_batch import apply_knowledge_batch

    state = Path(state_dir).resolve(strict=True)
    root = Path(repo_root).resolve(strict=True)
    store = RepoKnowledgeStore(root)
    manifest_path = root / ".local-ai-hub" / "project.json"
    legacy_repository_keys: tuple[str, ...] = ()
    if not manifest_path.exists():
        from .agent_incidents import _incident_scope_key

        path_identity = "local:" + hashlib.sha256(str(root).casefold().encode("utf-8")).hexdigest()
        legacy_repository_keys = tuple(dict.fromkeys((
            _incident_scope_key("repository", str(root)),
            hashlib.sha256(f"agent-incident:repository\0{path_identity}".encode("utf-8")).hexdigest(),
        )))
        origin = _git_origin_identity(root)
        # Without a remote, independent clones cannot be identified safely; enroll this checkout once.
        project_id = (
            str(uuid.uuid5(uuid.NAMESPACE_URL, f"local-ai-hub-project:{origin}"))
            if origin else str(uuid.uuid4())
        )
        try:
            store.bootstrap(
                project_id, mode="shared", owner="release-update",
                idempotency_key=f"update-project-bootstrap-{project_id}",
                authorize_write=lambda: True,
            )
        except (OSError, RepoPlanConflictError, RepoPlanValidationError, RuntimeError) as exc:
            try:
                manifest, _ = store.manifest()
            except (OSError, RepoPlanConflictError, RepoPlanValidationError, RuntimeError) as read_exc:
                raise RepoPlanValidationError(
                    "Old checkout project identity could not be bootstrapped safely"
                ) from read_exc
            if manifest.get("mode") != "shared":
                raise RepoPlanValidationError(
                    "Concurrent project bootstrap did not produce a shared project"
                ) from exc
    manifest, _ = store.manifest()
    project_id = manifest["project_id"]
    marker = state / "project_state_migration_v1.json"
    if marker.is_symlink() or getattr(marker, "is_junction", lambda: False)():
        raise RepoPlanValidationError("Project state migration marker is not a regular file")
    if marker.exists():
        try:
            saved = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise RepoPlanValidationError("Project state migration marker is corrupt") from exc
        if not isinstance(saved, dict) or saved.get("schema_version") != 1 or not isinstance(saved.get("projects"), dict):
            raise RepoPlanValidationError("Project state migration marker is invalid")
        if project_id in saved["projects"]:
            return {"status": "already_migrated", "project_id": project_id, "records": 0}
    else:
        saved = {"schema_version": 1, "projects": {}}

    db = state / "agent_state.sqlite"
    if not db.exists():
        return {"status": "no_legacy_state", "project_id": project_id, "records": 0}

    source_identity = _identity(db)
    source_snapshot = _database_snapshot(db)
    if db.is_symlink() or getattr(db, "is_junction", lambda: False)() or not _sidecars_absent(db):
        raise RepoPlanValidationError("Project state migration requires a clean offline database")
    try:
        with closing(sqlite3.connect(db.resolve().as_uri() + "?mode=ro&immutable=1", uri=True, timeout=1.0)) as con:
            source_tables = {
                str(row[0]) for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
    except sqlite3.Error as exc:
        raise RepoPlanValidationError("Project state migration database is unreadable") from exc
    if _identity(db) != source_identity or _database_snapshot(db) != source_snapshot:
        raise RepoPlanValidationError("Legacy project state snapshot changed during migration inventory")

    # Do not inspect legacy paths or databases after this project has been cut over.
    repository_roots = tuple(sorted(set(_registered_project_roots(root, project_id)) | set(
        _database_project_roots(state, root, project_id)
    )))
    if _identity(db) != source_identity or _database_snapshot(db) != source_snapshot:
        raise RepoPlanValidationError("Legacy project state snapshot changed during migration inventory")

    counts = {"task": 0, "memory": 0, "incident": 0}
    plans = tuple(plan for plan in (
        ("task", "agent_tasks_projection", preview_legacy_canonical_task_batch, "after_task_id", "next_after_task_id"),
        ("memory", "agent_memory_records", preview_legacy_memory_batch, "after_record_id", "next_after_record_id"),
        ("incident", "agent_incidents", preview_legacy_incident_batch, "after_incident_id", "next_after_incident_id"),
    ) if plan[1] in source_tables)
    for kind, _table, previewer, cursor_name, next_name in plans:
        cursor = ""
        while True:
            batch = previewer(
                state, store, limit=16,
                **{cursor_name: cursor, "expected_snapshot": source_snapshot, "repository_roots": repository_roots},
                **({"repository_key_aliases": legacy_repository_keys}
                   if kind == "incident" and legacy_repository_keys else {}),
            )
            states = batch["states"]
            blocked = [item for item in states if item["state"] not in {"review_required", "already_published", "blocked_live_attempt"}]
            if blocked:
                raise RepoPlanValidationError(f"Project {kind} migration contains blocked records")
            records = batch["batch"]["records"]
            if records:
                preview = batch.get("preview")
                if not isinstance(preview, dict) or not isinstance(preview.get("preview_digest"), str):
                    raise RepoPlanValidationError(f"Project {kind} migration preview is unavailable")
                operation = hashlib.sha256(
                    f"project-state-v1\0{project_id}\0{kind}\0{source_snapshot}\0{cursor}".encode("utf-8")
                ).hexdigest()
                result = apply_knowledge_batch(
                    store, records, preview_digest=preview["preview_digest"], operation_id=operation,
                    authorize_write=lambda: True,
                )
                if result.get("success") is not True:
                    raise RepoPlanValidationError(f"Project {kind} migration publication failed")
                counts[kind] += len(records)
            if batch["page_complete"]:
                break
            next_cursor = batch.get(next_name)
            if not isinstance(next_cursor, str) or not next_cursor or next_cursor <= cursor:
                raise RepoPlanValidationError(f"Project {kind} migration pagination did not advance")
            cursor = next_cursor

    if _identity(db) != source_identity or _database_snapshot(db) != source_snapshot:
        raise RepoPlanValidationError("Legacy project state snapshot changed before migration cutover")
    saved["projects"][project_id] = {"status": "complete", "records": counts}
    _write_project_migration_marker(marker, saved)
    return {"status": "migrated", "project_id": project_id, "records": counts}


def _write_project_migration_marker(marker: Path, saved: dict[str, Any]) -> None:
    """Persist the one-time cutover marker atomically inside local state."""
    marker.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="project-state-migration-", suffix=".tmp", dir=marker.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(saved, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, marker)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def migrate_runtime_task_scopes_on_update(state_dir: Path | str) -> dict[str, Any]:
    """Fence pre-cutover local task attempts during the explicit updater run."""
    state = Path(state_dir).expanduser().resolve(strict=True)
    marker = state / "agent_task_scope_v4_migration.json"
    if marker.is_symlink() or getattr(marker, "is_junction", lambda: False)():
        raise RepoPlanValidationError("Task scope migration marker is not a regular file")
    if marker.exists():
        try:
            saved = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise RepoPlanValidationError("Task scope migration marker is corrupt") from exc
        if not isinstance(saved, dict) or saved.get("schema_version") != 1:
            raise RepoPlanValidationError("Task scope migration marker is invalid")
        return {"status": "already_migrated", "converted": 0, "retired": 0}

    db = state / "agent_state.sqlite"
    if not db.is_file():
        return {"status": "no_legacy_state", "converted": 0, "retired": 0}
    if db.is_symlink() or getattr(db, "is_junction", lambda: False)() or not _sidecars_absent(db):
        raise RepoPlanValidationError("Task scope update requires a clean offline database")

    converted = 0
    retired = 0
    with closing(sqlite3.connect(db.as_uri() + "?mode=rw", uri=True, timeout=2.0, isolation_level=None)) as con:
        con.execute("PRAGMA trusted_schema=OFF")
        con.execute("BEGIN IMMEDIATE")
        tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "agent_tasks_projection" not in tables:
            con.commit()
            _write_scope_migration_marker(marker, {"schema_version": 1, "converted": 0, "retired": 0})
            return {"status": "no_scoped_tasks", "converted": 0, "retired": 0}
        rows = con.execute(
            "SELECT task_id,status,lease_id,heartbeat_expires_at,checkpoint "
            "FROM agent_tasks_projection ORDER BY task_id LIMIT 10001"
        ).fetchall()
        if len(rows) > 10000:
            con.rollback()
            raise RepoPlanValidationError("Task scope update exceeds the migration bound")
        for task_id, status, lease_id, heartbeat, checkpoint_raw in rows:
            try:
                checkpoint = json.loads(checkpoint_raw or "{}")
            except (TypeError, ValueError) as exc:
                con.rollback()
                raise RepoPlanValidationError("Task scope update found malformed checkpoint data") from exc
            if not isinstance(checkpoint, dict):
                con.rollback()
                raise RepoPlanValidationError("Task scope update found malformed checkpoint data")
            state_data = checkpoint.get("state_data", {})
            if not isinstance(state_data, dict):
                con.rollback()
                raise RepoPlanValidationError("Task scope update found malformed state data")
            scope = state_data.get("_agent_task_scope")
            if scope is None or (isinstance(scope, dict) and scope.get("version") == 4):
                continue
            if not isinstance(scope, dict) or scope.get("version") not in {2, 3}:
                con.rollback()
                raise RepoPlanValidationError("Task scope update found an unsupported scope contract")
            old_root = scope.get("repo_root")
            try:
                if not isinstance(old_root, str) or not Path(old_root).is_absolute():
                    raise ValueError
                root = Path(old_root).resolve(strict=True)
                if not root.is_dir():
                    raise ValueError
                scope = {
                    "version": 4,
                    "project_id": project_scope_id(root),
                    "worktree_id": worktree_scope_id(root),
                    "repo_root": str(root),
                    "snapshot_id": repository_snapshot_id(root),
                }
                state_data["_agent_task_scope"] = scope
                if status in {"planned", "active", "waiting", "verifying"}:
                    checkpoint["blockers"] = list(checkpoint.get("blockers", []))
                    checkpoint["blockers"].append(
                        "Updater fenced this in-flight task; re-review it against the current Git snapshot before continuing."
                    )
                    status = "blocked"
                con.execute(
                    "UPDATE agent_tasks_projection SET status=?,lease_id='',heartbeat_expires_at=0,checkpoint=?,updated_at=? WHERE task_id=?",
                    (status, json.dumps(checkpoint, ensure_ascii=False), time.time(), task_id),
                )
                converted += 1
            except (OSError, RuntimeError, TypeError, ValueError):
                state_data.pop("_agent_task_scope", None)
                state_data["_retired_repository_scope"] = hashlib.sha256(
                    str(old_root).encode("utf-8", errors="replace")
                ).hexdigest()
                checkpoint["blockers"] = list(checkpoint.get("blockers", []))
                checkpoint["blockers"].append(
                    "Updater could not verify the old checkout; task is archived as local history."
                )
                con.execute(
                    "UPDATE agent_tasks_projection SET status='abandoned',lease_id='',heartbeat_expires_at=0,checkpoint=?,updated_at=? WHERE task_id=?",
                    (json.dumps(checkpoint, ensure_ascii=False), time.time(), task_id),
                )
                retired += 1
        con.commit()

    _write_scope_migration_marker(marker, {"schema_version": 1, "converted": converted, "retired": retired})
    return {"status": "migrated", "converted": converted, "retired": retired}


def _write_scope_migration_marker(marker: Path, saved: dict[str, Any]) -> None:
    marker.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="task-scope-v4-", suffix=".tmp", dir=marker.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(saved, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, marker)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
