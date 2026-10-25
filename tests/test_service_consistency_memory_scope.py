from types import SimpleNamespace

import pytest

from local_ai_hub.agent_consistency import AgentConsistencyGuard, ConsistencyRequest
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import AgentScope
from local_ai_hub.agent_memory import MemoryStatus, MemoryStore
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.services import LocalAIServices


def _services(tmp_path, monkeypatch, store, namespace="repository-current"):
    from local_ai_hub import project_config

    root = tmp_path / "repository"
    root.mkdir()
    config = {"server": {"state_dir": str(tmp_path / "state")}}
    monkeypatch.setattr(
        project_config, "resolve_project_context",
        lambda *_args, **_kwargs: SimpleNamespace(coordination_id=namespace),
    )
    guard = AgentConsistencyGuard(RepositoryTools(config), memory_store=store)
    service = object.__new__(LocalAIServices)
    service.config = config
    service.consistency_guard = guard
    request = ConsistencyRequest(root=str(root), task_id="task-current", phase="implementation")
    return service, request


def test_service_decision_uses_canonical_repository_scope_and_confirmed_status(tmp_path, monkeypatch):
    memory = MemoryStore(AgentStateStore(tmp_path / "memory.sqlite3"))
    service, request = _services(tmp_path, monkeypatch, memory)

    assert service._guard_decision(request, "revision-current", reason="approved change", approval=True) == (True, True)
    records = memory.find(
        scope=AgentScope.REPOSITORY, scope_id="repository-current",
        repository_id="repository-current", semantic=False,
    )
    assert len(records) == 1
    record = records[0]
    assert record.status is MemoryStatus.CONFIRMED
    assert record.provenance["repository_id"] == "repository-current"
    assert record.provenance["related_task"] == request.task_id
    assert record.repository_revision == "revision-current"
    assert service._guard_existing_approval(request) is True


@pytest.mark.parametrize("namespace", [None, "", " padded", "bad\x00identity"])
def test_service_decision_never_falls_back_to_unbound_repository_scope(tmp_path, monkeypatch, namespace):
    writes = []
    store = SimpleNamespace(record=lambda record, **options: writes.append((record, options)) or record)
    service, request = _services(tmp_path, monkeypatch, store, namespace)

    assert service._guard_decision(request, "revision-current", approval=True) == (True, False)
    assert writes == []


def test_approval_lookup_type_error_does_not_retry_without_root(tmp_path, monkeypatch, caplog):
    calls = []
    foreign = SimpleNamespace(
        kind="decision", value={"approved": True},
        provenance={"related_task": "task-current", "repository_id": "foreign"},
    )

    def find(**options):
        calls.append(options)
        if "root" in options:
            raise TypeError("private storage payload must not enter logs")
        return [foreign]

    service, request = _services(tmp_path, monkeypatch, SimpleNamespace(find=find))

    assert service._guard_existing_approval(request) is False
    assert len(calls) == 1
    assert calls[0]["scope_id"] == "repository-current"
    assert calls[0]["repository_id"] == "repository-current"
    assert "TypeError" in caplog.text
    assert "private storage payload" not in caplog.text


def test_decision_type_error_does_not_retry_without_actor_and_idempotency(tmp_path, monkeypatch):
    calls = []

    def record(value, **options):
        calls.append((value, options))
        if options:
            raise TypeError("internal failure after persistence boundary")
        return value

    service, request = _services(tmp_path, monkeypatch, SimpleNamespace(record=record))

    assert service._guard_decision(request, "revision-current", approval=True) == (True, False)
    assert len(calls) == 1
    assert calls[0][1]["actor"] == "consistency_guard"
    assert calls[0][1]["idempotency_key"]

