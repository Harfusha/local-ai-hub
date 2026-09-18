from __future__ import annotations

from .json_utils import dumps as json_dumps

import hashlib
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from dataclasses import replace
from pathlib import Path
from typing import Any, Collection, Mapping

from .agent_events import AgentStateStore
from .agent_memory import MemoryStatus, MemoryStore
from .sqlite_support import connect_sqlite, retry_busy


@dataclass(frozen=True)
class ContextRequest:
    task_id: str
    token_budget: int = 4000
    include_kinds: tuple[str, ...] = ()
    changed_paths: tuple[str, ...] = ()
    root: str = ""
    tenant: str = ""
    include_diagnostics: bool = False
    clone_id: str = ""
    worktree_id: str = ""
    branch: str = ""
    repository_id: str = ""
    session_id: str = ""
    repository_revision: str = ""
    phase: str = ""
    focus: tuple[str, ...] = ()
    preload_profile: str = ""
    repo_revision: str = ""
    since_hash: str = ""


@dataclass(frozen=True)
class ContextElement:
    element_id: str
    source_kind: str
    content: str
    estimated_tokens: int
    reason: str
    confidence: float = 1.0
    freshness: float = 0.0
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self, compact: bool = False) -> dict[str, Any]:
        if compact:
            res: dict[str, Any] = {
                "element_id": self.element_id,
                "source_kind": self.source_kind,
                "content": self.content,
            }
            if self.reason:
                res["reason"] = self.reason
            return res
        return {
            "element_id": self.element_id,
            "source_kind": self.source_kind,
            "content": self.content,
            "estimated_tokens": self.estimated_tokens,
            "reason": self.reason,
            "confidence": self.confidence,
            "freshness": self.freshness,
            **({"provenance": dict(self.provenance)} if self.provenance else {}),
        }


