from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
import socket
import pytest

from local_ai_hub import mcp_server as local_ai_mcp
from local_ai_hub import client as client_module
from local_ai_hub.artifacts import ArtifactStore
import mcp.types as t
from local_ai_hub.token_accounting import json_tokens


def _assert_json_schema(value, schema: dict[str, object]) -> None:
    if "const" in schema:
        assert value == schema["const"]
    alternatives = schema.get("anyOf")
    if isinstance(alternatives, list):
        for alternative in alternatives:
            try:
                _assert_json_schema(value, alternative)
                break
            except AssertionError:
                continue
        else:
            raise AssertionError(f"value does not match any schema branch: {value!r}")

    expected = schema.get("type")
    if expected is not None:
        expected_types = expected if isinstance(expected, list) else [expected]
        type_checks = {
            "object": lambda item: isinstance(item, dict),
            "array": lambda item: isinstance(item, list),
            "string": lambda item: isinstance(item, str),
            "boolean": lambda item: isinstance(item, bool),
            "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
            "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
            "null": lambda item: item is None,
        }
        assert any(type_checks[kind](value) for kind in expected_types), (expected, value)

    if isinstance(value, dict):
        for key in schema.get("required", []):
            assert key in value, f"missing required output field: {key}"
        properties = schema.get("properties", {})
        for key, child_schema in properties.items():
            if key in value and isinstance(child_schema, dict):
                _assert_json_schema(value[key], child_schema)
    elif isinstance(value, list) and isinstance(schema.get("items"), dict):
        for item in value:
            _assert_json_schema(item, schema["items"])


def _telemetry_output_schema() -> dict[str, object]:
    output_schema = local_ai_mcp.mcp._tool_manager._tools["local_ai_status"].output_schema
    return output_schema["x-action-output-contracts"]["telemetry"]


def test_status_telemetry_compaction_preserves_required_empty_arrays_and_matches_schema() -> None:
    report = {
        "success": True,
        "window": {"days": 30, "scope": "window", "events": 0},
        "summary": {"events": 0},
        "queue": {},
        "hotspots": [],
        "by_operation": [],
        "error_fingerprints": [],
        "detail": {},
        "decision_grade": {},
    }

    result = local_ai_mcp._compact(report, "status")

    _assert_json_schema(result, _telemetry_output_schema())
    assert result["hotspots"] == []
    assert result["by_operation"] == []
    assert result["error_fingerprints"] == []


def test_mcp_telemetry_tools_call_loopback_matches_declared_output_schema(tmp_path, monkeypatch) -> None:
    from local_ai_hub import http_server
    from local_ai_hub.app import LocalAIApp
    from local_ai_hub.client import HubClient

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    state_dir = (tmp_path / "state").as_posix()
    config = tmp_path / "config.toml"
    config.write_text(
        f'[server]\nbind="127.0.0.1"\nport={port}\nstate_dir="{state_dir}"\n'
        "[observability]\nenabled=true\n",
        encoding="utf-8",
    )
    app = LocalAIApp(str(config))
    monkeypatch.setattr(app.telemetry, "report", lambda *args, **kwargs: {
        "success": True,
        "window": {"days": 30, "scope": "window", "events": 0},
        "summary": {"events": 0},
        "queue": {},
        "hotspots": [],
        "by_operation": [],
        "error_fingerprints": [],
        "detail": {},
        "decision_grade": {},
    })
    previous_app = http_server.APP
    previous_client = local_ai_mcp.CLIENT
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", port), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = HubClient(tenant="mcp-telemetry-test", config_path=str(config), auto_start=False)
    monkeypatch.setattr(local_ai_mcp, "CLIENT", client)
    request = t.CallToolRequest(
        method="tools/call",
        params=t.CallToolRequestParams(name="local_ai_status", arguments={"detail": "telemetry", "scope": "window"}),
    )
    try:
        declared_schema = _telemetry_output_schema()
        response = asyncio.run(local_ai_mcp.mcp._mcp_server.request_handlers[t.CallToolRequest](request))
        assert isinstance(response.root, t.CallToolResult)
        assert response.root.isError is not True
        payload = json.loads(response.root.content[0].text)
        assert payload["success"] is True, payload
        _assert_json_schema(payload, declared_schema)
        assert payload["hotspots"] == []
        assert payload["by_operation"] == []
        assert payload["error_fingerprints"] == []
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        http_server.APP = previous_app
        local_ai_mcp.CLIENT = previous_client
        app.close()


