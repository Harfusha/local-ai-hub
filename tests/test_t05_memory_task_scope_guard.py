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
from task_memory_support import repository_memory_id


@pytest.fixture
def task_memory(tmp_path: Path):
    state = AgentStateStore(tmp_path / "memory.sqlite3")
    store = MemoryStore(state)
    root = tmp_path / "repo-a"
    root.mkdir()
    other_root = tmp_path / "repo-b"
    other_root.mkdir()
    root_id = repository_memory_id(root, state)
    other_id = repository_memory_id(other_root, state)
    records = {}
    for name, scope_id, provenance in (
        ("valid", "shared-task", {"root": str(root), "repository_id": root_id, "task_id": "shared-task"}),
        ("other_task", "other-task", {"root": str(root), "repository_id": root_id, "task_id": "other-task"}),
        ("other_project", "shared-task", {"root": str(other_root), "repository_id": other_id, "task_id": "shared-task"}),
        ("missing_root", "shared-task", {"repository_id": root_id, "task_id": "shared-task"}),
    ):
        record = MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope=AgentScope.TASK,
            scope_id=scope_id,
            key="scope-guard",
            value=name,
            status=MemoryStatus.CONFIRMED,
            source="user",
            provenance=provenance,
        )
        store._save_record(record)
        records[name] = record
    return store, root, other_root, records, root_id


def test_task_lookup_requires_physical_root(task_memory):
    store, root, _other_root, records, _root_id = task_memory
    request = {"scope": AgentScope.TASK, "scope_id": "shared-task", "task_id": "shared-task"}
    assert store.find(**request, semantic=False) == []
    for record in records.values():
        assert store.get(record.record_id, **request) is None
    found = store.find(**request, root=str(root), semantic=False)
    assert [record.record_id for record in found] == [records["valid"].record_id]
    assert store.get(records["valid"].record_id, **request, root=str(root)) == records["valid"]


def test_task_lookup_preserves_task_and_repository_boundaries(task_memory):
    store, root, other_root, records, root_id = task_memory
    assert store.find(
        scope=AgentScope.TASK, scope_id="shared-task", task_id="shared-task",
        root=str(root), repository_id=root_id, semantic=False,
    ) == [records["valid"]]
    assert store.find(
        scope=AgentScope.TASK, scope_id="other-task", task_id="other-task",
        root=str(root), semantic=False,
    ) == [records["other_task"]]
    assert store.get(
        records["other_project"].record_id, scope=AgentScope.TASK,
        scope_id="shared-task", task_id="shared-task", root=str(root), repository_id=root_id,
    ) is None
    assert store.find(
        scope=AgentScope.TASK, scope_id="shared-task", task_id="shared-task",
        root=str(root), repository_id=repository_memory_id(other_root, store.state_store), semantic=False,
    ) == []
    assert store.find_for_context(
        root=str(other_root), task_id="shared-task",
        coordination_id=repository_memory_id(other_root, store.state_store),
    ) == [records["other_project"]]


def test_task_context_requires_root_and_matches_task(task_memory):
    store, root, _other_root, records, _root_id = task_memory
    assert store.find_for_context(root="", task_id="shared-task") == []
    assert store.find_for_context(
        root=str(root), task_id="shared-task",
        coordination_id=repository_memory_id(root, store.state_store),
    ) == [records["valid"]]


def test_task_matcher_requires_matching_root_and_actual_task_identity(task_memory):
    _store, root, other_root, _records, _root_id = task_memory
    provenance = {"root": str(root), "task_id": "shared-task"}
    assert _memory_matches_request_scope(
        scope=AgentScope.TASK, scope_id="shared-task", task_id="shared-task",
        root=str(root), provenance=provenance,
    )
    assert not _memory_matches_request_scope(
        scope=AgentScope.TASK, scope_id="shared-task", task_id="shared-task",
        root=str(other_root), provenance=provenance,
    )
    assert not _memory_matches_request_scope(
        scope=AgentScope.TASK, scope_id="other-task", task_id="shared-task",
        root=str(root), provenance=provenance,
    )
    assert not _memory_matches_request_scope(
        scope=AgentScope.TASK, scope_id="shared-task", task_id="shared-task",
        root=str(root), provenance={"task_id": "shared-task"},
    )


def test_retired_tenant_selectors_and_provenance_reject(task_memory):
    store, root, _other_root, _records, _root_id = task_memory
    with pytest.raises(TypeError):
        store.find(root=str(root), task_id="shared-task", tenant="retired", semantic=False)
    with pytest.raises(ValueError, match="retired memory identity field"):
        _memory_matches_request_scope(
            scope=AgentScope.TASK, scope_id="shared-task", task_id="shared-task",
            root=str(root), provenance={"root": str(root), "tenant": None},
        )


def test_unconfigured_store_preserves_owner_global_lookup(task_memory):
    store, _root, _other_root, records, _root_id = task_memory
    record = MemoryRecord.create(kind=MemoryKind.FACT, scope=AgentScope.GLOBAL, key="global-owner-fact", value="safe")
    store._save_record(record)
    assert store.get(record.record_id) == record
    assert store.find(scope=AgentScope.GLOBAL, key="global-owner-fact", semantic=False) == [record]
    assert store.get(records["missing_root"].record_id, task_id="shared-task") is None


def test_unscoped_find_cannot_return_task_memory(task_memory):
    store, _root, _other_root, records, _root_id = task_memory
    assert store.find(query="scope-guard", semantic=False) == []
    assert store.find(record_id=records["valid"].record_id, semantic=False) == []
