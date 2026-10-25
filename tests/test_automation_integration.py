from pathlib import Path
from types import SimpleNamespace
import tomllib

import pytest

from local_ai_hub import mcp_server
from local_ai_hub.config import validate_config, ConfigError
from local_ai_hub.operation_contracts import operation_actions, operation_input_schema, validate_operation_arguments


def test_automation_is_a_closed_explicit_existing_tool_action():
    assert "automation" in operation_actions("local_ai_task")
    schema = operation_input_schema("local_ai_task", "automation")
    assert schema["properties"]["automation"]["additionalProperties"] is False
    assert validate_operation_arguments("local_ai_task", "automation", {"root": "C:/repo", "task_id": "t", "automation": {"op": "open", "mode": "isolated", "url": "http://localhost/"}}) is None
    assert validate_operation_arguments("local_ai_task", "automation", {"automation": {"op": "open", "shell": "evil"}})


def test_mcp_dispatches_without_local_model_execution(monkeypatch):
    calls = []
    monkeypatch.setattr(mcp_server, "load_operational_mode", lambda *_args, **_kwargs: SimpleNamespace(mode="active", revision=0))
    monkeypatch.setattr(mcp_server, "operational_mode_gate_error", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mcp_server, "_compact", lambda result, *args, **kwargs: result)
    monkeypatch.setattr(mcp_server.CLIENT, "post", lambda path, payload, **kwargs: calls.append((path, payload, kwargs)) or {"success": True, "automation": {"session_id": "s", "session_key": "k"}})
    result = mcp_server.local_ai_task(action="automation", root="C:/repo", task_id="t", automation={"op": "open", "mode": "isolated", "url": "http://localhost/"})
    assert result["automation"]["session_key"] == "k"
    assert calls[0][0] == "/api/task/automation"
    assert calls[0][1]["task_id"] == "t"


@pytest.mark.parametrize("value", [{"enabled": "yes"}, {"allowed_targets": ["http://*.local/"]},
                                  {"max_sessions": True}, {"timeout_seconds": 1000},
                                  {"playwright_command": ["npx.cmd", "anything"]}, {"tenant": "x"}])
def test_invalid_automation_configuration_rejects(value):
    with pytest.raises((ConfigError, ValueError)):
        validate_config({"automation": value})


def test_source_and_packaged_defaults_match_and_deny_access():
    root = Path(__file__).parents[1]
    source = tomllib.loads((root / "src/local_ai_hub/defaults.toml").read_text(encoding="utf-8"))
    packaged = tomllib.loads((root / "defaults.toml").read_text(encoding="utf-8"))
    assert source["automation"] == packaged["automation"]
    assert source["automation"]["enabled"] is False
    assert source["automation"]["allowed_targets"] == []


def test_compact_projection_preserves_session_capability_and_result():
    result = mcp_server._compact({"success": True, "automation": {"session_id": "s", "session_key": "k", "text": "fixture"}}, "general", extra_fields=["automation"])
    assert result["automation"] == {"session_id": "s", "session_key": "k", "text": "fixture"}


@pytest.mark.parametrize("authorized,active,expected", [(False, True, 403), (True, False, 409), (True, True, 200)])
def test_http_handler_enforces_write_authorization_and_task_state(monkeypatch, tmp_path, authorized, active, expected):
    from local_ai_hub import http_server
    calls, responses = [], []
    broker = SimpleNamespace(execute=lambda **kwargs: calls.append(kwargs) or {"success": True, "automation": {"closed": True}})
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(automation=broker))
    handler = SimpleNamespace(
        _authorized=lambda **kwargs: authorized and kwargs == {"permission": "write"},
        _bind_task_payload=lambda payload: True,
        _request_task=lambda task, root: SimpleNamespace(status="running" if active else "completed"),
        _send=lambda status, response: responses.append((status, response)),
    )
    http_server.Handler._handle_task_automation(handler, {"root": str(tmp_path), "task_id": "t", "automation": {"op": "open", "mode": "isolated", "url": "http://localhost/"}})
    assert responses[-1][0] == expected
    assert bool(calls) is (authorized and active)


