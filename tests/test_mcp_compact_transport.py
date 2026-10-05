from __future__ import annotations

import asyncio
import ast
import json
from pathlib import Path
import pytest

from local_ai_hub import mcp_server as local_ai_mcp
import mcp.types as t
from local_ai_hub.token_accounting import json_tokens


def test_python_direct_invocation_returns_dict() -> None:
    res = local_ai_mcp.local_ai_status()
    assert isinstance(res, dict)
    assert "success" in res


def test_mcp_client_factory_forwards_tenant_and_config(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_client(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(local_ai_mcp, "HubClient", fake_client)
    client = local_ai_mcp._build_mcp_client("agent:workspace", "hub.toml")

    assert client is not None
    assert captured == {
        "tenant": "agent:workspace",
        "config_path": "hub.toml",
        "auto_start": True,
    }


def test_mcp_call_tool_returns_compact_minified_json(monkeypatch) -> None:
    monkeypatch.setattr(local_ai_mcp, "CLIENT", local_ai_mcp.HubClient(tenant="test", auto_start=False))
    monkeypatch.setattr(local_ai_mcp.CLIENT, "get", lambda path, timeout=None: {"hub_online": True, "scheduler": {}, "observability": {}})

    # Call via FastMCP call_tool (the MCP protocol entrypoint)
    result = asyncio.run(local_ai_mcp.mcp.call_tool("local_ai_status", {"detail": "brief"}))

    if isinstance(result, tuple):
        content = result[0][0]
    else:
        assert isinstance(result, list)
        assert len(result) >= 1
        content = result[0]
    assert isinstance(content, t.TextContent)
    assert content.type == "text"

    # Text must be compact (no newline formatting, no spacing around separators)
    assert "\n" not in content.text
    assert ": " not in content.text
    assert ", " not in content.text

    parsed = json.loads(content.text)
    assert isinstance(parsed, dict)
    assert parsed["success"] is True


def test_mcp_stdio_main_starts_proxy_then_runs_without_local_app_stack(monkeypatch) -> None:
    from types import SimpleNamespace

    calls = []

    class ProxyClient:
        auto_start = True
        startup_wait = 3.0

        def ensure_server(self, *, timeout):
            calls.append(("ensure_server", timeout))
            return True

    monkeypatch.setattr(local_ai_mcp, "CLIENT", ProxyClient())
    monkeypatch.setattr(
        local_ai_mcp, "bounded_startup_wait", lambda timeout: calls.append(("bounded_wait", timeout)) or 2.0
    )
    monkeypatch.setattr(local_ai_mcp, "mcp", SimpleNamespace(run=lambda: calls.append(("stdio_run",))))

    source = Path(local_ai_mcp.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    import_modules = {
        node.module for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module
    }
    forbidden_modules = {
        "local_ai_hub.app", "local_ai_hub.services", "local_ai_hub.indexes",
        "local_ai_hub.embeddings",
    }
    assert forbidden_modules.isdisjoint(import_modules)
    forbidden_names = {
        "LocalAIApp", "HubServices", "LocalAIServices", "RAGStore",
        "EmbeddingIndex", "ProcessPoolExecutor",
    }
    source_names = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    }
    assert forbidden_names.isdisjoint(source_names)
    client_assignment = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "CLIENT" for target in node.targets)
    )
    assert isinstance(client_assignment.value, ast.Call)
    assert isinstance(client_assignment.value.func, ast.Name)
    assert client_assignment.value.func.id == "_build_mcp_client"
    assert [ast.unparse(arg) for arg in client_assignment.value.args] == ["TENANT", "CONFIG_PATH"]
    builder = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_build_mcp_client"
    )
    assert [argument.arg for argument in builder.args.args] == ["tenant", "config_path"]
    hub_client_call = next(
        node for node in ast.walk(builder)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "HubClient"
    )
    assert {
        keyword.arg: ast.unparse(keyword.value)
        for keyword in hub_client_call.keywords
    } == {
        "tenant": "tenant",
        "config_path": "config_path",
        "auto_start": "True",
    }
    main_node = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    parents = {
        child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)
    }
    pool_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "ThreadPoolExecutor"
    ]
    assert pool_calls
    for call in pool_calls:
        parent = parents.get(call)
        while parent is not None and not isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
            parent = parents.get(parent)
        assert isinstance(parent, ast.FunctionDef)
        assert parent.name == "_local_ai_repo_impl"
    called_names = {
        node.func.id if isinstance(node.func, ast.Name)
        else node.func.attr if isinstance(node.func, ast.Attribute)
        else ""
        for node in ast.walk(main_node) if isinstance(node, ast.Call)
    }
    assert "ThreadPoolExecutor" not in called_names

    local_ai_mcp.main()

    assert calls == [("bounded_wait", 3.0), ("ensure_server", 2.0), ("stdio_run",)]


