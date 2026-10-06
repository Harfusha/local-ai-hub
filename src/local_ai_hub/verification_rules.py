"""Project-config adapter for task completion verification."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .agent_tasks import CompletionGateError
from .agent_verification import CompletionResult
from .project_config import ProjectConfigError, resolve_project_context


def evaluate_project_completion(
    verification_store: Any,
    task_id: str,
    *,
    root: str | Path,
    state_dir: str | Path,
    current_revision: str = "",
    now: float | None = None,
) -> CompletionResult:
    """Evaluate persisted receipts using this project's configured rules."""
    try:
        project = resolve_project_context(root, state_dir)
    except (ProjectConfigError, OSError, RuntimeError, ValueError):
        return CompletionResult(
            task_id=str(task_id),
            complete=False,
            satisfied_criteria=(),
            unsatisfied_criteria=("project_configuration",),
            stale_criteria=(),
            receipts=(),
        )
    if project.resolution.error_codes:
        return CompletionResult(
            task_id=str(task_id),
            complete=False,
            satisfied_criteria=(),
            unsatisfied_criteria=("project_configuration",),
            stale_criteria=(),
            receipts=(),
        )

    settings = project.settings
    return verification_store.completion(
        str(task_id),
        now=now,
        current_revision=str(current_revision or ""),
        verification_rules=settings.verification_rules,
        configured_criteria=tuple(settings.commands),
    )


def complete_task_with_project_rules(
    task_store: Any,
    verification_store: Any,
    task_id: str,
    *,
    root: str | Path,
    state_dir: str | Path,
    current_revision: str = "",
    reason: str = "completed by agent",
    actor: str = "agent",
    idempotency_key: str = "",
    now: float | None = None,
) -> Any:
    """Gate task mutation on the T09 evaluator, then complete via TaskStore."""
    result = evaluate_project_completion(
        verification_store,
        task_id,
        root=root,
        state_dir=state_dir,
        current_revision=current_revision,
        now=now,
    )
    if not result.complete:
        missing = ", ".join(result.unsatisfied_criteria + result.stale_criteria)
        raise CompletionGateError(
            f"Cannot complete task {task_id}: verification incomplete"
            + (f" ({missing})" if missing else "")
        )
    return task_store.complete(
        task_id,
        reason=reason,
        actor=actor,
        idempotency_key=idempotency_key,
    )
