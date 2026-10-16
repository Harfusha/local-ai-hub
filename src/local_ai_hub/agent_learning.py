from __future__ import annotations

from .json_utils import dumps as json_dumps

import json
import logging
import math
import sqlite3
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

LOGGER = logging.getLogger(__name__)


def _safe_float(val: Any, default: float = 0.0) -> float:
    if isinstance(val, bool):
        return default
    try:
        f = float(val)
        return f if math.isfinite(f) else default
    except (ValueError, TypeError, OverflowError):
        return default


def _safe_int(val: Any, default: int = 0) -> int:
    if isinstance(val, bool):
        return default
    try:
        return int(val)
    except (ValueError, TypeError, OverflowError):
        return default


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

    def __post_init__(self) -> None:
        lat = max(0.0, _safe_float(self.latency_ms, 0.0))
        c = max(0.0, _safe_float(self.cost, 0.0))
        ec = max(0, _safe_int(self.error_count, 0))
        object.__setattr__(self, "latency_ms", lat)
        object.__setattr__(self, "success", self.success is True)
        object.__setattr__(self, "cost", c)
        object.__setattr__(self, "error_count", ec)

    def is_successful(self) -> bool:
        return self.success and self.error_count == 0

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

    def __post_init__(self) -> None:
        cid = str(self.candidate_id or "").replace("\x00", "").strip()
        act = str(self.action or "rollback").replace("\x00", "").strip()
        rsn = str(self.reason or "").replace("\x00", "").strip()
        rv = str(self.restored_version or "").replace("\x00", "").strip()
        object.__setattr__(self, "candidate_id", cid)
        object.__setattr__(self, "action", act)
        object.__setattr__(self, "reason", rsn)
        object.__setattr__(self, "restored_version", rv)

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

    def __post_init__(self) -> None:
        cid = str(self.candidate_id or "").replace("\x00", "").strip()
        app = str(self.approver or "").replace("\x00", "").strip()
        ver = str(self.version or "").replace("\x00", "").strip()
        object.__setattr__(self, "candidate_id", cid)
        object.__setattr__(self, "promoted", self.promoted is True)
        object.__setattr__(self, "approver", app)
        object.__setattr__(self, "version", ver)

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

    def __post_init__(self) -> None:
        cid = str(self.candidate_id or "").replace("\x00", "").strip()
        nm = str(self.name or "").replace("\x00", "").strip()
        bv = str(self.baseline_version or "").replace("\x00", "").strip()
        cv = str(self.candidate_version or "").replace("\x00", "").strip()
        st = self.status
        if isinstance(st, str):
            try:
                st = CandidateStatus(st)
            except ValueError:
                st = CandidateStatus.CANDIDATE
        elif not isinstance(st, CandidateStatus):
            st = CandidateStatus.CANDIDATE

        thresh: dict[str, float] = {}
        if isinstance(self.slo_thresholds, Mapping) and not isinstance(self.slo_thresholds, bool):
            for k, v in self.slo_thresholds.items():
                thresh[str(k).replace("\x00", "").strip()] = _safe_float(v, 0.0)

        mets: dict[str, float] = {}
        if isinstance(self.metrics, Mapping) and not isinstance(self.metrics, bool):
            for k, v in self.metrics.items():
                mets[str(k).replace("\x00", "").strip()] = _safe_float(v, 0.0)

        app = str(self.approver or "").replace("\x00", "").strip()
        ca = max(0.0, _safe_float(self.created_at, 0.0))
        ua = max(0.0, _safe_float(self.updated_at, 0.0))

        object.__setattr__(self, "candidate_id", cid)
        object.__setattr__(self, "name", nm)
        object.__setattr__(self, "baseline_version", bv)
        object.__setattr__(self, "candidate_version", cv)
        object.__setattr__(self, "status", st)
        object.__setattr__(self, "slo_thresholds", thresh)
        object.__setattr__(self, "metrics", mets)
        object.__setattr__(self, "approver", app)
        object.__setattr__(self, "created_at", ca)
        object.__setattr__(self, "updated_at", ua)

    def is_promoted(self) -> bool:
        return self.status == CandidateStatus.PROMOTED

    def is_terminal(self) -> bool:
        return self.status in (CandidateStatus.ROLLED_BACK, CandidateStatus.REJECTED)

    def can_advance(self) -> bool:
        return not self.is_terminal()

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
        if not isinstance(data, Mapping) or isinstance(data, bool):
            raise TypeError("improvement candidate data must be a mapping")
        required = (
            "candidate_id",
            "name",
            "baseline_version",
            "candidate_version",
            "status",
            "slo_thresholds",
            "metrics",
            "approver",
            "created_at",
            "updated_at",
        )
        missing = [field_name for field_name in required if field_name not in data]
        if missing:
            raise ValueError(f"improvement candidate is missing required fields: {', '.join(missing)}")

        def _text(field_name: str, *, allow_empty: bool = False) -> str:
            value = data[field_name]
            if not isinstance(value, str):
                raise TypeError(f"{field_name} must be a string")
            if "\x00" in value or value != value.strip():
                raise ValueError(f"{field_name} must be canonical text")
            if not allow_empty and not value:
                raise ValueError(f"{field_name} cannot be empty")
            return value

        def _finite_number(value: Any, field_name: str) -> float:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{field_name} must be a finite number")
            try:
                number = float(value)
            except (OverflowError, ValueError) as exc:
                raise ValueError(f"{field_name} must be a finite number") from exc
            if not math.isfinite(number):
                raise ValueError(f"{field_name} must be a finite number")
            return number

        status_raw = data["status"]
        if not isinstance(status_raw, str):
            raise TypeError("status must be a canonical CandidateStatus string")
        try:
            status = CandidateStatus(status_raw)
        except ValueError as exc:
            raise ValueError("status must be a canonical CandidateStatus value") from exc

        def _numeric_mapping(field_name: str) -> dict[str, float]:
            raw = data[field_name]
            if not isinstance(raw, Mapping) or isinstance(raw, bool):
                raise TypeError(f"{field_name} must be a mapping of strings to finite numbers")
            result: dict[str, float] = {}
            for key, value in raw.items():
                if not isinstance(key, str) or not key or "\x00" in key or key != key.strip():
                    raise ValueError(f"{field_name} keys must be nonempty canonical strings")
                result[key] = _finite_number(value, f"{field_name}.{key}")
            return result

        candidate_id = _text("candidate_id")
        name = _text("name")
        baseline_version = _text("baseline_version")
        candidate_version = _text("candidate_version")
        approver = _text("approver", allow_empty=True)
        slo_dict = _numeric_mapping("slo_thresholds")
        mets_dict = _numeric_mapping("metrics")
        created_at = _finite_number(data["created_at"], "created_at")
        updated_at = _finite_number(data["updated_at"], "updated_at")
        if created_at < 0 or updated_at < 0:
            raise ValueError("candidate timestamps cannot be negative")
        return cls(
            candidate_id=candidate_id,
            name=name,
            baseline_version=baseline_version,
            candidate_version=candidate_version,
            status=status,
            slo_thresholds=slo_dict,
            metrics=mets_dict,
            approver=approver,
            created_at=created_at,
            updated_at=updated_at,
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

        max_cost = current.slo_thresholds.get("max_cost")
        if max_cost is not None and observation.cost > max_cost:
            return self._rollback(
                current,
                f"cost {observation.cost:.6f} breached SLO max {max_cost:.6f}",
            )

        max_error_count = current.slo_thresholds.get("max_error_count")
        if max_error_count is not None and observation.error_count > max_error_count:
            return self._rollback(
                current,
                f"error count {observation.error_count} breached SLO max {max_error_count:.0f}",
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

    def has_candidates(self) -> bool:
        if not self.state_store.enabled or not self.state_store.db_path.exists():
            return False
        self._init_table()

        def _do_check() -> bool:
            with closing(connect_sqlite(self.state_store.db_path)) as con:
                row = con.execute("SELECT 1 FROM agent_learning_candidates LIMIT 1").fetchone()
                return bool(row)

        return bool(retry_busy(_do_check, retries=5, base_delay_seconds=0.02))

    def candidate_count(self, status: CandidateStatus | None = None) -> int:
        if not self.state_store.enabled or not self.state_store.db_path.exists():
            return 0
        self._init_table()

        def _do_count() -> int:
            with closing(connect_sqlite(self.state_store.db_path)) as con:
                if status is not None:
                    st_val = status.value if isinstance(status, CandidateStatus) else str(status)
                    row = con.execute(
                        "SELECT COUNT(*) FROM agent_learning_candidates WHERE status = ?",
                        (st_val,),
                    ).fetchone()
                else:
                    row = con.execute("SELECT COUNT(*) FROM agent_learning_candidates").fetchone()
                return int(row[0]) if row else 0

        return int(retry_busy(_do_count, retries=5, base_delay_seconds=0.02))

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
                except sqlite3.Error as rollback_error:
                    LOGGER.warning(
                        "learning rollback failed error_type=%s",
                        type(rollback_error).__name__,
                    )
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
        if not isinstance(thresholds_raw, str) or not isinstance(metrics_raw, str):
            raise TypeError("stored candidate thresholds and metrics must be JSON strings")
        try:
            thresholds = json.loads(thresholds_raw)
            metrics = json.loads(metrics_raw)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ValueError("stored candidate thresholds and metrics contain invalid JSON") from exc
        return ImprovementCandidate.from_dict(
            {
                "candidate_id": candidate_id,
                "name": name,
                "baseline_version": baseline_version,
                "candidate_version": candidate_version,
                "status": status_val,
                "slo_thresholds": thresholds,
                "metrics": metrics,
                "approver": approver,
                "created_at": created_at,
                "updated_at": updated_at,
            }
        )
