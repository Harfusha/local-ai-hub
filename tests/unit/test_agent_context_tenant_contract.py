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
