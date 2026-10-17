from local_ai_hub.agent_identity import AgentScope
from local_ai_hub.agent_memory import _memory_matches_request_scope


def _repository_match(*, scope=AgentScope.REPOSITORY, record_tenant="tenant-a", tenant="tenant-a"):
    return _memory_matches_request_scope(
        scope=scope,
        scope_id="",
        provenance={"root": "C:/repo", "tenant": record_tenant},
        root="C:/repo",
        task_id="",
        tenant=tenant,
    )


def test_repository_memory_match_requires_exact_tenant_and_scope_identity():
    assert _repository_match()
    assert not _repository_match(record_tenant=" tenant-a ")
    assert not _repository_match(tenant=" tenant-a ")
    assert not _repository_match(record_tenant=7)
    assert not _repository_match(scope="repository")


def test_repository_memory_match_rejects_missing_tenant_identity():
    assert not _repository_match(record_tenant="")
    assert not _repository_match(tenant="")
