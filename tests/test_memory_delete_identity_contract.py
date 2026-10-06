from __future__ import annotations

from pathlib import Path

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import AgentScope
from local_ai_hub.agent_memory import MemoryKind, MemoryRecord, MemoryStore


def test_repository_memory_delete_requires_matching_root_and_tenant(tmp_path: Path):
    root = str(tmp_path / "repository")
    store = MemoryStore(AgentStateStore(tmp_path / "agent_state.sqlite3"))
    record = store.record(MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.REPOSITORY,
        scope_id=root,
        key="repository-delete-identity",
        value="repository private value",
        provenance={"root": root, "tenant": "owner-tenant"},
    ), actor="user")

    assert store.delete(record.record_id) is False
    assert store.delete(
        record.record_id,
        scope=record.scope,
        scope_id=record.scope_id,
        root=str(tmp_path / "other-repository"),
        tenant="owner-tenant",
    ) is False
    assert store.delete(
        record.record_id,
        scope=record.scope,
        scope_id=record.scope_id,
        root=root,
        tenant="other-tenant",
    ) is False
    assert store.get(
        record.record_id,
        scope=record.scope,
        scope_id=record.scope_id,
        root=root,
        tenant="owner-tenant",
    ) == record
    assert store.delete(
        record.record_id,
        scope=record.scope,
        scope_id=record.scope_id,
        root=root,
        tenant="owner-tenant",
    ) is True
    assert store.get(record.record_id, include_expired=True) is None
