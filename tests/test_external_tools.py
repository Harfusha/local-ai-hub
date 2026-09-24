from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest

from local_ai_hub.external_tools import ExternalCodeIntelligence, MCPStdioClient


def test_serena_index_uses_upstream_per_file_timeout(monkeypatch, tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "code_intelligence": {"enabled": True, "serena_enabled": True, "codegraph_enabled": False},
    }
    ext = ExternalCodeIntelligence(cfg, telemetry=None)
    captured = []
    monkeypatch.setattr(ext, "_resolve_command", lambda backend: "serena.exe" if backend == "serena" else None)
    monkeypatch.setattr(
        ext,
        "_run_index",
        lambda backend, argv, project, env=None: captured.append(argv) or {"success": True},
    )

    result = ext.index("serena", str(root))

    assert result["success"] is True
    timeout_index = captured[0].index("--timeout")
    assert captured[0][timeout_index + 1] == "10"


@pytest.mark.skip(reason="codegraph backend excised from application")
def test_codegraph_query_fails_after_bounded_operation_lock_wait(monkeypatch, tmp_path: Path):
    import threading

    root = tmp_path / "repo"
    root.mkdir()
    ext = ExternalCodeIntelligence(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "code_intelligence": {
                "enabled": True,
                "serena_enabled": False,
                "codegraph_enabled": True,
                "query_timeout_seconds": 0.02,
            },
        },
        telemetry=None,
    )
    monkeypatch.setattr(ext, "_query_codegraph_locked", lambda *_args: {"success": True})
    results = []
    finished = threading.Event()

    def query():
        try:
            results.append(ext.query_codegraph(str(root), "calls", "sample"))
        finally:
            finished.set()

    with ext._backend_operation("codegraph", str(root)):
        worker = threading.Thread(target=query)
        worker.start()
        bounded_wait = finished.wait(0.5)
    worker.join(1)

    assert bounded_wait is True
    assert worker.is_alive() is False
    assert results[0]["success"] is False
    assert "timed out" in results[0]["error"].lower()


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
    if method == "initialize": result={"protocolVersion":"2024-11-05","capabilities":{"tools":{}},"serverInfo":{"name":"fake","version":"1"}}
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


def test_mcp_stdio_soft_timeout_does_not_kill_process(tmp_path: Path):
    from local_ai_hub.external_tools import MCPSoftTimeoutError

    script = _server(tmp_path)
    client = MCPStdioClient([sys.executable, str(script)], startup_timeout=2, call_timeout=2)
    try:
        assert "hang" in client.tool_names()
        proc_before = client._proc
        assert proc_before is not None

        # Soft timeout at 0.1s, hard timeout at 2.0s
        with pytest.raises(MCPSoftTimeoutError):
            client.call_tool("hang", {}, timeout=2.0, soft_timeout=0.1)

        # Process MUST still be alive and not stopped!
        assert client._proc is not None
        assert client._proc.poll() is None
        assert client._proc == proc_before
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


@pytest.mark.skip(reason="codegraph backend excised from application")
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
        assert {x.env["CGC_OUTPUT_FORMAT"] for x in _FakeClient.instances} == {"json"}
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


@pytest.mark.skip(reason="codegraph backend excised from application")
def test_codegraph_relationships_use_supported_query_type(monkeypatch, tmp_path: Path):
    import local_ai_hub.external_tools as mod

    _FakeClient.instances = []
    monkeypatch.setattr(mod, "MCPStdioClient", _FakeClient)
    root = tmp_path / "repo"
    root.mkdir()
    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "code_intelligence": {"enabled": True, "codegraph_enabled": True, "serena_enabled": False, "codegraph_command": sys.executable},
        "tools": {},
    }
    ext = ExternalCodeIntelligence(cfg, telemetry=None)
    try:
        result = ext.query_codegraph(str(root), "relationships", query="ExternalCodeIntelligence")
    finally:
        ext.close()

    assert result["success"] is True
    assert result["result"]["arguments"]["query_type"] == "module_deps"


