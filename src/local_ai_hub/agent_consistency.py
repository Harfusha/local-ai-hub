"""Deterministic, soft consistency checks for agent task context.

The guard deliberately keeps repository evidence separate from suggestions.  It
does not mutate task state, remove history, or treat model output as proof.
"""

from __future__ import annotations

import hashlib
import itertools
import math
import re
import threading
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .agent_tasks import GoalContract
from .repo_tools import RepositoryTools


_MAX_TEXT = 1200
_MAX_ITEMS = 64
_MAX_MEMORY_VALUE_ITEMS = 16
_MEMORY_RETENTION_SECONDS = 30 * 86400
_METRIC_KEYS = (
    "reuse_candidates",
    "reuse_accepted",
    "reuse_rejected",
    "warning_info",
    "warning_warning",
    "warning_boundary",
    "warning_high",
    "warning_critical",
    "unknown_claims",
    "contract_mismatches",
    "duplicate_context_reuse",
    "degraded_local_model_fallback",
)
_IDENTIFIER = re.compile(r"\b[A-Z][A-Z0-9_]{2,}\b")
_PUBLIC_SYMBOL = re.compile(r"^\+\s*(?:export\s+)?(?:async\s+)?(?:def|class|function|const|let|type|interface)\s+([A-Za-z_]\w*)")
_HTTP_ENDPOINT = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\s+([/A-Za-z0-9_{}:$.-]+)")
_FIELD = re.compile(r"\b([A-Za-z_]\w*)\s*:\s*([A-Za-z_][\w<>\[\]| ]*)(?=[,;}\n]|$)")


def _text(value: Any, limit: int = _MAX_TEXT) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        rendered = value
    else:
        try:
            rendered = str(value)
        except Exception:
            rendered = "<unserializable>"
    return rendered[:limit]


def _tuple(value: Any, limit: int = _MAX_ITEMS) -> tuple[str, ...]:
    if isinstance(value, str):
        values = (value,)
    else:
        try:
            values = itertools.islice(iter(value), limit)
        except Exception:
            values = ()
    output: list[str] = []
    try:
        for item in values:
            if item is not None:
                output.append(_text(item, 240))
    except Exception:
        pass
    return tuple(output[:limit])


def _bounded_sequence(value: Any, limit: int = _MAX_ITEMS) -> tuple[Any, ...]:
    try:
        return tuple(itertools.islice(iter(value), limit))
    except Exception:
        return ()


def _safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"", "0", "false", "no", "off", "none", "null"}:
            return False
        if normalized in {"1", "true", "yes", "on"}:
            return True
    try:
        return bool(value)
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except Exception:
        return default


def _json_value(value: Any, depth: int = 0, seen: set[int] | None = None) -> Any:
    seen = seen if seen is not None else set()
    if depth > 3:
        return _text(value, 240)
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else 0.0
    identity = id(value)
    if identity in seen:
        return "<cycle>"
    if isinstance(value, Mapping):
        seen.add(identity)
        output: dict[str, Any] = {}
        try:
            items = itertools.islice(value.items(), _MAX_ITEMS)
            for key, item in items:
                output[_text(key, 80)] = _json_value(item, depth + 1, seen)
        except Exception:
            pass
        seen.discard(identity)
        return output
    if isinstance(value, (tuple, list, set)):
        seen.add(identity)
        output: list[Any] = []
        try:
            for item in itertools.islice(iter(value), _MAX_ITEMS):
                output.append(_json_value(item, depth + 1, seen))
        except Exception:
            pass
        seen.discard(identity)
        return output
    return _text(value, 240)


def _normalise_authority_label(value: Any) -> str:
    raw = unicodedata.normalize("NFKC", _text(value, 240)).casefold()
    return re.sub(r"[^a-z0-9]+", " ", raw).strip()


def _is_local_model_evidence(item: Mapping[str, Any]) -> bool:
    labels = []
    for key in ("source", "provider", "provider_name", "model", "model_name"):
        if item.get(key) is not None:
            labels.append(_normalise_authority_label(item.get(key)))
    blocked = {"local", "model", "llm", "generated", "local model", "local model output", "local inference", "ollama"}
    model_family = ("qwen", "llama", "mistral", "gemma", "phi", "deepseek", "granite", "llm")
    for label in labels:
        compact = label.replace(" ", "")
        tokens = set(label.split())
        if label in blocked or tokens.intersection({"model", "llm", "generated", "ollama"}) or "ollama" in compact:
            return True
        if "local" in label and any(token in label for token in ("model", "inference", "llm", "ai")):
            return True
        if any(compact.startswith(prefix) for prefix in model_family):
            return True
    return False


def _memory_value(value: Any, depth: int = 0) -> Any:
    """Keep evidence memory compact and exclude source/prompt-shaped fields."""
    if depth > 2:
        return _text(value, 240)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _text(value, 240)
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for key, item in itertools.islice(value.items(), _MAX_MEMORY_VALUE_ITEMS):
            name = _text(key, 80)
            lowered = name.casefold()
            if any(token in lowered for token in ("raw", "source", "prompt", "output", "content", "text")):
                continue
            output[name] = _memory_value(item, depth + 1)
        return output
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_memory_value(item, depth + 1) for item in itertools.islice(iter(value), _MAX_MEMORY_VALUE_ITEMS)]
    return _text(value, 240)


@dataclass(frozen=True)
class ConsistencyRequest:
    root: str
    task_id: str = ""
    query: str = ""
    phase: str = ""
    focus: tuple[str, ...] = ()
    workspace: str = ""
    preload_profile: str = ""
    token_budget: int = 2400
    changed_paths: tuple[str, ...] = ()
    base: str = "HEAD"
    staged: bool = False
    tenant: str = ""
    memory_revision: str = ""
    override_reason: str = ""
    approval: str | bool = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", _text(self.root, 400))
        object.__setattr__(self, "task_id", _text(self.task_id, 160))
        object.__setattr__(self, "query", _text(self.query, 800))
        object.__setattr__(self, "phase", _text(self.phase, 80))
        object.__setattr__(self, "focus", _tuple(self.focus, 16))
        object.__setattr__(self, "workspace", _text(self.workspace, 160))
        object.__setattr__(self, "preload_profile", _text(self.preload_profile, 120))
        object.__setattr__(self, "token_budget", max(128, min(_safe_int(self.token_budget, 2400), 20000)))
        object.__setattr__(self, "changed_paths", _tuple(self.changed_paths, 64))
        object.__setattr__(self, "base", _text(self.base, 160) or "HEAD")
        object.__setattr__(self, "staged", _safe_bool(self.staged))
        object.__setattr__(self, "tenant", _text(self.tenant, 160))
        object.__setattr__(self, "memory_revision", _text(self.memory_revision, 200))
        object.__setattr__(self, "override_reason", _text(self.override_reason, 500))
        if not isinstance(self.approval, bool):
            object.__setattr__(self, "approval", _text(self.approval, 240))

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root, "task_id": self.task_id, "query": self.query,
            "phase": self.phase, "focus": list(self.focus), "workspace": self.workspace,
            "preload_profile": self.preload_profile, "token_budget": self.token_budget,
            "changed_paths": list(self.changed_paths), "base": self.base, "staged": self.staged,
            "tenant": self.tenant, "memory_revision": self.memory_revision,
            "override_reason": self.override_reason, "approval": self.approval,
        }


