from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .agent_events import AgentEvent, AgentStateStore
from .sqlite_support import connect_sqlite, retry_busy


@dataclass(frozen=True)
class VerificationReceipt:
    receipt_id: str
    task_id: str
    criterion: str
    change_intent_id: str = ""
    evidence_id: str = ""
    command_id: str = ""
    repository_revision: str = ""
    observed_at: float = 0.0
    expires_at: float | None = None
    passed: bool = True
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        task_id: str,
        criterion: str,
        passed: bool = True,
        change_intent_id: str = "",
        evidence_id: str = "",
        command_id: str = "",
        repository_revision: str = "",
        expires_at: float | None = None,
        details: dict[str, Any] | None = None,
    ) -> VerificationReceipt:
        now = time.time()
        return cls(
            receipt_id=f"rcpt_{uuid.uuid4().hex[:12]}",
            task_id=task_id,
            criterion=criterion,
            change_intent_id=change_intent_id,
            evidence_id=evidence_id,
            command_id=command_id,
            repository_revision=repository_revision,
            observed_at=now,
            expires_at=expires_at,
            passed=bool(passed),
            details=dict(details or {}),
        )

    def is_fresh(self, now: float) -> bool:
        if not self.passed:
            return False
        if self.expires_at is None:
            return True
        return float(self.expires_at) >= float(now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id,
            "task_id": self.task_id,
            "criterion": self.criterion,
            "change_intent_id": self.change_intent_id,
            "evidence_id": self.evidence_id,
            "command_id": self.command_id,
            "repository_revision": self.repository_revision,
            "observed_at": self.observed_at,
            "expires_at": self.expires_at,
            "passed": self.passed,
            "details": dict(self.details),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> VerificationReceipt:
        return cls(
            receipt_id=str(data["receipt_id"]),
            task_id=str(data["task_id"]),
            criterion=str(data["criterion"]),
            change_intent_id=str(data.get("change_intent_id", "")),
            evidence_id=str(data.get("evidence_id", "")),
            command_id=str(data.get("command_id", "")),
            repository_revision=str(data.get("repository_revision", "")),
            observed_at=float(data.get("observed_at", 0.0)),
            expires_at=float(data["expires_at"]) if data.get("expires_at") is not None else None,
            passed=bool(data.get("passed", True)),
            details=dict(data.get("details") or {}),
        )


@dataclass(frozen=True)
class ChangeIntent:
    change_id: str
    task_id: str
    affected_paths: tuple[str, ...]
    affected_symbols: tuple[str, ...] = ()
    expected_impact: str = ""
    rollback_description: str = ""
    created_at: float = 0.0

    @classmethod
    def create(
        cls,
        task_id: str,
        affected_paths: tuple[str, ...] | list[str],
        affected_symbols: tuple[str, ...] | list[str] = (),
        expected_impact: str = "",
        rollback_description: str = "",
    ) -> ChangeIntent:
        return cls(
            change_id=f"chg_{uuid.uuid4().hex[:12]}",
            task_id=task_id,
            affected_paths=tuple(affected_paths),
            affected_symbols=tuple(affected_symbols),
            expected_impact=expected_impact,
            rollback_description=rollback_description,
            created_at=time.time(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "change_id": self.change_id,
            "task_id": self.task_id,
            "affected_paths": list(self.affected_paths),
            "affected_symbols": list(self.affected_symbols),
            "expected_impact": self.expected_impact,
            "rollback_description": self.rollback_description,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ChangeIntent:
        return cls(
            change_id=str(data["change_id"]),
            task_id=str(data["task_id"]),
            affected_paths=tuple(data.get("affected_paths") or ()),
            affected_symbols=tuple(data.get("affected_symbols") or ()),
            expected_impact=str(data.get("expected_impact", "")),
            rollback_description=str(data.get("rollback_description", "")),
            created_at=float(data.get("created_at", 0.0)),
        )


@dataclass(frozen=True)
class OutcomeRecord:
    outcome_id: str
    change_id: str = ""
    task_id: str = ""
    kind: str = "accepted"
    actor: str = "user"
    details: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0

    @classmethod
    def reverted(
        cls,
        change_id: str,
        *,
        actor: str = "user",
        task_id: str = "",
        details: dict[str, Any] | None = None,
    ) -> OutcomeRecord:
        return cls(
            outcome_id=f"outc_{uuid.uuid4().hex[:12]}",
            change_id=change_id,
            task_id=task_id,
            kind="reverted",
            actor=actor,
            details=dict(details or {}),
            created_at=time.time(),
        )

    @classmethod
    def accepted(
        cls,
        change_id: str,
        *,
        actor: str = "user",
        task_id: str = "",
        details: dict[str, Any] | None = None,
    ) -> OutcomeRecord:
        return cls(
            outcome_id=f"outc_{uuid.uuid4().hex[:12]}",
            change_id=change_id,
            task_id=task_id,
            kind="accepted",
            actor=actor,
            details=dict(details or {}),
            created_at=time.time(),
        )

    @classmethod
    def corrected(
        cls,
        change_id: str,
        *,
        actor: str = "user",
        task_id: str = "",
        details: dict[str, Any] | None = None,
    ) -> OutcomeRecord:
        return cls(
            outcome_id=f"outc_{uuid.uuid4().hex[:12]}",
            change_id=change_id,
            task_id=task_id,
            kind="corrected",
            actor=actor,
            details=dict(details or {}),
            created_at=time.time(),
        )

    @classmethod
    def regressed(
        cls,
        change_id: str,
        *,
        actor: str = "user",
        task_id: str = "",
        details: dict[str, Any] | None = None,
    ) -> OutcomeRecord:
        return cls(
            outcome_id=f"outc_{uuid.uuid4().hex[:12]}",
            change_id=change_id,
            task_id=task_id,
            kind="regressed",
            actor=actor,
            details=dict(details or {}),
            created_at=time.time(),
        )

    @classmethod
    def rejected(
        cls,
        change_id: str,
        *,
        actor: str = "user",
        task_id: str = "",
        details: dict[str, Any] | None = None,
    ) -> OutcomeRecord:
        return cls(
            outcome_id=f"outc_{uuid.uuid4().hex[:12]}",
            change_id=change_id,
            task_id=task_id,
            kind="rejected",
            actor=actor,
            details=dict(details or {}),
            created_at=time.time(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome_id": self.outcome_id,
            "change_id": self.change_id,
            "task_id": self.task_id,
            "kind": self.kind,
            "actor": self.actor,
            "details": dict(self.details),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> OutcomeRecord:
        return cls(
            outcome_id=str(data["outcome_id"]),
            change_id=str(data.get("change_id", "")),
            task_id=str(data.get("task_id", "")),
            kind=str(data.get("kind", "accepted")),
            actor=str(data.get("actor", "user")),
            details=dict(data.get("details") or {}),
            created_at=float(data.get("created_at", 0.0)),
        )


@dataclass(frozen=True)
class CompletionResult:
    task_id: str
    complete: bool
    satisfied_criteria: tuple[str, ...]
    unsatisfied_criteria: tuple[str, ...]
    stale_criteria: tuple[str, ...]
    receipts: tuple[VerificationReceipt, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "complete": self.complete,
            "satisfied_criteria": list(self.satisfied_criteria),
            "unsatisfied_criteria": list(self.unsatisfied_criteria),
            "stale_criteria": list(self.stale_criteria),
            "receipts": [r.to_dict() for r in self.receipts],
        }


class VerificationStore:
    def __init__(
        self,
        state_store: AgentStateStore,
        *,
        task_store: Any | None = None,
    ) -> None:
        self.state_store = state_store
        self.task_store = task_store
        self._lock = threading.RLock()
        self._initialized = False
        self._init_tables()

    def _init_tables(self) -> None:
        if self._initialized or not self.state_store.enabled:
            return
        with self._lock:
            if self._initialized or not self.state_store.enabled:
                return
            self.state_store._ensure_schema()
            def _setup() -> None:
                con = connect_sqlite(self.state_store.db_path)
                try:
                    with con:
                        con.execute(
                            """
                            CREATE TABLE IF NOT EXISTS agent_verification_receipts (
                                receipt_id TEXT PRIMARY KEY,
                                task_id TEXT NOT NULL,
                                criterion TEXT NOT NULL,
                                change_intent_id TEXT NOT NULL,
                                evidence_id TEXT NOT NULL,
                                command_id TEXT NOT NULL,
                                repository_revision TEXT NOT NULL,
                                observed_at REAL NOT NULL,
                                expires_at REAL,
                                passed INTEGER NOT NULL,
                                details TEXT NOT NULL
                            );
                            """
                        )
                        con.execute(
                            """
                            CREATE INDEX IF NOT EXISTS idx_agent_verif_task
                            ON agent_verification_receipts (task_id, criterion, observed_at DESC);
                            """
                        )
                        con.execute(
                            """
                            CREATE INDEX IF NOT EXISTS idx_agent_verif_task_observed
                            ON agent_verification_receipts (task_id, observed_at DESC);
                            """
                        )
                        con.execute(
                            """
                            CREATE TABLE IF NOT EXISTS agent_change_intents (
                                change_id TEXT PRIMARY KEY,
                                task_id TEXT NOT NULL,
                                affected_paths TEXT NOT NULL,
                                affected_symbols TEXT NOT NULL,
                                expected_impact TEXT NOT NULL,
                                rollback_description TEXT NOT NULL,
                                created_at REAL NOT NULL
                            );
                            """
                        )
                        con.execute(
                            """
                            CREATE INDEX IF NOT EXISTS idx_agent_change_task
                            ON agent_change_intents (task_id);
                            """
                        )
                        con.execute(
                            """
                            CREATE TABLE IF NOT EXISTS agent_outcomes (
                                outcome_id TEXT PRIMARY KEY,
                                change_id TEXT NOT NULL,
                                task_id TEXT NOT NULL,
                                kind TEXT NOT NULL,
                                actor TEXT NOT NULL,
                                details TEXT NOT NULL,
                                created_at REAL NOT NULL
                            );
                            """
                        )
                        con.execute(
                            """
                            CREATE INDEX IF NOT EXISTS idx_agent_outcomes_task
                            ON agent_outcomes (task_id);
                            """
                        )
                        con.execute(
                            """
                            CREATE INDEX IF NOT EXISTS idx_agent_outcomes_change
                            ON agent_outcomes (change_id);
                            """
                        )
                finally:
                    con.close()
            retry_busy(_setup, retries=5, base_delay_seconds=0.02)
            self._initialized = True

    def record(self, receipt: VerificationReceipt) -> VerificationReceipt:
        self._init_tables()
        event = AgentEvent.create(
            stream_id=f"verification:{receipt.task_id}",
            kind="verification.receipt_recorded",
            payload=receipt.to_dict(),
            idempotency_key=f"rcpt_{receipt.receipt_id}",
            actor="verifier",
        )
        self.state_store.append(event)

        def _do_save() -> None:
            con = connect_sqlite(self.state_store.db_path, isolation_level=None)
            try:
                con.execute("BEGIN IMMEDIATE")
                con.execute(
                    """
                    INSERT INTO agent_verification_receipts (
                        receipt_id, task_id, criterion, change_intent_id, evidence_id,
                        command_id, repository_revision, observed_at, expires_at,
                        passed, details
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(receipt_id) DO UPDATE SET
                        expires_at = excluded.expires_at,
                        passed = excluded.passed,
                        details = excluded.details
                    """,
                    (
                        receipt.receipt_id,
                        receipt.task_id,
                        receipt.criterion,
                        receipt.change_intent_id,
                        receipt.evidence_id,
                        receipt.command_id,
                        receipt.repository_revision,
                        receipt.observed_at,
                        receipt.expires_at,
                        1 if receipt.passed else 0,
                        json.dumps(receipt.details),
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

        if self.task_store is not None and receipt.passed:
            try:
                self.task_store.add_verification_receipt(
                    receipt.task_id,
                    receipt.criterion,
                    receipt.receipt_id,
                )
            except KeyError:
                pass

        return receipt

    def record_change(self, change: ChangeIntent) -> ChangeIntent:
        self._init_tables()
        event = AgentEvent.create(
            stream_id=f"change:{change.task_id}",
            kind="change.intended",
            payload=change.to_dict(),
            idempotency_key=f"chg_{change.change_id}",
            actor="agent",
        )
        self.state_store.append(event)

        def _do_save() -> None:
            con = connect_sqlite(self.state_store.db_path, isolation_level=None)
            try:
                con.execute("BEGIN IMMEDIATE")
                con.execute(
                    """
                    INSERT INTO agent_change_intents (
                        change_id, task_id, affected_paths, affected_symbols,
                        expected_impact, rollback_description, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        change.change_id,
                        change.task_id,
                        json.dumps(list(change.affected_paths)),
                        json.dumps(list(change.affected_symbols)),
                        change.expected_impact,
                        change.rollback_description,
                        change.created_at,
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
        return change

    def record_outcome(self, outcome: OutcomeRecord) -> OutcomeRecord:
        self._init_tables()
        event = AgentEvent.create(
            stream_id=f"outcome:{outcome.change_id or outcome.task_id or 'global'}",
            kind="outcome.recorded",
            payload=outcome.to_dict(),
            idempotency_key=f"outc_{outcome.outcome_id}",
            actor=outcome.actor,
        )
        self.state_store.append(event)

        def _do_save() -> None:
            con = connect_sqlite(self.state_store.db_path, isolation_level=None)
            try:
                con.execute("BEGIN IMMEDIATE")
                con.execute(
                    """
                    INSERT INTO agent_outcomes (
                        outcome_id, change_id, task_id, kind, actor, details, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        outcome.outcome_id,
                        outcome.change_id,
                        outcome.task_id,
                        outcome.kind,
                        outcome.actor,
                        json.dumps(outcome.details),
                        outcome.created_at,
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
        return outcome

    def completion(self, task_id: str, now: float | None = None) -> CompletionResult:
        if not self.state_store.enabled or not self.state_store.db_path.exists():
            return CompletionResult(
                task_id=task_id,
                complete=False,
                satisfied_criteria=(),
                unsatisfied_criteria=(),
                stale_criteria=(),
                receipts=(),
            )
        self._init_tables()
        current_time = float(time.time() if now is None else now)

        required_criteria: list[str] = []
        if self.task_store is not None:
            t = self.task_store.get(task_id)
            if t:
                required_criteria = list(t.contract.acceptance_criteria)

        def _fetch_receipts() -> list[Any]:
            with closing(connect_sqlite(self.state_store.db_path)) as con:
                cur = con.execute(
                    """
                    SELECT receipt_id, task_id, criterion, change_intent_id, evidence_id,
                           command_id, repository_revision, observed_at, expires_at,
                           passed, details
                    FROM agent_verification_receipts
                    WHERE task_id = ?
                    ORDER BY observed_at DESC
                    """,
                    (task_id,),
                )
                return cur.fetchall()

        rows = retry_busy(_fetch_receipts, retries=5, base_delay_seconds=0.02)

        latest_by_criterion: dict[str, VerificationReceipt] = {}
        for row in rows:
            r = VerificationReceipt(
                receipt_id=row[0],
                task_id=row[1],
                criterion=row[2],
                change_intent_id=row[3],
                evidence_id=row[4],
                command_id=row[5],
                repository_revision=row[6],
                observed_at=row[7],
                expires_at=row[8],
                passed=bool(row[9]),
                details=json.loads(row[10]) if row[10] else {},
            )
            if r.criterion not in latest_by_criterion:
                latest_by_criterion[r.criterion] = r

        target_criteria = required_criteria if required_criteria else list(latest_by_criterion.keys())
        satisfied: list[str] = []
        unsatisfied: list[str] = []
        stale: list[str] = []

        for crit in target_criteria:
            rcpt = latest_by_criterion.get(crit)
            if not rcpt or not rcpt.passed:
                unsatisfied.append(crit)
            elif not rcpt.is_fresh(current_time):
                stale.append(crit)
            else:
                satisfied.append(crit)

        is_complete = (
            len(target_criteria) > 0
            and len(unsatisfied) == 0
            and len(stale) == 0
            and len(satisfied) == len(target_criteria)
        )

        return CompletionResult(
            task_id=task_id,
            complete=is_complete,
            satisfied_criteria=tuple(satisfied),
            unsatisfied_criteria=tuple(unsatisfied),
            stale_criteria=tuple(stale),
            receipts=tuple(latest_by_criterion.values()),
        )
