from __future__ import annotations

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
        self.state_store.append(event)
        self._save_projection(initial_state)
        return initial_state

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

    def list_tasks(self, status: TaskStatus | None = None, limit: int = 100) -> list[TaskState]:
        if not self._db_path_available():
            return []
        self._init_projection_table()
        def _fetch_tasks() -> list[Any]:
            with closing(connect_sqlite(self.state_store.db_path)) as con:
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
                return cur.fetchall()

        rows = retry_busy(_fetch_tasks, retries=5, base_delay_seconds=0.02)
        return [self._row_to_state(row) for row in rows]

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
        self.state_store.append(event)
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
            now_check = time.time()
            for criterion in current.contract.acceptance_criteria:
                if criterion not in current.verification_receipts:
                    raise CompletionGateError(
                        f"Cannot transition to COMPLETED: criterion '{criterion}' has no verified receipt"
                    )
                rcpt_id = current.verification_receipts[criterion]
                if self.state_store.enabled and self.state_store.db_path.exists():
                    try:
                        with closing(connect_sqlite(self.state_store.db_path)) as con:
                            row = con.execute(
                                "SELECT passed, expires_at FROM agent_verification_receipts WHERE receipt_id = ?",
                                (rcpt_id,),
                            ).fetchone()
                            if row is not None:
                                passed, expires_at = bool(row[0]), row[1]
                                if not passed:
                                    raise CompletionGateError(
                                        f"Cannot transition to COMPLETED: receipt '{rcpt_id}' for criterion '{criterion}' is marked failed"
                                    )
                                if expires_at is not None and float(expires_at) < now_check:
                                    raise CompletionGateError(
                                        f"Cannot transition to COMPLETED: receipt '{rcpt_id}' for criterion '{criterion}' is expired (stale)"
                                    )
                    except CompletionGateError:
                        raise
                    except Exception:
                        pass

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
        self.state_store.append(event)
        self._save_projection(updated)
        return updated

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
        self.state_store.append(event)
        self._save_projection(updated)
        return updated

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
                    WHERE status IN ('active', 'verifying', 'waiting', 'blocked')
                      AND heartbeat_expires_at > 0 AND heartbeat_expires_at < ?
                    """,
                    (current_time,),
                )
                return [row[0] for row in cur.fetchall()]

        expired_ids = retry_busy(_fetch_expired, retries=5, base_delay_seconds=0.02)

        reaped: list[str] = []
        for t_id in expired_ids:
            try:
                target_status = TaskStatus.WAITING if auto_recover else TaskStatus.ABANDONED
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
            out_file.write_text(json.dumps(samples, indent=2, ensure_ascii=False), encoding="utf-8")
        else:
            with out_file.open("w", encoding="utf-8") as f:
                for item in samples:
                    f.write(json.dumps(item, ensure_ascii=False) + "\n")

        return {
            "success": True,
            "count": len(samples),
            "dataset_count": len(samples),
            "output_path": str(out_file),
            "format": format,
        }
