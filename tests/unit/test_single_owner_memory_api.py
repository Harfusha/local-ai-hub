"""Memory reads and mutations preserve declared scopes without tenancy."""

import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import AgentScope
from local_ai_hub.agent_memory import MemoryKind, MemoryRecord, MemoryStore
from local_ai_hub import http_server


@pytest.fixture
def store(tmp_path):
    return MemoryStore(AgentStateStore(tmp_path / "agent-state.sqlite3"))


@pytest.mark.parametrize("name,args,kwargs", [
    ("get", ("record-one",), {}),
    ("find", (), {}),
    ("delete", ("record-one",), {"scope": AgentScope.GLOBAL}),
    ("promote", ("record-one", AgentScope.GLOBAL), {"approver": "user"}),
    ("quarantine", ("record-one", "review"), {"actor": "agent"}),
    ("find_for_context", (), {}),
    ("diagnostic_summary", (), {}),
    ("task_retrieval_scope", ("goal",), {"root": "", "task_id": "task-one"}),
])
@pytest.mark.parametrize("value", [None, "", False, "former-owner"])
def test_memory_api_rejects_retired_argument_before_state_access(name, args, kwargs, value):
    instance = MemoryStore.__new__(MemoryStore)
    with pytest.raises(TypeError, match="tenant"):
        getattr(instance, name)(*args, **kwargs, tenant=value)


def test_repository_memory_requires_exact_coordination_id(store, tmp_path):
    root = str(tmp_path)
    record = store.record(MemoryRecord.create(
        MemoryKind.FACT, AgentScope.REPOSITORY, "repo-fact", "keep",
        scope_id="repository-one", source="user",
        provenance={"root": root, "repository_id": "repository-one"},
    ), actor="user")
    assert store.get(record.record_id, scope=AgentScope.REPOSITORY, root=root, repository_id="other") is None
    assert store.get(record.record_id, scope=AgentScope.REPOSITORY, root=root) is None
    assert store.get(record.record_id, scope=AgentScope.REPOSITORY, root=root, repository_id="repository-one") is not None
    assert not store.delete(record.record_id, scope=AgentScope.REPOSITORY, root=root, repository_id="other")
    assert store.delete(record.record_id, scope=AgentScope.REPOSITORY, root=root, repository_id="repository-one")


def test_same_task_id_does_not_cross_repository_roots(store, tmp_path):
    paths = [tmp_path / "repo-one", tmp_path / "repo-two"]
    for path in paths:
        path.mkdir()
    roots = [str(path) for path in paths]
    records = [store.record(MemoryRecord.create(
        MemoryKind.FACT, AgentScope.TASK, "task-fact", root,
        scope_id="task-one", source="user", provenance={"root": root, "task_id": "task-one"},
    ), actor="user") for root in roots]
    assert store.find(scope=AgentScope.TASK, task_id="task-one", semantic=False) == []
    assert not store.delete(records[0].record_id, scope=AgentScope.TASK, task_id="task-one")
    assert not store.delete(records[0].record_id, scope=AgentScope.TASK, root=roots[1], task_id="task-one")
    found = store.find(scope=AgentScope.TASK, root=roots[0], task_id="task-one", semantic=False)
    assert [record.record_id for record in found] == [records[0].record_id]


def test_owner_global_memory_has_no_transport_partition(store):
    record = store.record(MemoryRecord.create(
        MemoryKind.FACT, AgentScope.GLOBAL, "global-fact", "keep", source="user",
    ), actor="user")
    assert store.get(record.record_id) is not None
    assert store.find(scope=AgentScope.GLOBAL, semantic=False)
    assert store.delete(record.record_id, scope=AgentScope.GLOBAL)


def test_http_scope_resolver_does_not_invent_a_session():
    assert http_server._resolve_memory_scope(None) == (None, None, False)
    assert http_server._resolve_memory_scope(AgentScope.GLOBAL) == (AgentScope.GLOBAL, None, False)
    assert http_server._resolve_memory_scope(AgentScope.SESSION)[2] is True
    assert http_server._resolve_memory_scope(AgentScope.SESSION, session_id="chat-one") == (AgentScope.SESSION, "chat-one", False)
    with pytest.raises(TypeError, match="tenant"):
        http_server._resolve_memory_scope(None, tenant=None)


def test_repository_scope_keeps_task_attribution_without_becoming_task_scope():
    scope, _, ambiguous = http_server._resolve_memory_scope(
        AgentScope.REPOSITORY, repository_id="repository-one", task_id="task-one", session_id="chat-one",
    )
    assert scope is AgentScope.REPOSITORY
    assert ambiguous is False


def test_repository_provenance_requires_server_coordination_identity(tmp_path):
    from types import SimpleNamespace

    with pytest.raises(ValueError, match="coordination identity"):
        http_server._bind_repository_memory_provenance({}, root=str(tmp_path), project_context=None)
    result = http_server._bind_repository_memory_provenance(
        {"repository_id": "untrusted"}, root=str(tmp_path),
        project_context=SimpleNamespace(root=tmp_path, coordination_id="repository-one"),
    )
    assert result == {"root": str(tmp_path.resolve()), "repository_id": "repository-one"}
