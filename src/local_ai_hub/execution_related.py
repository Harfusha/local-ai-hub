"""Explicit, bounded reuse of published problem leads in the same checkout."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .agent_task_models import _task_scope_root
from .execution_problems import PROBLEM_STATE_KEY, _validated_records

MAX_RELATED_TASKS = 32
MAX_RELATED_PROBLEMS = 8


def related_problem_leads(task_store: Any, task: Any, request: Any) -> list[dict[str, Any]]:
    """Return historical observations, never evidence or a completion decision.

    Task-only context, unrelated checkout identities and nonpublished reports
    are excluded. Only exact overlapping obligation names are considered.
    """
    if request.scoped_task_only or not request.root or not task.context.repository_id:
        return []
    fields = ("repository_id", "clone_id", "worktree_id", "branch")
    identity = tuple(getattr(task.context, field) for field in fields)
    if any(getattr(request, field) != value for field, value in zip(fields, identity)):
        return []
    root = _task_scope_root(task)
    try:
        if not root or not Path(root).samefile(request.root):
            return []
    except (OSError, ValueError):
        return []
    current = set(task.contract.acceptance_criteria)
    page = task_store.list_tasks(limit=MAX_RELATED_TASKS, include_stale=True, repo_root=root)
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for candidate in page.tasks[:MAX_RELATED_TASKS]:
        if candidate.task_id == task.task_id:
            continue
        if tuple(getattr(candidate.context, field) for field in fields) != identity:
            continue
        try:
            if not Path(_task_scope_root(candidate)).samefile(root):
                continue
            records = _validated_records(candidate.checkpoint.state_data.get(PROBLEM_STATE_KEY, {}))
        except (OSError, RuntimeError, ValueError):
            continue
        for record in records.values():
            report = record["report"]
            criterion = report["criterion"]
            if report.get("share_repository") is not True or criterion not in current:
                continue
            key = (criterion, report["title"])
            if key in seen:
                continue
            seen.add(key)
            result.append({
                "source_task_id": candidate.task_id, "problem_id": report["id"],
                "title": report["title"], "criterion": criterion,
                "reported_at": record["reported_at"], "status": "historical_unverified",
            })
            if len(result) >= MAX_RELATED_PROBLEMS:
                return result
    return result
