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
    (AgentScope.REPOSITORY, {}),
    (AgentScope.SESSION, {"session_id": "shared-session"}),
    (AgentScope.TASK, {"task_id": "shared-task"}),
])
@pytest.mark.parametrize("tenant", ["", " \t "])
def test_context_without_tenant_excludes_scoped_rows(store, tmp_path, scope, identity, tenant):
    root = str(tmp_path / "repo")
    record = seed(store, scope, {"root": root}, "shared-session" if scope is AgentScope.SESSION else "shared-task")
    shared = seed(store, AgentScope.GLOBAL, {})
    found = store.find_for_context(root=root, tenant=tenant, **identity)
    assert record.record_id not in {item.record_id for item in found}
    assert found == [shared]


@pytest.mark.parametrize("scope,identity", [
    (AgentScope.REPOSITORY, {}),
    (AgentScope.SESSION, {"session_id": "shared-session"}),
])
def test_context_scoped_identity_denies_foreign_owner(store, tmp_path, scope, identity):
    root = str(tmp_path / "repo")
    scope_id = "shared-session" if scope is AgentScope.SESSION else root
    valid = seed(store, scope, {"root": root, "tenant": "tenant-a"}, scope_id)
    seed(store, scope, {"root": str(tmp_path / "other"), "tenant": "tenant-a"}, scope_id)
    seed(store, scope, {"root": root, "tenant": "tenant-b"}, scope_id)
    seed(store, scope, {"root": root}, scope_id)
    assert store.find_for_context(root=root, tenant="tenant-a", **identity) == [valid]
    assert store.find_for_context(root=root, tenant="tenant-a") == ([] if scope is AgentScope.SESSION else [valid])
    if scope is AgentScope.REPOSITORY:
        assert store.find_for_context(tenant="tenant-a") == []


@pytest.mark.parametrize("owner_field", ["root", "repository_id", "session_id", "task_id", "clone_id", "worktree_id", "branch"])
@pytest.mark.parametrize("opt_in", [False, True])
def test_explicit_global_lookup_cannot_omit_provenance_owner(store, owner_field, opt_in):
    record = seed(store, AgentScope.GLOBAL, {owner_field: "owner-identity"})
    assert store.get(record.record_id, scope=AgentScope.GLOBAL, tenant_agnostic_global=opt_in) is None


def test_explicit_global_lookup_rejects_nonempty_scope_id(store):
    record = seed(store, AgentScope.GLOBAL, {}, scope_id="owner-identity")
    assert store.get(record.record_id, scope=AgentScope.GLOBAL) is None
    assert store.get(record.record_id, scope=AgentScope.GLOBAL, tenant_agnostic_global=True) is None


@pytest.mark.parametrize("opt_in", [False, True])
def test_global_owner_lookup_matches_root_and_repository(store, tmp_path, opt_in):
    root = str(tmp_path / "repo")
    record = seed(store, AgentScope.GLOBAL, {"root": root, "repository_id": "repo-a", "tenant": "tenant-a"})
    request = {"scope": AgentScope.GLOBAL, "root": root, "repository_id": "repo-a", "tenant": "tenant-a", "tenant_agnostic_global": opt_in}
    assert store.get(record.record_id, **request) == record
    assert store.get(record.record_id, **{**request, "root": str(tmp_path / "other")}) is None
    assert store.get(record.record_id, **{**request, "repository_id": "other"}) is None
    assert store.get(record.record_id, **{**request, "root": None}) is None
    assert store.get(record.record_id, **{**request, "repository_id": None}) is None
    foreign_tenant = store.get(record.record_id, **{**request, "tenant": "tenant-b"})
    assert foreign_tenant == (record if opt_in else None)


def test_global_context_shares_across_projects_not_tenants(store, tmp_path):
    shared = seed(store, AgentScope.GLOBAL, {"root": str(tmp_path / "foreign-repo"), "repository_id": "foreign-repo", "tenant": "tenant-a"})
    unowned = seed(store, AgentScope.GLOBAL, {})
    seed(store, AgentScope.GLOBAL, {"tenant": "tenant-b"})
    assert {item.record_id for item in store.find_for_context(root=str(tmp_path / "repo"), tenant="tenant-a")} == {shared.record_id, unowned.record_id}
    assert store.find_for_context(root=str(tmp_path / "repo")) == [unowned]


@pytest.mark.parametrize("scope", [AgentScope.TASK, AgentScope.REPOSITORY, AgentScope.SESSION])
def test_tenant_agnostic_opt_in_is_global_only(store, scope):
    record = seed(store, scope, {"root": "repo-a", "tenant": "tenant-a"}, scope_id="identity")
    with pytest.raises(ValueError, match="only valid for GLOBAL"):
        store.get(record.record_id, scope=scope, scope_id="identity", root="repo-a", tenant="tenant-a", tenant_agnostic_global=True)


def test_global_delete_transport_tenant_does_not_override_root(store, tmp_path):
    root = str(tmp_path / "repo")
    record = seed(store, AgentScope.GLOBAL, {"root": root, "tenant": "owner-tenant"})
    assert not store.delete(record.record_id, scope=AgentScope.GLOBAL, root=str(tmp_path / "other"), tenant="transport-tenant")
    assert store.get(record.record_id, scope=AgentScope.GLOBAL, root=root, tenant="owner-tenant") == record
    assert store.delete(record.record_id, scope=AgentScope.GLOBAL, root=root, tenant="transport-tenant")
