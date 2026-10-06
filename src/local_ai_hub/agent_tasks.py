from __future__ import annotations

from .json_utils import dumps as json_dumps

import json
import sqlite3
import hashlib
import inspect
import math
import threading
import time
import unicodedata
import uuid
from contextlib import closing
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from .agent_events import AgentEvent, AgentStateStore
from .agent_identity import AgentScope, ScopeContext
from .sqlite_support import connect_sqlite, retry_busy

MAX_TASK_QUERY_SCAN_ROWS = 10_000


MAX_TRAINING_DATASET_BYTES = 16 * 1024 * 1024


class CompletionGateError(RuntimeError):
    """Raised when task completion is attempted without verified criteria receipts."""


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
        goal = str(self.goal or "").strip()
        if not goal:
            raise ValueError("task contract requires goal")
        object.__setattr__(self, "goal", goal)
        object.__setattr__(self, "description", str(self.description or "").strip())
        if not isinstance(self.scope, AgentScope):
            object.__setattr__(self, "scope", AgentScope.parse(self.scope))
        if not isinstance(self.acceptance_criteria, tuple):
            object.__setattr__(self, "acceptance_criteria", tuple(self.acceptance_criteria or ()))
        if not isinstance(self.non_goals, tuple):
            object.__setattr__(self, "non_goals", tuple(self.non_goals or ()))
        if not isinstance(self.constraints, tuple):
            object.__setattr__(self, "constraints", tuple(self.constraints or ()))

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
        explicit_goal = next(
            (data.get(key) for key in ("goal", "title", "summary", "intent", "task", "name") if data.get(key)),
            None,
        )
        goal_val = str(explicit_goal or data.get("description") or "").strip()
        description = str(data.get("description") or "").strip() if explicit_goal else ""
        if not goal_val:
            crit = data.get("acceptance_criteria")
            if crit and isinstance(crit, (list, tuple)) and len(crit) > 0:
                goal_val = f"Complete task: {crit[0]}"
        return cls(
            goal=goal_val,
            description=description,
            acceptance_criteria=tuple(data.get("acceptance_criteria") or ()),
            scope=AgentScope.parse(data.get("scope", AgentScope.TASK.value)),
            non_goals=tuple(data.get("non_goals") or ()),
            constraints=tuple(data.get("constraints") or ()),
            risk_profile=str(data.get("risk_profile", "normal")),
            slo_profile=dict(data.get("slo_profile") or {}),
        )