def test_mcp_stdio_initialize_tools_list_and_call_use_http_proxy(monkeypatch) -> None:
    from mcp.shared.memory import create_connected_server_and_client_session

    http_calls = []

    class HttpHubClientProbe:
        auto_start = True
        startup_wait = 2.0

        def get(self, path, **kwargs):
            http_calls.append((path, dict(kwargs)))
            return {"hub_online": True, "scheduler": {}, "observability": {}}

    monkeypatch.setattr(local_ai_mcp, "CLIENT", HttpHubClientProbe())
    monkeypatch.setattr(local_ai_mcp, "_mcp_operational_mode_block", lambda *args, **kwargs: None)

    async def protocol_round_trip():
        async with create_connected_server_and_client_session(local_ai_mcp.mcp) as session:
            # The helper performs MCP initialize before yielding the session.
            listed = await session.list_tools()
            calls_after_list = list(http_calls)
            called = await session.call_tool("local_ai_status", {"detail": "brief"})
            return listed, called, calls_after_list

    listed, called, calls_after_list = asyncio.run(protocol_round_trip())
    tool_names = {tool.name for tool in listed.tools}
    assert len(tool_names) == 8
    assert tool_names == set(local_ai_mcp.FEATURES.enabled_tools)
    assert calls_after_list == []
    assert called.content
    assert http_calls == [
        ("/api/live/status?light=1&scope=process", {})
    ]


def test_task_new_alias_is_advertised_and_invokes_task_create_through_mcp(monkeypatch, tmp_path: Path) -> None:
    tasks: dict[str, dict[str, str]] = {}
    calls: list[tuple[str, dict[str, str]]] = []

    def request(path, payload, **kwargs):
        calls.append((path, payload))
        if path != "/api/agent-state/tasks":
            raise AssertionError(f"unexpected HTTP proxy path: {path}")
        if payload["action"] == "create":
            task = {"task_id": "task-1", "task": payload["task"], "status": "active"}
            tasks[task["task_id"]] = task
            return {"success": True, "task": task}
        if payload["action"] == "get":
            return {"success": True, "task": tasks[payload["task_id"]]}
        raise AssertionError(f"unexpected task action: {payload['action']}")

    client = local_ai_mcp.HubClient(tenant="test")
    monkeypatch.setattr(local_ai_mcp, "CLIENT", client)
    monkeypatch.setattr(client, "request", request)
    tool = local_ai_mcp.mcp._tool_manager._tools["local_ai_coord"]
    assert "task_new" in tool.parameters["properties"]["action"]["enum"]
    assert client.auto_start is True

    created = asyncio.run(local_ai_mcp.mcp.call_tool(
        "local_ai_coord", {"action": "task_new", "task": "protocol-created task", "root": str(tmp_path)}
    ))
    created_content = created[0][0] if isinstance(created, tuple) else created[0]
    created_payload = json.loads(created_content.text)
    assert created_payload["success"] is True
    assert created_payload["task"]["task_id"] == "task-1"

    fetched = asyncio.run(local_ai_mcp.mcp.call_tool(
        "local_ai_coord", {"action": "task_get", "task_id": "task-1", "root": str(tmp_path)}
    ))
    fetched_content = fetched[0][0] if isinstance(fetched, tuple) else fetched[0]
    fetched_payload = json.loads(fetched_content.text)
    assert fetched_payload["task"]["task_id"] == "task-1"
    assert [path for path, _ in calls] == ["/api/agent-state/tasks", "/api/agent-state/tasks"]
    assert [payload["action"] for _, payload in calls] == ["create", "get"]
    assert calls[0][1]["task"] == "protocol-created task"
    assert calls[0][1]["root"] == str(tmp_path)
    assert calls[1][1]["task_id"] == "task-1"
    assert client.tenant == "test"