def test_mcp_telemetry_error_text_is_redacted(monkeypatch) -> None:
    private_values = (
        "PROMPT-SECRET",
        "token=TOKEN-SECRET",
        "/private/customer/report.json",
    )
    private_error = "telemetry failed: " + " ".join(private_values)

    def fake_get(path: str, timeout: float | None = None) -> dict[str, object]:
        if path.startswith("/api/live/status"):
            return {"success": True, "hub_online": True, "runtime_stats": {}}
        return {"success": False, "error": private_error}

    monkeypatch.setattr(local_ai_mcp.FEATURES, "status", True)
    monkeypatch.setattr(local_ai_mcp.CLIENT, "get", fake_get)
    request = t.CallToolRequest(
        method="tools/call",
        params=t.CallToolRequestParams(name="local_ai_status", arguments={"detail": "telemetry"}),
    )

    response = asyncio.run(local_ai_mcp.mcp._mcp_server.request_handlers[t.CallToolRequest](request))

    assert isinstance(response.root, t.CallToolResult)
    assert response.root.isError is not True
    payload = json.loads(response.root.content[0].text)
    assert payload["success"] is False
    assert payload["error"] == "Telemetry report failed; details omitted"
    assert all(value not in response.root.content[0].text for value in private_values)


def _mcp_telemetry_call() -> t.CallToolResult:
    request = t.CallToolRequest(
        method="tools/call",
        params=t.CallToolRequestParams(name="local_ai_status", arguments={"detail": "telemetry"}),
    )
    response = asyncio.run(local_ai_mcp.mcp._mcp_server.request_handlers[t.CallToolRequest](request))
    assert isinstance(response.root, t.CallToolResult)
    return response.root


def test_mcp_telemetry_loopback_redacts_nested_error_text_and_keeps_metrics(tmp_path, monkeypatch) -> None:
    from local_ai_hub import http_server
    from local_ai_hub.app import LocalAIApp
    from local_ai_hub.client import HubClient

    private_values = (
        "PROMPT-SECRET",
        "token=TOKEN-SECRET",
        "/private/customer/report.json",
    )
    telemetry_error = " ".join(private_values)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    config = tmp_path / "config.toml"
    config.write_text(
        f'[server]\nbind="127.0.0.1"\nport={port}\nstate_dir="{(tmp_path / "state").as_posix()}"\n'
        "[observability]\nenabled=true\n",
        encoding="utf-8",
    )
    app = LocalAIApp(str(config))
    report = {
        "success": True,
        "window": {"days": 30, "scope": "window", "events": 7},
        "summary": {"events": 7, "failure_rate": 0.25},
        "queue": {"events": 2, "avg_age_ms": 17.5, "last_error": telemetry_error},
        "hotspots": [{"type": "latency", "signal": "queue_wait", "value_ms": 80, "message": telemetry_error}],
        "by_operation": [{"action": "context", "calls": 4, "error_message": telemetry_error}],
        "error_fingerprints": [],
        "detail": {
            "status": "incomplete", "truncated": True, "incomplete": True,
            "omitted_sections": ["writer_failures"], "list_limit": 24, "recent_error": telemetry_error,
        },
        "decision_grade": {
            "counts": {"events": 7},
            "queue": {"events": 2, "error": telemetry_error},
            "detail": {"status": "complete", "private_note": telemetry_error},
        },
    }

    monkeypatch.setattr(app.telemetry, "report", lambda *args, **kwargs: report)
    previous_app = http_server.APP
    previous_client = local_ai_mcp.CLIENT
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", port), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = HubClient(tenant="mcp-telemetry-privacy", config_path=str(config), auto_start=False)
    monkeypatch.setattr(local_ai_mcp, "CLIENT", client)
    monkeypatch.setattr(local_ai_mcp.FEATURES, "status", True)

    try:
        tool_result = _mcp_telemetry_call()
        payload = json.loads(tool_result.content[0].text)
        assert tool_result.isError is not True
        assert payload["success"] is True
        assert payload["summary"]["events"] == 7
        assert payload["queue"]["events"] == 2
        assert payload["hotspots"][0]["value_ms"] == 80
        assert payload["detail"]["list_limit"] == 24
        assert payload["decision_grade"]["counts"]["events"] == 7
        assert all(value not in tool_result.content[0].text for value in private_values)
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        http_server.APP = previous_app
        local_ai_mcp.CLIENT = previous_client
        app.close()


