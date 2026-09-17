from __future__ import annotations

import json
import math
import re
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
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
        scope = AgentScope.parse(scope, AgentScope.REPOSITORY)
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
            scope=AgentScope.parse(data.get("scope", AgentScope.REPOSITORY)),
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
                con = connect_sqlite(self.state_store.db_path)
                try:
                    with con:
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
                        con.execute(
                            """
                            CREATE INDEX IF NOT EXISTS idx_agent_memory_expires
                            ON agent_memory_records (expires_at)
                            WHERE expires_at IS NOT NULL;
                            """
                        )
                        con.execute(
                            """
                            CREATE TABLE IF NOT EXISTS agent_entity_relations (
                                relation_id TEXT PRIMARY KEY,
                                source_entity TEXT NOT NULL,
                                relation TEXT NOT NULL,
                                target_entity TEXT NOT NULL,
                                weight REAL NOT NULL DEFAULT 1.0,
                                metadata TEXT NOT NULL DEFAULT '{}',
                                created_at REAL NOT NULL,
                                updated_at REAL NOT NULL
                            );
                            """
                        )
                        con.execute(
                            "CREATE INDEX IF NOT EXISTS idx_entity_rel_source ON agent_entity_relations(source_entity);"
                        )
                        con.execute(
                            "CREATE INDEX IF NOT EXISTS idx_entity_rel_target ON agent_entity_relations(target_entity);"
                        )
                        con.execute(
                            "CREATE INDEX IF NOT EXISTS idx_entity_rel_type ON agent_entity_relations(relation);"
                        )
                        try:
                            con.execute(
                                """
                                CREATE VIRTUAL TABLE IF NOT EXISTS agent_memory_fts USING fts5(
                                    record_id UNINDEXED,
                                    key,
                                    value,
                                    tokenize='unicode61'
                                );
                                """
                            )
                        except Exception:
                            pass
                        con.execute(
                            """
                            CREATE TABLE IF NOT EXISTS agent_memory_embeddings (
                                record_id TEXT PRIMARY KEY,
                                embedding TEXT NOT NULL,
                                created_at REAL NOT NULL
                            );
                            """
                        )
                finally:
                    con.close()
            retry_busy(_setup, retries=5, base_delay_seconds=0.02)
            self._initialized = True

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
        self._auto_link_record(target_record, actor=actor)
        return target_record

    def _auto_link_record(self, record: MemoryRecord, actor: str = "agent") -> None:
        """Automatically create entity relations for recorded memory items."""
        try:
            if record.key:
                self.record_relation(
                    source=record.record_id,
                    relation="defines",
                    target=record.key,
                    weight=record.confidence,
                    actor=actor,
                )
            if record.scope_id:
                self.record_relation(
                    source=record.record_id,
                    relation="scoped_in",
                    target=record.scope_id,
                    weight=1.0,
                    actor=actor,
                )
            text_corpus = f"{record.key or ''} {record.value or ''}"
            matches = set(re.findall(r"\b[\w\-./\\]+\.(?:py|js|ts|tsx|jsx|go|rs|cs|java|cpp|h|json|toml|yaml|md)\b", text_corpus))
            source_ent = record.key or record.record_id
            for target_path in list(matches)[:10]:
                norm_path = target_path.replace("\\", "/").strip("./")
                if norm_path and norm_path != source_ent:
                    self.record_relation(
                        source=source_ent,
                        relation="targets",
                        target=norm_path,
                        weight=0.8,
                        actor=actor,
                    )
            if isinstance(record.provenance, dict) and "relations" in record.provenance:
                for rel in record.provenance["relations"]:
                    if isinstance(rel, dict) and "target" in rel and "relation" in rel:
                        self.record_relation(
                            source=rel.get("source", source_ent),
                            relation=rel["relation"],
                            target=rel["target"],
                            weight=float(rel.get("weight", 1.0)),
                            actor=actor,
                        )
        except Exception:
            pass

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

    def get(self, record_id: str, *, include_expired: bool = False) -> MemoryRecord | None:
        if not self.state_store.enabled or not self.state_store.db_path.exists():
            return None
        self._init_table()
        con = connect_sqlite(self.state_store.db_path)
        try:
            sql = (
                "SELECT record_id, kind, scope, scope_id, key, value, status, confidence, source, "
                "evidence_ids, sensitivity, contradicts_record_id, supersedes_record_id, "
                "quarantine_reason, provenance, created_at, updated_at, expires_at "
                "FROM agent_memory_records WHERE record_id = ?"
            )
            params: list[Any] = [record_id]
            if not include_expired:
                sql += " AND (expires_at IS NULL OR expires_at > ?)"
                params.append(time.time())
            row = con.execute(sql, tuple(params)).fetchone()
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
        *,
        include_expired: bool = False,
        semantic: bool = True,
        services: Any = None,
        min_score: float = 0.1,
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
        if not include_expired:
            sql += " AND (expires_at IS NULL OR expires_at > ?)"
            params.append(time.time())
        if scope is not None:
            scope_val = scope.value if hasattr(scope, "value") else str(scope)
            if scope_val.lower() == "repo":
                scope_val = "repository"
            sql += " AND scope = ?"
            params.append(scope_val)
        if key is not None:
            sql += " AND key = ?"
            params.append(key)
        if status is not None:
            sql += " AND status = ?"
            params.append(status.value if hasattr(status, "value") else str(status))

        base_sql = sql
        base_params = list(params)

        if query:
            sql += " AND (key LIKE ? OR value LIKE ?)"
            pat = f"%{query}%"
            params.extend([pat, pat])

        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(max(1, int(limit)))

        con = connect_sqlite(self.state_store.db_path)
        try:
            cur = con.execute(sql, tuple(params))
            exact_records = [self._row_to_record(row) for row in cur.fetchall()]

            if not query or not semantic:
                return exact_records

            # Hybrid Semantic Search: Vector Embeddings + FTS5 BM25 + Token Overlap
            fts_scores: dict[str, float] = {}
            clean_terms = [re.sub(r"[^\w_]", "", t) for t in query.split()]
            clean_terms = [t for t in clean_terms if len(t) > 1]
            if clean_terms:
                fts_query = " OR ".join(f'"{t}"' for t in clean_terms[:8])
                try:
                    fts_cur = con.execute("SELECT record_id, rank FROM agent_memory_fts WHERE agent_memory_fts MATCH ? ORDER BY rank LIMIT 100", (fts_query,))
                    for r_id, rk in fts_cur.fetchall():
                        fts_scores[r_id] = 1.0 / (1.0 + abs(float(rk)))
                except Exception:
                    pass

            vec_scores: dict[str, float] = {}
            embed_fn = getattr(services, "embed", None)
            if embed_fn and callable(embed_fn):
                try:
                    emb_res = embed_fn([query], tenant="agent")
                    q_vec = emb_res.get("embeddings", [[]])[0]
                    if q_vec:
                        cur_emb = con.execute("SELECT record_id, embedding FROM agent_memory_embeddings ORDER BY created_at DESC LIMIT 500")
                        for r_id, emb_json in cur_emb.fetchall():
                            rec_vec = json.loads(emb_json)
                            sim = self._cosine_similarity(q_vec, rec_vec)
                            if sim >= min_score:
                                vec_scores[r_id] = sim
                except Exception:
                    pass

            cand_ids = set(fts_scores.keys()) | set(vec_scores.keys())
            cand_records: list[MemoryRecord] = []
            if cand_ids:
                placeholders = ",".join("?" for _ in cand_ids)
                fetch_sql = base_sql + f" AND record_id IN ({placeholders})"
                fetch_rows = con.execute(fetch_sql, tuple(base_params) + tuple(cand_ids)).fetchall()
                cand_records.extend(self._row_to_record(row) for row in fetch_rows)

            cand_sql = base_sql + " ORDER BY updated_at DESC LIMIT 100"
            cand_rows = con.execute(cand_sql, tuple(base_params)).fetchall()
            seen_cand = {r.record_id for r in cand_records}
            for row in cand_rows:
                rec = self._row_to_record(row)
                if rec.record_id not in seen_cand:
                    cand_records.append(rec)
                    seen_cand.add(rec.record_id)

            scored: list[tuple[float, MemoryRecord]] = []
            seen_ids = set()

            for rec in exact_records:
                seen_ids.add(rec.record_id)
                v_s = vec_scores.get(rec.record_id, 0.0)
                f_s = fts_scores.get(rec.record_id, 0.0)
                base = 1.0 + (v_s * 0.5 + f_s * 0.3)
                scored.append((base, rec))

            for rec in cand_records:
                if rec.record_id not in seen_ids:
                    seen_ids.add(rec.record_id)
                    v_s = vec_scores.get(rec.record_id, 0.0)
                    f_s = fts_scores.get(rec.record_id, 0.0)
                    score = v_s * 0.7 + f_s * 0.3
                    if score >= min_score:
                        scored.append((score, rec))

            scored.sort(key=lambda x: x[0], reverse=True)
            return [rec for _, rec in scored[:limit]]
        finally:
            con.close()

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        return dot / (na * nb) if na and nb else 0.0

    def set_embedding(self, record_id: str, embedding: list[float]) -> bool:
        if not self.state_store.enabled or not self.state_store.db_path.exists():
            return False
        self._init_table()
        now = time.time()
        emb_json = json.dumps([round(float(x), 5) for x in embedding])
        with self._lock:
            def _insert():
                con = connect_sqlite(self.state_store.db_path)
                try:
                    with con:
                        con.execute(
                            """
                            INSERT INTO agent_memory_embeddings(record_id, embedding, created_at)
                            VALUES (?, ?, ?)
                            ON CONFLICT(record_id) DO UPDATE SET
                                embedding = excluded.embedding,
                                created_at = excluded.created_at
                            """,
                            (record_id, emb_json, now),
                        )
                finally:
                    con.close()
            retry_busy(_insert, retries=5, base_delay_seconds=0.02)
        return True

    store_embedding = set_embedding

    def reap_expired(self, now: float | None = None) -> int:
        if not self.state_store.enabled or not self.state_store.db_path.exists():
            return 0
        self._init_table()
        cutoff = float(time.time() if now is None else now)
        with self._lock:
            def _do_reap() -> int:
                con = connect_sqlite(self.state_store.db_path)
                try:
                    with con:
                        cur = con.execute(
                            "DELETE FROM agent_memory_records WHERE expires_at IS NOT NULL AND expires_at <= ?",
                            (cutoff,),
                        )
                        count = int(cur.rowcount)
                        if count > 0:
                            con.execute(
                                "DELETE FROM agent_memory_embeddings WHERE record_id NOT IN (SELECT record_id FROM agent_memory_records)"
                            )
                            try:
                                con.execute(
                                    "DELETE FROM agent_memory_fts WHERE record_id NOT IN (SELECT record_id FROM agent_memory_records)"
                                )
                            except Exception:
                                pass
                            try:
                                con.execute(
                                    "DELETE FROM agent_entity_relations WHERE source_entity NOT IN (SELECT record_id FROM agent_memory_records) AND target_entity NOT IN (SELECT record_id FROM agent_memory_records)"
                                )
                            except Exception:
                                pass
                        return count
                finally:
                    con.close()
            return retry_busy(_do_reap, retries=5, base_delay_seconds=0.02)

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
                try:
                    val_str = json.dumps(record.value) if isinstance(record.value, (dict, list)) else str(record.value)
                    con.execute("DELETE FROM agent_memory_fts WHERE record_id = ?", (record.record_id,))
                    con.execute(
                        "INSERT INTO agent_memory_fts(record_id, key, value) VALUES(?, ?, ?)",
                        (record.record_id, str(record.key), val_str),
                    )
                except Exception:
                    pass
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
            scope=AgentScope.parse(scope_val, AgentScope.REPOSITORY),
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
            if cnt > 0:
                con.execute(
                    "DELETE FROM agent_entity_relations WHERE source_entity = ? OR target_entity = ?",
                    (record_id, record_id),
                )
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
                out_scope = AgentScope.parse(target_scope, grp_scope)

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
            self._auto_link_record(digest_record, actor=actor)

            for src_rec in grp_records:
                superseded_rec = src_rec.with_superseded_by(digest_record.record_id)
                self._save_record(superseded_rec)
                self.record_relation(
                    source=src_rec.record_id,
                    relation="compacted_into",
                    target=digest_record.record_id,
                    weight=1.0,
                    actor=actor,
                )
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

    def record_relation(
        self,
        source: str,
        relation: str,
        target: str,
        *,
        weight: float = 1.0,
        metadata: dict[str, Any] | None = None,
        actor: str = "agent",
    ) -> dict[str, Any]:
        self._init_table()
        rel_id = f"rel_{uuid.uuid4().hex[:12]}"
        now = time.time()
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)
        def _insert():
            con = connect_sqlite(self.state_store.db_path)
            try:
                with con:
                    con.execute(
                        """
                        INSERT INTO agent_entity_relations (
                            relation_id, source_entity, relation, target_entity, weight, metadata, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (rel_id, source.strip(), relation.strip(), target.strip(), float(weight), meta_json, now, now),
                    )
            finally:
                con.close()
        retry_busy(_insert, retries=5, base_delay_seconds=0.02)
        event = AgentEvent.create(
            stream_id=f"relation:{source}:{target}",
            kind="relation.recorded",
            payload={"relation_id": rel_id, "source": source, "relation": relation, "target": target, "weight": weight},
            actor=actor,
        )
        self.state_store.append(event)
        return {
            "success": True,
            "relation_id": rel_id,
            "source_entity": source,
            "relation": relation,
            "target_entity": target,
            "weight": weight,
        }

    def find_relations(
        self,
        entity: str = "",
        *,
        source_entity: str | None = None,
        target_entity: str | None = None,
        direction: str = "both",
        relation: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        self._init_table()
        if source_entity:
            ent = source_entity.strip()
            direction = "out"
        elif target_entity:
            ent = target_entity.strip()
            direction = "in"
        else:
            ent = entity.strip() if entity else ""

        def _fetch():
            con = connect_sqlite(self.state_store.db_path)
            try:
                params: list[Any] = []
                where_clauses: list[str] = []
                if ent:
                    if direction == "out":
                        where_clauses.append("source_entity = ?")
                        params.append(ent)
                    elif direction == "in":
                        where_clauses.append("target_entity = ?")
                        params.append(ent)
                    else:
                        where_clauses.append("(source_entity = ? OR target_entity = ?)")
                        params.extend([ent, ent])
                if relation:
                    where_clauses.append("relation = ?")
                    params.append(relation.strip())
                sql = "SELECT relation_id, source_entity, relation, target_entity, weight, metadata, updated_at FROM agent_entity_relations"
                if where_clauses:
                    sql += " WHERE " + " AND ".join(where_clauses)
                sql += " ORDER BY weight DESC, updated_at DESC LIMIT ?"
                params.append(max(1, int(limit)))
                cur = con.execute(sql, params)
                results = []
                for row in cur.fetchall():
                    results.append({
                        "relation_id": row[0],
                        "source_entity": row[1],
                        "relation": row[2],
                        "target_entity": row[3],
                        "weight": float(row[4]),
                        "metadata": json.loads(row[5]) if row[5] else {},
                        "updated_at": float(row[6]),
                    })
                return results
            finally:
                con.close()
        return retry_busy(_fetch, retries=5, base_delay_seconds=0.02)

    def traverse_graph(
        self,
        start_entity: str,
        *,
        max_depth: int = 2,
        max_nodes: int = 50,
    ) -> dict[str, Any]:
        self._init_table()
        visited_nodes: set[str] = {start_entity.strip()}
        collected_edges: list[dict[str, Any]] = []
        queue = [(start_entity.strip(), 0)]
        while queue and len(visited_nodes) < max_nodes:
            curr_node, depth = queue.pop(0)
            if depth >= max_depth:
                continue
            rels = self.find_relations(curr_node, direction="both", limit=20)
            for r in rels:
                collected_edges.append(r)
                neighbor = r["target_entity"] if r["source_entity"] == curr_node else r["source_entity"]
                if neighbor not in visited_nodes and len(visited_nodes) < max_nodes:
                    visited_nodes.add(neighbor)
                    queue.append((neighbor, depth + 1))
        return {
            "success": True,
            "start_entity": start_entity,
            "nodes": sorted(list(visited_nodes)),
            "edges": collected_edges,
            "total_nodes": len(visited_nodes),
            "total_edges": len(collected_edges),
        }
