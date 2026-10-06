from __future__ import annotations

import asyncio
import json
from pathlib import Path
import socket
import pytest

from local_ai_hub import mcp_server as local_ai_mcp
from local_ai_hub import client as client_module
import mcp.types as t
from local_ai_hub.token_accounting import json_tokens


def test_python_direct_invocation_returns_dict() -> None:
    res = local_ai_mcp.local_ai_status()
    assert isinstance(res, dict)
    assert "success" in res


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


def test_mcp_status_remains_usable_when_hub_daemon_is_offline(tmp_path, monkeypatch) -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        config_path = tmp_path / "offline.toml"
        state_dir = (tmp_path / "state").as_posix()
        config_path.write_text(f'[server]\nport = {port}\nstate_dir = "{state_dir}"\n', encoding="utf-8")
        client = local_ai_mcp.HubClient(tenant="offline-test", config_path=str(config_path), auto_start=False)
        monkeypatch.setattr(local_ai_mcp, "CLIENT", client)
        monkeypatch.setattr(
            client_module.subprocess,
            "Popen",
            lambda *_args, **_kwargs: pytest.fail("daemon-off MCP call must not spawn a process"),
        )

        result = asyncio.run(local_ai_mcp.mcp.call_tool("local_ai_status", {"detail": "brief"}))
        content = result[0][0] if isinstance(result, tuple) else result[0]

        assert isinstance(content, t.TextContent)
        payload = json.loads(content.text)
        assert payload["success"] is False
        assert not Path(client.config["server"]["state_dir"]).exists()


