"""Canonical Git-backed project incidents and verified fixes.

Git is the authoritative owner of resolved operational incidents, signature
hashes, root causes, and verified fixes across developer nodes. Local attempts
and raw execution command outputs remain private in SQLite.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .repo_knowledge import RepoKnowledgeStore, _identifier, _text, validate_knowledge_file
from .repo_knowledge_privacy import contains_private_project_data
from .repo_plan.schema_validation import RepoPlanValidationError

_ALLOWED_OPERATION_CLASSES = {"agent", "command", "tool", "mcp", "verification"}


def _reject(message: str = "Invalid canonical project incident") -> RepoPlanValidationError:
    return RepoPlanValidationError(message)


def _safe_relative_path(value: Any) -> bool:
    return (
        isinstance(value, str) and 0 < len(value) <= 512
        and not any(char in value for char in ("\\", ":"))
        and all(part not in {"", ".", ".."} and part.casefold() != ".git"
                for part in value.split("/"))
        and all(char.isprintable() for char in value)
    )


def validate_project_incident_payload(record: Mapping[str, Any]) -> None:
    """Validate canonical project incident envelope and payload."""
    payload = record.get("payload")
    if (
        not isinstance(payload, dict)
        or not {"incident_id", "operation_class", "error_class", "signature_hash", "resolved"} <= set(payload)
        or set(payload) - {
            "incident_id", "operation_class", "error_class", "signature_hash",
            "resolved", "redacted_message", "root_cause", "verified_fix",
            "confidence", "affected_paths", "created_at", "updated_at",
        }
        or not _identifier(payload["incident_id"])
        or record.get("id") != payload["incident_id"]
        or payload["operation_class"] not in _ALLOWED_OPERATION_CLASSES
        or not _text(payload["error_class"], 128)
        or not re.fullmatch(r"[0-9a-f]{16,64}", str(payload["signature_hash"]))
        or not isinstance(payload["resolved"], bool)
        or not isinstance(record.get("provenance"), dict)
        or not isinstance(record.get("evidence"), list)
        or not isinstance(record.get("relations"), list)
    ):
        raise _reject()

    if contains_private_project_data(payload):
        raise _reject("Project incident contains private session, receipt, or credential data")

    # Redacted message must not contain secrets or raw exception dumps
    redacted_message = payload.get("redacted_message", "")
    if redacted_message and not _text(redacted_message, 1500):
        raise _reject("Invalid redacted_message length or format")

    root_cause = payload.get("root_cause", "")
    if root_cause and not _text(root_cause, 1500):
        raise _reject("Invalid root_cause length or format")

    verified_fix = payload.get("verified_fix", "")
    if payload["resolved"] and not (verified_fix and _text(verified_fix, 1500)):
        raise _reject("Resolved incident requires a concrete verified_fix description")
    if verified_fix and str(verified_fix).strip().casefold() == "resolved":
        raise _reject("verified_fix must describe the actual fix, not simply 'resolved'")

    confidence = payload.get("confidence", 1.0)
    if not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        raise _reject("Incident confidence must be finite and between 0.0 and 1.0")

    affected_paths = payload.get("affected_paths", [])
    if not isinstance(affected_paths, list) or len(affected_paths) > 64:
        raise _reject("Invalid affected_paths in incident")
    if not all(_safe_relative_path(path) for path in affected_paths):
        raise _reject("Invalid path in incident affected_paths")


def build_project_incident_record(
    store: RepoKnowledgeStore,
    incident_data: Mapping[str, Any],
    *,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Construct a canonical project incident record."""
    incident_id = str(incident_data.get("incident_id", "")).strip()
    if not _identifier(incident_id):
        h = hashlib.sha256(str(incident_data.get("signature_hash", "")).encode()).hexdigest()[:16]
        incident_id = f"inc-{h}"

    resolved = incident_data.get("resolved", False)
    if not isinstance(resolved, bool):
        raise _reject("Incident resolved flag must be a boolean")

    manifest, _ = store.manifest()
    payload: dict[str, Any] = {
        "incident_id": incident_id,
        "operation_class": str(incident_data.get("operation_class", "agent")),
        "error_class": str(incident_data.get("error_class", "RuntimeError")),
        "signature_hash": str(incident_data.get("signature_hash", "")),
        "resolved": resolved,
        "redacted_message": str(incident_data.get("redacted_message", "") or ""),
        "root_cause": str(incident_data.get("root_cause", "") or ""),
        "verified_fix": str(incident_data.get("verified_fix", "") or ""),
        "confidence": float(incident_data.get("confidence", 1.0)),
        "affected_paths": sorted(set(incident_data.get("affected_paths") or [])),
    }

    record = {
        "schema_version": 1,
        "project_id": manifest["project_id"],
        "kind": "incident",
        "id": incident_id,
        "payload": payload,
        "provenance": provenance or {"origin_kind": "manual"},
        "evidence": [],
        "relations": [],
    }
    validate_project_incident_payload(record)
    return record


