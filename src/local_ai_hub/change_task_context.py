"""Root-scoped task and verification candidates for a change plan."""
from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

from .agent_task_models import _task_matches_scope

_MAX_TASKS = 8


def scoped_tasks(store: Any, root: str, task_id: str = "") -> tuple[list[Any], bool]:
    if store is None:
        if task_id:
            raise ValueError("Scoped task store unavailable")
        return [], False
    if task_id:
        task = store.get(task_id)
        if task is None or not _task_matches_scope(task, root, task_id):
            raise ValueError("Scoped task not found")
        return [task], False
    page = store.list_tasks(status=None, limit=_MAX_TASKS + 1, repo_root=root)
    tasks = [task for task in page.tasks if _task_matches_scope(task, root)]
    return tasks[:_MAX_TASKS], len(tasks) > _MAX_TASKS or bool(getattr(page, "has_more", False))


def current_task_revision(services: Any, root: str) -> str:
    tracker = getattr(services, "repo_state", None)
    fingerprint = getattr(tracker, "fingerprint", None)
    if not callable(fingerprint):
        return ""
    try:
        result = fingerprint(root, force=True)
    except Exception:
        return ""
    if not isinstance(result, dict) or result.get("success") is False or result.get("degraded") or result.get("stale"):
        return ""
    revision = result.get("fingerprint")
    return revision if isinstance(revision, str) and revision and len(revision) <= 512 else ""


def _affected_paths(task: Any, root: str) -> set[str]:
    paths = set()
    for raw in task.checkpoint.affected_paths[:256]:
        try:
            path = Path(raw)
            if path.is_absolute():
                path = path.relative_to(root)
            relative = PurePosixPath(path.as_posix())
            if relative.is_absolute() or ".." in relative.parts or not relative.parts:
                continue
            paths.add(relative.as_posix())
        except (TypeError, ValueError):
            continue
    return paths


def task_verification_candidates(services: Any, task: Any, revision: str) -> dict[str, Any]:
    store = getattr(services, "verification_store", None)
    output: dict[str, Any] = {
        "task_id": task.task_id,
        "verification_scope": "whole_worktree_task_only",
        "commit_verified": False,
        "status": "unknown",
        "current_receipt_count": 0,
    }
    if store is None or not revision:
        return output
    result = store.completion(task.task_id, current_revision=revision)
    satisfied = set(result.satisfied_criteria)
    accepted = [
        receipt for receipt in result.receipts
        if receipt.passed and receipt.repository_revision == revision
        and receipt.criterion in satisfied
    ]
    output.update({
        "status": "task_completion_current" if result.complete else "task_completion_incomplete",
        "satisfied_count": len(satisfied),
        "unsatisfied_count": len(result.unsatisfied_criteria),
        "stale_count": len(result.stale_criteria),
        "current_receipt_count": len(accepted),
        "receipt_ids": [receipt.receipt_id for receipt in accepted[:8]],
        "receipt_ids_omitted": max(0, len(accepted) - 8),
    })
    return output


def attach_task_context(
    services: Any, result: dict[str, Any], tasks: list[Any], root: str,
    *, revision_before: str, truncated: bool,
) -> None:
    """Associate exact checkpoint paths, without inferring ownership or commit proof."""
    if result.get("success") is not True:
        return
    groups = result.get("clusters", [])
    revision_after = current_task_revision(services, root) if tasks else ""
    revision = revision_after if revision_after and revision_after == revision_before else ""
    linked: dict[str, dict[str, Any]] = {}
    paths_by_task = [(task, _affected_paths(task, root)) for task in tasks]
    for group in groups:
        files = set(group.get("files", []))
        matches = []
        for task, paths in paths_by_task:
            overlap = files & paths
            if not overlap:
                continue
            if task.task_id not in linked:
                linked[task.task_id] = task_verification_candidates(services, task, revision)
            matches.append({
                "task_id": task.task_id,
                "goal": str(task.contract.goal).replace("\r", " ").replace("\n", " ")[:160],
                "matching_path_count": len(overlap),
                "association": "checkpoint_path_overlap",
                "verification": linked[task.task_id],
            })
        group["task_candidates"] = matches[:4]
        group["task_candidates_omitted"] = max(0, len(matches) - 4)
    # Avoid returning a current verification claim if the task revision changed
    # while reading receipts. Existing Agent OS completion remains authoritative.
    if linked and revision and current_task_revision(services, root) != revision:
        for group in groups:
            for match in group.get("task_candidates", []):
                match["verification"] = {
                    "task_id": match["task_id"], "verification_scope": "whole_worktree_task_only",
                    "status": "revision_changed", "commit_verified": False, "current_receipt_count": 0,
                }
        revision = ""
    result["task_context"] = {
        "tasks_considered": len(tasks),
        "tasks_truncated": truncated,
        "linked_task_count": len(linked),
        "current_revision_observed": bool(revision),
        "scope": "checkpoint_path_overlap_only",
        "commit_receipt_reuse_authorized": False,
    }


def attach_index_impact(services: Any, result: dict[str, Any], root: str) -> None:
    """Offer bounded indexed consumer/test hints, not fresh dependency proof."""
    if result.get("success") is not True:
        return
    output: dict[str, Any] = {
        "status": "unavailable", "freshness": "not_checked", "dependencies_verified": False,
        "verification_reuse_authorized": False,
    }
    result["indexed_impact"] = output
    index = getattr(services, "code_index", None)
    if index is None:
        return
    paths = sorted({path for group in result.get("clusters", []) for path in group.get("files", [])})
    if not paths:
        output["status"] = "no_changes"
        return
    if len(paths) > 64:
        output.update(status="path_budget_exceeded", omitted_changed_paths=len(paths) - 64)
        return
    try:
        impact = index.impact(root, paths, max_symbols=48, max_dependents=24)
    except (OSError, ValueError, RuntimeError):
        return
    if not isinstance(impact, dict) or impact.get("success") is not True or impact.get("root") != root:
        return

    def candidates(key: str) -> list[str]:
        rows = impact.get(key, [])
        if not isinstance(rows, list):
            return []
        found = set()
        for row in rows[:24]:
            path = row.get("path") if isinstance(row, dict) else None
            if (isinstance(path, str) and 0 < len(path) <= 512 and "\0" not in path
                    and "\\" not in path and ":" not in path and not path.startswith("/")
                    and all(part not in {"", ".", ".."} for part in path.split("/"))
                    and all(ord(c) >= 32 for c in path)):
                found.add(path)
        return sorted(found)

    dependents = [p for p in candidates("likely_dependents") if p not in paths]
    tests = candidates("suggested_tests")
    indexed = impact.get("indexed_changed_files")
    output.update(
        status="advisory_index_candidates",
        changed_path_count=len(paths),
        indexed_changed_path_count=indexed if type(indexed) is int and 0 <= indexed <= len(paths) else None,
        dependent_paths=dependents[:8], dependent_paths_omitted=max(0, len(dependents) - 8),
        test_paths=tests[:8], test_paths_omitted=max(0, len(tests) - 8),
        index_scan_truncated=impact.get("truncated") is not False,
        complete=False,
    )
