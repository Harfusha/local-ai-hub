from types import SimpleNamespace

from local_ai_hub.agent_consistency import AgentConsistencyGuard, ConsistencyRequest


def make_guard(monkeypatch, tmp_path, namespace):
    from local_ai_hub import project_config

    writes = []

    def record(value, **kwargs):
        writes.append((value, kwargs))
        return value

    monkeypatch.setattr(project_config, "resolve_project_context", lambda *args: SimpleNamespace(coordination_id=namespace))
    tools = SimpleNamespace(config={"server": {"state_dir": str(tmp_path / "state")}})
    guard = AgentConsistencyGuard(tools, memory_store=SimpleNamespace(record=record))
    monkeypatch.setattr(guard, "_revision", lambda *args: "revision-current")
    return guard, writes


def test_missing_tenant_cannot_write_repository_memory(monkeypatch, tmp_path):
    guard, writes = make_guard(monkeypatch, tmp_path, "repository-current")
    assert guard.record_finding(ConsistencyRequest(root=str(tmp_path)), finding="claim") is None
    assert writes == []


def test_invalid_project_identity_cannot_write_repository_memory(monkeypatch, tmp_path):
    guard, writes = make_guard(monkeypatch, tmp_path, None)
    request = ConsistencyRequest(root=str(tmp_path), tenant="tenant-current")
    assert guard.record_finding(request, finding="claim") is None
    assert writes == []


def test_writer_uses_resolved_namespace_and_explicit_tenant(monkeypatch, tmp_path):
    guard, writes = make_guard(monkeypatch, tmp_path, "repository-current")
    request = ConsistencyRequest(root=str(tmp_path), tenant="tenant-current")
    record = guard.record_finding(request, finding="claim")
    assert len(writes) == 1
    assert record.scope_id == "repository-current"
    assert record.provenance["repository_id"] == "repository-current"
    assert record.provenance["tenant"] == "tenant-current"