def test_mcp_delegate_autostarts_owned_daemon_and_preserves_http_payload(tmp_path, monkeypatch) -> None:
    from local_ai_hub import http_server
    from local_ai_hub.app import LocalAIApp
    import sys
    import subprocess
    import time
    import traceback
    import types
    from types import SimpleNamespace
    import threading
    from local_ai_hub.external_tools import ExternalCodeIntelligence

    operational_mode = types.ModuleType("local_ai_hub.operational_mode")
    operational_mode.load_operational_mode = lambda _path: SimpleNamespace(mode="active", degraded=False)
    monkeypatch.setitem(sys.modules, operational_mode.__name__, operational_mode)
    monkeypatch.setattr(ExternalCodeIntelligence, "_startup_preflight", lambda _self: None)

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    state_dir = (tmp_path / "state").as_posix()
    config_path = tmp_path / "autostart.toml"
    config_path.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = {port}\nstate_dir = "{state_dir}"\n'
        "[client]\nstartup_wait_seconds = 2\nstartup_poll_seconds = 0.05\nhealth_timeout_seconds = 0.2\n",
        encoding="utf-8",
    )
    received: list[tuple[dict[str, object], str]] = []
    server_box: dict[str, object] = {}
    owned_children: list[object] = []
    retained_children: list[object] = []
    start_events: list[tuple[int, object, str]] = []
    app = LocalAIApp(str(config_path))
    server_box.update(app=app, serve_errors=[])
    generated: list[str] = []

    def fake_generate(model, prompt, system, max_tokens, temperature, tenant, source, priority, **kwargs):
        generated.append(prompt)
        return {"success": True, "model": model, "text": f"HTTP result {len(generated)}"}

    app.services._generate = fake_generate
    original_delegate = app.services.delegate

    def capture_delegate(payload, tenant):
        received.append((dict(payload), tenant))
        return original_delegate(payload, tenant)

    app.services.delegate = capture_delegate

    def start_owned_server(*_args, **_kwargs):
        lock_path = Path(state_dir) / "hub.start.lock"
        lock_snapshot = lock_path.read_text(encoding="utf-8") if lock_path.exists() else "<missing>"
        start_events.append((threading.get_ident(), _args[0] if _args else None, lock_snapshot))
        monkeypatch.setattr(http_server, "APP", app)
        server = http_server.LocalAIHTTPServer(("127.0.0.1", port), http_server.Handler)

        def serve():
            try:
                server.serve_forever()
            except BaseException as exc:
                server_box.setdefault("serve_errors", []).append(exc)

        thread = threading.Thread(target=serve, daemon=True)
        server_box.update(server=server, thread=thread)
        thread.start()
        child = SimpleNamespace(poll=lambda: None)
        owned_children.append(child)
        return child

    client = local_ai_mcp.HubClient(tenant="autostart-test", config_path=str(config_path), auto_start=True)
    monkeypatch.setattr(local_ai_mcp, "CLIENT", client)
    monkeypatch.setattr(local_ai_mcp.FEATURES, "tasks", True)
    monkeypatch.setattr(local_ai_mcp.FEATURES, "has_any_model", lambda: True)
    monkeypatch.setattr(client_module, "find_listening_pid", lambda _port: False)
    # Isolate client process creation. Patching subprocess.Popen in-place also
    # intercepts unrelated ExternalCodeIntelligence and pip preflight children.
    monkeypatch.setattr(client_module, "subprocess", SimpleNamespace(
        Popen=start_owned_server,
        DEVNULL=subprocess.DEVNULL,
        TimeoutExpired=subprocess.TimeoutExpired,
    ))
    monkeypatch.setattr(client_module, "_retain_detached_child", retained_children.append)

    tasks = (("Summarize first input", "First source facts"), ("Summarize second input", "Second source facts"))

    async def dispatch_concurrently():
        return await asyncio.gather(*(
            local_ai_mcp.mcp.call_tool("local_ai_task", {
                "action": "delegate",
                "task": task,
                "context": context,
                "complexity": "low",
                "max_tokens": 256,
                "delivery": "sync",
                "latency_budget_ms": 1500,
            })
            for task, context in tasks
        ))

    try:
        results = asyncio.run(dispatch_concurrently())
    finally:
        client.close()
        server = server_box.get("server")
        if server is not None:
            thread = server_box["thread"]
            assert threading.current_thread() is not thread
            drain_deadline = time.monotonic() + 5
            while server.concurrency_stats()["active"] and time.monotonic() < drain_deadline:
                time.sleep(0.01)
            assert server.concurrency_stats()["active"] == 0
            shutdown_thread = threading.Thread(target=server.shutdown, daemon=True)
            shutdown_thread.start()
            shutdown_thread.join(timeout=5)
            if shutdown_thread.is_alive():
                server.server_close()
                shutdown_thread.join(timeout=5)
            assert not shutdown_thread.is_alive(), "HTTP server shutdown exceeded bounded wait"
            server.server_close()
            thread.join(timeout=5)
            if thread.is_alive():
                frame = sys._current_frames().get(thread.ident)
                stack = "".join(traceback.format_stack(frame)) if frame is not None else "stack unavailable"
                pytest.fail(f"HTTP serve_forever thread did not stop; stack:\n{stack}")
            assert server_box["serve_errors"] == []
        app = server_box.get("app")
        if app is not None:
            server_box["app"].close()

    for result, (task, _context) in zip(results, tasks):
        content = result[0][0] if isinstance(result, tuple) else result[0]
        assert isinstance(content, t.TextContent)
        payload = json.loads(content.text)
        assert payload["success"] is True, payload
        assert payload["text"].startswith("HTTP result ")
    assert sorted(received, key=lambda item: item[0]["task"]) == [
        ({
            "task": task,
            "context": context,
            "complexity": "low",
            "max_tokens": 256,
            "delivery": "sync",
            "latency_budget_ms": 1500,
            "model": "",
            "operation": "delegate",
            "changed_paths": [],
            "repository_revision": "",
            "evidence_ids": [],
        }, "autostart-test")
        for task, context in tasks
    ]
    assert len(owned_children) == 1, f"duplicate daemon starts: {start_events!r}"
    assert retained_children == owned_children


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