def incident_file_path(repo_root: Path | str, incident_id: str) -> Path:
    """Return filesystem path for canonical project incident file."""
    if not _identifier(incident_id):
        raise _reject("Invalid incident identifier")
    return Path(repo_root) / ".local-ai-hub" / "agent-os" / "incidents" / f"{incident_id}.json"


def load_project_incident(repo_root: Path | str, incident_id: str) -> dict[str, Any]:
    """Load canonical project incident from disk and validate schema."""
    path = incident_file_path(repo_root, incident_id)
    if not path.is_file():
        raise FileNotFoundError(f"Canonical project incident '{incident_id}' not found at {path}")
    data = path.read_bytes()
    rel_path = f".local-ai-hub/agent-os/incidents/{incident_id}.json"
    record = validate_knowledge_file(rel_path, data)
    return record


def list_project_incidents(repo_root: Path | str, *, resolved_only: bool = False) -> list[dict[str, Any]]:
    """Enumerate canonical incidents under repository root."""
    inc_dir = Path(repo_root) / ".local-ai-hub" / "agent-os" / "incidents"
    if not inc_dir.is_dir():
        return []
    records = []
    for file in sorted(inc_dir.glob("*.json")):
        if file.name.endswith(".tmp"):
            continue
        inc_id = file.stem
        if _identifier(inc_id):
            try:
                rec = load_project_incident(repo_root, inc_id)
                if not resolved_only or rec.get("payload", {}).get("resolved") is True:
                    records.append(rec)
            except Exception:
                continue
    return records


def find_project_incidents(
    repo_root: Path | str, *, query: str = "", affected_paths: list[str] | tuple[str, ...] = (),
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Find canonical project incidents by bounded text and changed-path matches."""
    store = RepoKnowledgeStore(repo_root)
    manifest, _ = store.manifest()
    query_tokens = set(re.findall(r"[a-z0-9]+", query.casefold().replace("_", " "))) - {
        "test", "tests", "pytest", "python", "command", "run", "error", "failed",
    }
    changed = {str(path).replace("\\", "/").casefold() for path in affected_paths}
    ranked = []
    for record in list_project_incidents(repo_root):
        if record.get("project_id") != manifest.get("project_id"):
            continue
        payload = record.get("payload", {})
        searchable = " ".join(str(payload.get(field, "")) for field in (
            "error_class", "redacted_message", "root_cause", "verified_fix",
        )).casefold().replace("_", " ")
        shared_terms = query_tokens & set(re.findall(r"[a-z0-9]+", searchable))
        path_match = bool(changed.intersection(
            str(path).replace("\\", "/").casefold() for path in payload.get("affected_paths", [])
        ))
        query_match = bool(shared_terms)
        if (query_tokens or changed) and not (query_match or path_match):
            continue
        ranked.append((len(shared_terms) + int(path_match), str(record.get("id", "")), record))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    return [record for _, _, record in ranked[:max(1, min(100, limit))]]
