from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest

from local_ai_hub.external_tools import ExternalCodeIntelligence, MCPStdioClient


FAKE_MCP = r'''
import json, sys, time
TOOLS = [
 {"name":"echo","inputSchema":{"type":"object","properties":{"value":{"type":"string"}},"required":["value"]}},
 {"name":"hang","inputSchema":{"type":"object","properties":{}}},
]
for raw in sys.stdin:
    try: msg=json.loads(raw)
    except Exception: continue
    if "id" not in msg: continue
    mid=msg["id"]; method=msg.get("method")
    if method == "initialize": result={"protocolVersion":"2025-11-25","capabilities":{"tools":{}},"serverInfo":{"name":"fake","version":"1"}}
    elif method == "tools/list": result={"tools":TOOLS}
    elif method == "tools/call":
        params=msg.get("params") or {}; name=params.get("name"); args=params.get("arguments") or {}
        if name == "hang": time.sleep(2)
        result={"content":[{"type":"text","text":json.dumps({"name":name,"args":args})}],"isError":False}
    else: result={}
    sys.stdout.write(json.dumps({"jsonrpc":"2.0","id":mid,"result":result})+"\n"); sys.stdout.flush()
'''


def _server(tmp_path: Path) -> Path:
    p = tmp_path / "fake_mcp.py"
    p.write_text(textwrap.dedent(FAKE_MCP), encoding="utf-8")
    return p


def test_stdio_mcp_filters_args_and_recovers_after_timeout(tmp_path: Path):
    script = _server(tmp_path)
    client = MCPStdioClient([sys.executable, str(script)], startup_timeout=2, call_timeout=1)
    try:
        assert "echo" in client.tool_names()
        response = client.call_tool("echo", {"value": "ok", "ignored": 7})
        assert response["success"] is True
        assert response["result"]["args"] == {"value": "ok"}
        with pytest.raises(TimeoutError):
            client.call_tool("hang", {}, timeout=0.1)
        client.reset()
        response = client.call_tool("echo", {"value": "again"})
        assert response["result"]["args"] == {"value": "again"}
    finally:
        client.close()


class _FakeClient:
    instances = []
    def __init__(self, command, *, cwd=None, env=None, **kwargs):
        self.command = command; self.cwd = cwd; self.env = env or {}; self.closed = False
        self.__class__.instances.append(self)
    def call_tool(self, name, arguments, timeout=None):
        return {"success": True, "result": {"tool": name, "arguments": arguments}}
    def tool_names(self):
        return {"find_code", "analyze_code_relationships", "find_dead_code", "calculate_cyclomatic_complexity", "get_repository_stats"}
    def close(self): self.closed = True
    def reset(self): self.closed = True


def test_codegraph_sessions_are_isolated_per_project(monkeypatch, tmp_path: Path):
    import local_ai_hub.external_tools as mod
    _FakeClient.instances = []
    monkeypatch.setattr(mod, "MCPStdioClient", _FakeClient)
    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "code_intelligence": {"enabled": True, "codegraph_enabled": True, "serena_enabled": False, "codegraph_command": sys.executable},
        "tools": {},
    }
    ext = ExternalCodeIntelligence(cfg, telemetry=None)
    roots = [tmp_path / "a", tmp_path / "b"]
    for root in roots: root.mkdir()
    try:
        for root in roots:
            out = ext.query_codegraph(str(root), "search", query="needle")
            assert out["success"] is True
        assert len(_FakeClient.instances) == 2
        assert {Path(x.cwd) for x in _FakeClient.instances} == set(roots)
        assert {Path(x.env["CGC_ALLOWED_ROOTS"]) for x in _FakeClient.instances} == set(roots)
        assert {x.env["CGC_OUTPUT_FORMAT"] for x in _FakeClient.instances} == {"gcf"}
        assert {x.env["PYTHONIOENCODING"] for x in _FakeClient.instances} == {"utf-8"}
        assert {x.env["PYTHONUTF8"] for x in _FakeClient.instances} == {"1"}
        db_paths = {Path(x.env["CGC_RUNTIME_DB_PATH"]) for x in _FakeClient.instances}
        assert len(db_paths) == 2
        assert all(path.parent == tmp_path / "state" / "codegraph" for path in db_paths)
        assert (tmp_path / "state" / "codegraph").is_dir()
        assert {x.env["CGC_RUNTIME_DB_TYPE"] for x in _FakeClient.instances} == {"kuzudb"}
        ext.query_codegraph(str(roots[0]), "search", query="again")
        complexity = ext.query_codegraph(str(roots[0]), "complexity", query="main", path="src/main.py")
        assert complexity["success"] is True
        assert len(_FakeClient.instances) == 2
    finally:
        ext.close()
    assert all(x.closed for x in _FakeClient.instances)


def test_serena_index_supplies_noninteractive_dominant_language(monkeypatch, tmp_path: Path):
    import local_ai_hub.external_tools as mod

    root = tmp_path / "repo"
    root.mkdir()
    (root / ".gitignore").write_text("Woodbound/Library/\nWoodbound/Temp/\n", encoding="utf-8")
    for index in range(3):
        (root / f"module_{index}.py").write_text("value = 1\n", encoding="utf-8")
    (root / "README.md").write_text("docs\n", encoding="utf-8")
    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "code_intelligence": {"enabled": True, "serena_enabled": True, "codegraph_enabled": False, "serena_command": sys.executable},
    }
    ext = ExternalCodeIntelligence(cfg, telemetry=None)
    captured = []

    def fake_run(backend, argv, project, env=None):
        captured.append((backend, argv, project, env))
        return {"success": True, "backend": backend}

    monkeypatch.setattr(ext, "_run_index", fake_run)
    try:
        result = ext.index("serena", str(root))
    finally:
        ext.close()

    assert result["success"] is True
    assert captured[0][0] == "serena"
    assert captured[0][1][captured[0][1].index("--language") + 1] == "python"


