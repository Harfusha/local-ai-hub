from __future__ import annotations

from .json_utils import dumps as json_dumps

import json
import threading
import time
import uuid
from contextlib import closing
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from .agent_events import AgentEvent, AgentStateStore
from .agent_identity import AgentScope, ScopeContext
from .sqlite_support import connect_sqlite, retry_busy

MAX_TASK_QUERY_SCAN_ROWS = 10_000


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

    def __post_init__(self) -> None:
        goal = str(self.goal or "").strip()
        if not goal:
            raise ValueError("task contract requires goal")
        object.__setattr__(self, "goal", goal)
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
            "acceptance_criteria": list(self.acceptance_criteria),
            "scope": scope_val,
            "non_goals": list(self.non_goals),
            "constraints": list(self.constraints),
            "risk_profile": self.risk_profile,
            "slo_profile": dict(self.slo_profile),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> GoalContract:
        goal_val = str(
            data.get("goal")
            or data.get("title")
            or data.get("description")
            or data.get("summary")
            or data.get("intent")
            or data.get("task")
            or data.get("name")
            or ""
        ).strip()
        if not goal_val:
            crit = data.get("acceptance_criteria")
            if crit and isinstance(crit, (list, tuple)) and len(crit) > 0:
                goal_val = f"Complete task: {crit[0]}"
        return cls(
            goal=goal_val,
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
        self._lock = threading.RLock()
        self._initialized = False
        self._init_projection_table()

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
    ) -> TaskState:
        t_id = task_id or f"task_{uuid.uuid4().hex[:12]}"
        now = time.time()
        initial_status = TaskStatus.PLANNED
        initial_sd: dict[str, Any] = {}

        if auto_worktree:
            try:
                from .process_utils import create_git_worktree
                r_root = repo_root or context.repository_id or "."
                wt_res = create_git_worktree(r_root, branch_name=f"hub/task-{t_id}")
                if wt_res.get("success"):
                    initial_sd["worktree"] = wt_res
            except Exception:
                pass

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
        normalized_query = (query or "").strip().casefold()
        page_size = max(1, int(limit))

        def matches_query(row: tuple[Any, ...]) -> bool:
            contract_data = json.loads(row[4] or "{}")
            checkpoint_data = json.loads(row[6] or "{}")
            search_values = [str(row[0] or ""), str(row[2] or "")]

            def add_text(value: Any) -> None:
                if isinstance(value, str):
                    search_values.append(value)
                elif isinstance(value, (list, tuple)):
                    for item in value:
                        add_text(item)
                elif value is not None:
                    search_values.append(str(value))

            for field in ("goal", "acceptance_criteria"):
                add_text(contract_data.get(field))
            for field in ("phase", "next_action", "affected_paths", "blockers"):
                add_text(checkpoint_data.get(field))
            return any(normalized_query in value.casefold() for value in search_values)

        def _fetch_tasks() -> tuple[list[Any], bool]:
            with closing(connect_sqlite(self.state_store.db_path)) as con:
                where_clauses: list[str] = []
                params: list[Any] = []
                if status is not None:
                    where_clauses.append("status = ?")
                    params.append(status.value)
                if not normalized_query and not include_stale:
                    where_clauses.append(
                        "(status IN (?, ?, ?, ?) OR heartbeat_expires_at <= 0 OR heartbeat_expires_at >= ?)"
                    )
                    params.extend((
                        TaskStatus.COMPLETED.value,
                        TaskStatus.CANCELLED.value,
                        TaskStatus.FAILED.value,
                        TaskStatus.ABANDONED.value,
                        now,
                    ))
                where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
                sql = f"""
                    SELECT task_id, status, owner, lease_id, contract, context, checkpoint, receipts,
                           heartbeat_expires_at, created_at, updated_at
                    FROM agent_tasks_projection
                    {where_sql}
                    ORDER BY updated_at DESC
                """
                if not normalized_query:
                    cur = con.execute(sql + " LIMIT ?", (*params, page_size))
                    return cur.fetchall(), False

                cur = con.execute(sql + " LIMIT ?", (*params, MAX_TASK_QUERY_SCAN_ROWS + 1))
                candidates = cur.fetchmany(MAX_TASK_QUERY_SCAN_ROWS + 1)
                query_truncated = len(candidates) > MAX_TASK_QUERY_SCAN_ROWS
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
        current = self.get(task_id)
        if not current:
            raise KeyError(f"Task {task_id} not found")
        if current.verification_receipts.get(criterion) == receipt_id:
            return current
        new_receipts = dict(current.verification_receipts)
        new_receipts[criterion] = receipt_id
        now = time.time()
        updated = TaskState(
            task_id=current.task_id,
            status=current.status,
            contract=current.contract,
            context=current.context,
            owner=current.owner,
            lease_id=current.lease_id,
            created_at=current.created_at,
            updated_at=now,
            heartbeat_expires_at=current.heartbeat_expires_at,
            checkpoint=current.checkpoint,
            verification_receipts=new_receipts,
        )
        event = AgentEvent.create(
            stream_id=f"task:{task_id}",
            kind="task.verified",
            payload={"criterion": criterion, "receipt_id": receipt_id},
            idempotency_key=f"ver_{task_id}_{criterion}_{receipt_id}",
            actor="verifier",
        )
        return self._commit_update(current, updated, event)

    def transition(
        self,
        task_id: str,
        target: TaskStatus,
        *,
        reason: str,
        actor: str,
        idempotency_key: str,
    ) -> TaskState:
        current = self.get(task_id)
        if not current:
            raise KeyError(f"Task {task_id} not found")

        if target == current.status:
            return current

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
            checkpoint=current.checkpoint,
            verification_receipts=current.verification_receipts,
        )

        event = AgentEvent.create(
            stream_id=f"task:{task_id}",
            kind="task.transitioned",
            payload={"from_status": current.status.value, "to_status": target.value, "reason": reason},
            idempotency_key=idempotency_key,
            actor=actor,
        )
        return self._commit_update(current, updated, event)

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
        return self.transition(
            task_id,
            TaskStatus.ACTIVE,
            reason="resumed from checkpoint",
            actor=actor,
            idempotency_key=idempotency_key or f"resume_{task_id}_{int(time.time())}",
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

    def cleanup_worktree(self, task_id: str, delete_branch: bool = True) -> dict[str, Any]:
        task = self.get(task_id)
        if not task:
            return {"success": False, "error": f"Task {task_id} not found"}
        wt = task.checkpoint.state_data.get("worktree")
        if not isinstance(wt, dict) or not wt.get("worktree_path"):
            return {"success": True, "had_worktree": False}
        try:
            from .process_utils import remove_git_worktree
            r_root = wt.get("repo_root", ".")
            w_path = wt.get("worktree_path")
            rm_res = remove_git_worktree(r_root, w_path, delete_branch=delete_branch)
            return {"success": True, "had_worktree": True, "cleanup": rm_res}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def reap_expired_heartbeats(self, now: float | None = None, *, auto_recover: bool = False) -> list[str]:
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
                target_status = TaskStatus.WAITING if auto_recover and current and current.status != TaskStatus.PLANNED else TaskStatus.ABANDONED
                reason = "heartbeat expired - auto-recovered to waiting" if auto_recover else "heartbeat expired"
                self.transition(
                    t_id,
                    target_status,
                    reason=reason,
                    actor="system",
                    idempotency_key=f"reap_{t_id}_{int(current_time)}",
                )
                reaped.append(t_id)
            except Exception:
                pass
        return reaped

    def recover_zombie_tasks(self, now: float | None = None) -> list[str]:
        """Automatically detect timed-out zombie tasks and recover them to WAITING state for re-assignment."""
        return self.reap_expired_heartbeats(now=now, auto_recover=True)

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
        """Atomically create initial projection and task.created event."""
        if not self.state_store.enabled:
            return state
        self._init_projection_table()
        payload = json_dumps(event.payload, separators=(",", ":"))
        payload_bytes = payload.encode("utf-8")
        if len(payload_bytes) > self.state_store.max_payload_bytes:
            raise ValueError(
                f"payload exceeds maximum allowed {self.state_store.max_payload_bytes} bytes (got {len(payload_bytes)})"
            )
        context = json_dumps({
            "repository_id": state.context.repository_id,
            "clone_id": state.context.clone_id,
            "worktree_id": state.context.worktree_id,
            "branch": state.context.branch,
            "task_id": state.context.task_id,
            "session_id": state.context.session_id,
        })

        def _do_commit() -> None:
            con = connect_sqlite(self.state_store.db_path, isolation_level=None, timeout_seconds=0.25)
            try:
                con.execute("BEGIN IMMEDIATE")
                seq_row = con.execute(
                    "SELECT COALESCE(MAX(seq), 0) + 1 FROM agent_events WHERE stream_id = ?",
                    (event.stream_id,),
                ).fetchone()
                seq = int(seq_row[0]) if seq_row else 1
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
                con.execute(
                    """
                    INSERT INTO agent_events (
                        stream_id, seq, event_id, kind, payload, idempotency_key,
                        correlation_id, actor, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.stream_id,
                        seq,
                        event.event_id,
                        event.kind,
                        payload,
                        event.idempotency_key,
                        event.correlation_id,
                        event.actor,
                        event.created_at,
                    ),
                )
                con.execute("COMMIT")
            except Exception:
                try:
                    con.execute("ROLLBACK")
                except Exception:
                    pass
                raise
            finally:
                con.close()
            self.state_store._publish(event.with_seq(seq))

        retry_busy(_do_commit, retries=5, base_delay_seconds=0.02)
        return state

    def _commit_update(
        self,
        current: TaskState,
        updated: TaskState,
        event: AgentEvent,
    ) -> TaskState:
        """Atomically compare task version, append event, and update projection."""
        if not self._db_path_available():
            raise RuntimeError("agent task storage is unavailable")
        payload = json_dumps(event.payload, separators=(",", ":"))
        payload_bytes = payload.encode("utf-8")
        if len(payload_bytes) > self.state_store.max_payload_bytes:
            raise ValueError(
                f"payload exceeds maximum allowed {self.state_store.max_payload_bytes} bytes (got {len(payload_bytes)})"
            )

        context = json_dumps({
            "repository_id": updated.context.repository_id,
            "clone_id": updated.context.clone_id,
            "worktree_id": updated.context.worktree_id,
            "branch": updated.context.branch,
            "task_id": updated.context.task_id,
            "session_id": updated.context.session_id,
        })
        expected_context = json_dumps({
            "repository_id": current.context.repository_id,
            "clone_id": current.context.clone_id,
            "worktree_id": current.context.worktree_id,
            "branch": current.context.branch,
            "task_id": current.context.task_id,
            "session_id": current.context.session_id,
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

        def _do_commit() -> None:
            con = connect_sqlite(self.state_store.db_path, isolation_level=None, timeout_seconds=0.25)
            try:
                con.execute("BEGIN IMMEDIATE")
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
                if event.idempotency_key:
                    existing_ev = con.execute(
                        "SELECT seq FROM agent_events WHERE stream_id = ? AND idempotency_key = ?",
                        (event.stream_id, event.idempotency_key),
                    ).fetchone()
                    if existing_ev:
                        con.execute("COMMIT")
                        return
                seq_row = con.execute(
                    "SELECT COALESCE(MAX(seq), 0) + 1 FROM agent_events WHERE stream_id = ?",
                    (event.stream_id,),
                ).fetchone()
                seq = int(seq_row[0]) if seq_row else 1
                con.execute(
                    """
                    INSERT INTO agent_events (
                        stream_id, seq, event_id, kind, payload, idempotency_key,
                        correlation_id, actor, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.stream_id,
                        seq,
                        event.event_id,
                        event.kind,
                        payload,
                        event.idempotency_key,
                        event.correlation_id,
                        event.actor,
                        event.created_at,
                    ),
                )
                con.execute("COMMIT")
            except Exception:
                try:
                    con.execute("ROLLBACK")
                except Exception:
                    pass
                raise
            finally:
                con.close()
            self.state_store._publish(event.with_seq(seq))

        retry_busy(_do_commit, retries=5, base_delay_seconds=0.02)
        return updated

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
            # V4 rejects empty goals for new contracts, but older persisted
            # projections may still contain one. Keep those tasks loadable and
            # make the missing intent explicit instead of returning blank
            # task context or failing the entire Agent OS startup.
            contract_data = dict(contract_data)
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
    ) -> dict[str, Any]:
        """Export verified completed tasks into structured fine-tuning / LoRA training dataset."""
        tasks = self.list_tasks(status=TaskStatus.COMPLETED, limit=5000)
        samples: list[dict[str, Any]] = []

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

            samples.append({
                "instruction": instruction,
                "prompt": instruction,
                "input": input_text,
                "output": output_text,
                "task_id": t.task_id,
                "created_at": t.created_at,
                "status": t.status.value,
            })

        out_file = Path(output_path).expanduser().resolve(strict=False)
        out_file.parent.mkdir(parents=True, exist_ok=True)

        if format.lower() == "json":
            out_file.write_text(json_dumps(samples, indent=2, ensure_ascii=False), encoding="utf-8")
        else:
            with out_file.open("w", encoding="utf-8") as f:
                for item in samples:
                    f.write(json_dumps(item, ensure_ascii=False) + "\n")

        return {
            "success": True,
            "count": len(samples),
            "dataset_count": len(samples),
            "output_path": str(out_file),
            "format": format,
        }
