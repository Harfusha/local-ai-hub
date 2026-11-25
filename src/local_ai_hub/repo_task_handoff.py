"""Portable task handoffs, not a second canonical Agent OS task store.

Only explicitly reviewed task intent and checkpoint guidance cross a checkout.
Execution leases, receipts, raw events, contexts and local state stay local.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .agent_task_models import GoalContract, TaskStatus
from .repo_knowledge import RepoKnowledgeStore, _identifier, _text
from .repo_plan.schema_validation import RepoPlanValidationError
from .secret_scan_config import _SECRET_SCAN_PATTERNS

_CONTRACT_FIELDS = {
    "goal", "description", "acceptance_criteria", "non_goals", "constraints", "risk_profile",
}
_CHECKPOINT_FIELDS = {"phase", "next_action", "blockers", "affected_paths"}


def _reject(message: str = "Invalid portable task handoff") -> RepoPlanValidationError:
    return RepoPlanValidationError(message)


def _bounded_text(value: Any, maximum: int = 1000) -> bool:
    return value == "" or _text(value, maximum)


def _safe_relative_path(value: Any) -> bool:
    return (
        isinstance(value, str) and 0 < len(value) <= 512
        and not any(char in value for char in ("\\", ":"))
        and all(part not in {"", ".", ".."} and part.casefold() != ".git"
                for part in value.split("/"))
        and all(char.isprintable() for char in value)
    )


def validate_handoff_payload(record: Mapping[str, Any]) -> None:
    payload = record.get("payload")
    if (
        not isinstance(payload, dict)
        or set(payload) != {"origin_task_id", "historical_status", "contract", "checkpoint"}
        or not _identifier(payload["origin_task_id"])
        or payload["historical_status"] not in tuple(status.value for status in TaskStatus)
        or record.get("id") != "handoff-" + hashlib.sha256(
            str(payload["origin_task_id"]).encode("utf-8")
        ).hexdigest()[:24]
        or record.get("provenance") != {"origin_kind": "manual"}
        or record.get("evidence") != []
        or record.get("relations") != []
    ):
        raise _reject()
    contract = payload["contract"]
    checkpoint = payload["checkpoint"]
    if not isinstance(contract, dict) or set(contract) != _CONTRACT_FIELDS:
        raise _reject()
    if not _text(contract["goal"], 1500) or not _bounded_text(contract["description"], 1500):
        raise _reject()
    if contract["risk_profile"] not in ("normal", "low", "medium", "high", "critical"):
        raise _reject()
    for key in ("acceptance_criteria", "constraints", "non_goals"):
        values = contract[key]
        if not isinstance(values, list) or len(values) > 16 or any(not _text(value, 500) for value in values):
            raise _reject()
    if not isinstance(checkpoint, dict) or set(checkpoint) != _CHECKPOINT_FIELDS:
        raise _reject()
    if not _bounded_text(checkpoint["phase"], 80) or not _bounded_text(checkpoint["next_action"], 1000):
        raise _reject()
    blockers = checkpoint["blockers"]
    paths = checkpoint["affected_paths"]
    if not isinstance(blockers, list) or len(blockers) > 16 or any(not _text(value, 500) for value in blockers):
        raise _reject()
    if not isinstance(paths, list) or len(paths) > 32 or any(not _safe_relative_path(path) for path in paths):
        raise _reject("Handoff affected paths must be portable relative paths")
    # Recognized secret patterns are rejected; operator privacy review remains
    # essential because a regex cannot establish that arbitrary text is public.
    text = json.dumps(record, ensure_ascii=False)
    if any(pattern.search(text) for _, _, pattern, _ in _SECRET_SCAN_PATTERNS):
        raise _reject("Handoff contains a recognized secret pattern")


def build_task_handoff(store: RepoKnowledgeStore, task: Mapping[str, Any]) -> dict[str, Any]:
    """Project an actual scoped Agent OS task without copying execution state."""
    manifest, _ = store.manifest()
    raw_root = task.get("repo_root")
    try:
        if not isinstance(raw_root, str) or not Path(raw_root).is_absolute() or not Path(raw_root).samefile(store.root):
            raise _reject("Task does not belong to the selected checkout")
    except (OSError, ValueError, RuntimeError) as exc:
        raise _reject("Task repository scope unavailable") from exc
    task_id = task.get("task_id")
    if not _identifier(task_id):
        raise _reject("Task ID is not portable")
    raw_contract = task.get("contract")
    raw_checkpoint = task.get("checkpoint")
    if not isinstance(raw_contract, Mapping) or not isinstance(raw_checkpoint, Mapping):
        raise _reject()
    goal = GoalContract.from_dict(raw_contract).to_dict()
    # A nonempty SLO profile may carry execution policy or acceptance details.
    # Do not silently drop it and claim that the handoff is complete.
    if goal["scope"] != "task" or goal["slo_profile"]:
        raise _reject("Non-task scope or custom SLO profile requires explicit conversion")
    record = {
        "schema_version": 1, "project_id": manifest["project_id"],
        "kind": "handoff", "id": "handoff-" + hashlib.sha256(str(task_id).encode("utf-8")).hexdigest()[:24],
        "payload": {
            "origin_task_id": task_id, "historical_status": task.get("status"),
            "contract": {key: goal[key] for key in sorted(_CONTRACT_FIELDS)},
            "checkpoint": {key: raw_checkpoint.get(key, [] if key in {"blockers", "affected_paths"} else "")
                           for key in sorted(_CHECKPOINT_FIELDS)},
        },
        "provenance": {"origin_kind": "manual"}, "evidence": [], "relations": [],
    }
    validate_handoff_payload(record)
    return record


def handoff_resume_contract(record: Mapping[str, Any]) -> dict[str, Any]:
    """Derive a fresh planned task contract. Never import historical success."""
    validate_handoff_payload(record)
    payload = record["payload"]
    contract = dict(payload["contract"])
    checkpoint = payload["checkpoint"]
    guidance = "\n\nHistorical handoff (unverified; inspect current checkout before use):"
    guidance += "\nPrevious status: " + payload["historical_status"]
    if checkpoint["next_action"]:
        guidance += "\nSuggested next action: " + checkpoint["next_action"]
    if checkpoint["affected_paths"]:
        guidance += "\nPrevious affected paths: " + ", ".join(checkpoint["affected_paths"])
    if checkpoint["blockers"]:
        guidance += "\nPrevious blockers: " + "; ".join(checkpoint["blockers"])
    contract["description"] = contract["description"] + guidance
    contract["constraints"] = [*contract["constraints"],
        "Revalidate current source, requirements and all acceptance criteria; no historical receipt is valid for this attempt."]
    return GoalContract.from_dict(contract).to_dict()
