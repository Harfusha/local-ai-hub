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
from contextlib import closing
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .agent_state_inventory import _identity, _sidecars_absent
from .repo_knowledge import RepoKnowledgeStore, _digest_value, _encode, _path_for, validate_knowledge_file
from .repo_knowledge_batch import preview_knowledge_batch
from .repo_plan.schema_validation import RepoPlanValidationError
from .project_identity import project_scope_id

_MAX_BATCH = 16
_MAX_JSON_BYTES = 65536
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
        if project_scope_id(candidate) == project_id:
            return True
    except (OSError, RuntimeError, TypeError, ValueError):
        return False
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
            if candidate.is_dir() and (
                project_scope_id(candidate) == project_id or _same_git_origin(candidate, root)
            ):
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
    snapshot = _digest_value(list(before))
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
    if _identity(db) != before or not _sidecars_absent(db) or db.is_symlink():
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
    snapshot = _digest_value(list(before))
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

    if _identity(db) != before or not _sidecars_absent(db) or db.is_symlink():
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
    snapshot = _digest_value(list(before))
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

    if _identity(db) != before or not _sidecars_absent(db) or db.is_symlink():
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

    # Do not inspect legacy paths or databases after this project has been cut over.
    repository_roots = tuple(sorted(set(_registered_project_roots(root, project_id)) | set(
        _database_project_roots(state, root, project_id)
    )))

    counts = {"task": 0, "memory": 0, "incident": 0}
    plans = (
        ("task", preview_legacy_canonical_task_batch, "after_task_id", "next_after_task_id"),
        ("memory", preview_legacy_memory_batch, "after_record_id", "next_after_record_id"),
        ("incident", preview_legacy_incident_batch, "after_incident_id", "next_after_incident_id"),
    )
    for kind, previewer, cursor_name, next_name in plans:
        cursor = ""
        expected_snapshot = ""
        while True:
            batch = previewer(
                state, store, limit=16,
                **{cursor_name: cursor, "expected_snapshot": expected_snapshot, "repository_roots": repository_roots},
            )
            expected_snapshot = batch["snapshot"]
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
                    f"project-state-v1\0{project_id}\0{kind}\0{expected_snapshot}\0{cursor}".encode("utf-8")
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