def test_lowlevel_request_handler_returns_compact_minified_json(monkeypatch) -> None:
    monkeypatch.setattr(local_ai_mcp, "CLIENT", local_ai_mcp.HubClient(tenant="test", auto_start=False))
    monkeypatch.setattr(local_ai_mcp.CLIENT, "get", lambda path, timeout=None: {"hub_online": True, "scheduler": {}, "observability": {}})

    req = t.CallToolRequest(method="tools/call", params=t.CallToolRequestParams(name="local_ai_status", arguments={"detail": "brief"}))
    server_res = asyncio.run(local_ai_mcp.mcp._mcp_server.request_handlers[t.CallToolRequest](req))

    assert hasattr(server_res, "root")
    tool_res = server_res.root
    assert isinstance(tool_res, t.CallToolResult)
    assert len(tool_res.content) >= 1
    content = tool_res.content[0]
    assert isinstance(content, t.TextContent)

    assert "\n" not in content.text
    assert ": " not in content.text
    assert ", " not in content.text

    parsed = json.loads(content.text)
    assert parsed["success"] is True


def _capture_client(monkeypatch, response):
    client = local_ai_mcp.HubClient(tenant="test", auto_start=False)
    calls = []

    def post(path, payload, timeout=None):
        calls.append((path, payload, timeout))
        return response

    monkeypatch.setattr(local_ai_mcp, "CLIENT", client)
    monkeypatch.setattr(client, "post", post)
    return calls


def test_local_ai_repo_context_forwards_guarded_pack_fields(monkeypatch) -> None:
    calls = _capture_client(monkeypatch, {"success": True, "evidence_ids": ["e1"]})

    result = local_ai_mcp.local_ai_repo(
        action="context",
        root="C:/repo",
        query="find route",
        workspace="ws",
        mode="full",
        task_id="task-1",
        phase="implementation",
        focus=["reuse", "contract"],
        preload_profile="default",
        changed_paths=["src/app.py"],
        base="main",
        staged=True,
        guarded=True,
        since_hash="rev-1",
        approval=True,
        override_reason="approved test scope",
        token_budget=777,
    )

    assert result["success"] is True
    assert len(calls) == 1
    path, payload, _ = calls[0]
    assert path == "/api/context/pack"
    assert payload == {
        "root": str(Path("C:/repo")),
        "query": "find route",
        "workspace": "ws",
        "max_tokens": 777,
        "mode": "full",
        "guarded": True,
        "task_id": "task-1",
        "phase": "implementation",
        "focus": ["reuse", "contract"],
        "preload_profile": "default",
        "changed_paths": ["src/app.py"],
        "base": "main",
        "staged": True,
        "since_hash": "rev-1",
        "approval": True,
        "override_reason": "approved test scope",
        "token_budget": 777,
    }


def test_local_ai_repo_context_preserves_legacy_fast_full_payload(monkeypatch) -> None:
    calls = _capture_client(monkeypatch, {"success": True, "context": "legacy"})

    local_ai_mcp.local_ai_repo(
        action="context", root="C:/repo", query="legacy", mode="full", max_tokens=512,
    )

    assert calls == [(
        "/api/context/pack",
        {"root": str(Path("C:/repo")), "query": "legacy", "workspace": None, "max_tokens": 512, "mode": "full"},
        600.0,
    )]


def test_local_ai_repo_non_context_actions_ignore_guard_fields(monkeypatch) -> None:
    calls = _capture_client(monkeypatch, {"success": True, "items": []})

    local_ai_mcp.local_ai_repo(
        action="search",
        root="C:/repo",
        query="route",
        task_id="task-1",
        phase="review",
        guarded=True,
        changed_paths=["src/app.py"],
        token_budget=777,
        approval=True,
    )

    assert calls == [(
        "/api/search",
        {"root": str(Path("C:/repo")), "query": "route", "top_k": 12, "enrich": False},
        180.0,
    )]


def test_local_ai_repo_context_returns_bounded_deterministic_projection(monkeypatch) -> None:
    response = {
        "success": True,
        "context": "x" * 20000,
        "evidence": [{"evidence_id": f"e{i}", "content": "y" * 1000} for i in range(40)],
        "evidence_ids": ["deterministic-1"],
        "warnings": [{"code": "scope_drift", "message": "warning"}],
        "repo_revision": "revision-1",
        "changed_paths": ["src/app.py"],
        "degraded": True,
        "fallback_used": True,
        "adaptive_context_pack": {
            "evidence": [{"evidence_id": "deterministic-pack"}],
            "warnings": [{"code": "pack-warning", "message": "pack warning"}],
            "repo_revision": "revision-pack",
            "changed_paths": ["pack.py"],
        },
        "postprocess": {"evidence_ids": ["model-claim"], "changed_paths": ["model.py"]},
    }
    calls = _capture_client(monkeypatch, response)

    result = local_ai_mcp.local_ai_repo(
        action="context", root="C:/repo", query="guarded", task_id="task-1", phase="review",
        guarded=True, max_response_tokens=500,
    )

    assert len(json.dumps(result, separators=(",", ":"))) <= 8000
    assert result["evidence_ids"] == ["deterministic-pack"]
    assert result["changed_paths"] == ["pack.py"]
    assert result["repo_revision"] == "revision-pack"
    assert result["warnings"][0]["code"] == "pack-warning"
    assert result["degraded"] is True
    assert result["fallback_used"] is True
    assert calls[0][1]["guarded"] is True