@pytest.mark.skip(reason="codegraph backend excised from application")
def test_codegraph_calls_alias_maps_to_supported_find_callees(monkeypatch, tmp_path: Path):
    import local_ai_hub.external_tools as mod
    _FakeClient.instances = []
    monkeypatch.setattr(mod, "MCPStdioClient", _FakeClient)
    root = tmp_path / "repo"
    root.mkdir()
    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "code_intelligence": {"enabled": True, "codegraph_enabled": True, "serena_enabled": False, "codegraph_command": sys.executable},
        "tools": {},
    }
    ext = ExternalCodeIntelligence(cfg, telemetry=None)
    try:
        result = ext.query_codegraph(str(root), "calls", query="target")
    finally:
        ext.close()

    assert result["success"] is True
    assert result["result"]["arguments"]["query_type"] == "find_callees"


@pytest.mark.skip(reason="codegraph backend excised from application")
def test_codegraph_nested_query_error_is_not_reported_as_success(monkeypatch, tmp_path: Path):
    import local_ai_hub.external_tools as mod
    _FakeClient.instances = []
    monkeypatch.setattr(mod, "MCPStdioClient", _FakeClient)
    monkeypatch.setattr(
        _FakeClient,
        "call_tool",
        lambda self, name, arguments, timeout=None: {
            "success": True,
            "structured": {
                "query_type": arguments.get("query_type"),
                "results": {"error": "Unknown query type: callees", "supported_types": ["find_callees"]},
            },
        },
    )
    root = tmp_path / "repo"
    root.mkdir()
    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "code_intelligence": {"enabled": True, "codegraph_enabled": True, "serena_enabled": False, "codegraph_command": sys.executable},
        "tools": {},
    }
    ext = ExternalCodeIntelligence(cfg, telemetry=None)
    try:
        result = ext.query_codegraph(str(root), "calls", query="target")
    finally:
        ext.close()

    assert result["success"] is False
    assert "Unknown query type" in result["error"]


def test_fresh_codegraph_index_finds_known_python_callee(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "sample.py"
    source.write_text("def callee():\n    return 1\n\ndef caller():\n    return callee()\n", encoding="utf-8")
    ext = ExternalCodeIntelligence(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "code_intelligence": {"enabled": True, "codegraph_enabled": True, "serena_enabled": False},
        },
        telemetry=None,
    )
    if not ext.backend_available("codegraph"):
        ext.close()
        pytest.skip("CodeGraphContext is not installed")
    try:
        indexed = ext.index("codegraph", str(root))
        result = ext.query_codegraph(str(root), "calls", query="caller", path="sample.py")
    finally:
        ext.close()

    assert indexed["success"] is True
    assert result["success"] is True
    assert "callee" in repr(result)


def test_serena_tool_error_is_counted_as_backend_failure(monkeypatch, tmp_path: Path):
    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "code_intelligence": {"enabled": True, "serena_enabled": True, "codegraph_enabled": False},
    }
    ext = ExternalCodeIntelligence(cfg, telemetry=None)

    class RejectedSerenaClient:
        def tool_names(self):
            return {"search_for_pattern"}

        def call_tool(self, name, arguments, timeout=None):
            return {"success": False, "error": "Serena tool execution failed"}

    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(ext, "_serena_session", lambda _root: RejectedSerenaClient())
    try:
        result = ext.query_serena(str(root), "search", query="needle")
    finally:
        ext.close()

    assert result["success"] is False
    assert ext.query_failures == 1


