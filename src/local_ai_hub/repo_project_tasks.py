"""Canonical Git-backed project tasks, goals, contracts, and checkpoints.

The Git repository is the authoritative owner for approved project tasks.
Local execution leases, private receipts, in-flight attempts, and transient
events stay local to the node's SQLite projection.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .agent_task_models import TaskStatus
from .repo_knowledge import RepoKnowledgeStore, _identifier, _text, validate_knowledge_file
from .repo_plan.schema_validation import RepoPlanValidationError

_CONTRACT_FIELDS = {
    "goal", "description", "acceptance_criteria", "non_goals", "constraints", "risk_profile",
}
_CHECKPOINT_FIELDS = {"phase", "next_action", "blockers", "affected_paths"}
_ALLOWED_STATUSES = {status.value for status in TaskStatus}


def _reject(message: str = "Invalid canonical project task") -> RepoPlanValidationError:
    return RepoPlanValidationError(message)


def _bounded_text(value: Any, maximum: int = 1500) -> bool:
    return value == "" or _text(value, maximum)


def _safe_relative_path(value: Any) -> bool:
    return (
        isinstance(value, str) and 0 < len(value) <= 512
        and not any(char in value for char in ("\\", ":"))
        and all(part not in {"", ".", ".."} and part.casefold() != ".git"
                for part in value.split("/"))
        and all(char.isprintable() for char in value)
    )


def validate_project_task_payload(record: Mapping[str, Any]) -> None:
    """Validate canonical project task record envelope and payload."""
    payload = record.get("payload")
    if (
        not isinstance(payload, dict)
        or not {"task_id", "status", "contract", "checkpoint"} <= set(payload)
        or set(payload) - {
            "task_id", "status", "contract", "checkpoint",
            "historical_verification", "source_dependencies", "previous_attempt",
            "created_at", "updated_at",
        }
        or not _identifier(payload["task_id"])
        or payload["status"] not in _ALLOWED_STATUSES
        or record.get("id") != payload["task_id"]
        or not isinstance(record.get("provenance"), dict)
        or not isinstance(record.get("evidence"), list)
        or not isinstance(record.get("relations"), list)
    ):
        raise _reject()

    if "previous_attempt" in payload:
        attempt = payload["previous_attempt"]
        if (
            not isinstance(attempt, dict)
            or set(attempt) != {"attempt_id", "parent_revision"}
            or not _identifier(attempt["attempt_id"])
            or attempt["attempt_id"] == payload["task_id"]
            or not isinstance(attempt["parent_revision"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", attempt["parent_revision"])
        ):
            raise _reject("Invalid project task attempt ancestry")

    contract = payload["contract"]
    checkpoint = payload["checkpoint"]
    if not isinstance(contract, dict) or set(contract) != _CONTRACT_FIELDS:
        raise _reject("Invalid task contract schema")
    if not _text(contract["goal"], 1500) or not _bounded_text(contract["description"], 1500):
        raise _reject("Invalid task contract text bounds")
    if contract["risk_profile"] not in ("normal", "low", "medium", "high", "critical"):
        raise _reject("Invalid task contract risk profile")
    for key in ("acceptance_criteria", "constraints", "non_goals"):
        items = contract[key]
        if not isinstance(items, list) or len(items) > 32 or not all(_text(item, 300) for item in items):
            raise _reject(f"Invalid task contract {key}")
    if not contract["acceptance_criteria"]:
        raise _reject("Task contract requires at least one acceptance criterion")

    if not isinstance(checkpoint, dict) or set(checkpoint) != _CHECKPOINT_FIELDS:
        raise _reject("Invalid task checkpoint schema")
    if not _bounded_text(checkpoint["phase"], 200) or not _bounded_text(checkpoint["next_action"], 500):
        raise _reject("Invalid task checkpoint text")
    for key in ("blockers", "affected_paths"):
        items = checkpoint[key]
        if not isinstance(items, list) or len(items) > 64:
            raise _reject(f"Invalid task checkpoint {key}")
        if key == "blockers" and not all(_text(item, 300) for item in items):
            raise _reject("Invalid task checkpoint blocker")
        if key == "affected_paths" and not all(_safe_relative_path(item) for item in items):
            raise _reject("Invalid task checkpoint path")


def build_project_task_record(
    store: RepoKnowledgeStore,
    task: Mapping[str, Any],
    *,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Construct an in-memory canonical task record ready for storage validation."""
    task_id = str(task.get("task_id", "")).strip()
    if not _identifier(task_id):
        raise _reject("Task identity must be a canonical identifier")

    contract = task.get("contract")
    checkpoint = task.get("checkpoint")
    if not isinstance(contract, dict) or not isinstance(checkpoint, dict):
        raise _reject("Task must contain contract and checkpoint objects")

    manifest, _ = store.manifest()
    payload: dict[str, Any] = {
        "task_id": task_id,
        "status": str(task.get("status", "planned")),
        "contract": {
            "goal": str(contract.get("goal", "")),
            "description": str(contract.get("description", "") or ""),
            "acceptance_criteria": list(contract.get("acceptance_criteria") or []),
            "non_goals": list(contract.get("non_goals") or []),
            "constraints": list(contract.get("constraints") or []),
            "risk_profile": str(contract.get("risk_profile", "normal")),
        },
        "checkpoint": {
            "phase": str(checkpoint.get("phase", "") or ""),
            "next_action": str(checkpoint.get("next_action", "") or ""),
            "blockers": list(checkpoint.get("blockers") or []),
            "affected_paths": sorted(set(checkpoint.get("affected_paths") or [])),
        },
    }
    if "previous_attempt" in task:
        payload["previous_attempt"] = dict(task["previous_attempt"])
    if "historical_verification" in task:
        payload["historical_verification"] = task["historical_verification"]

    record = {
        "schema_version": 1,
        "project_id": manifest["project_id"],
        "kind": "task",
        "id": task_id,
        "payload": payload,
        "provenance": provenance or {"origin_kind": "manual"},
        "evidence": [],
        "relations": [],
    }
    validate_project_task_payload(record)
    return record


def task_file_path(repo_root: Path | str, task_id: str) -> Path:
    """Return filesystem path for canonical project task file."""
    if not _identifier(task_id):
        raise _reject("Invalid task identifier")
    return Path(repo_root) / ".local-ai-hub" / "agent-os" / "tasks" / f"{task_id}.json"


def load_project_task(repo_root: Path | str, task_id: str) -> dict[str, Any]:
    """Load canonical project task from disk and validate schema."""
    path = task_file_path(repo_root, task_id)
    if not path.is_file():
        raise FileNotFoundError(f"Canonical project task '{task_id}' not found at {path}")
    data = path.read_bytes()
    rel_path = f".local-ai-hub/agent-os/tasks/{task_id}.json"
    record = validate_knowledge_file(rel_path, data)
    return record


def list_project_tasks(repo_root: Path | str) -> list[dict[str, Any]]:
    """Enumerate all valid canonical project tasks under repository root."""
    tasks_dir = Path(repo_root) / ".local-ai-hub" / "agent-os" / "tasks"
    if not tasks_dir.is_dir():
        return []
    tasks = []
    for file in sorted(tasks_dir.glob("*.json")):
        if file.name.endswith(".tmp"):
            continue
        task_id = file.stem
        if _identifier(task_id):
            try:
                tasks.append(load_project_task(repo_root, task_id))
            except Exception:
                continue
    return tasks
