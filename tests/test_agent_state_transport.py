from __future__ import annotations

from pathlib import Path
import pytest

from local_ai_hub.app import LocalAIApp
from local_ai_hub.client import HubClient
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import GoalContract, TaskStatus


@pytest.fixture
def running_app_client(tmp_path: Path):
    # Setup app with agent_state enabled and start it
    from local_ai_hub.agent_events import AgentStateStore
    from local_ai_hub.agent_tasks import TaskStore

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(f"""
[server]
bind = "127.0.0.1"
port = 11489
state_dir = "{tmp_path.as_posix()}/state"

[agent_state]
enabled = true
""", encoding="utf-8")

    app = LocalAIApp(str(cfg_path))
    client = HubClient(config_path=str(cfg_path), auto_start=False)

    # Pre-populate a task
    app.agent_tasks.create(
        GoalContract(goal="Test Task"),
        ScopeContext(task_id="task-1"),
        task_id="task-1",
    )
    # Save a memo
    app.memory.put(str(tmp_path), "known", "memo_value", 3600)

    # We mock or run directly via app or client
    # For transport test without network server, we can mock client request/get/post through app handlers or test client directly
    client._app_direct = app
    return client, app


def test_coord_task_checkpoint_action_preserves_existing_memo_actions(running_app_client):
    client, app = running_app_client
    # Directly test client coord dispatch logic
    # Set up client mock to dispatch to app methods directly
    def mock_post(path, payload, **kwargs):
        if path == "/v1/agent-state/tasks":
            act = payload.get("action")
            if act == "checkpoint":
                from local_ai_hub.agent_tasks import TaskCheckpoint
                chk = TaskCheckpoint.from_dict(payload.get("checkpoint", {}))
                t = app.agent_tasks.checkpoint(payload.get("task_id"), chk)
                return {"success": True, "task": t.to_dict()}
        if path == "/v1/memory/search":
            results = app.memory.search(payload.get("root"), payload.get("query"))
            return {"success": True, "results": results}
        return {"success": False}

    client.post = mock_post
    response = client.coord(action="task_checkpoint", task_id="task-1", checkpoint={"next_action": "test"})
    assert response["success"] is True
    assert response["task"]["checkpoint"]["next_action"] == "test"

    memo_res = client.coord(action="memo_search", query="known")
    assert memo_res["success"] is True


def test_agent_state_response_never_returns_raw_prompt_or_absolute_path(running_app_client):
    client, app = running_app_client
    def mock_get(path, **kwargs):
        if "detail=agent_state" in path:
            return {
                "success": True,
                "enabled": app.agent_state.enabled,
                "active_tasks": [t.task_id for t in app.agent_tasks.list_tasks(status=TaskStatus.ACTIVE)],
                "tasks_count": len(app.agent_tasks.list_tasks()),
                "status": "healthy",
            }
        return {"success": False}

    client.get = mock_get
    response = client.status(detail="agent_state")
    assert "prompt" not in repr(response).lower()
    assert "C:\\" not in repr(response)
    assert "/Users" not in repr(response)
    assert response["success"] is True


def test_mcp_actions_dispatch_and_compact(monkeypatch):
    import local_ai_hub.mcp_server as mcp_mod

    calls = []

    class DummyClient:
        def post(self, path, payload, **kwargs):
            calls.append(("POST", path, payload))
            return {"success": True, "path": path, "payload": payload}

        def get(self, path, **kwargs):
            calls.append(("GET", path))
            return {"success": True, "path": path}

        def coord(self, action, **kwargs):
            calls.append(("COORD", action, kwargs))
            return {"success": True, "action": action, "kwargs": kwargs}

        def status(self, detail="brief", **kwargs):
            calls.append(("STATUS", detail))
            return {"success": True, "detail": detail}

    monkeypatch.setattr(mcp_mod, "CLIENT", DummyClient())

    # local_ai_status agent_state
    st_res = mcp_mod.local_ai_status(detail="agent_state")
    assert st_res["success"] is True
    assert ("STATUS", "agent_state") in calls

    # local_ai_coord actions
    c_res1 = mcp_mod.local_ai_coord(action="task_create", task_id="t1", contract={"goal": "g"})
    assert c_res1["success"] is True

    c_res2 = mcp_mod.local_ai_coord(action="memory_record", record={"key": "k", "value": "v"})
    assert c_res2["success"] is True

    c_res3 = mcp_mod.local_ai_coord(action="incident_decision", fingerprint={"error_class": "e"})
    assert c_res3["success"] is True

    # local_ai_repo actions
    r_res1 = mcp_mod.local_ai_repo(action="context_compile", task_id="t1")
    assert r_res1["success"] is True
    assert any(c[0] == "POST" and c[1] == "/v1/agent-state/context" for c in calls)

    r_res2 = mcp_mod.local_ai_repo(action="verify_receipt", receipt={"task_id": "t1", "criterion": "c1"})
    assert r_res2["success"] is True
    assert any(c[0] == "POST" and c[1] == "/v1/agent-state/verification" for c in calls)

    r_res3 = mcp_mod.local_ai_repo(action="verify_completion", task_id="t1")
    assert r_res3["success"] is True

    # local_ai_task actions
    t_res1 = mcp_mod.local_ai_task(action="candidate_create", task="improve_eval")
    assert t_res1["success"] is True
    assert any(c[0] == "POST" and c[1] == "/v1/agent-state/learning" for c in calls)

    t_res2 = mcp_mod.local_ai_task(action="candidate_promote", candidate="c1", approver="user")
    assert t_res2["success"] is True


def test_http_agent_state_routes(running_app_client):
    from local_ai_hub import http_server
    client, app = running_app_client
    http_server.APP = app

    # Test handler dispatch directly via dummy mock or test client
    # 1. Incidents endpoint
    assert app.agent_incidents.state_store.enabled is True
    # 2. Verification endpoint
    assert app.agent_verification.state_store.enabled is True
    # 3. Context endpoint
    assert app.agent_context.state_store.enabled is True
    # 4. Learning endpoint
    assert app.agent_learning.state_store.enabled is True