def test_serena_structured_tool_error_is_counted_as_backend_failure(monkeypatch, tmp_path: Path):
    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "code_intelligence": {"enabled": True, "serena_enabled": True, "codegraph_enabled": False},
    }
    ext = ExternalCodeIntelligence(cfg, telemetry=None)

    class RejectedSerenaClient:
        def tool_names(self):
            return {"search_for_pattern"}

        def call_tool(self, name, arguments, timeout=None):
            return {"success": True, "structured": {"success": False, "error": "Serena index unavailable"}}

    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(ext, "_serena_session", lambda _root: RejectedSerenaClient())
    try:
        result = ext.query_serena(str(root), "search", query="needle")
    finally:
        ext.close()

    assert result["success"] is False
    assert ext.query_failures == 1


@pytest.mark.skip(reason="codegraph backend excised from application")
def test_codegraph_search_structured_error_is_not_reported_as_success(monkeypatch, tmp_path: Path):
    import local_ai_hub.external_tools as mod
    _FakeClient.instances = []
    monkeypatch.setattr(mod, "MCPStdioClient", _FakeClient)
    monkeypatch.setattr(
        _FakeClient,
        "call_tool",
        lambda self, name, arguments, timeout=None: {
            "success": True,
            "structured": {"success": False, "error": "CodeGraph database unavailable"},
        },
    )
    root = tmp_path / "repo"
    root.mkdir()
    ext = ExternalCodeIntelligence(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "code_intelligence": {"enabled": True, "codegraph_enabled": True, "serena_enabled": False, "codegraph_command": sys.executable},
            "tools": {},
        },
        telemetry=None,
    )
    try:
        result = ext.query_codegraph(str(root), "search", query="needle")
    finally:
        ext.close()

    assert result["success"] is False
    assert "CodeGraph database unavailable" in result["error"]


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


@pytest.mark.skip(reason="codegraph backend excised from application")
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


@pytest.mark.skip(reason="codegraph backend excised from application")
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


@pytest.mark.skip(reason="codegraph backend excised from application")
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


def test_index_timeout_is_counted_as_retryable_failure(tmp_path: Path):
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
        assert ext.status()["serena"]["failures"] == 1
        assert ext._allowed("serena", str(root)) is False
    finally:
        ext.close()

    assert len(telemetry.errors) == 1
    assert telemetry.errors[0][1]["retryable"] is True


def test_missing_index_timeout_uses_packaged_slow_device_budget(tmp_path: Path):
    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "code_intelligence": {"enabled": True},
    }
    ext = ExternalCodeIntelligence(cfg, telemetry=None)
    try:
        assert ext.index_timeout == 1200.0
    finally:
        ext.close()


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


def test_serena_search_uses_available_symbol_tool_when_pattern_tool_missing(monkeypatch, tmp_path: Path):
    import local_ai_hub.external_tools as mod

    class SerenaClient(_FakeClient):
        calls = []

        def tool_names(self):
            return {"find_symbol"}

        def call_tool(self, name, arguments, timeout=None):
            self.calls.append((name, arguments))
            if name not in self.tool_names():
                raise RuntimeError(f"MCP tool not available: {name}")
            return {"success": True, "result": {"symbols": []}}

    SerenaClient.instances = []
    SerenaClient.calls = []
    monkeypatch.setattr(mod, "MCPStdioClient", SerenaClient)
    root = tmp_path / "repo"
    root.mkdir()
    ext = ExternalCodeIntelligence({
        "server": {"state_dir": str(tmp_path / "state")},
        "code_intelligence": {"enabled": True, "serena_enabled": True, "codegraph_enabled": False, "serena_command": sys.executable},
    })
    try:
        result = ext.query_serena(str(root), "search", query="RouteHandler")
    finally:
        ext.close()

    assert result["success"] is True
    assert SerenaClient.calls == [("find_symbol", {"name_path_pattern": "RouteHandler", "relative_path": None, "max_answer_chars": ext.max_output_chars, "depth": 1, "include_body": False, "substring_matching": True})]


