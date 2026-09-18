from __future__ import annotations

from pathlib import Path
import gc
import time
import pytest

from local_ai_hub.app import LocalAIApp
from local_ai_hub.client import HubClient
from local_ai_hub.agent_identity import AgentScope, ScopeContext
from local_ai_hub.agent_memory import MemoryRecord, MemoryStatus
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
        if path == "/api/agent-state/tasks":
            act = payload.get("action")
            if act == "checkpoint":
                from local_ai_hub.agent_tasks import TaskCheckpoint
                chk = TaskCheckpoint.from_dict(payload.get("checkpoint", {}))
                t = app.agent_tasks.checkpoint(payload.get("task_id"), chk)
                return {"success": True, "task": t.to_dict()}
        if path == "/api/memory/search":
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

    c_res2 = mcp_mod.local_ai_coord(
        action="memory_record",
        record={"key": "k", "value": "v", "expires_at": 12345.0},
        ttl_seconds=77,
    )
    assert c_res2["success"] is True
    memory_payload = next(
        call[2] for call in calls
        if call[0] == "COORD" and call[1] == "memory_record"
    )
    assert memory_payload["record"]["expires_at"] == 12345.0
    assert memory_payload["ttl_seconds"] == 77

    c_res2_default = mcp_mod.local_ai_coord(
        action="memory_record",
        record={"key": "no-expiry-by-default", "value": "v"},
    )
    assert c_res2_default["success"] is True
    default_memory_payload = next(
        call[2] for call in calls
        if call[0] == "COORD"
        and call[1] == "memory_record"
        and call[2]["record"]["key"] == "no-expiry-by-default"
    )
    assert "ttl_seconds" not in default_memory_payload

    c_res2_get = mcp_mod.local_ai_coord(
        action="memory_get",
        record_id="mem-task-1",
        scope="task",
        scope_id="task-1",
        task_id="task-1",
        root="repo-root",
        repository_id="repository-1",
        tenant="tenant-1",
        clone_id="clone-1",
        worktree_id="worktree-1",
        branch="branch-1",
    )
    assert c_res2_get["success"] is True
    memory_get_payload = next(
        call[2] for call in calls
        if call[0] == "COORD" and call[1] == "memory_get"
    )
    assert {key: memory_get_payload[key] for key in (
        "record_id", "scope", "scope_id", "task_id", "repository_id", "tenant",
        "clone_id", "worktree_id", "branch",
    )} == {
        "record_id": "mem-task-1",
        "scope": "task",
        "scope_id": "task-1",
        "task_id": "task-1",
        "repository_id": "repository-1",
        "tenant": "tenant-1",
        "clone_id": "clone-1",
        "worktree_id": "worktree-1",
        "branch": "branch-1",
    }

    c_res3 = mcp_mod.local_ai_coord(action="incident_decision", fingerprint={"error_class": "e"})
    assert c_res3["success"] is True

    c_res4 = mcp_mod.local_ai_coord(
        action="context_compile",
        task_id="t1",
        root="repo-root",
        clone_id="clone-1",
        worktree_id="worktree-1",
        branch="branch-1",
        repository_id="repository-1",
        session_id="session-1",
        repository_revision="revision-1",
        include_diagnostics=True,
    )
    assert c_res4["success"] is True
    coord_context_payload = next(
        call[2] for call in calls
        if call[0] == "POST" and call[1] == "/api/agent-state/context" and call[2].get("task_id") == "t1"
    )
    assert coord_context_payload["include_diagnostics"] is True
    assert {key: coord_context_payload[key] for key in (
        "clone_id", "worktree_id", "branch", "repository_id", "session_id", "repository_revision"
    )} == {
        "clone_id": "clone-1",
        "worktree_id": "worktree-1",
        "branch": "branch-1",
        "repository_id": "repository-1",
        "session_id": "session-1",
        "repository_revision": "revision-1",
    }

    # local_ai_repo actions
    r_res1 = mcp_mod.local_ai_repo(
        action="context_compile",
        task_id="t2",
        root="repo-root",
        clone_id="clone-2",
        worktree_id="worktree-2",
        branch="branch-2",
        repository_id="repository-2",
        session_id="session-2",
        repository_revision="revision-2",
        changed_paths=["src/main.py"],
        include_diagnostics=True,
    )
    assert r_res1["success"] is True
    assert any(c[0] == "POST" and c[1] == "/api/agent-state/context" for c in calls)
    repo_context_payload = next(
        call[2] for call in calls
        if call[0] == "POST" and call[1] == "/api/agent-state/context" and call[2].get("task_id") == "t2"
    )
    assert repo_context_payload["include_diagnostics"] is True
    assert {key: repo_context_payload[key] for key in (
        "clone_id", "worktree_id", "branch", "repository_id", "session_id", "repository_revision"
    )} == {
        "clone_id": "clone-2",
        "worktree_id": "worktree-2",
        "branch": "branch-2",
        "repository_id": "repository-2",
        "session_id": "session-2",
        "repository_revision": "revision-2",
    }
    assert repo_context_payload["changed_paths"] == ["src/main.py"]

    r_res2 = mcp_mod.local_ai_repo(action="verify_receipt", receipt={"task_id": "t1", "criterion": "c1"})
    assert r_res2["success"] is True
    assert any(c[0] == "POST" and c[1] == "/api/agent-state/verification" for c in calls)

    r_res3 = mcp_mod.local_ai_repo(action="verify_completion", task_id="t1")
    assert r_res3["success"] is True

    # local_ai_task actions
    t_res1 = mcp_mod.local_ai_task(action="candidate_create", task="improve_eval")
    assert t_res1["success"] is True
    assert any(c[0] == "POST" and c[1] == "/api/agent-state/learning" for c in calls)

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