def test_local_ai_repo_guarded_projection_drops_nested_raw_model_fields(monkeypatch) -> None:
    response = {
        "success": True,
        "context": "safe deterministic context",
        "adaptive_context_pack": {
            "context_id": "ctx-safe",
            "evidence": [{"evidence_id": "e1", "path": "src/app.py"}],
            "model_debug": {
                "prompt": "private prompt should not escape",
                "raw_model_output": "private raw model output should not escape",
            },
            "relevance": {
                "claims": [{"output": "nested raw equivalent"}],
                "debug_trace": "private trace",
            },
        },
        "postprocess": {
            "prompt": "private postprocess prompt",
            "raw_model_output": "private postprocess output",
        },
    }
    _capture_client(monkeypatch, response)

    result = local_ai_mcp.local_ai_repo(
        action="context", root="C:/repo", query="guarded", task_id="task-1", phase="review",
        guarded=True, max_response_tokens=500,
    )

    encoded = json.dumps(result, separators=(",", ":"))
    for secret in (
        "model_debug", "raw_model_output", "private prompt should not escape",
        "private raw model output should not escape", "debug_trace", "nested raw equivalent",
    ):
        assert secret not in encoded
    assert result["context_id"] == "ctx-safe"


def test_local_ai_repo_context_bounds_oversized_authoritative_fields(monkeypatch) -> None:
    response = {
        "success": True,
        "context": "context",
        "adaptive_context_pack": {
            "warnings": [{"code": "scope_drift", "message": "w" * 10000} for _ in range(24)],
            "evidence": [{"evidence_id": f"evidence-{i}-" + ("e" * 10000)} for i in range(24)],
            "repo_revision": "revision-" + ("r" * 10000),
            "changed_paths": ["src/" + ("p" * 10000) for _ in range(24)],
        },
    }
    _capture_client(monkeypatch, response)

    result = local_ai_mcp.local_ai_repo(
        action="context", root="C:/repo", query="guarded", task_id="task-1", phase="review",
        guarded=True, max_response_tokens=220,
    )

    assert json_tokens(result) <= 220
    assert result["response_budget"]["requested_tokens"] == 220


def test_local_ai_repo_context_low_budget_preserves_authoritative_envelope(monkeypatch) -> None:
    response = {
        "success": True,
        "adaptive_context_pack": {
            "context_id": "ctx-123",
            "repo_revision": "revision-1",
            "stale": True,
            "warnings": [{"code": "scope_drift", "message": "warning"}],
            "evidence": [{"evidence_id": "evidence-1"}],
            "delta_from": "ctx-previous",
            "since_hash": "hash-1",
        },
    }
    _capture_client(monkeypatch, response)

    result = local_ai_mcp.local_ai_repo(
        action="context",
        root="C:/repo",
        query="guarded",
        task_id="task-1",
        phase="review",
        guarded=True,
        max_response_tokens=128,
    )

    assert json_tokens(result) <= 128
    assert result["context_id"] == "ctx-123"
    assert result["repo_revision"] == "revision-1"
    assert result["stale"] is True
    assert result["warnings"] == [{"code": "scope_drift", "message": "warning"}]
    assert result["delta_from"] == "ctx-previous"
    assert result["since_hash"] == "hash-1"
    assert result["evidence_ids"] == ["evidence-1"]


def test_local_ai_repo_context_propagates_bounded_http_error(monkeypatch) -> None:
    calls = _capture_client(monkeypatch, {
        "success": False, "status_code": 400, "terminal": True, "retryable": False,
        "error": "focus must be a list",
    })

    result = local_ai_mcp.local_ai_repo(
        action="context", root="C:/repo", query="bad", guarded=True, task_id="task-1",
    )

    assert result == {
        "success": False,
        "status_code": 400,
        "terminal": True,
        "retryable": False,
        "error": "focus must be a list",
    }
    assert calls[0][0] == "/api/context/pack"