def test_http_foreign_task_and_root_never_reach_backend(monkeypatch, tmp_path):
    from local_ai_hub import http_server
    calls = []
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(automation=SimpleNamespace(execute=lambda **kwargs: calls.append(kwargs))))
    handler = SimpleNamespace(_authorized=lambda **kwargs: True, _bind_task_payload=lambda payload: True,
                              _request_task=lambda task, root: None, _send=lambda *_args: None)
    http_server.Handler._handle_task_automation(handler, {"root": str(tmp_path), "task_id": "foreign", "automation": {"op": "open"}})
    assert not calls
    handler._request_task = lambda *_args: pytest.fail("root must reject first")
    handler._bind_task_payload = lambda payload: False
    http_server.Handler._handle_task_automation(handler, {"root": str(tmp_path), "task_id": "foreign", "automation": {"op": "open"}})


def test_automation_browser_script_is_packaged():
    root = Path(__file__).parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert "automation_browser.js" in project["tool"]["setuptools"]["package-data"]["local_ai_hub"]


def test_actual_http_task_root_binding_and_session_lifecycle(tmp_path):
    import json
    import threading
    import urllib.request
    import urllib.error
    from local_ai_hub.app import LocalAIApp
    from local_ai_hub import http_server
    from local_ai_hub.automation import AutomationBroker

    config = tmp_path / "config.toml"
    state = tmp_path / "state"
    root = tmp_path / "repo"
    root.mkdir()
    config.write_text(f'[server]\nstate_dir="{state.as_posix()}"\n[security]\napi_token="automation-test-token"\nallowed_roots=["{tmp_path.as_posix()}"]\n[agent_state]\nenabled=true\n', encoding="utf-8")
    app = LocalAIApp(str(config))
    calls = []
    class Backend:
        def execute(self, request, timeout):
            calls.append(request)
            return {"url": "http://localhost:8765/", "text": "actual HTTP fixture"}
        def close(self):
            pass
    app.automation = AutomationBroker({"enabled": True, "allowed_targets": ["http://localhost:8765/"]}, backend_factory=lambda *_args: Backend())
    previous = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    def post(path, payload, token="automation-test-token"):
        request = urllib.request.Request(f"http://127.0.0.1:{server.server_address[1]}{path}", data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "X-LocalAI-Token": token}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            with exc:
                return json.load(exc)
    try:
        created = post("/api/agent-state/tasks", {"action": "create", "root": str(root), "contract": {"goal": "HTTP automation fixture", "acceptance_criteria": ["owned fixture"]}})
        assert created["success"], created
        task = created["task"]["task_id"]
        base = {"root": str(root), "task_id": task}
        opened = post("/api/task/automation", {**base, "automation": {"op": "open", "mode": "isolated", "url": "http://localhost:8765/"}})
        assert opened["success"], opened
        session = opened["automation"]
        operation = {"op": "act", "session_id": session["session_id"], "session_key": session["session_key"], "request_id": "actual-http-snapshot", "command": "snapshot"}
        denied = post("/api/task/automation", {**base, "automation": operation}, token="wrong")
        assert denied["success"] is False
        assert not calls
        foreign = tmp_path / "foreign"
        foreign.mkdir()
        denied = post("/api/task/automation", {**base, "root": str(foreign), "automation": operation})
        assert denied["success"] is False
        assert not calls
        result = post("/api/task/automation", {**base, "automation": operation})
        assert result["automation"]["text"] == "actual HTTP fixture"
        assert len(calls) == 1
        closed = post("/api/task/automation", {**base, "automation": {"op": "close", "session_id": session["session_id"], "session_key": session["session_key"]}})
        assert closed["success"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)
        app.close()
        http_server.APP = previous