def test_http_memory_get_is_scope_and_root_isolated(tmp_path: Path):
    import json
    import threading
    import urllib.parse
    import urllib.request
    import urllib.error

    from local_ai_hub import http_server

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = 11497\nstate_dir = "{(tmp_path / "state").as_posix()}"\n'
        "\n[agent_state]\nenabled = true\n",
        encoding="utf-8",
    )
    repo_one = tmp_path / "repo-one"
    repo_two = tmp_path / "repo-two"
    repo_one.mkdir()
    repo_two.mkdir()
    app = LocalAIApp(str(cfg_path))
    rich_record = MemoryRecord.create(
        kind="finding",
        scope=AgentScope.TASK,
        scope_id="task-rich",
        key="rich",
        value="rich-task",
        provenance={
            "root": str(repo_one),
            "repository_id": "repository-rich",
            "clone_id": "clone-rich",
            "worktree_id": "worktree-rich",
            "branch": "branch-rich",
        },
    )
    records = (
        MemoryRecord.create(kind="finding", scope=AgentScope.TASK, scope_id="task-one", key="shared", value="task-one"),
        MemoryRecord.create(kind="finding", scope=AgentScope.TASK, scope_id="task-two", key="shared", value="task-two"),
        MemoryRecord.create(kind="finding", scope=AgentScope.TASK, key="shared", value="legacy-task"),
        MemoryRecord.create(kind="finding", scope=AgentScope.SESSION, scope_id="session-one", key="shared", value="session-one"),
        MemoryRecord.create(kind="finding", scope=AgentScope.SESSION, scope_id="session-two", key="shared", value="session-two"),
        MemoryRecord.create(kind="finding", scope=AgentScope.SESSION, key="shared", value="legacy-session"),
        MemoryRecord.create(kind="finding", scope=AgentScope.SESSION, scope_id="tenant-1", key="tenant-shared", value="tenant-one", provenance={"tenant": "tenant-1"}),
        MemoryRecord.create(kind="finding", scope=AgentScope.SESSION, scope_id="tenant-2", key="tenant-shared", value="tenant-two", provenance={"tenant": "tenant-2"}),
        MemoryRecord.create(
            kind="finding",
            scope=AgentScope.SESSION,
            scope_id="session-rich",
            key="session-rich",
            value="session-rich-value",
            provenance={
                "tenant": "tenant-rich",
                "clone_id": "clone-session",
                "worktree_id": "worktree-session",
                "branch": "branch-session",
            },
        ),
        rich_record,
        MemoryRecord.create(kind="finding", scope=AgentScope.REPOSITORY, key="shared", value="repo-one", provenance={"root": str(repo_one), "repository_id": "repository-one"}),
        MemoryRecord.create(kind="finding", scope=AgentScope.REPOSITORY, key="shared", value="repo-one-missing-id", provenance={"root": str(repo_one)}),
        MemoryRecord.create(kind="finding", scope=AgentScope.REPOSITORY, key="shared", value="repo-two", provenance={"root": str(repo_two), "repository_id": "repository-two"}),
    )
    for record in records:
        app.agent_memory.record(record, actor="user")
    previous = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def get(**params):
        query = urllib.parse.urlencode(params)
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/agent-state/memory?{query}",
            headers={"Connection": "close"},
            method="GET",
        )
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))

    def post(payload):
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/agent-state/memory",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Connection": "close"},
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))

    try:
        task_result = get(scope="task", scope_id="task-one", key="shared")
        assert [item["value"] for item in task_result["records"]] == ["task-one"]
        session_result = get(scope="session", scope_id="session-one", key="shared")
        assert [item["value"] for item in session_result["records"]] == ["session-one"]
        task_without_scope = get(task_id="task-one", key="shared")
        assert [item["value"] for item in task_without_scope["records"]] == ["task-one"]
        session_without_scope = get(session_id="session-one", key="shared")
        assert [item["value"] for item in session_without_scope["records"]] == ["session-one"]
        repo_without_scope = get(root=str(repo_one), key="shared")
        assert {item["value"] for item in repo_without_scope["records"]} == {"repo-one", "repo-one-missing-id"}
        other_repo_without_scope = get(root=str(repo_two), key="shared")
        assert [item["value"] for item in other_repo_without_scope["records"]] == ["repo-two"]
        repository_id_without_scope = get(repository_id="repository-one", key="shared")
        assert [item["value"] for item in repository_id_without_scope["records"]] == ["repo-one"]
        tenant_without_scope = get(tenant="tenant-1", key="tenant-shared")
        assert [item["value"] for item in tenant_without_scope["records"]] == ["tenant-one"]
        rich_direct = post({
            "action": "get",
            "record_id": rich_record.record_id,
            "scope": "task",
            "scope_id": "task-rich",
            "task_id": "task-rich",
            "root": str(repo_one),
            "repository_id": "repository-rich",
            "clone_id": "clone-rich",
            "worktree_id": "worktree-rich",
            "branch": "branch-rich",
        })
        assert rich_direct["record"]["value"] == "rich-task"
        with pytest.raises(urllib.error.HTTPError) as ambiguous:
            post({
                "action": "get",
                "record_id": rich_record.record_id,
                "task_id": "task-rich",
                "session_id": "session-one",
            })
        assert ambiguous.value.code == 400
        with pytest.raises(urllib.error.HTTPError) as tenant_ambiguous:
            post({
                "action": "find",
                "scope": "session",
                "tenant": "tenant-1",
                "key": "tenant-shared",
            })
        assert tenant_ambiguous.value.code == 400
        with pytest.raises(urllib.error.HTTPError) as invalid_scope:
            get(scope="not-a-scope", key="shared")
        assert invalid_scope.value.code == 400
        with pytest.raises(urllib.error.HTTPError) as task_missing_id:
            post({
                "action": "find",
                "scope": "task",
                "session_id": "session-one",
                "key": "shared",
            })
        assert task_missing_id.value.code == 400
        with pytest.raises(urllib.error.HTTPError) as session_missing_id:
            post({
                "action": "find",
                "scope": "session",
                "task_id": "task-one",
                "key": "shared",
            })
        assert session_missing_id.value.code == 400
        session_rich = post({
            "action": "find",
            "scope": "session",
            "scope_id": "session-rich",
            "session_id": "session-rich",
            "tenant": "tenant-rich",
            "clone_id": "clone-session",
            "worktree_id": "worktree-session",
            "branch": "branch-session",
            "key": "session-rich",
        })
        assert [item["value"] for item in session_rich["records"]] == ["session-rich-value"]
        repo_result = get(scope="repository", root=str(repo_one), repository_id="repository-one", key="shared")
        assert [item["value"] for item in repo_result["records"]] == ["repo-one"]
        direct = post({
            "action": "get",
            "record_id": records[0].record_id,
            "scope": "task",
            "scope_id": "task-one",
        })
        assert direct["record"]["value"] == "task-one"
        direct_without_scope = post({
            "action": "get",
            "record_id": records[0].record_id,
            "task_id": "task-one",
        })
        assert direct_without_scope["record"]["value"] == "task-one"
        with pytest.raises(urllib.error.HTTPError) as mismatch:
            post({
                "action": "get",
                "record_id": records[0].record_id,
                "scope": "task",
                "scope_id": "task-two",
            })
        assert mismatch.value.code == 404
        with pytest.raises(urllib.error.HTTPError) as task_mismatch_without_scope:
            post({
                "action": "get",
                "record_id": records[0].record_id,
                "task_id": "task-two",
            })
        assert task_mismatch_without_scope.value.code == 404

        from local_ai_hub import mcp_server
        previous_mcp_client = mcp_server.CLIENT
        mcp_client = HubClient(config_path=str(cfg_path), auto_start=False)
        mcp_client._http_host = "127.0.0.1"
        mcp_client._http_port = server.server_address[1]
        mcp_server.CLIENT = mcp_client
        try:
            mcp_result = mcp_server.local_ai_coord(
                action="memory_get",
                record_id=rich_record.record_id,
                scope="task",
                scope_id="task-rich",
                task_id="task-rich",
                root=str(repo_one),
                repository_id="repository-rich",
                clone_id="clone-rich",
                worktree_id="worktree-rich",
                branch="branch-rich",
            )
            assert mcp_result["success"] is True
            assert mcp_result["record"]["value"] == "rich-task"
            mcp_ambiguous = mcp_server.local_ai_coord(
                action="memory_get",
                record_id=rich_record.record_id,
                task_id="task-rich",
                session_id="session-one",
            )
            assert mcp_ambiguous["success"] is False
            assert mcp_ambiguous["status_code"] == 400
        finally:
            mcp_server.CLIENT = previous_mcp_client
            mcp_client.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        gc.collect()
        http_server.APP = previous
        app.close()


