from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
import math
from pathlib import Path
import time
from typing import Any

from .agent_identity import AgentScope, ScopeContext

MAX_TASK_QUERY_SCAN_ROWS = 10_000
MAX_TASK_REAP_BATCH = 64
MAX_AGENT_QUESTION_BYTES = 16_384
_AGENT_TASK_WRITE_TIMEOUT_SECONDS = 5.0
MAX_TRAINING_DATASET_BYTES = 16 * 1024 * 1024


class CompletionGateError(RuntimeError):
    """Raised when task completion is attempted without verified criteria receipts."""


class CheckpointResponseBudgetError(CompletionGateError):
    """Raised before persistence when a task mutation's full memory receipt cannot fit."""

    def __init__(self, requested_tokens: int, required_tokens: int) -> None:
        self.requested_tokens = requested_tokens
        self.required_tokens = required_tokens
        super().__init__("checkpoint_response_budget_too_small")


class TaskWorktreeError(CompletionGateError):
    """A requested automatic worktree could not be prepared or created."""

    def __init__(
        self,
        message: str,
        *,
        mutation_applied: bool | None,
        operation_not_started: bool,
        outcome_unknown: bool = False,
        cleanup_succeeded: bool | None = None,
    ) -> None:
        self.mutation_applied = mutation_applied
        self.operation_not_started = operation_not_started
        self.outcome_unknown = outcome_unknown
        self.cleanup_succeeded = cleanup_succeeded
        super().__init__(message)


class TaskIdempotencyConflictError(CompletionGateError):
    """Raised when a task-create idempotency key is reused with different data."""


class InvalidTransitionError(ValueError):
    """Raised when an illegal task state transition is attempted."""


class ConcurrentTaskUpdateError(RuntimeError):
    """Raised when a task projection changed after a transition read it."""


class TaskStatus(str, Enum):
    DRAFT = "draft"
    PLANNED = "planned"
    ACTIVE = "active"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    WAITING = "waiting"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ABANDONED = "abandoned"


VALID_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.DRAFT: {TaskStatus.PLANNED, TaskStatus.CANCELLED},
    TaskStatus.PLANNED: {TaskStatus.ACTIVE, TaskStatus.CANCELLED, TaskStatus.FAILED},
    TaskStatus.ACTIVE: {
        TaskStatus.VERIFYING,
        TaskStatus.WAITING,
        TaskStatus.BLOCKED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
        TaskStatus.ABANDONED,
    },
    TaskStatus.VERIFYING: {
        TaskStatus.COMPLETED,
        TaskStatus.ACTIVE,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
        TaskStatus.ABANDONED,
    },
    TaskStatus.WAITING: {TaskStatus.ACTIVE, TaskStatus.CANCELLED, TaskStatus.ABANDONED, TaskStatus.FAILED},
    TaskStatus.BLOCKED: {TaskStatus.ACTIVE, TaskStatus.CANCELLED, TaskStatus.ABANDONED, TaskStatus.FAILED},
    TaskStatus.ABANDONED: {TaskStatus.ACTIVE, TaskStatus.CANCELLED, TaskStatus.FAILED},
    TaskStatus.FAILED: {TaskStatus.ACTIVE, TaskStatus.CANCELLED},
    TaskStatus.COMPLETED: set(),
    TaskStatus.CANCELLED: set(),
}