def test_local_ai_repo_context_rejects_non_object_route_response(monkeypatch) -> None:
    _capture_client(monkeypatch, "not-json-object")

    result = local_ai_mcp.local_ai_repo(action="context", root="C:/repo", query="bad")

    assert result == {
        "success": False,
        "status_code": 502,
        "terminal": True,
        "retryable": True,
        "error": "context pack response must be a JSON object",
    }


def test_local_ai_repo_context_rejects_malformed_guard_input_before_http(monkeypatch) -> None:
    calls = _capture_client(monkeypatch, {"success": True})

    result = local_ai_mcp.local_ai_repo(
        action="context", root="C:/repo", guarded="yes", task_id="task-1",
    )

    assert result["success"] is False
    assert result["status_code"] == 400
    assert result["terminal"] is True
    assert "guarded must be boolean" in result["error"]
    assert calls == []


def test_local_ai_repo_context_rejects_guard_fields_without_guard_trigger(monkeypatch) -> None:
    calls = _capture_client(monkeypatch, {"success": True})

    result = local_ai_mcp.local_ai_repo(
        action="context", root="C:/repo", changed_paths=["src/app.py"],
    )

    assert result["success"] is False
    assert result["status_code"] == 400
    assert "require guarded=true" in result["error"]
    assert calls == []


def test_context_compile_compatibility_stays_on_agent_state_route(monkeypatch) -> None:
    calls = _capture_client(monkeypatch, {"success": True, "task_id": "task-1"})

    local_ai_mcp.local_ai_repo(action="context_compile", root="C:/repo", task_id="task-1", max_tokens=900)

    assert calls[0][0] == "/api/agent-state/context"
    assert calls[0][1]["task_id"] == "task-1"
    assert calls[0][1]["token_budget"] == 900
def test_shared_hub_clients_keep_repo_root_and_task_separate(monkeypatch, tmp_path):
    import local_ai_hub.mcp_server as mcp_server

    from local_ai_hub.client import HubClient

    captured = []

    def fake_post(self, path, payload, **kwargs):
        captured.append((self.tenant, path, dict(payload)))
        return {"success": True, "items": []}

    monkeypatch.setattr(HubClient, "post", fake_post)
    roots = [tmp_path / "worktree-a", tmp_path / "worktree-b"]
    for root in roots:
        root.mkdir()

    for root, task_id in (
        (roots[0], "task-a"),
        (roots[1], "task-b"),
    ):
        client = HubClient(tenant="same-base-client", auto_start=False)
        monkeypatch.setattr(mcp_server, "CLIENT", client)
        result = mcp_server._local_ai_repo_impl(
            action="context",
            root=str(root),
            query="isolation probe",
            task_id=task_id,
            phase="edit",
        )
        assert result.get("success") is True

    assert [(tenant, payload.get("root"), payload.get("task_id")) for tenant, _, payload in captured] == [
        ("same-base-client", mcp_server.canonical_root(roots[0]), "task-a"),
        ("same-base-client", mcp_server.canonical_root(roots[1]), "task-b"),
    ]


def test_repo_operation_requires_root_when_process_cwd_is_not_project(monkeypatch):
    import local_ai_hub.mcp_server as mcp_server

    monkeypatch.delenv("LOCAL_AI_ROOT", raising=False)
    monkeypatch.setattr(mcp_server, "_workspace", "")
    result = mcp_server._local_ai_repo_impl(action="profile", root="")

    assert result.get("success") is False
    assert result.get("error_code") == "repository_root_required"


def test_client_root_allows_explicit_hub_repo_and_local_session_id_is_stable(monkeypatch):
    import local_ai_hub.mcp_server as mcp_server

    assert mcp_server._client_root(str(mcp_server._hub_install_root)) == mcp_server.canonical_root(
        mcp_server._hub_install_root
    )
    monkeypatch.setenv("LOCAL_AI_ROOT", str(mcp_server._hub_install_root))
    assert mcp_server._configured_repo_root() == mcp_server.canonical_root(mcp_server._hub_install_root)
    assert mcp_server._local_session_id("agent", "config.toml") == mcp_server._local_session_id(
        "agent", "config.toml"
    )
    assert mcp_server._local_session_id("agent", "config-a.toml") != mcp_server._local_session_id(
        "agent", "config-b.toml"
    )