@pytest.mark.skip(reason="codegraph backend excised from application")
def test_codegraph_index_closes_cached_session_before_rebuilding(monkeypatch, tmp_path: Path):
    import local_ai_hub.external_tools as mod

    _FakeClient.instances = []
    monkeypatch.setattr(mod, "MCPStdioClient", _FakeClient)
    root = tmp_path / "repo"
    root.mkdir()
    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "code_intelligence": {"enabled": True, "serena_enabled": False, "codegraph_enabled": True, "codegraph_command": sys.executable},
    }
    ext = ExternalCodeIntelligence(cfg)
    session = ext._codegraph_client(str(root))
    observed = []

    def index_after_session_release(backend, argv, project, env=None):
        observed.append((session.closed, backend, str(project)))
        return {"success": True}

    monkeypatch.setattr(ext, "_run_index", index_after_session_release)
    try:
        result = ext.index("codegraph", str(root))
    finally:
        ext.close()

    assert result["success"] is True
    assert observed == [(True, "codegraph", str(root))]


def test_managed_context_intelligence_defaults_expose_needed_tools(tmp_path: Path):
    from local_ai_hub.config import load_config

    cfg = load_config()
    ext = ExternalCodeIntelligence(cfg)
    try:
        env = ext._codegraph_env(str(tmp_path))
        assert env["CGC_OUTPUT_FORMAT"] == "json"
        assert cfg["code_intelligence"]["serena_context"] == "codex"
    finally:
        ext.close()


@pytest.mark.skip(reason="codegraph backend excised from application")
def test_codegraph_query_normalizes_windows_repository_filter(monkeypatch, tmp_path: Path):
    import local_ai_hub.external_tools as mod

    class RecordingClient(_FakeClient):
        calls = []

        def call_tool(self, name, arguments, timeout=None):
            self.calls.append((name, arguments))
            return super().call_tool(name, arguments, timeout)

    RecordingClient.instances = []
    RecordingClient.calls = []
    monkeypatch.setattr(mod, "MCPStdioClient", RecordingClient)
    root = tmp_path / "repo"
    root.mkdir()
    ext = ExternalCodeIntelligence({
        "server": {"state_dir": str(tmp_path / "state")},
        "code_intelligence": {"enabled": True, "serena_enabled": False, "codegraph_enabled": True, "codegraph_command": sys.executable},
    })
    try:
        result = ext.query_codegraph(str(root), "search", query="needle")
    finally:
        ext.close()

    assert result["success"] is True
    assert RecordingClient.calls[0][1]["repo_path"] == root.resolve().as_posix()


@pytest.mark.skip(reason="codegraph backend excised from application")
def test_codegraph_query_waits_while_same_repository_is_indexing(monkeypatch, tmp_path: Path):
    import threading
    import local_ai_hub.external_tools as mod

    _FakeClient.instances = []
    monkeypatch.setattr(mod, "MCPStdioClient", _FakeClient)
    root = tmp_path / "repo"
    root.mkdir()
    ext = ExternalCodeIntelligence({
        "server": {"state_dir": str(tmp_path / "state")},
        "code_intelligence": {"enabled": True, "serena_enabled": False, "codegraph_enabled": True, "codegraph_command": sys.executable},
    })
    ext._codegraph_client(str(root))
    indexing = threading.Event()
    release_index = threading.Event()
    query_started = threading.Event()
    query_finished = threading.Event()
    monkeypatch.setattr(ext, "_run_index", lambda *_args, **_kwargs: indexing.set() or release_index.wait(2) or {"success": True})

    index_thread = threading.Thread(target=lambda: ext.index("codegraph", str(root)))
    index_thread.start()
    assert indexing.wait(1)

    def query():
        query_started.set()
        ext.query_codegraph(str(root), "search", query="needle")
        query_finished.set()

    query_thread = threading.Thread(target=query)
    query_thread.start()
    try:
        assert query_started.wait(1)
        assert query_finished.wait(0.1) is False
    finally:
        release_index.set()
        index_thread.join(2)
        query_thread.join(2)
        ext.close()

    assert not index_thread.is_alive()
    assert not query_thread.is_alive()
    assert query_finished.is_set()


