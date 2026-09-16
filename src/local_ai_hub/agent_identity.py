from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping


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
    def parse(cls, value: Any, default: AgentScope = TASK) -> AgentScope:
        if isinstance(value, cls):
            return value
        if not value:
            return default
        raw = str(value).strip().lower()
        _ALIASES: dict[str, AgentScope] = {
            "code": cls.TASK,
            "task": cls.TASK,
            "tasks": cls.TASK,
            "repo": cls.REPOSITORY,
            "repository": cls.REPOSITORY,
            "project": cls.REPOSITORY,
            "workspace": cls.WORKTREE,
            "worktree": cls.WORKTREE,
            "worktrees": cls.WORKTREE,
            "clone": cls.CLONE,
            "branch": cls.BRANCH,
            "branches": cls.BRANCH,
            "session": cls.SESSION,
            "sessions": cls.SESSION,
            "global": cls.GLOBAL,
            "user": cls.GLOBAL,
        }
        if raw in _ALIASES:
            return _ALIASES[raw]
        try:
            return cls(raw)
        except ValueError:
            return default


@dataclass(frozen=True)
class ScopeContext:
    repository_id: str = ""
    clone_id: str = ""
    worktree_id: str = ""
    branch: str = ""
    task_id: str = ""
    session_id: str = ""

    def matches(self, scope: AgentScope, scope_id: str = "") -> bool:
        if scope == AgentScope.GLOBAL:
            return True
        if scope == AgentScope.REPOSITORY:
            return not scope_id or scope_id == self.repository_id
        if scope == AgentScope.CLONE:
            return bool(self.clone_id) and (not scope_id or scope_id == self.clone_id)
        if scope == AgentScope.WORKTREE:
            return bool(self.worktree_id) and (not scope_id or scope_id == self.worktree_id)
        if scope == AgentScope.BRANCH:
            return bool(self.branch) and (not scope_id or scope_id == self.branch)
        if scope == AgentScope.TASK:
            return bool(self.task_id) and (not scope_id or scope_id == self.task_id)
        if scope == AgentScope.SESSION:
            return bool(self.session_id) and (not scope_id or scope_id == self.session_id)
        return False


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


class ScopeResolver:
    def resolve(
        self,
        records: Iterable[ScopedRecord],
        context: ScopeContext,
    ) -> list[ScopedRecord]:
        applicable: list[ScopedRecord] = []
        for r in records:
            if r.status in ("active", "confirmed") and context.matches(r.scope, r.scope_id):
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
                    float(r.confidence),
                    float(r.created_at),
                ),
            )
            results.append(best)

        return results


@dataclass(frozen=True)
class RepositoryIdentity:
    family_id: str
    normalized_name: str
    repo_id: str

    @classmethod
    def derive(
        cls,
        root: str | Path | None = None,
        remote_url: str | None = None,
    ) -> RepositoryIdentity:
        if remote_url:
            cleaned = remote_url.strip().lower()
            cleaned = re.sub(r"^git@[^:]+:", "", cleaned)
            cleaned = re.sub(r"^https?://[^/]+/", "", cleaned)
            cleaned = re.sub(r"\.git$", "", cleaned)
            name = cleaned.strip("/").split("/")[-1] if "/" in cleaned else cleaned
            h = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:16]
            return cls(
                family_id=f"repofam_{h}",
                normalized_name=name or "repo",
                repo_id=f"repo_{h}",
            )

        # No remote available: local stable opaque ID
        seed = str(root or "local_repo")
        # Ensure no user personal paths are exposed
        base_name = Path(seed).name or "local_repo"
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
    def from_mapping(cls, env: Mapping[str, Any]) -> EnvironmentCapsule:
        sanitized: dict[str, Any] = {}
        for k, v in env.items():
            key_str = str(k).strip()
            if _SECRET_KEY_PATTERNS.search(key_str):
                continue
            if _PATH_KEY_PATTERNS.search(key_str):
                continue

            if isinstance(v, (int, float, bool)):
                sanitized[key_str] = v
            elif isinstance(v, str):
                val_str = v.strip()
                if len(val_str) > 256:
                    continue
                if _PATH_VALUE_PATTERNS.search(val_str):
                    continue
                sanitized[key_str] = val_str
            elif isinstance(v, (list, tuple)):
                if all(isinstance(item, (int, float, bool, str)) and not _PATH_VALUE_PATTERNS.search(str(item)) for item in v):
                    sanitized[key_str] = list(v)
        return cls(values=sanitized)

    def to_dict(self) -> dict[str, Any]:
        return dict(self.values)
