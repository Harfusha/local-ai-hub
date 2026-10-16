from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Protocol

from .agent_tasks import CompletionGateError, TaskCheckpoint, TaskState, TaskStore
from .agent_verification import CompletionResult
from .project_config import ProjectSettings


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
        configured_commands: Mapping[str, object] | None = None,
        project_config_digest: str = "",
        configured_environment_sha256: Mapping[str, str] | None = None,
        project_root: str | Path = "",
    ) -> CompletionResult: ...


def project_command_environment_sha256(settings: object, criterion: str) -> str:
    """Hash the effective project command environment without persisting values."""
    if settings is None:
        raise CompletionGateError("project settings is required")
    if not isinstance(criterion, str) or not criterion.strip() or "\x00" in criterion:
        raise CompletionGateError("project command criterion is invalid")
    commands = getattr(settings, "commands", {})
    command = commands.get(criterion) if isinstance(commands, Mapping) else None
    environment = dict(getattr(settings, "env", {}) or {})
    command_env = command.get("env", {}) if isinstance(command, Mapping) else getattr(command, "env", {})
    if isinstance(command_env, Mapping):
        environment.update(command_env)
    references = dict(getattr(settings, "env_references", {}) or {})
    command_references = (
        command.get("env_references", {})
        if isinstance(command, Mapping)
        else getattr(command, "env_references", {})
    )
    if isinstance(command_references, Mapping):
        references.update(command_references)
    for target_name, source_name in references.items():
        if not isinstance(target_name, str) or not isinstance(source_name, str):
            raise CompletionGateError("project command environment is invalid")
        if source_name not in os.environ:
            raise CompletionGateError("project command environment is unavailable")
        value = os.environ[source_name]
        if not isinstance(value, str) or "\x00" in value:
            raise CompletionGateError("project command environment is invalid")
        environment[target_name] = value
    return hashlib.sha256(
        json.dumps(environment, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def evaluate_project_completion(
    verification_store: CompletionReceiptStore,
    settings_or_task_id: ProjectSettings | str,
    *,
    task_id: str = "",
    root: str | Path = "",
    state_dir: str | Path = "",
    repository_revision: str = "",
    current_revision: str = "",
    project_config_digest: str = "",
    configured_environment_sha256: Mapping[str, str] | None = None,
    project_root: str | Path = "",
    now: float | None = None,
) -> CompletionResult:
    """Delegate project-aware completion to T09's persisted receipt gate."""
    if isinstance(settings_or_task_id, str):
        task_key = str(settings_or_task_id).strip()
        rev = str(current_revision or repository_revision or "").strip()
        task_store = getattr(verification_store, "task_store", None)
        task_getter = getattr(task_store, "get", None)
        if not task_key or not callable(task_getter):
            return CompletionResult(task_key, False, (), ("trusted_task_context",), (), ())
        task = task_getter(task_key)
        if (
            task is None
            or str(getattr(task, "task_id", "")).strip() != task_key
            or not str(getattr(task, "owner", "") or "").strip()
        ):
            return CompletionResult(task_key, False, (), ("trusted_task_context",), (), ())
        trusted_root = _task_project_root(task, _task_created_state_data(task_store, task_key))
        if trusted_root is None:
            return CompletionResult(task_key, False, (), ("trusted_project_root",), (), ())
        requested_root = str(root or "").strip()
        if requested_root and _canonical_project_root(requested_root) != _canonical_project_root(trusted_root):
            return CompletionResult(task_key, False, (), ("trusted_project_root",), (), ())
        try:
            from .project_config import ProjectConfigError, resolve_project_context

            project = resolve_project_context(trusted_root, state_dir)
        except (ProjectConfigError, OSError, RuntimeError, ValueError):
            return CompletionResult(
                task_id=task_key,
                complete=False,
                satisfied_criteria=(),
                unsatisfied_criteria=("project_configuration",),
                stale_criteria=(),
                receipts=(),
            )
        if project.resolution.error_codes:
            return CompletionResult(
                task_id=task_key,
                complete=False,
                satisfied_criteria=(),
                unsatisfied_criteria=("project_configuration",),
                stale_criteria=(),
                receipts=(),
            )
        settings = project.settings
        return evaluate_project_completion(
            verification_store,
            settings,
            task_id=task_key,
            now=now,
            repository_revision=rev,
            project_config_digest=project.config_digest,
            configured_environment_sha256={
                name: project_command_environment_sha256(settings, name)
                for name in settings.commands
            },
            project_root=trusted_root,
        )

    settings = settings_or_task_id
    task_key = str(task_id or "").strip()
    revision = str(repository_revision or current_revision or "").strip()
    if not task_key:
        raise ValueError("task_id is required")
    if not revision:
        raise ValueError("repository_revision is required")

    task_store = getattr(verification_store, "task_store", None)
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
        configured_commands=settings.commands,
        project_config_digest=project_config_digest,
        configured_environment_sha256=configured_environment_sha256,
        project_root=project_root,
    )


def _task_created_state_data(task_store: TaskStore, task_id: str) -> Mapping[str, object] | None:
    state_store = getattr(task_store, "state_store", None)
    events = getattr(state_store, "events", None)
    if not callable(events):
        return None
    try:
        created_events = events(stream_id=f"task:{task_id}", after_seq=0, limit=1)
    except (OSError, RuntimeError, TimeoutError, TypeError, ValueError):
        return None
    if not created_events or getattr(created_events[0], "kind", "") != "task.created":
        return None
    payload = getattr(created_events[0], "payload", None)
    if not isinstance(payload, Mapping) or payload.get("task_id") != task_id:
        return None
    checkpoint = payload.get("checkpoint")
    if not isinstance(checkpoint, Mapping):
        return None
    state_data = checkpoint.get("state_data")
    return state_data if isinstance(state_data, Mapping) else None


def _task_owned_worktree_root(
    task: TaskState,
    worktree: Mapping[str, object],
    trusted_repo_root: Path | None,
) -> Path | None:
    raw_path = worktree.get("worktree_path")
    raw_repo = worktree.get("repo_root")
    worktree_id = str(worktree.get("worktree_id", "") or "").strip()
    branch = str(worktree.get("branch", "") or "").strip()
    owner = str(task.owner or "").strip()
    if (
        not isinstance(raw_path, (str, Path))
        or not str(raw_path).strip()
        or not isinstance(raw_repo, (str, Path))
        or not str(raw_repo).strip()
        or not worktree_id
        or not branch
        or not owner
        or str(worktree.get("task_id", "")) != task.task_id
        or str(worktree.get("owner", "")).strip() != owner
    ):
        return None

    worktree_path = Path(raw_path).expanduser().resolve(strict=False)
    repo_root = Path(raw_repo).expanduser().resolve(strict=False)
    if trusted_repo_root is not None and _canonical_project_root(repo_root) != _canonical_project_root(
        trusted_repo_root
    ):
        return None
    try:
        from .process_utils import _worktree_ownership_path

        metadata_path = _worktree_ownership_path(worktree_path)
        if metadata_path is None or not metadata_path.is_file():
            return None
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, RuntimeError, TypeError, ValueError, ImportError):
        return None
    if not isinstance(metadata, Mapping):
        return None
    try:
        metadata_root = Path(str(metadata.get("repo_root", ""))).expanduser().resolve(
            strict=False
        )
        metadata_path_value = Path(
            str(metadata.get("worktree_path", ""))
        ).expanduser().resolve(strict=False)
    except (OSError, TypeError, ValueError):
        return None
    if (
        metadata.get("schema_version") != 1
        or str(metadata.get("task_id", "")) != task.task_id
        or str(metadata.get("owner", "")).strip() != owner
        or str(metadata.get("worktree_id", "")).strip() != worktree_id
        or str(metadata.get("branch", "")).strip() != branch
        or _canonical_project_root(metadata_root) != _canonical_project_root(repo_root)
        or _canonical_project_root(metadata_path_value)
        != _canonical_project_root(worktree_path)
        or not worktree_path.is_dir()
        or not repo_root.is_dir()
    ):
        return None
    return worktree_path