@dataclass(frozen=True)
class GoalContract:
    goal: str
    acceptance_criteria: tuple[str, ...] = ()
    scope: AgentScope = AgentScope.TASK
    non_goals: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    risk_profile: str = "normal"
    slo_profile: dict[str, Any] = field(default_factory=dict)
    description: str = ""

    def __post_init__(self) -> None:
        if type(self.goal) is not str:
            raise ValueError("task contract requires goal to be a string")
        if "\x00" in self.goal:
            raise ValueError("goal must be a string without null bytes")
        goal = self.goal.strip()
        if not goal:
            raise ValueError("task contract requires goal")
        object.__setattr__(self, "goal", goal)
        if type(self.description) is not str or "\x00" in self.description:
            raise ValueError("description must be a string without null bytes")
        object.__setattr__(self, "description", self.description.strip())
        if type(self.risk_profile) is not str or "\x00" in self.risk_profile:
            raise ValueError("risk_profile must be a string without null bytes")
        risk_profile = self.risk_profile.strip()
        object.__setattr__(self, "risk_profile", risk_profile or "normal")

        def _clean_tuple(items: Any, field_name: str) -> tuple[str, ...]:
            if type(items) not in (tuple, list):
                raise ValueError(f"{field_name} must be an array of strings")
            cleaned: list[str] = []
            for item in items:
                if type(item) is not str or "\x00" in item:
                    raise ValueError(f"{field_name} entries must be strings without null bytes")
                value = item.strip()
                if value:
                    cleaned.append(value)
            return tuple(cleaned)

        if not isinstance(self.scope, AgentScope):
            if type(self.scope) is not str:
                raise ValueError("scope must be a canonical string or AgentScope")
            try:
                object.__setattr__(self, "scope", AgentScope(self.scope))
            except ValueError as exc:
                raise ValueError("scope must use a canonical AgentScope value") from exc
        object.__setattr__(self, "acceptance_criteria", _clean_tuple(self.acceptance_criteria, "acceptance_criteria"))
        object.__setattr__(self, "non_goals", _clean_tuple(self.non_goals, "non_goals"))
        object.__setattr__(self, "constraints", _clean_tuple(self.constraints, "constraints"))
        if type(self.slo_profile) is not dict:
            raise ValueError("slo_profile must be a mapping")

    def has_criteria(self) -> bool:
        return bool(self.acceptance_criteria)

    def criteria_count(self) -> int:
        return len(self.acceptance_criteria)

    def is_high_risk(self) -> bool:
        return self.risk_profile in ("high", "critical")

    def has_non_goals(self) -> bool:
        return bool(self.non_goals)

    def has_constraints(self) -> bool:
        return bool(self.constraints)

    def to_dict(self) -> dict[str, Any]:
        scope_val = self.scope.value if isinstance(self.scope, AgentScope) else (getattr(self.scope, "value", None) or str(self.scope))
        return {
            "goal": self.goal,
            "description": self.description,
            "acceptance_criteria": list(self.acceptance_criteria),
            "scope": scope_val,
            "non_goals": list(self.non_goals),
            "constraints": list(self.constraints),
            "risk_profile": self.risk_profile,
            "slo_profile": dict(self.slo_profile),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> GoalContract:
        if not isinstance(data, Mapping):
            raise ValueError("goal contract data must be a mapping")
        criteria = data.get("acceptance_criteria", ())
        non_goals = data.get("non_goals", ())
        constraints = data.get("constraints", ())
        if any(type(items) not in (tuple, list) for items in (criteria, non_goals, constraints)):
            raise ValueError("goal contract collections must be arrays")
        slo_profile = data.get("slo_profile", {})
        if type(slo_profile) is not dict:
            raise ValueError("slo_profile must be a mapping")
        return cls(
            goal=data.get("goal", ""),
            description=data.get("description", ""),
            acceptance_criteria=tuple(criteria),
            scope=data.get("scope", AgentScope.TASK),
            non_goals=tuple(non_goals),
            constraints=tuple(constraints),
            risk_profile=data.get("risk_profile", "normal"),
            slo_profile=slo_profile,
        )


@dataclass(frozen=True)
class TaskCheckpoint:
    phase: str = ""
    next_action: str = ""
    affected_paths: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    state_data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        def _clean_str(val: Any) -> str:
            return str(val or "").replace("\x00", "").strip()

        def _clean_tuple(items: Any) -> tuple[str, ...]:
            if not items:
                return ()
            cleaned: list[str] = []
            for item in items:
                s = _clean_str(item)
                if s:
                    cleaned.append(s)
            return tuple(cleaned)

        object.__setattr__(self, "phase", _clean_str(self.phase))
        object.__setattr__(self, "next_action", _clean_str(self.next_action))
        object.__setattr__(self, "affected_paths", _clean_tuple(self.affected_paths))
        object.__setattr__(self, "evidence_ids", _clean_tuple(self.evidence_ids))
        object.__setattr__(self, "blockers", _clean_tuple(self.blockers))
        object.__setattr__(self, "state_data", dict(self.state_data) if isinstance(self.state_data, Mapping) else {})

    def has_blockers(self) -> bool:
        return bool(self.blockers)

    def has_evidence(self) -> bool:
        return bool(self.evidence_ids)

    def has_affected_paths(self) -> bool:
        return bool(self.affected_paths)

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "next_action": self.next_action,
            "affected_paths": list(self.affected_paths),
            "evidence_ids": list(self.evidence_ids),
            "blockers": list(self.blockers),
            "state_data": dict(self.state_data),
        }

    @classmethod
    def from_dict(cls, data: Any) -> TaskCheckpoint:
        if not isinstance(data, Mapping):
            return cls()
        state_data = dict(data["state_data"]) if isinstance(data.get("state_data"), Mapping) else {}
        return cls(
            phase=str(data.get("phase") or ""),
            next_action=str(data.get("next_action") or ""),
            affected_paths=tuple(data.get("affected_paths") or ()),
            evidence_ids=tuple(data.get("evidence_ids") or ()),
            blockers=tuple(data.get("blockers") or ()),
            state_data=state_data,
        )


