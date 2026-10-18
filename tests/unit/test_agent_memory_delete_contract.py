import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import AgentScope
from local_ai_hub.agent_memory import MemoryKind, MemoryRecord, MemoryStore


class _CanonicalScopeString:
    def __str__(self):
        return "repository"


def _store_that_must_not_reach_storage(monkeypatch, tmp_path):
    store = object.__new__(MemoryStore)
    store.state_store = SimpleNamespace(enabled=True, db_path=Path(tmp_path) / "state.sqlite")
    store.state_store.db_path.touch()
    monkeypatch.setattr(store, "_init_table", lambda: (_ for _ in ()).throw(AssertionError("storage reached")))
    return store


def test_memory_delete_rejects_nonstring_scope_coercion(monkeypatch, tmp_path):
    store = _store_that_must_not_reach_storage(monkeypatch, tmp_path)
    assert not store.delete(
        "record-1",
        scope=_CanonicalScopeString(),
        repository_id="repo-1",
    )


def test_memory_delete_rejects_retired_tenant_keyword_before_storage(monkeypatch, tmp_path):
    store = _store_that_must_not_reach_storage(monkeypatch, tmp_path)
    with pytest.raises(TypeError, match="tenant"):
        store.delete("record-1", scope="repository", repository_id="repo-1", tenant=None)


@pytest.mark.parametrize(
    "identity",
    [
        {"root": 7},
        {"root": " /project "},
        {"scope_id": 7},
        {"scope_id": " repo-1 "},
        {"repository_id": 7},
        {"repository_id": ""},
        {"repository_id": " repo-1 "},
    ],
)
def test_memory_delete_rejects_coercive_or_trimmed_canonical_ids(monkeypatch, tmp_path, identity):
    store = _store_that_must_not_reach_storage(monkeypatch, tmp_path)
    supplied = {"repository_id": "repo-1", **identity}
    assert not store.delete(
        "record-1",
        scope="repository",
        **supplied,
    )


def _record_for_delete(tmp_path, scope, *, scope_id="", provenance=None):
    store = MemoryStore(AgentStateStore(tmp_path / "agent-state.sqlite3"))
    record = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=scope,
        scope_id=scope_id,
        key="delete-contract",
        value="contract test",
        source="user",
        provenance=provenance or {},
    )
    store.record(record, actor="user")
    return store, record


def test_memory_delete_global_remains_owner_global(tmp_path):
    store, record = _record_for_delete(tmp_path, AgentScope.GLOBAL)
    assert store.delete(record.record_id, scope=AgentScope.GLOBAL)


def test_memory_delete_global_needs_no_transport_partition(tmp_path):
    store, record = _record_for_delete(tmp_path, AgentScope.GLOBAL)
    assert store.delete(record.record_id, scope=AgentScope.GLOBAL)


@pytest.mark.parametrize("provenance", ["not-json", "[]", ""])
def test_memory_delete_global_rejects_malformed_provenance(tmp_path, provenance):
    store, record = _record_for_delete(
        tmp_path,
        AgentScope.GLOBAL,
        provenance={},
    )
    con = sqlite3.connect(store.state_store.db_path)
    try:
        con.execute(
            "UPDATE agent_memory_records SET provenance = ? WHERE record_id = ?",
            (provenance, record.record_id),
        )
        con.commit()
    finally:
        con.close()

    assert not store.delete(record.record_id, scope=AgentScope.GLOBAL)


def test_memory_delete_supplied_root_must_match_stored_root(tmp_path):
    store, record = _record_for_delete(
        tmp_path,
        AgentScope.REPOSITORY,
        scope_id="repo-1",
        provenance={
            "repository_id": "repo-1",
            "root": str(tmp_path / "actual-project"),
        },
    )

    assert not store.delete(
        record.record_id,
        scope=AgentScope.REPOSITORY,
        repository_id="repo-1",
        root=str(tmp_path / "other-project"),
    )
    assert store.delete(
        record.record_id,
        scope=AgentScope.REPOSITORY,
        repository_id="repo-1",
        root=str(tmp_path / "actual-project"),
    )


def test_memory_delete_root_cannot_fall_back_to_repository_id(tmp_path):
    store, record = _record_for_delete(
        tmp_path,
        AgentScope.REPOSITORY,
        scope_id="repo-1",
        provenance={"repository_id": "repo-1"},
    )

    assert not store.delete(
        record.record_id,
        scope=AgentScope.REPOSITORY,
        repository_id="repo-1",
        root=str(tmp_path / "repo-1"),
    )
