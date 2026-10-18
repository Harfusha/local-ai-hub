"""V14-H004/H058 store contracts; these do not assert a live HTTP leak."""

from pathlib import Path

import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import AgentScope
from local_ai_hub.agent_memory import (
    MemoryKind,
    MemoryRecord,
    MemoryStatus,
    MemoryStore,
    _memory_matches_request_scope,
)


@pytest.fixture
def task_memory(tmp_path: Path):
    store = MemoryStore(AgentStateStore(tmp_path / "memory.sqlite3"))
    root = str(tmp_path / "repo-a")
    records = {}
    for name, provenance in {
        "valid": {"root": root, "tenant": "tenant-a", "repository_id": "repo-a"},
        "other_project": {"root": str(tmp_path / "repo-b"), "tenant": "tenant-a"},
        "other_tenant": {"root": root, "tenant": "tenant-b"},
        "missing_root": {"tenant": "tenant-a", "repository_id": "repo-a"},
        "missing_tenant": {"root": root, "repository_id": "repo-a"},
        "missing_both": {},
    }.items():
        record = MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope=AgentScope.TASK,
            scope_id="shared-task",
            key="scope-guard",
            value=name,
            status=MemoryStatus.CONFIRMED,
            source="user",
            provenance=provenance,
        )
        # Lookup-only historical rows, independent of event-publication ownership.
        store._save_record(record)
        records[name] = record
    return store, root, records


@pytest.mark.parametrize("identity", [
    {"task_id": "shared-task"},
    {"scope": AgentScope.TASK, "scope_id": "shared-task"},
])
@pytest.mark.parametrize("missing", ["root", "tenant", "both"])
@pytest.mark.parametrize("repository_id", [None, "repo-a"])
def test_task_lookup_requires_root_and_tenant(task_memory, identity, missing, repository_id):
    store, root, records = task_memory
    request = {
        **identity,
        "root": root if missing == "tenant" else " \t ",
        "tenant": "tenant-a" if missing == "root" else " \t ",
        "repository_id": repository_id,
    }
    assert store.find(**request, semantic=False) == []
    for record in records.values():
        assert store.get(record.record_id, **request) is None


@pytest.mark.parametrize("semantic", [False, True])
@pytest.mark.parametrize("identity", [
    {"task_id": "shared-task"},
    {"scope": AgentScope.TASK, "scope_id": "shared-task"},
])
def test_task_lookup_binds_both_provenance_identities(task_memory, identity, semantic):
    store, root, records = task_memory
    request = {**identity, "root": root, "tenant": "tenant-a"}
    found = store.find(**request, query="scope-guard", semantic=semantic)
    assert [record.record_id for record in found] == [records["valid"].record_id]
    assert store.get(records["valid"].record_id, **request) == records["valid"]
    for name, record in records.items():
        if name != "valid":
            assert store.get(record.record_id, **request) is None


@pytest.mark.parametrize("identity_change", [
    {"tenant": "tenant-b"},
    {"root": "another-project"},
    {"task_id": "other-task"},
    {"repository_id": "another-repository"},
])
def test_task_lookup_denies_cross_identity(task_memory, identity_change):
    store, root, records = task_memory
    request = {"task_id": "shared-task", "root": root, "tenant": "tenant-a", **identity_change}
    assert store.get(records["valid"].record_id, **request) is None
    assert records["valid"].record_id not in {
        record.record_id for record in store.find(**request, semantic=False)
    }


def test_task_repository_id_is_an_additional_constraint(task_memory):
    store, root, records = task_memory
    request = {"task_id": "shared-task", "root": root, "tenant": "tenant-a", "repository_id": "repo-a"}
    assert store.find(**request, semantic=False) == [records["valid"]]
    assert store.get(records["missing_tenant"].record_id, **request) is None


@pytest.mark.parametrize("missing", ["root", "tenant", "both"])
def test_task_context_requires_root_and_tenant(task_memory, missing):
    store, root, _ = task_memory
    assert store.find_for_context(
        root=root if missing == "tenant" else "",

        task_id="shared-task",
    ) == []


def test_task_context_accepts_matching_trusted_identity(task_memory):
    store, root, records = task_memory
    assert store.find_for_context(root=root,  task_id="shared-task") == [records["valid"]]


@pytest.mark.parametrize("identity_request", [
    {"root": "", "tenant": "tenant-a"},
    {"root": "repo-a", "tenant": ""},
    {"root": "", "tenant": ""},
    {"root": "repo-b", "tenant": "tenant-a"},
    {"root": "repo-a", "tenant": "tenant-b"},
])
def test_task_matcher_denies_incomplete_or_foreign_request(identity_request):
    assert not _memory_matches_request_scope(
        scope=AgentScope.TASK, scope_id="shared-task", task_id="shared-task",
        provenance={"root": "repo-a", "tenant": "tenant-a"}, **identity_request,
    )


@pytest.mark.parametrize("provenance", [
    None, {}, {"root": "repo-a"}, {"tenant": "tenant-a"},
    {"root": " \t ", "tenant": "tenant-a"},
    {"root": "repo-a", "tenant": " \t "},
])
def test_task_matcher_requires_nonempty_provenance(provenance):
    assert not _memory_matches_request_scope(
        scope=AgentScope.TASK, scope_id="shared-task", task_id="shared-task",
        root="repo-a",  provenance=provenance,
    )


def test_task_matcher_accepts_matching_identity():
    assert _memory_matches_request_scope(
        scope=AgentScope.TASK, scope_id="shared-task", task_id="shared-task",
        root="repo-a/.",
        provenance={"root": "repo-a", "tenant": "tenant-a"},
    )


def test_unconfigured_store_preserves_unowned_global_lookup(task_memory):
    store, _, records = task_memory
    record = MemoryRecord.create(kind=MemoryKind.FACT, scope=AgentScope.GLOBAL, key="legacy-global", value="safe")
    store._save_record(record)
    assert store.get(record.record_id) == record
    assert store.find(scope=AgentScope.GLOBAL, key="legacy-global", semantic=False) == [record]
    assert store.get(records["missing_both"].record_id, task_id="shared-task") is None


@pytest.mark.parametrize("selector", ["query", "record_id"])
def test_unscoped_find_cannot_return_task_identity(task_memory, selector):
    store, _, records = task_memory
    request = {"query": "scope-guard"} if selector == "query" else {
        "record_id": records["missing_both"].record_id,
    }
    assert store.find(**request, semantic=False) == []
