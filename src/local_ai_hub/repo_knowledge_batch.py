"""Reviewed bounded publication of related records through RepoPlanStorage.

A batch is recoverable, not an atomic multi-file read snapshot. No live task
or receipt authority is transferred. Recovery requires the original reviewed
batch, operation key and local authorization.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from typing import Any

from .repo_knowledge import (
    RepoKnowledgeStore, _MANIFEST, _digest_value, _encode, _path_for, validate_knowledge_file,
)
from .repo_plan.schema_validation import RepoPlanConflictError, RepoPlanValidationError

_MAX_BATCH = 16
_REVISION = re.compile(r"[0-9a-f]{64}")


def _prepare(
    store: RepoKnowledgeStore, records: Any,
) -> tuple[list[tuple[str, bytes, str]], dict[str, Any]]:
    if not isinstance(records, list) or not 1 <= len(records) <= _MAX_BATCH:
        raise RepoPlanValidationError("Knowledge batch requires 1–16 reviewed records")
    raw, revision = store._read_raw(_MANIFEST)
    manifest = validate_knowledge_file(_MANIFEST, raw)
    candidates = []
    rows = []
    seen = set()
    for entry in records:
        if not isinstance(entry, dict) or set(entry) != {"record", "expected_revision"}:
            raise RepoPlanValidationError("Knowledge batch entries require record and expected_revision")
        record, expected = entry["record"], entry["expected_revision"]
        if not isinstance(record, dict) or not isinstance(expected, str) or (expected and not _REVISION.fullmatch(expected)):
            raise RepoPlanValidationError("Invalid knowledge batch record or revision")
        path = _path_for(record.get("kind"), record.get("id"))
        data = _encode(record)
        clean = validate_knowledge_file(path, data)
        if clean["project_id"] != manifest["project_id"] or clean["kind"] in {"review", "finding"} or path in seen:
            raise RepoPlanValidationError("Invalid knowledge batch identity or kind")
        seen.add(path)
        candidates.append((path, data, expected))
        rows.append({"path": path, "expected_revision": expected,
                     "candidate_revision": hashlib.sha256(data).hexdigest(), "record": clean})
    # Stable order means a differently ordered JSON array has the same digest.
    rows.sort(key=lambda row: row["path"])
    candidates.sort(key=lambda row: row[0])
    candidates.insert(0, (_MANIFEST, raw, revision))
    digest = _digest_value([revision, rows])
    return candidates, {
        "project_id": manifest["project_id"], "manifest_revision": revision,
        "writable_mode": manifest["mode"] != "read_only", "records": rows,
        "preview_digest": digest, "canonical_cutover_supported": False,
    }


def preview_knowledge_batch(store: RepoKnowledgeStore, records: Any) -> dict[str, Any]:
    epoch = store.read_epoch()
    candidates, preview = _prepare(store, records)
    for path, _, expected in candidates[1:]:
        try:
            before, revision = store._read(path)
            if before["project_id"] != preview["project_id"]:
                raise RepoPlanConflictError("Knowledge batch project identity mismatch")
        except FileNotFoundError:
            revision = ""
        if revision != expected:
            raise RepoPlanConflictError("Knowledge batch target revision changed")
    if store.manifest()[1] != preview["manifest_revision"]:
        raise RepoPlanConflictError("Knowledge batch manifest changed")
    store.require_read_epoch(epoch)
    return {"success": True, "preview": True, **preview}


def apply_knowledge_batch(
    store: RepoKnowledgeStore, records: Any, *, preview_digest: str, operation_id: str,
    authorize_write: Callable[[], bool], recover: bool = False,
) -> dict[str, Any]:
    if not callable(authorize_write) or authorize_write() is not True:
        raise RepoPlanConflictError("Knowledge batch requires authorized operator apply")
    if not isinstance(operation_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", operation_id):
        raise RepoPlanValidationError("Knowledge batch requires a stable operation ID")
    candidates, preview = _prepare(store, records)
    if preview_digest != preview["preview_digest"] or not preview["writable_mode"]:
        raise RepoPlanConflictError("Knowledge batch reviewed content or manifest changed")
    store._require_local_journal_ignored()

    def fence() -> bool:
        try:
            return authorize_write() is True and store.manifest()[1] == preview["manifest_revision"]
        except (OSError, RepoPlanValidationError):
            return False

    if recover:
        targets = {path: (expected, hashlib.sha256(data).hexdigest())
                   for path, data, expected in candidates}
        outcomes = store.storage.recover_pending_intents(
            only_key=operation_id, resume_unapplied=True, expected_targets=targets,
            lease_check_fn=fence,
        )
        return {
            "success": bool(outcomes) and all(row["status"] == "completed" for row in outcomes),
            "recovery": outcomes, "canonical_cutover_supported": False,
        }
    result = store.storage.save_knowledge_batch(
        candidates, owner="local-operator", idempotency_key=operation_id, lease_check_fn=fence,
    )
    return {**result, "canonical_cutover_supported": False}
