"""Offline, bounded preparation of real legacy TaskStore rows for review.

This is a preparatory migration of portable history, not a live authority
switch. The existing SQLite task/event/receipt authority stays untouched.
No raw event, lease ID, receipt ID, context or checkpoint state is exported.
"""
from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Any

from .agent_state_inventory import _identity, _sidecars_absent
from .repo_knowledge import RepoKnowledgeStore, _digest_value, _encode, _path_for, validate_knowledge_file
from .repo_knowledge_batch import preview_knowledge_batch
from .repo_plan.schema_validation import RepoPlanValidationError
from .repo_task_handoff import attach_source_dependencies, build_task_handoff

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


def preview_legacy_task_batch(
    state_dir: Path | str, store: RepoKnowledgeStore, *, limit: int = 8,
    after_task_id: str = "", expected_snapshot: str = "",
) -> dict[str, Any]:
    """Prepare reviewed batch input from a clean offline database.

    Pages use task_id ordering and a snapshot identity. Repeated pages must
    supply the previous snapshot identity; never claim whole-project cutover.
    """
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
    deadline = time.monotonic() + 3.0
    try:
        with closing(sqlite3.connect(db.as_uri() + "?mode=ro&immutable=1", uri=True, timeout=1.0)) as con:
            con.execute("PRAGMA query_only=ON")
            con.execute("PRAGMA trusted_schema=OFF")
            con.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            tables = con.execute("PRAGMA main.table_list").fetchmany(257)
            if len(tables) > 256 or not any(row[:3] == ("main", "agent_tasks_projection", "table") for row in tables):
                raise RepoPlanValidationError("Canonical legacy task projection unavailable")
            columns = {row[1] for row in con.execute("PRAGMA main.table_xinfo(agent_tasks_projection)")}
            from .agent_state_inventory import _SCHEMA

            if columns != set(_SCHEMA["agent_tasks_projection"][2]):
                raise RepoPlanValidationError("Legacy task projection schema requires explicit conversion")
            unscoped = con.execute(
                f"SELECT COUNT(*) FROM agent_tasks_projection WHERE NOT COALESCE(({_SCOPED}), 0)"
            ).fetchone()[0]
            # Do not read other-root payloads. Bound both raw JSON documents
            # before decoding; select no receipts, context, owner or lease ID.
            rows = con.execute(
                f"""SELECT task_id, status, lease_id <> '',
                    CASE WHEN length(CAST(contract AS BLOB)) <= ? THEN contract END,
                    CASE WHEN length(CAST(checkpoint AS BLOB)) <= ? THEN checkpoint END
                    FROM agent_tasks_projection
                    WHERE ({_SCOPED})
                    AND json_extract({_CHECKPOINT}, '{_SCOPE}.repo_root') = ?
                    AND task_id > ?
                    ORDER BY task_id LIMIT ?""",
                (_MAX_JSON_BYTES, _MAX_JSON_BYTES, str(store.root), after_task_id, limit + 1),
            ).fetchall()
    except sqlite3.Error as exc:
        raise RepoPlanValidationError("Offline task inventory unavailable or scan bound reached") from exc

    records: list[dict[str, Any]] = []
    states: list[dict[str, Any]] = []
    affected_budget = 16
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
            task = {"task_id": task_id, "repo_root": str(store.root), "status": status,
                    "contract": contract, "checkpoint": checkpoint}
            record = build_task_handoff(store, task)
            paths = set(record["payload"]["checkpoint"]["affected_paths"])
            if len(paths) > affected_budget:
                states.append({"handoff_id": record["id"], "state": "blocked_dependency_budget"})
                continue
            affected_budget -= len(paths)
            record = attach_source_dependencies(store, record)
            validate_knowledge_file(_path_for("handoff", record["id"]), _encode(record))
            entry["handoff_id"] = record["id"]
            try:
                existing = store.get("handoff", record["id"], verify_sources=False)
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
        "canonical_cutover_supported": False, "runtime_state_imported": False,
        "publication_requires_review": True,
    }