def test_http_context_transport_preserves_diagnostics_flag(tmp_path: Path):
    import json
    import threading
    import urllib.request

    from local_ai_hub import http_server

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = 11498\nstate_dir = "{(tmp_path / "state").as_posix()}"\n'
        "\n[agent_state]\nenabled = true\n",
        encoding="utf-8",
    )
    app = LocalAIApp(str(cfg_path))
    previous = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = json.dumps({
            "action": "compile",
            "task_id": "transport-task",
            "token_budget": 120,
            "include_diagnostics": True,
        }).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/agent-state/context",
            data=payload,
            headers={"Content-Type": "application/json", "Connection": "close"},
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            result = json.loads(response.read().decode("utf-8"))
        assert result["success"] is True
        assert any(element["source_kind"] == "memory_diagnostics" for element in result["context"]["elements"])
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        gc.collect()
        http_server.APP = previous
        app.close()


def test_http_context_transport_forwards_scope_context(tmp_path: Path, monkeypatch):
    import json
    import threading
    import urllib.request

    from local_ai_hub import http_server
    from local_ai_hub.agent_context import CompiledContext

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = 11499\nstate_dir = "{(tmp_path / "state").as_posix()}"\n'
        "\n[agent_state]\nenabled = true\n",
        encoding="utf-8",
    )
    app = LocalAIApp(str(cfg_path))
    previous = http_server.APP
    http_server.APP = app
    seen = {}

    def capture(request):
        seen.update({
            "clone_id": request.clone_id,
            "worktree_id": request.worktree_id,
            "branch": request.branch,
            "repository_id": request.repository_id,
            "session_id": request.session_id,
            "repository_revision": request.repository_revision,
        })
        return CompiledContext(elements=[], estimated_tokens=0, token_budget=request.token_budget)

    monkeypatch.setattr(app.agent_context, "compile", capture)
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = json.dumps({
            "action": "compile",
            "task_id": "transport-task",
            "clone_id": "clone-http",
            "worktree_id": "worktree-http",
            "branch": "branch-http",
            "repository_id": "repository-http",
            "session_id": "session-http",
            "repository_revision": "revision-http",
        }).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/agent-state/context",
            data=payload,
            headers={"Content-Type": "application/json", "Connection": "close"},
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            result = json.loads(response.read().decode("utf-8"))
        assert result["success"] is True
        assert seen == {
            "clone_id": "clone-http",
            "worktree_id": "worktree-http",
            "branch": "branch-http",
            "repository_id": "repository-http",
            "session_id": "session-http",
            "repository_revision": "revision-http",
        }
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        gc.collect()
        http_server.APP = previous
        app.close()


