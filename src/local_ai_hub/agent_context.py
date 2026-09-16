from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Collection

from .agent_events import AgentStateStore
from .sqlite_support import connect_sqlite, retry_busy


@dataclass(frozen=True)
class ContextRequest:
    task_id: str
    token_budget: int = 4000
    include_kinds: tuple[str, ...] = ()
    changed_paths: tuple[str, ...] = ()
    root: str = ""
    tenant: str = ""


@dataclass(frozen=True)
class ContextElement:
    element_id: str
    source_kind: str
    content: str
    estimated_tokens: int
    reason: str
    confidence: float = 1.0
    freshness: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "element_id": self.element_id,
            "source_kind": self.source_kind,
            "content": self.content,
            "estimated_tokens": self.estimated_tokens,
            "reason": self.reason,
            "confidence": self.confidence,
            "freshness": self.freshness,
        }


@dataclass(frozen=True)
class CompiledContext:
    elements: list[ContextElement]
    estimated_tokens: int
    token_budget: int
    truncated: bool = False
    value_density: float = 0.0
    packed_ratio: float = 0.0

    def text(self) -> str:
        return "\n\n".join(el.content for el in self.elements)

    def to_dict(self) -> dict[str, Any]:
        return {
            "elements": [el.to_dict() for el in self.elements],
            "estimated_tokens": self.estimated_tokens,
            "token_budget": self.token_budget,
            "truncated": self.truncated,
            "value_density": round(self.value_density, 4),
            "packed_ratio": round(self.packed_ratio, 4),
        }


@dataclass(frozen=True)
class KnowledgeLink:
    link_id: str
    source_id: str
    target_id: str
    relationship: str
    path: str = ""
    revision: str = ""
    valid: bool = True
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "link_id": self.link_id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relationship": self.relationship,
            "path": self.path,
            "revision": self.revision,
            "valid": self.valid,
            "created_at": self.created_at,
        }


