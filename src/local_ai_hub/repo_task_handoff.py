"""Portable task handoffs, not a second canonical Agent OS task store.

Only explicitly reviewed task intent and checkpoint guidance cross a checkout.
Execution leases, receipts, raw events, contexts and local state stay local.
"""
from __future__ import annotations

import hashlib
import json
import re
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
        or not {"origin_task_id", "historical_status", "contract", "checkpoint"} <= set(payload)
        or set(payload) - {"origin_task_id", "historical_status", "contract", "checkpoint",
                           "historical_verification", "source_dependencies", "previous_attempt"}
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
    if "previous_attempt" in payload:
        attempt = payload["previous_attempt"]
        if (
            not isinstance(attempt, dict)
            or set(attempt) != {"attempt_id", "parent_revision"}
            or not _identifier(attempt["attempt_id"])
            or attempt["attempt_id"] == payload["origin_task_id"]
            or not isinstance(attempt["parent_revision"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", attempt["parent_revision"])
        ):
            raise _reject("Invalid portable attempt ancestry")
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
    if "source_dependencies" in payload:
        dependencies = payload["source_dependencies"]
        if not isinstance(dependencies, list) or len(dependencies) > 32:
            raise _reject("Invalid handoff source dependencies")
        declared = []
        for dependency in dependencies:
            if (
                not isinstance(dependency, dict)
                or set(dependency) != {"path", "content_digest"}
                or not _safe_relative_path(dependency["path"])
                or not isinstance(dependency["content_digest"], str)
                or (dependency["content_digest"] != "" and not re.fullmatch(r"[0-9a-f]{64}", dependency["content_digest"]))
                or (dependency["content_digest"] and not _dependency_path_allowed(dependency["path"]))
            ):
                raise _reject("Invalid or private source dependency")
            declared.append(dependency["path"])
        if declared != sorted(set(paths)):
            raise _reject("Source dependencies must cover exactly the declared affected paths")
    if "historical_verification" in payload:
        summaries = payload["historical_verification"]
        if not isinstance(summaries, list) or not 1 <= len(summaries) <= 8:
            raise _reject("Invalid historical verification summaries")
        seen: set[str] = set()
        for summary in summaries:
            if (
                not isinstance(summary, dict)
                or set(summary) != {"criterion_digest", "evidence_type", "reported_pass", "revision_digest"}
                or any(not isinstance(summary[key], str) or not re.fullmatch(r"[0-9a-f]{64}", summary[key])
                       for key in ("criterion_digest", "revision_digest"))
                or summary["evidence_type"] not in {"test", "benchmark", "source_review"}
                or type(summary["reported_pass"]) is not bool
                or summary["criterion_digest"] in seen
            ):
                raise _reject("Invalid historical verification summary")
            if summary["criterion_digest"] not in {
                hashlib.sha256(criterion.encode("utf-8")).hexdigest()
                for criterion in contract["acceptance_criteria"]
            }:
                raise _reject("Historical summary is not linked to a contract criterion")
            seen.add(summary["criterion_digest"])
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
    origin_task_id = task_id
    previous_attempt = None
    state_data = raw_checkpoint.get("state_data", {})
    if not isinstance(state_data, Mapping):
        raise _reject("Invalid task checkpoint state")
    if "_portable_attempt" in state_data:
        lineage = state_data["_portable_attempt"]
        if (
            not isinstance(lineage, Mapping)
            or set(lineage) != {"schema_version", "project_id", "handoff_id", "handoff_revision",
                                "origin_task_id", "attempt_id", "preview_digest"}
            or type(lineage["schema_version"]) is not int or lineage["schema_version"] != 1
            or lineage["project_id"] != manifest["project_id"]
            or lineage["attempt_id"] != task_id
            or not _identifier(lineage["origin_task_id"]) or lineage["origin_task_id"] == task_id
            or lineage["handoff_id"] != "handoff-" + hashlib.sha256(
                lineage["origin_task_id"].encode("utf-8")
            ).hexdigest()[:24]
            or any(not isinstance(lineage[key], str) or not re.fullmatch(r"[0-9a-f]{64}", lineage[key])
                   for key in ("handoff_revision", "preview_digest"))
        ):
            raise _reject("Invalid server-managed portable attempt lineage")
        origin_task_id = lineage["origin_task_id"]
        previous_attempt = {"attempt_id": task_id, "parent_revision": lineage["handoff_revision"]}
        # Require the exact adopted record; stale parallel attempts cannot
        # silently overwrite the latest shared continuation. Same-attempt
        # subsequent exports are left for explicit reconciliation.
        parent = store.get("handoff", lineage["handoff_id"], verify_sources=False)
        if parent["revision"] != lineage["handoff_revision"]:
            raise _reject("Parent handoff changed; reconcile competing attempts before publication")
        adopted = handoff_resume_contract(parent["record"])
        original = parent["record"]["payload"]["contract"]
        # Do not duplicate synthetic resume guidance in successive exports.
        for field in ("description", "constraints"):
            if goal[field] == adopted[field]:
                goal[field] = original[field]

    # A nonempty SLO profile may carry execution policy or acceptance details.
    # Do not silently drop it and claim that the handoff is complete.
    if goal["scope"] != "task" or goal["slo_profile"]:
        raise _reject("Non-task scope or custom SLO profile requires explicit conversion")
    record = {
        "schema_version": 1, "project_id": manifest["project_id"],
        "kind": "handoff", "id": "handoff-" + hashlib.sha256(str(origin_task_id).encode("utf-8")).hexdigest()[:24],
        "payload": {
            "origin_task_id": origin_task_id, "historical_status": task.get("status"),
            "contract": {key: goal[key] for key in sorted(_CONTRACT_FIELDS)},
            "checkpoint": {key: raw_checkpoint.get(key, [] if key in {"blockers", "affected_paths"} else "")
                           for key in sorted(_CHECKPOINT_FIELDS)},
        },
        "provenance": {"origin_kind": "manual"}, "evidence": [], "relations": [],
    }
    if previous_attempt is not None:
        record["payload"]["previous_attempt"] = previous_attempt
    validate_handoff_payload(record)
    return record


def _dependency_path_allowed(path: str) -> bool:
    from .repo_knowledge_assertions import _PRIVATE

    return _safe_relative_path(path) and not any(
        part.startswith(".") or _PRIVATE.search(part) or part.lower().endswith((".pem", ".p12", ".key", ".pfx"))
        for part in path.split("/")
    )


def _dependency_digest(root: Path, path: str) -> str:
    """Hash only a single, tracked, unconflicted regular source file.

    A tracked working-tree file may contain an uncommitted edit. Its hash
    is intentionally not replaced with the index blob hash: a second clone
    without that edit must not look ready. No contents are published.
    """
    from .evidence import EvidenceStore, _evidence_path_under_root
    from .repo_knowledge_sync import _git

    if not _dependency_path_allowed(path):
        return ""
    index = _git(root, "ls-files", "--stage", "-z", "--", ":(literal)" + path)
    if not index:
        return ""
    meta, separator, name = index.partition(b"\t")
    if (
        not separator or name != path.encode("utf-8") + b"\0"
        or not re.fullmatch(rb"(?:100644|100755) (?:[0-9a-f]{40}|[0-9a-f]{64}) 0", meta)
    ):
        return ""
    source = _evidence_path_under_root(str(root), path, strict=True)
    if source is None or not source.is_file():
        return ""
    try:
        digest = EvidenceStore._hash_source_file(source)
        if (
            _evidence_path_under_root(str(root), path, strict=True) != source
            or _git(root, "ls-files", "--stage", "-z", "--", ":(literal)" + path) != index
        ):
            return ""
        return digest
    except (OSError, ValueError, RuntimeError):
        return ""


def attach_source_dependencies(store: RepoKnowledgeStore, record: Mapping[str, Any]) -> dict[str, Any]:
    """Capture a bounded working-tree dependency inventory for explicit export."""
    validate_handoff_payload(record)
    manifest, revision = store.manifest()
    if record["project_id"] != manifest["project_id"]:
        raise _reject("Handoff project identity mismatch")
    updated = {**record, "payload": dict(record["payload"])}
    updated["payload"]["source_dependencies"] = [
        {"path": path, "content_digest": _dependency_digest(store.root, path)}
        for path in sorted(set(record["payload"]["checkpoint"]["affected_paths"]))
    ]
    if store.manifest()[1] != revision:
        raise _reject("Project changed during dependency capture")
    validate_handoff_payload(updated)
    return updated


def inspect_handoff_dependencies(store: RepoKnowledgeStore, record: Mapping[str, Any]) -> dict[str, Any]:
    """Assess declared paths only, never claim full patch or runtime proof."""
    validate_handoff_payload(record)
    manifest, revision = store.manifest()
    if record["project_id"] != manifest["project_id"]:
        raise _reject("Handoff project identity mismatch")
    payload = record["payload"]
    paths = sorted(set(payload["checkpoint"]["affected_paths"]))
    declared = {row["path"]: row["content_digest"] for row in payload.get("source_dependencies", [])}
    rows = []
    for path in paths:
        expected = declared.get(path, "")
        actual = _dependency_digest(store.root, path) if expected else ""
        status = ("unrecorded" if not expected else "unavailable" if not actual
                  else "matching" if actual == expected else "different")
        rows.append({"path": path, "status": status, "expected_digest": expected, "current_digest": actual})
    if store.manifest()[1] != revision:
        raise _reject("Project changed during dependency inspection")
    return {
        "state": ("no_declared_paths" if not paths else "matching_declared_paths"
                  if all(row["status"] == "matching" for row in rows) else "blocked_missing_dependency"),
        "resume_allowed": all(row["status"] == "matching" for row in rows),
        "paths": rows,
        "coverage": "declared_affected_paths_only",
        "runtime_verified": False,
    }


def attach_historical_verification(
    record: Mapping[str, Any], task: Mapping[str, Any], receipts: list[Any],
) -> dict[str, Any]:
    """Project only linked receipt observations, never fresh or trusted proof.

    No raw receipt/evidence/command IDs, text, details, credentials, or host
    paths are published. Callers obtain receipts through the scoped Hub API.
    """
    validate_handoff_payload(record)
    payload = record["payload"]
    attempt_id = payload.get("previous_attempt", {}).get("attempt_id", payload["origin_task_id"])
    if task.get("task_id") != attempt_id:
        raise _reject("Receipt task scope mismatch")
    links = task.get("verification_receipts")
    if not isinstance(links, dict) or not isinstance(receipts, list) or len(receipts) > 64:
        raise _reject("Unavailable or oversized verification inventory")
    indexed: dict[str, Mapping[str, Any]] = {}
    for receipt in receipts:
        if not isinstance(receipt, Mapping) or receipt.get("task_id") != task["task_id"]:
            raise _reject("Receipt task scope mismatch")
        ident = receipt.get("receipt_id")
        if not isinstance(ident, str) or not ident or ident in indexed:
            raise _reject("Invalid or duplicate receipt identity")
        indexed[ident] = receipt
    summaries = []
    for criterion in payload["contract"]["acceptance_criteria"]:
        if criterion not in links:
            continue
        ident = links[criterion]
        if not isinstance(ident, str):
            raise _reject("Invalid task receipt link")
        receipt = indexed.get(ident)
        if receipt is None or receipt.get("criterion") != criterion:
            raise _reject("Linked receipt unavailable or mismatched")
        revision = receipt.get("repository_revision")
        if not isinstance(revision, str) or not revision.strip():
            raise _reject("Linked receipt has no repository revision")
        summaries.append({
            "criterion_digest": hashlib.sha256(criterion.encode("utf-8")).hexdigest(),
            "revision_digest": hashlib.sha256(revision.encode("utf-8")).hexdigest(),
            "evidence_type": receipt.get("evidence_type"),
            "reported_pass": receipt.get("passed"),
        })
    if len(summaries) > 8:
        raise _reject("Historical verification summary exceeds publication bound")
    updated = {**record, "payload": dict(payload)}
    updated["payload"].pop("historical_verification", None)
    if summaries:
        updated["payload"]["historical_verification"] = summaries
    validate_handoff_payload(updated)
    return updated


def handoff_resume_contract(record: Mapping[str, Any]) -> dict[str, Any]:
    """Derive a fresh planned task contract. Never import historical success."""
    validate_handoff_payload(record)
    payload = record["payload"]
    contract = dict(payload["contract"])
    checkpoint = payload["checkpoint"]
    guidance = "\n\nHistorical handoff (unverified; inspect current checkout before use):"
    guidance += "\nPrevious status: " + payload["historical_status"]
    if payload.get("historical_verification"):
        guidance += "\nHistorical receipt summaries exist; none are valid verification for this attempt."
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


def preview_handoff_resume(store: RepoKnowledgeStore, handoff_id: str) -> dict[str, Any]:
    """One read-only resume preview shared by HTTP and the CLI."""
    from .repo_knowledge import _digest_value

    epoch = store.read_epoch()
    manifest_revision = store.manifest()[1]
    item = store.get("handoff", handoff_id, verify_sources=False)
    dependencies = inspect_handoff_dependencies(store, item["record"])
    contract = handoff_resume_contract(item["record"])
    if (
        store.manifest()[1] != manifest_revision
        or store.get("handoff", handoff_id, verify_sources=False)["revision"] != item["revision"]
    ):
        raise _reject("Handoff changed during preview")
    store.require_read_epoch(epoch)
    return {
        "preview": True, "revision": item["revision"], "contract": contract,
        "historical_verification": item["record"]["payload"].get("historical_verification", []),
        "dependencies": dependencies,
        "resume_allowed": dependencies["resume_allowed"],
        "preview_digest": _digest_value([manifest_revision, item["revision"], dependencies, contract]),
        "requires_revalidation": True,
    }


def validate_resume_creation(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Recheck reviewed handoff at the existing scoped task-create boundary.

    Root and repository identity have already been bound by the HTTP task
    route. This check is a freshness precondition, never execution authority.
    """
    selection = payload.get("handoff_resume")
    if (
        not isinstance(selection, Mapping)
        or set(selection) != {"handoff_id", "revision", "preview_digest"}
        or not _identifier(selection["handoff_id"])
        or any(not isinstance(selection[key], str) or not re.fullmatch(r"[0-9a-f]{64}", selection[key])
               for key in ("revision", "preview_digest"))
        or not _identifier(payload.get("task_id"))
        or payload.get("auto_worktree", False) is not False
        or not isinstance(payload.get("repo_root"), str)
        or not payload["repo_root"]
        or payload.get("root") != payload["repo_root"]
    ):
        raise _reject("Invalid scoped handoff creation")
    store = RepoKnowledgeStore(payload["repo_root"])
    checked = preview_handoff_resume(store, selection["handoff_id"])
    if (
        checked["resume_allowed"] is not True
        or checked["revision"] != selection["revision"]
        or checked["preview_digest"] != selection["preview_digest"]
        or payload.get("contract") != checked["contract"]
    ):
        raise _reject("Handoff or dependencies changed; preview again")
    epoch = store.read_epoch()
    manifest, manifest_revision = store.manifest()
    item = store.get("handoff", selection["handoff_id"], verify_sources=False)
    origin = item["record"]["payload"]["origin_task_id"]
    previous_attempt = item["record"]["payload"].get("previous_attempt", {})
    if (item["revision"] != checked["revision"] or origin == payload["task_id"]
            or previous_attempt.get("attempt_id") == payload["task_id"]):
        raise _reject("Handoff must create a new local task identity")
    if store.manifest()[1] != manifest_revision:
        raise _reject("Project changed during attempt creation")
    store.require_read_epoch(epoch)
    # Persist only portable identities and exact adopted revision, not a
    # previous owner's lease, session, receipt or execution status.
    return {
        "schema_version": 1, "project_id": manifest["project_id"],
        "handoff_id": selection["handoff_id"], "handoff_revision": item["revision"],
        "origin_task_id": origin, "attempt_id": payload["task_id"],
        "preview_digest": checked["preview_digest"],
    }


def list_task_handoffs(store: RepoKnowledgeStore, *, limit: int = 32) -> dict[str, Any]:
    """Discover shared handoffs in this checkout without importing task state."""
    from itertools import islice

    from .evidence import _evidence_path_under_root

    if type(limit) is not int or not 1 <= limit <= 64:
        raise _reject("Handoff limit must be between 1 and 64")
    epoch = store.read_epoch()
    manifest, manifest_revision = store.manifest()
    relative = ".local-ai-hub/agent-os/handoffs"
    parent = store.root / relative
    result: dict[str, Any] = {
        "project_id": manifest["project_id"], "complete": True,
        "handoffs": [], "issues": [], "authority": "historical_declaration",
    }
    if not parent.exists() and not parent.is_symlink():
        store.require_read_epoch(epoch)
        return result
    if _evidence_path_under_root(str(store.root), relative, strict=True) != parent or not parent.is_dir():
        raise _reject("Unsafe handoff directory")
    entries = list(islice(parent.iterdir(), limit + 1))
    if len(entries) > limit:
        result["complete"] = False
        result["issues"].append("inventory_limit")
    for entry in sorted(entries[:limit]):
        if entry.suffix != ".json" or not _identifier(entry.stem):
            result["complete"] = False
            result["issues"].append("unexpected_entry")
            continue
        try:
            item = store.get("handoff", entry.stem, verify_sources=False)
        except (OSError, RepoPlanValidationError):
            result["complete"] = False
            result["issues"].append("invalid_or_unavailable_handoff")
            continue
        payload = item["record"]["payload"]
        result["handoffs"].append({
            "id": entry.stem, "revision": item["revision"],
            "goal": payload["contract"]["goal"][:160],
            "historical_status": payload["historical_status"],
            "requires_revalidation": True,
        })
    if store.manifest()[1] != manifest_revision:
        raise _reject("Project changed during handoff inventory")
    store.require_read_epoch(epoch)
    return result


def preflight_task_handoffs(
    store: RepoKnowledgeStore, tasks: list[Any], *, inventory_complete: bool,
) -> dict[str, Any]:
    """Classify legacy task snapshots before any reviewed handoff publication.

    This is not a canonical store cutover. It never copies receipts, leases,
    local evidence or execution state, and never returns raw contract content.
    """
    from .repo_knowledge import _encode, _path_for, validate_knowledge_file

    if not isinstance(tasks, list) or len(tasks) > 64:
        raise _reject("Preflight requires a bounded task inventory")
    epoch = store.read_epoch()
    manifest, manifest_revision = store.manifest()
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for task in tasks:
        row: dict[str, Any] = {"state": "blocked_invalid_or_out_of_scope"}
        if isinstance(task, Mapping):
            task_id = task.get("task_id")
            if _identifier(task_id):
                assert isinstance(task_id, str)
                # Verify the scope before returning even a task identifier.
                try:
                    record = build_task_handoff(store, task)
                    validate_knowledge_file(_path_for("handoff", record["id"]), _encode(record))
                except (OSError, RepoPlanValidationError, ValueError, TypeError):
                    rows.append(row)
                    continue
                row = {"handoff_id": record["id"], "state": "review_required"}
                if task_id in seen:
                    row["state"] = "blocked_duplicate_task"
                elif task.get("status") in {"active", "verifying"} or task.get("lease_id"):
                    row["state"] = "blocked_live_attempt"
                else:
                    try:
                        existing = store.get("handoff", record["id"], verify_sources=False)
                    except FileNotFoundError:
                        existing = None
                    except (OSError, RepoPlanValidationError):
                        row["state"] = "blocked_existing_record_invalid"
                        rows.append(row)
                        seen.add(task_id)
                        continue
                    if existing is not None:
                        existing_record = existing["record"]
                        if existing_record == record:
                            row["state"] = "already_published"
                        elif existing_record["payload"].get("historical_verification"):
                            # Do not classify a receipt-bearing handoff as a
                            # safe overwrite merely because legacy intent matches.
                            row["state"] = "blocked_existing_record_differs"
                            row["historical_verification_present"] = True
                        else:
                            row["state"] = "blocked_existing_record_differs"
                        row["revision"] = existing["revision"]
                    elif manifest["mode"] == "read_only":
                        row["state"] = "blocked_read_only"
                seen.add(task_id)
        rows.append(row)
    if store.manifest()[1] != manifest_revision:
        raise _reject("Project changed during handoff preflight")
    store.require_read_epoch(epoch)
    return {
        "project_id": manifest["project_id"],
        "complete": inventory_complete is True,
        "records": rows,
        "publication_requires_review": True,
        "canonical_cutover_supported": False,
        "runtime_state_imported": False,
    }
