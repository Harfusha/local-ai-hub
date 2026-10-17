from __future__ import annotations

from .json_utils import dumps as json_dumps

import hashlib
import json
import logging
import math
import os
import re
import sqlite3
import threading
import time
import uuid
from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Collection, Mapping

from .agent_events import AgentEvent, AgentStateStore
from .agent_identity import AgentScope
from .sqlite_support import connect_sqlite, retry_busy

_logger = logging.getLogger(__name__)

_TASK_MEMORY_QUERY: ContextVar[tuple[Any, tuple[str, str, str], frozenset[str]] | None] = ContextVar(
    "agent_task_memory_query", default=None,
)
_GOAL_STOP_WORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in",
    "is", "it", "of", "on", "or", "the", "this", "to", "with", "fix",
    "change", "implement", "improve", "update", "task", "goal", "feature",
    "a", "ale", "do", "je", "na", "pro", "se", "to", "v", "ve", "z", "ze",
    "oprav", "upravit", "implementuj", "změň",
})


def _goal_words(value: str, *, max_words: int | None = 24) -> frozenset[str]:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    words = re.findall(r"[^\W_]+", value.casefold(), flags=re.UNICODE)
    words = [word for word in words if len(word) >= 2 and word not in _GOAL_STOP_WORDS]
    # An English plural is also a useful match for singular task keywords.
    selected = words if max_words is None else words[:max_words]
    expanded = [part for word in selected for part in (word, word[:-1] if len(word) > 4 and word.endswith("s") else word)]
    return frozenset(expanded)


def _task_memory_relevance(kind: str, scope: str, scope_id: str, key: str, value: str | None,
                           terms: frozenset[str], task_id: str) -> int:
    base_score = 400 if scope == AgentScope.TASK.value and scope_id == task_id else 1 if kind == "convention" else 0
    try:
        decoded = json.loads(value) if value else ""
    except (TypeError, ValueError):
        return base_score
    text = decoded if isinstance(decoded, str) else json_dumps(decoded, ensure_ascii=False)
    return base_score + 10 * len(terms.intersection(_goal_words(f"{key} {text}", max_words=None)))


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
    FINDING = "finding"
    REUSABLE_CANDIDATE = "reusable_candidate"
    CONTRACT_MAPPING = "contract_mapping"
    REJECTED_APPROACH = "rejected_approach"
    UNKNOWN = "unknown"
    VALIDATION = "validation"


class MemoryStatus(str, Enum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    CONFIRMED = "confirmed"
    QUARANTINED = "quarantined"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"
    STALE = "stale"


def _memory_event_stream_id(scope: AgentScope, scope_id: str | None, key: str) -> str:
    parts = (scope.value, scope_id or "", key)
    return "memory:" + "".join(f"{len(part)}:{part}" for part in parts)




def _normalise_scope_root(value: str) -> str:
    return os.path.normcase(os.path.abspath(os.path.normpath(str(value).replace("\\", "/")))).replace("\\", "/")


def _memory_deletion_event(con: Any, *, record_id: str) -> AgentEvent | None:
    rows = con.execute(
        """
        SELECT stream_id, seq, event_id, kind, payload, idempotency_key,
               correlation_id, actor, created_at
        FROM agent_events
        WHERE kind = 'memory.deleted' AND idempotency_key = ?
        """,
        (f"deleted_{record_id}",),
    ).fetchall()
    for row in rows:
        event = AgentEvent.from_row(row)
        if str(event.payload.get("record_id", "")) != record_id:
            raise ValueError("memory deletion idempotency key collision")
        return event
    return None


def _memory_matches_request_scope(
    *,
    scope: Any,
    scope_id: str,
    provenance: Mapping[str, Any] | None,
    root: str,
    task_id: str,
    tenant: str,
    session_id: str = "",
    clone_id: str = "",
    worktree_id: str = "",
    branch: str = "",
) -> bool:
    if not isinstance(scope, AgentScope):
        return False
    scope_value = scope.value
    if scope_value == AgentScope.REPOSITORY.value:
        if not isinstance(provenance, Mapping) or not isinstance(tenant, str):
            return False
        record_root = str(provenance.get("root") or "")
        record_tenant = provenance.get("tenant")
        if not isinstance(record_tenant, str) or not record_tenant or not tenant:
            return False
        if not (root and _normalise_scope_root(record_root) == _normalise_scope_root(root)):
            return False
        return tenant == record_tenant
    if scope_value == AgentScope.TASK.value:
        if not isinstance(provenance, Mapping) or not isinstance(tenant, str):
            return False
        record_root = str(provenance.get("root") or "").strip()
        record_tenant = provenance.get("tenant")
        requested_root = str(root or "").strip()
        requested_task_id = str(task_id or "").strip()
        if not isinstance(record_tenant, str) or not all(
            (requested_root, tenant, record_root, record_tenant, requested_task_id)
        ):
            return False
        if str(scope_id or "").strip() != requested_task_id:
            return False
        if _normalise_scope_root(record_root) != _normalise_scope_root(requested_root):
            return False
        return tenant == record_tenant
    if scope_value == AgentScope.SESSION.value:
        if not isinstance(provenance, Mapping) or not isinstance(tenant, str):
            return False
        record_tenant = provenance.get("tenant")
        if not isinstance(record_tenant, str) or not record_tenant or not tenant:
            return False
        requested_session = str(session_id or "").strip()
        if not requested_session or str(scope_id or "").strip() != requested_session:
            return False
        return tenant == record_tenant
    if scope_value == AgentScope.CLONE.value:
        return bool(clone_id) and scope_id == clone_id
    if scope_value == AgentScope.WORKTREE.value:
        return bool(worktree_id) and scope_id == worktree_id
    if scope_value == AgentScope.BRANCH.value:
        return bool(branch) and scope_id == branch
    return scope_value == AgentScope.GLOBAL.value


def _memory_conflict_context_matches(left: MemoryRecord, right: MemoryRecord) -> bool:
    """Keep contradiction detection inside the same identity context."""
    left_scope = left.scope.value if hasattr(left.scope, "value") else str(left.scope)
    right_scope = right.scope.value if hasattr(right.scope, "value") else str(right.scope)
    if left_scope != right_scope or left.scope_id != right.scope_id:
        return False
    left_provenance = left.provenance or {}
    right_provenance = right.provenance or {}
    left_root = str(left_provenance.get("root") or "")
    right_root = str(right_provenance.get("root") or "")
    if bool(left_root) != bool(right_root):
        return False
    if left_root and _normalise_scope_root(left_root) != _normalise_scope_root(right_root):
        return False
    for identity_key in ("repository_id", "tenant", "task_id", "session_id", "clone_id", "worktree_id", "branch"):
        left_value = str(left_provenance.get(identity_key) or "")
        right_value = str(right_provenance.get(identity_key) or "")
        if bool(left_value) != bool(right_value) or (left_value and left_value != right_value):
            return False
    return True


_CONTEXT_ROOT_VALUE_SQL = (
    "json_extract(CASE WHEN json_valid(provenance) THEN provenance ELSE '{}' END, '$.root')"
)
_CONTEXT_ROOT_SQL = (
    "canonical_scope_root(json_extract("
    "CASE WHEN json_valid(provenance) THEN provenance ELSE '{}' END, '$.root'))"
)
_MEMORY_PRIVATE_FIELD_PARTS = {"content", "output", "prompt", "raw", "source", "text", "transcript"}
_MEMORY_SECRET_FIELD_PARTS = {"authorization", "credential", "password", "secret", "token"}
_MEMORY_SECRET_FIELD_NAMES = {
    "access_key", "access_token", "api_key", "authorization", "client_secret",
    "credential", "password", "private_key", "refresh_token", "secret", "token",
}
_MEMORY_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|secret|authorization|credential)\s*([=:])\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_MEMORY_PROMPT_SOURCE_RE = re.compile(
    r"(?is)\b(prompt|source(?:\s+text)?|raw[_ -]?(?:source|text)|transcript)\s*([=:])\s*.*$"
)
_MEMORY_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_MEMORY_TOKEN_RE = re.compile(r"\b(?:sk|rk)-[A-Za-z0-9_-]{16,}\b|\bgh[pousr]_[A-Za-z0-9_]{12,}\b|\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
_MAX_STALE_CHANGED_PATHS = 32
MAX_MEMORY_QUERY_LIMIT = 100


def _bounded_memory_limit(limit: int, cap: int = MAX_MEMORY_QUERY_LIMIT) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError) as exc:
        raise ValueError("memory limit must be an integer") from exc
    effective_cap = max(1, min(int(cap), MAX_MEMORY_QUERY_LIMIT))
    return max(1, min(value, effective_cap))


