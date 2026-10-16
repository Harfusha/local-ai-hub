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


def test_scope_context_accepts_only_canonical_scope_values() -> None:
    ctx = ScopeContext(repository_id="repo-1", worktree_id="wt-1", task_id="t-1")

    assert ctx.matches(AgentScope.REPOSITORY, "repo-1") is True
    assert ctx.matches(AgentScope.WORKTREE, "wt-1") is True
    assert ctx.matches(AgentScope.TASK, "t-1") is True
    for alias in ("repo", "project", "workspace", "GLOBAL", " repository "):
        with pytest.raises(ValueError):
            ctx.matches(alias, "repo-1")

    # Inspection helpers
    assert ctx.is_empty() is False
    assert ScopeContext().is_empty() is True
    assert ctx.to_dict()["repository_id"] == "repo-1"


@pytest.mark.parametrize("value", [None, 3, " repo-1", "repo-1 ", "repo\x00-1"])
def test_scope_context_rejects_noncanonical_identity_values(value: object) -> None:
    with pytest.raises(ValueError):
        ScopeContext(repository_id=value)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ScopeContext.from_dict({"repository_id": value})


@pytest.mark.parametrize("scope_id", [3, " repo-1", "repo-1 ", "repo\x00-1"])
def test_scoped_record_rejects_noncanonical_scope_identity(scope_id: object) -> None:
    with pytest.raises(ValueError):
        ScopedRecord(record_id="record-1", scope=AgentScope.REPOSITORY, scope_id=scope_id)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ScopedRecord.from_dict({"record_id": "record-1", "scope": "repository", "scope_id": scope_id})


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


def test_scope_context_canonical_ids_from_dict_and_helpers() -> None:
    ctx = ScopeContext(
        repository_id="repo-1",
        clone_id="clone-1",
        worktree_id="wt-1",
        branch="main",
        task_id="t-1",
        session_id="s-1",
    )
    assert ctx.repository_id == "repo-1"
    assert ctx.clone_id == "clone-1"
    assert ctx.worktree_id == "wt-1"
    assert ctx.branch == "main"
    assert ctx.task_id == "t-1"
    assert ctx.session_id == "s-1"

    assert ctx.has_task() is True
    assert ctx.has_session() is True
    assert ctx.has_repository() is True
    assert ctx.has_worktree() is True
    assert ctx.has_branch() is True

    # with_task and with_session
    ctx2 = ctx.with_task("t-2")
    assert ctx2.task_id == "t-2"
    assert ctx2.repository_id == "repo-1"

    ctx3 = ctx.with_session("s-2")
    assert ctx3.session_id == "s-2"
    assert ctx3.task_id == "t-1"

    # from_dict and TypeError on invalid input
    d = ctx.to_dict()
    recovered = ScopeContext.from_dict(d)
    assert recovered == ctx

    with pytest.raises(TypeError):
        ScopeContext.from_dict("invalid")  # type: ignore[arg-type]


def test_scoped_record_sanitization_serialization_and_helpers() -> None:
    rec = ScopedRecord(
        record_id=" rec-1\x00 ",
        scope="task",  # type: ignore[arg-type]
        scope_id="t-1",
        key=" my_key\x00 ",
        value={"data": 123},
        confidence=1.5,
        evidence_ids=(" ev1\x00 ", ""),
        created_at=-10.0,
        status=" confirmed\x00 ",
        sensitivity=" normal\x00 ",
    )
    assert rec.record_id == "rec-1"
    assert rec.scope == AgentScope.TASK
    assert rec.scope_id == "t-1"
    assert rec.key == "my_key"
    assert rec.confidence == 1.0
    assert rec.evidence_ids == ("ev1",)
    assert rec.created_at == 0.0
    assert rec.status == "confirmed"
    assert rec.sensitivity == "normal"

    assert rec.is_active() is True
    assert rec.is_tombstone() is False
    assert rec.has_evidence() is True

    # Serialization roundtrip
    d = rec.to_dict()
    assert d["record_id"] == "rec-1"
    assert d["scope"] == "task"
    assert d["key"] == "my_key"

    recovered = ScopedRecord.from_dict(d)
    assert recovered.record_id == "rec-1"
    assert recovered.scope == AgentScope.TASK
    assert recovered.key == "my_key"

    with pytest.raises(TypeError):
        ScopedRecord.from_dict("invalid")  # type: ignore[arg-type]


def test_repository_identity_serialization_and_helpers() -> None:
    ident = RepositoryIdentity(
        family_id="repofam_local_123",
        normalized_name="my_repo",
        repo_id="repo_local_123",
    )
    assert ident.is_local() is True

    ident_remote = RepositoryIdentity(
        family_id="repofam_123",
        normalized_name="remote_repo",
        repo_id="repo_123",
    )
    assert ident_remote.is_local() is False

    d = ident.to_dict()
    assert d["family_id"] == "repofam_local_123"
    recovered = RepositoryIdentity.from_dict(d)
    assert recovered == ident

    with pytest.raises(TypeError):
        RepositoryIdentity.from_dict("invalid")  # type: ignore[arg-type]


def test_environment_capsule_inspection_helpers() -> None:
    cap = EnvironmentCapsule.from_mapping({"FOO": "bar", "NUM": 42})
    assert cap.is_empty() is False
    assert cap.contains("FOO") is True
    assert cap.contains("BAR") is False
    assert cap.get("FOO") == "bar"
    assert cap.get("BAR", "default") == "default"
    assert cap.keys() == ("FOO", "NUM")

    empty_cap = EnvironmentCapsule.from_mapping({})
    assert empty_cap.is_empty() is True
    assert empty_cap.keys() == ()


def test_scope_resolver_resolve_one_and_tombstones() -> None:
    resolver = ScopeResolver()
    ctx = ScopeContext(task_id="t1")

    rec1 = ScopedRecord(
        record_id="r1",
        scope=AgentScope.TASK,
        scope_id="t1",
        key="config",
        value="v1",
        confidence=0.9,
    )
    rec2 = ScopedRecord(
        record_id="r2",
        scope=AgentScope.TASK,
        scope_id="t1",
        key="config",
        value="v2",
        confidence=0.95,
    )
    rec_tombstone = ScopedRecord(
        record_id="r3",
        scope=AgentScope.TASK,
        scope_id="t1",
        key="deleted_key",
        value="dead",
        status="tombstone",
    )

    resolved_one = resolver.resolve_one([rec1, rec2, rec_tombstone], ctx, "config")
    assert resolved_one is not None
    assert resolved_one.record_id == "r2"

    resolved_tomb = resolver.resolve_one([rec1, rec2, rec_tombstone], ctx, "deleted_key")
    assert resolved_tomb is None

    assert resolver.resolve_one(None, ctx, "config") is None

