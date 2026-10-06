from __future__ import annotations

from .json_utils import dumps as json_dumps

import json
import threading
import time
import uuid
from contextlib import closing
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from .agent_events import AgentEvent, AgentStateStore
from .agent_memory import ApprovalRequiredError
from .sqlite_support import connect_sqlite, retry_busy


class CandidateStatus(str, Enum):
    CANDIDATE = "candidate"
    REPLAY_PASSED = "replay_passed"
    SHADOW_PASSED = "shadow_passed"
    CANARY_PASSED = "canary_passed"
    APPROVED = "approved"
    PROMOTED = "promoted"
    ROLLED_BACK = "rolled_back"
    REJECTED = "rejected"


@dataclass(frozen=True)
class SLOObservation:
    latency_ms: float = 0.0
    success: bool = True
    cost: float = 0.0
    error_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "latency_ms": self.latency_ms,
            "success": self.success,
            "cost": self.cost,
            "error_count": self.error_count,
        }


@dataclass(frozen=True)
class RollbackTrigger:
    candidate_id: str
    action: str = "rollback"
    reason: str = ""
    restored_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "action": self.action,
            "reason": self.reason,
            "restored_version": self.restored_version,
        }


@dataclass(frozen=True)
class PromotionDecision:
    candidate_id: str
    promoted: bool
    approver: str
    version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "promoted": self.promoted,
            "approver": self.approver,
            "version": self.version,
        }


