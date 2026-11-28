from types import SimpleNamespace
import json
import logging

import pytest

from local_ai_hub.agent_consistency import AgentConsistencyGuard, ConsistencyRequest
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import AgentScope
from local_ai_hub.agent_memory import MemoryStatus, MemoryStore
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.services import LocalAIServices


@pytest.mark.parametrize("authorization", [
    "Authorization: Bearer private-credential",
    "Authorization: Basic private-credential",
    'Authorization: Digest username="private-credential", response="private-response"',
    pytest.param('Authorization: Digest username="private-credential"\r\n response="private-response"', id="folded-digest"),
])
def test_canonical_decision_redacts_complete_authorization(tmp_path, monkeypatch, authorization):
    records = []
    store = SimpleNamespace(record=lambda record, **_kwargs: records.append(record) or record)
    service, request = _services(tmp_path, monkeypatch, store)
    saved = service.consistency_guard.record_decision(
        request, decision="override", reason=authorization, approved=True,
        repository_revision="revision-current",
    )
    assert saved is not None
    reason = records[0].value["reason"]
    assert "private-credential" not in json.dumps(records[0].value)
    assert "private-response" not in reason
    if "Bearer" in authorization:
        assert "Bearer [REDACTED]" in reason
    from local_ai_hub.agent_consistency import _redact_memory_text
    assert _redact_memory_text(reason) == reason


@pytest.mark.parametrize("error,level", [
    (OSError, logging.WARNING), (TypeError, logging.WARNING),
    (ZeroDivisionError, logging.ERROR),
])
def test_canonical_persistence_failure_logs_type_without_payload(
    tmp_path, monkeypatch, caplog, error, level,
):
    writes = []

    def fail_record(record, **kwargs):
        writes.append((record, kwargs))
        raise error("private-store-credential")

    service, request = _services(tmp_path, monkeypatch, SimpleNamespace(record=fail_record))
    with caplog.at_level(logging.WARNING):
        assert service._guard_decision(request, "revision-current", approval=True) == (True, False)
    assert len(writes) == 1
    assert any(record.levelno == level and error.__name__ in record.getMessage() for record in caplog.records)
    assert "private-store-credential" not in caplog.text


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
    request = ConsistencyRequest(root=str(root),  task_id="task-current", phase="implementation")
    return service, request


def test_service_decision_is_task_scoped_and_never_reuses_repository_approval(tmp_path, monkeypatch):
    memory = MemoryStore(AgentStateStore(tmp_path / "memory.sqlite3"))
    service, request = _services(tmp_path, monkeypatch, memory)

    assert service._guard_decision(request, "revision-current", reason="approved change", approval=True) == (True, True)
    records = memory.find(
        root=request.root, scope=AgentScope.TASK, scope_id=request.task_id,
        task_id=request.task_id, semantic=False,
    )
    assert len(records) == 1
    record = records[0]
    assert record.status is MemoryStatus.CONFIRMED
    assert record.scope is AgentScope.TASK
    assert record.provenance["task_id"] == request.task_id
    assert record.repository_revision == "revision-current"
    assert not hasattr(service, "_guard_existing_approval")


def test_service_decision_does_not_require_project_identity(tmp_path, monkeypatch):
    writes = []
    store = SimpleNamespace(record=lambda record, **options: writes.append((record, options)) or record)
    service, request = _services(tmp_path, monkeypatch, store, namespace="")

    assert service._guard_decision(request, "revision-current", approval=True) == (True, True)
    assert writes[0][0].scope is AgentScope.TASK
    assert writes[0][0].scope_id == request.task_id


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

