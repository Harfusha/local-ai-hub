import threading
import json
import os
import tomllib

import pytest

from local_ai_hub.opencode_sandbox_session import SandboxSession


def test_client_port_comes_from_os_ephemeral_allocation(monkeypatch):
    import local_ai_hub.opencode_sandbox_session as module
    calls = []
    class Probe:
        def __enter__(self): return self
        def __exit__(self, *_args): calls.append("closed")
        def setsockopt(self, *args): calls.append(("option", *args))
        def bind(self, address): calls.append(("bind", address))
        def getsockname(self): return ("127.0.0.1", 42345)
    monkeypatch.setattr(module.socket, "socket", lambda *_args: Probe())
    assert module._select_client_port() == 42345
    assert ("bind", ("127.0.0.1", 0)) in calls and calls[-1] == "closed"


def test_session_keeps_services_until_run_finishes_and_uses_fresh_secrets(monkeypatch, tmp_path):
    import local_ai_hub.opencode_sandbox_session as module
    events = []
    started, release = threading.Event(), threading.Event()
    captured = {}

    class Profile:
        sid = "sid"
        def __enter__(self): events.append("profile-open"); return self
        def __exit__(self, *_args): events.append("profile-close")
    class Router:
        port = 123
        def __init__(self, *_args): pass
        def __enter__(self): events.append("router-open"); return self
        def __exit__(self, *_args): events.append("router-close")
        def register_client_port(self, port): captured["registered_port"] = port
    class Service:
        def __init__(self, sid, secret, target):
            assert sid == "sid" and len(secret) == 32
            self.name = "pipe-" + str(len(events))
        def __enter__(self): events.append(self.name + "-open"); return self
        def __exit__(self, *_args): events.append(self.name + "-close")
    def run(profile, argv, **kwargs):
        captured.update(kwargs["env"])
        started.set()
        assert release.wait(3)
        return 0

    monkeypatch.setattr(module, "AppContainerProfile", Profile)
    monkeypatch.setattr(module, "LocalRouter", Router)
    monkeypatch.setattr(module, "PipeService", Service)
    monkeypatch.setattr(module, "StopService", Service)
    monkeypatch.setattr(module, "run_in_appcontainer", run)
    session = SandboxSession(1, 2).__enter__()
    staged = tmp_path / "stage"
    cfg = {"server": {"port": 1111}, "security": {"api_token": "owner-super-secret"},
           "commands": {"enabled": True, "password": "private-value"}}
    runtime, client_toml = session.build_runtime_config(cfg, install_dir=staged, hub_python=staged / "python.exe",
                                                         client_config=staged / "client.toml", model="model-a")
    port = session.client_port
    assert runtime["providers"]["local-hub"]["settings"]["baseURL"] == f"http://127.0.0.1:{port}/v1"
    assert runtime["plugins"][0]["options"]["hubURL"] == f"http://127.0.0.1:{port}"
    assert runtime["mcp"]["servers"] == {}
    assert runtime["plugins"][1]["options"]["server"]["environment"]["LOCAL_AI_CONFIG"] == str(staged / "client.toml")
    site = staged / "Lib" / "site-packages"
    assert runtime["plugins"][1]["options"]["server"]["environment"]["PYTHONPATH"].split(os.pathsep) == [
        str(staged / "src"), str(site / "win32"), str(site / "win32" / "lib"), str(site / "pythonwin")]
    assert tomllib.loads(client_toml)["server"]["port"] == port
    assert tomllib.loads(client_toml)["server"]["state_dir"] == str(staged / "mcp-state")
    assert "owner-super-secret" not in json.dumps(runtime) + client_toml and "private-value" not in client_toml
    with pytest.raises(ValueError):
        session.build_runtime_config(cfg, install_dir=staged, hub_python=staged / "python.exe",
                                     client_config=tmp_path / "outside.toml", model="model-a")
    with pytest.raises(ValueError):
        session.build_runtime_config(cfg, install_dir=staged, hub_python=tmp_path / "outside.exe",
                                     client_config=staged / "client.toml", model="model-a")
    with pytest.raises(ValueError):
        session.build_runtime_config(cfg, install_dir=staged, hub_python=staged / "python.exe",
                                     client_config=staged / "client.toml", model="model-a:cloud")
    result = []
    worker = threading.Thread(target=lambda: result.append(session.run(["cmd"], cwd="x", env={}, timeout=1)))
    worker.start()
    try:
        assert started.wait(2)
        with pytest.raises(RuntimeError, match="not available"):
            session.build_runtime_config(cfg, install_dir=staged, hub_python=staged / "python.exe",
                                         client_config=staged / "client.toml", model="model-a")
        with pytest.raises(RuntimeError, match="still has a running process"):
            session.__exit__(None, None, None)
        assert "profile-close" not in events
        assert len(captured["LOCAL_AI_PIPE_SECRET"]) == len(captured["LOCAL_AI_STOP_SECRET"]) == 64
        assert captured["LOCAL_AI_PIPE_SECRET"] != captured["LOCAL_AI_STOP_SECRET"]
        assert 1024 <= int(captured["LOCAL_AI_CLIENT_PORT"]) <= 65535
        assert int(captured["LOCAL_AI_CLIENT_PORT"]) == captured["registered_port"]
    finally:
        release.set()
        worker.join(timeout=3)
        session.__exit__(None, None, None)
    assert session.cleanup_confirmed is True
    assert result == [0]
    assert events[-2:] == ["router-close", "profile-close"]
    assert session._relay_secret is None and session._stop_secret is None


def test_session_does_not_confirm_cleanup_after_unknown_run(monkeypatch):
    import local_ai_hub.opencode_sandbox_session as module

    class Profile:
        sid = "sid"
        def __enter__(self): return self
        def __exit__(self, *_args): pass
    class Router:
        port = 123
        def __init__(self, *_args): pass
        def __enter__(self): return self
        def __exit__(self, *_args): pass
        def register_client_port(self, _port): pass
    class Service:
        name = "pipe"
        def __init__(self, *_args): pass
        def __enter__(self): return self
        def __exit__(self, *_args): pass
    def unknown(*_args, **_kwargs):
        raise TimeoutError("cleanup outcome unknown")
    monkeypatch.setattr(module, "AppContainerProfile", Profile)
    monkeypatch.setattr(module, "LocalRouter", Router)
    monkeypatch.setattr(module, "PipeService", Service)
    monkeypatch.setattr(module, "StopService", Service)
    monkeypatch.setattr(module, "run_in_appcontainer", unknown)
    with SandboxSession(1, 2) as session:
        with pytest.raises(TimeoutError):
            session.run(["example"], cwd="x", env={}, timeout=1)
    assert session.cleanup_confirmed is False
