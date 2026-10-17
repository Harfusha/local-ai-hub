from types import SimpleNamespace

from local_ai_hub.agent_context import _memory_record_matches_tenant
from local_ai_hub.agent_identity import AgentScope


def _record(*, scope=AgentScope.REPOSITORY, tenant="tenant-a"):
    return SimpleNamespace(scope=scope, provenance={"tenant": tenant})


def test_memory_context_requires_exact_tenant_identity():
    assert _memory_record_matches_tenant(_record(tenant="tenant-a"), "tenant-a")
    assert not _memory_record_matches_tenant(_record(tenant=" tenant-a "), "tenant-a")
    assert not _memory_record_matches_tenant(_record(tenant="tenant-a"), " tenant-a ")


def test_memory_context_rejects_noncanonical_scope_and_tenant_types():
    assert not _memory_record_matches_tenant(_record(scope=" GLOBAL ", tenant=""), "tenant-a")
    assert not _memory_record_matches_tenant(_record(scope=AgentScope.GLOBAL, tenant=7), "tenant-a")
    assert not _memory_record_matches_tenant(_record(tenant="tenant-a"), 7)


def test_memory_context_keeps_unscoped_global_filter_semantics():
    assert _memory_record_matches_tenant(_record(scope=AgentScope.GLOBAL, tenant=""), "")
    assert not _memory_record_matches_tenant(_record(scope=AgentScope.GLOBAL, tenant="session-1"), "")
    assert not _memory_record_matches_tenant(_record(scope=AgentScope.REPOSITORY, tenant=""), "")


def test_preload_without_tenant_does_not_substitute_session_identity(tmp_path):
    from local_ai_hub.agent_context import ContextCompiler, ContextRequest
    from local_ai_hub.agent_events import AgentStateStore

    tagged_global = SimpleNamespace(
        record_id="session-tagged-global",
        kind=SimpleNamespace(value="fact"),
        key="private",
        value="session-tagged data",
        evidence_ids=(),
        confidence=1.0,
        updated_at=1.0,
        scope=AgentScope.GLOBAL,
        provenance={"tenant": "session-1"},
    )

    class MemoryStore:
        def find_for_context(self, **_kwargs):
            return [tagged_global]

    compiler = ContextCompiler(
        AgentStateStore(tmp_path / "state.sqlite3"),
        memory_store=MemoryStore(),
        config={"context": {"preloads": {"memory_kinds": ["fact"], "max_memory": 2}}},
    )

    elements = compiler._load_preloads(
        ContextRequest(task_id="task-1", root=str(tmp_path), session_id="session-1"),
        [],
    )

    assert not any(element.source_kind == "preload_memory" for _, element in elements)