def test_mcp_telemetry_error_projection_preserves_retry_semantics(monkeypatch) -> None:
    private_error = "token=TOKEN-SECRET /private/customer/report.json"

    def fake_get(path: str, timeout: float | None = None) -> dict[str, object]:
        if path.startswith("/api/live/status"):
            return {"success": True, "hub_online": True, "runtime_stats": {}}
        return {
            "success": False,
            "status_code": 503,
            "terminal": False,
            "retryable": True,
            "error": private_error,
        }

    monkeypatch.setattr(local_ai_mcp.FEATURES, "status", True)
    monkeypatch.setattr(local_ai_mcp.CLIENT, "get", fake_get)

    tool_result = _mcp_telemetry_call()
    payload = json.loads(tool_result.content[0].text)

    assert payload["success"] is False
    assert payload["status_code"] == 503
    assert payload["terminal"] is False
    assert payload["retryable"] is True
    assert private_error not in tool_result.content[0].text


def test_mcp_telemetry_exception_before_projection_redacts_private_text(monkeypatch) -> None:
    private_values = ("PROMPT-SECRET", "token=TOKEN-SECRET", "/private/customer/report.json")
    private_error = "telemetry transport failed: " + " ".join(private_values)

    def fake_get(path: str, timeout: float | None = None) -> dict[str, object]:
        if path.startswith("/api/live/status"):
            return {"success": True, "hub_online": True, "runtime_stats": {}}
        raise RuntimeError(private_error)

    monkeypatch.setattr(local_ai_mcp.FEATURES, "status", True)
    monkeypatch.setattr(local_ai_mcp.CLIENT, "get", fake_get)

    tool_result = _mcp_telemetry_call()
    payload = json.loads(tool_result.content[0].text)

    assert payload["success"] is False
    assert payload["status_code"] == 500
    assert payload["terminal"] is True
    assert payload["retryable"] is False
    assert all(value not in tool_result.content[0].text for value in private_values)


def test_mcp_telemetry_live_status_exception_redacts_private_text(monkeypatch) -> None:
    private_values = ("PROMPT-SECRET", "token=TOKEN-SECRET", "/private/customer/report.json")
    private_error = "live status transport failed: " + " ".join(private_values)

    def fake_get(path: str, timeout: float | None = None) -> dict[str, object]:
        raise RuntimeError(private_error)

    monkeypatch.setattr(local_ai_mcp.FEATURES, "status", True)
    monkeypatch.setattr(local_ai_mcp.CLIENT, "get", fake_get)

    tool_result = _mcp_telemetry_call()
    payload = json.loads(tool_result.content[0].text)

    assert payload["success"] is False
    assert payload["status_code"] == 500
    assert payload["terminal"] is True
    assert payload["retryable"] is False
    assert all(value not in tool_result.content[0].text for value in private_values)
def test_fallback_used_is_protected_reliability_metadata() -> None:
    assert "fallback_used" in local_ai_mcp._RELIABILITY_PROTECTED_KEYS


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


def test_mcp_delegate_autostarts_owned_daemon_and_preserves_http_payload(tmp_path, monkeypatch, request) -> None:
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
    from local_ai_hub.operational_mode import operational_mode_gate_error as mode_gate_error

    operational_mode = types.ModuleType("local_ai_hub.operational_mode")
    operational_mode.load_operational_mode = lambda _path: SimpleNamespace(mode="active", degraded=False)
    operational_mode.operational_mode_gate_error = mode_gate_error
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
        try:
            lock_snapshot = lock_path.read_text(encoding="utf-8") if lock_path.exists() else "<missing>"
        except OSError:
            # Windows may deny a second handle while the startup owner holds
            # the OS lock. The test only records it; it must not block launch.
            lock_snapshot = "<locked>"
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
    if "local_ai_task" not in local_ai_mcp.mcp._tool_manager._tools:
        local_ai_mcp.mcp.tool()(local_ai_mcp.local_ai_task)
        request.addfinalizer(lambda: local_ai_mcp.mcp._tool_manager._tools.pop("local_ai_task", None))
    monkeypatch.setattr(client_module, "find_listening_pid", lambda _port: False)
    # Isolate client process creation. Patching subprocess.Popen in-place also
    # intercepts unrelated ExternalCodeIntelligence and pip preflight children.
    monkeypatch.setattr(client_module, "subprocess", SimpleNamespace(
        Popen=start_owned_server,
        DEVNULL=subprocess.DEVNULL,
        TimeoutExpired=subprocess.TimeoutExpired,
    ))
    monkeypatch.setattr(client_module, "popen_managed", start_owned_server)
    monkeypatch.setattr(
        client_module, "retain_process_job_in_child",
        lambda process: any(process is child for child in owned_children),
    )
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
        assert not (Path(state_dir) / "service.managed").exists(), "test unexpectedly marks its temporary server as externally managed"
        assert not (Path(state_dir) / "service.disabled").exists(), "test unexpectedly disables autostart"
        assert (Path(client_module.__file__).resolve().parents[2] / "tools" / "service.py").is_file(), "autostart entrypoint missing"
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
        }, "http-default")
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