@dataclass(frozen=True)
class ImprovementCandidate:
    candidate_id: str
    name: str
    baseline_version: str
    candidate_version: str
    status: CandidateStatus = CandidateStatus.CANDIDATE
    slo_thresholds: dict[str, float] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)
    approver: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0

    @classmethod
    def create(
        cls,
        name: str,
        baseline_version: str,
        candidate_version: str,
        slo_thresholds: dict[str, float] | None = None,
        metrics: dict[str, float] | None = None,
    ) -> ImprovementCandidate:
        now = time.time()
        return cls(
            candidate_id=f"cand_{uuid.uuid4().hex[:12]}",
            name=name,
            baseline_version=baseline_version,
            candidate_version=candidate_version,
            status=CandidateStatus.CANDIDATE,
            slo_thresholds=dict(slo_thresholds or {}),
            metrics=dict(metrics or {}),
            approver="",
            created_at=now,
            updated_at=now,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "name": self.name,
            "baseline_version": self.baseline_version,
            "candidate_version": self.candidate_version,
            "status": self.status.value,
            "slo_thresholds": dict(self.slo_thresholds),
            "metrics": dict(self.metrics),
            "approver": self.approver,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ImprovementCandidate:
        return cls(
            candidate_id=str(data["candidate_id"]),
            name=str(data["name"]),
            baseline_version=str(data["baseline_version"]),
            candidate_version=str(data["candidate_version"]),
            status=CandidateStatus(data["status"]),
            slo_thresholds={k: float(v) for k, v in (data.get("slo_thresholds") or {}).items()},
            metrics={k: float(v) for k, v in (data.get("metrics") or {}).items()},
            approver=str(data.get("approver", "")),
            created_at=float(data.get("created_at", 0.0)),
            updated_at=float(data.get("updated_at", 0.0)),
        )


class LearningStore:
    def __init__(self, state_store: AgentStateStore) -> None:
        self.state_store = state_store
        self._lock = threading.RLock()
        self._initialized = False
        self._init_table()

    def _init_table(self) -> None:
        if self._initialized or not self.state_store.enabled:
            return
        with self._lock:
            if self._initialized or not self.state_store.enabled:
                return
            self.state_store._ensure_schema()
            def _setup() -> None:
                with closing(connect_sqlite(self.state_store.db_path)) as con:
                    con.execute(
                        """
                        CREATE TABLE IF NOT EXISTS agent_learning_candidates (
                            candidate_id TEXT PRIMARY KEY,
                            name TEXT NOT NULL,
                            baseline_version TEXT NOT NULL,
                            candidate_version TEXT NOT NULL,
                            status TEXT NOT NULL,
                            slo_thresholds TEXT NOT NULL,
                            metrics TEXT NOT NULL,
                            approver TEXT NOT NULL,
                            created_at REAL NOT NULL,
                            updated_at REAL NOT NULL
                        );
                        """
                    )
                    con.commit()
            retry_busy(_setup, retries=5, base_delay_seconds=0.02)
            self._initialized = True

    def create_candidate(self, candidate: ImprovementCandidate) -> ImprovementCandidate:
        self._init_table()
        event = AgentEvent.create(
            stream_id=f"learning:{candidate.candidate_id}",
            kind="learning.candidate_created",
            payload=candidate.to_dict(),
            idempotency_key=f"cand_create_{candidate.candidate_id}",
            actor="agent",
        )
        self.state_store.append(event)
        self._save(candidate)
        return candidate

    def advance(self, candidate_id: str, new_status: CandidateStatus) -> ImprovementCandidate:
        current = self.get(candidate_id)
        if not current:
            raise KeyError(f"Candidate {candidate_id} not found")
        if current.status in (CandidateStatus.ROLLED_BACK, CandidateStatus.REJECTED):
            raise ValueError(f"Cannot advance candidate in terminal status '{current.status.value}'")

        updated = ImprovementCandidate(
            candidate_id=current.candidate_id,
            name=current.name,
            baseline_version=current.baseline_version,
            candidate_version=current.candidate_version,
            status=new_status,
            slo_thresholds=current.slo_thresholds,
            metrics=current.metrics,
            approver=current.approver,
            created_at=current.created_at,
            updated_at=time.time(),
        )
        event = AgentEvent.create(
            stream_id=f"learning:{candidate_id}",
            kind="learning.advanced",
            payload={"status": new_status.value},
            idempotency_key=f"adv_{candidate_id}_{new_status.value}",
            actor="agent",
        )
        self.state_store.append(event)
        self._save(updated)
        return updated

    def promote(self, candidate_id: str, *, approver: str) -> PromotionDecision:
        current = self.get(candidate_id)
        if not current:
            raise KeyError(f"Candidate {candidate_id} not found")
        if current.status in (CandidateStatus.ROLLED_BACK, CandidateStatus.REJECTED):
            raise ValueError(f"Cannot promote candidate in terminal status '{current.status.value}'")

        if approver != "user":
            raise ApprovalRequiredError(
                "governed learning promotion strictly requires explicit human user approval"
            )

        promoted = ImprovementCandidate(
            candidate_id=current.candidate_id,
            name=current.name,
            baseline_version=current.baseline_version,
            candidate_version=current.candidate_version,
            status=CandidateStatus.PROMOTED,
            slo_thresholds=current.slo_thresholds,
            metrics=current.metrics,
            approver=approver,
            created_at=current.created_at,
            updated_at=time.time(),
        )
        event = AgentEvent.create(
            stream_id=f"learning:{candidate_id}",
            kind="learning.promoted",
            payload={"approver": approver, "version": promoted.candidate_version},
            idempotency_key=f"prom_{candidate_id}",
            actor=approver,
        )
        self.state_store.append(event)
        self._save(promoted)
        return PromotionDecision(
            candidate_id=candidate_id,
            promoted=True,
            approver=approver,
            version=promoted.candidate_version,
        )

    def observe(self, candidate_id: str, observation: SLOObservation) -> RollbackTrigger | None:
        current = self.get(candidate_id)
        if not current or current.status != CandidateStatus.PROMOTED:
            return None

        # Check thresholds
        max_latency = current.slo_thresholds.get("max_latency_ms")
        if max_latency is not None and observation.latency_ms > max_latency:
            return self._rollback(
                current,
                f"latency {observation.latency_ms:.1f}ms breached SLO max {max_latency:.1f}ms",
            )

        min_success = current.slo_thresholds.get("min_success_rate")
        if min_success is not None and not observation.success:
            return self._rollback(
                current,
                f"observed failure violated min_success_rate SLO {min_success:.2f}",
            )

        return None

    def _rollback(self, candidate: ImprovementCandidate, reason: str) -> RollbackTrigger:
        rolled_back = ImprovementCandidate(
            candidate_id=candidate.candidate_id,
            name=candidate.name,
            baseline_version=candidate.baseline_version,
            candidate_version=candidate.candidate_version,
            status=CandidateStatus.ROLLED_BACK,
            slo_thresholds=candidate.slo_thresholds,
            metrics=candidate.metrics,
            approver=candidate.approver,
            created_at=candidate.created_at,
            updated_at=time.time(),
        )
        event = AgentEvent.create(
            stream_id=f"learning:{candidate.candidate_id}",
            kind="learning.rolled_back",
            payload={"reason": reason, "restored_version": candidate.baseline_version},
            idempotency_key=f"rb_{candidate.candidate_id}_{int(time.time())}",
            actor="system",
        )
        self.state_store.append(event)
        self._save(rolled_back)
        return RollbackTrigger(
            candidate_id=candidate.candidate_id,
            action="rollback",
            reason=reason,
            restored_version=candidate.baseline_version,
        )

    def get(self, candidate_id: str) -> ImprovementCandidate | None:
        if not self.state_store.enabled or not self.state_store.db_path.exists():
            return None
        self._init_table()
        def _do_get() -> Any:
            with closing(connect_sqlite(self.state_store.db_path)) as con:
                return con.execute(
                    """
                    SELECT candidate_id, name, baseline_version, candidate_version, status,
                           slo_thresholds, metrics, approver, created_at, updated_at
                    FROM agent_learning_candidates
                    WHERE candidate_id = ?
                    """,
                    (candidate_id,),
                ).fetchone()
        row = retry_busy(_do_get, retries=5, base_delay_seconds=0.02)
        if not row:
            return None
        return self._row_to_candidate(row)

    def list_candidates(self, limit: int = 100) -> list[ImprovementCandidate]:
        if not self.state_store.enabled or not self.state_store.db_path.exists():
            return []
        self._init_table()
        def _do_list() -> list[Any]:
            with closing(connect_sqlite(self.state_store.db_path)) as con:
                cur = con.execute(
                    """
                    SELECT candidate_id, name, baseline_version, candidate_version, status,
                           slo_thresholds, metrics, approver, created_at, updated_at
                    FROM agent_learning_candidates
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (max(1, int(limit)),),
                )
                return cur.fetchall()
        rows = retry_busy(_do_list, retries=5, base_delay_seconds=0.02)
        return [self._row_to_candidate(r) for r in rows]

    def _save(self, candidate: ImprovementCandidate) -> None:
        if not self.state_store.enabled:
            return
        self._init_table()

        def _do_save() -> None:
            con = connect_sqlite(self.state_store.db_path, isolation_level=None)
            try:
                con.execute("BEGIN IMMEDIATE")
                con.execute(
                    """
                    INSERT INTO agent_learning_candidates (
                        candidate_id, name, baseline_version, candidate_version,
                        status, slo_thresholds, metrics, approver, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(candidate_id) DO UPDATE SET
                        status = excluded.status,
                        slo_thresholds = excluded.slo_thresholds,
                        metrics = excluded.metrics,
                        approver = excluded.approver,
                        updated_at = excluded.updated_at
                    """,
                    (
                        candidate.candidate_id,
                        candidate.name,
                        candidate.baseline_version,
                        candidate.candidate_version,
                        candidate.status.value,
                        json_dumps(candidate.slo_thresholds),
                        json_dumps(candidate.metrics),
                        candidate.approver,
                        candidate.created_at,
                        candidate.updated_at,
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

    def _row_to_candidate(self, row: tuple[Any, ...]) -> ImprovementCandidate:
        (
            candidate_id,
            name,
            baseline_version,
            candidate_version,
            status_val,
            thresholds_raw,
            metrics_raw,
            approver,
            created_at,
            updated_at,
        ) = row
        return ImprovementCandidate(
            candidate_id=candidate_id,
            name=name,
            baseline_version=baseline_version,
            candidate_version=candidate_version,
            status=CandidateStatus(status_val),
            slo_thresholds=json.loads(thresholds_raw) if thresholds_raw else {},
            metrics=json.loads(metrics_raw) if metrics_raw else {},
            approver=approver,
            created_at=float(created_at),
            updated_at=float(updated_at),
        )