@dataclass(frozen=True)
class TaskState:
    task_id: str
    status: TaskStatus
    contract: GoalContract
    context: ScopeContext
    owner: str = ""
    lease_id: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    heartbeat_expires_at: float = 0.0
    checkpoint: TaskCheckpoint = field(default_factory=TaskCheckpoint)
    verification_receipts: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("task_id", "owner", "lease_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or "\x00" in value or value != value.strip():
                raise ValueError(f"{name} must be a canonical string")
        if not self.task_id:
            raise ValueError("task_id must not be empty")
        if not isinstance(self.status, (str, TaskStatus)):
            raise ValueError("status must be a canonical task status")
        object.__setattr__(self, "status", TaskStatus(self.status))
        if not isinstance(self.contract, GoalContract) or not isinstance(self.context, ScopeContext):
            raise TypeError("contract and context must be typed task values")
        if not isinstance(self.checkpoint, TaskCheckpoint):
            raise TypeError("checkpoint must be a TaskCheckpoint")
        for name in ("created_at", "updated_at", "heartbeat_expires_at"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                raise ValueError(f"{name} must be a finite nonnegative number")
            try:
                finite = math.isfinite(value)
            except OverflowError:
                finite = False
            if not finite:
                raise ValueError(f"{name} must be a finite nonnegative number")
        if not isinstance(self.verification_receipts, Mapping) or any(
            not isinstance(key, str) or not key or "\x00" in key
            or not isinstance(value, str) or not value or "\x00" in value
            for key, value in self.verification_receipts.items()
        ):
            raise ValueError("verification_receipts must map criterion strings to receipt IDs")
        object.__setattr__(self, "verification_receipts", dict(self.verification_receipts))

    @property
    def is_stale(self) -> bool:
        return bool(
            self.heartbeat_expires_at > 0
            and self.heartbeat_expires_at < time.time()
            and self.status not in {TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.FAILED, TaskStatus.ABANDONED}
        )

    def is_terminal(self) -> bool:
        return self.status in {TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.FAILED, TaskStatus.ABANDONED}

    def is_active(self) -> bool:
        return self.status == TaskStatus.ACTIVE

    def is_verifying(self) -> bool:
        return self.status == TaskStatus.VERIFYING

    def has_owner(self) -> bool:
        return bool(self.owner)

    def has_lease(self) -> bool:
        return bool(self.lease_id)

    def receipt_count(self) -> int:
        return len(self.verification_receipts)

    def has_receipt(self, criterion: str) -> bool:
        crit = str(criterion or "").replace("\x00", "").strip()
        return crit in self.verification_receipts

    def to_dict(self) -> dict[str, Any]:
        stale = self.is_stale
        return {
            "task_id": self.task_id,
            "status": self.status.value,
            "owner": self.owner,
            "lease_id": self.lease_id,
            "repo_root": _task_scope_root(self),
            "contract": self.contract.to_dict(),
            "context": {
                "repository_id": self.context.repository_id,
                "clone_id": self.context.clone_id,
                "worktree_id": self.context.worktree_id,
                "branch": self.context.branch,
                "task_id": self.context.task_id,
                "session_id": self.context.session_id,
            },
            "checkpoint": self.checkpoint.to_dict(),
            "verification_receipts": dict(self.verification_receipts),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "heartbeat_expires_at": self.heartbeat_expires_at,
            "stale": stale,
            "stale_reason": "heartbeat_expired" if stale else "",
        }

    @classmethod
    def from_dict(cls, data: Any) -> TaskState:
        if not isinstance(data, Mapping):
            raise ValueError("task state data must be a mapping")
        contract_data = data["contract"]
        if isinstance(contract_data, Mapping):
            contract = GoalContract.from_dict(contract_data)
        elif isinstance(contract_data, GoalContract):
            contract = contract_data
        else:
            raise ValueError("contract must be a GoalContract or mapping")

        context_data = data["context"]
        if isinstance(context_data, Mapping):
            context = ScopeContext(
                **dict(context_data),
            )
        elif isinstance(context_data, ScopeContext):
            context = context_data
        else:
            raise ValueError("context must be a ScopeContext or mapping")

        checkpoint_data = data["checkpoint"]
        if isinstance(checkpoint_data, Mapping):
            checkpoint = TaskCheckpoint.from_dict(checkpoint_data)
        elif isinstance(checkpoint_data, TaskCheckpoint):
            checkpoint = checkpoint_data
        else:
            raise ValueError("checkpoint must be a TaskCheckpoint or mapping")

        receipts = data["verification_receipts"]

        return cls(
            task_id=data["task_id"],
            status=data["status"],
            contract=contract,
            context=context,
            owner=data["owner"],
            lease_id=data["lease_id"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            heartbeat_expires_at=data["heartbeat_expires_at"],
            checkpoint=checkpoint,
            verification_receipts=receipts,
        )


@dataclass(frozen=True, slots=True)
class TaskPage:
    """One bounded task query result and its completeness state."""

    tasks: tuple[TaskState, ...] = ()
    query_truncated: bool = False


def _validate_checkpoint_memory_context(
    current_state_data: Mapping[str, Any],
    requested_state_data: Mapping[str, Any],
) -> None:
    """Prevent checkpoint clients from replacing server-injected memory."""
    if "memory_context" in requested_state_data and (
        "memory_context" not in current_state_data
        or requested_state_data["memory_context"] != current_state_data["memory_context"]
    ):
        raise CompletionGateError(
            "Cannot checkpoint: memory_context is server-managed and cannot be modified"
        )
    if "_agent_task_scope" in requested_state_data and (
        "_agent_task_scope" not in current_state_data
        or requested_state_data["_agent_task_scope"] != current_state_data["_agent_task_scope"]
    ):
        raise ValueError("Cannot checkpoint: _agent_task_scope is server-managed and cannot be modified")
    if "repo_root" in requested_state_data and (
        requested_state_data["repo_root"] != current_state_data.get("repo_root")
    ):
        raise ValueError("Cannot checkpoint: repo_root is server-managed and cannot be modified")
    current_worktree = current_state_data.get("worktree")
    requested_worktree = requested_state_data.get("worktree")
    if isinstance(requested_worktree, Mapping):
        requested_root = requested_worktree.get("repo_root")
        current_root = current_worktree.get("repo_root") if isinstance(current_worktree, Mapping) else None
        if requested_root != current_root and (requested_root is not None or current_root is not None):
            raise ValueError("Cannot checkpoint: worktree repo_root is server-managed and cannot be modified")


def _preserve_checkpoint_memory_state(
    current_state_data: Mapping[str, Any],
    checkpoint: TaskCheckpoint,
    *,
    allow_server_memory_refresh: bool = False,
    allow_server_work_update: bool = False,
) -> TaskCheckpoint:
    if not allow_server_memory_refresh:
        _validate_checkpoint_memory_context(current_state_data, checkpoint.state_data)
    merged_state_data = dict(checkpoint.state_data)
    if not allow_server_work_update:
        key = "_pending_fenced_work"
        if key in merged_state_data and (key not in current_state_data or merged_state_data[key] != current_state_data[key]):
            raise ValueError("pending fenced work is server-managed")
        if key in current_state_data:
            merged_state_data[key] = current_state_data[key]
            if ("mutation_generation" in merged_state_data
                    and merged_state_data["mutation_generation"] != current_state_data.get("mutation_generation")):
                raise ValueError("mutation generation is server-managed while work is pending")
            merged_state_data["mutation_generation"] = current_state_data.get("mutation_generation")
    for key in (
        "memory_context",
        "memory_audit",
        "memory_audit_history",
        "_agent_task_scope",
        "repo_root",
    ):
        if key not in merged_state_data and key in current_state_data:
            merged_state_data[key] = current_state_data[key]
    current_worktree = current_state_data.get("worktree")
    merged_worktree = merged_state_data.get("worktree")
    if isinstance(current_worktree, Mapping) and current_worktree.get("repo_root"):
        preserved_worktree = dict(merged_worktree) if isinstance(merged_worktree, Mapping) else dict(current_worktree)
        preserved_worktree["repo_root"] = current_worktree["repo_root"]
        merged_state_data["worktree"] = preserved_worktree
    if merged_state_data == dict(checkpoint.state_data):
        return checkpoint
    return TaskCheckpoint(
        phase=checkpoint.phase,
        next_action=checkpoint.next_action,
        affected_paths=checkpoint.affected_paths,
        evidence_ids=checkpoint.evidence_ids,
        blockers=checkpoint.blockers,
        state_data=merged_state_data,
    )


def _checkpoint_with_scheduled_worktree_cleanup(checkpoint: TaskCheckpoint) -> TaskCheckpoint:
    """Keep completed worktree cleanup asynchronous and visible in task state."""
    state_data = dict(checkpoint.state_data)
    worktree = state_data.get("worktree")
    if not isinstance(worktree, Mapping) or worktree.get("cleanup_success"):
        return checkpoint
    state_data["worktree"] = {
        **dict(worktree),
        "cleanup_pending": True,
        "cleanup_scheduled": True,
    }
    return TaskCheckpoint(
        phase=checkpoint.phase,
        next_action=checkpoint.next_action,
        affected_paths=checkpoint.affected_paths,
        evidence_ids=checkpoint.evidence_ids,
        blockers=checkpoint.blockers,
        state_data=state_data,
    )


def _canonical_repository_root(value: Any) -> str:
    if not isinstance(value, (str, Path)):
        raise ValueError("repo_root is required as an explicit path")
    raw = str(value)
    if raw != raw.strip() or "\x00" in raw:
        raise ValueError("repo_root must be a canonical path")
    if not raw:
        raise ValueError("repo_root is required")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ValueError("repo_root must be absolute")
    try:
        from .repository_scope import _is_redirecting_link
        if any(_is_redirecting_link(item) for item in (path, *path.parents)):
            raise ValueError("repo_root must not contain symlinks or junctions")
        canonical = path.resolve(strict=True)
    except ValueError:
        raise
    except (OSError, RuntimeError) as exc:
        raise ValueError("repo_root must resolve to an existing directory") from exc
    if not canonical.is_dir():
        raise ValueError("repo_root must resolve to an existing directory")
    return str(canonical)


def _task_scope_root(task: TaskState) -> str:
    scope = task.checkpoint.state_data.get("_agent_task_scope")
    if scope is None:
        return ""
    if (not isinstance(scope, Mapping) or set(scope) != {"version", "repo_root"}
            or type(scope.get("version")) is not int or scope.get("version") != 2):
        raise RuntimeError("retired task scope contract requires explicit offline conversion")
    try:
        return _canonical_repository_root(scope["repo_root"])
    except ValueError:
        return ""


def _task_matches_scope(task: TaskState, repo_root: str, task_id: str | None = None) -> bool:
    if task_id and task.task_id != task_id:
        return False
    root = _task_scope_root(task)
    if not root:
        return False
    try:
        return Path(root).samefile(repo_root)
    except (OSError, RuntimeError, TypeError, ValueError):
        return False
