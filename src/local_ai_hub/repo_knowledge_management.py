"""Scoped operator management of the existing Git-native knowledge store.

Preview is read-only. Save requires an explicit local operator authorization,
an exact reviewed candidate digest and current file revision. Git content
never grants a permission or creates current verification.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any

from .repo_knowledge import RepoKnowledgeStore, _digest_value, _encode, _path_for, build_finding_review, validate_knowledge_file
from .repo_knowledge_quality import build_remediation_contract, knowledge_impact, quality_report
from .repo_plan.schema_validation import RepoPlanConflictError, RepoPlanValidationError
from .repository_scope import RepositoryScopeError, authorized_repository_root

_FIELDS = {
    "audit": {"action", "root"},
    "sync_status": {"action", "root"},
    "impact": {"action", "root", "changed_paths"},
    "preview_edit": {"action", "root", "record", "expected_revision"},
    "save_edit": {"action", "root", "record", "expected_revision", "preview_digest", "operation_id", "apply"},
    "preview_review": {"action", "root", "finding_id", "subject_digest", "decision", "note"},
    "save_review": {"action", "root", "finding_id", "subject_digest", "decision", "note", "expected_revision", "preview_digest", "operation_id", "apply"},
    "preview_remediation": {"action", "root", "finding_id", "subject_digest"},
}


def _error(status: int, message: str) -> dict[str, Any]:
    return {"success": False, "status_code": status, "error": message,
            "terminal": True, "retryable": False}


def _revision(value: Any) -> bool:
    return isinstance(value, str) and (value == "" or re.fullmatch(r"[0-9a-f]{64}", value) is not None)


def manage_repository_knowledge(
    config: Mapping[str, Any], payload: Mapping[str, Any], *,
    authorize_operator_write: Callable[[], bool],
) -> dict[str, Any]:
    action = payload.get("action")
    if not isinstance(action, str) or action not in _FIELDS or set(payload) != _FIELDS[action]:
        return _error(400, "Invalid knowledge management action or fields")
    writing = action.startswith("save_")
    if writing and (
        payload["apply"] is not True or authorize_operator_write() is not True
        or not isinstance(payload["operation_id"], str)
        or re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", payload["operation_id"]) is None
    ):
        return _error(403, "Knowledge save requires explicit authorized operator apply")
    try:
        root = authorized_repository_root(config, payload["root"])
        store = RepoKnowledgeStore(root)
        if action == "sync_status":
            from .repo_knowledge_sync import checkout_sync_status

            return {"success": True, **checkout_sync_status(store.root)}
        manifest, manifest_revision = store.manifest()
        if action == "audit":
            return {"success": True, **quality_report(store.catalog())}
        if action == "impact":
            return {"success": True, **knowledge_impact(store.catalog(), payload["changed_paths"])}
        if action == "preview_remediation":
            return {"success": True, "preview": True,
                    "contract": build_remediation_contract(store.catalog(), payload["finding_id"], payload["subject_digest"])}
        if action.endswith("_review"):
            record = build_finding_review(store.catalog(), payload["finding_id"], payload["subject_digest"],
                                          payload["decision"], payload["note"])
        else:
            record = payload["record"]
            if not isinstance(record, dict) or record.get("kind") in {"handoff", "review"}:
                return _error(400, "Edit requires a normal knowledge declaration")
        kind, record_id = record.get("kind"), record.get("id")
        clean = validate_knowledge_file(_path_for(kind, record_id), _encode(record))
        if clean["project_id"] != manifest["project_id"]:
            return _error(409, "Knowledge project identity changed")
        try:
            previous = store.get(kind, record_id, verify_sources=False)
        except FileNotFoundError:
            previous = None
        current_revision = previous["revision"] if previous is not None else ""
        expected = payload.get("expected_revision", current_revision)
        if not _revision(expected) or current_revision != expected:
            return _error(409, "Knowledge revision changed; refresh before editing")
        before = previous["record"] if previous is not None else None
        # Bind exact reviewed contents, project manifest and prior revision.
        digest = _digest_value([manifest_revision, current_revision, clean])
        if not writing:
            return {
                "success": True, "preview": True, "before": before, "after": clean,
                "expected_revision": current_revision, "preview_digest": digest,
                "writable_mode": manifest["mode"] != "read_only",
            }
        if payload["preview_digest"] != digest:
            return _error(409, "Reviewed candidate changed; preview again")
        if manifest["mode"] == "read_only":
            return _error(403, "Knowledge project is read-only")

        def fence() -> bool:
            try:
                return authorize_operator_write() is True and store.manifest()[1] == manifest_revision
            except (OSError, RepoPlanValidationError):
                return False

        return store.save(clean, expected_revision=current_revision, owner="local-operator",
                          idempotency_key=payload["operation_id"], authorize_write=fence)
    except RepositoryScopeError as exc:
        return _error(exc.status_code, str(exc))
    except RepoPlanConflictError:
        return _error(409, "Knowledge write conflict; refresh before retry")
    except FileNotFoundError:
        return _error(404, "Knowledge project is uninitialized or unavailable")
    except (RepoPlanValidationError, ValueError, TypeError):
        return _error(400, "Invalid knowledge record or finding")
    except (OSError, RuntimeError):
        return _error(409, "Knowledge storage unavailable; inspect before retry")