def _context_scope_sql(
    *,
    root: str,
    task_id: str,
    tenant: str,
    session_id: str = "",
    clone_id: str,
    worktree_id: str,
    branch: str,
    coordination_id: str = "",
) -> tuple[str, list[Any]]:
    if not isinstance(tenant, str):
        raise ValueError("tenant must be a string")
    root = str(root or "").strip()
    canonical_root = _normalise_scope_root(root) if root else ""
    provenance_tenant = (
        "json_extract(CASE WHEN json_valid(provenance) THEN provenance ELSE '{}' END, "
        "'$.tenant')"
    )
    global_conditions = ["scope = ?"]
    params: list[Any] = [AgentScope.GLOBAL.value]
    if tenant:
        global_conditions.append(
            f"({provenance_tenant} IS NULL OR {provenance_tenant} = '' OR {provenance_tenant} = ?)"
        )
        params.append(tenant)
    else:
        global_conditions.append(f"({provenance_tenant} IS NULL OR {provenance_tenant} = '')")
    clauses = ["(" + " AND ".join(global_conditions) + ")"]

    def add_scoped_identity(scope_value: str, identity_value: str = "") -> None:
        identity_value = str(identity_value or "").strip()
        if scope_value != AgentScope.REPOSITORY.value and not identity_value:
            return
        if scope_value == AgentScope.REPOSITORY.value and not (root and tenant):
            return
        if scope_value == AgentScope.SESSION.value and not tenant:
            return
        if scope_value == AgentScope.TASK.value and not (root and tenant):
            return
        conditions = ["scope = ?"]
        identity_params: list[Any] = [scope_value]
        if scope_value == AgentScope.REPOSITORY.value:
            if root:
                conditions.append(f"{_CONTEXT_ROOT_SQL} = ?")
                identity_params.append(canonical_root)
            else:
                conditions.append(f"{_CONTEXT_ROOT_SQL} = ''")
        else:
            conditions.append("scope_id = ?")
            identity_params.append(identity_value)
            if root:
                conditions.append(f"{_CONTEXT_ROOT_SQL} = ?")
                identity_params.append(canonical_root)
            else:
                conditions.append(f"{_CONTEXT_ROOT_SQL} = ''")
        if tenant:
            conditions.append(f"{provenance_tenant} = ?")
            identity_params.append(tenant)
        else:
            conditions.append(f"({provenance_tenant} IS NULL OR {provenance_tenant} = '')")
        clauses.append("(" + " AND ".join(conditions) + ")")
        params.extend(identity_params)

    coordination_id = str(coordination_id or "").strip()
    # Repository memory requires trusted repository identity and exact tenant.
    if tenant and coordination_id:
        shared_repository = [
            "scope = ?",
            f"{provenance_tenant} = ?",
            "json_extract(CASE WHEN json_valid(provenance) THEN provenance ELSE '{}' END, '$.repository_id') = ?",
        ]
        clauses.append("(" + " AND ".join(shared_repository) + ")")
        params.extend([AgentScope.REPOSITORY.value, tenant, coordination_id])
    add_scoped_identity(AgentScope.TASK.value, task_id)
    add_scoped_identity(AgentScope.SESSION.value, session_id)
    add_scoped_identity(AgentScope.CLONE.value, clone_id)
    add_scoped_identity(AgentScope.WORKTREE.value, worktree_id)
    add_scoped_identity(AgentScope.BRANCH.value, branch)
    return "(" + " OR ".join(clauses) + ")", params


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
        repository_revision: str | None = None,
        path_refs: tuple[str, ...] | list[str] = (),
        symbol_refs: tuple[str, ...] | list[str] = (),
        related_task: str | None = None,
        contradicts_record_id: str | None = None,
        supersedes_record_id: str | None = None,
        quarantine_reason: str | None = None,
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

        provenance_data = dict(provenance or {})
        if repository_revision is not None:
            provenance_data["repository_revision"] = repository_revision
        if path_refs:
            provenance_data["path_refs"] = list(path_refs)
        if symbol_refs:
            provenance_data["symbol_refs"] = list(symbol_refs)
        if related_task is not None:
            provenance_data["related_task"] = related_task

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
            contradicts_record_id=contradicts_record_id,
            supersedes_record_id=supersedes_record_id,
            quarantine_reason=quarantine_reason,
            provenance=provenance_data,
            created_at=now,
            updated_at=now,
            expires_at=expires_at,
        )

    @property
    def repository_revision(self) -> str | None:
        value = self.provenance.get("repository_revision") if isinstance(self.provenance, Mapping) else None
        return str(value) if value is not None else None

    @staticmethod
    def _provenance_refs(value: Any) -> tuple[str, ...]:
        if isinstance(value, str):
            return (value,) if value else ()
        if isinstance(value, (list, tuple, set, frozenset)):
            return tuple(str(item) for item in value if item is not None and str(item))
        return ()

    @property
    def path_refs(self) -> tuple[str, ...]:
        value = self.provenance.get("path_refs") if isinstance(self.provenance, Mapping) else None
        return self._provenance_refs(value)

    @property
    def symbol_refs(self) -> tuple[str, ...]:
        value = self.provenance.get("symbol_refs") if isinstance(self.provenance, Mapping) else None
        return self._provenance_refs(value)

    @property
    def related_task(self) -> str | None:
        value = self.provenance.get("related_task") if isinstance(self.provenance, Mapping) else None
        return str(value) if value is not None else None

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
        safe = _sanitise_memory_record(self, reject_sensitive=False)
        return {
            "record_id": safe.record_id,
            "kind": safe.kind.value,
            "scope": safe.scope.value,
            "scope_id": safe.scope_id,
            "key": safe.key,
            "value": safe.value,
            "confidence": safe.confidence,
            "status": safe.status.value,
            "source": safe.source,
            "evidence_ids": list(safe.evidence_ids),
            "sensitivity": safe.sensitivity,
            "contradicts_record_id": safe.contradicts_record_id,
            "supersedes_record_id": safe.supersedes_record_id,
            "quarantine_reason": safe.quarantine_reason,
            "provenance": dict(safe.provenance),
            "created_at": safe.created_at,
            "updated_at": safe.updated_at,
            "expires_at": safe.expires_at,
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
            evidence_ids=_normalise_memory_evidence_ids(data.get("evidence_ids", ()), allow_none=True),
            sensitivity=str(data.get("sensitivity", "normal")),
            contradicts_record_id=data.get("contradicts_record_id"),
            supersedes_record_id=data.get("supersedes_record_id"),
            quarantine_reason=data.get("quarantine_reason"),
            provenance=dict(data.get("provenance") or {}),
            created_at=float(data.get("created_at", 0.0)),
            updated_at=float(data.get("updated_at", 0.0)),
            expires_at=float(data["expires_at"]) if data.get("expires_at") is not None else None,
        )


def _memory_field_is_private(value: Any) -> bool:
    field_name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(value)).casefold()
    parts = {part for part in re.split(r"[^a-z0-9]+", field_name) if part}
    joined = "_".join(part for part in field_name.split("_") if part)
    return (
        bool(parts & (_MEMORY_PRIVATE_FIELD_PARTS | _MEMORY_SECRET_FIELD_PARTS))
        or joined in _MEMORY_SECRET_FIELD_NAMES
        or ("api" in parts and "key" in parts)
    )


def _sanitise_memory_text(value: Any, limit: int = 4096) -> str:
    try:
        text = str(value)
    except Exception:
        return "[omitted]"
    text = _MEMORY_PROMPT_SOURCE_RE.sub(r"\1\2[redacted]", text)
    text = _MEMORY_SECRET_ASSIGNMENT_RE.sub(r"\1\2[redacted]", text)
    text = _MEMORY_BEARER_RE.sub("Bearer [redacted]", text)
    text = _MEMORY_TOKEN_RE.sub("[redacted]", text)
    return text[:limit]


def _sanitise_memory_value(value: Any, depth: int = 0, *, allow_source_root: bool = False) -> Any:
    if depth > 4:
        return "[omitted]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _sanitise_memory_text(value)
    if isinstance(value, bytes):
        return "[binary omitted]"
    if isinstance(value, Mapping):
        safe: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 64:
                break
            if not isinstance(key, str):
                continue
            if key == "source_root" and allow_source_root and depth == 0:
                if (
                    isinstance(item, str)
                    and item == item.strip()
                    and len(item) <= 1024
                    and bool(re.match(r"^(?:[A-Za-z]:[\\/]|\\\\[^\\/]+[\\/][^\\/]+|/)", item))
                    and not re.search(r"[\r\n]", item)
                ):
                    safe["source_root"] = _sanitise_memory_text(item, limit=1024)
                continue
            if _memory_field_is_private(key):
                continue
            safe_key = _sanitise_memory_text(key, limit=120)
            safe_item = _sanitise_memory_value(item, depth + 1)
            if isinstance(item, Mapping) and item and isinstance(safe_item, Mapping) and not safe_item:
                continue
            safe[safe_key] = safe_item
        return safe
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_sanitise_memory_value(item, depth + 1) for item in list(value)[:64]]
    return _sanitise_memory_text(value)


def _normalise_memory_evidence_ids(value: Any, *, allow_none: bool = False) -> tuple[str, ...]:
    if value is None and allow_none:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError("memory evidence_ids must be a sequence of strings")
    if any(not isinstance(item, str) for item in value):
        raise ValueError("memory evidence_ids must contain only strings")
    return tuple(value)

def _sanitise_memory_record(record: MemoryRecord, *, reject_sensitive: bool = True) -> MemoryRecord:
    sensitivity = str(record.sensitivity or "").strip().casefold()
    if reject_sensitive and sensitivity != "normal":
        raise ValueError("sensitive memory cannot be persisted")
    source = str(record.source or "").strip()
    safe_source = _sanitise_memory_text(source, limit=64)
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,63}", safe_source) or safe_source != source:
        source = "unknown"
    else:
        source = safe_source
    safe_provenance = _sanitise_memory_value(record.provenance, allow_source_root=True)
    if not isinstance(safe_provenance, dict):
        safe_provenance = {}
    return replace(
        record,
        key=_sanitise_memory_text(record.key, limit=240),
        value=None if sensitivity != "normal" else _sanitise_memory_value(record.value),
        source=source,
        evidence_ids=tuple(
            _sanitise_memory_text(item, limit=240)
            for item in _normalise_memory_evidence_ids(record.evidence_ids)
        ),
        sensitivity=sensitivity or "normal",
        quarantine_reason=(
            _sanitise_memory_text(record.quarantine_reason, limit=500)
            if record.quarantine_reason is not None
            else None
        ),
        provenance=safe_provenance,
    )


