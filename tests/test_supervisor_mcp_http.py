from local_ai_hub.supervisor import Supervisor
import tomllib
import pytest


def test_http_transition_preserves_codex_operational_settings(tmp_path):
    from tools.setup import codex_mcp_merge, MARKER_BEGIN, MARKER_END
    config = tmp_path / "config.toml"
    config.write_text(f'''{MARKER_BEGIN}
[mcp_servers.local-ai]
command = "python"
args = ["-m", "local_ai_hub.mcp_server"]
enabled = false
required = true
startup_timeout_sec = 45
tool_timeout_sec = 123
default_tools_approval_mode = "prompt"
{MARKER_END}
''', encoding="utf-8")
    codex_mcp_merge(config, {"local-ai": {"url": "http://127.0.0.1:11436/mcp"}}, False)
    server = tomllib.loads(config.read_text(encoding="utf-8"))["mcp_servers"]["local-ai"]
    assert server["url"] == "http://127.0.0.1:11436/mcp"
    assert (server["enabled"], server["required"]) == (False, True)
    assert (server["startup_timeout_sec"], server["tool_timeout_sec"]) == (45, 123)
    assert server["default_tools_approval_mode"] == "prompt"
    assert "command" not in server and "args" not in server


def test_supervisor_owns_enabled_mcp_transport(monkeypatch):
    from local_ai_hub import mcp_http

    events = []

    class Transport:
        def __init__(self, *, port):
            events.append(("create", port))
        def start(self):
            events.append("start")
        def stop(self):
            events.append("stop")

    monkeypatch.setattr(mcp_http, "HTTPMCPService", Transport)
    supervisor = Supervisor.__new__(Supervisor)
    supervisor.config = {"mcp_http": {"enabled": True, "port": 11436}}
    supervisor._mcp_http = None
    supervisor._start_mcp_http()
    supervisor._stop_mcp_http()
    assert events == [("create", 11436), "start", "stop"]


def test_supervisor_does_not_start_disabled_transport():
    supervisor = Supervisor.__new__(Supervisor)
    supervisor.config = {}
    supervisor._mcp_http = None
    supervisor._start_mcp_http()
    assert supervisor._mcp_http is None


def test_supervisor_rejects_mismatched_transport_config(monkeypatch, tmp_path):
    from local_ai_hub import mcp_server
    monkeypatch.setattr(mcp_server, "CFG", {"_config_path": str(tmp_path / "other.toml")})
    supervisor = Supervisor.__new__(Supervisor)
    supervisor.config_path = str(tmp_path / "expected.toml")
    supervisor.config = {"mcp_http": {"enabled": True, "port": 11436}}
    supervisor._mcp_http = None
    with pytest.raises(RuntimeError, match="differs"):
        supervisor._start_mcp_http()


def test_supervisor_runs_and_stops_transport(monkeypatch, tmp_path):
    from local_ai_hub import mcp_http, supervisor as module

    events = []

    class Transport:
        def __init__(self, **_kwargs):
            pass
        def start(self):
            events.append("start")
        def stop(self):
            events.append("stop")

    monkeypatch.setattr(mcp_http, "HTTPMCPService", Transport)
    monkeypatch.setattr(module, "process_owner_record", lambda *_args: None)
    monkeypatch.setattr(module.signal, "signal", lambda *_args: None)
    s = Supervisor.__new__(Supervisor)
    s.config = {"mcp_http": {"enabled": True, "port": 11436}}
    s.cfg = {"manage_ollama": False}
    s.state_dir = tmp_path
    s.pid_path = tmp_path / "supervisor.pid"
    s.disabled_path = tmp_path / "service.disabled"
    s._mcp_http = None
    s.stopping = False
    s.child = None
    s.child_ready = True
    s.spawns = s.restarts = 0
    s.crashes = []
    s.acquire = lambda: True
    s.release_lock = lambda: None
    s._start_signal_wakeup = lambda: None
    s._stop_signal_wakeup = lambda: None
    s.log = lambda *_args: None
    s.write_status = lambda *_args, **_kwargs: None
    s.hub_online = lambda: True
    s.terminate_child = lambda: True
    s._wait_interruptibly = lambda _timeout: setattr(s, "stopping", True)
    monkeypatch.setattr(module, "find_listening_pid", lambda _port: None)
    assert s.run() == 0
    assert events == ["start", "stop"]


def test_codex_merge_supports_http_transport_without_secret(tmp_path):
    from tools.setup import codex_mcp_merge

    target = tmp_path / "config.toml"
    codex_mcp_merge(target, {"local-ai": {"url": "http://127.0.0.1:11436/mcp"}}, False)
    entry = tomllib.loads(target.read_text(encoding="utf-8"))["mcp_servers"]["local-ai"]
    assert entry["url"] == "http://127.0.0.1:11436/mcp"
    assert "bearer_token_env_var" not in entry
    assert "command" not in entry and "args" not in entry


def test_codex_entries_select_http_only_when_enabled(monkeypatch, tmp_path):
    from tools import setup

    monkeypatch.setattr(setup, "build_mcp_entries", lambda *_args: {
        "local-ai": {"command": "python", "args": ["-m", "local_ai_hub.mcp_server"]}})
    args = (tmp_path, tmp_path / "python", None)
    assert "command" in setup.build_codex_mcp_entries(*args, {})["local-ai"]
    cfg = {"mcp_http": {"enabled": True, "port": 11436}}
    entry = setup.build_codex_mcp_entries(*args, cfg)["local-ai"]
    assert entry == {"url": "http://127.0.0.1:11436/mcp"}
    with pytest.raises(ValueError):
        setup.build_codex_mcp_entries(*args, {"mcp_http": {"enabled": True, "port": 0}})


def test_configure_agents_fails_before_writes_when_http_mcp_unavailable(monkeypatch, tmp_path):
    from tools import setup

    monkeypatch.setattr(setup, "_http_mcp_ready", lambda _url: False, raising=False)
    monkeypatch.setattr(setup, "build_mcp_entries", lambda *_args: {"local-ai": {"command": "python"}})
    writes = []
    monkeypatch.setattr(setup, "write_all_generated", lambda *_args: writes.append(True))
    monkeypatch.setattr(setup, "install_agent_skills", lambda *_args, **_kwargs: writes.append(True))
    cfg = {"mcp_http": {"enabled": True, "port": 11436}, "agents": {"codex": True}}
    with pytest.raises(RuntimeError, match="not ready"):
        setup.configure_agents(tmp_path, tmp_path / "python", None, cfg)
    assert not writes