@dataclass(frozen=True)
class TaskCheckpoint:
    phase: str = ""
    next_action: str = ""
    affected_paths: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    state_data: dict[str, Any] = field(default_factory=dict)

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
    def from_dict(cls, data: Mapping[str, Any]) -> TaskCheckpoint:
        return cls(
            phase=str(data.get("phase", "")),
            next_action=str(data.get("next_action", "")),
            affected_paths=tuple(data.get("affected_paths") or ()),
            evidence_ids=tuple(data.get("evidence_ids") or ()),
            blockers=tuple(data.get("blockers") or ()),
            state_data=dict(data.get("state_data") or {}),
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

    @property
    def is_stale(self) -> bool:
        return bool(
            self.heartbeat_expires_at > 0
            and self.heartbeat_expires_at < time.time()
            and self.status not in {TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.FAILED, TaskStatus.ABANDONED}
        )

    def to_dict(self) -> dict[str, Any]:
        stale = self.is_stale
        return {
            "task_id": self.task_id,
            "status": self.status.value,
            "owner": self.owner,
            "lease_id": self.lease_id,
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


class TaskList(list[TaskState]):
    """List-compatible task page with an explicit bounded-query truncation signal."""

    def __init__(self, tasks: list[TaskState] | tuple[TaskState, ...] = (), *, query_truncated: bool = False) -> None:
        super().__init__(tasks)
        self.query_truncated = bool(query_truncated)


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


def _canonical_repository_root(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("repo_root is required")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ValueError("repo_root must be absolute")
    try:
        canonical = path.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("repo_root must resolve to an existing directory") from exc
    if not canonical.is_dir():
        raise ValueError("repo_root must resolve to an existing directory")
    return str(canonical)

def _tenant_scope_key(tenant: Any) -> str:
    value = str(tenant or "").strip()
    if not value:
        raise ValueError("authenticated tenant is required")
    return hashlib.sha256(f"agent-task-memory-tenant\\0{value}".encode("utf-8")).hexdigest()

def _task_scope_values(task: "TaskState") -> tuple[str, str]:
    state_data = task.checkpoint.state_data
    scope = state_data.get("_agent_task_scope")
    if not isinstance(scope, Mapping) or scope.get("version") != 1:
        return "", ""
    root = scope.get("repo_root")
    tenant_key = scope.get("tenant_key")
    try:
        canonical_root = _canonical_repository_root(root)
    except ValueError:
        return "", ""
    key = str(tenant_key or "").strip().lower()
    if len(key) != 64 or any(ch not in "0123456789abcdef" for ch in key):
        return "", ""
    return canonical_root, key

def _task_matches_scope(
    task: "TaskState", repo_root: str, tenant_key: str, task_id: str | None = None
) -> bool:
    if task_id and task.task_id != task_id:
        return False
    task_root, task_tenant_key = _task_scope_values(task)
    return task_root == repo_root and task_tenant_key == tenant_key

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
        self.memory_store: Any | None = None
        self.memory_context_compiler: Any | None = None
        self.incident_store: Any | None = None
        self._lock = threading.RLock()
        self._initialized = False
        self._init_projection_table()

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
            return str(Path(raw).expanduser().resolve(strict=False)).replace("\\", "/").casefold()
        except (OSError, RuntimeError, TypeError, ValueError):
            return ""

    @staticmethod
    def _memory_token_count(value: str) -> int:
        return max(1, len(value.strip()) // 4)

    def _task_memory_context(
        self,
        task_id: str,
        contract: GoalContract,
        context: ScopeContext,
        *,
        root_override: str = "",
        previous: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        compiler = self.memory_context_compiler
        memory_store = self.memory_store
        if compiler is None or memory_store is None:
            return None
        try:
            from .agent_context import ContextRequest
            from .trace_context import current as current_trace_context

            trace_tenant = str(current_trace_context().get("tenant", "") or "").strip()
            tenant = trace_tenant
            root = str(root_override or context.repository_id or "").strip()
            tenant_key = hashlib.sha256(
                f"agent-task-memory-tenant\\0{tenant}".encode("utf-8")
            ).hexdigest() if tenant else ""
            old_tenant_key = str((previous or {}).get("tenant_key", "") or "")
            warnings: list[dict[str, str]] = []
            if previous is not None and old_tenant_key and old_tenant_key != tenant_key:
                return {
                    "schema_version": 1,
                    "tenant_key": tenant_key,
                    "instruction": "Memory is advisory. Cite used memory IDs in the next checkpoint; otherwise record not_used_reason. Verify volatile facts against current source before relying on them.",
                    "items": [],
                    "warnings": [{"code": "memory_tenant_mismatch"}],
                    "estimated_tokens": 0,
                }

            request = ContextRequest(
                task_id=task_id,
                token_budget=512,
                root=root,
                tenant=tenant,
                session_id=context.session_id,
                clone_id=context.clone_id,
                worktree_id=context.worktree_id,
                branch=context.branch,
                repository_id=context.repository_id,
            )
            started = time.monotonic()
            compiled = compiler.compile(request)
            if time.monotonic() - started > 1.0:
                return {
                    "schema_version": 1,
                    "tenant_key": tenant_key,
                    "instruction": "Memory is advisory. Cite used memory IDs in the next checkpoint; otherwise record not_used_reason. Verify volatile facts against current source before relying on them.",
                    "items": [],
                    "warnings": [{"code": "memory_lookup_deadline_exceeded"}],
                    "estimated_tokens": 0,
                }

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
                        tenant=tenant or None,
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
            find_records = getattr(memory_store, "find", None)
            if callable(find_records):
                try:
                    expired_found = False
                    queries = [
                        {"scope": AgentScope.GLOBAL},
                        {
                            "scope": AgentScope.REPOSITORY,
                            "scope_id": root or None,
                            "root": root or None,
                            "tenant": tenant or None,
                        },
                    ]
                    for query in queries:
                        for status in ("active", "confirmed"):
                            records = find_records(
                                **query,
                                status=status,
                                include_expired=True,
                                semantic=False,
                                limit=8,
                            )
                            for record in records:
                                expires_at = getattr(record, "expires_at", None)
                                provenance = getattr(record, "provenance", {})
                                if expires_at is None or float(expires_at) > time.time():
                                    continue
                                if not isinstance(provenance, Mapping):
                                    continue
                                record_tenant = str(provenance.get("tenant", "") or "").strip()
                                if record_tenant and record_tenant != tenant:
                                    continue
                                record_root = provenance.get("root") or provenance.get("repository_root")
                                if record_root and root and self._canonical_memory_root(record_root) != self._canonical_memory_root(root):
                                    continue
                                if record_root and not root:
                                    continue
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
                            task_id=task_id,
                            tenant=tenant,
                            session_id=context.session_id,
                            clone_id=context.clone_id,
                            worktree_id=context.worktree_id,
                            branch=context.branch,
                            limit=20,
                        )
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
            for element in elements:
                if getattr(element, "source_kind", "") != "memory_record" or len(items) >= 5:
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
                    record_tenant = str(provenance.get("tenant", "") or "").strip()
                    if scope == "global":
                        if record_tenant and record_tenant != tenant:
                            continue
                    else:
                        if (tenant and record_tenant != tenant) or (not tenant and record_tenant):
                            continue
                        expected_scope_ids = {
                            "repository": root,
                            "clone": context.clone_id,
                            "worktree": context.worktree_id,
                            "branch": context.branch,
                            "task": context.task_id,
                            "session": context.session_id,
                        }
                        expected_scope_id = str(expected_scope_ids.get(str(scope), "") or "")
                        record_scope_id = str(getattr(record, "scope_id", "") or "")
                        record_root = provenance.get("root") or provenance.get("repository_root")
                        effective_scope_id = record_scope_id or str(record_root or "")
                        if not expected_scope_id or (
                            scope == "repository"
                            and self._canonical_memory_root(expected_scope_id)
                            != self._canonical_memory_root(effective_scope_id)
                        ) or (scope != "repository" and expected_scope_id != record_scope_id):
                            continue
                    record_root = provenance.get("root") or provenance.get("repository_root")
                    if record_root and (
                        not root
                        or self._canonical_memory_root(record_root) != self._canonical_memory_root(root)
                    ):
                        continue
                    if scope == "repository" and not root:
                        continue
                    content = str(getattr(element, "content", "") or "").strip()
                    remaining_tokens = token_budget - used_tokens
                    if not content or remaining_tokens <= 0:
                        break
                    max_chars = remaining_tokens * 4
                    if len(content) > max_chars:
                        content = content[:max_chars].rstrip()
                    item_tokens = self._memory_token_count(content)
                    if item_tokens > remaining_tokens:
                        continue
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
                    used_tokens += item_tokens
                except (AttributeError, TypeError, ValueError, OverflowError):
                    warnings.append({"code": "memory_record_invalid"})

            incident_store = self.incident_store
            if root and tenant and incident_store is not None:
                finder = getattr(incident_store, "find_negative_knowledge", None)
                if callable(finder):
                    try:
                        incidents = finder(contract.goal, limit=3, root=root, tenant=tenant)
                        for incident in incidents[:3]:
                            if not isinstance(incident, Mapping):
                                continue
                            incident_id = str(incident.get("incident_id", "") or "").strip()
                            provenance = incident.get("provenance")
                            if not incident_id or not isinstance(provenance, Mapping):
                                continue
                            if not provenance.get("repository_key") or not provenance.get("tenant_key"):
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
                                "scope": "repository+tenant",
                                "scope_id": "",
                                "status": "active",
                                "validity": {"updated_at": float(incident.get("updated_at", 0.0) or 0.0), "expires_at": None},
                                "confidence": float(incident.get("confidence", 0.0) or 0.0),
                                "volatile": True,
                                "provenance": dict(provenance),
                                "estimated_tokens": item_tokens,
                            })
                            used_tokens += item_tokens
                    except Exception:
                        warnings.append({"code": "negative_knowledge_unavailable"})
            if not items and not warnings:
                return None
            return {
                "schema_version": 1,
                "tenant_key": tenant_key,
                "instruction": instruction,
                "items": items,
                "warnings": warnings[:8],
                "estimated_tokens": used_tokens if items else 0,
            }
        except Exception:
            return {
                "schema_version": 1,
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
        items = memory_context.get("items")
        warnings = memory_context.get("warnings")
        if not isinstance(items, list) or (not items and not warnings):
            return
        audit = state_data.get("memory_audit")
        if not isinstance(audit, Mapping):
            raise CompletionGateError(
                "Cannot transition to COMPLETED: memory context requires checkpoint memory_audit"
            )
        available_ids = {
            str(item.get("id", ""))
            for item in items
            if isinstance(item, Mapping) and str(item.get("id", "")).strip()
        }
        used_ids = audit.get("used_ids", ())
        if not isinstance(used_ids, (list, tuple)) or any(not isinstance(value, str) for value in used_ids):
            raise CompletionGateError(
                "Cannot transition to COMPLETED: memory_audit.used_ids must be a list of IDs"
            )
        if not set(used_ids).issubset(available_ids):
            raise CompletionGateError(
                "Cannot transition to COMPLETED: memory_audit references unavailable memory IDs"
            )
        raw_not_used_reason = audit.get("not_used_reason", "")
        not_used_reason = raw_not_used_reason.strip() if isinstance(raw_not_used_reason, str) else ""
        if not used_ids and not not_used_reason:
            raise CompletionGateError(
                "Cannot transition to COMPLETED: record used memory IDs or not_used_reason in checkpoint"
            )
        volatile_used = {
            str(item.get("id", ""))
            for item in items
            if isinstance(item, Mapping) and item.get("volatile") and str(item.get("id", "")) in used_ids
        }
        source_checks = audit.get("source_checks", {})
        if volatile_used and not isinstance(source_checks, Mapping):
            raise CompletionGateError(
                "Cannot transition to COMPLETED: volatile memory requires source_checks"
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
                    f"Cannot transition to COMPLETED: volatile memory '{record_id}' lacks current-source check"
                )

    def set_verification_store(self, verification_store: Any) -> None:
        self.verification_store = verification_store

    def set_policy_engine(self, policy_engine: Any) -> None:
        self.policy_engine = policy_engine

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

    def _init_projection_table(self) -> None:
        if self._initialized or not self._db_path_available():
            return
        with self._lock:
            if self._initialized or not self._db_path_available():
                return
            self.state_store._ensure_schema()
            def _setup() -> None:
                with closing(connect_sqlite(self.state_store.db_path)) as con:
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
                    self._backfill_task_search_index(con)
                    con.commit()
            retry_busy(_setup, retries=5, base_delay_seconds=0.02)
            self._initialized = True

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
    ) -> TaskState:
        t_id = task_id or f"task_{uuid.uuid4().hex[:12]}"
        now = time.time()
        initial_status = TaskStatus.PLANNED
        initial_sd: dict[str, Any] = {}
        canonical_root = _canonical_repository_root(repo_root) if repo_root else ""
        try:
            from .trace_context import current as current_trace_context
            authenticated_tenant = str(current_trace_context().get("tenant", "") or "").strip()
        except Exception:
            authenticated_tenant = ""
        if canonical_root:
            initial_sd["repo_root"] = canonical_root
        if repository_revision:
            initial_sd["repository_revision"] = str(repository_revision).strip()

        if auto_worktree:
            try:
                from .process_utils import create_git_worktree
                r_root = repo_root or context.repository_id or "."
                if context.repository_id and Path(r_root).expanduser().resolve(strict=False) != Path(context.repository_id).expanduser().resolve(strict=False):
                    raise ValueError("task worktree repository does not match task context")
                worktree_ttl = 24 * 60 * 60.0
                worktree_expiry = now + worktree_ttl
                wt_res = create_git_worktree(
                    r_root,
                    branch_name=f"hub/task-{t_id}",
                    task_id=t_id,
                    owner=actor,
                    created_at=now,
                    ttl_seconds=worktree_ttl,
                    expires_at=worktree_expiry,
                )
                if wt_res.get("success"):
                    initial_sd["worktree"] = wt_res
                    if not canonical_root and wt_res.get("repo_root"):
                        canonical_root = _canonical_repository_root(wt_res["repo_root"])
                        initial_sd["repo_root"] = canonical_root
            except Exception:
                pass

        if canonical_root and authenticated_tenant:
            initial_sd["_agent_task_scope"] = {
                "version": 1,
                "repo_root": canonical_root,
                "tenant_key": _tenant_scope_key(authenticated_tenant),
            }

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

        event = AgentEvent.create(
            stream_id=f"task:{t_id}",
            kind="task.created",
            payload=initial_state.to_dict(),
            idempotency_key=idempotency_key or f"create_{t_id}",
            actor=actor,
        )
        return self._commit_create(initial_state, event)

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
    ) -> TaskList:
        if not self._db_path_available():
            return TaskList()
        self._init_projection_table()
        now = time.time()
        normalized_query = self._normalize_search_text(query or "")
        query_terms = [term for term in normalized_query.split() if term]
        page_size = max(1, int(limit))

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
                    where_clauses.append("NOT (heartbeat_expires_at > 0 AND heartbeat_expires_at < ?)")
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
                    ORDER BY updated_at DESC
                """
                if not query_terms:
                    cur = con.execute(sql + " LIMIT ?", (*params, page_size))
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
        if verifier is None:
            try:
                from .agent_verification import VerificationStore

                verifier = VerificationStore(self.state_store, task_store=self)
                self.verification_store = verifier
            except Exception as exc:
                raise CompletionGateError(
                    "Cannot transition to COMPLETED: verification evaluator is unavailable"
                ) from exc

        completion = getattr(verifier, "completion", None)
        if not callable(completion):
            raise CompletionGateError(
                "Cannot transition to COMPLETED: verification evaluator has no completion method"
            )
        try:
            parameters = inspect.signature(completion).parameters
            supports_kwargs = any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in parameters.values()
            )
            supports_project_rules = {
                "current_revision",
                "current_mutation_generation",
                "verification_rules",
                "configured_criteria",
            }.issubset(parameters)
            supports_project_binding = supports_kwargs or {
                "configured_commands",
                "project_config_digest",
                "configured_environment_sha256",
                "project_root",
            }.issubset(parameters)
            if supports_project_rules:
                if active_rules and not repository_revision:
                    raise CompletionGateError(
                        "Cannot transition to COMPLETED: trusted repository_revision is unavailable"
                    )
                if active_rules and not supports_project_binding:
                    raise CompletionGateError(
                        "Cannot transition to COMPLETED: verification evaluator does not bind project commands"
                    )
                project_binding_kwargs = (
                    {
                        "configured_commands": configured_commands,
                        "project_config_digest": project_config_digest,
                        "configured_environment_sha256": configured_environment_sha256,
                        "project_root": repo_root,
                    }
                    if supports_project_binding
                    else {}
                )
                result = completion(
                    task.task_id,
                    current_revision=repository_revision,
                    current_mutation_generation=mutation_generation,
                    verification_rules=verification_rules,
                    configured_criteria=configured_criteria,
                    **project_binding_kwargs,
                )
            else:
                if active_rules:
                    raise CompletionGateError(
                        "Cannot transition to COMPLETED: verification evaluator does not support project rules"
                    )
                legacy_kwargs = {}
                if repository_revision and ("current_revision" in parameters or supports_kwargs):
                    legacy_kwargs["current_revision"] = repository_revision
                result = completion(task.task_id, **legacy_kwargs)
        except CompletionGateError:
            raise
        except Exception as exc:
            receipt_ids = ", ".join(
                f"'{receipt_id}' for '{criterion}'"
                for criterion, receipt_id in task.verification_receipts.items()
            ) or "required criteria"
            raise CompletionGateError(
                f"Cannot transition to COMPLETED: verification storage could not validate {receipt_ids}: {exc}"
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
        _allow_server_memory_refresh: bool = False,
        _expected_reap: tuple[str, str, TaskStatus, float, float] | None = None,
    ) -> TaskState:
        current = self.get(task_id)
        if not current:
            raise KeyError(f"Task {task_id} not found")

        if _expected_reap is not None:
            expected_root, expected_tenant_key, expected_status, expected_expiry, deadline = _expected_reap
            if (
                not _task_matches_scope(current, expected_root, expected_tenant_key, task_id)
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
            if checkpoint is not None:
                return self.checkpoint(
                    task_id,
                    checkpoint,
                    actor=actor,
                    idempotency_key=idempotency_key,
                )
            if not idempotency_key:
                return current
            return self._replay_same_status_transition(
                task_id, target, reason=reason, actor=actor, idempotency_key=idempotency_key
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

        now = time.time()
        heartbeat = (
            now + self.default_heartbeat_ttl
            if target == TaskStatus.ACTIVE
            else (0.0 if target in (TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.ABANDONED, TaskStatus.FAILED) else current.heartbeat_expires_at)
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
    ) -> TaskState:
        current = self.get(task_id)
        if not current:
            raise KeyError(f"Task {task_id} not found")
        if current.status == TaskStatus.COMPLETED:
            return current
        if current.status == TaskStatus.PLANNED:
            current = self.transition(
                task_id,
                TaskStatus.ACTIVE,
                reason="auto-activated before completion",
                actor=actor,
                idempotency_key=f"{idempotency_key}_act" if idempotency_key else "",
            )
        if current.status in (TaskStatus.WAITING, TaskStatus.BLOCKED):
            current = self.transition(
                task_id,
                TaskStatus.ACTIVE,
                reason="auto-resumed before completion",
                actor=actor,
                idempotency_key=f"{idempotency_key}_res" if idempotency_key else "",
            )
        if current.status == TaskStatus.ACTIVE:
            current = self.transition(
                task_id,
                TaskStatus.VERIFYING,
                reason="auto-verifying before completion",
                actor=actor,
                idempotency_key=f"{idempotency_key}_ver" if idempotency_key else "",
            )
        if current.status != TaskStatus.VERIFYING:
            raise InvalidTransitionError(
                f"Cannot complete task {task_id} from {current.status.value}"
            )
        return self.transition(
            task_id,
            TaskStatus.COMPLETED,
            reason=reason,
            actor=actor,
            idempotency_key=idempotency_key,
        )

    def fail(
        self,
        task_id: str,
        *,
        reason: str = "failed by agent",
        actor: str = "agent",
        idempotency_key: str = "",
    ) -> TaskState:
        current = self.get(task_id)
        if not current:
            raise KeyError(f"Task {task_id} not found")
        if current.status == TaskStatus.FAILED:
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
        capture_files: bool = False,
        actor: str = "agent",
        idempotency_key: str = "",
    ) -> TaskState:
        current = self.get(task_id)
        if not current:
            raise KeyError(f"Task {task_id} not found")

        checkpoint = _preserve_checkpoint_memory_state(
            current.checkpoint.state_data, checkpoint
        )

        if capture_files or checkpoint.state_data.get("capture_files"):
            snaps = dict(checkpoint.state_data.get("file_snapshots") or {})
            for p_str in checkpoint.affected_paths:
                if p_str not in snaps:
                    try:
                        p = Path(p_str)
                        if p.exists() and p.is_file():
                            snaps[p_str] = p.read_text(encoding="utf-8", errors="ignore")
                        else:
                            snaps[p_str] = None
                    except Exception:
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

        if self.policy_engine and current.status == TaskStatus.ACTIVE:
            budget = self.policy_engine.get_budget(task_id)
            if budget.is_exhausted():
                return self.fail(
                    task_id,
                    reason=f"TASK_BUDGET_EXCEEDED: used_tokens={budget.used_tokens}/{budget.max_tokens}, used_compute_seconds={budget.used_compute_seconds:.1f}/{budget.max_compute_seconds:.1f}s",
                    actor="watchdog",
                )

        now = time.time()
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

        event = AgentEvent.create(
            stream_id=f"task:{task_id}",
            kind="task.checkpointed",
            payload=checkpoint.to_dict(),
            idempotency_key=idempotency_key or f"chk_{task_id}_{time.time_ns()}",
            actor=actor,
        )
        return self._commit_update(current, updated, event)

    def rollback(
        self,
        task_id: str,
        *,
        actor: str = "agent",
        idempotency_key: str = "",
        reason: str = "rolled back to previous checkpoint",
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

    def resume(self, task_id: str, *, actor: str = "agent", idempotency_key: str = "") -> TaskState:
        current = self.get(task_id)
        if not current:
            raise KeyError(f"Task {task_id} not found")
        resume_key = idempotency_key or f"resume_{task_id}_{int(time.time())}"
        if current.status == TaskStatus.ACTIVE and idempotency_key:
            return self.transition(
                task_id,
                TaskStatus.ACTIVE,
                reason="resumed from checkpoint",
                actor=actor,
                idempotency_key=resume_key,
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
            root_override=str(
                state_data.get("repo_root")
                or (
                    state_data.get("worktree", {}).get("repo_root", "")
                    if isinstance(state_data.get("worktree"), Mapping)
                    else ""
                )
                or current.context.repository_id
                or ""
            ),
            previous=state_data.get("memory_context") if isinstance(state_data.get("memory_context"), Mapping) else None,
        )
        if memory_context is not None:
            state_data["memory_context"] = memory_context
        elif "memory_context" in state_data:
            state_data["memory_context"] = {
                "schema_version": 1,
                "instruction": "Memory is advisory. Cite used memory IDs or record not_used_reason in the next checkpoint.",
                "items": [],
                "warnings": [{"code": "memory_context_unavailable"}],
            }
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
            _allow_server_memory_refresh=True,
        )

    def heartbeat(
        self,
        task_id: str,
        ttl_seconds: float | None = None,
        *,
        actor: str = "agent",
        idempotency_key: str = "",
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
    ) -> dict[str, Any]:
        task = self.get(task_id)
        if not task:
            return {"success": False, "error": f"Task {task_id} not found"}
        wt = task.checkpoint.state_data.get("worktree")
        if not isinstance(wt, dict) or not wt.get("worktree_path"):
            return {"success": True, "had_worktree": False}
        actor_value = str(actor or "").strip()
        if not actor_value or actor_value.lower() in {"http-default", "system", "admin", "*"}:
            return {"success": False, "error": "cleanup requires a non-reserved owner actor"}
        if actor_value != task.owner:
            return {"success": False, "error": "cleanup actor does not own task"}

        try:
            from .process_utils import get_git_worktree_ownership, remove_git_worktree

            task_id_value = str(wt.get("task_id", ""))
            owner_value = str(wt.get("owner", ""))
            repo_value = Path(str(wt.get("repo_root", ""))).expanduser().resolve(strict=False)
            worktree_id = str(wt.get("worktree_id", ""))
            branch = str(wt.get("branch", ""))
            worktree_path = Path(str(wt.get("worktree_path", ""))).expanduser()
            if not task_id_value or task_id_value != task.task_id:
                return {"success": False, "error": "worktree task identity mismatch"}
            if not owner_value or owner_value != task.owner:
                return {"success": False, "error": "worktree owner identity mismatch"}
            if not worktree_id or not branch or worktree_path.is_symlink():
                return {"success": False, "error": "worktree ownership metadata is incomplete"}
            expected_repo = Path(task.context.repository_id or ".").expanduser().resolve(strict=False)
            if repo_value != expected_repo:
                return {"success": False, "error": "worktree repository does not match task context"}
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
            ownership = get_git_worktree_ownership(repo_value, worktree_path)
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
            )
            if any(ownership.get(field) != wt.get(field) for field in expected_fields):
                return {"success": False, "error": "worktree ownership metadata was tampered"}

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
            )
            if not rm_res.get("success"):
                return {"success": False, "had_worktree": True, "cleanup": rm_res, "error": rm_res.get("error", "cleanup failed")}

            cleaned_at = time.time()
            cleaned_wt = {**wt, "cleanup_success": True, "cleaned_at": cleaned_at}
            state_data = {**task.checkpoint.state_data, "worktree": cleaned_wt}
            updated_checkpoint = TaskCheckpoint(
                phase=task.checkpoint.phase,
                next_action=task.checkpoint.next_action,
                affected_paths=task.checkpoint.affected_paths,
                evidence_ids=task.checkpoint.evidence_ids,
                blockers=task.checkpoint.blockers,
                state_data=state_data,
            )
            updated = self.checkpoint(
                task_id,
                updated_checkpoint,
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
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def reap_expired_heartbeats(
        self,
        now: float | None = None,
        *,
        auto_recover: bool = False,
        repo_root: str | Path | None = None,
        tenant: Any = None,
        task_id: str | None = None,
    ) -> list[str]:
        try:
            scoped_root = _canonical_repository_root(repo_root)
            tenant_key = _tenant_scope_key(tenant)
        except ValueError:
            return []
        if not self._db_path_available():
            return []
        self._init_projection_table()
        current_time = float(time.time() if now is None else now)
        def _fetch_expired() -> list[str]:
            with closing(connect_sqlite(self.state_store.db_path)) as con:
                cur = con.execute(
                    """
                    SELECT task_id FROM agent_tasks_projection
                    WHERE status IN ('planned', 'active', 'verifying', 'waiting', 'blocked')
                      AND heartbeat_expires_at > 0 AND heartbeat_expires_at < ?
                    """,
                    (current_time,),
                )
                return [row[0] for row in cur.fetchall()]

        expired_ids = retry_busy(_fetch_expired, retries=5, base_delay_seconds=0.02)

        reaped: list[str] = []
        for t_id in expired_ids:
            try:
                current = self.get(t_id)
                if (
                    current is None
                    or not _task_matches_scope(current, scoped_root, tenant_key, task_id)
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
                        tenant_key,
                        current.status,
                        current.heartbeat_expires_at,
                        current_time,
                    ),
                )
                reaped.append(t_id)
            except Exception:
                pass
        return reaped

    def recover_zombie_tasks(
        self,
        now: float | None = None,
        *,
        repo_root: str | Path | None = None,
        tenant: Any = None,
        task_id: str | None = None,
    ) -> list[str]:
        """Automatically detect timed-out zombie tasks and recover them to WAITING state for re-assignment."""
        return self.reap_expired_heartbeats(
            now=now,
            auto_recover=True,
            repo_root=repo_root,
            tenant=tenant,
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
        contract_data = json.loads(contract_raw)
        if not str(contract_data.get("goal", "")).strip():
            contract_data = dict(contract_data)
            legacy_title = str(contract_data.get("title", "")).strip()
            if legacy_title:
                contract_data["goal"] = legacy_title
            else:
                # V4 rejects empty goals for new contracts, but older persisted
                # projections may still contain one. Keep those tasks loadable and
                # make the missing intent explicit instead of returning blank
                # task context or failing the entire Agent OS startup.
                contract_data["goal"] = f"Legacy task contract: {task_id}"
        contract = GoalContract.from_dict(contract_data)
        ctx_data = json.loads(context_raw)
        context = ScopeContext(
            repository_id=ctx_data.get("repository_id", ""),
            clone_id=ctx_data.get("clone_id", ""),
            worktree_id=ctx_data.get("worktree_id", ""),
            branch=ctx_data.get("branch", ""),
            task_id=ctx_data.get("task_id", ""),
            session_id=ctx_data.get("session_id", ""),
        )
        checkpoint = TaskCheckpoint.from_dict(json.loads(checkpoint_raw))
        receipts = json.loads(receipts_raw) if receipts_raw else {}
        return TaskState(
            task_id=task_id,
            status=TaskStatus(status_val),
            contract=contract,
            context=context,
            owner=owner,
            lease_id=lease_id,
            created_at=created_at,
            updated_at=updated_at,
            heartbeat_expires_at=heartbeat_expires_at,
            checkpoint=checkpoint,
            verification_receipts=receipts,
        )

    def curate_training_dataset(
        self,
        output_path: str,
        min_receipts: int = 1,
        format: str = "jsonl",
        *,
        repo_root: str | Path | None = None,
        tenant: Any = None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        """Export verified completed tasks into structured fine-tuning / LoRA training dataset."""
        scoped_root = Path(_canonical_repository_root(repo_root))
        tenant_key = _tenant_scope_key(tenant)
        tasks = [
            task for task in self.list_tasks(status=TaskStatus.COMPLETED, limit=5000)
            if _task_matches_scope(task, str(scoped_root), tenant_key, task_id)
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

        if format.lower() == "json":
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