class MemoryStore:
    max_query_limit = MAX_MEMORY_QUERY_LIMIT

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
                    from .sqlite_support import validate_durable_schema

                    validate_durable_schema(
                        con,
                        self.state_store.db_path,
                        {
                            "agent_memory_records": [
                                ("record_id", "TEXT", 0, 1), ("kind", "TEXT", 1, 0),
                                ("scope", "TEXT", 1, 0), ("scope_id", "TEXT", 1, 0),
                                ("key", "TEXT", 1, 0), ("value", "TEXT", 1, 0),
                                ("status", "TEXT", 1, 0), ("confidence", "REAL", 1, 0),
                                ("source", "TEXT", 1, 0), ("evidence_ids", "TEXT", 1, 0),
                                ("sensitivity", "TEXT", 1, 0),
                                ("contradicts_record_id", "TEXT", 0, 0),
                                ("supersedes_record_id", "TEXT", 0, 0),
                                ("quarantine_reason", "TEXT", 0, 0),
                                ("provenance", "TEXT", 1, 0), ("created_at", "REAL", 1, 0),
                                ("updated_at", "REAL", 1, 0), ("expires_at", "REAL", 0, 0),
                            ],
                            "agent_entity_relations": [
                                ("relation_id", "TEXT", 0, 1), ("source_entity", "TEXT", 1, 0),
                                ("relation", "TEXT", 1, 0), ("target_entity", "TEXT", 1, 0),
                                ("weight", "REAL", 1, 0), ("metadata", "TEXT", 1, 0),
                                ("created_at", "REAL", 1, 0), ("updated_at", "REAL", 1, 0),
                            ],
                        },
                        complete_groups=(("agent_memory_records", "agent_entity_relations"),),
                        required_if_event_kinds={"agent_memory_records": ("memory.%",)},
                    )
                    # SQLite DDL may autocommit statement by statement. Keep the
                    # durable table group invisible until both tables exist.
                    con.execute("BEGIN IMMEDIATE")
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
                            CREATE INDEX IF NOT EXISTS idx_agent_memory_scope_identity
                            ON agent_memory_records (scope, scope_id, status, updated_at DESC);
                            """
                        )
                        con.execute(
                            """
                            CREATE INDEX IF NOT EXISTS idx_agent_memory_provenance_root
                            ON agent_memory_records (
                                scope,
                                json_extract(CASE WHEN json_valid(provenance) THEN provenance ELSE '{}' END, '$.root'),
                                status,
                                updated_at DESC
                            );
                            """
                        )
                        con.execute(
                            """
                            CREATE INDEX IF NOT EXISTS idx_agent_memory_provenance_repository
                            ON agent_memory_records (
                                scope,
                                json_extract(CASE WHEN json_valid(provenance) THEN provenance ELSE '{}' END, '$.repository_id'),
                                status,
                                updated_at DESC
                            );
                            """
                        )
                        con.execute(
                            """
                            CREATE INDEX IF NOT EXISTS idx_agent_memory_provenance_tenant
                            ON agent_memory_records (
                                scope,
                                json_extract(CASE WHEN json_valid(provenance) THEN provenance ELSE '{}' END, '$.tenant'),
                                status,
                                updated_at DESC
                            );
                            """
                        )
                        for identity_name in ("clone_id", "worktree_id", "branch"):
                            con.execute(
                                f"""
                                CREATE INDEX IF NOT EXISTS idx_agent_memory_provenance_{identity_name}
                                ON agent_memory_records (
                                    scope,
                                    json_extract(CASE WHEN json_valid(provenance) THEN provenance ELSE '{{}}' END, '$.{identity_name}'),
                                    status,
                                    updated_at DESC
                                );
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
                        except sqlite3.OperationalError as exc:
                            if "no such module: fts5" not in str(exc).casefold():
                                raise
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
        target_record = _sanitise_memory_record(record)
        # Enforce candidate status for model output or hypothesis
        if target_record.source == "model" or target_record.kind in (MemoryKind.HYPOTHESIS, MemoryKind.ASSUMPTION):
            if target_record.status not in (MemoryStatus.QUARANTINED, MemoryStatus.REJECTED):
                target_record = target_record.with_status(MemoryStatus.CANDIDATE)

        saved_record, duplicate, _ = self._record_event_and_save(
            target_record,
            actor=actor,
            idempotency_key=idempotency_key,
        )
        saved_record = _sanitise_memory_record(saved_record, reject_sensitive=False)
        if not duplicate:
            self._auto_link_record(saved_record, actor=actor)
        return saved_record

    def _record_event_and_save(
        self,
        record: MemoryRecord,
        *,
        actor: str,
        idempotency_key: str,
    ) -> tuple[MemoryRecord, bool, AgentEvent | None]:
        if not self.state_store.enabled:
            self._save_record(record)
            return record, False, None
        self._init_table()
        def _do_record() -> tuple[MemoryRecord, bool, AgentEvent | None]:
            con = connect_sqlite(self.state_store.db_path, isolation_level=None)
            try:
                with self.state_store.ordered_event_publication(con) as publish:
                    con.execute("BEGIN IMMEDIATE")
                    stream_id = _memory_event_stream_id(
                        record.scope,
                        record.scope_id,
                        record.key or record.record_id,
                    )
                    event_idempotency_key = idempotency_key or f"rec_{record.record_id}"
                    existing = con.execute(
                        """
                        SELECT stream_id, seq, event_id, kind, payload, idempotency_key, correlation_id, actor, created_at
                        FROM agent_events WHERE stream_id = ? AND idempotency_key = ?
                        """,
                        (stream_id, event_idempotency_key),
                    ).fetchone()
                    if existing:
                        existing_event = AgentEvent.from_row(existing)
                        existing_record_id = str(existing_event.payload.get("record_id", ""))
                        if _memory_deletion_event(
                            con,
                            record_id=existing_record_id,
                        ) is not None:
                            raise ValueError("memory record was deleted and cannot be replayed")
                        appended = self.state_store.append_in_transaction(
                            con,
                            existing_event,
                            strict_idempotency=False,
                        )
                        if not appended.succeeded():
                            raise RuntimeError(
                                appended.error or "agent memory event append did not succeed"
                            )
                        existing_record_id = str(existing_event.payload.get("record_id", ""))
                        existing_row = con.execute(
                            """
                            SELECT record_id, kind, scope, scope_id, key, value, status, confidence, source,
                                   evidence_ids, sensitivity, contradicts_record_id, supersedes_record_id,
                                   quarantine_reason, provenance, created_at, updated_at, expires_at
                            FROM agent_memory_records WHERE record_id = ?
                            """,
                            (existing_record_id,),
                        ).fetchone()
                        if existing_row:
                            existing_record = self._row_to_record(existing_row)
                        else:
                            existing_record = MemoryRecord.from_dict(existing_event.payload)
                            self._save_record_row(con, existing_record)
                        con.execute("COMMIT")
                        return existing_record, True, None

                    if _memory_deletion_event(
                        con,
                        record_id=record.record_id,
                    ) is not None:
                        raise ValueError("memory record was deleted and cannot be replayed")
                    final_record = self._resolve_conflict_in_transaction(con, record)
                    event = AgentEvent.create(
                        stream_id=stream_id,
                        kind="memory.recorded",
                        payload=final_record.to_dict(),
                        idempotency_key=event_idempotency_key,
                        actor=actor,
                    )
                    appended = self.state_store.append_in_transaction(
                        con,
                        event,
                        strict_idempotency=False,
                    )
                    if not appended.succeeded():
                        raise RuntimeError(
                            appended.error or "agent memory event append did not succeed"
                        )
                    self._save_record_row(con, final_record)
                    con.execute("COMMIT")
                    publish([appended.event])
                    return final_record, False, appended.event
            except Exception:
                try:
                    con.execute("ROLLBACK")
                except Exception:
                    pass
                raise
            finally:
                con.close()


        saved_record, duplicate, persisted_event = retry_busy(
            _do_record,
            retries=5,
            base_delay_seconds=0.02,
        )
        return saved_record, duplicate, persisted_event

    def _resolve_conflict_in_transaction(self, con: Any, record: MemoryRecord) -> MemoryRecord:
        """Resolve high-confidence contradictions while write lock is held."""
        if record.status not in (MemoryStatus.ACTIVE, MemoryStatus.CONFIRMED):
            return record
        scope_value = record.scope.value if hasattr(record.scope, "value") else str(record.scope)
        rows = con.execute(
            """
            SELECT record_id, kind, scope, scope_id, key, value, status, confidence, source,
                   evidence_ids, sensitivity, contradicts_record_id, supersedes_record_id,
                   quarantine_reason, provenance, created_at, updated_at, expires_at
            FROM agent_memory_records
            WHERE scope = ? AND scope_id = ? AND key = ?
              AND status IN (?, ?)
            ORDER BY updated_at DESC
            """,
            (
                scope_value,
                record.scope_id,
                record.key,
                MemoryStatus.ACTIVE.value,
                MemoryStatus.CONFIRMED.value,
            ),
        ).fetchall()
        for row in rows:
            try:
                existing = self._row_to_record(row)
            except (TypeError, ValueError, OverflowError):
                continue
            if not isinstance(existing.provenance, Mapping):
                continue
            if not _memory_conflict_context_matches(existing, record):
                continue
            if existing.confidence >= 0.8 and record.confidence >= 0.8 and existing.value != record.value:
                return record.with_status(
                    MemoryStatus.QUARANTINED,
                    reason=f"Conflicting high-confidence record exists: {existing.record_id}",
                )
        return record

    def _auto_link_record(self, record: MemoryRecord, actor: str = "agent") -> None:
        """Automatically create entity relations for recorded memory items."""
        try:
            for source, relation, target, weight in self._auto_link_specs(record):
                self.record_relation(
                    source=source,
                    relation=relation,
                    target=target,
                    weight=weight,
                    actor=actor,
                )
        except Exception:
            pass

    def _save_record_mutation(self, record: MemoryRecord, event: AgentEvent) -> MemoryRecord:
        """Persist a memory mutation and its event in the durable transaction."""
        if not self.state_store.enabled:
            self._save_record(record)
            return record

        self._init_table()
        con = connect_sqlite(self.state_store.db_path, isolation_level=None)
        try:
            # T08 contract: enter publication before BEGIN; projection, cursor, and
            # outbox event commit together; publish only the committed row.
            with self.state_store.ordered_event_publication(con) as publish:
                con.execute("BEGIN IMMEDIATE")
                appended = self.state_store.append_in_transaction(
                    con,
                    event,
                    strict_idempotency=False,
                )
                self._save_record_row(con, record)
                con.execute("COMMIT")
                publish([appended.event])
            return record
        except Exception:
            if con.in_transaction:
                con.execute("ROLLBACK")
            raise
        finally:
            con.close()
    @staticmethod
    def _auto_link_specs(record: MemoryRecord) -> list[tuple[str, str, str, float]]:
        specs: list[tuple[str, str, str, float]] = []
        if record.key:
            specs.append((record.record_id, "defines", record.key, record.confidence))
        if record.scope_id:
            specs.append((record.record_id, "scoped_in", record.scope_id, 1.0))
        text_corpus = f"{record.key or ''} {record.value or ''}"
        matches = set(re.findall(r"\b[\w\-./\\]+\.(?:py|js|ts|tsx|jsx|go|rs|cs|java|cpp|h|json|toml|yaml|md)\b", text_corpus))
        source_ent = record.key or record.record_id
        for target_path in list(matches)[:10]:
            norm_path = target_path.replace("\\", "/").strip("./")
            if norm_path and norm_path != source_ent:
                specs.append((source_ent, "targets", norm_path, 0.8))
        if isinstance(record.provenance, dict) and "relations" in record.provenance:
            for rel in record.provenance["relations"]:
                if isinstance(rel, dict) and "target" in rel and "relation" in rel:
                    specs.append((
                        str(rel.get("source", source_ent)),
                        str(rel["relation"]),
                        str(rel["target"]),
                        float(rel.get("weight", 1.0)),
                    ))
        return specs

    def promote(
        self,
        record_id: str,
        target_scope: AgentScope,
        *,
        approver: str,
        scope: AgentScope | str | None = None,
        scope_id: str | None = None,
        root: str | None = None,
        repository_id: str | None = None,
        tenant: str | None = None,
        task_id: str | None = None,
        session_id: str | None = None,
        clone_id: str | None = None,
        worktree_id: str | None = None,
        branch: str | None = None,
    ) -> MemoryRecord:
        if target_scope == AgentScope.GLOBAL and approver != "user":
            raise ApprovalRequiredError("global promotion requires user approval")
        current = self.get(
            record_id,
            scope=scope,
            scope_id=scope_id,
            root=root,
            repository_id=repository_id,
            tenant=tenant,
            task_id=task_id,
            session_id=session_id,
            clone_id=clone_id,
            worktree_id=worktree_id,
            branch=branch,
        )
        if not current:
            raise KeyError(f"Memory record {record_id} not found")

        promoted = current.with_scope(target_scope, MemoryStatus.CONFIRMED)
        event = AgentEvent.create(
            stream_id=f"memory:{target_scope.value}:{promoted.key or promoted.record_id}",
            kind="memory.promoted",
            payload={"record_id": record_id, "from_scope": current.scope.value, "to_scope": target_scope.value, "approver": approver},
            idempotency_key=f"promote_{record_id}_{target_scope.value}",
            actor=approver,
        )
        return self._save_record_mutation(promoted, event)

    def quarantine(
        self,
        record_id: str,
        reason: str,
        *,
        actor: str,
        scope: AgentScope | str | None = None,
        scope_id: str | None = None,
        root: str | None = None,
        repository_id: str | None = None,
        tenant: str | None = None,
        task_id: str | None = None,
        session_id: str | None = None,
        clone_id: str | None = None,
        worktree_id: str | None = None,
        branch: str | None = None,
    ) -> MemoryRecord:
        identity = {
            "scope": scope,
            "scope_id": scope_id,
            "root": root,
            "repository_id": repository_id,
            "tenant": tenant,
            "task_id": task_id,
            "session_id": session_id,
            "clone_id": clone_id,
            "worktree_id": worktree_id,
            "branch": branch,
        }
        authorised = self.get(record_id, **identity)
        if authorised is None:
            raise KeyError(f"Memory record {record_id} not found")
        if not self.state_store.enabled or not self.state_store.db_path.exists():
            quarantined = authorised.with_status(MemoryStatus.QUARANTINED, reason=reason)
            self._save_record(quarantined)
            return quarantined
        self._init_table()

        def _do_quarantine() -> tuple[MemoryRecord, AgentEvent | None]:
            con = connect_sqlite(self.state_store.db_path, isolation_level=None)
            try:
                with self.state_store.ordered_event_publication(con) as publish:
                    con.execute("BEGIN IMMEDIATE")
                    try:
                        row = con.execute(
                            """
                            SELECT record_id, kind, scope, scope_id, key, value, status,
                                   confidence, source, evidence_ids, sensitivity,
                                   contradicts_record_id, supersedes_record_id,
                                   quarantine_reason, provenance, created_at, updated_at,
                                   expires_at
                            FROM agent_memory_records
                            WHERE record_id = ?
                            """,
                            (record_id,),
                        ).fetchone()
                        if row is None:
                            raise KeyError(f"Memory record {record_id} not found")
                        current = self._row_to_record(row)
                        if (
                            current.scope != authorised.scope
                            or current.scope_id != authorised.scope_id
                            or current.provenance != authorised.provenance
                        ):
                            raise KeyError(f"Memory record {record_id} not found")
                        quarantined = current.with_status(
                            MemoryStatus.QUARANTINED,
                            reason=reason,
                        )
                        event = AgentEvent.create(
                            stream_id=_memory_event_stream_id(
                                current.scope,
                                current.scope_id,
                                current.key or current.record_id,
                            ),
                            kind="memory.quarantined",
                            payload={"record_id": record_id, "reason": reason},
                            idempotency_key=(
                                f"quar_{record_id}_"
                                f"{hashlib.sha256(reason.encode('utf-8')).hexdigest()[:16]}"
                            ),
                            actor=actor,
                        )
                        appended = self.state_store.append_in_transaction(
                            con,
                            event,
                            strict_idempotency=False,
                        )
                        self._save_record_row(con, quarantined)
                        con.execute("COMMIT")
                    except BaseException:
                        if bool(getattr(con, "in_transaction", False)):
                            con.execute("ROLLBACK")
                        raise
                    persisted_event = appended.event
                    publish([persisted_event] if persisted_event is not None else [])
                    return quarantined, persisted_event
            finally:
                con.close()

        quarantined, _event = retry_busy(
            _do_quarantine,
            retries=5,
            base_delay_seconds=0.02,
        )
        return quarantined

    @staticmethod
    def _normalise_path(value: str) -> str:
        return os.path.normcase(os.path.normpath(str(value).replace("\\", "/"))).replace("\\", "/")

    @classmethod
    def _canonical_repo_path(cls, root: str, value: str) -> str:
        root_abs = os.path.normcase(os.path.abspath(os.path.normpath(str(root).replace("\\", "/"))))
        raw_path = str(value).replace("\\", "/")
        path_abs = os.path.normcase(
            os.path.abspath(
                os.path.normpath(raw_path if os.path.isabs(raw_path) else os.path.join(root_abs, raw_path))
            )
        )
        return os.path.normcase(os.path.relpath(path_abs, root_abs)).replace("\\", "/")

    @classmethod
    def _paths_overlap(cls, left: str, right: str, *, root: str = "") -> bool:
        if root:
            return cls._canonical_repo_path(root, left) == cls._canonical_repo_path(root, right)
        return cls._normalise_path(left).strip("/") == cls._normalise_path(right).strip("/")

    def mark_stale_for_revision(self, root: str, revision: str, changed_paths: Collection[str] | None) -> int:
        """Atomically stale matching memories; transition or event errors roll back the batch."""
        if not self.state_store.enabled or not self.state_store.db_path.exists():
            return 0

        raw_changed_paths: Collection[str]
        if isinstance(changed_paths, str):
            raw_changed_paths = (changed_paths,)
        else:
            raw_changed_paths = changed_paths or ()
        changed_values: list[str] = []
        seen_paths: set[str] = set()
        for path in raw_changed_paths:
            if path is None or not str(path).strip() or str(path).strip().lower() == "none":
                continue
            normalized_path = self._canonical_repo_path(root, str(path))
            if normalized_path in seen_paths:
                continue
            seen_paths.add(normalized_path)
            changed_values.append(normalized_path)
            if len(changed_values) >= _MAX_STALE_CHANGED_PATHS:
                break
        changed = tuple(changed_values)
        if not changed:
            return 0

        changed_placeholders = ", ".join("?" for _ in changed)
        revision_sql = (
            "json_extract(CASE WHEN json_valid(provenance) THEN provenance ELSE '{}' END, "
            "'$.repository_revision')"
        )
        path_refs_sql = (
            "CASE "
            "WHEN json_valid(provenance) AND json_type(provenance, '$.path_refs') = 'array' "
            "THEN json_extract(provenance, '$.path_refs') "
            "WHEN json_valid(provenance) AND json_type(provenance, '$.path_refs') = 'text' "
            "THEN json_array(json_extract(provenance, '$.path_refs')) "
            "ELSE '[]' END"
        )
        select_sql = f"""
            SELECT record_id, kind, scope, scope_id, key, value, status, confidence, source,
                   evidence_ids, sensitivity, contradicts_record_id, supersedes_record_id,
                   quarantine_reason, provenance, created_at, updated_at, expires_at
            FROM agent_memory_records
            WHERE scope = ?
              AND status <> ?
              AND {_CONTEXT_ROOT_SQL} = ?
              AND COALESCE({revision_sql}, '') <> ?
              AND EXISTS (
                  SELECT 1
                  FROM json_each({path_refs_sql}) AS path_ref
                  WHERE canonical_repo_path(path_ref.value, ?) IN ({changed_placeholders})
              )
        """
        select_params = (
            AgentScope.REPOSITORY.value,
            MemoryStatus.STALE.value,
            _normalise_scope_root(root),
            str(revision),
            root,
            *changed,
        )

        def _mark_batch() -> tuple[int, list[AgentEvent]]:
            con = connect_sqlite(self.state_store.db_path, isolation_level=None)
            published_events: list[AgentEvent] = []
            stale_count = 0
            try:
                con.create_function(
                    "canonical_scope_root",
                    1,
                    lambda value: _normalise_scope_root(str(value)) if value else "",
                )
                con.create_function(
                    "canonical_repo_path",
                    2,
                    lambda value, repo_root: (
                        self._canonical_repo_path(str(repo_root), str(value)) if value is not None else ""
                    ),
                )
                with self.state_store.ordered_event_publication(con) as publish:
                    con.execute("BEGIN IMMEDIATE")
                    rows = con.execute(select_sql, select_params).fetchall()
                    for row in rows:
                        current = self._row_to_record(row)

                        original = current.to_dict()
                        updated_provenance = dict(current.provenance)
                        updated_provenance["staled_by_revision"] = str(revision)
                        updated_provenance["staled_changed_paths"] = list(changed)[:32]
                        updated_provenance["superseded_metadata"] = original
                        stale = replace(
                            current,
                            status=MemoryStatus.STALE,
                            quarantine_reason=f"Repository revision changed to {revision}",
                            provenance=updated_provenance,
                            updated_at=time.time(),
                        )
                        provenance_raw = row[14]
                        update = con.execute(
                            """
                            UPDATE agent_memory_records
                            SET status = ?, quarantine_reason = ?, provenance = ?, updated_at = ?
                            WHERE record_id = ? AND status = ? AND updated_at = ? AND provenance = ?
                            """,
                            (
                                stale.status.value,
                                stale.quarantine_reason,
                                json_dumps(stale.provenance),
                                stale.updated_at,
                                current.record_id,
                                current.status.value,
                                current.updated_at,
                                provenance_raw,
                            ),
                        )
                        if update.rowcount != 1:
                            continue

                        event = AgentEvent.create(
                            stream_id=_memory_event_stream_id(
                                current.scope,
                                current.scope_id,
                                current.key or current.record_id,
                            ),
                            kind="memory.staled",
                            payload={
                                "record_id": current.record_id,
                                "root": root,
                                "revision": str(revision),
                                "changed_paths": list(changed)[:32],
                            },
                            idempotency_key=f"stale_{current.record_id}_{revision}",
                            actor="system",
                        )
                        append_result = self.state_store.append_in_transaction(
                            con,
                            event,
                            strict_idempotency=False,
                        )
                        if not append_result.duplicate:
                            published_events.append(append_result.event)
                        stale_count += 1
                    con.execute("COMMIT")
                    publish(published_events)
            except Exception:
                try:
                    con.execute("ROLLBACK")
                except Exception:
                    pass
                raise
            finally:
                con.close()
            return stale_count, published_events

        stale_count, _published_events = retry_busy(_mark_batch, retries=5, base_delay_seconds=0.02)
        return stale_count

    def diagnostic_summary(
        self,
        *,
        id_limit: int = 8,
        root: str | None = None,
        coordination_id: str = "",
        task_id: str | None = None,
        session_id: str | None = None,
        tenant: str | None = None,
        clone_id: str | None = None,
        worktree_id: str | None = None,
        branch: str | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Return request-scoped excluded-memory counts with bounded newest IDs."""
        statuses = (
            MemoryStatus.STALE.value,
            MemoryStatus.QUARANTINED.value,
            MemoryStatus.REJECTED.value,
            MemoryStatus.SUPERSEDED.value,
        )
        summary = {status: {"count": 0, "ids": []} for status in statuses}
        if not self.state_store.enabled or not self.state_store.db_path.exists():
            return summary
        self._init_table()
        capped_limit = max(0, min(32, int(id_limit)))
        request_scope_provided = any(
            value is not None for value in (root, task_id, tenant, session_id, clone_id, worktree_id, branch)
        )
        request_scope_provided = request_scope_provided or bool(coordination_id)
        con = connect_sqlite(self.state_store.db_path)
        try:
            con.create_function(
                "canonical_scope_root",
                1,
                lambda value: _normalise_scope_root(str(value)) if value else "",
            )
            scope_sql = ""
            scope_params: list[Any] = []
            if request_scope_provided:
                scope_sql, scope_params = _context_scope_sql(
                    root=root or "",
                    coordination_id=coordination_id,
                    task_id=task_id or "",
                    tenant=tenant or "",
                    session_id=session_id or "",
                    clone_id=clone_id or "",
                    worktree_id=worktree_id or "",
                    branch=branch or "",
                )
            for status in statuses:
                where = "status = ? AND (expires_at IS NULL OR expires_at > ?)"
                params: list[Any] = [status, time.time()]
                if scope_sql:
                    where += f" AND {scope_sql}"
                    params.extend(scope_params)
                count_row = con.execute(
                    f"SELECT COUNT(1) FROM agent_memory_records WHERE {where}", tuple(params)
                ).fetchone()
                summary[status]["count"] = int(count_row[0]) if count_row else 0
                if capped_limit:
                    rows = con.execute(
                        f"SELECT record_id FROM agent_memory_records WHERE {where} "
                        "ORDER BY updated_at DESC LIMIT ?",
                        (*params, capped_limit),
                    ).fetchall()
                    summary[status]["ids"] = [str(row[0]) for row in rows]

        finally:
            con.close()
        return summary

    def get(
        self,
        record_id: str,
        *,
        include_expired: bool = False,
        scope: AgentScope | str | None = None,
        scope_id: str | None = None,
        root: str | None = None,
        repository_id: str | None = None,
        tenant: str | None = None,
        task_id: str | None = None,
        session_id: str | None = None,
        clone_id: str | None = None,
        worktree_id: str | None = None,
        branch: str | None = None,
        tenant_agnostic_global: bool = False,
    ) -> MemoryRecord | None:
        if tenant is not None and not isinstance(tenant, str):
            raise ValueError("tenant must be a string")
        requested_scope = AgentScope.parse(scope).value if scope is not None else ""
        if tenant_agnostic_global and requested_scope != AgentScope.GLOBAL.value:
            raise ValueError("tenant-agnostic memory lookup is only valid for GLOBAL scope")
        if not self.state_store.enabled or not self.state_store.db_path.exists():
            return None
        if (
            requested_scope == AgentScope.SESSION.value
            and not str(session_id or "").strip()
            and str(scope_id or "").strip()
        ):
            session_id = str(scope_id).strip()
        if (
            requested_scope == AgentScope.REPOSITORY.value
            or (not requested_scope and str(repository_id or "").strip())
        ) and (not str(repository_id or "").strip() or not tenant):
            return None
        if any(value is not None for value in (scope, scope_id, root, repository_id, tenant)) or any(
            str(value or "").strip() for value in (task_id, session_id, clone_id, worktree_id, branch)
        ):
            records = self.find(
                scope=scope,
                record_id=record_id,
                scope_id=scope_id,
                root=root,
                repository_id=repository_id,
                tenant=tenant,
                task_id=task_id,
                session_id=session_id,
                clone_id=clone_id,
                worktree_id=worktree_id,
                branch=branch,
                include_expired=include_expired,
                tenant_agnostic_global=tenant_agnostic_global,
                semantic=False,
                limit=1,
            )
            record = records[0] if records else None
            if requested_scope == AgentScope.GLOBAL.value and record is not None:
                # Direct lookup must provide every stored owner identity. This
                # does not constrain intentional cross-project GLOBAL context
                # sharing; tenant opt-in above bypasses only the tenant filter.
                if str(record.scope_id or "").strip():
                    return None
                for identity_key, requested_identity in (
                    ("root", root), ("repository_id", repository_id),
                    ("task_id", task_id), ("session_id", session_id),
                    ("clone_id", clone_id), ("worktree_id", worktree_id),
                    ("branch", branch),
                ):
                    stored_identity = str(record.provenance.get(identity_key) or "").strip()
                    if stored_identity and not str(requested_identity or "").strip():
                        return None
            return record
        self._init_table()
        con = connect_sqlite(self.state_store.db_path)
        try:
            sql = (
                "SELECT record_id, kind, scope, scope_id, key, value, status, confidence, source, "
                "evidence_ids, sensitivity, contradicts_record_id, supersedes_record_id, "
                "quarantine_reason, provenance, created_at, updated_at, expires_at "
                "FROM agent_memory_records WHERE record_id = ? AND scope = ? AND scope_id = '' "
                "AND sensitivity = 'normal' "
                "AND COALESCE(json_extract(CASE WHEN json_valid(provenance) THEN provenance ELSE '{}' END, '$.root'), '') = '' "
                "AND COALESCE(json_extract(CASE WHEN json_valid(provenance) THEN provenance ELSE '{}' END, '$.tenant'), '') = '' "
                "AND COALESCE(json_extract(CASE WHEN json_valid(provenance) THEN provenance ELSE '{}' END, '$.repository_id'), '') = '' "
                "AND COALESCE(json_extract(CASE WHEN json_valid(provenance) THEN provenance ELSE '{}' END, '$.task_id'), '') = '' "
                "AND COALESCE(json_extract(CASE WHEN json_valid(provenance) THEN provenance ELSE '{}' END, '$.session_id'), '') = '' "
                "AND COALESCE(json_extract(CASE WHEN json_valid(provenance) THEN provenance ELSE '{}' END, '$.clone_id'), '') = '' "
                "AND COALESCE(json_extract(CASE WHEN json_valid(provenance) THEN provenance ELSE '{}' END, '$.worktree_id'), '') = '' "
                "AND COALESCE(json_extract(CASE WHEN json_valid(provenance) THEN provenance ELSE '{}' END, '$.branch'), '') = '' "
                "AND (value IS NULL OR value = '' OR json_valid(value)) "
                "AND (evidence_ids IS NULL OR evidence_ids = '' OR "
                "json_type(CASE WHEN json_valid(evidence_ids) THEN evidence_ids ELSE 'null' END) = 'array') "
                "AND (provenance IS NULL OR provenance = '' OR "
                "json_type(CASE WHEN json_valid(provenance) THEN provenance ELSE 'null' END) = 'object')"
            )
            params: list[Any] = [record_id, AgentScope.GLOBAL.value]
            if not include_expired:
                sql += " AND (expires_at IS NULL OR expires_at > ?)"
                params.append(time.time())
            provenance_tenant = (
                "json_extract(CASE WHEN json_valid(provenance) THEN provenance ELSE '{}' END, "
                "'$.tenant')"
            )
            sql += (
                " AND scope = ? AND ("
                f"{provenance_tenant} IS NULL OR {provenance_tenant} = '')"
            )
            params.append(AgentScope.GLOBAL.value)
            row = con.execute(sql, tuple(params)).fetchone()
            if not row:
                return None
            try:
                record = self._row_to_record(row)
            except (TypeError, ValueError, OverflowError):
                return None
            return _sanitise_memory_record(record, reject_sensitive=False)
        finally:
            con.close()

    @contextmanager
    def task_retrieval_scope(self, goal: str, *, root: str, tenant: str, task_id: str):
        """Apply goal relevance only within this request's exact memory identity."""
        if not isinstance(tenant, str):
            raise ValueError("tenant must be a string")
        identity = (_normalise_scope_root(root), tenant, str(task_id).strip())
        token = _TASK_MEMORY_QUERY.set((self, identity, _goal_words(str(goal or ""))))
        try:
            yield
        finally:
            _TASK_MEMORY_QUERY.reset(token)

    def task_relevance_score(self, record: MemoryRecord, goal: str, *, task_id: str) -> int:
        """Rank a scoped, already validated task candidate without mutating it."""
        return _task_memory_relevance(
            record.kind.value, record.scope.value, record.scope_id, record.key,
            json_dumps(record.value, ensure_ascii=False), _goal_words(goal), task_id,
        )

    def find_for_context(
        self,
        *,
        root: str = "",
        task_id: str = "",
        tenant: str = "",
        session_id: str = "",
        clone_id: str = "",
        worktree_id: str = "",
        branch: str = "",
        coordination_id: str | None = None,
        include_kinds: Collection[str] = (),
        limit: int = 20,
    ) -> list[MemoryRecord]:
        """Find bounded memory for exact context identity; GLOBAL remains cross-project, never cross-tenant."""
        if not isinstance(tenant, str):
            raise ValueError("tenant must be a string")
        if not self.state_store.enabled or not self.state_store.db_path.exists():
            return []
        self._init_table()
        scope_sql, scope_params = _context_scope_sql(
            root=root,
            task_id=task_id,
            tenant=tenant,
            session_id=session_id,
            clone_id=clone_id,
            worktree_id=worktree_id,
            branch=branch,
            coordination_id=str(coordination_id or "").strip(),
        )
        sql = (
            "SELECT record_id, kind, scope, scope_id, key, value, status, confidence, source, "
            "evidence_ids, sensitivity, contradicts_record_id, supersedes_record_id, "
            "quarantine_reason, provenance, created_at, updated_at, expires_at "
                "FROM agent_memory_records WHERE sensitivity = 'normal' "
                "AND status IN (?, ?) AND (expires_at IS NULL OR expires_at > ?) "
                "AND (source != ? OR status = ?) "
            f"AND {scope_sql} "
            "AND (value IS NULL OR value = '' OR json_valid(value)) "
            "AND (evidence_ids IS NULL OR evidence_ids = '' OR "
            "json_type(CASE WHEN json_valid(evidence_ids) THEN evidence_ids ELSE 'null' END) = 'array') "
            "AND (provenance IS NULL OR provenance = '' OR "
            "json_type(CASE WHEN json_valid(provenance) THEN provenance ELSE 'null' END) = 'object') "
            "AND typeof(confidence) IN ('integer', 'real') "
            "AND typeof(created_at) IN ('integer', 'real') "
            "AND typeof(updated_at) IN ('integer', 'real') "
            "AND (expires_at IS NULL OR typeof(expires_at) IN ('integer', 'real')) "
            f"AND kind IN ({', '.join('?' for _ in MemoryKind)})"
        )
        params: list[Any] = [
            MemoryStatus.ACTIVE.value,
            MemoryStatus.CONFIRMED.value,
            time.time(),
            "consistency_guard",
            MemoryStatus.CONFIRMED.value,
            *scope_params,
            *(kind.value for kind in MemoryKind),
        ]
        kinds = tuple(
            kind.value if hasattr(kind, "value") else str(kind).strip().lower()
            for kind in include_kinds
            if str(kind).strip()
        )
        if kinds:
            placeholders = ", ".join("?" for _ in kinds)
            sql += f" AND kind IN ({placeholders})"
            params.extend(kinds)
        bound_query = _TASK_MEMORY_QUERY.get()
        identity = (_normalise_scope_root(root), tenant, str(task_id).strip())
        goal_terms = (
            bound_query[2]
            if bound_query is not None and bound_query[0] is self and bound_query[1] == identity
            else None
        )
        relevance_expression = "task_memory_relevance(kind,scope,scope_id,key,value)"
        if goal_terms is not None:
            sql += f" AND {relevance_expression} > 0 ORDER BY {relevance_expression} DESC, updated_at DESC, record_id ASC LIMIT ?"
        else:
            sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(max(1, min(20, _bounded_memory_limit(limit, 20))))
        con = connect_sqlite(self.state_store.db_path)
        try:
            if goal_terms is not None:
                con.create_function(
                    "task_memory_relevance", 5,
                    lambda kind, scope, scope_id, key, value: _task_memory_relevance(
                        kind, scope, scope_id, key, value, goal_terms, str(task_id).strip(),
                    ),
                    deterministic=True,
                )
            con.create_function(
                "canonical_scope_root",
                1,
                lambda value: _normalise_scope_root(str(value)) if value else "",
            )
            records: list[MemoryRecord] = []
            for row in con.execute(sql, tuple(params)).fetchall():
                try:
                    record = self._row_to_record(row)
                except (TypeError, ValueError, OverflowError):
                    continue
                if not isinstance(record.provenance, Mapping):
                    continue
                if any(not isinstance(evidence_id, str) for evidence_id in record.evidence_ids):
                    continue
                records.append(_sanitise_memory_record(record, reject_sensitive=False))
            return records
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
        record_id: str | None = None,
        scope_id: str | None = None,
        root: str | None = None,
        repository_id: str | None = None,
        tenant: str | None = None,
        tenant_agnostic_global: bool = False,
        task_id: str | None = None,
        session_id: str | None = None,
        clone_id: str | None = None,
        worktree_id: str | None = None,
        branch: str | None = None,
    ) -> list[MemoryRecord]:
        if tenant is not None and not isinstance(tenant, str):
            raise ValueError("tenant must be a string")
        scope = AgentScope.parse(scope) if scope is not None else None
        if not self.state_store.enabled or not self.state_store.db_path.exists():
            return []
        self._init_table()
        sql = (
            "SELECT record_id, kind, scope, scope_id, key, value, status, confidence, source, "
            "evidence_ids, sensitivity, contradicts_record_id, supersedes_record_id, "
            "quarantine_reason, provenance, created_at, updated_at, expires_at "
            "FROM agent_memory_records WHERE sensitivity = 'normal' "
            "AND (value IS NULL OR value = '' OR json_valid(value)) "
            "AND (evidence_ids IS NULL OR evidence_ids = '' OR "
            "json_type(CASE WHEN json_valid(evidence_ids) THEN evidence_ids ELSE 'null' END) = 'array') "
            "AND (provenance IS NULL OR provenance = '' OR "
            "json_type(CASE WHEN json_valid(provenance) THEN provenance ELSE 'null' END) = 'object')"
        )
        params: list[Any] = []
        scope_val: str | None = None
        task_id_val = str(task_id or "").strip()
        session_id_val = str(session_id or "").strip()
        clone_id_val = str(clone_id or "").strip()
        worktree_id_val = str(worktree_id or "").strip()
        branch_val = str(branch or "").strip()
        scope_id_val = str(scope_id or "").strip()
        root = str(root or "").strip()
        repository_id = str(repository_id or "").strip()
        tenant = tenant if isinstance(tenant, str) else ""
        identity_scopes = [
            (task_id_val, AgentScope.TASK.value),
            (session_id_val, AgentScope.SESSION.value),
            (clone_id_val, AgentScope.CLONE.value),
            (worktree_id_val, AgentScope.WORKTREE.value),
            (branch_val, AgentScope.BRANCH.value),
        ]
        identity_scopes = [(value, scope_name) for value, scope_name in identity_scopes if value]
        identity_fields = {
            AgentScope.TASK.value: "task_id",
            AgentScope.SESSION.value: "session_id",
            AgentScope.CLONE.value: "clone_id",
            AgentScope.WORKTREE.value: "worktree_id",
            AgentScope.BRANCH.value: "branch",
        }
        if not include_expired:
            sql += " AND (expires_at IS NULL OR expires_at > ?)"
            params.append(time.time())
        if scope is not None:
            scope_val = scope.value
            sql += " AND scope = ?"
            params.append(scope_val)
        elif len(identity_scopes) == 1:
            scope_val = identity_scopes[0][1]
            sql += " AND scope = ?"
            params.append(scope_val)
            if not scope_id_val:
                scope_id_val = identity_scopes[0][0]
        elif len(identity_scopes) > 1:
            sql += " AND 0"
        elif root or repository_id or tenant:
            scope_val = AgentScope.REPOSITORY.value if (root or repository_id) else AgentScope.SESSION.value
            sql += " AND scope = ?"
            params.append(scope_val)
            # A tenant alone is not a SESSION identity; fail closed below.
        elif scope_id_val:
            sql += " AND 0"

        primary_identity = ""
        if scope_val in {scope_name for _, scope_name in identity_scopes}:
            primary_identity = next(value for value, scope_name in identity_scopes if scope_name == scope_val)
        if identity_scopes:
            if scope is None:
                if len(identity_scopes) > 1:
                    sql += " AND 0"
                elif scope_val != identity_scopes[0][1]:
                    sql += " AND 0"
                else:
                    scope_id_val = identity_scopes[0][0]
            elif primary_identity:
                if scope_id_val and scope_id_val != primary_identity:
                    sql += " AND 0"
                else:
                    scope_id_val = primary_identity
            elif scope_val == AgentScope.GLOBAL.value:
                sql += " AND 0"

        if scope_val != AgentScope.GLOBAL.value:
            if scope_id_val:
                sql += " AND scope_id = ?"
                params.append(scope_id_val)
            elif scope_val is not None:
                if scope_val == AgentScope.REPOSITORY.value:
                    if not repository_id or not tenant:
                        sql += " AND 0"
                elif scope_val in {AgentScope.TASK.value, AgentScope.SESSION.value}:
                    sql += " AND 0"
                else:
                    sql += " AND 0"
        elif scope_id_val:
            sql += " AND 0"
        if key is not None:
            sql += " AND key = ?"
            params.append(key)
        if status is not None:
            sql += " AND status = ?"
            params.append(status.value if hasattr(status, "value") else str(status))
        if record_id is not None:
            sql += " AND record_id = ?"
            params.append(str(record_id))
        if root and scope_val != AgentScope.REPOSITORY.value:
            canonical_root = _normalise_scope_root(root)
            provenance_repo_id = (
                "json_extract(CASE WHEN json_valid(provenance) THEN provenance ELSE '{}' END, "
                "'$.repository_id')"
            )
            sql += f" AND ({_CONTEXT_ROOT_VALUE_SQL} = ? OR {_CONTEXT_ROOT_SQL} = ? OR {provenance_repo_id} = ?)"
            params.extend([canonical_root, canonical_root, root])
        elif scope_val is None:
            sql += " AND scope = ?"
            params.append(AgentScope.GLOBAL.value)
        if repository_id:
            provenance_repository_id = (
                "json_extract(CASE WHEN json_valid(provenance) THEN provenance ELSE '{}' END, "
                "'$.repository_id')"
            )
            sql += f" AND {provenance_repository_id} = ?"
            params.append(repository_id)
        provenance_tenant = (
            "json_extract(CASE WHEN json_valid(provenance) THEN provenance ELSE '{}' END, "
            "'$.tenant')"
        )
        if tenant_agnostic_global:
            if scope_val != AgentScope.GLOBAL.value:
                raise ValueError("tenant-agnostic memory lookup is only valid for GLOBAL scope")
            # GLOBAL sharing deliberately ignores transport tenant; repository
            # and root identity filters above still constrain root-bound reads.
        elif tenant:
            if scope_val == AgentScope.GLOBAL.value:
                sql += (
                    f" AND ({provenance_tenant} IS NULL OR "
                    f"{provenance_tenant} = '' OR {provenance_tenant} = ?)"
                )
            else:
                sql += f" AND {provenance_tenant} = ?"
            params.append(tenant)
        else:
            sql += f" AND ({provenance_tenant} IS NULL OR {provenance_tenant} = '')"
        if scope_val == AgentScope.REPOSITORY.value and (not repository_id or not tenant):
            sql += " AND 0"
        if scope_val == AgentScope.TASK.value:
            # A task ID (or repository alias) cannot replace either trusted
            # context identity. The SQL above matches both provenance fields.
            if not (root and tenant and (task_id_val or scope_id_val)):
                sql += " AND 0"
        if scope_val == AgentScope.SESSION.value and (not tenant or not session_id_val):
            sql += " AND 0"
        for identity_value, identity_scope in identity_scopes:
            if identity_scope == scope_val:
                continue
            identity_field = identity_fields[identity_scope]
            provenance_identity = (
                "json_extract(CASE WHEN json_valid(provenance) THEN provenance ELSE '{}' END, "
                f"'$.{identity_field}')"
            )
            sql += f" AND {provenance_identity} = ?"
            params.append(identity_value)

        base_sql = sql
        base_params = list(params)

        if query:
            sql += " AND (key LIKE ? OR value LIKE ?)"
            pat = f"%{query}%"
            params.extend([pat, pat])

        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(_bounded_memory_limit(limit, self.max_query_limit))

        con = connect_sqlite(self.state_store.db_path)
        try:
            con.create_function(
                "canonical_scope_root",
                1,
                lambda value: _normalise_scope_root(str(value)) if value else "",
            )
            cur = con.execute(sql, tuple(params))
            exact_records = self._decode_memory_rows(cur.fetchall())

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
                except sqlite3.OperationalError as exc:
                    if "no such table: agent_memory_fts" not in str(exc).casefold():
                        raise

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
                cand_records.extend(self._decode_memory_rows(fetch_rows))

            cand_sql = base_sql + " ORDER BY updated_at DESC LIMIT 100"
            cand_rows = con.execute(cand_sql, tuple(base_params)).fetchall()
            seen_cand = {r.record_id for r in cand_records}
            for rec in self._decode_memory_rows(cand_rows):
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

    def _decode_memory_rows(self, rows: Collection[tuple[Any, ...]]) -> list[MemoryRecord]:
        records: list[MemoryRecord] = []
        for row in rows:
            try:
                record = self._row_to_record(row)
            except (TypeError, ValueError, OverflowError):
                continue
            if record.sensitivity != "normal":
                continue
            if not isinstance(record.provenance, Mapping):
                continue
            if any(not isinstance(evidence_id, str) for evidence_id in record.evidence_ids):
                continue
            records.append(_sanitise_memory_record(record, reject_sensitive=False))
        return records

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
        emb_json = json_dumps([round(float(x), 5) for x in embedding])
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
            def _do_reap() -> tuple[int, list[AgentEvent]]:
                con = connect_sqlite(self.state_store.db_path, isolation_level=None)
                try:
                    with self.state_store.ordered_event_publication(con) as publish:
                        con.execute("BEGIN IMMEDIATE")
                        try:
                            expired_rows = con.execute(
                                """
                                SELECT record_id, scope, scope_id, key, expires_at
                                FROM agent_memory_records
                                WHERE expires_at IS NOT NULL AND expires_at <= ?
                                ORDER BY record_id
                                """,
                                (cutoff,),
                            ).fetchall()
                            events: list[AgentEvent] = []
                            for row in expired_rows:
                                record_id = str(row[0])
                                event = AgentEvent.create(
                                    stream_id=_memory_event_stream_id(
                                        AgentScope(str(row[1])),
                                        str(row[2] or ""),
                                        str(row[3] or record_id),
                                    ),
                                    kind="memory.expired",
                                    payload={
                                        "record_id": record_id,
                                        "expires_at": float(row[4]),
                                    },
                                    idempotency_key=f"expired_{record_id}",
                                    actor="system",
                                )
                                appended = self.state_store.append_in_transaction(
                                    con,
                                    event,
                                    strict_idempotency=False,
                                )
                                if not appended.duplicate and appended.event is not None:
                                    events.append(appended.event)
                            count = int(
                                con.execute(
                                    "DELETE FROM agent_memory_records WHERE expires_at IS NOT NULL AND expires_at <= ?",
                                    (cutoff,),
                                ).rowcount
                            )
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
                            con.execute("COMMIT")
                        except BaseException:
                            if bool(getattr(con, "in_transaction", False)):
                                con.execute("ROLLBACK")
                            raise
                        publish(events)
                        return count, events
                finally:
                    con.close()
            count, _events = retry_busy(_do_reap, retries=5, base_delay_seconds=0.02)
            return count

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
                self._save_record_row(con, record)
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

    def _save_record_and_event(self, record: MemoryRecord, event: AgentEvent) -> MemoryRecord:
        if not self.state_store.enabled:
            return record
        self._init_table()
        published: list[AgentEvent] = []

        def _do_save() -> MemoryRecord:
            con = connect_sqlite(self.state_store.db_path, isolation_level=None)
            try:
                con.execute("BEGIN IMMEDIATE")
                existing_event = con.execute(
                    "SELECT stream_id, seq, event_id, kind, payload, idempotency_key, "
                    "correlation_id, actor, created_at FROM agent_events "
                    "WHERE stream_id = ? AND idempotency_key = ?",
                    (event.stream_id, event.idempotency_key),
                ).fetchone()
                if existing_event:
                    checked = self.state_store.append_in_transaction(
                        con, event, strict_idempotency=True
                    )
                    if checked.error or checked.event is None:
                        raise RuntimeError(checked.error or "memory duplicate event append returned no persisted event")
                    if not checked.duplicate:
                        raise RuntimeError("memory event disappeared during duplicate reconciliation")
                    row = con.execute(
                        """
                        SELECT record_id, kind, scope, scope_id, key, value, status, confidence, source,
                               evidence_ids, sensitivity, contradicts_record_id, supersedes_record_id,
                               quarantine_reason, provenance, created_at, updated_at, expires_at
                        FROM agent_memory_records WHERE record_id = ?
                        """,
                        (record.record_id,),
                    ).fetchone()
                    saved = self._row_to_record(row) if row else record
                    if row is None:
                        self._save_record_row(con, record)
                    con.execute("COMMIT")
                    return saved

                self._save_record_row(con, record)
                appended = self.state_store.append_in_transaction(
                    con, event, strict_idempotency=True
                )
                if appended.error or appended.event is None:
                    raise RuntimeError(appended.error or "memory event append returned no persisted event")
                if appended.duplicate:
                    raise RuntimeError("memory projection/event idempotency mismatch")
                if appended.event:
                    published.append(appended.event)
                con.execute("COMMIT")
                return record
            except Exception:
                try:
                    con.execute("ROLLBACK")
                except Exception:
                    pass
                raise
            finally:
                con.close()

        with self.state_store._append_publish_lock:
            saved = retry_busy(_do_save, retries=5, base_delay_seconds=0.02)
            for persisted in published:
                self.state_store._publish(persisted)
        return saved

    def _save_record_row(self, con: Any, record: MemoryRecord) -> None:
        record = _sanitise_memory_record(record)
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
                json_dumps(record.value),
                record.status.value,
                record.confidence,
                record.source,
                json_dumps(list(record.evidence_ids)),
                record.sensitivity,
                record.contradicts_record_id,
                record.supersedes_record_id,
                record.quarantine_reason,
                json_dumps(record.provenance),
                record.created_at,
                record.updated_at,
                record.expires_at,
            ),
        )
        fts_table = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'agent_memory_fts'"
        ).fetchone()
        if fts_table is None:
            return
        val_str = json_dumps(record.value) if isinstance(record.value, (dict, list)) else str(record.value)
        con.execute("DELETE FROM agent_memory_fts WHERE record_id = ?", (record.record_id,))
        con.execute(
            "INSERT INTO agent_memory_fts(record_id, key, value) VALUES(?, ?, ?)",
            (record.record_id, str(record.key), val_str),
        )

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
            evidence_ids=_normalise_memory_evidence_ids(json.loads(evidence_ids_raw) if evidence_ids_raw else ()),
            sensitivity=sensitivity,
            contradicts_record_id=contradicts_record_id,
            supersedes_record_id=supersedes_record_id,
            quarantine_reason=quarantine_reason,
            provenance=json.loads(provenance_raw) if provenance_raw else {},
            created_at=float(created_at),
            updated_at=float(updated_at),
            expires_at=float(expires_at) if expires_at is not None else None,
        )

    def delete(
        self,
        record_id: str,
        *,
        scope: AgentScope | str | None = None,
        scope_id: str | None = None,
        root: str | None = None,
        repository_id: str | None = None,
        tenant: str | None = None,
        task_id: str | None = None,
        session_id: str | None = None,
        clone_id: str | None = None,
        worktree_id: str | None = None,
        branch: str | None = None,
    ) -> bool:
        # Never derive authorization from the record being deleted. Callers must
        # provide the scope identity they already verified.
        if isinstance(scope, AgentScope):
            parsed_scope = scope
        elif isinstance(scope, str):
            try:
                parsed_scope = AgentScope.parse(scope, default=None)
            except ValueError:
                return False
        else:
            return False
        scope_value = parsed_scope.value
        if tenant is not None and not isinstance(tenant, str):
            return False
        identity_values = {
            "root": str(root or "").strip(),
            "repository_id": str(repository_id or "").strip(),
            "tenant": tenant if isinstance(tenant, str) else "",
            "task_id": str(task_id or "").strip(),
            "session_id": str(session_id or "").strip(),
            "clone_id": str(clone_id or "").strip(),
            "worktree_id": str(worktree_id or "").strip(),
            "branch": str(branch or "").strip(),
        }
        scope_id_value = str(scope_id or "").strip()
        scope_identity_key = {
            AgentScope.TASK: "task_id",
            AgentScope.SESSION: "session_id",
            AgentScope.CLONE: "clone_id",
            AgentScope.WORKTREE: "worktree_id",
            AgentScope.BRANCH: "branch",
        }.get(parsed_scope)
        if scope_identity_key:
            supplied_scope_identity = identity_values[scope_identity_key]
            if supplied_scope_identity:
                if scope_id_value and scope_id_value != supplied_scope_identity:
                    return False
                scope_id_value = supplied_scope_identity
            if not scope_id_value:
                return False
        elif parsed_scope is AgentScope.REPOSITORY:
            if not identity_values["repository_id"] or not identity_values["tenant"]:
                return False
        elif parsed_scope is AgentScope.GLOBAL:
            # Tenant is transport identity, not part of a GLOBAL record's scope.
            # Other supplied identities remain provenance constraints below.
            scope_id_value = ""
        elif not scope_id_value:
            return False
        if not self.state_store.enabled or not self.state_store.db_path.exists():
            return False
        self._init_table()

        def _do_delete() -> tuple[bool, AgentEvent | None]:
            con = connect_sqlite(self.state_store.db_path, isolation_level=None)
            try:
                with self.state_store.ordered_event_publication(con) as publish:
                    con.execute("BEGIN IMMEDIATE")
                    if parsed_scope is AgentScope.REPOSITORY and not scope_id_value:
                        row = con.execute(
                            """
                            SELECT scope_id, key, provenance
                            FROM agent_memory_records
                            WHERE record_id = ? AND scope = ?
                            """,
                            (record_id, scope_value),
                        ).fetchone()
                    else:
                        row = con.execute(
                            """
                            SELECT scope_id, key, provenance
                            FROM agent_memory_records
                            WHERE record_id = ? AND scope = ? AND scope_id = ?
                            """,
                            (record_id, scope_value, scope_id_value),
                        ).fetchone()
                    if row is None:
                        con.execute("COMMIT")
                        return False, None
                    stored_scope_id = str(row[0] or "")
                    try:
                        provenance = json.loads(row[2]) if row[2] else {}
                    except (TypeError, ValueError):
                        provenance = {}
                    if not isinstance(provenance, dict):
                        provenance = {}
                    record_tenant = provenance.get("tenant")
                    if parsed_scope is AgentScope.GLOBAL:
                        if record_tenant is not None and not isinstance(record_tenant, str):
                            con.execute("COMMIT")
                            return False, None
                    elif (
                        not isinstance(record_tenant, str)
                        or not record_tenant
                        or not identity_values["tenant"]
                        or record_tenant != identity_values["tenant"]
                    ):
                        con.execute("COMMIT")
                        return False, None
                    for identity_key, expected in identity_values.items():
                        if not expected or identity_key == scope_identity_key:
                            continue
                        if parsed_scope is AgentScope.REPOSITORY and identity_key == "root":
                            continue
                        if parsed_scope is AgentScope.GLOBAL and identity_key == "tenant":
                            continue
                        actual = str(provenance.get(identity_key, "") or "").strip()
                        if identity_key == "root":
                            repo_id = str(provenance.get("repository_id", "") or "").strip()
                            if (not actual or _normalise_scope_root(actual) != _normalise_scope_root(expected)) and repo_id != expected:
                                con.execute("COMMIT")
                                return False, None
                        elif actual != expected:
                            con.execute("COMMIT")
                            return False, None

                    stream_id = _memory_event_stream_id(
                        parsed_scope,
                        str(row[0] or ""),
                        str(row[1] or record_id),
                    )
                    event = AgentEvent.create(
                        stream_id=stream_id,
                        kind="memory.deleted",
                        payload={"record_id": record_id},
                        idempotency_key=f"deleted_{record_id}",
                        actor="memory-store",
                    )
                    appended = self.state_store.append_in_transaction(
                        con,
                        event,
                        strict_idempotency=True,
                    )
                    if appended.error or appended.event is None:
                        raise RuntimeError(appended.error or "memory deletion event append returned no persisted event")

                    cur = con.execute(
                        "DELETE FROM agent_memory_records WHERE record_id = ? AND scope = ? AND scope_id = ?",
                        (record_id, scope_value, stored_scope_id),
                    )
                    cnt = cur.rowcount
                    if cnt <= 0:
                        raise RuntimeError("memory record disappeared during deletion")
                    if cnt > 0:
                        con.execute(
                            "DELETE FROM agent_memory_embeddings WHERE record_id = ?",
                            (record_id,),
                        )
                        if con.execute(
                            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_memory_fts'"
                        ).fetchone() is not None:
                            con.execute(
                                "DELETE FROM agent_memory_fts WHERE record_id = ?",
                                (record_id,),
                            )
                        con.execute(
                            "DELETE FROM agent_entity_relations WHERE source_entity = ? OR target_entity = ?",
                            (record_id, record_id),
                        )
                    con.execute("COMMIT")
                    publish([appended.event])
                    return True, appended.event
            except Exception:
                try:
                    con.execute("ROLLBACK")
                except sqlite3.Error as rollback_error:
                    logging.getLogger(__name__).warning(
                        "memory_delete_rollback_failed exception_type=%s",
                        type(rollback_error).__name__,
                    )
                raise
            finally:
                con.close()

        deleted, _ = retry_busy(
            _do_delete,
            retries=5,
            base_delay_seconds=0.02,
        )
        return deleted

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
        self._init_table()
        scope_value = (
            scope.value if hasattr(scope, "value")
            else (AgentScope.parse(scope, AgentScope.REPOSITORY).value if scope is not None else None)
        )
        select_sql = (
            "SELECT record_id, kind, scope, scope_id, key, value, status, confidence, source, "
            "evidence_ids, sensitivity, contradicts_record_id, supersedes_record_id, "
            "quarantine_reason, provenance, created_at, updated_at, expires_at "
            "FROM agent_memory_records WHERE (expires_at IS NULL OR expires_at > ?)"
        )
        select_params: list[Any] = [now]
        if scope_value is not None:
            select_sql += " AND scope = ?"
            select_params.append(scope_value)
        select_sql += " ORDER BY updated_at DESC LIMIT 1000"
        con = connect_sqlite(self.state_store.db_path)
        try:
            records = self._decode_memory_rows(con.execute(select_sql, tuple(select_params)).fetchall())
        finally:
            con.close()
        candidates = [
            r for r in records
            if r.status in (MemoryStatus.ACTIVE, MemoryStatus.CONFIRMED)
            and not r.key.startswith("compacted_")
            and (older_than_seconds <= 0.0 or (now - r.updated_at) >= older_than_seconds)
        ]

        groups: dict[tuple[AgentScope, str, MemoryKind, str], list[MemoryRecord]] = defaultdict(list)
        for r in candidates:
            provenance_key = json_dumps(r.provenance or {}, sort_keys=True)
            groups[(r.scope, r.scope_id, r.kind, provenance_key)].append(r)

        created_records: list[dict[str, Any]] = []
        total_compacted = 0

        for (grp_scope, grp_scope_id, grp_kind, provenance_key), grp_records in groups.items():
            if len(grp_records) < max(2, min_records):
                continue

            out_scope = grp_scope
            if target_scope is not None:
                out_scope = AgentScope.parse(target_scope, grp_scope)

            group_identity = json_dumps(
                [
                    grp_scope.value,
                    grp_scope_id,
                    grp_kind.value,
                    provenance_key,
                    sorted(record.record_id for record in grp_records),
                ],
                sort_keys=True,
            )
            digest_suffix = hashlib.sha256(group_identity.encode("utf-8")).hexdigest()[:12]
            digest_key = f"compacted_{grp_kind.value}_{int(now)}_{digest_suffix}"
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
                scope_id=grp_scope_id if out_scope == grp_scope else "",
                key=digest_key,
                value=digest_value,
                confidence=round(avg_conf, 3),
                provenance=dict(grp_records[0].provenance),
                status=MemoryStatus.CONFIRMED if out_scope != grp_scope else MemoryStatus.ACTIVE,
                source="memory_compactor",
                evidence_ids=tuple(sorted(all_ev)),
            )

            superseded_records = [
                source.with_superseded_by(digest_record.record_id)
                for source in grp_records
            ]
            relation_specs = [
                (source.record_id, "compacted_into", digest_record.record_id, 1.0)
                for source in grp_records
            ]
            try:
                relation_specs.extend(self._auto_link_specs(digest_record))
            except Exception:
                pass
            relation_rows = [
                (
                    f"rel_{uuid.uuid4().hex[:12]}",
                    source,
                    relation,
                    target,
                    weight,
                )
                for source, relation, target, weight in relation_specs
            ]
            compaction_event = AgentEvent.create(
                stream_id=_memory_event_stream_id(out_scope, digest_record.scope_id, digest_key),
                kind="memory.compacted",
                payload={
                    "digest_record_id": digest_record.record_id,
                    "compacted_count": len(grp_records),
                    "source_record_ids": [r.record_id for r in grp_records],
                },
                idempotency_key=f"compact_{digest_record.record_id}",
                actor=actor,
            )

            def _commit_group(con: Any) -> list[AgentEvent]:
                published: list[AgentEvent] = []
                try:
                    con.execute("BEGIN IMMEDIATE")
                    records_to_event = [digest_record, *superseded_records]
                    for record in records_to_event:
                        record_event = AgentEvent.create(
                            stream_id=_memory_event_stream_id(record.scope, record.scope_id, record.key or record.record_id),
                            kind="memory.recorded",
                            payload=record.to_dict(),
                            idempotency_key=f"compact-record:{digest_record.record_id}:{record.record_id}",
                            actor=actor,
                        )
                        appended = self.state_store.append_in_transaction(
                            con, record_event, strict_idempotency=True
                        )
                        if appended.error or appended.event is None:
                            raise RuntimeError(appended.error or "compaction record append returned no persisted event")
                        if appended.duplicate:
                            raise RuntimeError("compaction record event already exists without its projection commit")
                        if appended.event:
                            published.append(appended.event)
                        self._save_record_row(con, record)

                    for relation_index, (relation_id, source_id, relation, target_id, weight) in enumerate(relation_rows):
                        relation_meta = "{}"
                        con.execute(
                            """
                            INSERT INTO agent_entity_relations (
                                relation_id, source_entity, relation, target_entity, weight,
                                metadata, created_at, updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (relation_id, source_id, relation, target_id, weight,
                             relation_meta, now, now),
                        )
                        relation_event = AgentEvent.create(
                            stream_id=f"relation:{source_id}:{target_id}",
                            kind="relation.recorded",
                            payload={
                                "relation_id": relation_id,
                                "source": source_id,
                                "relation": relation,
                                "target": target_id,
                                "weight": weight,
                            },
                            idempotency_key=f"compact-relation:{digest_record.record_id}:{relation_index}",
                            actor=actor,
                        )
                        appended = self.state_store.append_in_transaction(
                            con, relation_event, strict_idempotency=True
                        )
                        if appended.error or appended.event is None:
                            raise RuntimeError(appended.error or "compaction relation append returned no persisted event")
                        if appended.duplicate:
                            raise RuntimeError("compaction relation event already exists without its projection commit")
                        if appended.event:
                            published.append(appended.event)

                    appended = self.state_store.append_in_transaction(
                        con, compaction_event, strict_idempotency=True
                    )
                    if appended.error or appended.event is None:
                        raise RuntimeError(appended.error or "memory compaction append returned no persisted event")
                    if appended.duplicate:
                        raise RuntimeError("compaction event already exists without its projection commit")
                    if appended.event:
                        published.append(appended.event)
                    con.execute("COMMIT")
                    return published
                except Exception:
                    try:
                        con.execute("ROLLBACK")
                    except Exception:
                        pass
                    raise
            con = connect_sqlite(self.state_store.db_path, isolation_level=None)
            try:
                with self.state_store.ordered_event_publication(con) as publish_committed:
                    persisted_events = retry_busy(
                        lambda: _commit_group(con), retries=5, base_delay_seconds=0.02
                    )
                    publish_committed(persisted_events)
            finally:
                con.close()
            total_compacted += len(grp_records)
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
        meta_json = json_dumps(metadata or {}, ensure_ascii=False)
        event = AgentEvent.create(
            stream_id=f"relation:{source}:{target}",
            kind="relation.recorded",
            payload={"relation_id": rel_id, "source": source, "relation": relation, "target": target, "weight": weight},
            actor=actor,
        )

        def _insert() -> AgentEvent | None:
            con = connect_sqlite(self.state_store.db_path, isolation_level=None)
            try:
                con.execute("BEGIN IMMEDIATE")
                con.execute(
                    """
                    INSERT INTO agent_entity_relations (
                        relation_id, source_entity, relation, target_entity, weight, metadata, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (rel_id, source.strip(), relation.strip(), target.strip(), float(weight), meta_json, now, now),
                )
                appended = self.state_store.append_in_transaction(
                    con, event, strict_idempotency=True
                )
                if appended.error or appended.event is None:
                    raise RuntimeError(appended.error or "relation event append returned no persisted event")
                if appended.duplicate:
                    raise RuntimeError("relation projection/event idempotency mismatch")
                con.execute("COMMIT")
                return appended.event
            except Exception:
                try:
                    con.execute("ROLLBACK")
                except Exception:
                    pass
                raise
            finally:
                con.close()
        with self.state_store._append_publish_lock:
            persisted = retry_busy(_insert, retries=5, base_delay_seconds=0.02)
            if persisted is not None:
                self.state_store._publish(persisted)
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
        start = start_entity.strip()
        if not start:
            return {
                "success": True,
                "start_entity": start_entity,
                "nodes": [],
                "edges": [],
                "total_nodes": 0,
                "total_edges": 0,
            }

        limit_nodes = max(1, int(max_nodes))
        limit_depth = max(0, int(max_depth))

        sql = """
        WITH RECURSIVE
          node_cte(entity, depth) AS (
            SELECT ? AS entity, 0 AS depth
            UNION
            SELECT
              CASE WHEN r.source_entity = n.entity THEN r.target_entity ELSE r.source_entity END,
              n.depth + 1
            FROM node_cte n
            JOIN agent_entity_relations r ON (r.source_entity = n.entity OR r.target_entity = n.entity)
            WHERE n.depth < ?
          ),
          bounded_nodes AS (
            SELECT entity, MIN(depth) AS min_depth
            FROM node_cte
            GROUP BY entity
            ORDER BY min_depth ASC
            LIMIT ?
          )
        SELECT
          'node' AS record_type,
          b.entity AS node_name,
          NULL AS relation_id,
          NULL AS source_entity,
          NULL AS relation,
          NULL AS target_entity,
          NULL AS weight,
          NULL AS metadata,
          NULL AS updated_at
        FROM bounded_nodes b
        UNION ALL
        SELECT DISTINCT
          'edge' AS record_type,
          NULL AS node_name,
          r.relation_id,
          r.source_entity,
          r.relation,
          r.target_entity,
          r.weight,
          r.metadata,
          r.updated_at
        FROM agent_entity_relations r
        JOIN bounded_nodes b1 ON (r.source_entity = b1.entity OR r.target_entity = b1.entity)
        WHERE b1.min_depth < ?
        ORDER BY record_type DESC, weight DESC, updated_at DESC
        """

        params = [start, limit_depth, limit_nodes, limit_depth]

        def _fetch():
            con = connect_sqlite(self.state_store.db_path)
            try:
                cur = con.execute(sql, params)
                visited_nodes: set[str] = set()
                collected_edges: list[dict[str, Any]] = []
                seen_edges: set[Any] = set()
                for row in cur.fetchall():
                    if row[0] == "node":
                        if row[1]:
                            visited_nodes.add(str(row[1]))
                    else:
                        rel_id = str(row[2] or "")
                        edge_key = rel_id or (str(row[3]), str(row[4]), str(row[5]))
                        if edge_key in seen_edges:
                            continue
                        seen_edges.add(edge_key)
                        meta_raw = row[7]
                        if meta_raw:
                            try:
                                meta_dict = json.loads(meta_raw)
                            except Exception:
                                meta_dict = {}
                        else:
                            meta_dict = {}
                        collected_edges.append({
                            "relation_id": rel_id,
                            "source_entity": str(row[3] or ""),
                            "relation": str(row[4] or ""),
                            "target_entity": str(row[5] or ""),
                            "weight": float(row[6]) if row[6] is not None else 1.0,
                            "metadata": meta_dict,
                            "updated_at": float(row[8]) if row[8] is not None else 0.0,
                        })
                return {
                    "success": True,
                    "start_entity": start_entity,
                    "nodes": sorted(list(visited_nodes)),
                    "edges": collected_edges,
                    "total_nodes": len(visited_nodes),
                    "total_edges": len(collected_edges),
                }
            finally:
                con.close()

        return retry_busy(_fetch, retries=5, base_delay_seconds=0.02)
