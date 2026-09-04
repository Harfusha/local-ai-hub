from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from .agent_events import AgentEvent, AgentStateStore
from .agent_identity import AgentScope, ScopeContext
from .sqlite_support import connect_sqlite, retry_busy


class CompletionGateError(RuntimeError):
    """Raised when task completion is attempted without verified criteria receipts."""


class InvalidTransitionError(ValueError):
    """Raised when an illegal task state transition is attempted."""


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "acceptance_criteria": list(self.acceptance_criteria),
            "scope": self.scope.value,
            "non_goals": list(self.non_goals),
            "constraints": list(self.constraints),
            "risk_profile": self.risk_profile,
            "slo_profile": dict(self.slo_profile),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> GoalContract:
        return cls(
            goal=str(data.get("goal", "")),
            acceptance_criteria=tuple(data.get("acceptance_criteria") or ()),
            scope=AgentScope(data.get("scope", AgentScope.TASK.value)),
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

    def to_dict(self) -> dict[str, Any]:
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
        }


class TaskStore:
    def __init__(
        self,
        state_store: AgentStateStore,
        *,
        default_heartbeat_ttl: float = 300.0,
    ) -> None:
        self.state_store = state_store
        self.default_heartbeat_ttl = float(default_heartbeat_ttl)
        self._init_projection_table()

    def _init_projection_table(self) -> None:
        if not self.state_store.enabled:
            return
        self.state_store._ensure_schema()
        con = connect_sqlite(self.state_store.db_path)
        try:
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
            con.commit()
        finally:
            con.close()

    def create(
        self,
        contract: GoalContract,
        context: ScopeContext,
        *,
        task_id: str | None = None,
        actor: str = "agent",
        idempotency_key: str = "",
    ) -> TaskState:
        t_id = task_id or f"task_{uuid.uuid4().hex[:12]}"
        now = time.time()
        initial_status = TaskStatus.PLANNED
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
            checkpoint=TaskCheckpoint(),
            verification_receipts={},
        )

        event = AgentEvent.create(
            stream_id=f"task:{t_id}",
            kind="task.created",
            payload=initial_state.to_dict(),
            idempotency_key=idempotency_key or f"create_{t_id}",
            actor=actor,
        )
        self.state_store.append(event)
        self._save_projection(initial_state)
        return initial_state

    def get(self, task_id: str) -> TaskState | None:
        if not self.state_store.enabled or not self.state_store.db_path.exists():
            return None
        self._init_projection_table()
        con = connect_sqlite(self.state_store.db_path)
        try:
            row = con.execute(
                """
                SELECT task_id, status, owner, lease_id, contract, context, checkpoint, receipts,
                       heartbeat_expires_at, created_at, updated_at
                FROM agent_tasks_projection
                WHERE task_id = ?
                """,
                (task_id,),
            ).fetchone()
            if not row:
                return None
            return self._row_to_state(row)
        finally:
            con.close()

    def list_tasks(self, status: TaskStatus | None = None, limit: int = 100) -> list[TaskState]:
        if not self.state_store.enabled or not self.state_store.db_path.exists():
            return []
        self._init_projection_table()
        con = connect_sqlite(self.state_store.db_path)
        try:
            if status is not None:
                cur = con.execute(
                    """
                    SELECT task_id, status, owner, lease_id, contract, context, checkpoint, receipts,
                           heartbeat_expires_at, created_at, updated_at
                    FROM agent_tasks_projection
                    WHERE status = ?
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (status.value, max(1, int(limit))),
                )
            else:
                cur = con.execute(
                    """
                    SELECT task_id, status, owner, lease_id, contract, context, checkpoint, receipts,
                           heartbeat_expires_at, created_at, updated_at
                    FROM agent_tasks_projection
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (max(1, int(limit)),),
                )
            return [self._row_to_state(row) for row in cur.fetchall()]
        finally:
            con.close()

    def count(self, status: TaskStatus | None = None) -> int:
        if not self.state_store.enabled or not self.state_store.db_path.exists():
            return 0
        self._init_projection_table()
        con = connect_sqlite(self.state_store.db_path)
        try:
            if status is not None:
                row = con.execute("SELECT COUNT(1) FROM agent_tasks_projection WHERE status = ?", (status.value,)).fetchone()
            else:
                row = con.execute("SELECT COUNT(1) FROM agent_tasks_projection").fetchone()
            return int(row[0]) if row else 0
        finally:
            con.close()

    def add_verification_receipt(self, task_id: str, criterion: str, receipt_id: str) -> TaskState:
        current = self.get(task_id)
        if not current:
            raise KeyError(f"Task {task_id} not found")
        new_receipts = dict(current.verification_receipts)
        new_receipts[criterion] = receipt_id
        updated = TaskState(
            task_id=current.task_id,
            status=current.status,
            contract=current.contract,
            context=current.context,
            owner=current.owner,
            lease_id=current.lease_id,
            created_at=current.created_at,
            updated_at=time.time(),
            heartbeat_expires_at=current.heartbeat_expires_at,
            checkpoint=current.checkpoint,
            verification_receipts=new_receipts,
        )
        self._save_projection(updated)
        return updated

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
            for criterion in current.contract.acceptance_criteria:
                if criterion not in current.verification_receipts:
                    raise CompletionGateError(
                        f"Cannot transition to COMPLETED: criterion '{criterion}' has no verified receipt"
                    )

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
        self.state_store.append(event)
        self._save_projection(updated)
        return updated

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
            self.state_store.append(event)
            self._save_projection(updated)
            return updated
        raise InvalidTransitionError(
            f"Cannot fail task {task_id} from {current.status.value}"
        )

    def checkpoint(
        self,
        task_id: str,
        checkpoint: TaskCheckpoint,
        *,
        actor: str = "agent",
        idempotency_key: str = "",
    ) -> TaskState:
        current = self.get(task_id)
        if not current:
            raise KeyError(f"Task {task_id} not found")

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
            idempotency_key=idempotency_key or f"chk_{task_id}_{int(now)}",
            actor=actor,
        )
        self.state_store.append(event)
        self._save_projection(updated)
        return updated

    def resume(self, task_id: str, *, actor: str = "agent", idempotency_key: str = "") -> TaskState:
        return self.transition(
            task_id,
            TaskStatus.ACTIVE,
            reason="resumed from checkpoint",
            actor=actor,
            idempotency_key=idempotency_key or f"resume_{task_id}_{int(time.time())}",
        )

    def reap_expired_heartbeats(self, now: float | None = None) -> list[str]:
        if not self.state_store.enabled or not self.state_store.db_path.exists():
            return []
        self._init_projection_table()
        current_time = float(time.time() if now is None else now)
        con = connect_sqlite(self.state_store.db_path)
        try:
            cur = con.execute(
                """
                SELECT task_id FROM agent_tasks_projection
                WHERE status = 'active' AND heartbeat_expires_at > 0 AND heartbeat_expires_at < ?
                """,
                (current_time,),
            )
            expired_ids = [row[0] for row in cur.fetchall()]
        finally:
            con.close()

        reaped: list[str] = []
        for t_id in expired_ids:
            try:
                self.transition(
                    t_id,
                    TaskStatus.ABANDONED,
                    reason="heartbeat expired",
                    actor="system",
                    idempotency_key=f"abandon_{t_id}_{int(current_time)}",
                )
                reaped.append(t_id)
            except Exception:
                pass
        return reaped

    def _save_projection(self, state: TaskState) -> None:
        if not self.state_store.enabled:
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
                        json.dumps(state.contract.to_dict()),
                        json.dumps({
                            "repository_id": state.context.repository_id,
                            "clone_id": state.context.clone_id,
                            "worktree_id": state.context.worktree_id,
                            "branch": state.context.branch,
                            "task_id": state.context.task_id,
                            "session_id": state.context.session_id,
                        }),
                        json.dumps(state.checkpoint.to_dict()),
                        json.dumps(state.verification_receipts),
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
        contract = GoalContract.from_dict(json.loads(contract_raw))
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
