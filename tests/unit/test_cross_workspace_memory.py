from __future__ import annotations

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import AgentScope
from local_ai_hub.agent_memory import MemoryKind, MemoryRecord, MemoryStore


def test_global_memory_is_retrievable_across_project_roots_within_tenant(tmp_path):
    first_root = tmp_path / "first-project"
    second_root = tmp_path / "second-project"
    first_root.mkdir()
    second_root.mkdir()

    store = MemoryStore(AgentStateStore(tmp_path / "agent-state.sqlite3"))
    store.record(
        MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=AgentScope.GLOBAL,
            key="shared-convention",
            value="Use the shared formatter.",
            provenance={"tenant": "tenant-a"},
            source="user",
        ),
        actor="user",
    )

    first_results = store.find_for_context(root=str(first_root), tenant="tenant-a")
    second_results = store.find_for_context(root=str(second_root), tenant="tenant-a")
    other_tenant_results = store.find_for_context(root=str(second_root), tenant="tenant-b")

    assert any(item.key == "shared-convention" for item in first_results)
    assert any(item.key == "shared-convention" for item in second_results)
    assert all(item.key != "shared-convention" for item in other_tenant_results)


def test_explicit_unowned_global_memory_remains_shared_across_tenants(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    store = MemoryStore(AgentStateStore(tmp_path / "agent-state.sqlite3"))
    store.record(
        MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=AgentScope.GLOBAL,
            key="unowned-global-memory",
            value="No tenant provenance.",
            source="user",
        ),
        actor="user",
    )

    tenant_results = store.find_for_context(root=str(project_root), tenant="tenant-a")
    tenantless_results = store.find_for_context()

    assert any(item.key == "unowned-global-memory" for item in tenant_results)
    assert any(item.key == "unowned-global-memory" for item in tenantless_results)
