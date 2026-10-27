from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import GoalContract, TaskStore
from local_ai_hub.commands import CommandBroker
from local_ai_hub.operation_contracts import validate_operation_arguments


def test_session_repair_preserves_task_and_refuses_rebinding(tmp_path: Path):
    store = TaskStore(AgentStateStore(str(tmp_path / "state.db")))
    original = store.create(GoalContract(goal="repair"), ScopeContext(repository_id="repo"), repo_root=str(tmp_path))
    with pytest.raises(ValueError, match="owner"):
        store.repair_missing_session(original.task_id, session_id="session-1", repo_root=str(tmp_path), actor="other")
    with pytest.raises(ValueError, match="root"):
        store.repair_missing_session(original.task_id, session_id="session-1", repo_root=str(tmp_path / "other"), actor="agent")
    with pytest.raises(ValueError, match="session_id"):
        store.repair_missing_session(original.task_id, session_id="bad\x00id", repo_root=str(tmp_path), actor="agent")
    with pytest.raises(Exception, match="budget"):
        store.repair_missing_session(original.task_id, session_id="session-1", repo_root=str(tmp_path), actor="agent", response_budget_tokens=1)
    assert store.get(original.task_id).context.session_id == ""
    repaired = store.repair_missing_session(original.task_id, session_id="session-1", repo_root=str(tmp_path), actor="agent")
    assert repaired.task_id == original.task_id
    assert repaired.context.session_id == "session-1"
    assert repaired.contract == original.contract
    assert repaired.status == original.status
    assert store.get(original.task_id).context.session_id == "session-1"
    events = store.state_store.events(f"task:{original.task_id}")
    assert [(event.kind, event.payload.get("session_id")) for event in events if event.kind == "task.session_repaired"] == [("task.session_repaired", "session-1")]
    with pytest.raises(ValueError):
        store.repair_missing_session(original.task_id, session_id="session-2", repo_root=str(tmp_path), actor="agent")


def test_session_repair_broker_requires_write_authority(tmp_path: Path):
    store = TaskStore(AgentStateStore(str(tmp_path / "state.db")))
    task = store.create(GoalContract(goal="repair"), ScopeContext(repository_id="repo"), repo_root=str(tmp_path))
    broker = object.__new__(CommandBroker)
    broker.task_store = store
    with pytest.raises(PermissionError):
        broker.repair_task_session(task.task_id, root=str(tmp_path), session_id="session-1", reason="repair missing session", authorization_actor="api_token", authorization_permissions=frozenset({"read"}))
    assert store.get(task.task_id).context.session_id == ""
    repaired = broker.repair_task_session(task.task_id, root=str(tmp_path), session_id="session-1", reason="repair missing session", authorization_actor="local", authorization_permissions=frozenset())
    assert repaired.context.session_id == "session-1"


def test_session_repair_rejects_failed_tasks(tmp_path: Path):
    store = TaskStore(AgentStateStore(str(tmp_path / "state.db")))
    task = store.create(GoalContract(goal="repair"), ScopeContext(repository_id="repo"), repo_root=str(tmp_path))
    store.fail(task.task_id, actor="agent", reason="failed")
    with pytest.raises(ValueError, match="status"):
        store.repair_missing_session(task.task_id, session_id="session-1", repo_root=str(tmp_path), actor="agent")


def test_competing_repairs_commit_at_most_one_session(tmp_path: Path, monkeypatch):
    store = TaskStore(AgentStateStore(str(tmp_path / "state.db")))
    task = store.create(GoalContract(goal="repair"), ScopeContext(repository_id="repo"), repo_root=str(tmp_path))
    barrier = Barrier(2)
    commit = store._commit_update

    def synchronized(*args, **kwargs):
        barrier.wait(timeout=10)
        return commit(*args, **kwargs)

    monkeypatch.setattr(store, "_commit_update", synchronized)

    def repair(session):
        try:
            return store.repair_missing_session(task.task_id, session_id=session, repo_root=str(tmp_path), actor="agent")
        except Exception as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(repair, ["session-1", "session-2"]))
    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert store.get(task.task_id).context.session_id in {"session-1", "session-2"}
    assert sum(event.kind == "task.session_repaired" for event in store.state_store.events(f"task:{task.task_id}")) == 1


def test_session_repair_accepts_canonical_coordination_arguments(tmp_path: Path):
    error = validate_operation_arguments("local_ai_coord", "task_repair_session", {"root": str(tmp_path), "task_id": "task-1", "session_id": "session-1", "reason": "repair"})
    assert not error


def test_mcp_forwards_session_repair(monkeypatch, tmp_path: Path):
    from local_ai_hub import mcp_server
    calls = []
    monkeypatch.setattr(mcp_server.CLIENT, "coord", lambda **kwargs: calls.append(kwargs) or {"success": True})
    mcp_server.local_ai_coord(action="task_repair_session", root=str(tmp_path), task_id="task-1", session_id="session-1", reason="repair")
    assert calls[0]["action"] == "task_repair_session"
    assert calls[0]["session_id"] == "session-1"
    assert calls[0]["reason"] == "repair"


@pytest.mark.parametrize("permissions,expected", [(["read"], 403), (["write"], 200)])
def test_http_session_repair_uses_verified_authority(tmp_path: Path, monkeypatch, permissions, expected):
    from local_ai_hub import http_server

    root = tmp_path / "repository"
    root.mkdir()
    store = TaskStore(AgentStateStore(str(tmp_path / "state.db")))
    task = store.create(GoalContract(goal="repair"), ScopeContext(repository_id="repository"), repo_root=str(root))
    broker = object.__new__(CommandBroker)
    broker.task_store = store
    config = {"security": {"api_token": "owner-token-at-least-sixteen", "api_token_permissions": permissions, "allowed_roots": [str(root)]}}
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config=config, agent_tasks=store, commands=broker))
    monkeypatch.setattr(http_server, "_trusted_project_context", lambda _: SimpleNamespace(coordination_id="repository"))
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = "/api/agent-state/tasks"
    handler.command = "POST"
    handler.client_address = ("127.0.0.1", 0)
    handler.headers = {"X-LocalAI-Token": config["security"]["api_token"]}
    replies = []
    handler._send = lambda status, payload: replies.append((status, payload))
    handler._task_repair_session({"action": "repair_session", "root": str(root), "task_id": task.task_id, "session_id": "session-1", "reason": "repair"})
    assert replies[-1][0] == expected
    assert store.get(task.task_id).context.session_id == ("session-1" if expected == 200 else "")