def preview_legacy_canonical_task_batch(
    state_dir: Path | str, store: RepoKnowledgeStore, *, limit: int = 8,
    after_task_id: str = "", expected_snapshot: str = "",
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
                    AND json_extract({_CHECKPOINT}, '{_SCOPE}.repo_root') = ?
                    AND task_id > ?
                    ORDER BY task_id LIMIT ?""",
                (_MAX_JSON_BYTES, _MAX_JSON_BYTES, str(store.root), after_task_id, limit + 1),
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
    after_record_id: str = "", expected_snapshot: str = "",
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
    deadline = time.monotonic() + 3.0
    try:
        with closing(sqlite3.connect(db.as_uri() + "?mode=ro&immutable=1", uri=True, timeout=1.0)) as con:
            con.execute("PRAGMA query_only=ON")
            con.execute("PRAGMA trusted_schema=OFF")
            con.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            rows = con.execute(
                """SELECT record_id, kind, scope, key, value, confidence, source, sensitivity, quarantine_reason
                   FROM agent_memory_records
                   WHERE record_id > ? AND sensitivity != 'confidential' AND status = 'active'
                   ORDER BY record_id LIMIT ?""",
                (after_record_id, limit + 1),
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
    after_incident_id: str = "", expected_snapshot: str = "",
) -> dict[str, Any]:
    """Prepare reviewed incident records batch from clean offline database."""
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
    deadline = time.monotonic() + 3.0
    try:
        with closing(sqlite3.connect(db.as_uri() + "?mode=ro&immutable=1", uri=True, timeout=1.0)) as con:
            con.execute("PRAGMA query_only=ON")
            con.execute("PRAGMA trusted_schema=OFF")
            con.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            rows = con.execute(
                """SELECT incident_id, operation_class, error_class, signature_hash,
                          resolved, redacted_message, root_cause, verified_fix, confidence, affected_paths
                   FROM agent_incidents
                   WHERE incident_id > ? AND resolved = 1 AND length(verified_fix) > 0
                         AND trim(lower(verified_fix)) != 'resolved'
                   ORDER BY incident_id LIMIT ?""",
                (after_incident_id, limit + 1),
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


def publish_legacy_record(
    state_dir: Path | str,
    store: RepoKnowledgeStore,
    *,
    kind: str,
    record_id: str,
    expected_snapshot: str,
    operation_id: str,
    authorize_write: Callable[[], bool],
) -> dict[str, Any]:
    """Publish a single reviewed legacy record into canonical Git state."""
    from .repo_knowledge_batch import apply_knowledge_batch, preview_knowledge_batch

    if kind == "task":
        batch_res = preview_legacy_canonical_task_batch(
            state_dir, store, limit=16, after_task_id="", expected_snapshot=expected_snapshot,
        )
    elif kind == "memory":
        batch_res = preview_legacy_memory_batch(
            state_dir, store, limit=16, after_record_id="", expected_snapshot=expected_snapshot,
        )
    elif kind == "incident":
        batch_res = preview_legacy_incident_batch(
            state_dir, store, limit=16, after_incident_id="", expected_snapshot=expected_snapshot,
        )
    else:
        raise RepoPlanValidationError(f"Unsupported record kind '{kind}' for publishing")

    matching = [
        item for item in batch_res["batch"]["records"]
        if item["record"]["id"] == record_id
    ]
    if not matching:
        # Check if already published
        try:
            existing = store.get(kind, record_id, verify_sources=False)
            return {"success": True, "already_published": True, "record": existing["record"]}
        except FileNotFoundError:
            raise RepoPlanValidationError(f"Record '{record_id}' of kind '{kind}' not found or blocked in migration")

    preview = preview_knowledge_batch(store, matching)
    published = apply_knowledge_batch(
        store, matching, preview_digest=preview["preview_digest"],
        operation_id=operation_id, authorize_write=authorize_write,
    )
    return published
