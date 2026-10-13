from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest

from local_ai_hub.external_tools import ExternalCodeIntelligence, MCPStdioClient


@pytest.mark.parametrize("state", ["healthy", "available"])
def test_backend_status_preserves_failure_history_after_recovery(tmp_path: Path, monkeypatch, state: str):
    monkeypatch.setattr(ExternalCodeIntelligence, "_startup_preflight", lambda self: None)
    ext = ExternalCodeIntelligence({
        "server": {"state_dir": str(tmp_path / "state")},
        "code_intelligence": {"enabled": True, "serena_enabled": True},
    })
    try:
        ext._serena = sys.executable
        ext._record_failure("serena", RuntimeError("serena indexing exceeded 120s"),
                            operation="index", root="repo", emit_telemetry=False)
        assert ext.status()["serena"]["unavailable_reason"] == "serena indexing exceeded 120s"
        ext._record_success("serena", root="repo")
        ext._backend_health["serena"]["state"] = state
        status = ext.status()["serena"]
        assert status["unavailable_reason"] == ""
        assert status["last_failure"] == "serena indexing exceeded 120s"
        assert status["failure_active"] is False
        assert status["last_successful_operation"]
    finally:
        ext.close()


@pytest.mark.parametrize("condition, expected", [
    ("active_failure", "index failed"),
    ("repair_error", "repair failed"),
    ("repair_blocked", "operator approval needed"),
    ("missing", "managed executable is missing"),
    ("disabled", "disabled by configuration"),
])
def test_backend_status_keeps_current_unavailability(tmp_path: Path, monkeypatch, condition: str, expected: str):
    monkeypatch.setattr(ExternalCodeIntelligence, "_startup_preflight", lambda self: None)
    ext = ExternalCodeIntelligence({
        "server": {"state_dir": str(tmp_path / "state")},
        "code_intelligence": {"enabled": True, "serena_enabled": True},
    })
    try:
        ext._serena = sys.executable
        health = ext._backend_health["serena"]
        health.update(state="healthy", last_failure="index failed", failure_active=False)
        if condition == "active_failure":
            health["failure_active"] = True
        elif condition in {"repair_error", "repair_blocked"}:
            health[condition] = expected
        elif condition == "missing":
            ext._serena = None
        else:
            ext.cfg["serena_enabled"] = False
        assert ext.status()["serena"]["unavailable_reason"] == expected
    finally:
        ext.close()


def test_external_code_intelligence_does_not_manage_codegraph(tmp_path: Path):
    ext = ExternalCodeIntelligence(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "code_intelligence": {"enabled": True, "serena_enabled": True, "codegraph_enabled": True},
        }
    )
    try:
        assert "codegraph" not in ext.status()
        assert not hasattr(ext, "query_codegraph")
        assert ext.reset_sessions("codegraph")["success"] is False
    finally:
        ext.close()


def test_serena_index_uses_upstream_per_file_timeout(monkeypatch, tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "code_intelligence": {"enabled": True, "serena_enabled": True},
    }
    ext = ExternalCodeIntelligence(cfg, telemetry=None)
    captured = []
    monkeypatch.setattr(ext, "_resolve_command", lambda backend: "serena.exe" if backend == "serena" else None)
    ext.refresh_discovery()
    monkeypatch.setattr(
        ext,
        "_run_index",
        lambda backend, argv, project, env=None: captured.append(argv) or {"success": True},
    )

    result = ext.index("serena", str(root))

    assert result["success"] is True
    timeout_index = captured[0].index("--timeout")
    assert captured[0][timeout_index + 1] == "10"


def test_codegraph_stale_config_does_not_register_runtime_backend(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    ext = ExternalCodeIntelligence(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "code_intelligence": {
                "enabled": True,
                "serena_enabled": False,
                "codegraph_enabled": True,
                "codegraph_command": sys.executable,
            },
        },
        telemetry=None,
    )

    assert "codegraph" not in ext.status()
    assert not hasattr(ext, "codegraph_enabled")
    assert not hasattr(ext, "_codegraph")
    expected = {"success": False, "backend": "codegraph", "unavailable": True, "error": "unsupported backend: codegraph"}
    assert ext.index("codegraph", str(root)) == expected
    assert ext.query(str(root), "caller", backend="codegraph") == expected
    assert ext.reset_sessions("codegraph") == {"success": False, "error": "unknown backend: codegraph"}


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















def test_serena_tool_error_is_counted_as_backend_failure(monkeypatch, tmp_path: Path):
    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "code_intelligence": {"enabled": True, "serena_enabled": True},
    }
    ext = ExternalCodeIntelligence(cfg, telemetry=None)
    ext._serena = sys.executable

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
        "code_intelligence": {"enabled": True, "serena_enabled": True},
    }
    ext = ExternalCodeIntelligence(cfg, telemetry=None)
    ext._serena = sys.executable

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
        "code_intelligence": {"enabled": True, "serena_enabled": True, "serena_command": sys.executable},
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








def test_transient_circuit_is_isolated_to_failed_root(tmp_path: Path):
    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "code_intelligence": {"enabled": True, "serena_enabled": True, "serena_command": sys.executable, "failure_threshold": 1},
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
        "code_intelligence": {"enabled": True, "serena_enabled": True, "serena_command": sys.executable, "failure_threshold": 1},
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
        "code_intelligence": {"enabled": True, "serena_enabled": True, "serena_command": sys.executable, "failure_threshold": 1},
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


class _FakeClient:
    instances = []

    def __init__(self, command, *, cwd=None, env=None, **kwargs):
        self.command = command
        self.cwd = cwd
        self.env = env or {}
        self.closed = False
        self.__class__.instances.append(self)

    def close(self):
        self.closed = True


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
        "code_intelligence": {"enabled": True, "serena_enabled": True, "serena_command": sys.executable},
    })
    try:
        result = ext.query_serena(str(root), "search", query="RouteHandler")
    finally:
        ext.close()

    assert result["success"] is True
    assert SerenaClient.calls == [("find_symbol", {"name_path_pattern": "RouteHandler", "relative_path": None, "max_answer_chars": ext.max_output_chars, "depth": 1, "include_body": False, "substring_matching": True})]




def test_managed_context_intelligence_defaults_expose_serena_only():
    from local_ai_hub.config import load_config

    cfg = load_config()
    ext = ExternalCodeIntelligence(cfg)
    try:
        assert cfg["code_intelligence"]["serena_context"] == "codex"
        assert "serena" in ext.status()
        assert "codegraph" not in ext.status()
    finally:
        ext.close()






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
            evicted = ext._prune_sessions_locked()

        # Old project must be evicted
        assert old_client in evicted
        assert old_root not in ext._serena_sessions
        # The 5 projects active within the last hour must remain
        assert len(ext._serena_sessions) == 5
        for i in range(5):
            assert f"/path/to/project_{i}" in ext._serena_sessions
    finally:
        ext.close()

