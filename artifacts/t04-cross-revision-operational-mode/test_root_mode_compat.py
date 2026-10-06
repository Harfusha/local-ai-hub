"""One-off cross-revision check; reads root module, writes only pytest tmp_path."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import mcp.types as mcp_types
import pytest

from local_ai_hub import client as client_module
from local_ai_hub import http_server, mcp_server
from local_ai_hub.app import LocalAIApp
from local_ai_hub.external_tools import ExternalCodeIntelligence


ROOT_MODE = Path(r"C:\Users\Adam\.local-ai-hub\src\local_ai_hub\operational_mode.py")
ROOT_MODE_SHA256 = "19EDE1E62C79E160D41F47FE5BB05F0EA3048988E4A9E00C1DA8C03353667F85"
T04_CLIENT_SHA256 = "8EED9005A1374F48CD6FDC4738FE42985AB00FF2E20EDEFDB1F9D06E003759B5"


def _config(path: Path, port: int, state: Path) -> Path:
    result = path / f"hub-{port}.toml"
    result.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = {port}\nstate_dir = "{state.as_posix()}"\n'
        '[client]\nstartup_wait_seconds = 3\nstartup_poll_seconds = 0.03\nhealth_timeout_seconds = 0.2\n',
        encoding="utf-8",
    )
    return result


def test_t04_client_gate_and_http_route_with_actual_root_operational_mode(tmp_path, monkeypatch):
    assert hashlib.sha256(ROOT_MODE.read_bytes()).hexdigest().upper() == ROOT_MODE_SHA256
    assert hashlib.sha256(Path(client_module.__file__).read_bytes()).hexdigest().upper() == T04_CLIENT_SHA256

    spec = importlib.util.spec_from_file_location("local_ai_hub.operational_mode", ROOT_MODE)
    assert spec is not None and spec.loader is not None
    mode_module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, mode_module)
    spec.loader.exec_module(mode_module)

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    active_state = tmp_path / "active-state"
    config_path = _config(tmp_path, port, active_state)
    received: list[tuple[dict[str, object], str]] = []
    generated: list[str] = []
    server_box: dict[str, object] = {}
    children: list[object] = []
    serve_errors: list[BaseException] = []

    def fake_generate(model, prompt, system, max_tokens, temperature, tenant, source, priority, **kwargs):
        generated.append(prompt)
        return {"success": True, "model": model, "text": f"Root-mode HTTP result {len(generated)}"}

    def start_http_child(*_args, **_kwargs):
        app = LocalAIApp(str(config_path))
        app.services._generate = fake_generate
        original_delegate = app.services.delegate

        def capture_delegate(payload, tenant):
            received.append((dict(payload), tenant))
            return original_delegate(payload, tenant)

        app.services.delegate = capture_delegate
        monkeypatch.setattr(http_server, "APP", app)
        server = http_server.LocalAIHTTPServer(("127.0.0.1", port), http_server.Handler)

        def serve():
            try:
                server.serve_forever()
            except BaseException as exc:
                serve_errors.append(exc)

        thread = threading.Thread(target=serve, daemon=True)
        server_box.update(app=app, server=server, thread=thread)
        thread.start()
        child = SimpleNamespace(poll=lambda: None)
        children.append(child)
        return child

    # Capture only HubClient startup. App dependencies keep their real subprocess module.
    monkeypatch.setattr(client_module, "subprocess", SimpleNamespace(
        Popen=start_http_child, DEVNULL=subprocess.DEVNULL, TimeoutExpired=subprocess.TimeoutExpired,
    ))
    monkeypatch.setattr(client_module, "find_listening_pid", lambda _port: False)
    monkeypatch.setattr(client_module, "_retain_detached_child", lambda _child: None)
    monkeypatch.setattr(ExternalCodeIntelligence, "_startup_preflight", lambda _self: None)
    monkeypatch.setattr(mcp_server.FEATURES, "tasks", True)
    monkeypatch.setattr(mcp_server.FEATURES, "has_any_model", lambda: True)

    client = client_module.HubClient(tenant="root-mode-test", config_path=str(config_path), auto_start=True)
    monkeypatch.setattr(mcp_server, "CLIENT", client)
    tasks = ("Summarize root-mode input", "Root-mode source facts")

    async def dispatch():
        return await mcp_server.mcp.call_tool("local_ai_task", {
            "action": "delegate", "task": tasks[0], "context": tasks[1],
            "complexity": "low", "max_tokens": 128, "delivery": "sync",
            "latency_budget_ms": 1500,
        })

    try:
        results = asyncio.run(dispatch())
    finally:
        client.close()
        server = server_box.get("server")
        if server is not None:
            thread = server_box["thread"]
            assert threading.current_thread() is not thread
            deadline = time.monotonic() + 5
            while server.concurrency_stats()["active"] and time.monotonic() < deadline:
                time.sleep(0.01)
            assert server.concurrency_stats()["active"] == 0
            shutdown = threading.Thread(target=server.shutdown, daemon=True)
            shutdown.start()
            shutdown.join(timeout=5)
            if shutdown.is_alive():
                server.server_close()
                shutdown.join(timeout=5)
            assert not shutdown.is_alive()
            server.server_close()
            thread.join(timeout=5)
            assert not thread.is_alive()
            assert serve_errors == []
        app = server_box.get("app")
        if app is not None:
            app.close()

    content = results[0][0] if isinstance(results, tuple) else results[0]
    assert isinstance(content, mcp_types.TextContent)
    response = json.loads(content.text)
    assert response["success"] is True
    assert response["text"] == "Root-mode HTTP result 1"
    assert len(children) == 1
    assert len(generated) == 1
    assert tasks[0] in generated[0]
    assert tasks[1] in generated[0]
    assert received == [({
        "task": tasks[0], "context": tasks[1], "complexity": "low", "max_tokens": 160,
        "delivery": "sync", "latency_budget_ms": 1500.0, "model": "", "operation": "delegate",
        "changed_paths": [], "repository_revision": "", "evidence_ids": [],
    }, "root-mode-test")]
    assert not (active_state / "operational-mode.json").exists()

    blocked_state = tmp_path / "maintenance-state"
    mode_module.set_operational_mode(blocked_state, "maintenance")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        blocked_port = probe.getsockname()[1]
    blocked_config = _config(tmp_path, blocked_port, blocked_state)
    blocked_client = client_module.HubClient(tenant="root-mode-blocked", config_path=str(blocked_config), auto_start=True)
    assert blocked_client.ensure_server() is False
    assert len(children) == 1
    assert (blocked_state / "operational_mode.json").exists()
    blocked_client.close()
