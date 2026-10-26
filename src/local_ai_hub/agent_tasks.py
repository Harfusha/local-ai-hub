from __future__ import annotations

from .json_utils import dumps as json_dumps

import json
import sqlite3
import contextvars
import queue
import math
import os
import sys
import threading
import tempfile
import time
import unicodedata
import uuid
import weakref
from contextlib import closing, nullcontext
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from .agent_events import AgentEvent, AgentStateStore
from .agent_identity import AgentScope, ScopeContext
from .sqlite_support import connect_sqlite, retry_busy
from .task_memory_wire import (
    mcp_wire_tokens,
    task_memory_wire_tokens,
)
from .token_accounting import json_tokens

MAX_TASK_QUERY_SCAN_ROWS = 10_000
MAX_TASK_REAP_BATCH = 64
MAX_AGENT_QUESTION_BYTES = 16_384


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


class TaskList(list[TaskState]):
    """List-compatible task page with an explicit bounded-query truncation signal."""

    def __init__(self, tasks: list[TaskState] | tuple[TaskState, ...] = (), *, query_truncated: bool = False) -> None:
        super().__init__(tasks)
        self.query_truncated = bool(query_truncated)

    def is_truncated(self) -> bool:
        return self.query_truncated

    def has_tasks(self) -> bool:
        return len(self) > 0


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
) -> TaskCheckpoint:
    if not allow_server_memory_refresh:
        _validate_checkpoint_memory_context(current_state_data, checkpoint.state_data)
    merged_state_data = dict(checkpoint.state_data)
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
        if any(item.is_symlink() for item in (path, *path.parents)):
            raise ValueError("repo_root must not contain symlinks")
        canonical = path.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("repo_root must resolve to an existing directory") from exc
    if not canonical.is_dir():
        raise ValueError("repo_root must resolve to an existing directory")
    return str(canonical)

def _task_scope_root(task: "TaskState") -> str:
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


def _task_matches_scope(task: "TaskState", repo_root: str, task_id: str | None = None) -> bool:
    if task_id and task.task_id != task_id:
        return False
    root = _task_scope_root(task)
    return bool(root) and root == repo_root



