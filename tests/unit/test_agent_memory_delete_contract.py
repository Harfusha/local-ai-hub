from pathlib import Path
from types import SimpleNamespace

from local_ai_hub.agent_memory import MemoryStore


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
        tenant="tenant-a",
    )


def test_memory_delete_rejects_nonstring_tenant_coercion(monkeypatch, tmp_path):
    store = _store_that_must_not_reach_storage(monkeypatch, tmp_path)
    assert not store.delete(
        "record-1",
        scope="repository",
        repository_id="repo-1",
        tenant=7,
    )
