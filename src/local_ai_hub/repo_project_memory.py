"""Canonical Git-backed project memory records.

Git is the authoritative owner of reviewed durable knowledge, facts, concepts,
and patterns. Ephemeral session context, credentials, and local execution evidence
are strictly excluded and remain in local SQLite.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .repo_knowledge import RepoKnowledgeStore, _identifier, _text, validate_knowledge_file
from .repo_knowledge_privacy import contains_private_project_data
from .repo_plan.schema_validation import RepoPlanValidationError

_ALLOWED_KINDS = {"concept", "fact", "pattern", "rule", "decision", "negative_knowledge"}
_ALLOWED_SCOPES = {"project", "workspace", "global"}
_ALLOWED_SENSITIVITIES = {"low", "internal"}


def _reject(message: str = "Invalid canonical project memory") -> RepoPlanValidationError:
    return RepoPlanValidationError(message)


def validate_project_memory_payload(record: Mapping[str, Any]) -> None:
    """Validate canonical project memory envelope and payload."""
    payload = record.get("payload")
    if (
        not isinstance(payload, dict)
        or not {"record_id", "kind", "scope", "key", "value"} <= set(payload)
        or set(payload) - {
            "record_id", "kind", "scope", "key", "value", "confidence",
            "source", "sensitivity", "quarantine_reason", "contradicts_record_id",
            "supersedes_record_id", "expires_at", "created_at", "updated_at",
        }
        or not _identifier(payload["record_id"])
        or record.get("id") != payload["record_id"]
        or payload["kind"] not in _ALLOWED_KINDS
        or payload["scope"] not in _ALLOWED_SCOPES
        or not _text(payload["key"], 256)
        or not isinstance(record.get("provenance"), dict)
        or not isinstance(record.get("evidence"), list)
        or not isinstance(record.get("relations"), list)
    ):
        raise _reject()

    # Durable memory may be shared through Git; reject private field names and
    # recognizable credential values wherever they appear in nested content.
    if contains_private_project_data(payload):
        raise _reject("Project memory payload contains private session, receipt, or credential data")

    value = payload["value"]
    if not (isinstance(value, (str, dict, list)) and len(json.dumps(value)) <= 65536):
        raise _reject("Memory value exceeds size or type constraints")

    confidence = payload.get("confidence", 1.0)
    if not isinstance(confidence, (int, float)) or not (0.0 <= confidence <= 1.0):
        raise _reject("Memory confidence must be between 0.0 and 1.0")

    sensitivity = payload.get("sensitivity", "internal")
    if sensitivity == "confidential":
        raise _reject("confidential memory cannot be published in the shared Git store")
    if sensitivity not in _ALLOWED_SENSITIVITIES:
        raise _reject("Invalid memory sensitivity")


def build_project_memory_record(
    store: RepoKnowledgeStore,
    memory_data: Mapping[str, Any],
    *,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Construct a canonical memory record ready for persistence."""
    record_id = str(memory_data.get("record_id", "")).strip()
    if not _identifier(record_id):
        # Generate stable id from key and scope
        h = hashlib.sha256(f"{memory_data.get('scope', 'project')}:{memory_data.get('key', '')}".encode()).hexdigest()[:16]
        record_id = f"mem-{h}"

    manifest, _ = store.manifest()
    payload: dict[str, Any] = {
        "record_id": record_id,
        "kind": str(memory_data.get("kind", "fact")),
        "scope": str(memory_data.get("scope", "project")),
        "key": str(memory_data.get("key", "")).strip(),
        "value": memory_data.get("value"),
        "confidence": float(memory_data.get("confidence", 1.0)),
        "source": str(memory_data.get("source", "agent") or "agent"),
        "sensitivity": str(memory_data.get("sensitivity", "internal")),
    }
    if "quarantine_reason" in memory_data and memory_data["quarantine_reason"]:
        payload["quarantine_reason"] = str(memory_data["quarantine_reason"])
    if "supersedes_record_id" in memory_data and memory_data["supersedes_record_id"]:
        payload["supersedes_record_id"] = str(memory_data["supersedes_record_id"])

    record = {
        "schema_version": 1,
        "project_id": manifest["project_id"],
        "kind": "memory",
        "id": record_id,
        "payload": payload,
        "provenance": provenance or {"origin_kind": "manual"},
        "evidence": [],
        "relations": [],
    }
    validate_project_memory_payload(record)
    return record


def memory_file_path(repo_root: Path | str, record_id: str) -> Path:
    """Return filesystem path for canonical project memory file."""
    if not _identifier(record_id):
        raise _reject("Invalid memory record identifier")
    return Path(repo_root) / ".local-ai-hub" / "agent-os" / "memory" / f"{record_id}.json"


def load_project_memory(repo_root: Path | str, record_id: str) -> dict[str, Any]:
    """Load canonical project memory from disk and validate schema."""
    path = memory_file_path(repo_root, record_id)
    if not path.is_file():
        raise FileNotFoundError(f"Canonical memory record '{record_id}' not found at {path}")
    data = path.read_bytes()
    rel_path = f".local-ai-hub/agent-os/memory/{record_id}.json"
    record = validate_knowledge_file(rel_path, data)
    return record


def list_project_memory(repo_root: Path | str, *, kind: str = "") -> list[dict[str, Any]]:
    """Enumerate canonical memory records under repository root."""
    mem_dir = Path(repo_root) / ".local-ai-hub" / "agent-os" / "memory"
    if not mem_dir.is_dir():
        return []
    records = []
    for file in sorted(mem_dir.glob("*.json")):
        if file.name.endswith(".tmp"):
            continue
        record_id = file.stem
        if _identifier(record_id):
            try:
                rec = load_project_memory(repo_root, record_id)
                if not kind or rec.get("payload", {}).get("kind") == kind:
                    records.append(rec)
            except Exception:
                continue
    return records
