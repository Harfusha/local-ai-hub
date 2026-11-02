import tomllib
from pathlib import Path

import pytest

from local_ai_hub.config import ConfigError, load_config


def test_mcp_timeout_defaults_are_in_the_consumed_section_and_user_override_wins(tmp_path):
    defaults = Path(__file__).resolve().parents[1] / "src" / "local_ai_hub" / "defaults.toml"
    raw = defaults.read_bytes()
    assert (Path(__file__).resolve().parents[1] / "defaults.toml").read_bytes() == raw
    parsed = tomllib.loads(raw.decode("utf-8"))
    expected = {
        "quick_timeout_seconds": 180,
        "context_timeout_seconds": 600,
        "model_timeout_seconds": 600,
        "long_timeout_seconds": 600,
        "host_tool_timeout_seconds": 900,
    }
    assert {key: parsed["mcp"].get(key) for key in expected} == expected
    assert not set(expected).intersection(parsed["mcp"]["response_budget"])

    (tmp_path / "defaults.toml").write_bytes(raw)
    config = tmp_path / "config.toml"
    config.write_text("[mcp]\nlong_timeout_seconds = 77\n", encoding="utf-8")
    loaded = load_config(str(config), probe_hardware=False)
    assert loaded["mcp"]["long_timeout_seconds"] == 77
    assert loaded["mcp"]["quick_timeout_seconds"] == 180
    assert loaded["mcp"]["host_tool_timeout_seconds"] == 900
    config.write_text("[mcp]\nlong_timeout_seconds = 0\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(str(config), probe_hardware=False)


def test_setup_preserves_existing_http_host_timeout_but_sets_default_for_new_entry(tmp_path):
    from tools import setup

    servers = {"local-ai": {"url": "http://127.0.0.1:11435/mcp"}}
    existing = tmp_path / "existing.toml"
    setup.codex_mcp_merge(existing, servers, False, tool_timeout=900)
    setup.codex_mcp_merge(existing, servers, False, tool_timeout=2400)
    assert tomllib.loads(existing.read_text(encoding="utf-8"))["mcp_servers"]["local-ai"]["tool_timeout_sec"] == 900

    fresh = tmp_path / "fresh.toml"
    setup.codex_mcp_merge(fresh, servers, False, tool_timeout=2400)
    assert tomllib.loads(fresh.read_text(encoding="utf-8"))["mcp_servers"]["local-ai"]["tool_timeout_sec"] == 2400


def test_mcp_timeout_fallbacks_leave_host_margin_and_honor_override(monkeypatch):
    from local_ai_hub import mcp_server

    monkeypatch.setattr(mcp_server, "MCP_CFG", {})
    assert mcp_server._timeout("model") == 600
    assert mcp_server._timeout("long") == 600
    assert mcp_server._timeout("context") == 600
    monkeypatch.setattr(mcp_server, "MCP_CFG", {"long_timeout_seconds": 1200})
    assert mcp_server._timeout("long") == 1200


def test_mcp_review_forwards_bounded_timeout_and_preserves_unknown(monkeypatch, tmp_path):
    from local_ai_hub import mcp_server

    calls = []

    class Client:
        def post(self, endpoint, payload, **kwargs):
            calls.append((endpoint, kwargs.get("timeout")))
            return {"success": False, "error": "request outcome is unknown after a transport failure",
                    "request_id": "req-example", "outcome_unknown": True, "retryable": False, "terminal": True}

    monkeypatch.setattr(mcp_server, "CLIENT", Client())
    monkeypatch.setattr(mcp_server, "MCP_CFG", {})
    result = mcp_server.local_ai_repo(action="review_diff", root=str(tmp_path))
    assert calls == [("/api/review/diff", 600)]
    assert result["outcome_unknown"] is True
    assert result["retryable"] is False
    assert result["request_id"] == "req-example"


def test_review_transport_timeout_reports_unknown_without_duplicate_dispatch(tmp_path):
    import os
    import subprocess
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from local_ai_hub.client import HubClient

    root = tmp_path / "repo"
    root.mkdir()
    template = tmp_path / "empty-template"
    template.mkdir()
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    subprocess.run(["git", "init", "-q", "--template", str(template), str(root)], env=env, check=True)
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            if self.path != "/api/review/diff":
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"success":true}')
                return
            requests.append(self.path)
            started.set()
            release.wait(3)
            finished.set()
            try:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"success":true}')
            except OSError:
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config = tmp_path / "client.toml"
    config.write_text(f'[server]\nport = {server.server_port}\n[security]\napi_token = ""\n', encoding="utf-8")
    client = HubClient(config_path=str(config), auto_start=False)
    try:
        result = client.post("/api/review/diff", {"root": str(root), "task": "test"}, timeout=0.25)
        assert started.is_set()
        assert not finished.is_set()
        assert result["success"] is False
        assert result["outcome_unknown"] is True
        assert result["retryable"] is False
        assert result["request_id"]
        release.set()
        assert finished.wait(3)
        assert requests == ["/api/review/diff"]
    finally:
        release.set()
        client.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_mcp_review_timeout_preserves_unknown_without_duplicate_dispatch(tmp_path):
    import json
    import os
    import subprocess
    import sys
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    import anyio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    root = tmp_path / "repo"
    root.mkdir()
    template = tmp_path / "empty-template"
    template.mkdir()
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith("GIT_") and key not in {"LOCAL_AI_TENANT", "LOCAL_AI_HUB_TOKEN"}}
    subprocess.run(["git", "init", "-q", "--template", str(template), str(root)], env=env, check=True)
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            if self.path != "/api/review/diff":
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"success":true}')
                return
            requests.append(self.path)
            started.set()
            release.wait(6)
            finished.set()
            try:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"success":true}')
            except OSError:
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config = tmp_path / "client.toml"
    config.write_text(
        f'[server]\nport = {server.server_port}\nauto_start_ollama = false\n'
        '[security]\napi_token = ""\n[mcp]\nlong_timeout_seconds = 1\n', encoding="utf-8"
    )
    env.update(LOCAL_AI_CONFIG=str(config), PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"),
               PYTHONDONTWRITEBYTECODE="1")
    params = StdioServerParameters(command=sys.executable, args=["-B", "-m", "local_ai_hub.mcp_server"],
                                   env=env, cwd=str(tmp_path))

    async def call():
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                result = await session.call_tool("local_ai_repo", {"action": "review_diff", "root": str(root)})
                return json.loads(result.content[0].text)

    try:
        result = anyio.run(call)
        assert started.is_set()
        assert not finished.is_set()
        assert result["success"] is False
        assert result["outcome_unknown"] is True
        assert result["retryable"] is False
        assert result["request_id"]
        release.set()
        assert finished.wait(3)
        assert requests == ["/api/review/diff"]
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
