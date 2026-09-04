from __future__ import annotations

import json
import sqlite3
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from .agent_events import AgentEvent, AgentStateStore
from .agent_identity import AgentScope
from .sqlite_support import connect_sqlite, retry_busy


class ApprovalRequiredError(PermissionError):
    """Raised when an unapproved promotion is attempted (e.g. global scope without user approval)."""


class MemoryKind(str, Enum):
    FACT = "fact"
    DECISION = "decision"
    CONVENTION = "convention"
    GOTCHA = "gotcha"
    HYPOTHESIS = "hypothesis"
    ASSUMPTION = "assumption"
    PLAYBOOK = "playbook"
    CAPABILITY_OBSERVATION = "capability_observation"
    ENVIRONMENT_CAPSULE = "environment_capsule"


class MemoryStatus(str, Enum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    CONFIRMED = "confirmed"
    QUARANTINED = "quarantined"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"


@dataclass(frozen=True)
class MemoryRecord:
    record_id: str
    kind: MemoryKind
    scope: AgentScope
    scope_id: str = ""
    key: str = ""
    value: Any = None
    confidence: float = 1.0
    status: MemoryStatus = MemoryStatus.ACTIVE
    source: str = "agent"
    evidence_ids: tuple[str, ...] = ()
    sensitivity: str = "normal"
    contradicts_record_id: str | None = None
    supersedes_record_id: str | None = None
    quarantine_reason: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    updated_at: float = 0.0
    expires_at: float | None = None

    @classmethod
    def create(
        cls,
        kind: MemoryKind,
        scope: AgentScope,
        key: str,
        value: Any = None,
        scope_id: str = "",
        confidence: float = 1.0,
        status: MemoryStatus | None = None,
        source: str = "agent",
        evidence_ids: tuple[str, ...] = (),
        sensitivity: str = "normal",
        provenance: dict[str, Any] | None = None,
        expires_at: float | None = None,
    ) -> MemoryRecord:
        if isinstance(kind, str):
            try:
                kind = MemoryKind(kind.lower())
            except ValueError:
                kind = MemoryKind.FACT
        if isinstance(scope, str):
            raw_s = scope.lower()
            if raw_s == "repo":
                raw_s = "repository"
            try:
                scope = AgentScope(raw_s)
            except ValueError:
                scope = AgentScope.REPOSITORY
        now = time.time()
        # Default status based on source & kind
        determined_status = status
        if determined_status is None:
            if source == "model" or kind in (MemoryKind.HYPOTHESIS, MemoryKind.ASSUMPTION):
                determined_status = MemoryStatus.CANDIDATE
            else:
                determined_status = MemoryStatus.ACTIVE

        return cls(
            record_id=f"mem_{uuid.uuid4().hex[:12]}",
            kind=kind,
            scope=scope,
            scope_id=scope_id,
            key=key,
            value=value,
            confidence=float(confidence),
            status=determined_status,
            source=source,
            evidence_ids=tuple(evidence_ids),
            sensitivity=sensitivity,
            contradicts_record_id=None,
            supersedes_record_id=None,
            quarantine_reason=None,
            provenance=dict(provenance or {}),
            created_at=now,
            updated_at=now,
            expires_at=expires_at,
        )

    def with_status(
        self,
        new_status: MemoryStatus,
        reason: str | None = None,
    ) -> MemoryRecord:
        return MemoryRecord(
            record_id=self.record_id,
            kind=self.kind,
            scope=self.scope,
            scope_id=self.scope_id,
            key=self.key,
            value=self.value,
            confidence=self.confidence,
            status=new_status,
            source=self.source,
            evidence_ids=self.evidence_ids,
            sensitivity=self.sensitivity,
            contradicts_record_id=self.contradicts_record_id,
            supersedes_record_id=self.supersedes_record_id,
            quarantine_reason=reason or self.quarantine_reason,
            provenance=self.provenance,
            created_at=self.created_at,
            updated_at=time.time(),
            expires_at=self.expires_at,
        )

    def with_scope(self, new_scope: AgentScope, new_status: MemoryStatus = MemoryStatus.CONFIRMED) -> MemoryRecord:
        return MemoryRecord(
            record_id=self.record_id,
            kind=self.kind,
            scope=new_scope,
            scope_id=self.scope_id,
            key=self.key,
            value=self.value,
            confidence=self.confidence,
            status=new_status,
            source=self.source,
            evidence_ids=self.evidence_ids,
            sensitivity=self.sensitivity,
            contradicts_record_id=self.contradicts_record_id,
            supersedes_record_id=self.supersedes_record_id,
            quarantine_reason=None,
            provenance=self.provenance,
            created_at=self.created_at,
            updated_at=time.time(),
            expires_at=self.expires_at,
        )

    def with_superseded_by(self, new_record_id: str) -> MemoryRecord:
        return MemoryRecord(
            record_id=self.record_id,
            kind=self.kind,
            scope=self.scope,
            scope_id=self.scope_id,
            key=self.key,
            value=self.value,
            confidence=self.confidence,
            status=MemoryStatus.SUPERSEDED,
            source=self.source,
            evidence_ids=self.evidence_ids,
            sensitivity=self.sensitivity,
            contradicts_record_id=self.contradicts_record_id,
            supersedes_record_id=new_record_id,
            quarantine_reason=self.quarantine_reason,
            provenance=self.provenance,
            created_at=self.created_at,
            updated_at=time.time(),
            expires_at=self.expires_at,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "kind": self.kind.value,
            "scope": self.scope.value,
            "scope_id": self.scope_id,
            "key": self.key,
            "value": self.value,
            "confidence": self.confidence,
            "status": self.status.value,
            "source": self.source,
            "evidence_ids": list(self.evidence_ids),
            "sensitivity": self.sensitivity,
            "contradicts_record_id": self.contradicts_record_id,
            "supersedes_record_id": self.supersedes_record_id,
            "quarantine_reason": self.quarantine_reason,
            "provenance": dict(self.provenance),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MemoryRecord:
        return cls(
            record_id=str(data["record_id"]),
            kind=MemoryKind(data["kind"]),
            scope=AgentScope(data["scope"]),
            scope_id=str(data.get("scope_id", "")),
            key=str(data.get("key", "")),
            value=data.get("value"),
            confidence=float(data.get("confidence", 1.0)),
            status=MemoryStatus(data.get("status", MemoryStatus.ACTIVE.value)),
            source=str(data.get("source", "agent")),
            evidence_ids=tuple(data.get("evidence_ids") or ()),
            sensitivity=str(data.get("sensitivity", "normal")),
            contradicts_record_id=data.get("contradicts_record_id"),
            supersedes_record_id=data.get("supersedes_record_id"),
            quarantine_reason=data.get("quarantine_reason"),
            provenance=dict(data.get("provenance") or {}),
            created_at=float(data.get("created_at", 0.0)),
            updated_at=float(data.get("updated_at", 0.0)),
            expires_at=float(data["expires_at"]) if data.get("expires_at") is not None else None,
        )


class MemoryStore:
    def __init__(self, state_store: AgentStateStore) -> None:
        self.state_store = state_store
        self._init_table()

    def _init_table(self) -> None:
        if not self.state_store.enabled:
            return
        self.state_store._ensure_schema()
        con = connect_sqlite(self.state_store.db_path)
        try:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_memory_records (
                    record_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    status TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    source TEXT NOT NULL,
                    evidence_ids TEXT NOT NULL,
                    sensitivity TEXT NOT NULL,
                    contradicts_record_id TEXT,
                    supersedes_record_id TEXT,
                    quarantine_reason TEXT,
                    provenance TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    expires_at REAL
                );
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_agent_memory_scope_key
                ON agent_memory_records (scope, key, status);
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_agent_memory_updated
                ON agent_memory_records (updated_at DESC);
                """
            )
            con.commit()
        finally:
            con.close()

    def record(
        self,
        record: MemoryRecord,
        *,
        actor: str = "agent",
        idempotency_key: str = "",
    ) -> MemoryRecord:
        # Enforce candidate status for model output or hypothesis
        target_record = record
        if target_record.source == "model" or target_record.kind in (MemoryKind.HYPOTHESIS, MemoryKind.ASSUMPTION):
            if target_record.status not in (MemoryStatus.QUARANTINED, MemoryStatus.REJECTED):
                target_record = target_record.with_status(MemoryStatus.CANDIDATE)

        # Check for conflicts among high-confidence records
        if target_record.status in (MemoryStatus.ACTIVE, MemoryStatus.CONFIRMED):
            existing_records = self.find(scope=target_record.scope, key=target_record.key)
            for ex in existing_records:
                if ex.status in (MemoryStatus.ACTIVE, MemoryStatus.CONFIRMED):
                    if ex.confidence >= 0.8 and target_record.confidence >= 0.8 and ex.value != target_record.value:
                        target_record = target_record.with_status(
                            MemoryStatus.QUARANTINED,
                            reason=f"Conflicting high-confidence record exists: {ex.record_id}",
                        )
                        break

        event = AgentEvent.create(
            stream_id=f"memory:{target_record.scope.value}:{target_record.key or target_record.record_id}",
            kind="memory.recorded",
            payload=target_record.to_dict(),
            idempotency_key=idempotency_key or f"rec_{target_record.record_id}",
            actor=actor,
        )
        self.state_store.append(event)
        self._save_record(target_record)
        return target_record

    def promote(
        self,
        record_id: str,
        target_scope: AgentScope,
        *,
        approver: str,
    ) -> MemoryRecord:
        current = self.get(record_id)
        if not current:
            raise KeyError(f"Memory record {record_id} not found")

        if target_scope == AgentScope.GLOBAL and approver != "user":
            raise ApprovalRequiredError("global promotion requires user approval")

        promoted = current.with_scope(target_scope, MemoryStatus.CONFIRMED)
        event = AgentEvent.create(
            stream_id=f"memory:{target_scope.value}:{promoted.key or promoted.record_id}",
            kind="memory.promoted",
            payload={"record_id": record_id, "from_scope": current.scope.value, "to_scope": target_scope.value, "approver": approver},
            idempotency_key=f"promote_{record_id}_{target_scope.value}",
            actor=approver,
        )
        self.state_store.append(event)
        self._save_record(promoted)
        return promoted

    def quarantine(
        self,
        record_id: str,
        reason: str,
        *,
        actor: str,
    ) -> MemoryRecord:
        current = self.get(record_id)
        if not current:
            raise KeyError(f"Memory record {record_id} not found")

        quarantined = current.with_status(MemoryStatus.QUARANTINED, reason=reason)
        event = AgentEvent.create(
            stream_id=f"memory:{current.scope.value}:{current.key or current.record_id}",
            kind="memory.quarantined",
            payload={"record_id": record_id, "reason": reason},
            idempotency_key=f"quar_{record_id}_{int(time.time())}",
            actor=actor,
        )
        self.state_store.append(event)
        self._save_record(quarantined)
        return quarantined

    def get(self, record_id: str) -> MemoryRecord | None:
        if not self.state_store.enabled or not self.state_store.db_path.exists():
            return None
        self._init_table()
        con = connect_sqlite(self.state_store.db_path)
        try:
            row = con.execute(
                """
                SELECT record_id, kind, scope, scope_id, key, value, status, confidence, source,
                       evidence_ids, sensitivity, contradicts_record_id, supersedes_record_id,
                       quarantine_reason, provenance, created_at, updated_at, expires_at
                FROM agent_memory_records
                WHERE record_id = ?
                """,
                (record_id,),
            ).fetchone()
            if not row:
                return None
            return self._row_to_record(row)
        finally:
            con.close()

    def find(
        self,
        scope: AgentScope | None = None,
        key: str | None = None,
        query: str | None = None,
        status: MemoryStatus | None = None,
        limit: int = 100,
    ) -> list[MemoryRecord]:
        if not self.state_store.enabled or not self.state_store.db_path.exists():
            return []
        self._init_table()
        sql = (
            "SELECT record_id, kind, scope, scope_id, key, value, status, confidence, source, "
            "evidence_ids, sensitivity, contradicts_record_id, supersedes_record_id, "
            "quarantine_reason, provenance, created_at, updated_at, expires_at "
            "FROM agent_memory_records WHERE 1=1"
        )
        params: list[Any] = []
        if scope is not None:
            scope_val = scope.value if hasattr(scope, "value") else str(scope)
            if scope_val.lower() == "repo":
                scope_val = "repository"
            sql += " AND scope = ?"
            params.append(scope_val)
        if key is not None:
            sql += " AND key = ?"
            params.append(key)
        if query:
            sql += " AND (key LIKE ? OR value LIKE ?)"
            pat = f"%{query}%"
            params.extend([pat, pat])
        if status is not None:
            sql += " AND status = ?"
            params.append(status.value if hasattr(status, "value") else str(status))
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(max(1, int(limit)))

        con = connect_sqlite(self.state_store.db_path)
        try:
            cur = con.execute(sql, tuple(params))
            return [self._row_to_record(row) for row in cur.fetchall()]
        finally:
            con.close()

    def count(self) -> int:
        if not self.state_store.enabled or not self.state_store.db_path.exists():
            return 0
        self._init_table()
        con = connect_sqlite(self.state_store.db_path)
        try:
            row = con.execute("SELECT COUNT(1) FROM agent_memory_records").fetchone()
            return int(row[0]) if row else 0
        finally:
            con.close()

    def _save_record(self, record: MemoryRecord) -> None:
        if not self.state_store.enabled:
            return
        self._init_table()

        def _do_save() -> None:
            con = connect_sqlite(self.state_store.db_path, isolation_level=None)
            try:
                con.execute("BEGIN IMMEDIATE")
                con.execute(
                    """
                    INSERT INTO agent_memory_records (
                        record_id, kind, scope, scope_id, key, value, status, confidence, source,
                        evidence_ids, sensitivity, contradicts_record_id, supersedes_record_id,
                        quarantine_reason, provenance, created_at, updated_at, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(record_id) DO UPDATE SET
                        kind = excluded.kind,
                        scope = excluded.scope,
                        scope_id = excluded.scope_id,
                        key = excluded.key,
                        value = excluded.value,
                        status = excluded.status,
                        confidence = excluded.confidence,
                        source = excluded.source,
                        evidence_ids = excluded.evidence_ids,
                        sensitivity = excluded.sensitivity,
                        contradicts_record_id = excluded.contradicts_record_id,
                        supersedes_record_id = excluded.supersedes_record_id,
                        quarantine_reason = excluded.quarantine_reason,
                        provenance = excluded.provenance,
                        updated_at = excluded.updated_at,
                        expires_at = excluded.expires_at
                    """,
                    (
                        record.record_id,
                        record.kind.value,
                        record.scope.value,
                        record.scope_id,
                        record.key,
                        json.dumps(record.value),
                        record.status.value,
                        record.confidence,
                        record.source,
                        json.dumps(list(record.evidence_ids)),
                        record.sensitivity,
                        record.contradicts_record_id,
                        record.supersedes_record_id,
                        record.quarantine_reason,
                        json.dumps(record.provenance),
                        record.created_at,
                        record.updated_at,
                        record.expires_at,
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

    def _row_to_record(self, row: tuple[Any, ...]) -> MemoryRecord:
        (
            record_id,
            kind_val,
            scope_val,
            scope_id,
            key,
            val_raw,
            status_val,
            confidence,
            source,
            evidence_ids_raw,
            sensitivity,
            contradicts_record_id,
            supersedes_record_id,
            quarantine_reason,
            provenance_raw,
            created_at,
            updated_at,
            expires_at,
        ) = row
        return MemoryRecord(
            record_id=record_id,
            kind=MemoryKind(kind_val),
            scope=AgentScope(scope_val),
            scope_id=scope_id,
            key=key,
            value=json.loads(val_raw) if val_raw else None,
            confidence=float(confidence),
            status=MemoryStatus(status_val),
            source=source,
            evidence_ids=tuple(json.loads(evidence_ids_raw) if evidence_ids_raw else ()),
            sensitivity=sensitivity,
            contradicts_record_id=contradicts_record_id,
            supersedes_record_id=supersedes_record_id,
            quarantine_reason=quarantine_reason,
            provenance=json.loads(provenance_raw) if provenance_raw else {},
            created_at=float(created_at),
            updated_at=float(updated_at),
            expires_at=float(expires_at) if expires_at is not None else None,
        )

    def delete(self, record_id: str) -> bool:
        if not self.state_store.enabled or not self.state_store.db_path.exists():
            return False
        self._init_table()
        con = connect_sqlite(self.state_store.db_path, isolation_level=None)
        try:
            con.execute("BEGIN IMMEDIATE")
            cur = con.execute("DELETE FROM agent_memory_records WHERE record_id = ?", (record_id,))
            cnt = cur.rowcount
            con.execute("COMMIT")
            return cnt > 0
        finally:
            con.close()

    def compact(
        self,
        *,
        scope: AgentScope | str | None = None,
        older_than_seconds: float = 0.0,
        min_records: int = 3,
        target_scope: AgentScope | str | None = None,
        actor: str = "compactor",
    ) -> dict[str, Any]:
        """Compact older or fragmented memories of the same scope/kind into a digest record."""
        if not self.state_store.enabled or not self.state_store.db_path.exists():
            return {"success": False, "compacted_groups": 0, "compacted_records": 0, "created_records": []}

        now = time.time()
        records = self.find(scope=scope, limit=1000)
        candidates = [
            r for r in records
            if r.status in (MemoryStatus.ACTIVE, MemoryStatus.CONFIRMED)
            and not r.key.startswith("compacted_")
            and (older_than_seconds <= 0.0 or (now - r.updated_at) >= older_than_seconds)
        ]

        groups: dict[tuple[AgentScope, MemoryKind], list[MemoryRecord]] = defaultdict(list)
        for r in candidates:
            groups[(r.scope, r.kind)].append(r)

        created_records: list[dict[str, Any]] = []
        total_compacted = 0

        for (grp_scope, grp_kind), grp_records in groups.items():
            if len(grp_records) < max(2, min_records):
                continue

            out_scope = grp_scope
            if target_scope is not None:
                if isinstance(target_scope, str):
                    try:
                        out_scope = AgentScope(target_scope.lower())
                    except ValueError:
                        out_scope = grp_scope
                else:
                    out_scope = target_scope

            digest_key = f"compacted_{grp_kind.value}_{int(now)}"
            all_ev: set[str] = set()
            for r in grp_records:
                all_ev.update(r.evidence_ids)

            avg_conf = sum(r.confidence for r in grp_records) / len(grp_records)

            digest_value = {
                "type": "compacted_memory_digest",
                "kind": grp_kind.value,
                "record_count": len(grp_records),
                "keys": [r.key for r in grp_records if r.key],
                "items": [
                    {"key": r.key, "value": r.value, "confidence": r.confidence, "created_at": r.created_at}
                    for r in grp_records
                ],
                "summary": f"Compacted digest of {len(grp_records)} {grp_kind.value} records across sessions."
            }

            digest_record = MemoryRecord.create(
                kind=grp_kind,
                scope=out_scope,
                key=digest_key,
                value=digest_value,
                confidence=round(avg_conf, 3),
                status=MemoryStatus.CONFIRMED if out_scope != grp_scope else MemoryStatus.ACTIVE,
                source="memory_compactor",
                evidence_ids=tuple(sorted(all_ev)),
            )

            self._save_record(digest_record)

            for src_rec in grp_records:
                superseded_rec = src_rec.with_superseded_by(digest_record.record_id)
                self._save_record(superseded_rec)
                total_compacted += 1

            event = AgentEvent.create(
                stream_id=f"memory:{out_scope.value}:{digest_key}",
                kind="memory.compacted",
                payload={
                    "digest_record_id": digest_record.record_id,
                    "compacted_count": len(grp_records),
                    "source_record_ids": [r.record_id for r in grp_records],
                },
                idempotency_key=f"compact_{digest_record.record_id}",
                actor=actor,
            )
            self.state_store.append(event)
            created_records.append(digest_record.to_dict())

        return {
            "success": True,
            "compacted_groups": len(created_records),
            "compacted_records": total_compacted,
            "created_records": created_records,
        }