def _task_project_root(
    task: Any,
    trusted_initial_state_data: Mapping[str, object] | None = None,
) -> Path | None:
    context_root: Path | None = None
    context = getattr(task, "context", None)
    context_value = getattr(context, "repository_id", None) if context else None
    if isinstance(context_value, (str, Path)) and str(context_value).strip():
        candidate = Path(context_value).expanduser().resolve(strict=False)
        if candidate.is_dir():
            context_root = candidate

    initial_data = trusted_initial_state_data
    if initial_data is not None:
        initial_worktree = initial_data.get("worktree")
        initial_root = initial_data.get("repo_root")
        trusted_worktree = initial_worktree if isinstance(initial_worktree, Mapping) else None
    else:
        checkpoint = getattr(task, "checkpoint", None)
        current_data = getattr(checkpoint, "state_data", {}) if checkpoint else {}
        current_worktree = current_data.get("worktree") if isinstance(current_data, Mapping) else None
        trusted_worktree = current_worktree if isinstance(current_worktree, Mapping) else None
        initial_root = None

    trusted_repo_root: Path | None = None
    if isinstance(initial_root, (str, Path)) and str(initial_root).strip():
        candidate = Path(initial_root).expanduser().resolve(strict=False)
        if candidate.is_dir():
            trusted_repo_root = candidate
    if trusted_repo_root is None:
        trusted_repo_root = context_root

    if trusted_worktree is not None:
        owned_root = _task_owned_worktree_root(task, trusted_worktree, trusted_repo_root)
        if owned_root is not None:
            return owned_root
    return trusted_repo_root


