from __future__ import annotations

import math
from pathlib import Path
import pytest

from local_ai_hub.agent_identity import (
    AgentScope,
    EnvironmentCapsule,
    RepositoryIdentity,
    ScopeContext,
    ScopedRecord,
    ScopeResolver,
)


def test_repository_identity_local_path_canonicalization() -> None:
    # Case and slash differences on identical paths should produce identical family_id
    ident_fwd = RepositoryIdentity.derive(root="C:/Users/Adam/Project")
    ident_back = RepositoryIdentity.derive(root="c:\\users\\adam\\project")
    assert ident_fwd.family_id == ident_back.family_id
    assert ident_fwd.repo_id == ident_back.repo_id


def test_repository_identity_remote_url_normalization() -> None:
    # Trailing slashes, ssh:// prefix, and .git extensions should normalize identically
    ident_normal = RepositoryIdentity.derive(remote_url="https://github.com/org/repo")
    ident_trailing_slash = RepositoryIdentity.derive(remote_url="https://github.com/org/repo/")
    ident_ssh_prefix = RepositoryIdentity.derive(remote_url="ssh://git@github.com/org/repo.git")

    assert ident_normal.family_id == ident_trailing_slash.family_id
    assert ident_normal.family_id == ident_ssh_prefix.family_id
    assert ident_normal.normalized_name == "repo"


def test_scope_context_string_alias_matching_and_helpers() -> None:
    ctx = ScopeContext(repository_id="repo-1", worktree_id="wt-1", task_id="t-1")

    # String aliases should match their respective scopes
    assert ctx.matches("repo", "repo-1") is True
    assert ctx.matches("project", "repo-1") is True
    assert ctx.matches("workspace", "wt-1") is True
    assert ctx.matches("worktree", "wt-1") is True
    assert ctx.matches("task", "t-1") is True

    # Inspection helpers
    assert ctx.is_empty() is False
    assert ScopeContext().is_empty() is True
    assert ctx.to_dict()["repository_id"] == "repo-1"


def test_environment_capsule_none_and_nan_inf_safety() -> None:
    # None or non-mapping input returns empty capsule
    c_none = EnvironmentCapsule.from_mapping(None)  # type: ignore[arg-type]
    assert c_none.values == {}

    c_str = EnvironmentCapsule.from_mapping("invalid")  # type: ignore[arg-type]
    assert c_str.values == {}

    # NaN and Inf floats must be dropped
    c_floats = EnvironmentCapsule.from_mapping({
        "valid_num": 100,
        "valid_float": 1.5,
        "nan_val": float("nan"),
        "inf_val": float("inf"),
    })
    assert c_floats.values == {"valid_num": 100, "valid_float": 1.5}


def test_scope_resolver_none_safety_and_nan_confidence() -> None:
    resolver = ScopeResolver()
    assert resolver.resolve(None, None) == []  # type: ignore[arg-type]

    # Nan or None confidence does not crash sorting
    rec1 = ScopedRecord(
        record_id="r1",
        scope=AgentScope.GLOBAL,
        key="k",
        value="v1",
        confidence=float("nan"),
    )
    rec2 = ScopedRecord(
        record_id="r2",
        scope=AgentScope.GLOBAL,
        key="k",
        value="v2",
        confidence=0.8,
    )
    resolved = resolver.resolve([rec1, rec2], ScopeContext())
    assert len(resolved) == 1
    assert resolved[0].value == "v2"
