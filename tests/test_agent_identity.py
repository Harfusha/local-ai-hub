from __future__ import annotations

import pytest

from local_ai_hub.agent_identity import (
    AgentScope,
    EnvironmentCapsule,
    RepositoryIdentity,
    ScopeContext,
    ScopedRecord,
    ScopeResolver,
)


def test_more_specific_scope_wins_without_last_write_wins():
    resolver = ScopeResolver()
    ctx = ScopeContext(repository_id="repo-1", branch="feature", task_id="task-1")
    global_rec = ScopedRecord(
        record_id="rec-1",
        scope=AgentScope.GLOBAL,
        key="build_tool",
        value="make",
        confidence=0.9,
        created_at=200.0,
    )
    branch_rec = ScopedRecord(
        record_id="rec-2",
        scope=AgentScope.BRANCH,
        scope_id="feature",
        key="build_tool",
        value="ninja",
        confidence=0.8,
        created_at=100.0,  # Older than global_rec, but branch scope is more specific
    )
    chosen = resolver.resolve(records=[global_rec, branch_rec], context=ctx)
    assert len(chosen) == 1
    assert chosen[0].scope == AgentScope.BRANCH
    assert chosen[0].value == "ninja"


def test_environment_capsule_drops_paths_and_secret_like_keys():
    capsule = EnvironmentCapsule.from_mapping({
        "PATH": "C:/secret",
        "TOKEN": "x",
        "API_KEY": "supersecret",
        "USER_PASS": "pass123",
        "SOME_PATH": "/usr/local/bin",
        "python": "3.11",
        "platform": "win32",
    })
    assert capsule.values == {"python": "3.11", "platform": "win32"}


def test_repository_identity_normalization():
    ident1 = RepositoryIdentity.derive(remote_url="https://github.com/Example/repo.git")
    ident2 = RepositoryIdentity.derive(remote_url="git@github.com:example/repo")
    assert ident1.family_id == ident2.family_id
    assert not ident1.family_id.startswith("C:")
    assert not ident1.family_id.startswith("/")


def test_scope_context_matching():
    resolver = ScopeResolver()
    ctx = ScopeContext(repository_id="repo-1", branch="main")
    task_rec = ScopedRecord(
        record_id="rec-t",
        scope=AgentScope.TASK,
        scope_id="task-99",
        key="target",
        value="x",
    )
    repo_rec = ScopedRecord(
        record_id="rec-r",
        scope=AgentScope.REPOSITORY,
        scope_id="repo-1",
        key="target",
        value="y",
    )
    resolved = resolver.resolve(records=[task_rec, repo_rec], context=ctx)
    # task_rec does not match context because context has no task-99
    assert len(resolved) == 1
    assert resolved[0].scope == AgentScope.REPOSITORY
    assert resolved[0].value == "y"


def test_equal_scope_resolves_by_evidence_confidence_and_freshness():
    resolver = ScopeResolver()
    ctx = ScopeContext(repository_id="repo-1")
    rec_low_conf = ScopedRecord(
        record_id="r1",
        scope=AgentScope.REPOSITORY,
        scope_id="repo-1",
        key="port",
        value=8080,
        confidence=0.5,
        created_at=200.0,
    )
    rec_high_conf = ScopedRecord(
        record_id="r2",
        scope=AgentScope.REPOSITORY,
        scope_id="repo-1",
        key="port",
        value=9090,
        confidence=0.95,
        evidence_ids=("ev-1",),
        created_at=100.0,
    )
    chosen = resolver.resolve(records=[rec_low_conf, rec_high_conf], context=ctx)
    assert len(chosen) == 1
    assert chosen[0].record_id == "r2"
    assert chosen[0].value == 9090


def test_agent_scope_parse_defaults_and_aliases():
    assert AgentScope.parse(None) is AgentScope.TASK
    assert isinstance(AgentScope.parse(None), AgentScope)
    assert AgentScope.parse(None).value == "task"

    assert AgentScope.parse("") is AgentScope.TASK
    assert AgentScope.parse("code") is AgentScope.TASK
    assert AgentScope.parse("tasks") is AgentScope.TASK
    assert AgentScope.parse("repo") is AgentScope.REPOSITORY
    assert AgentScope.parse("workspace") is AgentScope.WORKTREE

    assert AgentScope.parse("nonexistent_scope") is AgentScope.TASK
    assert AgentScope.parse("nonexistent_scope", AgentScope.GLOBAL) is AgentScope.GLOBAL
    assert AgentScope.parse("nonexistent_scope", "clone") is AgentScope.CLONE