def test_client_root_rejects_direct_and_ancestor_symlinks(monkeypatch, tmp_path):
    import os

    import local_ai_hub.mcp_server as mcp_server

    target = tmp_path / "real-parent" / "repo"
    target.mkdir(parents=True)
    (target / "pyproject.toml").write_text("", encoding="utf-8")
    direct_link = tmp_path / "direct-link"
    parent_link = tmp_path / "parent-link"
    try:
        os.symlink(target, direct_link, target_is_directory=True)
        os.symlink(target.parent, parent_link, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")

    assert mcp_server._client_root(str(direct_link)) == ""
    assert mcp_server._client_root(str(parent_link / "repo")) == ""
    monkeypatch.setenv("LOCAL_AI_ROOT", str(direct_link))
    assert mcp_server._configured_repo_root() == ""
    monkeypatch.setenv("LOCAL_AI_ROOT", str(parent_link / "repo"))
    assert mcp_server._configured_repo_root() == ""


def test_agent_task_context_requires_project_root_and_fails_before_transport(monkeypatch):
    import local_ai_hub.mcp_server as mcp_server

    captured = []

    class ContextClient:
        def post(self, path, payload, **kwargs):
            captured.append((path, dict(payload)))
            return {"success": True, "context": "agent context", "evidence_ids": []}

    monkeypatch.delenv("LOCAL_AI_ROOT", raising=False)
    monkeypatch.setattr(mcp_server, "CLIENT", ContextClient())
    context, meta = mcp_server._load_task_context(task_id="task-agent-only", root="", context="seed")

    assert context == "seed"
    assert meta.get("error_code") == "repository_root_required"
    assert captured == []


def test_memory_calls_keep_same_task_separate_by_canonical_root(monkeypatch, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Lock

    import local_ai_hub.mcp_server as mcp_server
    from local_ai_hub.client import HubClient

    records = {}
    lock = Lock()

    def fake_post(self, path, payload, **kwargs):
        assert path == "/api/agent-state/memory"
        assert "tenant" not in payload
        identity = (payload["root"], payload["task_id"], payload["key"])
        with lock:
            if payload["action"] == "record":
                records[identity] = payload["record"]["value"]
            return {"success": True, "records": [{"value": records[identity]}] if identity in records else []}

    monkeypatch.setattr(HubClient, "post", fake_post)
    roots = [tmp_path / "repo-a", tmp_path / "repo-b"]
    for root in roots:
        root.mkdir()

    def round_trip(root, value):
        client = HubClient(tenant="same-base-client", auto_start=False)
        record_payload, error = mcp_server._agent_memory_kwargs(
            action="memory_record", root=str(root), task_id="shared-task",
            scope="task", record={
                "key": "shared-key", "value": value, "root": "wrong-root",
                "task_id": "wrong-task", "tenant": "caller-tenant",
                "provenance": {
                    "tenant": "caller-tenant", "root": "wrong-root", "task_id": "wrong-task",
                },
            },
        )
        assert error is None and record_payload is not None
        assert record_payload["record"]["root"] == mcp_server.canonical_root(root)
        assert record_payload["record"]["task_id"] == "shared-task"
        assert "tenant" not in record_payload["record"]
        assert "tenant" not in record_payload["record"]["provenance"]
        assert "root" not in record_payload["record"]["provenance"]
        assert "task_id" not in record_payload["record"]["provenance"]
        client.coord(**record_payload)
        find_payload, error = mcp_server._agent_memory_kwargs(
            action="memory_find", root=str(root), task_id="shared-task",
            scope="task", key="shared-key",
        )
        assert error is None and find_payload is not None
        return client.coord(**find_payload)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(round_trip, roots, ("value-a", "value-b")))

    assert [result["records"][0]["value"] for result in results] == ["value-a", "value-b"]


def test_memory_repo_lookup_without_root_fails_closed(monkeypatch):
    import local_ai_hub.mcp_server as mcp_server

    monkeypatch.delenv("LOCAL_AI_ROOT", raising=False)
    payload, error = mcp_server._agent_memory_kwargs(
        action="memory_find", root="", task_id="shared-task", scope="task", key="shared-key"
    )

    assert payload is None
    assert error is not None
    assert error.get("error_code") == "repository_root_required"


def test_mcp_memory_dispatch_forwards_root_and_task_not_client_tenant(monkeypatch, tmp_path):
    import local_ai_hub.mcp_server as mcp_server

    captured = []

    class CoordClient:
        def coord(self, **kwargs):
            captured.append(dict(kwargs))
            return {"success": True}

    monkeypatch.setattr(mcp_server, "_mcp_operational_mode_block", lambda *args, **kwargs: None)
    monkeypatch.setattr(mcp_server, "CLIENT", CoordClient())
    result = mcp_server.local_ai_coord(
        action="memory_record",
        root=str(tmp_path),
        task_id="task-mcp",
        scope="task",
        record={
            "key": "k", "value": "v", "tenant": "caller-controlled",
            "provenance": {
                "tenant": "caller-controlled", "root": "wrong-root", "task_id": "wrong-task",
            },
        },
        tenant="caller-controlled",
    )

    assert result.get("success") is True
    assert captured[0]["root"] == mcp_server.canonical_root(tmp_path)
    assert captured[0]["task_id"] == "task-mcp"
    assert "tenant" not in captured[0]
    assert "tenant" not in captured[0]["record"]
    assert "tenant" not in captured[0]["record"]["provenance"]
    assert "root" not in captured[0]["record"]["provenance"]
    assert "task_id" not in captured[0]["record"]["provenance"]


def test_task_event_sync_requires_and_forwards_root_task_stream(monkeypatch, tmp_path):
    import local_ai_hub.mcp_server as mcp_server

    captured = []

    class EventClient:
        def post(self, path, payload, **kwargs):
            captured.append((path, dict(payload)))
            return {"success": True, "events": []}

    monkeypatch.delenv("LOCAL_AI_ROOT", raising=False)
    monkeypatch.setattr(mcp_server, "_workspace", "")
    monkeypatch.setattr(mcp_server, "_mcp_operational_mode_block", lambda *args, **kwargs: None)
    monkeypatch.setattr(mcp_server, "CLIENT", EventClient())

    missing = mcp_server.local_ai_coord(action="task_sync", status="export", task_id="task-a")
    assert missing.get("error_code") == "task_scope_required"
    assert captured == []

    result = mcp_server.local_ai_coord(
        action="task_sync", status="export", root=str(tmp_path), task_id="task-a"
    )
    assert result.get("success") is True
    path, payload = captured[0]
    assert path == "/api/agent-state/events/delta"
    assert payload["root"] == mcp_server.canonical_root(tmp_path)
    assert payload["task_id"] == "task-a"
    assert payload["stream_id"] == "task:task-a"


def test_task_zombie_reap_requires_and_forwards_root_scope(monkeypatch, tmp_path):
    import local_ai_hub.mcp_server as mcp_server

    requests = []

    class TaskClient:
        def post(self, path, payload, **kwargs):
            requests.append((path, dict(payload)))
            return {"success": True}

    root = tmp_path / "repo"
    root.mkdir()
    (root / "pyproject.toml").touch()
    monkeypatch.delenv("LOCAL_AI_ROOT", raising=False)
    monkeypatch.setattr(mcp_server, "_workspace", "")
    monkeypatch.setattr(mcp_server, "_mcp_operational_mode_block", lambda *args, **kwargs: None)
    monkeypatch.setattr(mcp_server, "CLIENT", TaskClient())

    missing = mcp_server.local_ai_coord(action="task_zombie_reap", task_id="task-a")
    assert missing.get("error_code") == "task_scope_required"
    assert requests == []

    result = mcp_server.local_ai_coord(
        action="task_zombie_reap", root=str(root), task_id="task-a"
    )
    assert result.get("success") is True
    path, payload = requests[0]
    assert path == "/api/agent-state/tasks"
    assert payload["action"] == "reap_expired"
    assert payload["root"] == mcp_server.canonical_root(root)
    assert payload["task_id"] == "task-a"
    assert payload["auto_recover"] is True
    assert "tenant" not in payload
    assert "operational_action" not in payload
    assert "requires_heavy_work" not in payload


def test_dataset_curation_requires_and_forwards_root_scope(monkeypatch, tmp_path):
    import local_ai_hub.mcp_server as mcp_server

    requests = []

    class TaskClient:
        def post(self, path, payload, **kwargs):
            requests.append((path, dict(payload)))
            return {"success": True}

    root = tmp_path / "repo"
    root.mkdir()
    (root / "pyproject.toml").touch()
    monkeypatch.delenv("LOCAL_AI_ROOT", raising=False)
    monkeypatch.setattr(mcp_server, "_workspace", "")
    monkeypatch.setattr(mcp_server, "_mcp_operational_mode_block", lambda *args, **kwargs: None)
    monkeypatch.setattr(mcp_server, "CLIENT", TaskClient())

    missing = mcp_server.local_ai_coord(action="curate_dataset", task_id="task-a")
    assert missing.get("error_code") == "task_scope_required"
    assert requests == []

    result = mcp_server.local_ai_coord(
        action="curate_dataset", root=str(root), task_id="task-a", key="dataset.jsonl"
    )
    assert result.get("success") is True
    path, payload = requests[0]
    assert path == "/api/agent-state/tasks"
    assert payload["action"] == "curate_dataset"
    assert payload["root"] == mcp_server.canonical_root(root)
    assert payload["task_id"] == "task-a"
    assert payload["output_path"] == "dataset.jsonl"
    assert "tenant" not in payload
    assert "operational_action" not in payload
    assert "requires_heavy_work" not in payload


def test_coord_task_route_projection_requires_root_and_keeps_scoped_actions(monkeypatch):
    from types import SimpleNamespace

    import local_ai_hub.mcp_server as mcp_server

    raw_schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(mcp_server.CoordAction.__args__)},
            "root": {"type": "string"},
            "task_id": {"type": "string"},
        },
        "required": ["action"],
        "additionalProperties": False,
    }
    tool = SimpleNamespace(parameters=raw_schema)
    runtime = SimpleNamespace(
        _tool_manager=SimpleNamespace(_tools={"local_ai_coord": tool})
    )
    monkeypatch.setattr(mcp_server, "mcp", runtime)

    projected = mcp_server._mcp_contract_schema("local_ai_coord")
    assert projected is not None
    action_enum = projected["properties"]["action"]["enum"]
    assert {"task_zombie_reap", "curate_dataset"}.issubset(set(action_enum))
    root_scope = {
        "if": {
            "properties": {
                "action": {"enum": ["curate_dataset", "task_zombie_reap"]}
            },
            "required": ["action"],
        },
        "then": {"required": ["root"]},
    }
    assert root_scope in projected["allOf"]


