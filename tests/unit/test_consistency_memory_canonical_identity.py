from types import SimpleNamespace

import pytest

import local_ai_hub.agent_consistency as agent_consistency
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


def test_missing_coordination_identity_cannot_write_repository_memory(monkeypatch, tmp_path):
    guard, writes = make_guard(monkeypatch, tmp_path, None)
    assert guard.record_finding(ConsistencyRequest(root=str(tmp_path)), finding="claim") is None
    assert writes == []


@pytest.mark.parametrize("retired", ["tenant", "tenant_id", "tenant_key", "tenant_scope"])
@pytest.mark.parametrize("value", [None, "", False])
def test_retired_tenant_fields_are_rejected_at_request_boundary(tmp_path, retired, value):
    with pytest.raises(TypeError):
        ConsistencyRequest(root=str(tmp_path), **{retired: value})


def test_invalid_project_identity_cannot_write_repository_memory(monkeypatch, tmp_path):
    guard, writes = make_guard(monkeypatch, tmp_path, None)
    request = ConsistencyRequest(root=str(tmp_path), task_id="task-current", session_id="session-current")
    assert guard.record_finding(request, finding="claim") is None
    assert writes == []


def test_writer_uses_resolved_repository_identity_and_preserves_task_context(monkeypatch, tmp_path):
    guard, writes = make_guard(monkeypatch, tmp_path, "repository-current")
    request = ConsistencyRequest(
        root=str(tmp_path), task_id="task-current", session_id="session-current"
    )
    record = guard.record_finding(request, finding="claim")
    assert len(writes) == 1
    assert record.scope_id == "repository-current"
    assert record.provenance["repository_id"] == "repository-current"
    assert request.to_dict()["task_id"] == "task-current"
    assert request.to_dict()["session_id"] == "session-current"
    assert "tenant" not in record.provenance