@dataclass(frozen=True)
class CompiledContext:
    elements: list[ContextElement]
    estimated_tokens: int
    token_budget: int
    truncated: bool = False
    value_density: float = 0.0
    packed_ratio: float = 0.0
    phase: str = ""
    repo_revision: str = ""
    stale: bool = False
    warnings: tuple[dict[str, Any], ...] = ()
    delta_from: str = ""
    unchanged: bool = False

    def text(self) -> str:
        return "\n\n".join(el.content for el in self.elements)

    def etag(self) -> str:
        h = hashlib.sha1(usedforsecurity=False)
        h.update(self.phase.encode("utf-8"))
        h.update(self.repo_revision.encode("utf-8"))
        for el in self.elements:
            h.update(el.element_id.encode("utf-8"))
            h.update(el.content.encode("utf-8"))
        return h.hexdigest()[:12]

    def to_dict(self, compact: bool = False) -> dict[str, Any]:
        d: dict[str, Any] = {
            "elements": [el.to_dict(compact=compact) for el in self.elements],
            "estimated_tokens": self.estimated_tokens,
            "token_budget": self.token_budget,
            "etag": self.etag(),
        }
        if not compact:
            d.update({
                "truncated": self.truncated,
                "value_density": round(self.value_density, 4),
                "packed_ratio": round(self.packed_ratio, 4),
            })
        d.update({
            "phase": self.phase,
            "repo_revision": self.repo_revision,
            "stale": self.stale,
            "warnings": [dict(warning) for warning in self.warnings],
            "delta_from": self.delta_from,
            "unchanged": self.unchanged,
        })
        return d


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
        blackboard: Any | None = None,
        config: Mapping[str, Any] | None = None,
    ) -> None:
        self.state_store = state_store
        self.task_store = task_store
        self.verification_store = verification_store
        self.memory_store = memory_store
        self.incident_store = incident_store
        self.lease_store = lease_store
        self.blackboard = blackboard
        self.config = dict(config or {})
        self._lock = threading.RLock()
        self._initialized = False
        self._context_history: dict[str, tuple[ContextElement, ...]] = {}
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

    @staticmethod
    def _normalise_changed_paths(
        changed_paths: Collection[str] | str | None,
        root: str = "",
    ) -> tuple[tuple[str, ...], bool]:
        raw_paths = (changed_paths,) if isinstance(changed_paths, str) else (changed_paths or ())
        paths: list[str] = []
        seen: set[str] = set()
        truncated = False
        for path in raw_paths:
            if path is None or not str(path).strip() or str(path).strip().lower() == "none":
                continue
            raw_path = str(path)
            normalized = (
                MemoryStore._canonical_repo_path(root, raw_path)
                if root
                else os.path.normcase(os.path.normpath(raw_path.replace("\\", "/"))).replace("\\", "/").strip("/")
            )
            if normalized in seen:
                continue
            seen.add(normalized)
            if len(paths) >= 32:
                truncated = True
                continue
            paths.append(normalized)
        return tuple(paths), truncated

    def invalidate(
        self,
        changed_paths: Collection[str],
        revision: str = "",
        *,
        root: str = "",
    ) -> int:
        if not self.state_store.enabled or not self.state_store.db_path.exists():
            return 0
        paths, _ = self._normalise_changed_paths(changed_paths, root)
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

    def _preload_config(self, request: ContextRequest) -> dict[str, Any]:
        context_config = self.config.get("context", {})
        raw = context_config.get("preloads", {}) if isinstance(context_config, Mapping) else {}
        if not isinstance(raw, Mapping):
            return {}
        settings = dict(raw)
        profile = request.preload_profile.strip()
        profiles = raw.get("profiles", {})
        if profile and isinstance(profiles, Mapping) and isinstance(profiles.get(profile), Mapping):
            settings.update(profiles[profile])
        elif profile and isinstance(raw.get(profile), Mapping):
            settings.update(raw[profile])
        return settings

    @staticmethod
    def _warning(code: str, message: str, **details: Any) -> dict[str, Any]:
        return {"code": code, "message": message, **details}

    def _load_preloads(
        self,
        request: ContextRequest,
        warnings: list[dict[str, Any]],
    ) -> list[tuple[int, ContextElement]]:
        settings = self._preload_config(request)
        root = Path(request.root).resolve() if request.root else None
        if root is None:
            return []
        try:
            max_files = max(0, min(int(settings.get("max_files", 8)), 32))
            max_bytes = max(0, min(int(settings.get("max_bytes", 16000)), 256000))
            max_memory = max(0, min(int(settings.get("max_memory", 8)), 32))
        except (TypeError, ValueError):
            warnings.append(self._warning("preload_invalid_bounds", "preload bounds must be integers"))
            return []

        candidates: list[Path] = []
        configured_files = settings.get("files", ())
        if isinstance(configured_files, str):
            configured_files = (configured_files,)
        for value in configured_files or ():
            path = Path(str(value)).expanduser()
            candidates.append(path if path.is_absolute() else root / path)
        patterns = settings.get("patterns", ())
        if isinstance(patterns, str):
            patterns = (patterns,)
        for pattern in patterns or ():
            try:
                candidates.extend(sorted(root.glob(str(pattern))))
            except (ValueError, OSError):
                warnings.append(self._warning("preload_invalid_pattern", f"invalid preload pattern: {pattern}"))

        elements: list[tuple[int, ContextElement]] = []
        seen_paths: set[str] = set()
        seen_hashes: set[str] = set()
        used_bytes = 0
        for path in candidates:
            normalized_path = os.path.normcase(os.path.abspath(str(path))).replace("\\", "/")
            if normalized_path in seen_paths:
                continue
            seen_paths.add(normalized_path)
            if len(elements) >= max_files:
                break
            if not path.is_file():
                warnings.append(self._warning("preload_missing_file", f"preload file not found: {path.name}", path=normalized_path))
                continue
            try:
                raw_content = path.read_bytes()
            except OSError as exc:
                warnings.append(self._warning("preload_read_error", f"could not read preload file: {path.name}", error=type(exc).__name__))
                continue
            remaining = max_bytes - used_bytes
            if remaining <= 0:
                break
            content_bytes = raw_content[:remaining]
            content_hash = hashlib.sha256(content_bytes).hexdigest()
            if content_hash in seen_hashes:
                continue
            seen_hashes.add(content_hash)
            used_bytes += len(content_bytes)
            content = content_bytes.decode("utf-8", errors="replace")
            evidence_id = f"preload_{content_hash[:12]}"
            elements.append((
                88,
                ContextElement(
                    element_id=evidence_id,
                    source_kind="preload",
                    content=content,
                    estimated_tokens=_estimate_tokens(content),
                    reason="configured bounded repository preload",
                    confidence=1.0,
                    freshness=path.stat().st_mtime,
                    provenance={
                        "path": normalized_path,
                        "content_hash": content_hash,
                        "evidence_ids": (evidence_id,),
                    },
                ),
            ))

        memory_kinds = settings.get("memory_kinds", ())
        if isinstance(memory_kinds, str):
            memory_kinds = (memory_kinds,)
        if self.memory_store is not None and memory_kinds and max_memory:
            find_for_context = getattr(self.memory_store, "find_for_context", None)
            if callable(find_for_context):
                try:
                    records = find_for_context(
                        root=request.root,
                        task_id=request.task_id,
                        tenant=request.tenant or request.session_id,
                        clone_id=request.clone_id,
                        worktree_id=request.worktree_id,
                        branch=request.branch,
                        include_kinds=tuple(str(kind) for kind in memory_kinds),
                        limit=max_memory,
                    )
                except TypeError:
                    records = find_for_context(root=request.root, task_id=request.task_id, limit=max_memory)
                for record in records[:max_memory]:
                    content = f"[{record.kind.value.upper()}] {record.key}: {record.value}"
                    evidence_ids = tuple(record.evidence_ids)
                    elements.append((
                        86,
                        ContextElement(
                            element_id=f"preload_memory_{record.record_id}",
                            source_kind="preload_memory",
                            content=content,
                            estimated_tokens=_estimate_tokens(content),
                            reason="configured memory-kind preload",
                            confidence=record.confidence,
                            freshness=record.updated_at,
                            provenance={"record_id": record.record_id, "evidence_ids": evidence_ids},
                        ),
                    ))
        return elements

    @staticmethod
    def _phase_priority(request: ContextRequest, priority: int, element: ContextElement) -> int:
        phase = request.phase.strip().lower()
        kind = element.source_kind.lower()
        content = element.content.lower()
        focus = " ".join(request.focus).lower()
        if phase == "plan":
            if kind in {"task_goal", "task_checkpoint"} or "unknown" in kind or "unknown" in content:
                return priority + 55
        elif phase == "edit":
            if kind in {"exact_symbol", "reuse_candidate"} or "reusable_candidate" in content or "exact symbol" in focus:
                return priority + 65
            if "symbol_refs" in str(element.provenance) or element.provenance.get("symbol_refs"):
                return priority + 45
        elif phase == "review":
            if kind in {"incident", "incident_fix", "repository_context", "changed_paths", "memory_diagnostics"}:
                return priority + 55
        elif phase == "test":
            if kind in {"verification_receipt", "affected_test", "test_receipt"}:
                return priority + 65
        elif phase == "handoff":
            if kind in {"task_checkpoint", "decision", "memory_record"} and ("decision" in content or kind == "task_checkpoint"):
                return priority + 55
        return priority

    def compile(self, request: ContextRequest) -> CompiledContext:
        # Changed source paths make stored relationship links stale immediately.
        # Invalidation is idempotent and bounded to the explicit paths supplied by
        # the caller, avoiding broad repository-wide link churn.
        candidates: list[tuple[int, ContextElement]] = []
        warnings: list[dict[str, Any]] = []
        pinned_goal: ContextElement | None = None
        effective_revision = request.repo_revision or request.repository_revision
        changed_paths, changed_paths_truncated = self._normalise_changed_paths(
            request.changed_paths,
            request.root,
        )
        if changed_paths:
            if self.memory_store is not None and request.root and effective_revision:
                mark_stale = getattr(self.memory_store, "mark_stale_for_revision", None)
                if callable(mark_stale):
                    mark_stale(request.root, effective_revision, changed_paths)
            self.invalidate(
                changed_paths,
                revision=effective_revision,
                root=request.root,
            )

        if changed_paths:
            change_content = (
                "[REPOSITORY CHANGES] "
                f"revision={effective_revision or 'unknown'} paths={', '.join(changed_paths)}"
            )
            candidates.append((
                82,
                ContextElement(
                    element_id="repository_changes",
                    source_kind="changed_paths",
                    content=change_content,
                    estimated_tokens=_estimate_tokens(change_content),
                    reason="bounded changed repository paths",
                    confidence=1.0,
                    freshness=time.time(),
                    provenance={"evidence_ids": ("repository_changes",), "paths": changed_paths},
                ),
            ))

        if not self.state_store.enabled:
            warnings.append(self._warning(
                "agent_state_disabled",
                "Agent OS state is disabled; compiled context is stateless and repository-scoped only",
            ))
            if request.root:
                stateless_content = (
                    "[STATELESS REPOSITORY CONTEXT] "
                    f"root={os.path.abspath(request.root)} "
                    f"revision={effective_revision or 'unknown'} "
                    f"changed_paths={', '.join(changed_paths) or 'none'}"
                )
                candidates.append((
                    78,
                    ContextElement(
                        element_id="stateless_repository_context",
                        source_kind="repository_context",
                        content=stateless_content,
                        estimated_tokens=_estimate_tokens(stateless_content),
                        reason="stateless repository facts remain available when Agent OS is disabled",
                        confidence=1.0,
                        freshness=time.time(),
                        provenance={"evidence_ids": ("stateless_repository_context",)},
                    ),
                ))

        candidates.extend(self._load_preloads(request, warnings))
        if changed_paths_truncated and request.include_diagnostics:
            diagnostic_content = (
                "[CONTEXT DIAGNOSTICS] changed_paths_truncated=true "
                f"kept={len(changed_paths)} limit=32"
            )
            candidates.append((55, ContextElement(
                element_id="context_diagnostics",
                source_kind="context_diagnostics",
                content=diagnostic_content,
                estimated_tokens=_estimate_tokens(diagnostic_content),
                reason="bounded changed-path invalidation diagnostics",
                confidence=1.0,
                freshness=time.time(),
            )))

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
            context_tenant = request.tenant or request.session_id
            find_for_context = getattr(self.memory_store, "find_for_context", None)
            if callable(find_for_context):
                records = find_for_context(
                    root=request.root,
                    task_id=request.task_id,
                    tenant=context_tenant,
                    clone_id=request.clone_id,
                    worktree_id=request.worktree_id,
                    branch=request.branch,
                    limit=20,
                )
            else:
                # A generic store cannot guarantee SQL-side status/scope/root
                # filtering before its limit. Omit memory rather than allowing
                # unrelated records to crowd out matching context.
                records = []
            excluded_memory: dict[str, dict[str, Any]] = {
                status: {"count": 0, "ids": []}
                for status in (
                    MemoryStatus.STALE.value,
                    MemoryStatus.QUARANTINED.value,
                    MemoryStatus.REJECTED.value,
                    MemoryStatus.SUPERSEDED.value,
                    "legacy_unscoped",
                )
            }
            diagnostic_summary = None
            summary_fn = getattr(self.memory_store, "diagnostic_summary", None)
            if request.include_diagnostics and callable(summary_fn):
                try:
                    diagnostic_summary = summary_fn(
                        id_limit=8,
                        root=request.root,
                        task_id=request.task_id,
                        tenant=context_tenant,
                        clone_id=request.clone_id,
                        worktree_id=request.worktree_id,
                        branch=request.branch,
                    )
                except Exception:
                    diagnostic_summary = None
            if diagnostic_summary is not None:
                for status, data in diagnostic_summary.items():
                    if status in excluded_memory and isinstance(data, dict):
                        excluded_memory[status] = {
                            "count": int(data.get("count", 0) or 0),
                            "ids": [str(record_id) for record_id in list(data.get("ids") or [])[:8]],
                        }
            for rec in records:
                status_value = rec.status.value if hasattr(rec.status, "value") else str(rec.status)
                if status_value in excluded_memory:
                    if diagnostic_summary is None:
                        excluded_memory[status_value]["count"] += 1
                        if len(excluded_memory[status_value]["ids"]) < 8:
                            excluded_memory[status_value]["ids"].append(rec.record_id)
                    continue
                if status_value in (MemoryStatus.ACTIVE.value, MemoryStatus.CONFIRMED.value):
                    m_content = f"[{rec.kind.value.upper()}] {rec.key}: {rec.value}"
                    memory_provenance = {
                        key: value
                        for key, value in {
                            "repository_revision": rec.repository_revision,
                            "path_refs": list(rec.path_refs),
                            "symbol_refs": list(rec.symbol_refs),
                            "related_task": rec.related_task,
                            "evidence_ids": list(rec.evidence_ids),
                        }.items()
                        if value not in (None, [], ())
                    }
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
                            provenance=memory_provenance,
                        ),
                    ))
            if request.include_diagnostics:
                stale = excluded_memory[MemoryStatus.STALE.value]
                quarantined = excluded_memory[MemoryStatus.QUARANTINED.value]
                rejected = excluded_memory[MemoryStatus.REJECTED.value]
                superseded = excluded_memory[MemoryStatus.SUPERSEDED.value]
                legacy_unscoped = excluded_memory["legacy_unscoped"]
                diagnostic_content = (
                    "[MEMORY DIAGNOSTICS] "
                    f"stale_count={stale['count']} quarantined_count={quarantined['count']} "
                    f"rejected_count={rejected['count']} "
                    f"superseded_count={superseded['count']} stale_ids={','.join(stale['ids'])} "
                    f"quarantined_ids={','.join(quarantined['ids'])} "
                    f"rejected_ids={','.join(rejected['ids'])} superseded_ids={','.join(superseded['ids'])} "
                    f"legacy_unscoped_count={legacy_unscoped['count']} "
                    f"legacy_unscoped_ids={','.join(legacy_unscoped['ids'])}"
                )
                candidates.append((
                    55,
                    ContextElement(
                        element_id="memory_diagnostics",
                        source_kind="memory_diagnostics",
                        content=diagnostic_content[:1200],
                        estimated_tokens=_estimate_tokens(diagnostic_content[:1200]),
                        reason="bounded diagnostics for excluded memory records",
                        confidence=1.0,
                        freshness=time.time(),
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

        # 6. Blackboard state (priority: 65)
        if getattr(self, "blackboard", None) is not None:
            boards_to_check: list[str] = []
            if request.task_id:
                boards_to_check.extend([request.task_id, f"task:{request.task_id}", f"swarm:{request.task_id}"])
            boards_to_check.append("global")
            for b_id in boards_to_check:
                try:
                    res = self.blackboard.get(b_id)
                    if isinstance(res, dict) and res.get("success") and "sections" in res:
                        for s_name, s_data in res["sections"].items():
                            s_dict = s_data if isinstance(s_data, dict) else (s_data.to_dict() if hasattr(s_data, "to_dict") else {})
                            raw_cnt = s_dict.get("content", "")
                            content_str = json_dumps(raw_cnt) if not isinstance(raw_cnt, str) else raw_cnt
                            bb_content = f"[BLACKBOARD {b_id}:{s_name}] {content_str}"
                            candidates.append((
                                65,
                                ContextElement(
                                    element_id=f"bb_{b_id}_{s_name}",
                                    source_kind="blackboard",
                                    content=bb_content,
                                    estimated_tokens=_estimate_tokens(bb_content),
                                    reason=f"shared blackboard state on board '{b_id}'",
                                    confidence=1.0,
                                    freshness=float(s_dict.get("timestamp", 0.0) or 0.0),
                                ),
                            ))
                except Exception:
                    pass

        if request.include_kinds:
            allowed_kinds = {str(kind).strip().lower() for kind in request.include_kinds if str(kind).strip()}
            candidates = [(prio, el) for prio, el in candidates if el.source_kind.lower() in allowed_kinds]
            if pinned_goal is not None and pinned_goal.source_kind.lower() not in allowed_kinds:
                pinned_goal = None

        candidates = [
            (self._phase_priority(request, priority, element), element)
            for priority, element in candidates
        ]
        pinned_goal_priority = self._phase_priority(request, 95, pinned_goal) if pinned_goal is not None else 95

        selected: list[tuple[int, ContextElement]] = []
        spent_tokens = 0
        truncated = False

        # Pin mandatory task goal contract first if budget allows
        if pinned_goal is not None:
            if pinned_goal.estimated_tokens <= request.token_budget:
                selected.append((pinned_goal_priority, pinned_goal))
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

        compiled = CompiledContext(
            elements=final_elements,
            estimated_tokens=spent_tokens,
            token_budget=request.token_budget,
            truncated=truncated,
            value_density=value_density,
            packed_ratio=packed_ratio,
            phase=request.phase,
            repo_revision=effective_revision,
            stale=not self.state_store.enabled,
            warnings=tuple(warnings[:32]),
        )
        current_etag = compiled.etag()
        if request.since_hash:
            if request.since_hash == current_etag:
                compiled = replace(
                    compiled,
                    elements=[],
                    estimated_tokens=0,
                    value_density=0.0,
                    packed_ratio=0.0,
                    truncated=False,
                    delta_from=request.since_hash,
                    unchanged=True,
                )
            else:
                previous = self._context_history.get(request.since_hash)
                if previous is not None:
                    previous_by_id = {element.element_id: element.content for element in previous}
                    delta_elements = [
                        element for element in compiled.elements
                        if previous_by_id.get(element.element_id) != element.content
                    ]
                    delta_tokens = sum(element.estimated_tokens for element in delta_elements)
                    compiled = replace(
                        compiled,
                        elements=delta_elements,
                        estimated_tokens=delta_tokens,
                        value_density=(sum(element.confidence for element in delta_elements) / max(1, delta_tokens)),
                        packed_ratio=(delta_tokens / request.token_budget if request.token_budget > 0 else 0.0),
                        delta_from=request.since_hash,
                    )
                else:
                    compiled = replace(compiled, delta_from=request.since_hash)
        self._context_history[current_etag] = tuple(final_elements)
        if len(self._context_history) > 32:
            oldest = next(iter(self._context_history))
            self._context_history.pop(oldest, None)
        return compiled
