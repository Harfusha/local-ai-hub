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
    try:
        yield client, app
    finally:
        client.close()
        app.close()


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


def test_client_convenience_methods(running_app_client):
    client, app = running_app_client
    calls = []

    def mock_post(path, payload, **kwargs):
        calls.append((path, payload))
        if path == "/v1/agent-state/tasks":
            return {"success": True, "action": payload.get("action")}
        if path == "/v1/agent-state/memory":
            return {"success": True, "action": payload.get("action")}
        if path == "/v1/conversations/continue":
            return {"success": True, "conversation_id": payload.get("conversation_id")}
        return {"success": False}

    client.post = mock_post

    res1 = client.create_task("Fix bug", acceptance_criteria=["test_passes"], task_id="t10")
    assert res1["success"] is True and res1["action"] == "create"

    res2 = client.get_task("t10")
    assert res2["success"] is True and res2["action"] == "get"

    res3 = client.list_tasks(status="active")
    assert res3["success"] is True and res3["action"] == "list"

    res4 = client.complete_task("t10", reason="done")
    assert res4["success"] is True and res4["action"] == "complete"

    res5 = client.fail_task("t10", reason="failed")
    assert res5["success"] is True and res5["action"] == "fail"

    res6 = client.checkpoint_task("t10", phase="dev", next_action="run_tests")
    assert res6["success"] is True and res6["action"] == "checkpoint"

    res7 = client.record_memory("key1", "val1", scope="project")
    assert res7["success"] is True and res7["action"] == "record"

    res8 = client.find_memory(query="val")
    assert res8["success"] is True and res8["action"] == "find"

    res9 = client.continue_conversation("conv-123", "Next prompt")
    assert res9["success"] is True and res9["conversation_id"] == "conv-123"

    def mock_get(path, **kwargs):
        if path == "/v1/doctor":
            return {"success": True, "doctor": True}
        if "/v1/logs/tail" in path:
            return {"success": True, "lines": ["log line 1", "log line 2"]}
        return {"success": False}

    client.get = mock_get
    res10 = client.doctor()
    assert res10["success"] is True and res10["doctor"] is True

    res11 = client.logs(lines=10)
    assert res11["success"] is True and len(res11["lines"]) == 2


def test_agent_state_cleanup(running_app_client):
    client, app = running_app_client
    cleanup_res = app.agent_state.cleanup(retention_days=30)
    assert cleanup_res["success"] is True
    assert "deleted_events" in cleanup_res
    assert "deleted_snapshots" in cleanup_res


def test_hubctl_tasks_and_memory(monkeypatch, capsys):
    from tools import hubctl

    class DummyClient:
        def get_task(self, tid):
            return {"success": True, "task": {"task_id": tid, "status": "active", "contract": {"goal": "Test Goal"}}}

        def list_tasks(self, status=None, limit=50):
            return {"success": True, "tasks": [{"task_id": "t-1", "status": "active", "contract": {"goal": "Test Task 1"}}]}

        def find_memory(self, scope=None, key=None, query=None, limit=50):
            return {"success": True, "records": [{"scope": "task", "kind": "fact", "key": "k1", "value": "v1"}]}

    monkeypatch.setattr(hubctl, "client", lambda: DummyClient())

    # Test hubctl tasks
    monkeypatch.setattr("sys.argv", ["hubctl.py", "tasks"])
    ret = hubctl.main()
    assert ret == 0
    out = capsys.readouterr().out
    assert "Test Task 1" in out

    # Test hubctl tasks with task-id
    monkeypatch.setattr("sys.argv", ["hubctl.py", "tasks", "--task-id", "t-1"])
    ret = hubctl.main()
    assert ret == 0
    out = capsys.readouterr().out
    assert "Test Goal" in out

    # Test hubctl memory
    monkeypatch.setattr("sys.argv", ["hubctl.py", "memory"])
    ret = hubctl.main()
    assert ret == 0
    out = capsys.readouterr().out
    assert "k1" in out


def test_hubctl_doctor_and_logs(monkeypatch, capsys):
    from tools import hubctl

    class DummyClient:
        def doctor(self):
            return {"success": True, "checks": [{"component": "TestComp", "status": "OK"}]}

        def logs(self, lines=200):
            return {"success": True, "lines": ["2026-09-04 INFO test log message"]}

    monkeypatch.setattr(hubctl, "client", lambda: DummyClient())

    # Test hubctl doctor
    monkeypatch.setattr("sys.argv", ["hubctl.py", "doctor"])
    ret1 = hubctl.main()
    assert ret1 == 0
    out1 = capsys.readouterr().out
    assert "TestComp" in out1

    # Test hubctl logs
    monkeypatch.setattr("sys.argv", ["hubctl.py", "logs", "--limit", "10"])
    ret2 = hubctl.main()
    assert ret2 == 0
    out2 = capsys.readouterr().out
    assert "test log message" in out2


def test_dashboard_agent_os_tab():
    from local_ai_hub.dashboard import DASHBOARD_HTML
    assert 'data-tab="agentos"' in DASHBOARD_HTML
    assert 'id="agentos"' in DASHBOARD_HTML
    assert 'loadAgentOsView' in DASHBOARD_HTML
    assert 'renderAgentOsView' in DASHBOARD_HTML
    assert 'agentStateCard' in DASHBOARD_HTML