def _canonical_project_root(root: str | Path | None) -> str:
    if root is None or root == "":
        return ""
    if not isinstance(root, (str, Path)) or "\x00" in str(root):
        raise CompletionGateError("project root must be a path without null bytes")
    if not str(root).strip():
        return ""
    return os.path.normcase(str(Path(root).expanduser().resolve(strict=False)))


def _completion_mutation_generation(task: object) -> int:
    checkpoint = getattr(task, "checkpoint", None)
    state_data = getattr(checkpoint, "state_data", None)
    if not isinstance(state_data, Mapping):
        raise CompletionGateError("trusted task checkpoint is unavailable")
    generation = state_data.get("mutation_generation", 0)
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
        raise CompletionGateError("trusted task mutation_generation is invalid")
    return generation


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
    response_budget_tokens: int | None = None,
) -> TaskState:
    """Resolve payload-root project rules and gate mutation on persisted receipts."""
    task_key = str(task_id or "").strip()
    if not task_key:
        raise CompletionGateError("task_id is required")
    revision = str(current_revision or "").strip()
    if not revision:
        raise CompletionGateError("trusted repository_revision is unavailable")
    receipt_task_store = getattr(verification_store, "task_store", None)
    if receipt_task_store is not task_store:
        raise CompletionGateError("verification task store is unavailable or mismatched")
    task_getter = getattr(task_store, "get", None)
    if not callable(task_getter):
        raise CompletionGateError("trusted task store is unavailable")
    before = task_getter(task_key)
    if before is None or str(getattr(before, "task_id", "")).strip() != task_key:
        raise CompletionGateError("trusted task is unavailable")
    before_owner = str(getattr(before, "owner", "") or "").strip()
    if not before_owner:
        raise CompletionGateError("task owner is unavailable")
    initial_state_data = _task_created_state_data(task_store, task_key)
    task_root = _task_project_root(before, initial_state_data)
    if task_root is None:
        raise CompletionGateError("trusted task project root is unavailable")
    memory_audit_validator = getattr(task_store, "_validate_memory_audit", None)
    if callable(memory_audit_validator):
        memory_audit_validator(before)
    try:
        from .project_config import ProjectConfigError, resolve_project_context
    except ImportError as exc:
        raise CompletionGateError("project configuration is unavailable") from exc
    try:
        project = resolve_project_context(task_root, state_dir)
        requested_root = str(root or "").strip()
        if requested_root:
            requested_project = resolve_project_context(requested_root, state_dir)
            if _canonical_project_root(requested_project.root) != _canonical_project_root(
                project.root
            ):
                raise CompletionGateError("requested project root does not match task project root")
    except CompletionGateError:
        raise
    except (ProjectConfigError, OSError, RuntimeError, ValueError) as exc:
        raise CompletionGateError("project configuration could not be resolved") from exc
    if project.resolution.error_codes:
        raise CompletionGateError("project configuration is invalid")
    contract = getattr(before, "contract", None) if before is not None else None
    if contract is not None and not getattr(contract, "acceptance_criteria", ()):
        checkpoint = getattr(before, "checkpoint", None)
        state_data = dict(getattr(checkpoint, "state_data", {}))
        state_data["repo_root"] = str(project.root)
        state_data["repository_revision"] = revision
        checkpoint_obj = TaskCheckpoint(
            phase=getattr(checkpoint, "phase", ""),
            next_action=getattr(checkpoint, "next_action", ""),
            affected_paths=getattr(checkpoint, "affected_paths", ()),
            evidence_ids=getattr(checkpoint, "evidence_ids", ()),
            blockers=getattr(checkpoint, "blockers", ()),
            state_data=state_data,
        )
        prepared_completion_updated_at = task_store.preflight_completion_response_budget(
            task_key, response_budget_tokens, actor=actor,
            checkpoint=checkpoint_obj if state_data != dict(getattr(checkpoint, "state_data", {})) else None,
        )
        return task_store.complete(
            task_key,
            reason=reason,
            actor=actor,
            idempotency_key=idempotency_key,
            response_budget_tokens=response_budget_tokens,
            checkpoint=checkpoint_obj if state_data != dict(getattr(checkpoint, "state_data", {})) else None,
            _prepared_completion_updated_at=prepared_completion_updated_at,
            _expected_completion_content=task_store._completion_content_snapshot(before),
        )
    before_generation = _completion_mutation_generation(before)
    preflight_current = task_store.get(task_key)
    if (
        preflight_current is None
        or preflight_current != before
        or str(getattr(preflight_current, "owner", "") or "").strip() != before_owner
        or _completion_mutation_generation(preflight_current) != before_generation
    ):
        raise CompletionGateError("task owner or mutation generation changed before completion preflight")
    preflight_checkpoint = getattr(preflight_current, "checkpoint", None)
    preflight_state_data = dict(getattr(preflight_checkpoint, "state_data", {}))
    preflight_state_data["repo_root"] = str(project.root)
    preflight_state_data["repository_revision"] = revision
    preflight_checkpoint_candidate = TaskCheckpoint(
        phase=getattr(preflight_checkpoint, "phase", ""),
        next_action=getattr(preflight_checkpoint, "next_action", ""),
        affected_paths=getattr(preflight_checkpoint, "affected_paths", ()),
        evidence_ids=getattr(preflight_checkpoint, "evidence_ids", ()),
        blockers=getattr(preflight_checkpoint, "blockers", ()),
        state_data=preflight_state_data,
    )
    preflight_fn = getattr(task_store, "preflight_completion_response_budget", None)
    prepared_completion_updated_at = (
        preflight_fn(
            task_key, response_budget_tokens, actor=actor,
            checkpoint=(preflight_checkpoint_candidate
                        if preflight_state_data != dict(getattr(preflight_checkpoint, "state_data", {}))
                        else None),
        )
        if callable(preflight_fn)
        else None
    )
    result = evaluate_project_completion(
        verification_store,
        project.settings,
        task_id=task_key,
        repository_revision=revision,
        project_config_digest=project.config_digest,
        configured_environment_sha256={
            name: project_command_environment_sha256(project.settings, name)
            for name in project.settings.commands
        },
        project_root=project.root,
        now=now,
    )
    if not result.complete:
        missing = ", ".join(result.unsatisfied_criteria + result.stale_criteria)
        raise CompletionGateError(
            f"Cannot complete task {task_key}: verification incomplete"
            + (f" ({missing})" if missing else "")
        )
    if before is not None and hasattr(before, "checkpoint"):
        current = task_store.get(task_key)
        current_chk = getattr(current, "checkpoint", None)
        if current is None or current != preflight_current:
            raise CompletionGateError("task owner or mutation generation changed during completion verification")
        current_state_data = dict(getattr(current_chk, "state_data", {}))
        current_state_data["repo_root"] = str(project.root)
        current_state_data["repository_revision"] = revision
        if current_state_data != dict(getattr(current_chk, "state_data", {})):
            checkpoint_obj = TaskCheckpoint(
                phase=getattr(current_chk, "phase", ""),
                next_action=getattr(current_chk, "next_action", ""),
                affected_paths=getattr(current_chk, "affected_paths", ()),
                evidence_ids=getattr(current_chk, "evidence_ids", ()),
                blockers=getattr(current_chk, "blockers", ()),
                state_data=current_state_data,
            )
        else:
            checkpoint_obj = None
    snapshot_fn = getattr(task_store, "_completion_content_snapshot", None)
    expected_completion_content = None
    if callable(snapshot_fn):
        try:
            expected_completion_content = snapshot_fn(preflight_current)
        except (AttributeError, TypeError):
            expected_completion_content = None
    return task_store.complete(
        task_key,
        reason=reason,
        actor=actor,
        idempotency_key=idempotency_key,
        response_budget_tokens=response_budget_tokens,
        checkpoint=checkpoint_obj,
        _prepared_completion_updated_at=prepared_completion_updated_at,
        _expected_completion_content=expected_completion_content,
    )