@dataclass(frozen=True)
class ReuseCandidate:
    candidate_id: str
    kind: str
    path: str
    symbol: str = ""
    line: int = 0
    score: float = 0.0
    reason: str = ""
    evidence_ids: tuple[str, ...] = ()
    suitable: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_id", _text(self.candidate_id, 160))
        object.__setattr__(self, "kind", _text(self.kind, 80))
        object.__setattr__(self, "path", _text(self.path, 400))
        object.__setattr__(self, "symbol", _text(self.symbol, 160))
        object.__setattr__(self, "line", max(0, _safe_int(self.line)))
        object.__setattr__(self, "score", round(_safe_float(self.score), 3))
        object.__setattr__(self, "reason", _text(self.reason, 400))
        object.__setattr__(self, "evidence_ids", _tuple(self.evidence_ids))
        object.__setattr__(self, "suitable", _safe_bool(self.suitable, True))

    def to_dict(self) -> dict[str, Any]:
        return _json_value({
            "candidate_id": self.candidate_id, "kind": self.kind, "path": self.path,
            "symbol": self.symbol, "line": self.line, "score": self.score,
            "reason": self.reason, "evidence_ids": list(self.evidence_ids), "suitable": self.suitable,
        })


@dataclass(frozen=True)
class ContractMapping:
    kind: str
    endpoint: str = ""
    backend_path: str = ""
    frontend_path: str = ""
    backend_symbol: str = ""
    frontend_symbol: str = ""
    backend_fields: tuple[str, ...] = ()
    frontend_fields: tuple[str, ...] = ()
    backend_error_identifiers: tuple[str, ...] = ()
    frontend_error_identifiers: tuple[str, ...] = ()
    loading_state: str = ""
    empty_state: str = ""
    error_state: str = ""
    test_paths: tuple[str, ...] = ()
    status: str = "matched"
    evidence_ids: tuple[str, ...] = ()
    mismatches: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("kind", "endpoint", "backend_path", "frontend_path", "backend_symbol", "frontend_symbol", "loading_state", "empty_state", "error_state", "status"):
            object.__setattr__(self, name, _text(getattr(self, name), 240))
        for name in ("backend_fields", "frontend_fields", "backend_error_identifiers", "frontend_error_identifiers", "test_paths", "evidence_ids", "mismatches"):
            object.__setattr__(self, name, _tuple(getattr(self, name)))

    def to_dict(self) -> dict[str, Any]:
        return _json_value({name: value for name, value in {
            "kind": self.kind, "endpoint": self.endpoint, "backend_path": self.backend_path,
            "frontend_path": self.frontend_path, "backend_symbol": self.backend_symbol,
            "frontend_symbol": self.frontend_symbol, "backend_fields": self.backend_fields,
            "frontend_fields": self.frontend_fields, "backend_error_identifiers": self.backend_error_identifiers,
            "frontend_error_identifiers": self.frontend_error_identifiers, "loading_state": self.loading_state,
            "empty_state": self.empty_state, "error_state": self.error_state, "test_paths": self.test_paths,
            "status": self.status, "evidence_ids": self.evidence_ids, "mismatches": self.mismatches,
        }.items()})


@dataclass(frozen=True)
class GuardWarning:
    severity: str
    code: str = ""
    message: str = ""
    evidence_ids: tuple[str, ...] = ()
    affected_paths: tuple[str, ...] = ()
    recommended_action: str = ""
    requires_approval: bool = False
    kind: str = ""

    def __post_init__(self) -> None:
        code = _text(self.code or self.kind, 100)
        object.__setattr__(self, "severity", _text(self.severity, 40))
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "kind", _text(self.kind or code, 100))
        object.__setattr__(self, "message", _text(self.message, _MAX_TEXT))
        object.__setattr__(self, "evidence_ids", _tuple(self.evidence_ids))
        object.__setattr__(self, "affected_paths", _tuple(self.affected_paths))
        object.__setattr__(self, "recommended_action", _text(self.recommended_action, 500))
        object.__setattr__(self, "requires_approval", _safe_bool(self.requires_approval))

    def to_dict(self) -> dict[str, Any]:
        return _json_value({
            "severity": self.severity, "code": self.code, "kind": self.kind, "message": self.message,
            "evidence_ids": list(self.evidence_ids), "affected_paths": list(self.affected_paths),
            "recommended_action": self.recommended_action, "requires_approval": self.requires_approval,
        })


@dataclass(frozen=True)
class AdaptiveContextPack:
    contract: GoalContract | None = None
    reuse_candidates: tuple[ReuseCandidate, ...] = ()
    mappings: tuple[ContractMapping, ...] = ()
    warnings: tuple[GuardWarning, ...] = ()
    evidence: tuple[dict[str, Any], ...] = ()
    repo_revision: str = ""
    changed_paths: tuple[str, ...] = ()
    stale: bool = False
    context_id: str = ""
    phase: str = ""
    focus: tuple[str, ...] = ()
    preload_profile: str = ""
    memory_revision: str = ""
    model_warnings: tuple[GuardWarning, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "reuse_candidates", _bounded_sequence(self.reuse_candidates))
        object.__setattr__(self, "mappings", _bounded_sequence(self.mappings))
        object.__setattr__(self, "warnings", _bounded_sequence(self.warnings))
        object.__setattr__(self, "evidence", _bounded_sequence(self.evidence))
        object.__setattr__(self, "repo_revision", _text(self.repo_revision, 200))
        object.__setattr__(self, "changed_paths", _tuple(self.changed_paths, 64))
        object.__setattr__(self, "stale", _safe_bool(self.stale))
        object.__setattr__(self, "context_id", _text(self.context_id, 200))
        object.__setattr__(self, "phase", _text(self.phase, 80))
        object.__setattr__(self, "focus", _tuple(self.focus, 16))
        object.__setattr__(self, "preload_profile", _text(self.preload_profile, 120))
        object.__setattr__(self, "memory_revision", _text(self.memory_revision, 200))
        object.__setattr__(self, "model_warnings", _bounded_sequence(self.model_warnings))

    def to_dict(self) -> dict[str, Any]:
        try:
            contract = self.contract.to_dict() if self.contract else None
        except Exception:
            contract = {"goal": "<unserializable>"}
        def nested(value: Any) -> Any:
            try:
                converter = getattr(value, "to_dict", None)
                return converter() if callable(converter) else value
            except Exception:
                return "<unserializable>"

        return _json_value({
            "contract": contract,
            "reuse_candidates": [nested(item) for item in self.reuse_candidates[:_MAX_ITEMS]],
            "mappings": [nested(item) for item in self.mappings[:_MAX_ITEMS]],
            "warnings": [nested(item) for item in self.warnings[:_MAX_ITEMS]],
            "evidence": [_json_value(item) for item in self.evidence[:_MAX_ITEMS]],
            "repo_revision": _text(self.repo_revision, 200), "changed_paths": list(_tuple(self.changed_paths)),
            "stale": bool(self.stale), "context_id": _text(self.context_id, 200),
            "phase": _text(self.phase, 80), "focus": list(_tuple(self.focus, 16)),
            "preload_profile": _text(self.preload_profile, 120),
            "memory_revision": _text(self.memory_revision, 200),
            "model_warnings": [nested(item) for item in self.model_warnings[:_MAX_ITEMS]],
        })