def _capture_client(monkeypatch, response, *, capture_path_hints=False, capture_accounting=False):
    client = local_ai_mcp.HubClient(tenant="test", auto_start=False)
    calls = []

    def post(path, payload, timeout=None, *, path_hints=None):
        call = (path, payload, timeout)
        calls.append((*call, path_hints) if capture_path_hints else call)
        return response

    monkeypatch.setattr(local_ai_mcp, "CLIENT", client)
    monkeypatch.setattr(client, "post", post)
    reporter = local_ai_mcp._ACCOUNTING_REPORTER
    original_send = reporter._send
    monkeypatch.setattr(reporter, "_send", lambda *_args, **_kwargs: None)
    if capture_accounting:
        monkeypatch.setattr(reporter, "record", lambda event: original_send([event], client=client))
    else:
        monkeypatch.setattr(reporter, "record", lambda _event: None)
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
        phase="edit",
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
        clone_id="clone-1",
        worktree_id="worktree-1",
        branch="feature/context",
        repository_id="repo-1",
        repository_revision="revision-1",
        include_diagnostics=True,
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
        "phase": "edit",
        "focus": ["reuse", "contract"],
        "preload_profile": "default",
        "changed_paths": ["src/app.py"],
        "base": "main",
        "staged": True,
        "since_hash": "rev-1",
        "approval": True,
        "override_reason": "approved test scope",
        "token_budget": 777,
        "clone_id": "clone-1",
        "worktree_id": "worktree-1",
        "branch": "feature/context",
        "repository_id": "repo-1",
        "repository_revision": "revision-1",
        "include_diagnostics": True,
    }
def test_local_ai_repo_context_preserves_legacy_fast_full_payload(monkeypatch) -> None:
    calls = _capture_client(monkeypatch, {"success": True, "context": "legacy"}, capture_accounting=True)

    local_ai_mcp.local_ai_repo(
        action="context", root="C:/repo", query="legacy", mode="full", max_tokens=512,
    )

    pack_calls = [call for call in calls if call[0] == "/api/context/pack"]
    assert pack_calls == [(
        "/api/context/pack",
        {"root": str(Path("C:/repo")), "query": "legacy", "workspace": None, "max_tokens": 512, "mode": "full"},
        600.0,
    )]
    for path, accounting_payload, accounting_timeout in calls:
        if path == "/api/telemetry/tool-accounting":
            assert isinstance(accounting_payload["batch_id"], str)
            assert isinstance(accounting_payload["events"], list)
            assert accounting_timeout == 0.25
        else:
            assert path == "/api/context/pack"


def test_local_ai_repo_non_context_actions_ignore_guard_fields(monkeypatch) -> None:
    calls = _capture_client(monkeypatch, {"success": True, "items": []}, capture_path_hints=True)

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
        limit=24,
        offset=0,
        path_hints=[{"path": "src/auth.py", "purpose": "repository_search", "scope": "repo_search"}],
    )

    api_calls = [call for call in calls if call[0] != "/api/telemetry/tool-accounting"]
    assert api_calls == [(
        "/api/search",
        {"root": str(Path("C:/repo")), "query": "route", "top_k": 12, "enrich": False, "limit": 24, "offset": 0},
        120.0,
        [{"path": "src/auth.py", "purpose": "repository_search", "scope": "repo_search"}],
    )]
    assert all(call[0] in {"/api/search", "/api/telemetry/tool-accounting"} for call in calls)


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
        action="context", root="C:/repo", query="check context", guarded="yes", task_id="task-1",
    )

    assert result["success"] is False
    assert result["status_code"] == 400
    assert result["terminal"] is True
    assert "guarded must be boolean" in result["error"]
    assert calls == []