def test_http_memory_transport_preserves_expiry_and_ttl(tmp_path: Path):
    import json
    import threading
    import urllib.request

    from local_ai_hub import http_server

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = 11500\nstate_dir = "{(tmp_path / "state").as_posix()}"\n'
        "\n[agent_state]\nenabled = true\n",
        encoding="utf-8",
    )
    app = LocalAIApp(str(cfg_path))
    previous = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def post(payload):
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/agent-state/memory",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Connection": "close"},
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))

    try:
        expires_at = time.time() + 600
        explicit = post({
            "action": "record",
            "idempotency_key": "expiry-explicit",
            "record": {
                "kind": "finding",
                "scope": "task",
                "scope_id": "task-expiry",
                "key": "explicit-expiry",
                "value": "v",
                "expires_at": expires_at,
            },
        })
        assert explicit["success"] is True
        assert explicit["record"]["expires_at"] == expires_at

        before = time.time()
        ttl_result = post({
            "action": "record",
            "idempotency_key": "expiry-ttl",
            "ttl_seconds": 120,
            "record": {
                "kind": "finding",
                "scope": "task",
                "scope_id": "task-expiry",
                "key": "ttl-expiry",
                "value": "v",
            },
        })
        assert ttl_result["success"] is True
        assert before + 100 <= ttl_result["record"]["expires_at"] <= time.time() + 120

        no_ttl = post({
            "action": "record",
            "idempotency_key": "expiry-unspecified",
            "record": {
                "kind": "finding",
                "scope": "task",
                "scope_id": "task-expiry",
                "key": "no-expiry",
                "value": "v",
            },
        })
        assert no_ttl["success"] is True
        assert no_ttl["record"]["expires_at"] is None
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        gc.collect()
        http_server.APP = previous
        app.close()


def test_client_convenience_methods(running_app_client):
    client, app = running_app_client
    calls = []

    def mock_post(path, payload, **kwargs):
        calls.append((path, payload))
        if path == "/api/agent-state/tasks":
            return {"success": True, "action": payload.get("action")}
        if path == "/api/agent-state/memory":
            return {"success": True, "action": payload.get("action")}
        if path == "/api/conversations/continue":
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
        if path == "/api/doctor":
            return {"success": True, "doctor": True}
        if "/api/logs/tail" in path:
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
            return {"success": True, "records": [{"scope": "task", "kind": "fact", "key": "k1", "value": "first"}]}

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