def test_code_intelligence_timeouts_and_session_pool_defaults(tmp_path: Path):
    from local_ai_hub.config import load_config, validate_config, ConfigError

    cfg = load_config()
    intel = cfg.get("code_intelligence", {})
    assert intel.get("startup_timeout_seconds") == 60
    assert intel.get("query_timeout_seconds") == 60
    assert intel.get("soft_timeout_seconds") == 4.0
    assert intel.get("session_idle_ttl_seconds") == 3600
    assert intel.get("max_sessions_per_backend") == 16

    # Test validation of soft_timeout_seconds
    valid_cfg = {"code_intelligence": {"soft_timeout_seconds": 5.0}}
    validate_config(valid_cfg)

    with pytest.raises(ConfigError):
        validate_config({"code_intelligence": {"soft_timeout_seconds": -1}})


def test_query_serena_soft_timeout_fallback_to_code_index(tmp_path: Path):
    from local_ai_hub.external_tools import ExternalCodeIntelligence, MCPSoftTimeoutError

    root = tmp_path / "repo"
    root.mkdir()

    class FakeCodeIndex:
        def find_symbol(self, root, query, **kwargs):
            return {"success": True, "symbols": [{"name": query, "path": "src/main.py", "line": 10}]}
        def search(self, root, query, **kwargs):
            return {"success": True, "symbols": [{"name": query, "path": "src/main.py", "line": 10}]}

    fake_ci = FakeCodeIndex()
    ext = ExternalCodeIntelligence({
        "server": {"state_dir": str(tmp_path / "state")},
        "code_intelligence": {"enabled": True, "serena_enabled": True, "soft_timeout_seconds": 0.05},
    }, code_index=fake_ci)

    class HangingClient:
        def call_tool(self, name, args, *, timeout=None, soft_timeout=None):
            raise MCPSoftTimeoutError("soft timeout")

    ext._serena_sessions[str(root.resolve())] = HangingClient()
    ext._session_access["serena"][str(root.resolve())] = 1000.0
    ext._serena = "serena"

    res = ext.query(str(root), "my_function", backend="serena", action="find_symbol")
    assert res["success"] is True
    assert res["backend"] == "code_index"
    assert res["fallback_used"] is True
    assert res["degraded_reason"] == "serena_soft_timeout"
    assert res["symbols"][0]["name"] == "my_function"


def test_serena_session_retained_for_one_hour(tmp_path: Path):
    from local_ai_hub.external_tools import ExternalCodeIntelligence
    import time

    ext = ExternalCodeIntelligence({
        "server": {"state_dir": str(tmp_path / "state")},
        "code_intelligence": {"enabled": True, "serena_enabled": True},
    })
    try:
        assert ext.session_idle_ttl == 3600.0
        assert ext.max_sessions == 16

        class DummyClient:
            def __init__(self):
                self.closed = False
            def close(self):
                self.closed = True

        now = time.monotonic()
        # Add 5 project sessions touched recently (within 1 hour)
        for i in range(5):
            client = DummyClient()
            root_path = f"/path/to/project_{i}"
            ext._serena_sessions[root_path] = client
            ext._session_access["serena"][root_path] = now - (i * 600)  # 0m, 10m, 20m, 30m, 40m ago

        # Add 1 project session touched 65 minutes ago (3900s)
        old_client = DummyClient()
        old_root = "/path/to/old_project"
        ext._serena_sessions[old_root] = old_client
        ext._session_access["serena"][old_root] = now - 3900

        with ext._lock:
            evicted = ext._prune_sessions_locked("serena")

        # Old project must be evicted
        assert old_client in evicted
        assert old_root not in ext._serena_sessions
        # The 5 projects active within the last hour must remain
        assert len(ext._serena_sessions) == 5
        for i in range(5):
            assert f"/path/to/project_{i}" in ext._serena_sessions
    finally:
        ext.close()