def test_local_ai_repo_context_enforces_pack_budget_and_identity_types(monkeypatch) -> None:
    calls = _capture_client(monkeypatch, {"success": True}, capture_accounting=True)

    below_minimum = local_ai_mcp.local_ai_repo(
        action="context", root="C:/repo", query="check context", task_id="task-1", phase="review", max_tokens=127,
    )
    mismatched = local_ai_mcp.local_ai_repo(
        action="context", root="C:/repo", query="check context", task_id="task-1", phase="review",
        max_tokens=256, token_budget=512,
    )
    malformed_identity = local_ai_mcp.local_ai_repo(
        action="context", root="C:/repo", query="check context", task_id="task-1", phase="review", branch=42,
    )
    invalid_mode = local_ai_mcp.local_ai_repo(
        action="context", root="C:/repo", query="check context", mode="unsafe",
    )

    assert "128" in below_minimum["error"]
    assert "must match" in mismatched["error"]
    assert "branch must be string" in malformed_identity["error"]
    assert "context mode must be adaptive" in invalid_mode["error"]
    assert len(calls) == 4
    for accounting_path, accounting_payload, accounting_timeout in calls:
        assert accounting_path == "/api/telemetry/tool-accounting"
        assert isinstance(accounting_payload["batch_id"], str)
        assert len(accounting_payload["events"]) == 1
        assert accounting_payload["events"][0]["operation_category"] == "repo"
        assert accounting_timeout == 0.25

