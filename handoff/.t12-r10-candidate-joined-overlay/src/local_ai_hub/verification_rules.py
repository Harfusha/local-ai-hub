from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from .agent_tasks import CompletionGateError, TaskCheckpoint, TaskState, TaskStore
from .agent_verification import CompletionResult
from .project_config import ProjectConfigError, ProjectSettings, resolve_project_context


class CompletionReceiptStore(Protocol):
    task_store: TaskStore | None

    def completion(
        self,
        task_id: str,
        now: float | None = None,
        *,
        current_revision: str = "",
        current_mutation_generation: int | None = None,
        verification_rules: Mapping[str, bool | tuple[str, ...]] | None = None,
        configured_criteria: tuple[str, ...] | None = None,
    ) -> CompletionResult: ...


def evaluate_project_completion(
    verification_store: CompletionReceiptStore,
    settings: ProjectSettings,
    *,
    task_id: str,
    repository_revision: str,
    now: float | None = None,
) -> CompletionResult:
    """Delegate project-aware completion to T09's persisted receipt gate."""
    task_key = str(task_id or "").strip()
    revision = str(repository_revision or "").strip()
    if not task_key:
        raise ValueError("task_id is required")
    if not revision:
        raise ValueError("repository_revision is required")

    task_store = verification_store.task_store
    if task_store is None:
        raise ValueError("task store is required for project completion")
    task = task_store.get(task_key)
    if task is None or task.task_id != task_key:
        raise ValueError("task not found")
    if not str(task.owner or "").strip():
        raise ValueError("task owner is required")
    generation = task.checkpoint.state_data.get("mutation_generation", 0)
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
        raise ValueError("task mutation_generation is invalid")

    return verification_store.completion(
        task_key,
        now=now,
        current_revision=revision,
        current_mutation_generation=generation,
        verification_rules=settings.verification_rules,
        configured_criteria=tuple(settings.commands),
    )


def complete_task_with_project_rules(
    task_store: TaskStore,
    verification_store: CompletionReceiptStore,
    task_id: str,
    *,
    root: str | Path,
    state_dir: str | Path,
    current_revision: str,
    reason: str = "completed by agent",
    actor: str = "agent",
    idempotency_key: str = "",
    now: float | None = None,
) -> TaskState:
    """Resolve payload-root project rules and gate mutation on persisted receipts."""
    task_key = str(task_id or "").strip()
    if not task_key:
        raise CompletionGateError("task_id is required")
    revision = str(current_revision or "").strip()
    if not revision:
        raise CompletionGateError("trusted repository_revision is unavailable")
    try:
        project = resolve_project_context(root, state_dir)
    except (ProjectConfigError, OSError, RuntimeError, ValueError) as exc:
        raise CompletionGateError("project configuration could not be resolved") from exc
    if project.resolution.error_codes:
        raise CompletionGateError("project configuration is invalid")
    receipt_task_store = getattr(verification_store, "task_store", None)
    if receipt_task_store is None or receipt_task_store is not task_store:
        raise CompletionGateError("verification task store is unavailable or mismatched")
    before = task_store.get(task_key)
    if before is None or not str(before.owner or "").strip():
        raise CompletionGateError("task owner is unavailable")
    before_generation = before.checkpoint.state_data.get("mutation_generation", 0)
    result = evaluate_project_completion(
        verification_store,
        project.settings,
        task_id=task_key,
        repository_revision=revision,
        now=now,
    )
    if not result.complete:
        missing = ", ".join(result.unsatisfied_criteria + result.stale_criteria)
        raise CompletionGateError(
            f"Cannot complete task {task_key}: verification incomplete"
            + (f" ({missing})" if missing else "")
        )
    current = task_store.get(task_key)
    if (
        current is None
        or current.owner != before.owner
        or current.checkpoint.state_data.get("mutation_generation", 0) != before_generation
    ):
        raise CompletionGateError("task owner or mutation generation changed during completion verification")
    state_data = dict(current.checkpoint.state_data)
    state_data["repo_root"] = str(project.root)
    state_data["repository_revision"] = revision
    if state_data != dict(current.checkpoint.state_data):
        checkpoint = TaskCheckpoint(
            phase=current.checkpoint.phase,
            next_action=current.checkpoint.next_action,
            affected_paths=current.checkpoint.affected_paths,
            evidence_ids=current.checkpoint.evidence_ids,
            blockers=current.checkpoint.blockers,
            state_data=state_data,
        )
        suffix = "_project_completion_context"
        task_store.checkpoint(
            task_key,
            checkpoint,
            actor=actor,
            idempotency_key=f"{idempotency_key}{suffix}" if idempotency_key else "",
        )
    return task_store.complete(
        task_key,
        reason=reason,
        actor=actor,
        idempotency_key=idempotency_key,
    )
