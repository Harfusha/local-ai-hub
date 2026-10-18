from __future__ import annotations

import hashlib
import math
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping
import uuid


class AgentScope(str, Enum):
    GLOBAL = "global"
    REPOSITORY = "repository"
    CLONE = "clone"
    WORKTREE = "worktree"
    BRANCH = "branch"
    TASK = "task"
    SESSION = "session"

    @property
    def rank(self) -> int:
        _RANKS = {
            AgentScope.GLOBAL: 1,
            AgentScope.REPOSITORY: 2,
            AgentScope.CLONE: 3,
            AgentScope.WORKTREE: 4,
            AgentScope.BRANCH: 5,
            AgentScope.TASK: 6,
            AgentScope.SESSION: 7,
        }
        return _RANKS[self]

    @classmethod
    def parse(cls, value: Any, default: AgentScope | str | None = None) -> AgentScope:
        resolved_default = cls.TASK if default is None else cls(default)
        if isinstance(value, cls):
            return value
        if value is None:
            return resolved_default
        if not isinstance(value, str):
            raise ValueError("scope must be a canonical string")
        return cls(value)


@dataclass(frozen=True)
class ScopeContext:
    repository_id: str = ""
    clone_id: str = ""
    worktree_id: str = ""
    branch: str = ""
    task_id: str = ""
    session_id: str = ""

    def __post_init__(self) -> None:
        for name in (
            "repository_id", "clone_id", "worktree_id", "branch", "task_id", "session_id"
        ):
            value = getattr(self, name)
            if type(value) is not str or value.strip() != value or "\x00" in value:
                raise ValueError(f"{name} must be a canonical string")

    def matches(self, scope: AgentScope | str, scope_id: str = "") -> bool:
        parsed_scope = AgentScope.parse(scope)
        if parsed_scope == AgentScope.GLOBAL:
            return True
        if parsed_scope == AgentScope.REPOSITORY:
            return bool(self.repository_id) and (not scope_id or scope_id == self.repository_id)
        if parsed_scope == AgentScope.CLONE:
            return bool(self.clone_id) and (not scope_id or scope_id == self.clone_id)
        if parsed_scope == AgentScope.WORKTREE:
            return bool(self.worktree_id) and (not scope_id or scope_id == self.worktree_id)
        if parsed_scope == AgentScope.BRANCH:
            return bool(self.branch) and (not scope_id or scope_id == self.branch)
        if parsed_scope == AgentScope.TASK:
            return bool(self.task_id) and (not scope_id or scope_id == self.task_id)
        if parsed_scope == AgentScope.SESSION:
            return bool(self.session_id) and (not scope_id or scope_id == self.session_id)
        return False

    def is_empty(self) -> bool:
        return not any((
            self.repository_id,
            self.clone_id,
            self.worktree_id,
            self.branch,
            self.task_id,
            self.session_id,
        ))

    def has_task(self) -> bool:
        return bool(self.task_id)

    def has_session(self) -> bool:
        return bool(self.session_id)

    def has_repository(self) -> bool:
        return bool(self.repository_id)

    def has_worktree(self) -> bool:
        return bool(self.worktree_id)

    def has_branch(self) -> bool:
        return bool(self.branch)

    def with_task(self, task_id: str) -> ScopeContext:
        return ScopeContext(
            repository_id=self.repository_id,
            clone_id=self.clone_id,
            worktree_id=self.worktree_id,
            branch=self.branch,
            task_id=task_id,
            session_id=self.session_id,
        )

    def with_session(self, session_id: str) -> ScopeContext:
        return ScopeContext(
            repository_id=self.repository_id,
            clone_id=self.clone_id,
            worktree_id=self.worktree_id,
            branch=self.branch,
            task_id=self.task_id,
            session_id=session_id,
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "repository_id": self.repository_id,
            "clone_id": self.clone_id,
            "worktree_id": self.worktree_id,
            "branch": self.branch,
            "task_id": self.task_id,
            "session_id": self.session_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ScopeContext:
        if not isinstance(data, Mapping):
            raise TypeError("ScopeContext data must be a mapping")
        allowed = {"repository_id", "clone_id", "worktree_id", "branch", "task_id", "session_id"}
        if set(data) - allowed:
            raise ValueError("ScopeContext contains unsupported fields; only canonical scope identities are accepted")
        return cls(
            repository_id=data.get("repository_id", ""),
            clone_id=data.get("clone_id", ""),
            worktree_id=data.get("worktree_id", ""),
            branch=data.get("branch", ""),
            task_id=data.get("task_id", ""),
            session_id=data.get("session_id", ""),
        )


@dataclass(frozen=True)
class ScopedRecord:
    record_id: str
    scope: AgentScope
    scope_id: str = ""
    key: str = ""
    value: Any = None
    confidence: float = 1.0
    evidence_ids: tuple[str, ...] = ()
    created_at: float = 0.0
    status: str = "active"
    sensitivity: str = "normal"
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        rid = str(self.record_id or "").replace("\x00", "").strip()
        if not rid:
            rid = f"rec_{uuid.uuid4().hex[:12]}"
        sc = self.scope
        if not isinstance(sc, AgentScope):
            sc = AgentScope.parse(sc)
        sid = self.scope_id
        if type(sid) is not str or sid.strip() != sid or "\x00" in sid:
            raise ValueError("scope_id must be a canonical string")
        k = str(self.key or "").replace("\x00", "").strip()

        try:
            conf = float(self.confidence)
            if not math.isfinite(conf):
                conf = 0.0
            else:
                conf = max(0.0, min(1.0, conf))
        except (ValueError, TypeError):
            conf = 0.0

        ev_list: list[str] = []
        if self.evidence_ids:
            for item in self.evidence_ids:
                s = str(item or "").replace("\x00", "").strip()
                if s:
                    ev_list.append(s)

        try:
            ca = float(self.created_at)
            ca = max(0.0, ca) if math.isfinite(ca) else 0.0
        except (ValueError, TypeError):
            ca = 0.0

        st = str(self.status or "active").replace("\x00", "").strip()
        sens = str(self.sensitivity or "normal").replace("\x00", "").strip()
        prov = dict(self.provenance) if isinstance(self.provenance, Mapping) else {}

        object.__setattr__(self, "record_id", rid)
        object.__setattr__(self, "scope", sc)
        object.__setattr__(self, "scope_id", sid)
        object.__setattr__(self, "key", k)
        object.__setattr__(self, "confidence", conf)
        object.__setattr__(self, "evidence_ids", tuple(ev_list))
        object.__setattr__(self, "created_at", ca)
        object.__setattr__(self, "status", st)
        object.__setattr__(self, "sensitivity", sens)
        object.__setattr__(self, "provenance", prov)

    def is_active(self) -> bool:
        return self.status in ("active", "confirmed")

    def is_tombstone(self) -> bool:
        return self.status == "tombstone"

    def has_evidence(self) -> bool:
        return bool(self.evidence_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "scope": self.scope.value,
            "scope_id": self.scope_id,
            "key": self.key,
            "value": self.value,
            "confidence": self.confidence,
            "evidence_ids": list(self.evidence_ids),
            "created_at": self.created_at,
            "status": self.status,
            "sensitivity": self.sensitivity,
            "provenance": dict(self.provenance),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ScopedRecord:
        if not isinstance(data, Mapping):
            raise TypeError("ScopedRecord data must be a mapping")
        return cls(
            record_id=str(data.get("record_id", "")),
            scope=AgentScope.parse(data.get("scope", AgentScope.GLOBAL.value)),
            scope_id=data.get("scope_id", ""),
            key=str(data.get("key", "")),
            value=data.get("value"),
            confidence=float(data.get("confidence", 1.0)),
            evidence_ids=tuple(data.get("evidence_ids") or ()),
            created_at=float(data.get("created_at", 0.0)),
            status=str(data.get("status", "active")),
            sensitivity=str(data.get("sensitivity", "normal")),
            provenance=dict(data.get("provenance") or {}),
        )


class ScopeResolver:
    def resolve(
        self,
        records: Iterable[ScopedRecord] | None,
        context: ScopeContext | None,
    ) -> list[ScopedRecord]:
        if records is None:
            return []
        ctx = context or ScopeContext()
        applicable: list[ScopedRecord] = []
        for r in records:
            if r.status in ("active", "confirmed") and ctx.matches(r.scope, r.scope_id):
                applicable.append(r)

        groups: dict[str, list[ScopedRecord]] = {}
        for r in applicable:
            k = r.key or r.record_id
            groups.setdefault(k, []).append(r)

        results: list[ScopedRecord] = []
        for _, recs in groups.items():
            if len(recs) == 1:
                results.append(recs[0])
                continue

            def _safe_float(val: Any) -> float:
                try:
                    f = float(val or 0.0)
                    return f if math.isfinite(f) else 0.0
                except (TypeError, ValueError, OverflowError):
                    return 0.0

            # Deterministic resolution:
            # 1. Higher scope specificity rank wins (more specific scope)
            # 2. Evidence quality: count of verified evidence IDs
            # 3. Calibrated confidence
            # 4. Freshness (timestamp)
            best = max(
                recs,
                key=lambda r: (
                    r.scope.rank,
                    len(r.evidence_ids),
                    _safe_float(r.confidence),
                    _safe_float(r.created_at),
                ),
            )
            results.append(best)

        return results

    def resolve_one(
        self,
        records: Iterable[ScopedRecord] | None,
        context: ScopeContext | None,
        key: str,
    ) -> ScopedRecord | None:
        if records is None:
            return None
        clean_key = str(key or "").replace("\x00", "").strip()
        filtered = [r for r in records if (r.key or r.record_id) == clean_key]
        resolved = self.resolve(filtered, context)
        return resolved[0] if resolved else None


@dataclass(frozen=True)
class RepositoryIdentity:
    family_id: str
    normalized_name: str
    repo_id: str

    def is_local(self) -> bool:
        return "local" in self.family_id or "local" in self.repo_id

    def to_dict(self) -> dict[str, str]:
        return {
            "family_id": self.family_id,
            "normalized_name": self.normalized_name,
            "repo_id": self.repo_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RepositoryIdentity:
        if not isinstance(data, Mapping):
            raise TypeError("RepositoryIdentity data must be a mapping")
        return cls(
            family_id=str(data.get("family_id", "")),
            normalized_name=str(data.get("normalized_name", "")),
            repo_id=str(data.get("repo_id", "")),
        )

    @classmethod
    def derive(
        cls,
        root: str | Path | None = None,
        remote_url: str | None = None,
    ) -> RepositoryIdentity:
        if remote_url:
            cleaned = remote_url.strip().lower()
            cleaned = re.sub(r"^(?:ssh://)?git@[^:/]+[:/](?:\d+/)?", "", cleaned)
            cleaned = re.sub(r"^https?://[^/]+/", "", cleaned)
            cleaned = re.sub(r"^ssh://[^/]+/", "", cleaned)
            cleaned = re.sub(r"\.git$", "", cleaned)
            cleaned = cleaned.rstrip("/")
            name = cleaned.split("/")[-1] if "/" in cleaned else cleaned
            h = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:16]
            return cls(
                family_id=f"repofam_{h}",
                normalized_name=name or "repo",
                repo_id=f"repo_{h}",
            )

        # No remote available: local stable opaque ID
        if root:
            canonical_path = os.path.normcase(str(Path(root).resolve(strict=False)))
            base_name = Path(canonical_path).name or "local_repo"
            seed = canonical_path
        else:
            seed = "local_repo"
            base_name = "local_repo"
        h = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
        return cls(
            family_id=f"repofam_local_{h}",
            normalized_name=base_name,
            repo_id=f"repo_local_{h}",
        )


_SECRET_KEY_PATTERNS = re.compile(
    r"(token|secret|key|auth|pass|pwd|cred|cookie|cert|signature)",
    re.IGNORECASE,
)
_PATH_KEY_PATTERNS = re.compile(
    r"^(path|pythonpath|temp|tmp|home|userprofile|appdata|windir|dir)$",
    re.IGNORECASE,
)
_PATH_VALUE_PATTERNS = re.compile(
    r"(^[a-zA-Z]:[/\\]|^/[a-zA-Z0-9_\.-]+|\\|/)",
)


@dataclass(frozen=True)
class EnvironmentCapsule:
    values: dict[str, Any]

    @classmethod
    def from_mapping(cls, env: Mapping[str, Any] | None) -> EnvironmentCapsule:
        if env is None or not isinstance(env, Mapping):
            return cls(values={})
        sanitized: dict[str, Any] = {}
        for k, v in env.items():
            key_str = str(k).strip()
            if not key_str:
                continue
            if _SECRET_KEY_PATTERNS.search(key_str):
                continue
            if _PATH_KEY_PATTERNS.search(key_str):
                continue

            if isinstance(v, bool):
                sanitized[key_str] = v
            elif isinstance(v, (int, float)):
                if isinstance(v, float) and not math.isfinite(v):
                    continue
                sanitized[key_str] = v
            elif isinstance(v, str):
                val_str = v.strip()
                if len(val_str) > 256:
                    continue
                if _PATH_VALUE_PATTERNS.search(val_str):
                    continue
                sanitized[key_str] = val_str
            elif isinstance(v, (list, tuple)):
                if all(
                    (isinstance(item, bool))
                    or (isinstance(item, (int, float)) and math.isfinite(item))
                    or (isinstance(item, str) and not _PATH_VALUE_PATTERNS.search(item))
                    for item in v
                ):
                    sanitized[key_str] = list(v)
        return cls(values=sanitized)

    def is_empty(self) -> bool:
        return len(self.values) == 0

    def contains(self, key: str) -> bool:
        return key in self.values

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    def keys(self) -> tuple[str, ...]:
        return tuple(self.values.keys())

    def to_dict(self) -> dict[str, Any]:
        return dict(self.values)