def test_codegraph_index_rediscoveries_command_before_reporting_unavailable(monkeypatch, tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "code_intelligence": {"enabled": True, "serena_enabled": False, "codegraph_enabled": True},
    }
    ext = ExternalCodeIntelligence(cfg, telemetry=None)
    captured = []
    monkeypatch.setattr(ext, "_resolve_command", lambda backend: "cgc.exe" if backend == "codegraph" else None)
    monkeypatch.setattr(ext, "_run_index", lambda backend, argv, project, env=None: captured.append((backend, argv, env)) or {"success": True})
    try:
        ext._codegraph = None
        result = ext.index("codegraph", str(root))
    finally:
        ext.close()

    assert result["success"] is True
    assert captured and captured[0][0] == "codegraph"


def test_codegraph_env_adds_git_ignored_directories(monkeypatch, tmp_path: Path):
    import local_ai_hub.external_tools as mod

    root = tmp_path / "repo"
    root.mkdir()
    (root / ".gitignore").write_text("Woodbound/Library/\nWoodbound/Temp/\n", encoding="utf-8")
    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "code_intelligence": {"enabled": True, "serena_enabled": False, "codegraph_enabled": True, "codegraph_command": sys.executable},
    }
    ext = ExternalCodeIntelligence(cfg, telemetry=None)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if "rev-parse" in argv:
            return type("Completed", (), {"returncode": 0, "stdout": str(root), "stderr": ""})()
        return type("Completed", (), {"returncode": 0, "stdout": b"Woodbound/Library/\x00Woodbound/Temp/\x00", "stderr": b""})()

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    try:
        env = ext._codegraph_env(str(root))
    finally:
        ext.close()

    assert "Library" in env["IGNORE_DIRS"]
    assert "Temp" in env["IGNORE_DIRS"]
    assert env["MAX_FILE_SIZE_MB"] == "5"
    assert any("ls-files" in call for call in calls)


def test_broken_codegraph_installation_degrades_once_without_future_retries(tmp_path: Path):
    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "code_intelligence": {"enabled": True, "serena_enabled": False, "codegraph_enabled": True, "codegraph_command": sys.executable},
    }
    ext = ExternalCodeIntelligence(cfg, telemetry=None)
    try:
        ext._record_failure("codegraph", RuntimeError("ModuleNotFoundError: No module named 'codegraphcontext'"), operation="index")
        status = ext.status()["codegraph"]
    finally:
        ext.close()

    assert status["enabled"] is False
    assert status["installed"] is False
    assert status["unavailable_reason"] == "codegraph installation is incomplete"


def test_transient_circuit_is_isolated_to_failed_root(tmp_path: Path):
    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "code_intelligence": {"enabled": True, "serena_enabled": True, "codegraph_enabled": False, "serena_command": sys.executable, "failure_threshold": 1},
    }
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir(); second.mkdir()
    ext = ExternalCodeIntelligence(cfg, telemetry=None)
    try:
        ext._record_failure("serena", TimeoutError("index exceeded"), operation="index", root=str(first))
        assert ext._allowed("serena", str(first)) is False
        assert ext._allowed("serena", str(second)) is True
    finally:
        ext.close()


def test_revision_scoped_index_timeout_is_skipped_without_failure_telemetry(tmp_path: Path):
    class Telemetry:
        def __init__(self):
            self.errors = []
            self.system = []

        def record_error(self, *args, **kwargs):
            self.errors.append((args, kwargs))

        def record_system(self, *args, **kwargs):
            self.system.append((args, kwargs))

    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "code_intelligence": {"enabled": True, "serena_enabled": True, "codegraph_enabled": False, "serena_command": sys.executable, "failure_threshold": 1},
    }
    root = tmp_path / "repo"
    root.mkdir()
    telemetry = Telemetry()
    ext = ExternalCodeIntelligence(cfg, telemetry=telemetry)
    try:
        ext._record_failure("serena", TimeoutError("serena indexing exceeded 30 seconds"), operation="index", root=str(root))
        assert ext.status()["serena"]["failures"] == 0
        assert ext._allowed("serena", str(root)) is True
    finally:
        ext.close()

    assert telemetry.errors == []
    assert telemetry.system == [(("code_intelligence:serena:index_skipped",), {"success": True, "degraded": True})]


def test_root_session_reset_clears_that_roots_circuit(tmp_path: Path):
    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "code_intelligence": {"enabled": True, "serena_enabled": True, "codegraph_enabled": False, "serena_command": sys.executable, "failure_threshold": 1},
    }
    root = tmp_path / "repo"
    root.mkdir()
    ext = ExternalCodeIntelligence(cfg, telemetry=None)
    try:
        ext._record_failure("serena", TimeoutError("startup timed out"), operation="search", root=str(root))
        assert ext._allowed("serena", str(root)) is False
        assert ext.reset_sessions("serena", str(root))["success"] is True
        assert ext._allowed("serena", str(root)) is True
    finally:
        ext.close()
