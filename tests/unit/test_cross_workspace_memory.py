from __future__ import annotations

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import AgentScope
from local_ai_hub.agent_memory import MemoryKind, MemoryRecord, MemoryStore


def test_owner_global_memory_is_retrievable_across_project_roots(tmp_path):
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
            source="user",
        ),
        actor="user",
    )

    first_results = store.find_for_context(root=str(first_root))
    second_results = store.find_for_context(root=str(second_root))

    assert any(item.key == "shared-convention" for item in first_results)
    assert any(item.key == "shared-convention" for item in second_results)
    assert any(item.key == "shared-convention" for item in store.find_for_context())


def test_explicit_owner_global_memory_remains_shared_without_project_context(tmp_path):
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

    project_results = store.find_for_context(root=str(project_root))
    tenantless_results = store.find_for_context()

    assert any(item.key == "unowned-global-memory" for item in project_results)
    assert any(item.key == "unowned-global-memory" for item in tenantless_results)


def test_repository_memory_uses_coordination_identity_across_paths(tmp_path):
    first_root = tmp_path / "first-project"
    second_root = tmp_path / "second-project"
    first_root.mkdir()
    second_root.mkdir()
    store = MemoryStore(AgentStateStore(tmp_path / "agent-state.sqlite3"))
    store.record(
        MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=AgentScope.REPOSITORY,
            scope_id="repo-first",
            key="repository-convention",
            value="Keep this within the resolved repository identity.",
            source="user",
            provenance={"repository_id": "repo-first"},
        ),
        actor="user",
    )

    first = store.find_for_context(root=str(first_root), coordination_id="repo-first")
    second = store.find_for_context(root=str(second_root), coordination_id="repo-second")

    assert any(item.key == "repository-convention" for item in first)
    assert all(item.key != "repository-convention" for item in second)