def test_local_ai_repo_context_rejects_guard_fields_without_guard_trigger(monkeypatch) -> None:
    calls = _capture_client(monkeypatch, {"success": True})

    result = local_ai_mcp.local_ai_repo(
        action="context", root="C:/repo", query="check context", guarded=False, base="HEAD~1",
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


def test_mcp_artifact_page_rejects_store_slice_larger_than_text_limit(monkeypatch, tmp_path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    artifact_id = store.put("small cap payload " * 100, "tenant-a", "text")
    client = local_ai_mcp.HubClient(tenant="tenant-a", auto_start=False)
    artifact_calls = []

    def get_artifact(path, payload, timeout=None):
        artifact_calls.append((path, payload))
        return store.get(
            payload["artifact_id"],
            offset=payload["offset"],
            max_chars=payload["max_chars"] + 1,
            tenant="tenant-a",
        )

    monkeypatch.setattr(local_ai_mcp, "MAX_TEXT", 128)
    monkeypatch.setattr(local_ai_mcp, "CLIENT", client)
    monkeypatch.setattr(client, "post", get_artifact)
    result = asyncio.run(
        local_ai_mcp.mcp.call_tool(
            "local_ai_artifact",
            {"action": "get", "artifact_id": artifact_id, "offset": 0, "max_chars": 128},
        )
    )
    if isinstance(result, tuple):
        content = result[0][0]
    else:
        assert isinstance(result, list) and result
        content = result[0]
    assert isinstance(content, t.TextContent)
    parsed = json.loads(content.text)
    assert artifact_calls[0][1]["max_chars"] == 128
    assert parsed["success"] is False
    assert parsed["error"] == (
        "Artifact page exceeds configured MCP text limit; "
        "increase compact_max_text_chars and retry."
    )
    assert "text" not in parsed
    assert "next_offset" not in parsed


def test_in_memory_stdio_handles_eight_concurrent_status_calls(monkeypatch) -> None:
    from mcp.shared.memory import create_connected_server_and_client_session

    calls = threading.Barrier(8)
    client = local_ai_mcp.HubClient(tenant="concurrent-stdio-test", auto_start=False)

    def get(_path, timeout=None):
        calls.wait(timeout=4)
        return {"hub_online": True, "scheduler": {}, "observability": {}}

    monkeypatch.setattr(local_ai_mcp, "CLIENT", client)
    monkeypatch.setattr(client, "get", get)
    monkeypatch.setattr(local_ai_mcp._ACCOUNTING_REPORTER, "record", lambda _event: None)
    monkeypatch.setattr(local_ai_mcp.CONTEXT_LEDGER, "record", lambda **_kwargs: None)

    async def call_eight():
        async with create_connected_server_and_client_session(local_ai_mcp.mcp) as session:
            results = await asyncio.wait_for(
                asyncio.gather(*(
                    session.call_tool("local_ai_status", {"detail": "brief"})
                    for _ in range(8)
                )),
                timeout=6,
            )
        return results

    results = asyncio.run(call_eight())
    assert len(results) == 8
    assert all(not result.isError for result in results)
    payloads = [json.loads(result.content[0].text) for result in results]
    assert all(payload["success"] is True for payload in payloads), payloads

def test_registered_mcp_context_uses_actual_http_context_pack(tmp_path, monkeypatch) -> None:
    import hashlib
    import importlib.util
    import json
    import os
    import sys
    import threading
    import urllib.error
    import urllib.request

    from local_ai_hub import http_server
    from local_ai_hub.app import LocalAIApp

    # Candidate uses the owner-pinned T21 source. Root uses its real resolver.
    project_config_path = os.environ.get("LOCAL_AI_HUB_T21_PROJECT_CONFIG_SOURCE")
    if project_config_path:
        project_config_source = Path(project_config_path)
        assert hashlib.sha256(project_config_source.read_bytes()).hexdigest().upper() == (
            "088B8AFDF05A331E51C74925884B2B7984DF8BD5E3AD227C82DBDBEEB19289A1"
        )
        spec = importlib.util.spec_from_file_location("local_ai_hub.project_config", project_config_source)
        assert spec is not None and spec.loader is not None
        project_config = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, spec.name, project_config)
        spec.loader.exec_module(project_config)
    else:
        from local_ai_hub import project_config

    assert callable(project_config.resolve_project_context)

    repo = tmp_path / "repo"
    source = repo / "src" / "app.py"
    source.parent.mkdir(parents=True)
    source.write_text("class AdaptiveContextMarker: pass\n", encoding="utf-8")
    excluded = repo / "vendor" / "private.py"
    excluded.parent.mkdir(parents=True)
    excluded.write_text("class AdaptiveContextMarker: pass\n", encoding="utf-8")
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = 11497\nstate_dir = "{(tmp_path / "state").as_posix()}"\nauto_start_ollama = false\n'
        '\n[hardware]\nprofile = "cpu"\nauto_tune = false\n'
        '\n[prewarm]\nenabled = false\n'
        '\n[preprocessing]\nenabled = false\n'
        '\n[code_intelligence]\nenabled = false\n'
        '\n[agent_state]\nenabled = false\n',
        encoding="utf-8",
    )
    app = LocalAIApp(str(cfg_path))
    original_app = http_server.APP
    original_hybrid = app.services._hybrid_context
    hybrid_calls = []

    def record_hybrid(*args, **kwargs):
        hybrid_calls.append(dict(kwargs))
        return original_hybrid(*args, **kwargs)

    app.services._hybrid_context = record_hybrid
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    transport_calls = []

    def post_actual_route(path, payload, timeout=None):
        transport_calls.append((path, dict(payload)))
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return json.loads(error.read().decode("utf-8"))

    monkeypatch.setattr(local_ai_mcp.CLIENT, "post", post_actual_route)
    try:
        wire = asyncio.run(local_ai_mcp.mcp.call_tool("local_ai_repo", {
            "action": "context", "root": str(repo), "query": "AdaptiveContextMarker",
            "mode": "adaptive", "max_tokens": 512,
            "max_response_tokens": 512,
            "path_hints": [{"path": "/src", "purpose": "context candidate", "scope": "repository"}],
            "exclude_paths": ["vendor"],
        }))
        content = wire[0][0] if isinstance(wire, tuple) else wire[0]
        result = json.loads(content.text)

        assert result["success"] is True, result
        assert result["success"] is True, result
        assert hybrid_calls and hybrid_calls[0]["quality_first"] is True
        assert hybrid_calls[0]["path_hints"] == ({"path": "src", "purpose": "context candidate", "scope": "repository"},)
        assert hybrid_calls[0]["exclude_paths"] == ("vendor",)
        assert transport_calls[0][0] == "/api/context/pack"
        assert transport_calls[0][1]["mode"] == "adaptive"
        assert transport_calls[0][1]["path_hints"] == [{"path": "/src", "purpose": "context candidate", "scope": "repository"}]
        assert transport_calls[0][1]["exclude_paths"] == ["vendor"]
        assert "AdaptiveContextMarker" in result["context"]
        assert all(item.get("path") != "vendor/private.py" for item in result.get("evidence", []))
        assert result["response_budget"]["returned_tokens"] <= 512
        assert json_tokens(result) <= 512
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        http_server.APP = original_app
        app.close()