def test_context_compile_requires_and_forwards_explicit_root_task(monkeypatch, tmp_path):
    import local_ai_hub.mcp_server as mcp_server

    captured = []

    class ContextClient:
        def post(self, path, payload, **kwargs):
            captured.append((path, dict(payload)))
            return {"success": True, "complete": True, "task_context": {"text": "context"}}

    monkeypatch.delenv("LOCAL_AI_ROOT", raising=False)
    monkeypatch.setattr(mcp_server, "_workspace", "")
    monkeypatch.setattr(mcp_server, "_mcp_operational_mode_block", lambda *args, **kwargs: None)
    monkeypatch.setattr(mcp_server, "CLIENT", ContextClient())

    missing = mcp_server.local_ai_coord(action="context_compile", query="must not become id")
    assert missing.get("error_code") == "task_scope_required"
    assert captured == []

    result = mcp_server.local_ai_coord(
        action="context_compile", root=str(tmp_path), task_id="task-context", query="context query"
    )
    assert result.get("success") is True
    path, payload = captured[0]
    assert path == "/api/agent-state/context"
    assert payload["root"] == mcp_server.canonical_root(tmp_path)
    assert payload["task_id"] == "task-context"


def test_verification_routes_require_matching_root_task_identity(monkeypatch, tmp_path):
    import local_ai_hub.mcp_server as mcp_server

    captured = []

    class VerificationClient:
        def post(self, path, payload, **kwargs):
            captured.append((path, dict(payload)))
            return {"success": True}

    monkeypatch.delenv("LOCAL_AI_ROOT", raising=False)
    monkeypatch.setattr(mcp_server, "_workspace", "")
    monkeypatch.setattr(mcp_server, "_mcp_operational_mode_block", lambda *args, **kwargs: None)
    monkeypatch.setattr(mcp_server, "CLIENT", VerificationClient())

    missing = mcp_server.local_ai_coord(action="verify_completion", task_id="task-v")
    assert missing.get("error_code") == "task_scope_required"
    assert captured == []

    result = mcp_server.local_ai_coord(
        action="verify_receipt",
        root=str(tmp_path),
        task_id="task-v",
        criterion="unit selector passed",
        status="passed",
    )
    assert result.get("success") is True
    path, payload = captured[0]
    assert path == "/api/agent-state/verification"
    assert payload["root"] == mcp_server.canonical_root(tmp_path)
    assert payload["task_id"] == "task-v"
    assert payload["receipt"]["task_id"] == "task-v"