class AgentConsistencyGuard:
    """Compose bounded repository evidence into soft consistency findings."""

    def __init__(self, repository_tools: RepositoryTools | Mapping[str, Any] | None = None, *, task_store: Any = None, memory_store: Any = None, verification_store: Any = None, max_candidates: int = 24) -> None:
        if isinstance(repository_tools, Mapping):
            repository_tools = RepositoryTools(dict(repository_tools))
        self.repository_tools = repository_tools or RepositoryTools({})
        self.task_store = task_store
        self.memory_store = memory_store
        self.verification_store = verification_store
        self.max_candidates = max(1, min(int(max_candidates), 64))
        self._metrics_lock = threading.RLock()
        self._metrics = {key: 0 for key in _METRIC_KEYS}

    @staticmethod
    def _request_from_metadata(
        request: ConsistencyRequest | Mapping[str, Any] | None,
        *,
        root: str = "",
        task_id: str = "",
        phase: str = "",
        changed_paths: Iterable[str] = (),
    ) -> ConsistencyRequest | None:
        if isinstance(request, ConsistencyRequest):
            return request
        if isinstance(request, Mapping):
            try:
                return ConsistencyRequest(**dict(request))
            except Exception:
                return None
        if root or task_id or phase or tuple(_bounded_sequence(changed_paths, 1)):
            return ConsistencyRequest(root=root, task_id=task_id, phase=phase, changed_paths=tuple(changed_paths))
        return None

    def _revision(self, request: ConsistencyRequest | None, explicit: str = "") -> str:
        if explicit:
            return _text(explicit, 200)
        if request is not None and request.memory_revision:
            return _text(request.memory_revision, 200)
        if request is not None:
            try:
                return _text(self.repository_tools.git_snapshot(request.root).revision, 200)
            except Exception:
                pass
        return ""

    @staticmethod
    def _memory_store_enabled(store: Any) -> bool:
        if store is None or not callable(getattr(store, "record", None)):
            return False
        state_store = getattr(store, "state_store", None)
        return getattr(store, "enabled", True) is not False and getattr(state_store, "enabled", True) is not False

    def _record_memory(
        self,
        kind: Any,
        request: ConsistencyRequest | Mapping[str, Any] | None,
        *,
        stable_key: str,
        value: Any,
        evidence_ids: Iterable[str] = (),
        repository_revision: str = "",
        path_refs: Iterable[str] = (),
        symbol_refs: Iterable[str] = (),
        related_task: str = "",
        confidence: float = 1.0,
        retention_seconds: float | None = None,
        actor: str = "consistency_guard",
        root: str = "",
        task_id: str = "",
        phase: str = "",
    ) -> Any:
        store = self.memory_store
        if not self._memory_store_enabled(store):
            return None
        request_obj = self._request_from_metadata(request, root=root, task_id=task_id, phase=phase, changed_paths=path_refs)
        revision = self._revision(request_obj, repository_revision)
        try:
            from .agent_identity import AgentScope
            from .agent_memory import MemoryKind, MemoryRecord

            memory_kind = kind if isinstance(kind, MemoryKind) else MemoryKind(str(kind).lower())
            bounded_evidence = tuple(dict.fromkeys(_text(item, 200) for item in evidence_ids if item))[:24]
            bounded_paths = tuple(dict.fromkeys(_text(item, 240) for item in path_refs if item))[:24]
            bounded_symbols = tuple(dict.fromkeys(_text(item, 200) for item in symbol_refs if item))[:24]
            task = _text(related_task or (request_obj.task_id if request_obj else ""), 160)
            stable = _text(stable_key, 240) or hashlib.sha256(
                json.dumps(_memory_value(value), sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()[:16]
            revision_token = revision or "unrevisioned"
            record_key = f"consistency:{memory_kind.value}:{stable}:{revision_token}"
            now = time.time()
            retention = _MEMORY_RETENTION_SECONDS if retention_seconds is None else max(1.0, float(retention_seconds))
            expires_at = now + min(retention, float(_MEMORY_RETENTION_SECONDS))
            provenance = {
                "root": _text(request_obj.root if request_obj else root, 400),
                "guard": "agent_consistency",
                "phase": _text(request_obj.phase if request_obj else phase, 80),
                "stable_key": stable,
            }
            record = MemoryRecord.create(
                kind=memory_kind,
                scope=AgentScope.REPOSITORY,
                key=record_key,
                value=_memory_value(value),
                confidence=max(0.0, min(1.0, float(confidence))),
                source="consistency_guard",
                evidence_ids=bounded_evidence,
                provenance=provenance,
                expires_at=expires_at,
                repository_revision=revision,
                path_refs=bounded_paths,
                symbol_refs=bounded_symbols,
                related_task=task or None,
            )
            idempotency_key = f"{record_key}:{revision_token}"
            try:
                return store.record(record, actor=actor, idempotency_key=idempotency_key)
            except TypeError:
                return store.record(record)
        except Exception:
            return None

    def record_finding(
        self,
        request: ConsistencyRequest | Mapping[str, Any] | None = None,
        finding: Any = None,
        *,
        evidence_ids: Iterable[str] = (),
        repository_revision: str = "",
        path_refs: Iterable[str] = (),
        symbol_refs: Iterable[str] = (),
        related_task: str = "",
        confidence: float = 1.0,
        stable_key: str = "",
        retention_seconds: float | None = None,
        root: str = "",
        task_id: str = "",
        phase: str = "",
    ) -> Any:
        if not isinstance(request, (ConsistencyRequest, Mapping)) and finding is None:
            finding, request = request, None
        evidence_ids = tuple(_bounded_sequence(evidence_ids, 24))
        path_refs = tuple(_bounded_sequence(path_refs, 24))
        symbol_refs = tuple(_bounded_sequence(symbol_refs, 24))
        evidence_token = ":".join(_text(item, 120) for item in evidence_ids if item)
        refs_token = ":".join((*(_text(item, 160) for item in path_refs if item), *(_text(item, 160) for item in symbol_refs if item)))
        stable = stable_key or _text((finding.get("stable_key") or finding.get("code") or finding.get("kind")) if isinstance(finding, Mapping) else "", 160)
        stable = stable or (f"evidence:{evidence_token}:{refs_token}" if evidence_token or refs_token else _text(finding, 160))
        return self._record_memory(
            "finding", request, stable_key=stable or "finding", value=finding or {}, evidence_ids=evidence_ids,
            repository_revision=repository_revision, path_refs=path_refs, symbol_refs=symbol_refs,
            related_task=related_task, confidence=confidence, retention_seconds=retention_seconds,
            root=root, task_id=task_id, phase=phase,
        )

    def record_reuse_decision(
        self,
        request: ConsistencyRequest | Mapping[str, Any] | None = None,
        *,
        candidate_id: str = "",
        decision: str = "",
        reason: str = "",
        evidence_ids: Iterable[str] = (),
        repository_revision: str = "",
        path_refs: Iterable[str] = (),
        symbol_refs: Iterable[str] = (),
        confidence: float = 1.0,
        stable_key: str = "",
        root: str = "",
        task_id: str = "",
        phase: str = "",
    ) -> Any:
        normalized = _text(decision, 80).casefold()
        self.record_metric("reuse_accepted" if normalized in {"accept", "accepted", "reuse", "used"} else "reuse_rejected" if normalized in {"reject", "rejected", "new"} else "reuse_candidates")
        return self._record_memory(
            "reusable_candidate", request,
            stable_key=stable_key or candidate_id or "reuse-decision",
            value={"candidate_id": _text(candidate_id, 160), "decision": normalized, "reason": _text(reason, 240)},
            evidence_ids=evidence_ids, repository_revision=repository_revision, path_refs=path_refs,
            symbol_refs=symbol_refs, confidence=confidence, root=root, task_id=task_id, phase=phase,
        )

    def record_decision(
        self,
        request: ConsistencyRequest | Mapping[str, Any] | None = None,
        *,
        decision: str = "",
        reason: str = "",
        approved: bool = False,
        evidence_ids: Iterable[str] = (),
        repository_revision: str = "",
        path_refs: Iterable[str] = (),
        confidence: float = 1.0,
        stable_key: str = "",
        root: str = "",
        task_id: str = "",
        phase: str = "",
    ) -> Any:
        return self._record_memory(
            "decision", request,
            stable_key=stable_key or decision or "decision",
            value={"decision": _text(decision, 120), "approved": bool(approved), "reason": _text(reason, 240)},
            evidence_ids=evidence_ids, repository_revision=repository_revision, path_refs=path_refs,
            confidence=confidence, root=root, task_id=task_id, phase=phase,
        )

    def record_rejected_approach(
        self,
        request: ConsistencyRequest | Mapping[str, Any] | None = None,
        *,
        approach: str = "",
        reason: str = "",
        evidence_ids: Iterable[str] = (),
        repository_revision: str = "",
        path_refs: Iterable[str] = (),
        symbol_refs: Iterable[str] = (),
        confidence: float = 1.0,
        stable_key: str = "",
        root: str = "",
        task_id: str = "",
        phase: str = "",
    ) -> Any:
        return self._record_memory(
            "rejected_approach", request,
            stable_key=stable_key or approach or "rejected-approach",
            value={"approach": _text(approach, 160), "reason": _text(reason, 240)},
            evidence_ids=evidence_ids, repository_revision=repository_revision, path_refs=path_refs,
            symbol_refs=symbol_refs, confidence=confidence, root=root, task_id=task_id, phase=phase,
        )

    def record_unknown(
        self,
        request: ConsistencyRequest | Mapping[str, Any] | None = None,
        *,
        claim: str = "",
        evidence_ids: Iterable[str] = (),
        repository_revision: str = "",
        path_refs: Iterable[str] = (),
        confidence: float = 0.0,
        stable_key: str = "",
        root: str = "",
        task_id: str = "",
        phase: str = "",
    ) -> Any:
        self.record_metric("unknown_claims")
        return self._record_memory(
            "unknown", request,
            stable_key=stable_key or claim or "unknown-claim",
            value={"claim": _text(claim, 240), "status": "unsupported"},
            evidence_ids=evidence_ids, repository_revision=repository_revision, path_refs=path_refs,
            confidence=confidence, root=root, task_id=task_id, phase=phase,
        )

    def record_validation(
        self,
        request: ConsistencyRequest | Mapping[str, Any] | None = None,
        *,
        criterion: str = "",
        passed: bool = True,
        evidence_ids: Iterable[str] = (),
        repository_revision: str = "",
        path_refs: Iterable[str] = (),
        confidence: float = 1.0,
        stable_key: str = "",
        root: str = "",
        task_id: str = "",
        phase: str = "",
        details: Mapping[str, Any] | None = None,
    ) -> Any:
        evidence_ids = tuple(_bounded_sequence(evidence_ids, 24))
        path_refs = tuple(_bounded_sequence(path_refs, 24))
        request_obj = self._request_from_metadata(request, root=root, task_id=task_id, phase=phase, changed_paths=path_refs)
        saved = self._record_memory(
            "validation", request_obj,
            stable_key=stable_key or criterion or "validation",
            value={"criterion": _text(criterion, 200), "passed": bool(passed), "details": _memory_value(details or {})},
            evidence_ids=evidence_ids, repository_revision=repository_revision, path_refs=path_refs,
            confidence=confidence, root=root, task_id=task_id, phase=phase,
        )
        if request_obj is not None and request_obj.task_id and self.verification_store is not None and callable(getattr(self.verification_store, "record", None)):
            try:
                from .agent_verification import VerificationReceipt
                self.verification_store.record(VerificationReceipt.create(
                    request_obj.task_id, _text(criterion, 200), passed=passed,
                    evidence_id=next(iter(evidence_ids), ""), repository_revision=self._revision(request_obj, repository_revision),
                    details={"kind": "consistency_validation"},
                ))
            except Exception:
                pass
        return saved

    def record_metric(self, category: str, amount: int = 1, *, severity: str = "") -> int:
        key = _text(category, 80).casefold().replace("-", "_")
        if key in {"warning", "warnings", "warning_severity"}:
            level = _text(severity, 40).casefold() or "warning"
            if level in {"high-risk", "high_risk"}:
                level = "high"
            key = f"warning_{level}" if level in {"info", "warning", "boundary", "high", "critical"} else "warning_warning"
        aliases = {"unknown": "unknown_claims", "unknown_claim": "unknown_claims", "contract_mismatch": "contract_mismatches", "degraded_fallback": "degraded_local_model_fallback"}
        key = aliases.get(key, key)
        if key not in _METRIC_KEYS:
            return 0
        try:
            increment = max(0, min(int(amount), 100000))
        except (TypeError, ValueError):
            increment = 0
        with self._metrics_lock:
            self._metrics[key] += increment
            return self._metrics[key]

    def metrics_snapshot(self) -> dict[str, int]:
        with self._metrics_lock:
            return {key: int(self._metrics[key]) for key in _METRIC_KEYS}

    @property
    def metrics(self) -> dict[str, int]:
        return self.metrics_snapshot()

    get_metrics = metrics_snapshot

    def build_contract(self, request: ConsistencyRequest) -> GoalContract:
        contract: Any = None
        if self.task_store is not None and request.task_id:
            try:
                getter = getattr(self.task_store, "get", None) or getattr(self.task_store, "get_task", None)
                if getter:
                    state = getter(request.task_id)
                    contract = state.get("contract") if isinstance(state, Mapping) else getattr(state, "contract", None)
            except Exception:
                contract = None
        if isinstance(contract, GoalContract):
            return contract
        if isinstance(contract, Mapping):
            return GoalContract.from_dict(contract)
        return GoalContract(goal=request.query, scope="task")

    @staticmethod
    def _evidence_id(item: Mapping[str, Any]) -> str:
        explicit = item.get("evidence_id") or item.get("id")
        if explicit:
            return _text(explicit, 200)
        raw = _text(item.get("raw") or item.get("text"), 1600)
        path = _text(item.get("path"), 400)
        return "ev-" + hashlib.sha256(f"{path}\n{raw}".encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _synthetic_claim_evidence_id(claim: str, requested_ids: tuple[str, ...], inspected_ids: tuple[str, ...]) -> str:
        payload = "\0".join((_text(claim, 400), *sorted(requested_ids), *sorted(inspected_ids)))
        return "synthetic-claim-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _synthetic_drift_evidence_id(request: ConsistencyRequest, paths: tuple[str, ...], revision: str, diff_fingerprint: str) -> str:
        payload = "\0".join((request.task_id, request.phase, request.base, str(request.staged), _text(revision, 200), _text(diff_fingerprint, 200), *sorted(paths)))
        return "synthetic-drift-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _synthetic_decision_evidence_id(request: ConsistencyRequest, candidate_id: str, action: str, context_ids: tuple[str, ...], revision: str) -> str:
        payload = "\0".join((request.task_id, _text(candidate_id, 200), _text(action, 80), _text(revision, 200), *sorted(context_ids)))
        return "synthetic-decision-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _raw(item: Mapping[str, Any]) -> str:
        return _text(item.get("raw") or item.get("text") or item.get("content"), 5000)

    def structured_evidence(self, evidence: Iterable[Mapping[str, Any]] | Mapping[str, Any], *, limit: int = 24) -> tuple[dict[str, Any], ...]:
        """Project deterministic evidence to metadata safe for local-model input."""
        if isinstance(evidence, Mapping):
            evidence = evidence.get("evidence") or evidence.get("results") or ()
        projected: list[dict[str, Any]] = []
        for item in _bounded_sequence(evidence, min(max(1, int(limit)), _MAX_ITEMS)):
            if not isinstance(item, Mapping) or _is_local_model_evidence(item):
                continue
            evidence_id = self._evidence_id(item)
            row: dict[str, Any] = {
                "evidence_id": evidence_id,
                "authority": "deterministic",
                "path": _text(item.get("path"), 240),
                "start_line": max(0, _safe_int(item.get("start_line"))),
                "end_line": max(0, _safe_int(item.get("end_line"))),
            }
            for key in ("kind", "source_kind", "repository_revision", "revision"):
                value = _text(item.get(key), 200)
                if value:
                    row[key] = value
            if item.get("semantic") is True:
                row["semantic"] = True
            projected.append(row)
        return tuple(projected[: min(max(1, int(limit)), _MAX_ITEMS)])

    def postprocess_model_claims(
        self,
        evidence: Iterable[Mapping[str, Any]] | Mapping[str, Any],
        claims: Iterable[Any],
        request: ConsistencyRequest | None = None,
    ) -> dict[str, Any]:
        """Keep only claims backed by current deterministic evidence IDs."""
        if isinstance(evidence, Mapping):
            evidence = evidence.get("evidence") or evidence.get("results") or ()
        bounded_evidence = _bounded_sequence(evidence, _MAX_ITEMS)
        authoritative = self._current_claim_evidence(bounded_evidence, request)
        accepted: list[dict[str, Any]] = []
        unknowns: list[str] = []
        warnings: list[GuardWarning] = []
        for claim in _bounded_sequence(claims, _MAX_ITEMS):
            if not isinstance(claim, Mapping):
                text, ids = _text(claim, 400), ()
            else:
                text, ids = _text(claim.get("claim") or claim.get("text"), 400), _tuple(claim.get("evidence_ids"))
            valid = bool(text and ids and all(evidence_id in authoritative for evidence_id in ids))
            if valid:
                accepted.append({"claim": text, "evidence_ids": list(ids)})
                continue
            unknowns.append(text or "<empty model claim>")
            self.record_metric("unknown_claims")
            check = self.check_claims(bounded_evidence, [{"claim": text, "evidence_ids": list(ids)}], request=request)
            if check:
                warning = check[0]
                warnings.append(GuardWarning(
                    warning.severity,
                    "unsupported_model_claim",
                    warning.message,
                    warning.evidence_ids,
                    warning.affected_paths,
                    warning.recommended_action,
                    False,
                    "unsupported_claim",
                ))
            else:
                synthetic = self._synthetic_claim_evidence_id(text, ids, tuple(self._evidence_id(item) for item in bounded_evidence if isinstance(item, Mapping)))
                warnings.append(GuardWarning(
                    "warning", "unsupported_model_claim", "model claim has no current deterministic evidence",
                    (synthetic,), (), "verify the claim with deterministic repository evidence", False, "unsupported_claim",
                ))
        return {
            "claims": tuple(accepted[:_MAX_ITEMS]),
            "unknowns": tuple(unknowns[:_MAX_ITEMS]),
            "warnings": tuple(warnings[:_MAX_ITEMS]),
            "authoritative_evidence_ids": tuple(authoritative.keys())[:_MAX_ITEMS],
        }

    def _current_claim_evidence(self, evidence: tuple[Any, ...], request: ConsistencyRequest | None) -> dict[str, Mapping[str, Any]]:
        """Return only deterministic evidence verified against this checkout."""
        revision = ""
        if request is not None:
            try:
                revision = _text(self.repository_tools.git_snapshot(request.root).revision, 200)
            except Exception:
                revision = ""
        records: list[Mapping[str, Any]] = []
        by_id: dict[str, Mapping[str, Any]] = {}
        for item in evidence:
            if not isinstance(item, Mapping) or _is_local_model_evidence(item):
                continue
            evidence_id = self._evidence_id(item)
            by_id[evidence_id] = item
            if item.get("path") and item.get("file_sha256"):
                records.append(item)
        statuses: dict[str, str] = {}
        if request is not None and records:
            try:
                checked = self.repository_tools.verify_evidence(request.root, list(records))
                checked_rows = _bounded_sequence(checked.get("checked", ()), _MAX_ITEMS) if isinstance(checked, Mapping) else ()
                for item, row in zip(records, checked_rows):
                    if isinstance(row, Mapping):
                        statuses[self._evidence_id(item)] = _text(row.get("status"), 40).casefold()
            except Exception:
                statuses = {}
        current: dict[str, Mapping[str, Any]] = {}
        if request is None:
            for evidence_id, item in by_id.items():
                if _safe_bool(item.get("stale")):
                    continue
                status = _text(item.get("status"), 40).casefold()
                if status in {"stale", "missing", "invalid", "invalid-path"}:
                    continue
                if item.get("path") and item.get("file_sha256"):
                    current[evidence_id] = item
            return current
        root_text = _text(request.root, 400)
        try:
            root_text = _text(Path(request.root).resolve(), 400)
        except Exception:
            pass
        for evidence_id, item in by_id.items():
            if _safe_bool(item.get("stale")):
                continue
            evidence_root = item.get("root") or item.get("repository_root")
            if evidence_root:
                try:
                    if _text(Path(_text(evidence_root, 400)).resolve(), 400) != root_text:
                        continue
                except Exception:
                    continue
            item_revision = _text(item.get("repository_revision") or item.get("revision"), 200)
            if item_revision and (not revision or item_revision != revision):
                continue
            status = statuses.get(evidence_id, "")
            if status == "current":
                current[evidence_id] = item
        return current

    def find_reuse_candidates(self, request: ConsistencyRequest, contract: GoalContract) -> tuple[ReuseCandidate, ...]:
        query = " ".join(x for x in (request.query, contract.goal, *contract.constraints, *request.focus) if x)
        if request.changed_paths:
            result = self.repository_tools.search_paths(request.root, query, list(request.changed_paths), top_k=self.max_candidates, context_lines=3)
        else:
            result = self.repository_tools.search(request.root, query, top_k=self.max_candidates, context_lines=3)
        if not result.get("success"):
            return ()
        candidates: list[ReuseCandidate] = []
        for item in _bounded_sequence(result.get("results", ()), self.max_candidates):
            path = _text(item.get("path"), 400)
            raw = self._raw(item)
            if path and not raw:
                try:
                    exact = self.repository_tools.file_slice(
                        request.root,
                        path,
                        int(item.get("start_line", 1) or 1),
                        int(item.get("end_line", item.get("start_line", 1)) or 1),
                        max_chars=2400,
                    )
                    raw = _text(exact.get("text"), 2400) if exact.get("success") else ""
                except Exception:
                    raw = ""
            symbols = re.findall(r"\b(?:class|def|function|interface|type|const)\s+([A-Za-z_]\w*)", raw)
            symbol = symbols[0] if symbols else Path(path).stem
            kind = "frontend" if any(token in path.lower() for token in ("frontend", "client", ".ts", ".tsx", "component")) else "backend"
            reinvention = bool(re.search(r"(?:^|[/_.-])(new|reinvent|duplicate|copy)(?:[/_.-]|$)", f"{path.lower()}"))
            score = _safe_float(item.get("score", 0.0)) + (2.0 if symbol.lower() in query.lower() else 0.0)
            if reinvention:
                score = max(0.0, score - 3.0)
            evidence_id = self._evidence_id(item)
            candidate_id = "reuse-" + hashlib.sha256(f"{path}:{item.get('start_line', 0)}:{symbol}".encode("utf-8")).hexdigest()[:16]
            candidates.append(ReuseCandidate(candidate_id, kind, path, symbol, _safe_int(item.get("start_line", 0)), score, "deterministic repository match", (evidence_id,), not reinvention))
        candidates.sort(key=lambda item: (-int(item.suitable), -item.score, item.path, item.line, item.candidate_id))
        bounded = tuple(candidates[: self.max_candidates])
        self.record_metric("reuse_candidates", len(bounded))
        return bounded

    def build_contract_mappings(self, request: ConsistencyRequest, evidence: Iterable[Mapping[str, Any]] | Mapping[str, Any]) -> tuple[tuple[ContractMapping, ...], tuple[GuardWarning, ...]]:
        if isinstance(evidence, Mapping):
            evidence = evidence.get("evidence") or evidence.get("results") or ()
        items = [dict(item) for item in _bounded_sequence(evidence, _MAX_ITEMS) if isinstance(item, Mapping) and not _is_local_model_evidence(item)]
        back = [item for item in items if self._is_backend(item)]
        front = [item for item in items if not self._is_backend(item)]
        tests = [str(item.get("path")) for item in items if self._is_test(item)]
        if not back or not front:
            return (), ()
        b, f = back[0], front[0]
        braw, fraw = self._raw(b), self._raw(f)
        be_id, fe_id = self._evidence_id(b), self._evidence_id(f)
        endpoint_match = _HTTP_ENDPOINT.search(braw + "\n" + fraw)
        endpoint = endpoint_match.group(2) if endpoint_match else ""
        bfields = tuple(sorted(set(name for name, _ in _FIELD.findall(braw))))
        ffields = tuple(sorted(set(name for name, _ in _FIELD.findall(fraw))))
        berr = tuple(sorted(set(_IDENTIFIER.findall(braw))))
        ferr = tuple(sorted(set(_IDENTIFIER.findall(fraw))))
        mappings: list[ContractMapping] = []
        warnings: list[GuardWarning] = []
        pair_ids = (be_id, fe_id)
        mappings.append(ContractMapping("endpoint", endpoint, str(b.get("path", "")), str(f.get("path", "")), evidence_ids=pair_ids, test_paths=tuple(tests)))
        missing = tuple(sorted(set(bfields) - set(ffields)))
        nullable_backend = {name for name, typ in _FIELD.findall(braw) if "null" in typ or "None" in typ}
        nullable_frontend = {name for name, typ in _FIELD.findall(fraw) if "null" in typ or "undefined" in typ or "?" in typ}
        mismatches = list(missing)
        if missing or nullable_backend != nullable_frontend:
            mappings.append(ContractMapping("response", endpoint, str(b.get("path", "")), str(f.get("path", "")), backend_fields=bfields, frontend_fields=ffields, status="mismatch", evidence_ids=pair_ids, mismatches=tuple(mismatches or ("nullable markers",))))
            warnings.append(GuardWarning("warning", "response_schema_mismatch", "backend and frontend response schemas differ", pair_ids, (str(b.get("path", "")), str(f.get("path", ""))), "align response fields and nullable markers"))
        else:
            mappings.append(ContractMapping("response", endpoint, str(b.get("path", "")), str(f.get("path", "")), backend_fields=bfields, frontend_fields=ffields, evidence_ids=pair_ids))
        error_diff = tuple(sorted(set(berr) - set(ferr)))
        if error_diff:
            mappings.append(ContractMapping("error", endpoint, str(b.get("path", "")), str(f.get("path", "")), backend_error_identifiers=berr, frontend_error_identifiers=ferr, status="mismatch", evidence_ids=pair_ids, mismatches=error_diff))
            warnings.append(GuardWarning("warning", "error_identifier_mismatch", "backend error identifiers are not handled by the frontend", pair_ids, (str(b.get("path", "")), str(f.get("path", ""))), "map backend error codes to the frontend error model"))
        else:
            mappings.append(ContractMapping("error", endpoint, str(b.get("path", "")), str(f.get("path", "")), backend_error_identifiers=berr, frontend_error_identifiers=ferr, evidence_ids=pair_ids))
        for state, markers in (("loading", ("loading", "isloading")), ("empty", ("empty", "no results")), ("error", ("error", "catch"))):
            if not any(marker in fraw.lower() for marker in markers):
                warnings.append(GuardWarning("warning", f"{state}_state_missing", f"frontend {state} state is not visible in bounded evidence", (fe_id,), (str(f.get("path", "")),), f"add or verify the frontend {state} state"))
        for warning in warnings[:_MAX_ITEMS]:
            if "mismatch" in warning.code or warning.kind == "contract_mismatch":
                self.record_metric("contract_mismatches")
            self.record_metric("warning", severity=warning.severity)
        return tuple(mappings[:_MAX_ITEMS]), tuple(warnings[:_MAX_ITEMS])

    @staticmethod
    def _is_backend(item: Mapping[str, Any]) -> bool:
        path = str(item.get("path", "")).lower()
        return not any(token in path for token in ("frontend", "client", ".ts", ".tsx", "component"))

    @staticmethod
    def _is_test(item: Mapping[str, Any]) -> bool:
        path = str(item.get("path", "")).lower()
        return "/test" in f"/{path}" or path.startswith("test_") or "_test" in path

    def check_claims(self, evidence: Iterable[Mapping[str, Any]] | Mapping[str, Any], claims: Iterable[Any], request: ConsistencyRequest | None = None) -> tuple[GuardWarning, ...]:
        if isinstance(evidence, Mapping):
            evidence = evidence.get("evidence") or evidence.get("results") or ()
        bounded_evidence = _bounded_sequence(evidence, _MAX_ITEMS)
        inspected_ids = tuple(
            dict.fromkeys(
                self._evidence_id(item)
                for item in bounded_evidence
                if isinstance(item, Mapping)
            )
        )[:_MAX_ITEMS]
        authoritative = self._current_claim_evidence(bounded_evidence, request)
        warnings: list[GuardWarning] = []
        for claim in _bounded_sequence(claims, _MAX_ITEMS):
            if isinstance(claim, Mapping):
                text = _text(claim.get("claim") or claim.get("text"), 400)
                ids = _tuple(claim.get("evidence_ids"))
            else:
                text, ids = _text(claim, 400), ()
            if not ids or any(evidence_id not in authoritative for evidence_id in ids):
                synthetic_id = self._synthetic_claim_evidence_id(text, ids, inspected_ids)
                warning_ids = (synthetic_id,)
                warnings.append(GuardWarning("warning", "unknown_claim", f"unsupported claim: {text}; synthetic claim-evidence reference: {synthetic_id}", warning_ids, (), "verify the claim with deterministic repository evidence"))
                self.record_metric("unknown_claims")
                self._persist_claim_decision(request, text, warning_ids, "unknown")
            else:
                self._persist_claim_decision(request, text, ids, "verified")
        return tuple(warnings)

    def _persist_claim_decision(self, request: ConsistencyRequest | None, claim: str, evidence_ids: tuple[str, ...], status: str) -> None:
        """Use existing stores when supplied; never create a parallel persistence layer."""
        if request is None or (self.memory_store is None and self.verification_store is None):
            return
        try:
            revision = self.repository_tools.git_snapshot(request.root).revision
        except Exception:
            revision = ""
        if not evidence_ids:
            evidence_ids = (self._synthetic_claim_evidence_id(claim, (), (revision,) if revision else ()),)
        compact_claim = _text(claim, 240)
        key_digest = hashlib.sha256(f"{request.task_id}:{status}:{compact_claim}:{','.join(evidence_ids)}".encode("utf-8")).hexdigest()[:16]
        if status == "verified":
            self.record_finding(
                request,
                finding={"status": status, "claim": compact_claim},
                evidence_ids=evidence_ids,
                repository_revision=revision,
                path_refs=request.changed_paths,
                stable_key=f"claim:{key_digest}",
            )
        else:
            self.record_unknown(
                request,
                claim=compact_claim,
                evidence_ids=evidence_ids,
                repository_revision=revision,
                path_refs=request.changed_paths,
                stable_key=f"claim:{key_digest}",
            )
        if status == "verified" and request.task_id and evidence_ids and self.verification_store is not None and callable(getattr(self.verification_store, "record", None)):
            try:
                from .agent_verification import VerificationReceipt

                receipt = VerificationReceipt.create(
                    task_id=request.task_id,
                    criterion=f"consistency claim:{key_digest}",
                    evidence_id=evidence_ids[0],
                    repository_revision=revision,
                    details={"kind": "claim", "evidence_ids": list(evidence_ids)},
                )
                self.verification_store.record(receipt)
            except Exception:
                pass

    def check_drift(self, request: ConsistencyRequest, contract: GoalContract, changed_paths: Iterable[str], diff: Mapping[str, Any] | str | None) -> tuple[GuardWarning, ...]:
        warnings: list[GuardWarning] = []
        paths = list(_bounded_sequence(_tuple(changed_paths), _MAX_ITEMS))
        if diff is None:
            try:
                diff = self.repository_tools.git_diff(request.root, base=request.base, staged=request.staged, max_tokens=request.token_budget)
            except Exception as exc:
                diff = {"success": False, "paths_complete": False, "error": _text(exc, 240)}
        diff_data: Mapping[str, Any] = diff if isinstance(diff, Mapping) else {}
        diff_unavailable = (
            diff_data.get("success") is False
            or diff_data.get("paths_complete") is False
            or diff_data.get("truncated") is True
            or diff_data.get("incomplete") is True
            or "error" in diff_data
        )
        if diff_unavailable:
            return ()
        if not paths:
            paths = list(_tuple(diff_data.get("changed_paths") or diff_data.get("changed_files")))
        if not paths:
            try:
                paths = list(_bounded_sequence(self.repository_tools.git_snapshot(request.root).changed_paths, _MAX_ITEMS))
            except Exception:
                paths = []
        if paths and not diff_data.get("impact") and not diff_unavailable:
            try:
                impact = self.repository_tools.impact_analysis(request.root, base=request.base, staged=request.staged)
                if isinstance(impact, Mapping) and impact.get("success"):
                    diff_data = {**diff_data, "impact": impact}
            except Exception:
                pass
        try:
            revision = _text(diff_data.get("revision") or diff_data.get("repository_revision"), 200)
            if not revision:
                revision = _text(self.repository_tools.git_snapshot(request.root).revision, 200)
        except Exception:
            revision = ""
        raw_diff = diff if isinstance(diff, str) else diff_data.get("diff", "")
        content_hash = hashlib.sha256(_text(raw_diff, 12000).encode("utf-8")).hexdigest()
        supplied_hash = _text(diff_data.get("diff_sha256"), 200)
        diff_fingerprint = f"{supplied_hash}:{content_hash}" if supplied_hash else content_hash
        synthetic_drift_id = self._synthetic_drift_evidence_id(request, tuple(paths), revision, diff_fingerprint)
        drift_trace_ids = (synthetic_drift_id,)
        candidates = self.find_reuse_candidates(request, contract)
        candidate_ids = {item.candidate_id for item in candidates}
        decisions = diff_data.get("reuse_decisions") or ()
        bounded_evidence = _bounded_sequence(diff_data.get("evidence") or (), _MAX_ITEMS)
        diff_evidence_ids = self._deterministic_evidence_ids(bounded_evidence)
        deterministic_context_ids = set(diff_evidence_ids)
        deterministic_context_ids.update(evidence_id for candidate in candidates for evidence_id in candidate.evidence_ids)
        for decision in _bounded_sequence(decisions, _MAX_ITEMS):
            if not isinstance(decision, Mapping):
                continue
            candidate_id = str(decision.get("candidate_id", ""))
            action = str(decision.get("decision", decision.get("action", ""))).lower()
            reason = str(decision.get("reason", "")).strip()
            decision_evidence_ids = tuple(
                evidence_id
                for evidence_id in _tuple(decision.get("evidence_ids"))
                if evidence_id in deterministic_context_ids
            )
            if not decision_evidence_ids:
                decision_evidence_ids = (
                    self._synthetic_decision_evidence_id(
                        request,
                        candidate_id,
                        action,
                        tuple(sorted(deterministic_context_ids)),
                        revision,
                    ),
                )
            self.record_reuse_decision(
                request,
                candidate_id=candidate_id,
                decision=action,
                reason=reason,
                evidence_ids=decision_evidence_ids,
                repository_revision=revision,
                path_refs=paths,
            )
            if candidate_id not in candidate_ids:
                warnings.append(GuardWarning("warning", "unknown_reuse_candidate", "reuse decision references no deterministic candidate", decision_evidence_ids, tuple(paths), "refresh deterministic reuse candidates"))
            elif action in {"reject", "rejected", "new"} and not reason:
                candidate = next(item for item in candidates if item.candidate_id == candidate_id)
                warnings.append(GuardWarning("warning", "reuse_rejection_reason_required", "rejected reuse candidate needs a concise reason", decision_evidence_ids or candidate.evidence_ids or drift_trace_ids, tuple(paths), "record why reuse violates the contract or boundary"))
            elif action in {"reject", "rejected", "new"}:
                self.record_rejected_approach(
                    request,
                    approach=candidate_id,
                    reason=reason,
                    evidence_ids=decision_evidence_ids,
                    repository_revision=revision,
                    path_refs=paths,
                )
        diff_text = diff if isinstance(diff, str) else str(diff_data.get("diff", ""))
        added_symbols = [match.group(1) for line in _text(diff_text, 12000).splitlines() if (match := _PUBLIC_SYMBOL.match(line))]
        if added_symbols and any(candidate.suitable for candidate in candidates):
            candidate_evidence_ids = tuple(evidence_id for candidate in candidates if candidate.suitable for evidence_id in candidate.evidence_ids)
            warnings.append(GuardWarning("boundary", "new_public_symbol_despite_reuse", "new public symbol added while a suitable reuse candidate exists", candidate_evidence_ids or diff_evidence_ids or drift_trace_ids, tuple(paths), "approve the boundary or reuse the existing symbol", True))
        if request.changed_paths:
            requested = set(request.changed_paths)
            outside = tuple(path for path in paths if path not in requested)
            if outside:
                warnings.append(GuardWarning("warning", "scope_drift", "changed paths exceed the request scope", diff_evidence_ids or drift_trace_ids, outside, "explain the scope expansion or narrow the change"))
        evidence = bounded_evidence
        if evidence:
            try:
                checked = self.repository_tools.verify_evidence(request.root, list(_bounded_sequence(evidence, _MAX_ITEMS)))
                if checked.get("stale"):
                    warnings.append(GuardWarning("warning", "stale_evidence", "one or more evidence slices are stale", diff_evidence_ids or drift_trace_ids, tuple(paths), "refresh evidence at the current repository revision"))
            except Exception:
                pass
        normalized_warnings = tuple(
            warning if warning.evidence_ids else GuardWarning(
                warning.severity,
                warning.code,
                warning.message,
                drift_trace_ids,
                warning.affected_paths,
                warning.recommended_action,
                warning.requires_approval,
                warning.kind,
            )
            for warning in warnings[:_MAX_ITEMS]
        )
        for warning in normalized_warnings:
            self.record_metric("warning", severity=warning.severity)
            if "mismatch" in warning.code:
                self.record_metric("contract_mismatches")
        return normalized_warnings

    def _deterministic_evidence_ids(self, evidence: Iterable[Mapping[str, Any]]) -> tuple[str, ...]:
        ids: list[str] = []
        for item in _bounded_sequence(evidence, _MAX_ITEMS):
            if isinstance(item, Mapping) and not _is_local_model_evidence(item):
                ids.append(self._evidence_id(item))
        return tuple(dict.fromkeys(ids))[:_MAX_ITEMS]

    def completion_audit(
        self,
        request: ConsistencyRequest | Mapping[str, Any] | None = None,
        *,
        criteria: Iterable[str] = (),
        receipts: Iterable[Any] = (),
        warnings: Iterable[Any] = (),
        mappings: Iterable[Any] = (),
        repository_revision: str = "",
        current_revision: str = "",
        records: Iterable[Any] = (),
        contract: Any = None,
    ) -> dict[str, Any]:
        """Return bounded consistency evidence for a completion decision."""
        request_obj = self._request_from_metadata(request)
        if contract is None and request_obj is not None:
            contract = self.build_contract(request_obj)
        criterion_names = tuple(dict.fromkeys(
            _text(item, 200) for item in (criteria or getattr(contract, "acceptance_criteria", ())) if _text(item, 200)
        ))[:_MAX_ITEMS]
        receipt_rows = tuple(_bounded_sequence(receipts, _MAX_ITEMS))
        warning_rows = tuple(_bounded_sequence(warnings, _MAX_ITEMS))
        mapping_rows = tuple(_bounded_sequence(mappings, _MAX_ITEMS))
        revision = _text(current_revision or repository_revision or self._revision(request_obj), 200)

        def field(item: Any, name: str, default: Any = "") -> Any:
            if isinstance(item, Mapping):
                return item.get(name, default)
            return getattr(item, name, default)

        by_criterion: dict[str, list[Any]] = {criterion: [] for criterion in criterion_names}
        for receipt in receipt_rows:
            criterion = _text(field(receipt, "criterion"), 200)
            if criterion in by_criterion:
                by_criterion[criterion].append(receipt)
        criterion_audit: dict[str, dict[str, Any]] = {}
        covered = 0
        stale_criteria: list[str] = []
        for criterion in criterion_names:
            matched = by_criterion.get(criterion, [])
            evidence_ids = tuple(dict.fromkeys(_text(field(item, "evidence_id"), 200) for item in matched if field(item, "evidence_id")))[:24]
            receipt_ids = tuple(dict.fromkeys(_text(field(item, "receipt_id"), 200) for item in matched if field(item, "receipt_id")))[:24]
            current = [item for item in matched if not revision or _text(field(item, "repository_revision"), 200) == revision]
            passed = any(bool(field(item, "passed", False)) for item in current)
            stale = bool(matched and not current)
            if stale:
                stale_criteria.append(criterion)
            if passed:
                covered += 1
            criterion_audit[criterion] = {
                "status": "satisfied" if passed else "stale" if stale else "unsatisfied",
                "evidence_ids": list(evidence_ids),
                "receipt_ids": list(receipt_ids),
                "current_revision": bool(current),
            }

        memory_rows = list(_bounded_sequence(records, _MAX_ITEMS))
        if not memory_rows and self.memory_store is not None:
            finder = getattr(self.memory_store, "find_for_context", None) or getattr(self.memory_store, "find", None)
            if callable(finder):
                try:
                    if finder.__name__ == "find_for_context":
                        memory_rows = list(finder(root=request_obj.root if request_obj else "", task_id=request_obj.task_id if request_obj else "", limit=24))
                    else:
                        memory_rows = list(finder(root=request_obj.root if request_obj else None, task_id=request_obj.task_id if request_obj else None, limit=24, semantic=False))
                except Exception:
                    memory_rows = []
        reuse_decisions: list[dict[str, Any]] = []
        contract_mismatches: list[dict[str, Any]] = []
        unsupported_claims: list[dict[str, Any]] = []
        stale_records: list[dict[str, Any]] = []
        for record in memory_rows[:_MAX_ITEMS]:
            kind = _text(getattr(getattr(record, "kind", None), "value", getattr(record, "kind", "")), 80)
            value = getattr(record, "value", {})
            if not isinstance(value, Mapping):
                value = {"value": _memory_value(value)}
            row = _memory_value(dict(value))
            row["record_id"] = _text(getattr(record, "record_id", ""), 200)
            if kind in {"reusable_candidate", "decision"} and value.get("decision"):
                reuse_decisions.append(row)
            if kind == "contract_mapping" or value.get("status") == "mismatch":
                contract_mismatches.append(row)
            if kind == "unknown":
                unsupported_claims.append(row)
            record_revision = _text(getattr(record, "repository_revision", "") or (getattr(record, "provenance", {}) or {}).get("repository_revision"), 200)
            status = _text(getattr(getattr(record, "status", None), "value", getattr(record, "status", "")), 40)
            if status == "stale" or (revision and record_revision and record_revision != revision):
                stale_records.append({"record_id": row["record_id"], "repository_revision": record_revision})

        drift_warning_rows: list[dict[str, Any]] = []
        for warning in warning_rows:
            if isinstance(warning, Mapping):
                converted = _memory_value(dict(warning))
            else:
                converter = getattr(warning, "to_dict", None)
                converted = _memory_value(converter() if callable(converter) else {"code": getattr(warning, "code", "warning")})
            if isinstance(converted, dict):
                drift_warning_rows.append(converted)
                self.record_metric("warning", severity=_text(converted.get("severity"), 40))
                code = _text(converted.get("code"), 80)
                if "mismatch" in code:
                    self.record_metric("contract_mismatches")
                    contract_mismatches.append(converted)
                if "unknown" in code or "unsupported" in code:
                    self.record_metric("unknown_claims")
                    unsupported_claims.append(converted)
        for mapping in mapping_rows:
            converted = _memory_value(dict(mapping)) if isinstance(mapping, Mapping) else _memory_value(getattr(mapping, "to_dict", lambda: {})())
            if isinstance(converted, dict) and (converted.get("status") == "mismatch" or converted.get("mismatches")):
                contract_mismatches.append(converted)

        return {
            "criteria": criterion_audit,
            "drift_warnings": drift_warning_rows[:_MAX_ITEMS],
            "reuse_decisions": reuse_decisions[:_MAX_ITEMS],
            "contract_mismatches": contract_mismatches[:_MAX_ITEMS],
            "unsupported_claims": unsupported_claims[:_MAX_ITEMS],
            "stale_records": stale_records[:_MAX_ITEMS],
            "current_revision_receipt_coverage": {
                "repository_revision": revision,
                "covered": covered,
                "total": len(criterion_names),
                "missing_criteria": [name for name, item in criterion_audit.items() if not item["current_revision"]],
                "stale_criteria": stale_criteria[:_MAX_ITEMS],
            },
            "warnings": drift_warning_rows[:_MAX_ITEMS],
        }