def _estimate_tokens(text: str) -> int:
    return max(1, len(text.strip()) // 4)


class ContextCompiler:
    def __init__(
        self,
        state_store: AgentStateStore,
        *,
        task_store: Any | None = None,
        verification_store: Any | None = None,
        memory_store: Any | None = None,
        incident_store: Any | None = None,
        lease_store: Any | None = None,
    ) -> None:
        self.state_store = state_store
        self.task_store = task_store
        self.verification_store = verification_store
        self.memory_store = memory_store
        self.incident_store = incident_store
        self.lease_store = lease_store
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
                            CREATE TABLE IF NOT EXISTS agent_knowledge_links (
                                link_id TEXT PRIMARY KEY,
                                source_id TEXT NOT NULL,
                                target_id TEXT NOT NULL,
                                relationship TEXT NOT NULL,
                                path TEXT NOT NULL,
                                revision TEXT NOT NULL,
                                valid INTEGER NOT NULL,
                                created_at REAL NOT NULL
                            );
                            """
                        )
                        con.execute(
                            """
                            CREATE INDEX IF NOT EXISTS idx_agent_klinks_path
                            ON agent_knowledge_links (path, valid);
                            """
                        )
                finally:
                    con.close()
            retry_busy(_setup, retries=5, base_delay_seconds=0.02)
            self._initialized = True

    def link(
        self,
        source_id: str,
        target_id: str,
        relationship: str,
        path: str = "",
        revision: str = "",
    ) -> KnowledgeLink:
        self._init_table()
        link_id = f"link_{uuid.uuid4().hex[:12]}"
        now = time.time()
        klink = KnowledgeLink(
            link_id=link_id,
            source_id=source_id,
            target_id=target_id,
            relationship=relationship,
            path=path,
            revision=revision,
            valid=True,
            created_at=now,
        )

        def _do_save() -> None:
            con = connect_sqlite(self.state_store.db_path, isolation_level=None)
            try:
                con.execute("BEGIN IMMEDIATE")
                con.execute(
                    """
                    INSERT INTO agent_knowledge_links (
                        link_id, source_id, target_id, relationship, path, revision, valid, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        klink.link_id,
                        klink.source_id,
                        klink.target_id,
                        klink.relationship,
                        klink.path,
                        klink.revision,
                        1,
                        klink.created_at,
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
        return klink

    def invalidate(self, changed_paths: Collection[str], revision: str = "") -> int:
        if not self.state_store.enabled or not self.state_store.db_path.exists():
            return 0
        paths = [str(p) for p in changed_paths if p]
        if not paths:
            return 0
        self._init_table()

        def _do_invalidate() -> int:
            con = connect_sqlite(self.state_store.db_path, isolation_level=None)
            try:
                con.execute("BEGIN IMMEDIATE")
                placeholders = ",".join("?" for _ in paths)
                cur = con.execute(
                    f"""
                    UPDATE agent_knowledge_links
                    SET valid = 0, revision = ?
                    WHERE valid = 1 AND path IN ({placeholders})
                    """,
                    (revision, *paths),
                )
                count = int(cur.rowcount or 0)
                con.execute("COMMIT")
                return count
            except Exception:
                try:
                    con.execute("ROLLBACK")
                except Exception:
                    pass
                raise
            finally:
                con.close()

        return retry_busy(_do_invalidate, retries=5, base_delay_seconds=0.02)

    def get_active_links(self, path: str) -> list[KnowledgeLink]:
        if not self.state_store.enabled or not self.state_store.db_path.exists():
            return []
        self._init_table()

        def _do_get() -> list[KnowledgeLink]:
            con = connect_sqlite(self.state_store.db_path)
            try:
                cur = con.execute(
                    """
                    SELECT link_id, source_id, target_id, relationship, path, revision, valid, created_at
                    FROM agent_knowledge_links
                    WHERE path = ? AND valid = 1
                    """,
                    (path,),
                )
                return [
                    KnowledgeLink(
                        link_id=row[0],
                        source_id=row[1],
                        target_id=row[2],
                        relationship=row[3],
                        path=row[4],
                        revision=row[5],
                        valid=bool(row[6]),
                        created_at=row[7],
                    )
                    for row in cur.fetchall()
                ]
            finally:
                con.close()

        return retry_busy(_do_get, retries=5, base_delay_seconds=0.02)

    def compile(self, request: ContextRequest) -> CompiledContext:
        # Changed source paths make stored relationship links stale immediately.
        # Invalidation is idempotent and bounded to the explicit paths supplied by
        # the caller, avoiding broad repository-wide link churn.
        if request.changed_paths:
            self.invalidate(request.changed_paths)

        candidates: list[tuple[int, ContextElement]] = []
        pinned_goal: ContextElement | None = None

        # 1. Fresh verification receipts (highest priority: 100)
        if self.verification_store is not None:
            comp_res = self.verification_store.completion(request.task_id)
            for rcpt in comp_res.receipts:
                if rcpt.passed:
                    content = f"Verification receipt for '{rcpt.criterion}': passed (observed at {rcpt.observed_at:.0f})"
                    tokens = _estimate_tokens(content)
                    candidates.append((
                        100,
                        ContextElement(
                            element_id=rcpt.receipt_id,
                            source_kind="verification_receipt",
                            content=content,
                            estimated_tokens=tokens,
                            reason=f"proven verification for acceptance criterion '{rcpt.criterion}'",
                            confidence=1.0,
                            freshness=rcpt.observed_at,
                        ),
                    ))

        # 2. Task goal and checkpoint (priority: 95 / 90)
        if self.task_store is not None:
            task = self.task_store.get(request.task_id)
            if task:
                goal_content = f"Task Goal: {task.contract.goal}\nCriteria: {', '.join(task.contract.acceptance_criteria)}"
                pinned_goal = ContextElement(
                    element_id=f"goal_{task.task_id}",
                    source_kind="task_goal",
                    content=goal_content,
                    estimated_tokens=_estimate_tokens(goal_content),
                    reason="primary task goal and acceptance criteria",
                    confidence=1.0,
                    freshness=task.created_at,
                )
                if task.checkpoint.phase or task.checkpoint.next_action:
                    chk_content = f"Checkpoint: Phase={task.checkpoint.phase}, Next={task.checkpoint.next_action}"
                    candidates.append((
                        90,
                        ContextElement(
                            element_id=f"chk_{task.task_id}",
                            source_kind="task_checkpoint",
                            content=chk_content,
                            estimated_tokens=_estimate_tokens(chk_content),
                            reason="latest resumable task checkpoint",
                            confidence=1.0,
                            freshness=task.updated_at,
                        ),
                    ))

        # 3. Active memory records (priority: 70)
        if self.memory_store is not None:
            records = self.memory_store.find(limit=20)
            for rec in records:
                if rec.status in ("active", "confirmed"):
                    m_content = f"[{rec.kind.value.upper()}] {rec.key}: {rec.value}"
                    candidates.append((
                        70,
                        ContextElement(
                            element_id=rec.record_id,
                            source_kind="memory_record",
                            content=m_content,
                            estimated_tokens=_estimate_tokens(m_content),
                            reason=f"relevant {rec.kind.value} memory",
                            confidence=rec.confidence,
                            freshness=rec.updated_at,
                        ),
                    ))

        # 4. Negative knowledge / incidents (priority: 60 / 50)
        if self.incident_store is not None:
            incidents = self.incident_store.list_incidents(limit=10)
            for inc in incidents:
                if inc.ignored:
                    continue
                if inc.verified_fix:
                    inc_content = f"[VERIFIED FIX] {inc.error_class}: {inc.verified_fix}"
                    candidates.append((
                        60,
                        ContextElement(
                            element_id=inc.incident_id,
                            source_kind="incident_fix",
                            content=inc_content,
                            estimated_tokens=_estimate_tokens(inc_content),
                            reason="verified resolution for prior error",
                            confidence=inc.confidence,
                            freshness=inc.updated_at,
                        ),
                    ))
                elif not inc.resolved:
                    inc_content = f"[NEGATIVE KNOWLEDGE] Prior failure {inc.error_class}: {inc.redacted_message}"
                    candidates.append((
                        50,
                        ContextElement(
                            element_id=inc.incident_id,
                            source_kind="incident",
                            content=inc_content,
                            estimated_tokens=_estimate_tokens(inc_content),
                            reason="preventing repeat failure",
                            confidence=0.9,
                            freshness=inc.updated_at,
                        ),
                    ))

        # 5. Active write leases (priority: 85). Exposing these in compiled
        # context prevents workers from planning edits into scopes already owned
        # by another agent and aligns context compilation with the coordination
        # contract documented for Local AI Hub.
        if self.lease_store is not None and request.root:
            for lease in self.lease_store.list(request.root)[:20]:
                owner = str(lease.get("tenant", ""))
                path = str(lease.get("path", ""))
                purpose = str(lease.get("purpose", ""))
                expires_at = float(lease.get("expires_at", 0.0) or 0.0)
                ownership = "current agent" if request.tenant and owner == request.tenant else owner or "another agent"
                lease_content = f"Active write lease: {path} held by {ownership} for {purpose}"
                candidates.append((
                    85,
                    ContextElement(
                        element_id=str(lease.get("lease_id", "lease")) + ":" + path,
                        source_kind="active_lease",
                        content=lease_content,
                        estimated_tokens=_estimate_tokens(lease_content),
                        reason="active coordination lease for repository edit scope",
                        confidence=1.0,
                        freshness=expires_at,
                    ),
                ))

        if request.include_kinds:
            allowed_kinds = {str(kind).strip().lower() for kind in request.include_kinds if str(kind).strip()}
            candidates = [(prio, el) for prio, el in candidates if el.source_kind.lower() in allowed_kinds]
            if pinned_goal is not None and pinned_goal.source_kind.lower() not in allowed_kinds:
                pinned_goal = None

        selected: list[tuple[int, ContextElement]] = []
        spent_tokens = 0
        truncated = False

        # Pin mandatory task goal contract first if budget allows
        if pinned_goal is not None:
            if pinned_goal.estimated_tokens <= request.token_budget:
                selected.append((95, pinned_goal))
                spent_tokens += pinned_goal.estimated_tokens
            else:
                truncated = True

        # Value-density knapsack token budgeting for remaining candidates
        # Score = (priority * confidence) / max(1, tokens)
        ranked_candidates: list[tuple[float, int, ContextElement]] = []
        for prio, el in candidates:
            score = (prio * el.confidence) / max(1, el.estimated_tokens)
            ranked_candidates.append((score, prio, el))

        # Sort primarily by value density DESC, then priority DESC, freshness DESC
        ranked_candidates.sort(key=lambda x: (x[0], x[1], x[2].freshness), reverse=True)

        for _, prio, el in ranked_candidates:
            if spent_tokens + el.estimated_tokens <= request.token_budget:
                selected.append((prio, el))
                spent_tokens += el.estimated_tokens
            else:
                truncated = True

        # Presentation ordering: sort final prompt context by priority weight DESC, freshness DESC
        selected.sort(key=lambda x: (x[0], x[1].freshness), reverse=True)
        final_elements = [el for _, el in selected]

        total_value = sum(prio * el.confidence for prio, el in selected)
        value_density = total_value / max(1, spent_tokens) if spent_tokens > 0 else 0.0
        packed_ratio = spent_tokens / request.token_budget if request.token_budget > 0 else 0.0

        return CompiledContext(
            elements=final_elements,
            estimated_tokens=spent_tokens,
            token_budget=request.token_budget,
            truncated=truncated,
            value_density=value_density,
            packed_ratio=packed_ratio,
        )