class TaskStore:
    def __init__(
        self,
        state_store: AgentStateStore,
        *,
        default_heartbeat_ttl: float = 300.0,
        policy_engine: Any | None = None,
    ) -> None:
        self.state_store = state_store
        self.default_heartbeat_ttl = float(default_heartbeat_ttl)
        self.policy_engine = policy_engine
        self.verification_store: Any | None = None
        self.memory_store: Any | None = None
        self.memory_context_compiler: Any | None = None
        self.incident_store: Any | None = None
        self._memory_lookup_slots = threading.BoundedSemaphore(1)
        self._memory_lookup_queue: queue.Queue[Any] = queue.Queue(maxsize=1)
        self._memory_lookup_worker: threading.Thread | None = None
        self._memory_lookup_finalizer = weakref.finalize(self, self._memory_lookup_queue.put_nowait, None)
        self._memory_lookup_finalizer.atexit = False
        self._lock = threading.RLock()
        self._idle_worktree_cursor: tuple[float, str] = (0.0, "")
        self._initialized = False
        self._init_projection_table()






    def set_policy_engine(self, policy_engine: Any) -> None:
        self.policy_engine = policy_engine

    @staticmethod
    def _completion_content_snapshot(
        task: TaskState,
    ) -> tuple[Any, Any, str, float, TaskCheckpoint, dict[str, str], str]:
        return (
            task.contract, task.context, task.lease_id, task.created_at,
            task.checkpoint, dict(task.verification_receipts), task.owner,
        )

    def set_verification_store(self, verification_store: Any) -> None:
        self.verification_store = verification_store

    def set_memory_adoption(
        self,
        *,
        memory_store: Any,
        context_compiler: Any,
        incident_store: Any | None = None,
    ) -> None:
        self.memory_store = memory_store
        self.memory_context_compiler = context_compiler
        self.incident_store = incident_store

    @staticmethod
    def _canonical_memory_root(value: Any) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        try:
            return os.path.normcase(str(Path(raw).expanduser().resolve(strict=False))).replace("\\", "/")
        except (OSError, RuntimeError, TypeError, ValueError):
            return ""

    @staticmethod
    def _memory_token_count(value: str) -> int:
        return max(1, len(value.strip()) // 4)

    class _MemoryDeadlineExceeded(Exception):
        pass

    @staticmethod
    def _memory_warning(code: str) -> dict[str, Any]:
        return TaskStore._account_memory_snapshot({
            "schema_version": 2, "context": {}, "instruction": "",
            "items": [], "warnings": [{"code": code}], "estimated_tokens": 0,
        })

    @staticmethod
    def _account_memory_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
        for _ in range(16):
            measured = json_tokens(snapshot)
            if snapshot.get("estimated_tokens") == measured:
                return snapshot
            snapshot["estimated_tokens"] = measured
        raise ValueError("memory snapshot accounting did not converge")

    def _check_memory_deadline(self, deadline: float, cancelled: threading.Event) -> None:
        if cancelled.is_set() or time.monotonic() >= deadline:
            raise self._MemoryDeadlineExceeded()

    @staticmethod
    def _run_memory_lookup_jobs(jobs: queue.Queue[Any], slots: threading.BoundedSemaphore) -> None:
        # A stuck backend occupies this single daemon worker/slot, never a
        # growing executor queue or a non-daemon interpreter shutdown hook.
        while not sys.is_finalizing():
            try:
                job = jobs.get(timeout=0.25)
            except queue.Empty:
                continue
            if job is None:
                jobs.task_done()
                return
            context, callback, completed, outcome = job
            try:
                outcome["value"] = context.run(callback)
            except BaseException as exc:
                outcome["error"] = "deadline" if isinstance(exc, TaskStore._MemoryDeadlineExceeded) else "unavailable"
            finally:
                jobs.task_done()
                slots.release()
                completed.set()
            del job, context, callback, completed, outcome

    @staticmethod
    def _fit_memory_snapshot(snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
        if snapshot is None:
            return None
        if (type(snapshot.get("schema_version")) is not int or snapshot.get("schema_version") != 2
                or "tenant_key" in snapshot or not isinstance(snapshot.get("context"), Mapping)):
            raise ValueError("retired memory snapshot contract requires explicit offline conversion")
        result = dict(snapshot)
        source_items = list(result.get("items", ()))
        result["items"] = []
        if not source_items:
            result["instruction"] = ""
            if not result.get("warnings"):
                return None
            result = TaskStore._account_memory_snapshot(result)
            return result if json_tokens(result) <= 512 else TaskStore._memory_warning("memory_snapshot_budget_exceeded")

        def fits(candidate: dict[str, Any]) -> bool:
            for _ in range(16):
                measured = json_tokens(candidate)
                if candidate.get("estimated_tokens") == measured:
                    return measured <= 512
                candidate["estimated_tokens"] = measured
            return False

        for source_item in source_items[:8]:
            item = dict(source_item)
            candidate = {**result, "items": [*result["items"], item]}
            if not fits(candidate):
                content = str(item.get("content", ""))
                low, high = 0, len(content)
                best = None
                while low <= high:
                    size = (low + high) // 2
                    bounded = {**item, "content": content[:size], "estimated_tokens": json_tokens(content[:size])}
                    trial = {**result, "items": [*result["items"], bounded]}
                    if fits(trial):
                        best = trial
                        low = size + 1
                    else:
                        high = size - 1
                if best is None or not best["items"][-1]["content"]:
                    continue  # Never shorten identity/provenance to fit an item.
                candidate = best
            result = candidate
        if not result["items"]:
            return TaskStore._memory_warning("memory_snapshot_budget_exceeded")
        return result if fits(result) else TaskStore._memory_warning("memory_snapshot_budget_exceeded")

    def _task_memory_context(
        self,
        task_id: str,
        contract: GoalContract,
        context: ScopeContext,
        *,
        root_override: str = "",
        previous: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if self.memory_context_compiler is None or self.memory_store is None:
            return self._memory_warning("memory_context_unavailable") if previous is not None else None

        deadline = time.monotonic() + 1.0
        if not self._memory_lookup_slots.acquire(blocking=False):
            return self._memory_warning("memory_lookup_busy")
        if time.monotonic() >= deadline:
            self._memory_lookup_slots.release()
            return self._memory_warning("memory_lookup_deadline_exceeded")
        cancelled, completed = threading.Event(), threading.Event()
        outcome: dict[str, Any] = {}

        def lookup() -> dict[str, Any] | None:
            self._check_memory_deadline(deadline, cancelled)
            root = str(root_override or "").strip()
            guard = getattr(self.memory_store, "task_retrieval_scope", None)
            with guard(contract.goal, root=root, task_id=task_id) if callable(guard) else nullcontext():
                self._check_memory_deadline(deadline, cancelled)
                snapshot = self._collect_task_memory_context(
                    task_id, contract, context, root_override=root, previous=previous,
                    deadline=deadline, cancelled=cancelled,
                )
                self._check_memory_deadline(deadline, cancelled)
                snapshot = self._fit_memory_snapshot(snapshot)
                self._check_memory_deadline(deadline, cancelled)
                return snapshot

        try:
            if self._memory_lookup_worker is None:
                worker = threading.Thread(
                    target=self._run_memory_lookup_jobs,
                    args=(self._memory_lookup_queue, self._memory_lookup_slots),
                    name="agent-task-memory-lookup", daemon=True,
                )
                worker.start()
                self._memory_lookup_worker = worker
            self._memory_lookup_queue.put_nowait((contextvars.copy_context(), lookup, completed, outcome))
        except Exception:
            self._memory_lookup_slots.release()
            return self._memory_warning("memory_context_unavailable")
        if not completed.wait(max(0.0, deadline - time.monotonic())):
            cancelled.set()
            return self._memory_warning("memory_lookup_deadline_exceeded")
        if outcome.get("error"):
            code = "memory_lookup_deadline_exceeded" if outcome["error"] == "deadline" else "memory_context_unavailable"
            return self._memory_warning(code)
        return outcome.get("value")

    def _collect_task_memory_context(
        self, task_id: str, contract: GoalContract, context: ScopeContext, *,
        root_override: str = "", previous: Mapping[str, Any] | None = None,
        deadline: float, cancelled: threading.Event,
    ) -> dict[str, Any] | None:
        compiler = self.memory_context_compiler
        memory_store = self.memory_store
        if compiler is None or memory_store is None:
            return None
        try:
            from .agent_context import ContextRequest

            root = str(root_override or "").strip()
            coordination_id = ""
            if root:
                try:
                    from .project_config import resolve_project_context

                    project = resolve_project_context(
                        root, Path(self.state_store.db_path).parent
                    )
                    resolved_identity = project.coordination_id
                    if not isinstance(resolved_identity, str) or not resolved_identity or resolved_identity != resolved_identity.strip() or "\x00" in resolved_identity:
                        raise ValueError("invalid project coordination identity")
                    coordination_id = resolved_identity
                except Exception:
                    # Missing repository identity excludes repository memory;
                    # independently scoped task/session/global records remain eligible.
                    coordination_id = ""
            self._check_memory_deadline(deadline, cancelled)
            snapshot_context = {
                "root": root, "coordination_id": coordination_id, "task_id": task_id,
                "session_id": context.session_id, "clone_id": context.clone_id,
                "worktree_id": context.worktree_id, "branch": context.branch,
            }
            warnings: list[dict[str, str]] = []
            if previous is not None:
                if (type(previous.get("schema_version")) is not int or previous.get("schema_version") != 2 or "tenant_key" in previous
                        or not isinstance(previous.get("context"), Mapping)):
                    return self._memory_warning("memory_snapshot_requires_offline_conversion")
                if previous.get("items") and previous["context"] != snapshot_context:
                    return {
                        "schema_version": 2, "context": snapshot_context,
                        "instruction": "Memory scope changed; verify memory against current context before use.",
                        "items": [], "warnings": [{"code": "memory_scope_mismatch"}], "estimated_tokens": 0,
                    }

            request = ContextRequest(
                task_id=task_id,
                token_budget=512,
                root=root,
                session_id=context.session_id,
                clone_id=context.clone_id,
                worktree_id=context.worktree_id,
                branch=context.branch,
                repository_id=context.repository_id,
                coordination_id=coordination_id,
            )
            compiled = compiler.compile(request)
            self._check_memory_deadline(deadline, cancelled)

            items: list[dict[str, Any]] = []
            warnings.extend(
                {"code": str(item.get("code", "memory_context_warning"))[:80]}
                for item in getattr(compiled, "warnings", ())[:8]
                if isinstance(item, Mapping) and str(item.get("code", "")).startswith("memory_")
            )
            diagnostic_summary = getattr(memory_store, "diagnostic_summary", None)
            if callable(diagnostic_summary):
                try:
                    summary = diagnostic_summary(
                        id_limit=0,
                        root=root or None,
                        coordination_id=coordination_id,
                        task_id=task_id,
                        session_id=context.session_id or None,
                        clone_id=context.clone_id or None,
                        worktree_id=context.worktree_id or None,
                        branch=context.branch or None,
                    )
                    for status, data in summary.items():
                        if isinstance(data, Mapping) and int(data.get("count", 0) or 0) > 0:
                            warnings.append({"code": f"memory_{str(status)[:32]}_skipped"})
                except Exception:
                    warnings.append({"code": "memory_diagnostics_unavailable"})
            self._check_memory_deadline(deadline, cancelled)
            find_records = getattr(memory_store, "find", None)
            if callable(find_records):
                try:
                    expired_found = False
                    queries = [
                        {"scope": AgentScope.GLOBAL},
                        {
                            "scope": AgentScope.REPOSITORY,
                            "repository_id": coordination_id or None,
                            "root": root or None,
                        },
                    ]
                    for query in queries:
                        for status in ("active", "confirmed"):
                            self._check_memory_deadline(deadline, cancelled)
                            records = find_records(
                                **query,
                                status=status,
                                include_expired=True,
                                semantic=False,
                                limit=8,
                            )
                            self._check_memory_deadline(deadline, cancelled)
                            for record in records:
                                expires_at = getattr(record, "expires_at", None)
                                provenance = getattr(record, "provenance", {})
                                if expires_at is None or float(expires_at) > time.time():
                                    continue
                                if not isinstance(provenance, Mapping):
                                    continue
                                if "tenant" in provenance or "tenant_key" in provenance:
                                    raise ValueError("retired memory provenance requires offline conversion")
                                expired_found = True
                                break
                            if expired_found:
                                break
                        if expired_found:
                            break
                    if expired_found:
                        warnings.append({"code": "memory_expired_skipped"})
                except Exception:
                    warnings.append({"code": "memory_expiry_check_unavailable"})
            self._check_memory_deadline(deadline, cancelled)
            instruction = (
                "Memory is advisory. Cite used memory IDs in the next checkpoint; "
                "otherwise record not_used_reason. Verify volatile facts against current source before relying on them."
            )
            token_budget = 512
            used_tokens = self._memory_token_count(instruction)
            elements = getattr(compiled, "elements", ())
            compiled_memory_ids = {
                str(getattr(element, "element_id", "") or "").strip()
                for element in elements
                if getattr(element, "source_kind", "") == "memory_record"
            }
            scoped_records_by_id: dict[str, Any] = {}
            if compiled_memory_ids:
                find_for_context = getattr(memory_store, "find_for_context", None)
                if callable(find_for_context):
                    try:
                        scoped_records = find_for_context(
                            root=root,
                            coordination_id=coordination_id,
                            task_id=task_id,
                            session_id=context.session_id,
                            clone_id=context.clone_id,
                            worktree_id=context.worktree_id,
                            branch=context.branch,
                            limit=20,
                        )
                        self._check_memory_deadline(deadline, cancelled)
                        scoped_records_by_id = {
                            str(getattr(record, "record_id", "") or "").strip(): record
                            for record in scoped_records
                            if str(getattr(record, "record_id", "") or "").strip()
                            in compiled_memory_ids
                        }
                    except Exception:
                        warnings.append({"code": "memory_scoped_lookup_unavailable"})
                else:
                    warnings.append({"code": "memory_scoped_lookup_unavailable"})
            self._check_memory_deadline(deadline, cancelled)
            for element in elements:
                self._check_memory_deadline(deadline, cancelled)
                if getattr(element, "source_kind", "") != "memory_record":
                    continue
                record_id = str(getattr(element, "element_id", "") or "").strip()
                if not record_id:
                    continue
                record = scoped_records_by_id.get(record_id)
                if record is None:
                    warnings.append({"code": "memory_record_unavailable"})
                    continue
                try:
                    status = getattr(getattr(record, "status", ""), "value", getattr(record, "status", ""))
                    scope = getattr(getattr(record, "scope", ""), "value", getattr(record, "scope", ""))
                    provenance = record.provenance
                    if not isinstance(provenance, Mapping):
                        raise ValueError("invalid provenance")
                    if status not in {"active", "confirmed"}:
                        continue
                    expires_at = getattr(record, "expires_at", None)
                    if expires_at is not None and float(expires_at) <= time.time():
                        continue
                    sensitivity = str(getattr(record, "sensitivity", "normal") or "normal").strip().lower()
                    if sensitivity not in {"normal", "low", "public"}:
                        continue
                    if "tenant" in provenance or "tenant_key" in provenance:
                        raise ValueError("retired memory provenance requires offline conversion")
                    if scope == "repository":
                        if not coordination_id or provenance.get("repository_id") != coordination_id:
                            continue
                    elif scope != "global":
                        expected_scope_ids = {
                            "clone": context.clone_id,
                            "worktree": context.worktree_id,
                            "branch": context.branch,
                            "task": task_id,
                            "session": context.session_id,
                        }
                        expected_scope_id = str(expected_scope_ids.get(str(scope), "") or "")
                        record_scope_id = str(getattr(record, "scope_id", "") or "")
                        if not expected_scope_id or expected_scope_id != record_scope_id:
                            continue
                    record_root = provenance.get("root")
                    if scope in {"task", "clone", "worktree", "branch"} and (not isinstance(record_root, str) or not record_root):
                        continue
                    if scope not in {"repository", "global"} and record_root and (
                        not root
                        or self._canonical_memory_root(record_root) != self._canonical_memory_root(root)
                    ):
                        continue
                    if scope == "repository" and not root:
                        continue
                    content = str(getattr(element, "content", "") or "").strip()
                    if not content:
                        continue
                    item_tokens = self._memory_token_count(content)
                    evidence_ids = [str(value)[:160] for value in tuple(getattr(record, "evidence_ids", ()) or ())[:8]]
                    safe_provenance: dict[str, Any] = {"evidence_ids": evidence_ids} if evidence_ids else {}
                    revision = provenance.get("repository_revision")
                    if isinstance(revision, str) and len(revision) <= 128:
                        safe_provenance["repository_revision"] = revision
                    version = provenance.get("version") or revision or getattr(record, "updated_at", "")
                    items.append({
                        "id": record_id,
                        "origin": "memory_store",
                        "content": content,
                        "source": str(getattr(record, "source", "") or "")[:64],
                        "scope": str(scope)[:32],
                        "scope_id": str(getattr(record, "scope_id", "") or "")[:256],
                        "status": str(status),
                        "version": str(version)[:128],
                        "validity": {
                            "created_at": float(getattr(record, "created_at", 0.0) or 0.0),
                            "updated_at": float(getattr(record, "updated_at", 0.0) or 0.0),
                            "expires_at": float(expires_at) if expires_at is not None else None,
                        },
                        "confidence": float(getattr(record, "confidence", 0.0) or 0.0),
                        "volatile": bool(provenance.get("volatile", False)),
                        "provenance": safe_provenance,
                        "estimated_tokens": item_tokens,
                    })
                except (AttributeError, TypeError, ValueError, OverflowError):
                    warnings.append({"code": "memory_record_invalid"})

            scorer = getattr(memory_store, "task_relevance_score", None)
            if callable(scorer):
                ranked = []
                for index, item in enumerate(items):
                    self._check_memory_deadline(deadline, cancelled)
                    try:
                        score = float(scorer(scoped_records_by_id[item["id"]], contract.goal, task_id=task_id))
                        if not math.isfinite(score):
                            raise ValueError("invalid relevance score")
                    except Exception:
                        score = 0.0
                        warnings.append({"code": "memory_relevance_unavailable"})
                    self._check_memory_deadline(deadline, cancelled)
                    ranked.append((score, index, item))
                items = [item for _, _, item in sorted(ranked, key=lambda entry: (-entry[0], entry[1]))]
            selected_items = []
            for item in items:
                remaining_tokens = token_budget - used_tokens
                if len(selected_items) >= 5 or remaining_tokens <= 0:
                    break
                content = item["content"][:remaining_tokens * 4].rstrip()
                item_tokens = self._memory_token_count(content)
                selected_items.append({**item, "content": content, "estimated_tokens": item_tokens})
                used_tokens += item_tokens
            items = selected_items

            incident_store = self.incident_store
            if root and incident_store is not None:
                finder = getattr(incident_store, "find_negative_knowledge", None)
                if callable(finder):
                    try:
                        incidents = finder(contract.goal, limit=3, root=root)
                        self._check_memory_deadline(deadline, cancelled)
                        for incident in incidents[:3]:
                            self._check_memory_deadline(deadline, cancelled)
                            if not isinstance(incident, Mapping):
                                continue
                            incident_id = str(incident.get("incident_id", "") or "").strip()
                            provenance = incident.get("provenance")
                            if not incident_id or not isinstance(provenance, Mapping):
                                continue
                            if not provenance.get("repository_key"):
                                continue
                            expires_at = incident.get("expires_at")
                            if "expires_at" not in incident:
                                getter = getattr(incident_store, "get", None)
                                if not callable(getter):
                                    warnings.append({"code": "negative_knowledge_invalid"})
                                    continue
                                full = getter(incident_id)
                                self._check_memory_deadline(deadline, cancelled)
                                if full is None or getattr(full, "repository_key", "") != provenance["repository_key"]:
                                    continue
                                expires_at = getattr(full, "expires_at", None)
                            try:
                                expires_at = float(expires_at) if expires_at is not None else None
                                if expires_at is not None and (not math.isfinite(expires_at) or expires_at <= time.time()):
                                    continue
                            except (TypeError, ValueError, OverflowError):
                                warnings.append({"code": "negative_knowledge_invalid"})
                                continue
                            detail = str(incident.get("verified_fix") or incident.get("root_cause") or "").strip()
                            if not detail:
                                continue
                            content = f"[NEGATIVE KNOWLEDGE] {str(incident.get('error_class', ''))[:100]}: {detail[:700]}"
                            remaining_tokens = token_budget - used_tokens
                            if remaining_tokens <= 0:
                                break
                            content = content[:remaining_tokens * 4].rstrip()
                            item_tokens = self._memory_token_count(content)
                            if item_tokens > remaining_tokens:
                                continue
                            items.append({
                                "id": incident_id,
                                "origin": "incident_store",
                                "content": content,
                                "source": "incident_store",
                                "scope": "repository",
                                "scope_id": "",
                                "status": "active",
                                "version": str(incident.get("state_revision", "") or "")[:128],
                                "validity": {"updated_at": float(incident.get("updated_at", 0.0) or 0.0), "expires_at": expires_at},
                                "confidence": float(incident.get("confidence", 0.0) or 0.0),
                                "volatile": True,
                                "provenance": dict(provenance),
                                "estimated_tokens": item_tokens,
                            })
                            used_tokens += item_tokens
                    except Exception:
                        warnings.append({"code": "negative_knowledge_unavailable"})
            self._check_memory_deadline(deadline, cancelled)
            if not items and not warnings:
                return None
            return {
                "schema_version": 2,
                "context": snapshot_context,
                "instruction": instruction,
                "items": items,
                "warnings": warnings[:8],
                "estimated_tokens": used_tokens if items else 0,
            }
        except self._MemoryDeadlineExceeded:
            raise
        except Exception:
            return {
                "schema_version": 2,
                "context": {},
                "instruction": "Memory unavailable; continue without memory claims. Cite used memory IDs or record not_used_reason in the next checkpoint.",
                "items": [],
                "warnings": [{"code": "memory_context_unavailable"}],
                "estimated_tokens": 0,
            }

    @staticmethod
    def _validate_memory_audit(task: TaskState) -> None:
        state_data = task.checkpoint.state_data
        memory_context = state_data.get("memory_context")
        if not isinstance(memory_context, Mapping):
            return
        if (type(memory_context.get("schema_version")) is not int or memory_context.get("schema_version") != 2 or "tenant_key" in memory_context
                or not isinstance(memory_context.get("context"), Mapping)):
            raise CompletionGateError("Retired memory snapshot contract requires explicit offline conversion")
        items = memory_context.get("items")
        warnings = memory_context.get("warnings")
        snapshot_context = memory_context["context"]
        expected_fields = {"root", "coordination_id", "task_id", "session_id", "clone_id", "worktree_id", "branch"}
        if snapshot_context and (
            set(snapshot_context) != expected_fields
            or any(not isinstance(value, str) or value != value.strip() or "\x00" in value for value in snapshot_context.values())
            or snapshot_context.get("task_id") != task.task_id
        ):
            raise CompletionGateError("Invalid checkpoint memory context identity")
        if items and not snapshot_context:
            raise CompletionGateError("Checkpoint memory items require explicit task context identity")
        if not isinstance(items, list) or not isinstance(warnings, list):
            raise CompletionGateError("Invalid checkpoint memory items/warnings contract")
        if not items and not warnings:
            return
        audit = state_data.get("memory_audit")
        if not isinstance(audit, Mapping):
            raise CompletionGateError(
                "Invalid checkpoint memory audit: memory context requires checkpoint memory_audit at state_data.memory_audit"
            )
        available_ids = {
            str(item.get("id", ""))
            for item in items
            if isinstance(item, Mapping) and str(item.get("id", "")).strip()
        }
        used_ids = audit.get("used_ids", ())
        if not isinstance(used_ids, (list, tuple)) or any(not isinstance(value, str) for value in used_ids):
            raise CompletionGateError(
                "Invalid checkpoint memory audit: state_data.memory_audit.used_ids must be a list of IDs"
            )
        if not set(used_ids).issubset(available_ids):
            raise CompletionGateError(
                "Invalid checkpoint memory audit: state_data.memory_audit references unavailable memory IDs"
            )
        raw_not_used_reason = audit.get("not_used_reason", "")
        not_used_reason = raw_not_used_reason.strip() if isinstance(raw_not_used_reason, str) else ""
        if not used_ids and not not_used_reason:
            raise CompletionGateError(
                "Invalid checkpoint memory audit: record used memory IDs or not_used_reason in state_data.memory_audit (used_ids or a nonempty reason)"
            )
        volatile_used = {
            str(item.get("id", ""))
            for item in items
            if isinstance(item, Mapping) and item.get("volatile") and str(item.get("id", "")) in used_ids
        }
        source_checks = audit.get("source_checks", {})
        if volatile_used and not isinstance(source_checks, Mapping):
            raise CompletionGateError(
                "Invalid checkpoint memory audit: volatile memory requires state_data.memory_audit.source_checks"
            )
        for record_id in volatile_used:
            check = source_checks.get(record_id) if isinstance(source_checks, Mapping) else None
            if not isinstance(check, Mapping):
                has_current_source = False
            else:
                source = str(check.get("source", "") or "").strip()
                evidence_ids = check.get("evidence_ids", ())
                has_current_source = bool(source) or (
                    isinstance(evidence_ids, (list, tuple))
                    and any(isinstance(value, str) and value.strip() for value in evidence_ids)
                )
            if not has_current_source:
                raise CompletionGateError(
                    f"Invalid checkpoint memory audit: volatile memory '{record_id}' lacks a current-source check in state_data.memory_audit.source_checks"
                )




    def _db_path_available(self) -> bool:
        """Return whether the projection database path is usable.

        AgentStateStore intentionally creates its database lazily in _ensure_schema().
        Requiring the file to exist here creates a bootstrap cycle on clean installs:
        the projection refuses to initialize because the file is absent, while the
        state store is never asked to create it.  Validate the path object instead
        and let _ensure_schema() create the parent/database atomically.
        """
        if not self.state_store.enabled:
            return False
        try:
            path = Path(self.state_store.db_path)
            return bool(path.name)
        except (RecursionError, OSError, ValueError, TypeError):
            return False


    def _init_projection_table(self) -> None:
        if self._initialized or not self._db_path_available():
            return
        with self._lock:
            if self._initialized or not self._db_path_available():
                return
            self.state_store._ensure_schema()
            def _setup() -> None:
                with closing(connect_sqlite(self.state_store.db_path)) as con:
                    from .sqlite_support import validate_durable_schema

                    validate_durable_schema(
                        con,
                        self.state_store.db_path,
                        {
                            "agent_tasks_projection": [
                                ("task_id", "TEXT", 0, 1), ("status", "TEXT", 1, 0),
                                ("owner", "TEXT", 1, 0), ("lease_id", "TEXT", 1, 0),
                                ("contract", "TEXT", 1, 0), ("context", "TEXT", 1, 0),
                                ("checkpoint", "TEXT", 1, 0), ("receipts", "TEXT", 1, 0),
                                ("heartbeat_expires_at", "REAL", 1, 0),
                                ("created_at", "REAL", 1, 0), ("updated_at", "REAL", 1, 0),
                            ],
                            "agent_questions": [
                                ("question_id", "TEXT", 0, 1),
                                ("root", "TEXT", 1, 0),
                                ("session_id", "TEXT", 1, 0), ("task_id", "TEXT", 1, 0),
                                ("question", "TEXT", 1, 0), ("answer", "TEXT", 1, 0),
                                ("status", "TEXT", 1, 0), ("asked_by", "TEXT", 1, 0),
                                ("answered_by", "TEXT", 1, 0),
                                ("created_at", "REAL", 1, 0), ("answered_at", "REAL", 0, 0),
                            ],
                        },
                        required_if_event_kinds={"agent_tasks_projection": ("task.%",)},
                    )
                    if con.execute(
                        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'agent_tasks_projection'"
                    ).fetchone() is not None:
                        document = "CASE WHEN json_valid(checkpoint) THEN checkpoint ELSE '{}' END"
                        invalid_contracts = ["NOT json_valid(checkpoint)"]
                        for path in ("$.state_data._agent_task_scope", "$.state_data.memory_context"):
                            checks = [
                                f"json_type({document}, '{path}') != 'object'",
                                f"COALESCE(json_type({document}, '{path}.{'version' if path.endswith('_agent_task_scope') else 'schema_version'}'), '') != 'integer'",
                                f"COALESCE(json_extract({document}, '{path}.{'version' if path.endswith('_agent_task_scope') else 'schema_version'}'), 0) != 2",
                                f"json_type({document}, '{path}.tenant') IS NOT NULL",
                                f"json_type({document}, '{path}.tenant_key') IS NOT NULL",
                            ]
                            if path.endswith("memory_context"):
                                checks.extend([
                                    f"COALESCE(json_type({document}, '{path}.context'), '') != 'object'",
                                    f"json_type({document}, '{path}.context.tenant') IS NOT NULL",
                                    f"json_type({document}, '{path}.context.tenant_key') IS NOT NULL",
                                ])
                            invalid_contracts.append(
                                f"(json_type({document}, '{path}') IS NOT NULL "
                                f"AND json_type({document}, '{path}') != 'null' AND ({' OR '.join(checks)}))"
                            )
                        invalid = con.execute(
                            "SELECT 1 FROM agent_tasks_projection WHERE " + " OR ".join(invalid_contracts) + " LIMIT 1"
                        ).fetchone()
                        if invalid is not None:
                            raise RuntimeError("retired task checkpoint contract requires explicit offline conversion")
                    con.execute(
                        """
                        CREATE TABLE IF NOT EXISTS agent_tasks_projection (
                            task_id TEXT PRIMARY KEY,
                            status TEXT NOT NULL,
                            owner TEXT NOT NULL,
                            lease_id TEXT NOT NULL,
                            contract TEXT NOT NULL,
                            context TEXT NOT NULL,
                            checkpoint TEXT NOT NULL,
                            receipts TEXT NOT NULL,
                            heartbeat_expires_at REAL NOT NULL,
                            created_at REAL NOT NULL,
                            updated_at REAL NOT NULL
                        );
                        """
                    )
                    con.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_agent_tasks_status
                        ON agent_tasks_projection (status, heartbeat_expires_at);
                        """
                    )
                    con.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_agent_tasks_updated
                        ON agent_tasks_projection (updated_at DESC);
                        """
                    )
                    con.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_agent_tasks_status_updated
                        ON agent_tasks_projection (status, updated_at DESC);
                        """
                    )
                    con.execute(
                        """
                        CREATE TABLE IF NOT EXISTS agent_questions (
                            question_id TEXT PRIMARY KEY,
                            root TEXT NOT NULL,
                            session_id TEXT NOT NULL,
                            task_id TEXT NOT NULL DEFAULT '',
                            question TEXT NOT NULL,
                            answer TEXT NOT NULL DEFAULT '',
                            status TEXT NOT NULL,
                            asked_by TEXT NOT NULL,
                            answered_by TEXT NOT NULL DEFAULT '',
                            created_at REAL NOT NULL,
                            answered_at REAL
                        );
                        """
                    )
                    con.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_agent_questions_session
                        ON agent_questions (root, session_id, created_at DESC);
                        """
                    )
                    self._backfill_task_search_index(con)
                    con.commit()
            retry_busy(_setup, retries=5, base_delay_seconds=0.02)
            self._initialized = True

    @staticmethod
    def _question_row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
        names = (
            "question_id", "root", "session_id", "task_id", "question",
            "answer", "status", "asked_by", "answered_by", "created_at", "answered_at",
        )
        if len(row) != len(names):
            raise ValueError("unsupported question row contract")
        result = dict(zip(names, row))
        result.pop("root", None)
        return result

    @staticmethod
    def _validate_question_text(value: Any, label: str) -> str:
        if not isinstance(value, str) or not value.strip() or "\x00" in value:
            raise ValueError(f"{label} must be a non-empty string without null bytes")
        try:
            encoded = value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValueError(f"{label} must contain valid UTF-8 text") from exc
        if len(encoded) > MAX_AGENT_QUESTION_BYTES:
            raise ValueError(f"{label} exceeds {MAX_AGENT_QUESTION_BYTES} UTF-8 bytes")
        return value.strip()

    @staticmethod
    def _validate_question_scope(root: Any, session_id: Any) -> tuple[str, str]:
        if any(not isinstance(value, str) or not value or value != value.strip() or "\x00" in value for value in (root, session_id)):
            raise ValueError("canonical root and session_id are required for agent questions")
        if len(session_id.encode("utf-8")) > 256:
            raise ValueError("session_id exceeds 256 UTF-8 bytes")
        return _canonical_repository_root(root), session_id

    @staticmethod
    def _validate_question_response_budget(response_budget_tokens: int | None) -> None:
        if response_budget_tokens is None:
            return
        if (
            isinstance(response_budget_tokens, bool)
            or not isinstance(response_budget_tokens, int)
            or response_budget_tokens < 1
        ):
            raise ValueError("response_budget_tokens must be a positive integer")

    @staticmethod
    def _preflight_question_response(
        question: dict[str, Any], response_budget_tokens: int | None,
    ) -> None:
        TaskStore._validate_question_response_budget(response_budget_tokens)
        if response_budget_tokens is None:
            return
        payload = TaskStore._include_current_request_id({"success": True, "question": question})
        required_tokens = mcp_wire_tokens(payload, text_payload=payload)
        if required_tokens > response_budget_tokens:
            raise CheckpointResponseBudgetError(response_budget_tokens, required_tokens)

    def ask_question(
        self,
        *,
        root: str,
        session_id: str,
        question: str = "",
        task_id: str = "",
        actor: str = "agent",
        question_id: str = "",
        response_budget_tokens: int | None = None,
    ) -> dict[str, Any] | None:
        """Persist a session-bound question or retrieve it within the same scope."""
        if not self._db_path_available():
            raise RuntimeError("agent question storage is unavailable")
        root_value, session_value = self._validate_question_scope(
            root, session_id
        )
        self._validate_question_response_budget(response_budget_tokens)
        if not isinstance(question_id, str) or question_id != question_id.strip() or "\x00" in question_id:
            raise ValueError("question_id must be a canonical string")
        if not isinstance(task_id, str) or task_id != task_id.strip() or "\x00" in task_id:
            raise ValueError("task_id must be a canonical string")
        question_key, task_value = question_id, task_id
        if len(question_key) > 80:
            raise ValueError("question_id exceeds 80 characters")
        if question_key:
            self._init_projection_table()
            def _read() -> dict[str, Any] | None:
                with closing(connect_sqlite(self.state_store.db_path)) as con:
                    row = con.execute(
                        """
                        SELECT question_id, root, session_id, task_id, question,
                               answer, status, asked_by, answered_by, created_at, answered_at
                        FROM agent_questions
                        WHERE question_id = ? AND root = ? AND session_id = ?
                        """,
                        (question_key, root_value, session_value),
                    ).fetchone()
                if row is None:
                    return None
                question_record = self._question_row_to_dict(row)
                return question_record if not task_value or question_record["task_id"] == task_value else None

            result = retry_busy(_read, retries=5, base_delay_seconds=0.02)
            if result is not None:
                self._preflight_question_response(result, response_budget_tokens)
            return result

        question_value = self._validate_question_text(question, "question")
        actor_value = str(actor or "agent").strip() or "agent"
        question_key = f"q_{uuid.uuid4().hex}"
        created_at = time.time()
        projected_question = {
            "question_id": question_key,
            "session_id": session_value,
            "task_id": task_value,
            "question": question_value,
            "answer": "",
            "status": "pending",
            "asked_by": actor_value,
            "answered_by": "",
            "created_at": created_at,
            "answered_at": None,
        }
        self._preflight_question_response(projected_question, response_budget_tokens)
        self._init_projection_table()

        def _write(con: sqlite3.Connection) -> tuple[dict[str, Any], list[AgentEvent]]:
            try:
                con.execute("BEGIN IMMEDIATE")
                con.execute(
                    """
                    INSERT INTO agent_questions (
                        question_id, root, session_id, task_id, question, answer,
                        status, asked_by, answered_by, created_at, answered_at
                    ) VALUES (?, ?, ?, ?, ?, '', 'pending', ?, '', ?, NULL)
                    """,
                    (
                        question_key, root_value, session_value, task_value,
                        question_value, actor_value, created_at,
                    ),
                )
                con.execute("COMMIT")
                return (projected_question, [])
            except Exception:
                if con.in_transaction:
                    con.execute("ROLLBACK")
                raise

        return self._run_ordered_task_write(_write)

    def answer_question(
        self,
        *,
        question_id: str,
        root: str,
        answer: str,
        task_id: str = "",
        actor: str = "operator",
        response_budget_tokens: int | None = None,
    ) -> dict[str, Any] | None:
        """Record an answer in the authorized repository; retain the stored session."""
        if not self._db_path_available():
            raise RuntimeError("agent question storage is unavailable")
        if any(not isinstance(value, str) or value != value.strip() or "\x00" in value for value in (root, question_id, task_id)) or not root or not question_id:
            raise ValueError("canonical question_id and root are required")
        root_value = _canonical_repository_root(root)
        question_key, task_value = question_id, task_id
        if len(question_key) > 80:
            raise ValueError("question_id exceeds 80 characters")
        self._validate_question_response_budget(response_budget_tokens)
        answer_value = self._validate_question_text(answer, "answer")
        actor_value = str(actor or "operator").strip() or "operator"
        answered_at = time.time()
        self._init_projection_table()

        def _write(con: sqlite3.Connection) -> tuple[dict[str, Any] | None, list[AgentEvent]]:
            try:
                con.execute("BEGIN IMMEDIATE")
                row = con.execute(
                    """
                    SELECT question_id, root, session_id, task_id, question,
                           answer, status, asked_by, answered_by, created_at, answered_at
                    FROM agent_questions
                    WHERE question_id = ? AND root = ?
                    """,
                    (question_key, root_value),
                ).fetchone()
                if row is None:
                    con.execute("COMMIT")
                    return None, []
                current = self._question_row_to_dict(row)
                if task_value and current["task_id"] != task_value:
                    con.execute("COMMIT")
                    return None, []
                if current["status"] not in {"pending", "answered"}:
                    raise ValueError("unsupported question status")
                if current["status"] == "answered":
                    if current["answer"] == answer_value:
                        self._preflight_question_response(current, response_budget_tokens)
                        con.execute("COMMIT")
                        return current, []
                    raise ValueError("question has already been answered")
                projected_question = {
                    **current,
                    "answer": answer_value,
                    "status": "answered",
                    "answered_by": actor_value,
                    "answered_at": answered_at,
                }
                self._preflight_question_response(projected_question, response_budget_tokens)
                con.execute(
                    """
                    UPDATE agent_questions
                    SET answer = ?, status = 'answered', answered_by = ?, answered_at = ?
                    WHERE question_id = ? AND root = ? AND status = 'pending'
                    """,
                    (answer_value, actor_value, answered_at, question_key, root_value),
                )
                updated_row = con.execute(
                    """
                    SELECT question_id, root, session_id, task_id, question,
                           answer, status, asked_by, answered_by, created_at, answered_at
                    FROM agent_questions
                    WHERE question_id = ? AND root = ?
                    """,
                    (question_key, root_value),
                ).fetchone()
                con.execute("COMMIT")
                return self._question_row_to_dict(updated_row), []
            except Exception:
                if con.in_transaction:
                    con.execute("ROLLBACK")
                raise

        return self._run_ordered_task_write(_write)

    def create(
        self,
        contract: GoalContract,
        context: ScopeContext,
        *,
        task_id: str | None = None,
        actor: str = "agent",
        idempotency_key: str = "",
        auto_worktree: bool = False,
        repo_root: str = "",
        repository_revision: str = "",
        worktree_ttl_seconds: float = 24 * 60 * 60.0,
        response_budget_tokens: int | None = None,
    ) -> TaskState:
        if not isinstance(auto_worktree, bool):
            raise ValueError("auto_worktree must be a boolean")
        if response_budget_tokens is not None and (
            isinstance(response_budget_tokens, bool)
            or not isinstance(response_budget_tokens, int)
            or response_budget_tokens < 1
        ):
            raise ValueError("response_budget_tokens must be a positive integer")
        t_id = task_id or f"task_{uuid.uuid4().hex[:12]}"
        now = time.time()
        initial_status = TaskStatus.PLANNED
        initial_sd: dict[str, Any] = {}
        try:
            canonical_root = _canonical_repository_root(repo_root) if repo_root else ""
            if auto_worktree and not canonical_root:
                raise ValueError("automatic worktree preparation requires an explicit repository root")
        except ValueError as exc:
            if auto_worktree:
                raise TaskWorktreeError(
                    f"automatic worktree preparation failed: {exc}",
                    mutation_applied=False,
                    operation_not_started=True,
                    outcome_unknown=False,
                ) from exc
            raise
        worktree_plan = None
        if canonical_root:
            initial_sd["repo_root"] = canonical_root
        if repository_revision:
            initial_sd["repository_revision"] = str(repository_revision).strip()

        if auto_worktree:
            try:
                from .process_utils import prepare_git_worktree
                r_root = canonical_root
                worktree_ttl = max(60.0, min(float(worktree_ttl_seconds), 30 * 24 * 60 * 60.0))
                worktree_expiry = now + worktree_ttl
                worktree_plan = prepare_git_worktree(
                    r_root,
                    branch_name=f"hub/task-{t_id}",
                    task_id=t_id,
                    owner=actor,
                    created_at=now,
                    ttl_seconds=worktree_ttl,
                    expires_at=worktree_expiry,
                )
                initial_sd["worktree"] = worktree_plan.response_metadata()
                if not canonical_root:
                    canonical_root = worktree_plan.repo_root
                    initial_sd["repo_root"] = canonical_root
            except Exception as exc:
                raise TaskWorktreeError(
                    f"automatic worktree preparation failed: {type(exc).__name__}: {exc}",
                    mutation_applied=False,
                    operation_not_started=True,
                    outcome_unknown=False,
                    cleanup_succeeded=None,
                ) from exc

        if canonical_root:
            initial_sd["_agent_task_scope"] = {"version": 2, "repo_root": canonical_root}

        memory_context = self._task_memory_context(
            t_id, contract, context, root_override=canonical_root or repo_root
        )
        if memory_context is not None:
            initial_sd["memory_context"] = memory_context

        initial_state = TaskState(
            task_id=t_id,
            status=initial_status,
            contract=contract,
            context=context,
            owner=actor,
            lease_id="",
            created_at=now,
            updated_at=now,
            heartbeat_expires_at=0.0,
            checkpoint=TaskCheckpoint(state_data=initial_sd),
            verification_receipts={},
        )

        self._preflight_response_budget(initial_state, response_budget_tokens)
        if worktree_plan is not None:
            try:
                from .process_utils import create_git_worktree
                r_root = canonical_root
                wt_res = create_git_worktree(
                    r_root,
                    branch_name=f"hub/task-{t_id}",
                    task_id=t_id,
                    owner=actor,
                    created_at=now,
                    ttl_seconds=worktree_plan.ttl_seconds,
                    expires_at=worktree_plan.expires_at,
                    prepared_plan=worktree_plan,
                )
            except Exception as exc:
                raise TaskWorktreeError(
                    f"automatic worktree creation outcome is unknown: {type(exc).__name__}: {exc}",
                    mutation_applied=None,
                    operation_not_started=False,
                    outcome_unknown=True,
                ) from exc
            if not wt_res.get("success"):
                raise TaskWorktreeError(
                    str(wt_res.get("error") or "automatic worktree creation failed"),
                    mutation_applied=wt_res.get("mutation_applied"),
                    operation_not_started=wt_res.get("operation_not_started") is True,
                    outcome_unknown=wt_res.get("outcome_unknown") is True,
                    cleanup_succeeded=wt_res.get("cleanup_succeeded"),
                )
            if wt_res != worktree_plan.response_metadata():
                raise TaskWorktreeError(
                    "automatic worktree creation metadata differed from its preflight plan",
                    mutation_applied=True,
                    operation_not_started=False,
                    outcome_unknown=True,
                )

        event = AgentEvent.create(
            stream_id=f"task:{t_id}",
            kind="task.created",
            payload=initial_state.to_dict(),
            idempotency_key=idempotency_key or f"create_{t_id}",
            actor=actor,
        )
        try:
            return self._commit_create(initial_state, event)
        except Exception as exc:
            if worktree_plan is not None:
                raise TaskWorktreeError(
                    f"task persistence failed after automatic worktree creation: {type(exc).__name__}: {exc}",
                    mutation_applied=True,
                    operation_not_started=False,
                    outcome_unknown=True,
                    cleanup_succeeded=None,
                ) from exc
            raise

    def has_task(self, task_id: str) -> bool:
        clean_id = str(task_id or "").replace("\x00", "").strip()
        if not clean_id:
            return False
        if not self._db_path_available():
            return False
        self._init_projection_table()

        def _do_check() -> bool:
            with closing(connect_sqlite(self.state_store.db_path)) as con:
                row = con.execute(
                    "SELECT 1 FROM agent_tasks_projection WHERE task_id = ?",
                    (clean_id,),
                ).fetchone()
                return bool(row)

        try:
            return bool(retry_busy(_do_check, retries=5, base_delay_seconds=0.02))
        except sqlite3.Error:
            return False

    def get(self, task_id: str) -> TaskState | None:
        if not self._db_path_available():
            return None
        self._init_projection_table()
        def _fetch_task() -> Any:
            with closing(connect_sqlite(self.state_store.db_path)) as con:
                return con.execute(
                    """
                    SELECT task_id, status, owner, lease_id, contract, context, checkpoint, receipts,
                           heartbeat_expires_at, created_at, updated_at
                    FROM agent_tasks_projection
                    WHERE task_id = ?
                    """,
                    (task_id,),
                ).fetchone()

        row = retry_busy(_fetch_task, retries=5, base_delay_seconds=0.02)
        if not row:
            return None
        return self._row_to_state(row)

    @staticmethod
    def _normalize_search_text(value: Any) -> str:
        return unicodedata.normalize("NFKC", str(value or "")).casefold()

    @staticmethod
    def _collect_search_values(value: Any, fields: list[str]) -> None:
        if isinstance(value, Mapping):
            for item in value.values():
                TaskStore._collect_search_values(item, fields)
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                TaskStore._collect_search_values(item, fields)
        elif value is not None:
            text = str(value).strip()
            if text:
                fields.append(text)

    @staticmethod
    def _searchable_task_fields(
        task_id: str,
        contract: Mapping[str, Any],
        checkpoint: Mapping[str, Any],
        context: Mapping[str, Any] | None = None,
        owner: str = "",
    ) -> tuple[str, ...]:
        fields = [str(task_id)]
        if owner:
            fields.append(str(owner))
        for source in (contract, context or {}, checkpoint):
            TaskStore._collect_search_values(source, fields)
        return tuple(fields)

    @classmethod
    def _search_grams(cls, values: Any) -> set[str]:
        if isinstance(values, str):
            values = (values,)
        grams: set[str] = set()
        for value in values:
            normalized = cls._normalize_search_text(value)
            grams.update(normalized[index:index + 3] for index in range(max(0, len(normalized) - 2)))
        return grams

    @classmethod
    def _write_task_search_index(
        cls,
        con: sqlite3.Connection,
        task_id: str,
        fields: tuple[str, ...],
    ) -> None:
        con.execute("DELETE FROM agent_task_search_grams WHERE task_id = ?", (task_id,))
        con.execute(
            "INSERT OR REPLACE INTO agent_task_search_documents(task_id, fields) VALUES (?, ?)",
            (task_id, json_dumps(list(fields))),
        )
        con.executemany(
            "INSERT INTO agent_task_search_grams(task_id, gram) VALUES (?, ?)",
            ((task_id, gram) for gram in sorted(cls._search_grams(fields))),
        )

    @classmethod
    def _backfill_task_search_index(cls, con: sqlite3.Connection) -> None:
        con.execute(
            "CREATE TABLE IF NOT EXISTS agent_task_search_documents "
            "(task_id TEXT PRIMARY KEY, fields TEXT NOT NULL)"
        )
        con.execute(
            "CREATE TABLE IF NOT EXISTS agent_task_search_grams "
            "(task_id TEXT NOT NULL, gram TEXT NOT NULL, PRIMARY KEY(task_id, gram))"
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_task_search_grams_gram "
            "ON agent_task_search_grams(gram, task_id)"
        )
        rows = con.execute(
            "SELECT task_id, owner, contract, context, checkpoint FROM agent_tasks_projection"
        ).fetchall()
        for task_id, owner, contract_raw, context_raw, checkpoint_raw in rows:
            contract = json.loads(contract_raw or "{}")
            context = json.loads(context_raw or "{}")
            checkpoint = json.loads(checkpoint_raw or "{}")
            fields = cls._searchable_task_fields(task_id, contract, checkpoint, context, owner)
            expected = cls._search_grams(fields)
            document = con.execute(
                "SELECT fields FROM agent_task_search_documents WHERE task_id = ?", (task_id,)
            ).fetchone()
            existing = {
                str(row[0]) for row in con.execute(
                    "SELECT gram FROM agent_task_search_grams WHERE task_id = ?", (task_id,)
                ).fetchall()
            }
            if not document or document[0] != json_dumps(list(fields)) or existing != expected:
                cls._write_task_search_index(con, task_id, fields)
        con.execute(
            "DELETE FROM agent_task_search_documents WHERE task_id NOT IN "
            "(SELECT task_id FROM agent_tasks_projection)"
        )
        con.execute(
            "DELETE FROM agent_task_search_grams WHERE task_id NOT IN "
            "(SELECT task_id FROM agent_tasks_projection)"
        )

    @classmethod
    def _refresh_task_search_index(cls, con: sqlite3.Connection, task_id: str) -> None:
        row = con.execute(
            "SELECT owner, contract, context, checkpoint FROM agent_tasks_projection WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if not row:
            con.execute("DELETE FROM agent_task_search_documents WHERE task_id = ?", (task_id,))
            con.execute("DELETE FROM agent_task_search_grams WHERE task_id = ?", (task_id,))
            return
        owner = row[0]
        contract, context, checkpoint = (json.loads(value or "{}") for value in row[1:])
        fields = cls._searchable_task_fields(task_id, contract, checkpoint, context, owner)
        cls._write_task_search_index(con, task_id, fields)

    def list_tasks(
        self,
        status: TaskStatus | None = None,
        limit: int = 100,
        include_stale: bool = False,
        query: str | None = None,
        *,
        offset: int = 0,
    ) -> TaskList:
        if not self._db_path_available():
            return TaskList()
        self._init_projection_table()
        now = time.time()
        normalized_query = self._normalize_search_text(query or "")
        query_terms = [term for term in normalized_query.split() if term]
        page_size = max(1, int(limit))
        page_offset = max(0, int(offset))

        def matches_query(row: tuple[Any, ...]) -> bool:
            contract_data = json.loads(row[4] or "{}")
            context_data = json.loads(row[5] or "{}")
            checkpoint_data = json.loads(row[6] or "{}")
            fields = self._searchable_task_fields(
                row[0], contract_data, checkpoint_data, context_data, row[2]
            )
            normalized_fields = tuple(self._normalize_search_text(value) for value in fields)
            return all(any(term in value for value in normalized_fields) for term in query_terms)

        def _fetch_tasks() -> tuple[list[Any], bool]:
            with closing(connect_sqlite(self.state_store.db_path)) as con:
                where_clauses: list[str] = []
                params: list[Any] = []
                if status is not None:
                    where_clauses.append("status = ?")
                    params.append(status.value)
                if not query_terms and not include_stale:
                    where_clauses.append(
                        "(status IN ('completed', 'cancelled', 'failed', 'abandoned') "
                        "OR NOT (heartbeat_expires_at > 0 AND heartbeat_expires_at < ?))"
                    )
                    params.append(now)
                scan_where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
                scan_params = list(params)
                query_grams = sorted(self._search_grams(query_terms))
                if query_grams:
                    placeholders = ", ".join("?" for _ in query_grams)
                    where_clauses.append(
                        "task_id IN (SELECT task_id FROM agent_task_search_grams "
                        f"WHERE gram IN ({placeholders}) GROUP BY task_id "
                        "HAVING COUNT(DISTINCT gram) = ?)"
                    )
                    params.extend(query_grams)
                    params.append(len(query_grams))
                where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
                sql = f"""
                    SELECT task_id, status, owner, lease_id, contract, context, checkpoint, receipts,
                           heartbeat_expires_at, created_at, updated_at
                    FROM agent_tasks_projection
                    {where_sql}
                    ORDER BY updated_at DESC, task_id DESC
                """
                if not query_terms:
                    cur = con.execute(sql + " LIMIT ? OFFSET ?", (*params, page_size, page_offset))
                    return cur.fetchall(), False

                scan_count = con.execute(
                    f"SELECT COUNT(1) FROM agent_tasks_projection {scan_where_sql}", scan_params
                ).fetchone()
                cur = con.execute(sql + " LIMIT ?", (*params, MAX_TASK_QUERY_SCAN_ROWS + 1))
                candidates = cur.fetchmany(MAX_TASK_QUERY_SCAN_ROWS + 1)
                query_truncated = (
                    len(candidates) > MAX_TASK_QUERY_SCAN_ROWS
                    or bool(scan_count and int(scan_count[0]) > MAX_TASK_QUERY_SCAN_ROWS)
                )
                matched: list[Any] = []
                terminal_statuses = {
                    TaskStatus.COMPLETED.value,
                    TaskStatus.CANCELLED.value,
                    TaskStatus.FAILED.value,
                    TaskStatus.ABANDONED.value,
                }
                skipped = 0
                for row in candidates[:MAX_TASK_QUERY_SCAN_ROWS]:
                    heartbeat_expires_at = float(row[8] or 0.0)
                    if (
                        not include_stale
                        and heartbeat_expires_at > 0
                        and heartbeat_expires_at < now
                        and row[1] not in terminal_statuses
                    ):
                        continue
                    if matches_query(row):
                        if skipped < page_offset:
                            skipped += 1
                            continue
                        matched.append(row)
                        if len(matched) >= page_size:
                            return matched, False
                return matched, query_truncated

        rows, query_truncated = retry_busy(_fetch_tasks, retries=5, base_delay_seconds=0.02)
        tasks = [self._row_to_state(row) for row in rows]
        return TaskList(tasks[:page_size], query_truncated=query_truncated)

    def count(self, status: TaskStatus | None = None) -> int:
        if not self._db_path_available():
            return 0
        self._init_projection_table()
        def _fetch_count() -> int:
            with closing(connect_sqlite(self.state_store.db_path)) as con:
                if status is not None:
                    row = con.execute("SELECT COUNT(1) FROM agent_tasks_projection WHERE status = ?", (status.value,)).fetchone()
                else:
                    row = con.execute("SELECT COUNT(1) FROM agent_tasks_projection").fetchone()
                return int(row[0]) if row else 0

        return retry_busy(_fetch_count, retries=5, base_delay_seconds=0.02)

    def get_active_task(
        self,
        repo_root: str | None = None,
    ) -> TaskState | None:
        """Find the most recently updated active/planned task matching the declared repository scope."""
        if not self._db_path_available():
            return None
        target_root = self._canonical_memory_root(repo_root) if repo_root else ""
        def _matches(task: TaskState) -> bool:
            if task.is_stale or task.is_terminal():
                return False
            if target_root and self._canonical_memory_root(_task_scope_root(task)) != target_root:
                return False
            return True

        for st in (TaskStatus.ACTIVE, TaskStatus.VERIFYING, TaskStatus.PLANNED):
            tasks = self.list_tasks(status=st, limit=20, include_stale=False)
            for t in tasks:
                if _matches(t):
                    return t
        return None

    def _run_ordered_task_write(
        self,
        write: Any,
        *,
        timeout_seconds: float | None = None,
    ) -> Any:
        connection_options: dict[str, Any] = {"isolation_level": None}
        if timeout_seconds is not None:
            connection_options["timeout_seconds"] = timeout_seconds
        con = connect_sqlite(self.state_store.db_path, **connection_options)
        try:
            with self.state_store.ordered_event_publication(con) as publish_committed:
                result, events = retry_busy(
                    lambda: write(con), retries=5, base_delay_seconds=0.02
                )
                publish_committed(events)
                return result
        finally:
            con.close()

    def add_verification_receipt(self, task_id: str, criterion: str, receipt_id: str) -> TaskState:
        if not self._db_path_available():
            raise RuntimeError("agent task storage is unavailable")
        self._init_projection_table()
        def _write(con: sqlite3.Connection) -> tuple[TaskState | None, list[AgentEvent]]:
            try:
                con.execute("BEGIN IMMEDIATE")
                state, event = self.add_verification_receipt_in_transaction(
                    con, task_id, criterion, receipt_id
                )
                con.execute("COMMIT")
                return state, [event] if event is not None else []
            except Exception:
                try:
                    con.execute("ROLLBACK")
                except Exception:
                    pass
                raise
        state = self._run_ordered_task_write(_write)
        if state is None:
            raise KeyError(f"Task {task_id} not found")
        return state

    def add_verification_receipt_in_transaction(
        self,
        con: sqlite3.Connection,
        task_id: str,
        criterion: str,
        receipt_id: str,
    ) -> tuple[TaskState | None, AgentEvent | None]:
        """Update task receipt projection and event using caller's SQLite transaction."""
        if not bool(getattr(con, "in_transaction", False)):
            raise RuntimeError(
                "add_verification_receipt_in_transaction requires a caller-owned transaction"
            )
        row = con.execute(
            "SELECT * FROM agent_tasks_projection WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if not row:
            return None, None
        current = self._row_to_state(row)
        event = AgentEvent.create(
            stream_id=f"task:{task_id}",
            kind="task.verified",
            payload={"criterion": criterion, "receipt_id": receipt_id},
            idempotency_key=f"ver_{task_id}_{criterion}_{receipt_id}",
            actor="verifier",
        )
        existing = con.execute(
            "SELECT seq FROM agent_events WHERE stream_id = ? AND idempotency_key = ?",
            (event.stream_id, event.idempotency_key),
        ).fetchone()
        current_receipt = current.verification_receipts.get(criterion)
        if existing and current_receipt not in (None, receipt_id):
            appended = self.state_store.append_in_transaction(con, event, strict_idempotency=True)
            if appended.error or appended.event is None:
                raise RuntimeError(appended.error or "task receipt replay returned no persisted event")
            return current, None
        if current_receipt == receipt_id:
            appended = self.state_store.append_in_transaction(con, event, strict_idempotency=True)
            if appended.error or appended.event is None:
                raise RuntimeError(appended.error or "task receipt append returned no persisted event")
            return current, appended.event if not appended.duplicate else None

        updated_receipts = dict(current.verification_receipts)
        updated_receipts[criterion] = receipt_id
        updated_at = time.time()
        cur = con.execute(
            """
            UPDATE agent_tasks_projection
            SET receipts = ?, updated_at = ?
            WHERE task_id = ? AND receipts = ? AND updated_at = ?
            """,
            (
                json_dumps(updated_receipts),
                updated_at,
                current.task_id,
                json_dumps(current.verification_receipts),
                current.updated_at,
            ),
        )
        if cur.rowcount != 1:
            raise ConcurrentTaskUpdateError(
                f"Task {task_id} changed while recording verification receipt"
            )
        appended = self.state_store.append_in_transaction(con, event, strict_idempotency=True)
        if appended.error or appended.event is None:
            raise RuntimeError(appended.error or "task receipt append returned no persisted event")
        updated = TaskState(
            task_id=current.task_id,
            status=current.status,
            contract=current.contract,
            context=current.context,
            owner=current.owner,
            lease_id=current.lease_id,
            created_at=current.created_at,
            updated_at=updated_at,
            heartbeat_expires_at=current.heartbeat_expires_at,
            checkpoint=current.checkpoint,
            verification_receipts=updated_receipts,
        )
        return updated, appended.event if not appended.duplicate else None

    def validate_completion(self, task_id: str) -> TaskState:
        """Validate persisted completion gates without changing task state."""
        task = self.get(task_id)
        if task is None:
            raise KeyError(f"Task {task_id} not found")
        self._verify_completion(task)
        return task

    def _verify_completion(self, task: TaskState, *, current_revision: str = "") -> None:
        memory_audit_validator = getattr(self, "_validate_memory_audit", None)
        if callable(memory_audit_validator):
            memory_audit_validator(task)
        if not task.contract.acceptance_criteria:
            return

        state_data = task.checkpoint.state_data
        try:
            from .verification_rules import (
                _task_created_state_data,
                _task_project_root,
                project_command_environment_sha256,
            )

            initial_state_data = _task_created_state_data(self, task.task_id)
            repo_root = _task_project_root(task, initial_state_data)
        except Exception as exc:
            raise CompletionGateError(
                "Cannot transition to COMPLETED: trusted task project root is unavailable"
            ) from exc
        has_repo_root = isinstance(repo_root, (str, Path)) and bool(str(repo_root).strip())
        repository_revision = str(
            current_revision or state_data.get("repository_revision", "") or ""
        ).strip()
        mutation_generation = state_data.get("mutation_generation", 0)
        if isinstance(mutation_generation, bool) or not isinstance(mutation_generation, int) or mutation_generation < 0:
            raise CompletionGateError(
                "Cannot transition to COMPLETED: task mutation_generation is invalid"
            )

        configured_commands: Mapping[str, Any] = {}
        configured_environment_sha256: Mapping[str, str] = {}
        project_config_digest = ""
        if has_repo_root:
            try:
                from .project_config import resolve_project_context

                project = resolve_project_context(repo_root, Path(self.state_store.db_path).parent)
                settings = project.settings
                verification_rules = settings.verification_rules
                configured_criteria = tuple(settings.commands)
                configured_commands = settings.commands
                configured_environment_sha256 = {
                    name: project_command_environment_sha256(settings, name)
                    for name in settings.commands
                }
                project_config_digest = project.config_digest
                if not isinstance(verification_rules, Mapping) or not isinstance(settings.commands, Mapping):
                    raise ValueError("project verification settings are invalid")
            except Exception as exc:
                raise CompletionGateError(
                    "Cannot transition to COMPLETED: project verification config could not be resolved"
                ) from exc
        else:
            verification_rules = {}
            configured_criteria = ()
        acceptance = set(task.contract.acceptance_criteria)
        active_rules = any(str(key).strip() in acceptance for key in verification_rules)

        verifier = getattr(self, "verification_store", None)
        from .agent_verification import VerificationStore

        if verifier is None:
            try:
                verifier = VerificationStore(self.state_store, task_store=self)
                self.verification_store = verifier
            except Exception as exc:
                raise CompletionGateError(
                    "Cannot transition to COMPLETED: verification evaluator is unavailable"
                ) from exc
        if not isinstance(verifier, VerificationStore):
            raise CompletionGateError(
                "Cannot transition to COMPLETED: verification evaluator is unsupported"
            )

        completion = getattr(verifier, "completion", None)
        if not callable(completion):
            raise CompletionGateError(
                "Cannot transition to COMPLETED: verification evaluator has no completion method"
            )
        try:
            if active_rules and not repository_revision:
                raise CompletionGateError(
                    "Cannot transition to COMPLETED: trusted repository_revision is unavailable"
                )
            result = completion(
                task.task_id,
                current_revision=repository_revision,
                current_mutation_generation=mutation_generation,
                verification_rules=verification_rules,
                configured_criteria=configured_criteria,
                configured_commands=configured_commands,
                project_config_digest=project_config_digest,
                configured_environment_sha256=configured_environment_sha256,
                project_root=repo_root or "",
            )
        except CompletionGateError:
            raise
        except Exception as exc:
            raise CompletionGateError(
                "Cannot transition to COMPLETED: verification completion evaluation failed"
            ) from exc

        complete = result.get("complete", False) if isinstance(result, Mapping) else getattr(result, "complete", False)
        if complete is not True:
            unsatisfied = (
                result.get("unsatisfied_criteria", ())
                if isinstance(result, Mapping)
                else getattr(result, "unsatisfied_criteria", ())
            )
            stale = result.get("stale_criteria", ()) if isinstance(result, Mapping) else getattr(result, "stale_criteria", ())
            details = []
            if unsatisfied:
                details.append(f"unsatisfied={tuple(unsatisfied)}")
            if stale:
                details.append(f"stale={tuple(stale)}")
            suffix = f" ({'; '.join(details)})" if details else ""
            invalid = [
                f"criterion '{criterion}' receipt '{task.verification_receipts.get(criterion, 'missing')}': missing, failed, spoofed, wrong owner, or wrong evidence type"
                for criterion in unsatisfied
            ]
            invalid.extend(
                f"criterion '{criterion}' receipt '{task.verification_receipts.get(criterion, 'missing')}': expired or stale revision/mutation generation"
                for criterion in stale
            )
            raise CompletionGateError(
                "Cannot transition to COMPLETED: " + ("; ".join(invalid) or f"verification evaluator rejected completion{suffix}")
            )

    def transition(
        self,
        task_id: str,
        target: TaskStatus,
        *,
        reason: str,
        actor: str,
        idempotency_key: str,
        checkpoint: TaskCheckpoint | None = None,
        response_budget_tokens: int | None = None,
        _allow_server_memory_refresh: bool = False,
        _expected_reap: tuple[str, TaskStatus, float, float] | None = None,
        _prepared_updated_at: float | None = None,
        _expected_completion_content: tuple[Any, Any, str, float, TaskCheckpoint, dict[str, str], str] | None = None,
    ) -> TaskState:
        if response_budget_tokens is not None and (
            isinstance(response_budget_tokens, bool)
            or not isinstance(response_budget_tokens, int)
            or response_budget_tokens < 1
        ):
            raise ValueError("response_budget_tokens must be a positive integer")
        current = self.get(task_id)
        if not current:
            raise KeyError(f"Task {task_id} not found")
        if _expected_completion_content is not None and (
            current.contract != _expected_completion_content[0]
            or current.context != _expected_completion_content[1]
            or current.lease_id != _expected_completion_content[2]
            or current.created_at != _expected_completion_content[3]
            or current.checkpoint != _expected_completion_content[4]
            or current.verification_receipts != _expected_completion_content[5]
            or current.owner not in (_expected_completion_content[6], actor)
        ):
            raise ConcurrentTaskUpdateError("task completion content changed after response preflight")

        if _expected_reap is not None:
            expected_root, expected_status, expected_expiry, deadline = _expected_reap
            if (
                not _task_matches_scope(current, expected_root, task_id)
                or current.status is not expected_status
                or current.heartbeat_expires_at != expected_expiry
                or expected_expiry <= 0
                or expected_expiry >= deadline
            ):
                raise ConcurrentTaskUpdateError(
                    f"Task {task_id} changed scope or heartbeat before reap transition"
                )

        if checkpoint is not None:
            checkpoint = _preserve_checkpoint_memory_state(
                current.checkpoint.state_data,
                checkpoint,
                allow_server_memory_refresh=_allow_server_memory_refresh,
            )

        if target == current.status:
            if target == TaskStatus.COMPLETED:
                completed_checkpoint = _checkpoint_with_scheduled_worktree_cleanup(
                    checkpoint or current.checkpoint
                )
                checkpoint = (
                    completed_checkpoint
                    if completed_checkpoint != current.checkpoint
                    else None
                )
                candidate = (
                    replace(
                        current,
                        checkpoint=checkpoint,
                        updated_at=(
                            _prepared_updated_at
                            if _prepared_updated_at is not None
                            else current.updated_at
                        ),
                    )
                    if checkpoint is not None
                    else current
                )
                if checkpoint is not None or not idempotency_key:
                    self._preflight_response_budget(candidate, response_budget_tokens)
                # No-op retries must not trust an old terminal projection alone.
                self._verify_completion(current)
                if checkpoint is not None:
                    self._verify_completion(replace(current, checkpoint=checkpoint))
            if checkpoint is not None:
                return self.checkpoint(
                    task_id,
                    checkpoint,
                    response_budget_tokens=response_budget_tokens,
                    actor=actor,
                    idempotency_key=idempotency_key,
                    _prepared_updated_at=_prepared_updated_at,
                )
            if not idempotency_key:
                self._preflight_response_budget(current, response_budget_tokens)
                return current
            return self._replay_same_status_transition(
                task_id, target, reason=reason, actor=actor,
                idempotency_key=idempotency_key,
                response_budget_tokens=response_budget_tokens,
            )

        allowed = VALID_TRANSITIONS.get(current.status, set())
        if target not in allowed:
            raise InvalidTransitionError(
                f"Cannot transition task {task_id} from {current.status.value} to {target.value}"
            )

        if target == TaskStatus.COMPLETED:
            now_check = time.time()
            for criterion in current.contract.acceptance_criteria:
                if criterion not in current.verification_receipts:
                    raise CompletionGateError(
                        f"Cannot transition to COMPLETED: criterion '{criterion}' has no verified receipt"
                    )
                rcpt_id = current.verification_receipts[criterion]
                if not self.state_store.enabled or not self.state_store.db_path.exists():
                    raise CompletionGateError(
                        f"Cannot transition to COMPLETED: receipt '{rcpt_id}' for criterion '{criterion}' cannot be validated because verification storage is unavailable"
                    )
                try:
                    with closing(connect_sqlite(self.state_store.db_path)) as con:
                        row = con.execute(
                            """
                            SELECT task_id, criterion, evidence_id, passed, expires_at
                            FROM agent_verification_receipts WHERE receipt_id = ?
                            """,
                            (rcpt_id,),
                        ).fetchone()
                    if row is None:
                        raise CompletionGateError(
                            f"Cannot transition to COMPLETED: receipt '{rcpt_id}' for criterion '{criterion}' is missing from verification storage"
                        )
                    receipt_task_id, receipt_criterion, evidence_id, passed, expires_at = row
                    if receipt_task_id != task_id:
                        raise CompletionGateError(
                            f"Cannot transition to COMPLETED: receipt '{rcpt_id}' belongs to task '{receipt_task_id}', expected '{task_id}'"
                        )
                    if receipt_criterion != criterion:
                        raise CompletionGateError(
                            f"Cannot transition to COMPLETED: receipt '{rcpt_id}' belongs to criterion '{receipt_criterion}', expected '{criterion}'"
                        )
                    if not str(evidence_id or "").strip():
                        raise CompletionGateError(
                            f"Cannot transition to COMPLETED: receipt '{rcpt_id}' for criterion '{criterion}' has no evidence_id"
                        )
                    if not bool(passed):
                        raise CompletionGateError(
                            f"Cannot transition to COMPLETED: receipt '{rcpt_id}' for criterion '{criterion}' is marked failed"
                        )
                    if expires_at is not None and float(expires_at) < now_check:
                        raise CompletionGateError(
                            f"Cannot transition to COMPLETED: receipt '{rcpt_id}' for criterion '{criterion}' is expired (stale)"
                        )
                except CompletionGateError:
                    raise
                except Exception as exc:
                    raise CompletionGateError(
                        f"Cannot transition to COMPLETED: could not validate receipt '{rcpt_id}' for criterion '{criterion}': {exc}"
                    ) from exc

        now = _prepared_updated_at if _prepared_updated_at is not None else time.time()
        heartbeat = (
            now + self.default_heartbeat_ttl
            if target == TaskStatus.ACTIVE
            else (0.0 if target in (TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.ABANDONED, TaskStatus.FAILED) else current.heartbeat_expires_at)
        )
        if target == TaskStatus.COMPLETED:
            checkpoint = _checkpoint_with_scheduled_worktree_cleanup(
                checkpoint or current.checkpoint
            )

        updated = TaskState(
            task_id=current.task_id,
            status=target,
            contract=current.contract,
            context=current.context,
            owner=actor,
            lease_id=current.lease_id,
            created_at=current.created_at,
            updated_at=now,
            heartbeat_expires_at=heartbeat,
            checkpoint=checkpoint or current.checkpoint,
            verification_receipts=current.verification_receipts,
        )

        self._preflight_response_budget(updated, response_budget_tokens)
        if target == TaskStatus.COMPLETED:
            self._verify_completion(updated)

        event = AgentEvent.create(
            stream_id=f"task:{task_id}",
            kind="task.transitioned",
            payload={"from_status": current.status.value, "to_status": target.value, "reason": reason},
            idempotency_key=idempotency_key,
            actor=actor,
        )
        if _allow_server_memory_refresh:
            return self._commit_update(
                current, updated, event, allow_server_memory_refresh=True
            )
        return self._commit_update(current, updated, event)

    def _replay_same_status_transition(
        self,
        task_id: str,
        target: TaskStatus,
        *,
        reason: str,
        actor: str,
        idempotency_key: str,
        response_budget_tokens: int | None = None,
    ) -> TaskState:
        """Serialize a no-op retry with writers and validate its original operation."""
        def _read_retry() -> TaskState:
            con = connect_sqlite(
                self.state_store.db_path, isolation_level=None, timeout_seconds=0.25
            )
            try:
                con.execute("BEGIN IMMEDIATE")
                row = con.execute(
                    "SELECT * FROM agent_tasks_projection WHERE task_id = ?", (task_id,)
                ).fetchone()
                if not row:
                    raise KeyError(f"Task {task_id} not found")
                persisted = self._row_to_state(row)
                if persisted.status != target:
                    raise ConcurrentTaskUpdateError(
                        f"Task {task_id} changed during transition; reload and retry"
                    )
                self._preflight_response_budget(persisted, response_budget_tokens)
                existing = con.execute(
                    """SELECT stream_id, seq, event_id, kind, payload, idempotency_key,
                              correlation_id, actor, created_at
                       FROM agent_events WHERE stream_id = ? AND idempotency_key = ?""",
                    (f"task:{task_id}", idempotency_key),
                ).fetchone()
                if existing:
                    event = AgentEvent.from_row(existing)
                    payload = dict(event.payload)
                    try:
                        source_status = TaskStatus(payload.get("from_status"))
                        valid_transition = target in VALID_TRANSITIONS.get(source_status, set())
                    except (TypeError, ValueError):
                        valid_transition = False
                    if (
                        event.actor != actor
                        or event.kind != "task.transitioned"
                        or set(payload) != {"from_status", "to_status", "reason"}
                        or payload.get("to_status") != target.value
                        or payload.get("reason") != reason
                        or not valid_transition
                    ):
                        raise ValueError("idempotency key was already used")
                if target == TaskStatus.COMPLETED:
                    # Recheck the serialized projection/receipts, not the earlier read.
                    self._verify_completion(persisted)
                con.execute("COMMIT")
                return persisted
            except Exception:
                if con.in_transaction:
                    con.execute("ROLLBACK")
                raise
            finally:
                con.close()

        return retry_busy(_read_retry, retries=5, base_delay_seconds=0.02)

    def complete(
        self,
        task_id: str,
        *,
        reason: str = "completed by agent",
        actor: str = "agent",
        idempotency_key: str = "",
        response_budget_tokens: int | None = None,
        checkpoint: TaskCheckpoint | None = None,
        _prepared_completion_updated_at: float | None = None,
        _expected_completion_content: tuple[Any, Any, str, float, TaskCheckpoint, dict[str, str], str] | None = None,
    ) -> TaskState:
        if response_budget_tokens is not None and (
            isinstance(response_budget_tokens, bool)
            or not isinstance(response_budget_tokens, int)
            or response_budget_tokens < 1
        ):
            raise ValueError("response_budget_tokens must be a positive integer")
        current = self.get(task_id)
        if not current:
            raise KeyError(f"Task {task_id} not found")
        if _expected_completion_content is not None and (
            current.contract != _expected_completion_content[0]
            or current.context != _expected_completion_content[1]
            or current.lease_id != _expected_completion_content[2]
            or current.created_at != _expected_completion_content[3]
            or current.checkpoint != _expected_completion_content[4]
            or current.verification_receipts != _expected_completion_content[5]
            or current.owner not in (_expected_completion_content[6], actor)
        ):
            raise ConcurrentTaskUpdateError("task completion content changed after response preflight")
        requested_checkpoint = current.checkpoint
        if checkpoint is not None:
            requested_checkpoint = _preserve_checkpoint_memory_state(current.checkpoint.state_data, checkpoint)
        completion_checkpoint = _checkpoint_with_scheduled_worktree_cleanup(requested_checkpoint)
        expected_completion_content = (
            _expected_completion_content or self._completion_content_snapshot(current)
        )
        if current.status == TaskStatus.COMPLETED and completion_checkpoint == current.checkpoint:
            return self.transition(
                task_id,
                TaskStatus.COMPLETED,
                reason=reason,
                actor=actor,
                idempotency_key=idempotency_key,
                response_budget_tokens=response_budget_tokens,
                _expected_completion_content=expected_completion_content,
            )
        completion_updated_at = _prepared_completion_updated_at
        if completion_updated_at is None:
            completion_updated_at = self.preflight_completion_response_budget(
                task_id, response_budget_tokens, actor=actor, checkpoint=completion_checkpoint,
            )
        if current.status == TaskStatus.COMPLETED:
            checkpoint_for_transition = (
                completion_checkpoint if completion_checkpoint != current.checkpoint else None
            )
            completed = self.transition(
                task_id,
                TaskStatus.COMPLETED,
                reason=reason,
                actor=actor,
                idempotency_key=idempotency_key,
                checkpoint=checkpoint_for_transition,
                response_budget_tokens=response_budget_tokens,
                _prepared_updated_at=completion_updated_at,
                _expected_completion_content=expected_completion_content,
            )
            return completed
        if current.status not in (TaskStatus.PLANNED, TaskStatus.ACTIVE, TaskStatus.VERIFYING,
                                  TaskStatus.WAITING, TaskStatus.BLOCKED):
            raise InvalidTransitionError(f"Cannot complete task {task_id} from {current.status.value}")
        self.preflight_completion_response_budget(
            task_id, response_budget_tokens, actor=actor, checkpoint=completion_checkpoint,
            completion_updated_at=completion_updated_at,
        )
        if response_budget_tokens is not None:
            candidate = replace(
                current, status=TaskStatus.COMPLETED, owner=actor,
                updated_at=completion_updated_at, heartbeat_expires_at=0.0,
                checkpoint=completion_checkpoint,
            )
            self._verify_completion(candidate)
        if current.status == TaskStatus.PLANNED:
            current = self.transition(
                task_id,
                TaskStatus.ACTIVE,
                reason="auto-activated before completion",
                actor=actor,
                idempotency_key=f"{idempotency_key}_act" if idempotency_key else "",
                _prepared_updated_at=completion_updated_at,
                _expected_completion_content=expected_completion_content,
            )
        if current.status in (TaskStatus.WAITING, TaskStatus.BLOCKED):
            current = self.transition(
                task_id,
                TaskStatus.ACTIVE,
                reason="auto-resumed before completion",
                actor=actor,
                idempotency_key=f"{idempotency_key}_res" if idempotency_key else "",
                _prepared_updated_at=completion_updated_at,
                _expected_completion_content=expected_completion_content,
            )
        if current.status == TaskStatus.ACTIVE:
            current = self.transition(
                task_id,
                TaskStatus.VERIFYING,
                reason="auto-verifying before completion",
                actor=actor,
                idempotency_key=f"{idempotency_key}_ver" if idempotency_key else "",
                _prepared_updated_at=completion_updated_at,
                _expected_completion_content=expected_completion_content,
            )
        if current.status != TaskStatus.VERIFYING:
            raise InvalidTransitionError(
                f"Cannot complete task {task_id} from {current.status.value}"
            )
        completed = self.transition(
            task_id,
            TaskStatus.COMPLETED,
            reason=reason,
            actor=actor,
            idempotency_key=idempotency_key,
            checkpoint=completion_checkpoint,
            response_budget_tokens=response_budget_tokens,
            _prepared_updated_at=completion_updated_at,
            _expected_completion_content=expected_completion_content,
        )
        return completed

    def claim(self, task_id: str, new_owner: str, *, actor: str) -> TaskState:
        """Adopt or claim task ownership by an authorized agent on this single-owner installation."""
        current = self.get(task_id)
        if not current:
            raise KeyError(f"Task {task_id} not found")
        if current.is_terminal():
            raise ValueError(f"Cannot claim terminal task {task_id}")
        owner_name = str(new_owner or actor or "").strip()
        if not owner_name:
            raise ValueError("new_owner cannot be empty")
        if current.owner == owner_name:
            return current
        updated = replace(current, owner=owner_name, updated_at=time.time())
        event = AgentEvent.create(
            stream_id=f"task:{task_id}",
            kind="task.claimed",
            payload={"previous_owner": current.owner, "new_owner": owner_name},
            actor=actor,
        )
        res = self._commit_update(current, updated, event)
        self._rebind_verification_receipts_owner(task_id, owner_name)
        return res

    def _rebind_verification_receipts_owner(self, task_id: str, new_owner: str) -> None:
        """Rebind any existing verification receipts, proof artifacts, and execution records to new owner upon adoption."""
        verifier = getattr(self, "verification_store", None)
        if not getattr(self, "state_store", None) or not self.state_store.enabled:
            return
        from contextlib import closing
        import json as _json, hashlib as _hashlib
        from .sqlite_support import connect_sqlite, retry_busy

        def _update() -> None:
            with closing(connect_sqlite(self.state_store.db_path)) as con:
                cur = con.execute(
                    "SELECT receipt_id, evidence_id, command_id, repository_revision, details FROM agent_verification_receipts WHERE task_id = ?",
                    (task_id,),
                )
                rows = cur.fetchall()
                if not rows:
                    return
                art_store = getattr(verifier, "artifact_store", None)
                for r_id, ev_id, cmd_id, repo_rev, raw_det in rows:
                    try:
                        d = _json.loads(raw_det) if raw_det else {}
                        if isinstance(d, dict) and "_verification_receipt" in d:
                            d["_verification_receipt"]["owner"] = new_owner
                            con.execute(
                                "UPDATE agent_verification_receipts SET details = ? WHERE receipt_id = ?",
                                (_json.dumps(d), r_id),
                            )
                        if art_store is not None and getattr(art_store, "path", None) and ev_id:
                            with closing(connect_sqlite(art_store.path)) as art_con:
                                a_cur = art_con.execute(f"SELECT text FROM {getattr(art_store, '_table', 'artifacts')} WHERE artifact_id = ?", (ev_id,))
                                a_row = a_cur.fetchone()
                                if a_row and isinstance(a_row[0], str):
                                    proof = _json.loads(a_row[0])
                                    if isinstance(proof, dict) and proof.get("owner") != new_owner:
                                        proof["owner"] = new_owner
                                        art_con.execute(
                                            f"UPDATE {getattr(art_store, '_table', 'artifacts')} SET text = ? WHERE artifact_id = ?",
                                            (_json.dumps(proof, sort_keys=True), ev_id),
                                        )
                                        art_con.commit()
                        if cmd_id:
                            exec_dir = Path(self.state_store.db_path).parent / "command-transactions" / "execution-records"
                            rec_path = exec_dir / f"{_hashlib.sha256(cmd_id.encode('ascii')).hexdigest()}.json"
                            if rec_path.exists():
                                rec_data = _json.loads(rec_path.read_text(encoding="utf-8"))
                                rec_data["owner"] = new_owner
                                from .agent_verification import _stored_receipt
                                rec_row = con.execute(
                                    "SELECT receipt_id, task_id, criterion, change_intent_id, evidence_id, command_id, repository_revision, observed_at, expires_at, passed, details FROM agent_verification_receipts WHERE receipt_id = ?",
                                    (r_id,),
                                ).fetchone()
                                if rec_row:
                                    updated_r = _stored_receipt(rec_row)
                                    rec_data["receipt_sha256"] = _hashlib.sha256(
                                        _json.dumps(updated_r.to_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
                                    ).hexdigest()
                                encoded = _json.dumps(rec_data, sort_keys=True, separators=(",", ":")).encode("utf-8")
                                rec_data["record_sha256"] = _hashlib.sha256(encoded).hexdigest()
                                rec_path.write_text(_json.dumps(rec_data, sort_keys=True, indent=2), encoding="utf-8")
                    except Exception:
                        pass
                con.commit()

        try:
            retry_busy(_update, retries=5, base_delay_seconds=0.02)
        except Exception:
            pass

    def preflight_completion_response_budget(
        self,
        task_id: str,
        response_budget_tokens: int | None,
        *,
        actor: str,
        checkpoint: TaskCheckpoint | None = None,
        completion_updated_at: float | None = None,
    ) -> float | None:
        """Check the final completion projection before any completion writes."""
        if response_budget_tokens is None and completion_updated_at is None:
            return None
        if response_budget_tokens is not None and (
            isinstance(response_budget_tokens, bool)
            or not isinstance(response_budget_tokens, int)
            or response_budget_tokens < 1
        ):
            raise ValueError("response_budget_tokens must be a positive integer")
        current = self.get(task_id)
        if current is None:
            raise KeyError(f"Task {task_id} not found")
        prepared_updated_at = completion_updated_at if completion_updated_at is not None else time.time()
        candidate_checkpoint = current.checkpoint
        if checkpoint is not None:
            candidate_checkpoint = _preserve_checkpoint_memory_state(
                current.checkpoint.state_data, checkpoint
            )
        candidate_checkpoint = _checkpoint_with_scheduled_worktree_cleanup(candidate_checkpoint)
        candidate = replace(
            current,
            status=TaskStatus.COMPLETED,
            owner=current.owner if current.status is TaskStatus.COMPLETED else actor,
            updated_at=prepared_updated_at,
            heartbeat_expires_at=(
                current.heartbeat_expires_at
                if current.status is TaskStatus.COMPLETED
                else 0.0
            ),
            checkpoint=candidate_checkpoint,
        )
        self._preflight_response_budget(candidate, response_budget_tokens)
        return prepared_updated_at

    def _mark_cleanup_pending(self, task: TaskState, reason: str, *, actor: str) -> TaskState:
        wt = task.checkpoint.state_data.get("worktree")
        if not isinstance(wt, dict):
            return task
        state_data = dict(task.checkpoint.state_data)
        state_data["worktree"] = {**wt, "cleanup_pending": True, "cleanup_warning": reason[:240]}
        cp = TaskCheckpoint(
            phase=task.checkpoint.phase, next_action=task.checkpoint.next_action,
            affected_paths=task.checkpoint.affected_paths, evidence_ids=task.checkpoint.evidence_ids,
            blockers=task.checkpoint.blockers, state_data=state_data,
        )
        try:
            return self.checkpoint(task.task_id, cp, actor=actor,
                                   idempotency_key=f"cleanup_pending_{task.task_id}_{wt.get('worktree_id', '')}")
        except Exception:
            return self.get(task.task_id) or task

    def cleanup_idle_worktrees(self, *, limit: int = 32, deadline_seconds: float = 8.0) -> dict[str, int]:
        """Reap scheduled or expired terminal worktrees after ownership and cleanliness checks."""
        from .process_utils import process_owner_state
        from .worktrees import is_hub_temporary_worktree, worktree_is_clean_ancestor

        budget = max(0.0, min(float(deadline_seconds), 8.0))
        deadline = time.monotonic() + budget
        counts = {"cleaned": 0, "preserved": 0, "scanned": 0}
        terminal = (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.ABANDONED)
        cap = max(1, min(int(limit), 32))
        with closing(connect_sqlite(self.state_store.db_path)) as con:
            statuses = tuple(status.value for status in terminal)
            placeholders = ",".join("?" for _ in statuses)
            cursor_time, cursor_id = self._idle_worktree_cursor
            rows = con.execute(
                f"SELECT task_id, updated_at FROM agent_tasks_projection "
                f"WHERE status IN ({placeholders}) AND checkpoint LIKE '%worktree_path%' "
                "AND (updated_at > ? OR (updated_at = ? AND task_id > ?)) "
                "ORDER BY updated_at, task_id LIMIT ?",
                (*statuses, cursor_time, cursor_time, cursor_id, cap),
            ).fetchall()
            if not rows:
                rows = con.execute(
                    f"SELECT task_id, updated_at FROM agent_tasks_projection "
                    f"WHERE status IN ({placeholders}) AND checkpoint LIKE '%worktree_path%' "
                    "ORDER BY updated_at, task_id LIMIT ?",
                    (*statuses, cap),
                ).fetchall()
            if rows:
                self._idle_worktree_cursor = (float(rows[-1][1]), str(rows[-1][0]))
        for task_id, _updated_at in rows:
            if time.monotonic() >= deadline:
                return counts
            candidate = self.get(str(task_id))
            if candidate is None:
                continue
            counts["scanned"] += 1
            wt = candidate.checkpoint.state_data.get("worktree")
            if not isinstance(wt, dict) or wt.get("cleanup_success"):
                counts["preserved"] += 1
                continue
            try:
                expires_at = float(wt["expires_at"])
                creator = {
                    "pid": int(wt["creator_pid"]), "creation_identity": wt["creator_creation_identity"],
                    "creation_identity_type": wt["creator_creation_identity_type"],
                    "executable": wt["creator_executable"], "state_dir": str(Path(tempfile.gettempdir()).resolve()),
                    "role": "worktree",
                }
                repo = Path(str(wt["repo_root"])).resolve(strict=True)
                path = Path(str(wt["worktree_path"]))
                cleanup_scheduled = wt.get("cleanup_scheduled") is True
                if not cleanup_scheduled and (
                    expires_at >= time.time()
                    or process_owner_state(creator, tempfile.gettempdir(), "worktree") != "stale"
                ):
                    counts["preserved"] += 1
                    continue
                if not is_hub_temporary_worktree(path):
                    counts["preserved"] += 1
                    continue
                if time.monotonic() >= deadline:
                    counts["preserved"] += 1
                    return counts
                remaining = max(0.5, min(3.0, deadline - time.monotonic()))
                safe, _reason = worktree_is_clean_ancestor(
                    repo, path, str(wt["base_commit"]), timeout_seconds=remaining,
                    deadline_monotonic=deadline,
                )
                if not safe:
                    counts["preserved"] += 1
                    continue
                if time.monotonic() >= deadline:
                    counts["preserved"] += 1
                    return counts
                remaining = max(0.5, min(3.0, deadline - time.monotonic()))
                result = self.cleanup_worktree(
                    candidate.task_id, actor=candidate.owner, _timeout_seconds=remaining,
                    _required_base_commit=str(wt["base_commit"]),
                    _deadline_monotonic=deadline,
                )
                if result.get("success"):
                    counts["cleaned"] += 1
                else:
                    self._mark_cleanup_pending(candidate, str(result.get("error") or "idle cleanup failed"), actor=candidate.owner)
                    counts["preserved"] += 1
            except Exception:
                counts["preserved"] += 1
        return counts

    @staticmethod
    def _include_current_request_id(response: dict[str, Any]) -> dict[str, Any]:
        from .trace_context import current as current_trace_context

        request_id = str(current_trace_context().get("request_id") or "")
        if request_id:
            response.setdefault("request_id", request_id)
        return response

    @staticmethod
    def _preflight_response_budget(task: TaskState, response_budget_tokens: int | None) -> None:
        if response_budget_tokens is None:
            return
        if (
            isinstance(response_budget_tokens, bool)
            or not isinstance(response_budget_tokens, int)
            or response_budget_tokens < 1
        ):
            raise ValueError("response_budget_tokens must be a positive integer")
        raw_result = TaskStore._include_current_request_id({"success": True, "task": task.to_dict()})
        required_tokens = task_memory_wire_tokens(raw_result, response_budget_tokens)
        if required_tokens > response_budget_tokens:
            raise CheckpointResponseBudgetError(response_budget_tokens, required_tokens)

    def fail(
        self,
        task_id: str,
        *,
        reason: str = "failed by agent",
        actor: str = "agent",
        idempotency_key: str = "",
        response_budget_tokens: int | None = None,
    ) -> TaskState:
        if response_budget_tokens is not None and (
            isinstance(response_budget_tokens, bool)
            or not isinstance(response_budget_tokens, int)
            or response_budget_tokens < 1
        ):
            raise ValueError("response_budget_tokens must be a positive integer")
        current = self.get(task_id)
        if not current:
            raise KeyError(f"Task {task_id} not found")
        if current.status == TaskStatus.FAILED:
            self._preflight_response_budget(current, response_budget_tokens)
            return current
        if current.status in (
            TaskStatus.PLANNED,
            TaskStatus.ACTIVE,
            TaskStatus.VERIFYING,
            TaskStatus.WAITING,
            TaskStatus.BLOCKED,
            TaskStatus.ABANDONED,
        ):
            now = time.time()
            updated = TaskState(
                task_id=current.task_id,
                status=TaskStatus.FAILED,
                contract=current.contract,
                context=current.context,
                owner=actor,
                lease_id=current.lease_id,
                created_at=current.created_at,
                updated_at=now,
                heartbeat_expires_at=0.0,
                checkpoint=current.checkpoint,
                verification_receipts=current.verification_receipts,
            )
            self._preflight_response_budget(updated, response_budget_tokens)
            event = AgentEvent.create(
                stream_id=f"task:{task_id}",
                kind="task.transitioned",
                payload={"from_status": current.status.value, "to_status": TaskStatus.FAILED.value, "reason": reason},
                idempotency_key=idempotency_key,
                actor=actor,
            )
            return self._commit_update(current, updated, event)
        raise InvalidTransitionError(
            f"Cannot fail task {task_id} from {current.status.value}"
        )

    def checkpoint(
        self,
        task_id: str,
        checkpoint: TaskCheckpoint,
        *,
        response_budget_tokens: int | None = None,
        capture_files: bool = False,
        actor: str = "agent",
        idempotency_key: str = "",
        _prepared_updated_at: float | None = None,
    ) -> TaskState:
        if response_budget_tokens is not None and (
            isinstance(response_budget_tokens, bool)
            or not isinstance(response_budget_tokens, int)
            or response_budget_tokens < 1
        ):
            raise ValueError("response_budget_tokens must be a positive integer")
        current = self.get(task_id)
        if not current:
            raise KeyError(f"Task {task_id} not found")

        checkpoint = _preserve_checkpoint_memory_state(
            current.checkpoint.state_data, checkpoint
        )
        self._validate_memory_audit(replace(current, checkpoint=checkpoint))

        return self._persist_checkpoint(
            current, checkpoint, capture_files=capture_files,
            actor=actor, idempotency_key=idempotency_key,
            response_budget_tokens=response_budget_tokens,
            _prepared_updated_at=_prepared_updated_at,
        )

    def _persist_checkpoint(
        self,
        current: TaskState,
        checkpoint: TaskCheckpoint,
        *,
        response_budget_tokens: int | None = None,
        capture_files: bool = False,
        actor: str = "agent",
        idempotency_key: str = "",
        _prepared_updated_at: float | None = None,
    ) -> TaskState:
        """Persist a validated agent checkpoint or server-owned bookkeeping."""
        task_id = current.task_id

        now = _prepared_updated_at if _prepared_updated_at is not None else time.time()
        heartbeat = now + self.default_heartbeat_ttl if current.status == TaskStatus.ACTIVE else current.heartbeat_expires_at

        updated = TaskState(
            task_id=current.task_id,
            status=current.status,
            contract=current.contract,
            context=current.context,
            owner=current.owner,
            lease_id=current.lease_id,
            created_at=current.created_at,
            updated_at=now,
            heartbeat_expires_at=heartbeat,
            checkpoint=checkpoint,
            verification_receipts=current.verification_receipts,
        )

        self._preflight_response_budget(updated, response_budget_tokens)

        # File reads are optional checkpoint enrichment. Complete the response
        # preflight first so an undersized MCP budget has no filesystem work.
        capture_requested = capture_files or checkpoint.state_data.get("capture_files")
        if capture_requested:
            snaps = dict(checkpoint.state_data.get("file_snapshots") or {})
            for p_str in checkpoint.affected_paths:
                if p_str not in snaps:
                    try:
                        p = Path(p_str)
                        if p.exists() and p.is_file():
                            snaps[p_str] = p.read_text(encoding="utf-8", errors="ignore")
                        else:
                            snaps[p_str] = None
                    except OSError:
                        pass
            new_sd = dict(checkpoint.state_data)
            new_sd["file_snapshots"] = snaps
            checkpoint = TaskCheckpoint(
                phase=checkpoint.phase,
                next_action=checkpoint.next_action,
                affected_paths=checkpoint.affected_paths,
                evidence_ids=checkpoint.evidence_ids,
                blockers=checkpoint.blockers,
                state_data=new_sd,
            )
            updated = replace(updated, checkpoint=checkpoint)
            # Captured snapshots affect accounting of the full HTTP result.
            # Recheck the final exact envelope before policy handling/events.
            self._preflight_response_budget(updated, response_budget_tokens)

        if self.policy_engine and current.status == TaskStatus.ACTIVE:
            budget = self.policy_engine.get_budget(task_id)
            if budget.is_exhausted():
                return self.fail(
                    task_id,
                    reason=f"TASK_BUDGET_EXCEEDED: used_tokens={budget.used_tokens}/{budget.max_tokens}, used_compute_seconds={budget.used_compute_seconds:.1f}/{budget.max_compute_seconds:.1f}s",
                    actor="watchdog",
                    response_budget_tokens=response_budget_tokens,
                )

        event = AgentEvent.create(
            stream_id=f"task:{task_id}",
            kind="task.checkpointed",
            payload=checkpoint.to_dict(),
            idempotency_key=idempotency_key or f"chk_{task_id}_{time.time_ns()}",
            actor=actor,
        )
        return self._commit_update(current, updated, event)

    def advance_mutation_generation(
        self,
        task_id: str,
        *,
        repository_revision: str = "",
        actor: str = "agent",
    ) -> TaskState:
        """Advance receipt freshness without discarding checkpoint or owned state."""
        current = self.get(task_id)
        if current is None:
            raise KeyError(f"Task {task_id} not found")
        state_data = dict(current.checkpoint.state_data)
        generation = state_data.get("mutation_generation", 0)
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
            raise ValueError("task mutation_generation must be a non-negative integer")
        generation += 1
        state_data["mutation_generation"] = generation
        if repository_revision:
            state_data["repository_revision"] = str(repository_revision).strip()
        checkpoint = replace(current.checkpoint, state_data=state_data)
        return self._persist_checkpoint(
            current,
            checkpoint,
            actor=actor,
            idempotency_key=f"mutation_{task_id}_{generation}",
        )

    def rollback(
        self,
        task_id: str,
        *,
        actor: str = "agent",
        idempotency_key: str = "",
        reason: str = "rolled back to previous checkpoint",
        response_budget_tokens: int | None = None,
    ) -> TaskState:
        current = self.get(task_id)
        if not current:
            raise KeyError(f"Task {task_id} not found")

        events = self.state_store.events(f"task:{task_id}")
        chk_events = [e for e in events if e.kind == "task.checkpointed"]
        if len(chk_events) >= 2:
            restored_checkpoint = TaskCheckpoint.from_dict(chk_events[-2].payload)
        else:
            restored_checkpoint = TaskCheckpoint()

        now = time.time()
        new_status = TaskStatus.ACTIVE if current.status in (TaskStatus.VERIFYING, TaskStatus.FAILED, TaskStatus.BLOCKED) else current.status
        updated = TaskState(
            task_id=current.task_id,
            status=new_status,
            contract=current.contract,
            context=current.context,
            owner=current.owner,
            lease_id=current.lease_id,
            created_at=current.created_at,
            updated_at=now,
            heartbeat_expires_at=now + self.default_heartbeat_ttl if new_status == TaskStatus.ACTIVE else current.heartbeat_expires_at,
            checkpoint=restored_checkpoint,
            verification_receipts=current.verification_receipts,
        )
        self._preflight_response_budget(updated, response_budget_tokens)

        snapshots = restored_checkpoint.state_data.get("file_snapshots")
        if isinstance(snapshots, dict):
            for fpath, orig_content in snapshots.items():
                try:
                    p = Path(fpath)
                    if orig_content is None:
                        if p.exists():
                            p.unlink()
                    else:
                        p.parent.mkdir(parents=True, exist_ok=True)
                        p.write_text(str(orig_content), encoding="utf-8")
                except Exception:
                    pass

        event = AgentEvent.create(
            stream_id=f"task:{task_id}",
            kind="task.rolled_back",
            payload={
                "restored_checkpoint": restored_checkpoint.to_dict(),
                "reason": reason,
                "reverted_from_status": current.status.value,
            },
            idempotency_key=idempotency_key or f"rb_{task_id}_{int(now)}",
            actor=actor,
        )
        return self._commit_update(current, updated, event)

    def resume(
        self,
        task_id: str,
        *,
        actor: str = "agent",
        idempotency_key: str = "",
        response_budget_tokens: int | None = None,
    ) -> TaskState:
        current = self.get(task_id)
        if not current:
            raise KeyError(f"Task {task_id} not found")
        resume_key = idempotency_key or f"resume_{task_id}_{int(time.time())}"
        if current.status == TaskStatus.ACTIVE and idempotency_key:
            return self._replay_same_status_transition(
                task_id,
                TaskStatus.ACTIVE,
                reason="resumed from checkpoint",
                actor=actor,
                idempotency_key=resume_key,
                response_budget_tokens=response_budget_tokens,
            )
        state_data = dict(current.checkpoint.state_data)
        previous_audit = state_data.pop("memory_audit", None)
        if isinstance(previous_audit, Mapping):
            history = list(state_data.get("memory_audit_history", ()))
            history.append(dict(previous_audit))
            state_data["memory_audit_history"] = history[-20:]
        memory_context = self._task_memory_context(
            task_id,
            current.contract,
            current.context,
            root_override=_task_scope_root(current),
            previous=state_data.get("memory_context") if isinstance(state_data.get("memory_context"), Mapping) else None,
        )
        if memory_context is not None:
            state_data["memory_context"] = memory_context
        elif "memory_context" in state_data:
            # Explicit server refresh: omission would preserve the old snapshot
            # through the existing immutable-checkpoint merge.
            state_data["memory_context"] = None
        state_data["memory_audit"] = None
        resumed_checkpoint = TaskCheckpoint(
            phase=current.checkpoint.phase,
            next_action=current.checkpoint.next_action,
            affected_paths=current.checkpoint.affected_paths,
            evidence_ids=current.checkpoint.evidence_ids,
            blockers=current.checkpoint.blockers,
            state_data=state_data,
        )
        return self.transition(
            task_id,
            TaskStatus.ACTIVE,
            reason="resumed from checkpoint",
            actor=actor,
            idempotency_key=resume_key,
            checkpoint=resumed_checkpoint,
            response_budget_tokens=response_budget_tokens,
            _allow_server_memory_refresh=True,
        )

    def heartbeat(
        self,
        task_id: str,
        ttl_seconds: float | None = None,
        *,
        actor: str = "agent",
        idempotency_key: str = "",
        response_budget_tokens: int | None = None,
    ) -> TaskState:
        current = self.get(task_id)
        if not current:
            raise KeyError(f"Task {task_id} not found")

        now = time.time()
        ttl = float(ttl_seconds) if ttl_seconds is not None and float(ttl_seconds) > 0 else self.default_heartbeat_ttl
        new_expiry = now + ttl

        updated = TaskState(
            task_id=current.task_id,
            status=current.status,
            contract=current.contract,
            context=current.context,
            owner=current.owner,
            lease_id=current.lease_id,
            created_at=current.created_at,
            updated_at=now,
            heartbeat_expires_at=new_expiry,
            checkpoint=current.checkpoint,
            verification_receipts=current.verification_receipts,
        )
        self._preflight_response_budget(updated, response_budget_tokens)

        event = AgentEvent.create(
            stream_id=f"task:{task_id}",
            kind="task.heartbeat",
            payload={"heartbeat_expires_at": new_expiry, "ttl_seconds": ttl},
            idempotency_key=idempotency_key or f"hb_{task_id}_{int(now)}",
            actor=actor,
        )
        return self._commit_update(current, updated, event)

    def cleanup_worktree(
        self,
        task_id: str,
        delete_branch: bool = True,
        *,
        actor: str = "http-default",
        response_budget_tokens: int | None = None,
        _timeout_seconds: float = 30.0,
        _required_base_commit: str = "",
        _deadline_monotonic: float | None = None,
    ) -> dict[str, Any]:
        task = self.get(task_id)
        if not task:
            return {"success": False, "error": f"Task {task_id} not found"}
        if response_budget_tokens is not None and (
            isinstance(response_budget_tokens, bool)
            or not isinstance(response_budget_tokens, int)
            or response_budget_tokens < 1
        ):
            raise ValueError("response_budget_tokens must be a positive integer")
        wt = task.checkpoint.state_data.get("worktree")
        if not isinstance(wt, dict) or not wt.get("worktree_path"):
            return {"success": True, "had_worktree": False}
        actor_value = str(actor or "").strip()
        if not actor_value or actor_value.lower() in {"http-default", "system", "admin", "*"}:
            return {"success": False, "error": "cleanup requires a non-reserved owner actor"}
        if actor_value != task.owner:
            return {"success": False, "error": "cleanup actor does not own task"}

        try:
            from .process_utils import (
                get_git_worktree_ownership,
                remove_git_worktree,
                verify_git_worktree_cleanup_complete,
            )

            task_id_value = str(wt.get("task_id", ""))
            owner_value = str(wt.get("owner", ""))
            repo_value = Path(_canonical_repository_root(wt.get("repo_root")))
            worktree_id = str(wt.get("worktree_id", ""))
            branch = str(wt.get("branch", ""))
            worktree_path = Path(str(wt.get("worktree_path", ""))).expanduser()
            if not task_id_value or task_id_value != task.task_id:
                return {"success": False, "error": "worktree task identity mismatch"}
            if not owner_value or owner_value != task.owner:
                return {"success": False, "error": "worktree owner identity mismatch"}
            if not worktree_id or not branch or worktree_path.is_symlink():
                return {"success": False, "error": "worktree ownership metadata is incomplete"}
            scope_root = _task_scope_root(task)
            if not scope_root:
                return {"success": False, "error": "worktree cleanup requires the server-managed task scope root"}
            expected_repo = Path(scope_root)
            if repo_value != expected_repo:
                return {"success": False, "error": "worktree repository does not match the server-managed task scope"}
            created_at = float(wt["created_at"])
            ttl_seconds = float(wt["ttl_seconds"])
            expires_at = float(wt["expires_at"])
            if (
                not math.isfinite(created_at)
                or not math.isfinite(ttl_seconds)
                or not math.isfinite(expires_at)
                or ttl_seconds < 60.0
                or ttl_seconds > 30 * 24 * 60 * 60.0
                or abs(expires_at - (created_at + ttl_seconds)) > 0.001
            ):
                return {"success": False, "error": "worktree lifetime metadata is inconsistent"}
            if wt.get("cleanup_success") and not worktree_path.exists():
                return {"success": True, "had_worktree": True, "already_cleaned": True}

            cleaned_at = time.time()
            cleaned_wt = {**wt, "cleanup_success": True, "cleaned_at": cleaned_at}
            cleaned_wt.pop("cleanup_pending", None)
            cleaned_wt.pop("cleanup_warning", None)
            cleaned_wt.pop("cleanup_intent", None)
            projected_data = {**task.checkpoint.state_data, "worktree": cleaned_wt}
            projected_checkpoint = TaskCheckpoint(
                phase=task.checkpoint.phase,
                next_action=task.checkpoint.next_action,
                affected_paths=task.checkpoint.affected_paths,
                evidence_ids=task.checkpoint.evidence_ids,
                blockers=task.checkpoint.blockers,
                state_data=projected_data,
            )
            projected_task = TaskState(
                task_id=task.task_id,
                status=task.status,
                contract=task.contract,
                context=task.context,
                owner=task.owner,
                lease_id=task.lease_id,
                created_at=task.created_at,
                updated_at=cleaned_at,
                heartbeat_expires_at=task.heartbeat_expires_at,
                checkpoint=projected_checkpoint,
                verification_receipts=task.verification_receipts,
            )
            self._preflight_response_budget(projected_task, response_budget_tokens)
            if response_budget_tokens is not None:
                projected_cleanup = {
                    "success": True,
                    "worktree_removed": True,
                    "branch_deleted": bool(delete_branch),
                    "repo_root": str(repo_value),
                    "worktree_path": str(worktree_path.resolve(strict=False)),
                    "worktree_id": worktree_id,
                }
                projected_response = self._include_current_request_id({
                    "success": True,
                    "had_worktree": True,
                    "cleanup": projected_cleanup,
                    "cleaned_at": cleaned_at,
                    "task": projected_task.to_dict(),
                })
                required_tokens = mcp_wire_tokens(
                    projected_response, text_payload=projected_response,
                )
                if required_tokens > response_budget_tokens:
                    raise CheckpointResponseBudgetError(response_budget_tokens, required_tokens)
            cleanup_intent = wt.get("cleanup_intent")
            expected_intent = {
                "task_id": task_id_value,
                "owner": owner_value,
                "worktree_id": worktree_id,
                "branch": branch,
                "delete_branch": bool(delete_branch),
                "repo_root": str(repo_value),
                "worktree_path": str(worktree_path.resolve(strict=False)),
            }
            if cleanup_intent is not None and cleanup_intent != expected_intent:
                return {"success": False, "error": "worktree cleanup intent does not match this request"}
            if cleanup_intent == expected_intent and not worktree_path.exists():
                reconciled = verify_git_worktree_cleanup_complete(
                    repo_value,
                    worktree_path,
                    branch_name=branch,
                    delete_branch=bool(delete_branch),
                    timeout_seconds=_timeout_seconds,
                    deadline_monotonic=_deadline_monotonic,
                )
                if not reconciled.get("success"):
                    return {
                        "success": False,
                        "had_worktree": True,
                        "cleanup": reconciled,
                        "error": reconciled.get("error", "cleanup outcome could not be reconciled"),
                    }
                updated = self.checkpoint(
                    task_id,
                    projected_checkpoint,
                    actor=actor_value,
                    idempotency_key=f"cleanup_{task_id}_{worktree_id}",
                    response_budget_tokens=response_budget_tokens,
                )
                return {
                    "success": True,
                    "had_worktree": True,
                    "already_cleaned": True,
                    "cleanup": reconciled,
                    "cleaned_at": cleaned_at,
                    "task": updated.to_dict(),
                }
            ownership = get_git_worktree_ownership(
                repo_value, worktree_path, deadline_monotonic=_deadline_monotonic
            )
            if ownership is None:
                return {"success": False, "error": "live worktree ownership marker is missing"}
            expected_fields = (
                "worktree_id",
                "task_id",
                "owner",
                "repo_root",
                "worktree_path",
                "branch",
                "created_at",
                "ttl_seconds",
                "expires_at",
                "base_commit",
                "creator_pid",
                "creator_creation_identity",
                "creator_creation_identity_type",
                "creator_executable",
            )
            if any(ownership.get(field) != wt.get(field) for field in expected_fields):
                return {"success": False, "error": "worktree ownership metadata was tampered"}

            if cleanup_intent is None:
                intent_wt = {**wt, "cleanup_intent": expected_intent, "cleanup_pending": True}
                intent_checkpoint = TaskCheckpoint(
                    phase=task.checkpoint.phase,
                    next_action=task.checkpoint.next_action,
                    affected_paths=task.checkpoint.affected_paths,
                    evidence_ids=task.checkpoint.evidence_ids,
                    blockers=task.checkpoint.blockers,
                    state_data={**task.checkpoint.state_data, "worktree": intent_wt},
                )
                self.checkpoint(
                    task_id,
                    intent_checkpoint,
                    actor=actor_value,
                    idempotency_key=f"cleanup_intent_{task_id}_{worktree_id}_{int(bool(delete_branch))}",
                    response_budget_tokens=response_budget_tokens,
                )

            rm_res = remove_git_worktree(
                repo_value,
                worktree_path,
                delete_branch=delete_branch,
                branch_name=branch,
                worktree_id=worktree_id,
                expected_task_id=task_id,
                expected_owner=str(wt.get("owner", "")),
                expected_created_at=created_at,
                expected_ttl_seconds=ttl_seconds,
                expected_expires_at=expires_at,
                timeout_seconds=_timeout_seconds,
                required_base_commit=_required_base_commit,
                deadline_monotonic=_deadline_monotonic,
            )
            if not rm_res.get("success"):
                return {"success": False, "had_worktree": True, "cleanup": rm_res, "error": rm_res.get("error", "cleanup failed")}

            updated = self.checkpoint(
                task_id,
                projected_checkpoint,
                actor=actor_value,
                idempotency_key=f"cleanup_{task_id}_{worktree_id}",
            )
            return {
                "success": True,
                "had_worktree": True,
                "cleanup": rm_res,
                "cleaned_at": cleaned_at,
                "task": updated.to_dict(),
            }
        except CheckpointResponseBudgetError:
            raise
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def _expired_repository_roots(self, *, now: float, limit: int = 16, after_root: str = "") -> list[str]:
        """Bounded watchdog inventory from the server-managed task scope."""
        if isinstance(now, bool) or not isinstance(now, (int, float)) or not math.isfinite(now):
            raise ValueError("now must be a finite timestamp")
        if type(limit) is not int or not 1 <= limit <= 64:
            raise ValueError("root limit must be an integer between 1 and 64")
        if not isinstance(after_root, str) or after_root != after_root.strip() or "\x00" in after_root:
            raise ValueError("after_root must be a canonical string")
        if not self._db_path_available():
            return []
        self._init_projection_table()
        def _read() -> list[str]:
            document = "CASE WHEN json_valid(checkpoint) THEN checkpoint ELSE '{}' END"
            with closing(connect_sqlite(self.state_store.db_path)) as con:
                rows = con.execute(
                    "SELECT json_extract(" + document + ", '$.state_data._agent_task_scope.repo_root') AS scoped_root "
                    "FROM agent_tasks_projection "
                    "WHERE status IN ('planned', 'active', 'verifying', 'waiting', 'blocked') "
                    "AND heartbeat_expires_at > 0 AND heartbeat_expires_at < ? "
                    "AND json_type(" + document + ", '$.state_data._agent_task_scope.version') = 'integer' "
                    "AND json_extract(" + document + ", '$.state_data._agent_task_scope.version') = 2 "
                    "AND json_type(" + document + ", '$.state_data._agent_task_scope.repo_root') = 'text' "
                    "AND json_extract(" + document + ", '$.state_data._agent_task_scope.repo_root') != '' "
                    "GROUP BY scoped_root HAVING scoped_root > ? ORDER BY scoped_root LIMIT ?",
                    (now, after_root, limit),
                ).fetchall()
            return [row[0] for row in rows]
        return retry_busy(_read, retries=5, base_delay_seconds=0.02)

    def reap_expired_heartbeats(
        self,
        now: float | None = None,
        *,
        auto_recover: bool = False,
        repo_root: str | Path | None = None,
        task_id: str | None = None,
        response_budget_tokens: int | None = None,
        _deadline_monotonic: float | None = None,
        _cancel_event: threading.Event | None = None,
    ) -> list[str]:
        if task_id is not None and (not isinstance(task_id, str) or not task_id or task_id != task_id.strip() or "\x00" in task_id):
            raise ValueError("task_id must be a nonempty canonical string when supplied")
        if now is not None and (isinstance(now, bool) or not isinstance(now, (int, float)) or not math.isfinite(now)):
            raise ValueError("now must be a finite timestamp")
        if _deadline_monotonic is not None and (isinstance(_deadline_monotonic, bool) or not isinstance(_deadline_monotonic, (int, float)) or not math.isfinite(_deadline_monotonic)):
            raise ValueError("deadline must be finite")
        if response_budget_tokens is not None:
            if (
                isinstance(response_budget_tokens, bool)
                or not isinstance(response_budget_tokens, int)
                or response_budget_tokens < 1
            ):
                raise ValueError("response_budget_tokens must be a positive integer")
            if not isinstance(task_id, str) or not task_id or task_id != task_id.strip():
                raise ValueError("response budget requires a nonempty canonical task_id")
            projected_response = self._include_current_request_id({"success": True, "reaped": [task_id]})
            required_tokens = mcp_wire_tokens(
                projected_response, text_payload=projected_response,
            )
            if required_tokens > response_budget_tokens:
                raise CheckpointResponseBudgetError(response_budget_tokens, required_tokens)
        try:
            scoped_root = _canonical_repository_root(repo_root)
        except ValueError:
            return []
        if not self._db_path_available():
            return []
        self._init_projection_table()
        current_time = float(time.time() if now is None else now)
        def _fetch_expired() -> list[str]:
            with closing(connect_sqlite(self.state_store.db_path)) as con:
                task_filter = " AND task_id = ?" if task_id is not None else ""
                parameters = (current_time, scoped_root, task_id, MAX_TASK_REAP_BATCH) if task_id is not None else (current_time, scoped_root, MAX_TASK_REAP_BATCH)
                cur = con.execute(
                    """
                    SELECT task_id FROM agent_tasks_projection
                    WHERE status IN ('planned', 'active', 'verifying', 'waiting', 'blocked')
                      AND heartbeat_expires_at > 0 AND heartbeat_expires_at < ?
                      AND json_type(CASE WHEN json_valid(checkpoint) THEN checkpoint ELSE '{}' END, '$.state_data._agent_task_scope.version') = 'integer'
                      AND json_extract(CASE WHEN json_valid(checkpoint) THEN checkpoint ELSE '{}' END, '$.state_data._agent_task_scope.version') = 2
                      AND json_extract(CASE WHEN json_valid(checkpoint) THEN checkpoint ELSE '{}' END, '$.state_data._agent_task_scope.repo_root') = ?
                    """ + task_filter + " ORDER BY heartbeat_expires_at, task_id LIMIT ?",
                    parameters,
                )
                return [row[0] for row in cur.fetchall()]

        expired_ids = retry_busy(_fetch_expired, retries=5, base_delay_seconds=0.02)

        reaped: list[str] = []
        for t_id in expired_ids:
            if (_cancel_event is not None and _cancel_event.is_set()) or (
                _deadline_monotonic is not None and time.monotonic() >= _deadline_monotonic
            ):
                break
            try:
                current = self.get(t_id)
                if (
                    current is None
                    or not _task_matches_scope(current, scoped_root, task_id)
                    or current.status not in {
                        TaskStatus.PLANNED,
                        TaskStatus.ACTIVE,
                        TaskStatus.VERIFYING,
                        TaskStatus.WAITING,
                        TaskStatus.BLOCKED,
                    }
                    or current.heartbeat_expires_at <= 0
                    or current.heartbeat_expires_at >= current_time
                ):
                    continue
                target_status = TaskStatus.WAITING if auto_recover and current and current.status != TaskStatus.PLANNED else TaskStatus.ABANDONED
                reason = "heartbeat expired - auto-recovered to waiting" if auto_recover else "heartbeat expired"
                self.transition(
                    t_id,
                    target_status,
                    reason=reason,
                    actor="system",
                    idempotency_key=f"reap_{t_id}_{int(current_time)}",
                    _expected_reap=(
                        scoped_root,
                        current.status,
                        current.heartbeat_expires_at,
                        current_time,
                    ),
                )
                reaped.append(t_id)
            except (ConcurrentTaskUpdateError, KeyError):
                pass
        return reaped

    def recover_zombie_tasks(
        self,
        now: float | None = None,
        *,
        repo_root: str | Path | None = None,
        task_id: str | None = None,
    ) -> list[str]:
        """Automatically detect timed-out zombie tasks and recover them to WAITING state for re-assignment."""
        return self.reap_expired_heartbeats(
            now=now,
            auto_recover=True,
            repo_root=repo_root,
            task_id=task_id,
        )

    def _save_projection(self, state: TaskState) -> None:
        if not self._db_path_available():
            return
        self._init_projection_table()

        def _do_save() -> None:
            con = connect_sqlite(self.state_store.db_path, isolation_level=None)
            try:
                con.execute("BEGIN IMMEDIATE")
                con.execute(
                    """
                    INSERT INTO agent_tasks_projection (
                        task_id, status, owner, lease_id, contract, context, checkpoint, receipts,
                        heartbeat_expires_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(task_id) DO UPDATE SET
                        status = excluded.status,
                        owner = excluded.owner,
                        lease_id = excluded.lease_id,
                        contract = excluded.contract,
                        context = excluded.context,
                        checkpoint = excluded.checkpoint,
                        receipts = excluded.receipts,
                        heartbeat_expires_at = excluded.heartbeat_expires_at,
                        updated_at = excluded.updated_at
                    """,
                    (
                        state.task_id,
                        state.status.value,
                        state.owner,
                        state.lease_id,
                        json_dumps(state.contract.to_dict()),
                        json_dumps({
                            "repository_id": state.context.repository_id,
                            "clone_id": state.context.clone_id,
                            "worktree_id": state.context.worktree_id,
                            "branch": state.context.branch,
                            "task_id": state.context.task_id,
                            "session_id": state.context.session_id,
                        }),
                        json_dumps(state.checkpoint.to_dict()),
                        json_dumps(state.verification_receipts),
                        state.heartbeat_expires_at,
                        state.created_at,
                        state.updated_at,
                    ),
                )
                self._refresh_task_search_index(con, state.task_id)
                con.execute("COMMIT")
            except Exception:
                try:
                    con.execute("ROLLBACK")
                except Exception:
                    pass
                raise
            finally:
                con.close()

        retry_busy(_do_save, retries=5, base_delay_seconds=0.02)

    def _commit_create(self, state: TaskState, event: AgentEvent) -> TaskState:
        """Atomically create initial projection, sequence cursor, and task event."""
        if not self.state_store.enabled:
            return state
        self._init_projection_table()
        context = json_dumps({
            "repository_id": state.context.repository_id,
            "clone_id": state.context.clone_id,
            "worktree_id": state.context.worktree_id,
            "branch": state.context.branch,
            "task_id": state.context.task_id,
            "session_id": state.context.session_id,
        })
        published: list[AgentEvent] = []

        def _do_commit(con: sqlite3.Connection) -> tuple[TaskState, list[AgentEvent]]:
            published.clear()
            try:
                con.execute("BEGIN IMMEDIATE")
                existing = con.execute(
                    """
                    SELECT stream_id, seq, event_id, kind, payload, idempotency_key,
                           correlation_id, actor, created_at
                    FROM agent_events WHERE stream_id = ? AND idempotency_key = ?
                    """,
                    (event.stream_id, event.idempotency_key),
                ).fetchone()
                if existing:
                    existing_event = AgentEvent.from_row(existing)
                    if existing_event.kind != event.kind or dict(existing_event.payload) != dict(event.payload):
                        raise RuntimeError("task create idempotency key conflicts with a different event")
                    current = con.execute(
                        "SELECT * FROM agent_tasks_projection WHERE task_id = ?",
                        (state.task_id,),
                    ).fetchone()
                    if current:
                        con.execute("COMMIT")
                        return self._row_to_state(current), []
                    if str(existing_event.payload.get("task_id", "")) != state.task_id:
                        raise RuntimeError("task create event conflicts with requested task identity")

                con.execute(
                    """
                    INSERT INTO agent_tasks_projection (
                        task_id, status, owner, lease_id, contract, context, checkpoint, receipts,
                        heartbeat_expires_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        state.task_id,
                        state.status.value,
                        state.owner,
                        state.lease_id,
                        json_dumps(state.contract.to_dict()),
                        context,
                        json_dumps(state.checkpoint.to_dict()),
                        json_dumps(state.verification_receipts),
                        state.heartbeat_expires_at,
                        state.created_at,
                        state.updated_at,
                    ),
                )
                self._refresh_task_search_index(con, state.task_id)
                if not existing:
                    appended = self.state_store.append_in_transaction(
                        con, event, strict_idempotency=True
                    )
                    if appended.error or appended.event is None:
                        raise RuntimeError(appended.error or "task creation append returned no persisted event")
                    if appended.duplicate:
                        raise RuntimeError("task projection/event idempotency mismatch")
                    if appended.event:
                        published.append(appended.event)
                con.execute("COMMIT")
                return state, published
            except Exception:
                try:
                    con.execute("ROLLBACK")
                except Exception:
                    pass
                raise
        return self._run_ordered_task_write(
            _do_commit, timeout_seconds=0.25
        )

    def _commit_update(
        self,
        current: TaskState,
        updated: TaskState,
        event: AgentEvent,
        *,
        allow_server_memory_refresh: bool = False,
    ) -> TaskState:
        """CAS-update projection and append its event/cursor in one transaction."""
        checkpoint = _preserve_checkpoint_memory_state(
            current.checkpoint.state_data,
            updated.checkpoint,
            allow_server_memory_refresh=allow_server_memory_refresh,
        )
        if checkpoint != updated.checkpoint:
            updated = replace(updated, checkpoint=checkpoint)
        if not self._db_path_available():
            raise RuntimeError("agent task storage is unavailable")
        expected_context = json_dumps({
            "repository_id": current.context.repository_id,
            "clone_id": current.context.clone_id,
            "worktree_id": current.context.worktree_id,
            "branch": current.context.branch,
            "task_id": current.context.task_id,
            "session_id": current.context.session_id,
        })
        context = json_dumps({
            "repository_id": updated.context.repository_id,
            "clone_id": updated.context.clone_id,
            "worktree_id": updated.context.worktree_id,
            "branch": updated.context.branch,
            "task_id": updated.context.task_id,
            "session_id": updated.context.session_id,
        })
        values = (
            updated.status.value,
            updated.owner,
            updated.lease_id,
            json_dumps(updated.contract.to_dict()),
            context,
            json_dumps(updated.checkpoint.to_dict()),
            json_dumps(updated.verification_receipts),
            updated.heartbeat_expires_at,
            updated.updated_at,
        )
        expected_values = (
            current.task_id,
            current.status.value,
            current.owner,
            current.lease_id,
            json_dumps(current.contract.to_dict()),
            expected_context,
            json_dumps(current.checkpoint.to_dict()),
            json_dumps(current.verification_receipts),
            current.heartbeat_expires_at,
            current.updated_at,
        )
        published: list[AgentEvent] = []

        def _do_commit(con: sqlite3.Connection) -> tuple[TaskState, list[AgentEvent]]:
            published.clear()
            try:
                con.execute("BEGIN IMMEDIATE")
                if event.idempotency_key:
                    existing = con.execute(
                        "SELECT stream_id, seq, event_id, kind, payload, idempotency_key, "
                        "correlation_id, actor, created_at FROM agent_events "
                        "WHERE stream_id = ? AND idempotency_key = ?",
                        (event.stream_id, event.idempotency_key),
                    ).fetchone()
                    if existing:
                        existing_event = AgentEvent.from_row(existing)
                        if existing_event.actor != event.actor:
                            raise ValueError("idempotency key was already used")
                        if (
                            existing_event.kind != event.kind
                            or dict(existing_event.payload) != dict(event.payload)
                            or existing_event.correlation_id != event.correlation_id
                        ):
                            raise ValueError(
                                "idempotency key was already used for a different event payload"
                            )
                        current_row = con.execute(
                            "SELECT * FROM agent_tasks_projection WHERE task_id = ?",
                            (current.task_id,),
                        ).fetchone()
                        if not current_row:
                            raise RuntimeError("task event exists without its durable projection")
                        replayed = self._row_to_state(current_row)
                        con.execute("COMMIT")
                        return replayed, []

                con.execute(
                    """
                    UPDATE agent_tasks_projection SET
                        status = ?, owner = ?, lease_id = ?, contract = ?, context = ?, checkpoint = ?,
                        receipts = ?, heartbeat_expires_at = ?, updated_at = ?
                    WHERE task_id = ? AND status = ? AND owner = ? AND lease_id = ? AND contract = ?
                      AND context = ? AND checkpoint = ? AND receipts = ? AND heartbeat_expires_at = ?
                      AND updated_at = ?
                    """,
                    (*values, *expected_values),
                )
                if con.execute("SELECT changes()").fetchone()[0] != 1:
                    raise ConcurrentTaskUpdateError(
                        f"Task {current.task_id} changed during transition; reload and retry"
                    )
                self._refresh_task_search_index(con, updated.task_id)
                appended = self.state_store.append_in_transaction(
                    con, event, strict_idempotency=True
                )
                if appended.error or appended.event is None:
                    raise RuntimeError(appended.error or "task transition append returned no persisted event")
                if appended.duplicate:
                    raise RuntimeError("task projection/event idempotency mismatch")
                if appended.event:
                    published.append(appended.event)
                con.execute("COMMIT")
                return updated, published
            except Exception:
                try:
                    con.execute("ROLLBACK")
                except Exception:
                    pass
                raise
        return self._run_ordered_task_write(
            _do_commit, timeout_seconds=0.25
        )

    def _row_to_state(self, row: tuple[Any, ...]) -> TaskState:
        (
            task_id,
            status_val,
            owner,
            lease_id,
            contract_raw,
            context_raw,
            checkpoint_raw,
            receipts_raw,
            heartbeat_expires_at,
            created_at,
            updated_at,
        ) = row
        # Persisted corruption is explicit; never manufacture task provenance.
        return TaskState.from_dict({
            "task_id": task_id,
            "status": status_val,
            "owner": owner,
            "lease_id": lease_id,
            "contract": json.loads(contract_raw),
            "context": json.loads(context_raw),
            "checkpoint": json.loads(checkpoint_raw),
            "verification_receipts": json.loads(receipts_raw),
            "heartbeat_expires_at": heartbeat_expires_at,
            "created_at": created_at,
            "updated_at": updated_at,
        })

    def curate_training_dataset(
        self,
        output_path: str,
        min_receipts: int = 1,
        format: str = "jsonl",
        *,
        repo_root: str | Path | None = None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        """Export verified completed tasks into structured fine-tuning / LoRA training dataset."""
        if task_id is not None and (not isinstance(task_id, str) or not task_id or task_id != task_id.strip() or "\x00" in task_id):
            raise ValueError("task_id must be a nonempty canonical string when supplied")
        if not isinstance(format, str) or format not in {"json", "jsonl"}:
            raise ValueError("format must be json or jsonl")
        scoped_root = Path(_canonical_repository_root(repo_root))
        tasks = [
            task for task in self.list_tasks(status=TaskStatus.COMPLETED, limit=5000)
            if _task_matches_scope(task, str(scoped_root), task_id)
        ]
        samples: list[dict[str, Any]] = []
        estimated_bytes = 0

        for t in tasks:
            if len(t.verification_receipts) < min_receipts:
                continue
            criteria_str = "\n".join(f"- {c}" for c in t.contract.acceptance_criteria) if t.contract.acceptance_criteria else "All tests pass"
            constraints_str = "\n".join(f"- {c}" for c in t.contract.constraints) if t.contract.constraints else "None"
            affected = ", ".join(t.checkpoint.affected_paths) if t.checkpoint.affected_paths else "repository"
            next_act = t.checkpoint.next_action or "Task completed and verified"
            receipts_list = list(t.verification_receipts.keys())

            instruction = f"Implement engineering task: {t.contract.goal}"
            input_text = f"Acceptance criteria:\n{criteria_str}\n\nConstraints:\n{constraints_str}"
            output_text = f"Action taken:\nModified {affected}.\nVerification receipts validated: {', '.join(receipts_list)}.\nOutcome: {next_act}"

            sample = {
                "instruction": instruction,
                "prompt": instruction,
                "input": input_text,
                "output": output_text,
                "task_id": t.task_id,
                "created_at": t.created_at,
                "status": t.status.value,
            }
            estimated_bytes += len(json_dumps(sample, ensure_ascii=False).encode("utf-8")) + 1
            if estimated_bytes > MAX_TRAINING_DATASET_BYTES:
                raise ValueError(
                    f"training dataset exceeds {MAX_TRAINING_DATASET_BYTES} byte limit"
                )
            samples.append(sample)

        requested_output = Path(str(output_path or "")).expanduser()
        if not str(output_path or "").strip():
            raise ValueError("output_path is required")
        if not requested_output.is_absolute():
            requested_output = scoped_root / requested_output
        out_file = requested_output.resolve(strict=False)
        if out_file == scoped_root or not out_file.is_relative_to(scoped_root):
            raise ValueError("output_path must remain inside repo_root")
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file = out_file.resolve(strict=False)
        if out_file == scoped_root or not out_file.is_relative_to(scoped_root):
            raise ValueError("output_path must remain inside repo_root")

        if format == "json":
            payload = json_dumps(samples, indent=2, ensure_ascii=False)
        else:
            payload = "".join(json_dumps(item, ensure_ascii=False) + "\n" for item in samples)
        if len(payload.encode("utf-8")) > MAX_TRAINING_DATASET_BYTES:
            raise ValueError(f"training dataset exceeds {MAX_TRAINING_DATASET_BYTES} byte limit")
        out_file.write_text(payload, encoding="utf-8")

        return {
            "success": True,
            "count": len(samples),
            "dataset_count": len(samples),
            "output_path": str(out_file),
            "format": format,
        }
