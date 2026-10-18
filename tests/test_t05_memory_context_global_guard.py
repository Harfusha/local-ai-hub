"""Direct-record ownership is stricter than intentional GLOBAL context sharing."""

from pathlib import Path

import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import AgentScope
from local_ai_hub.agent_memory import MemoryKind, MemoryRecord, MemoryStatus, MemoryStore


@pytest.fixture
def store(tmp_path: Path):
    return MemoryStore(AgentStateStore(tmp_path / "memory.sqlite3"))


def seed(store, scope, provenance, scope_id=""):
    record = MemoryRecord.create(
        kind=MemoryKind.FACT, scope=scope, scope_id=scope_id, key="identity-guard",
        value="safe", source="user", status=MemoryStatus.CONFIRMED, provenance=provenance,
    )
    store._save_record(record)
    return record


@pytest.mark.parametrize("scope,identity", [
    (AgentScope.REPOSITORY, {"coordination_id": "shared-coord"}),
    (AgentScope.SESSION, {"session_id": "shared-session"}),
    (AgentScope.TASK, {"task_id": "shared-task"}),
])
def test_context_includes_only_matching_declared_scope_identity(store, tmp_path, scope, identity):
    root = str(tmp_path / "repo")
    prov = {"root": root}
    if scope is AgentScope.REPOSITORY:
        prov["repository_id"] = "shared-coord"
    if scope is AgentScope.REPOSITORY:
        scope_id = "shared-coord"
    elif scope is AgentScope.SESSION:
        scope_id = "shared-session"
    else:
        scope_id = "shared-task"
    record = seed(store, scope, prov, scope_id)
    shared = seed(store, AgentScope.GLOBAL, {})
    found = store.find_for_context(root=root, **identity)
    assert {item.record_id for item in found} == {record.record_id, shared.record_id}
    assert store.find_for_context(root=root) == [shared]


@pytest.mark.parametrize("scope,identity", [
    (AgentScope.REPOSITORY, {"coordination_id": "repo-coord"}),
    (AgentScope.SESSION, {"session_id": "shared-session"}),
])
def test_context_scoped_identity_denies_foreign_owner(store, tmp_path, scope, identity):
    root = str(tmp_path / "repo")
    scope_id = "shared-session" if scope is AgentScope.SESSION else root
    prov = {"root": root}
    if scope is AgentScope.REPOSITORY:
        prov["repository_id"] = "repo-coord"
    valid = seed(store, scope, prov, scope_id)
    if scope is AgentScope.REPOSITORY:
        other_coord = seed(
            store, scope,
            {"root": root, "repository_id": "other-coord"},
            scope_id,
        )
        assert store.find_for_context(root=root, **identity) == [valid]
        assert store.find_for_context(root=root, coordination_id="other-coord") == [other_coord]
        assert store.find_for_context() == []
    else:
        other_root = seed(store, scope, {"root": str(tmp_path / "other")}, scope_id)
        other_session = seed(store, scope, {"root": root}, "other-session")
        assert store.find_for_context(root=root, **identity) == [valid]
        assert other_root.record_id not in {item.record_id for item in store.find_for_context(root=root, **identity)}
        assert other_session.record_id not in {item.record_id for item in store.find_for_context(root=root, **identity)}
        assert store.find_for_context(root=root) == []


@pytest.mark.parametrize("owner_field", ["root", "repository_id", "session_id", "task_id", "clone_id", "worktree_id", "branch"])
def test_explicit_global_lookup_cannot_omit_provenance_owner(store, owner_field):
    record = seed(store, AgentScope.GLOBAL, {owner_field: "owner-identity"})
    assert store.get(record.record_id, scope=AgentScope.GLOBAL) is None


def test_explicit_global_lookup_rejects_nonempty_scope_id(store):
    record = seed(store, AgentScope.GLOBAL, {}, scope_id="owner-identity")
    assert store.get(record.record_id, scope=AgentScope.GLOBAL) is None


def test_global_owner_lookup_matches_root_and_repository(store, tmp_path):
    root = str(tmp_path / "repo")
    record = seed(store, AgentScope.GLOBAL, {"root": root, "repository_id": "repo-a"})
    request = {"scope": AgentScope.GLOBAL, "root": root, "repository_id": "repo-a"}
    assert store.get(record.record_id, **request) == record
    assert store.get(record.record_id, **{**request, "root": str(tmp_path / "other")}) is None
    assert store.get(record.record_id, **{**request, "repository_id": "other"}) is None
    assert store.get(record.record_id, **{**request, "root": None}) is None
    assert store.get(record.record_id, **{**request, "repository_id": None}) is None


def test_global_context_shares_owner_records_across_projects(store, tmp_path):
    shared = seed(store, AgentScope.GLOBAL, {"root": str(tmp_path / "foreign-repo"), "repository_id": "foreign-repo"})
    unowned = seed(store, AgentScope.GLOBAL, {})
    assert {item.record_id for item in store.find_for_context(root=str(tmp_path / "repo"))} == {shared.record_id, unowned.record_id}


def test_global_delete_requires_stored_root(store, tmp_path):
    root = str(tmp_path / "repo")
    record = seed(store, AgentScope.GLOBAL, {"root": root})
    assert not store.delete(record.record_id, scope=AgentScope.GLOBAL, root=str(tmp_path / "other"))
    assert store.get(record.record_id, scope=AgentScope.GLOBAL, root=root) == record
    assert store.delete(record.record_id, scope=AgentScope.GLOBAL, root=root)
