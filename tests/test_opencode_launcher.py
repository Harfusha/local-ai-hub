import json
import os
from pathlib import Path

import pytest

from local_ai_hub.opencode_launcher import LaunchError, launch_opencode


@pytest.mark.skipif(os.name != "nt", reason="Windows job lifecycle")
def test_owned_process_requires_empty_job_before_reporting_cleanup(monkeypatch, tmp_path):
    from local_ai_hub import opencode_launcher, process_utils
    calls = []

    class Child:
        pid = 123
        def wait(self, timeout): return 0
        def poll(self): return 0

    monkeypatch.setattr(opencode_launcher.subprocess, "Popen", lambda *a, **k: Child())
    monkeypatch.setattr(process_utils, "create_job_object_kill_on_close", lambda: 42)
    monkeypatch.setattr(process_utils, "assign_process_to_job", lambda *a: True)
    monkeypatch.setattr(process_utils, "_resume_suspended_process", lambda *a: True)
    monkeypatch.setattr(process_utils, "terminate_job_object", lambda *a: True)
    monkeypatch.setattr(process_utils, "wait_job_object_empty", lambda *a, **k: calls.append("checked") or False)
    monkeypatch.setattr(process_utils, "close_job_object", lambda *a: calls.append("closed") or True)
    with pytest.raises(LaunchError, match="cleanup was not confirmed"):
        opencode_launcher._run_owned_process(["example"], cwd=tmp_path, env={}, timeout=1)
    assert calls == ["checked", "closed"]


@pytest.mark.skipif(os.name != "nt", reason="Windows job lifecycle")
def test_owned_process_cleans_up_real_descendant(tmp_path):
    import ctypes
    import sys
    from ctypes import wintypes
    from local_ai_hub.opencode_launcher import _run_owned_process

    marker = tmp_path / "child.pid"
    script = ("import pathlib,subprocess,sys; "
              "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
              f"pathlib.Path({str(marker)!r}).write_text(str(p.pid))")
    assert _run_owned_process([sys.executable, "-c", script], cwd=tmp_path, env=dict(os.environ), timeout=10) == 0
    pid = int(marker.read_text())
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x00100000, False, pid)
    if handle:
        try:
            assert kernel.WaitForSingleObject(handle, 3000) == 0
        finally:
            kernel.CloseHandle(handle)


class Client:
    def __init__(self, root):
        self.config = {"server": {"port": 11435, "state_dir": str(root / "state"), "ollama_url": "http://127.0.0.1:11434"}, "security": {"api_token": "x" * 40}}
        self.calls = []
        self.responses = [
            {"success": True, "host": "127.0.0.1", "port": 12345, "model": "model-a", "nonce": "n" * 32},
            {"success": True, "state": "stopping"},
            {"success": True, "state": "stopped"},
        ]

    def post(self, path, payload, timeout):
        self.calls.append((path, payload, timeout))
        return self.responses.pop(0)


@pytest.fixture(autouse=True)
def installed_model(monkeypatch):
    monkeypatch.setattr("local_ai_hub.opencode_launcher.local_inventory", lambda origin: {"model-a"})


def test_missing_model_fails_before_provider_start(tmp_path, monkeypatch):
    monkeypatch.setattr("local_ai_hub.opencode_launcher.local_inventory", lambda origin: set())
    client = Client(tmp_path)
    exe = tmp_path / "opencode.exe"
    exe.touch()
    plugin = tmp_path / "tools" / "opencode_goal"
    plugin.mkdir(parents=True)
    (plugin / "index.js").touch()
    with pytest.raises(LaunchError, match="not installed"):
        launch_opencode(client, install_dir=tmp_path, hub_python=Path("python"), executable=exe,
                        project=tmp_path, model="model-a", run_child=lambda *a, **k: pytest.fail("launched"))
    assert client.calls == []


def test_unavailable_inventory_fails_before_provider_start(tmp_path, monkeypatch):
    from local_ai_hub.opencode_models import ModelPreparationError
    def unavailable(origin):
        raise ModelPreparationError("inventory unavailable")
    monkeypatch.setattr("local_ai_hub.opencode_launcher.local_inventory", unavailable)
    client = Client(tmp_path)
    exe = tmp_path / "opencode.exe"
    exe.touch()
    plugin = tmp_path / "tools" / "opencode_goal"
    plugin.mkdir(parents=True)
    (plugin / "index.js").touch()
    with pytest.raises(LaunchError, match="inventory unavailable"):
        launch_opencode(client, install_dir=tmp_path, hub_python=Path("python"), executable=exe,
                        project=tmp_path, model="model-a", run_child=lambda *a, **k: pytest.fail("launched"))
    assert client.calls == []


def test_launcher_starts_child_with_isolated_config_then_stops_owned_provider(tmp_path, monkeypatch):
    client = Client(tmp_path)
    client.config["_config_path"] = str(tmp_path / "owner-secret-config.toml")
    client.config["security"]["supervisor_token"] = "secret-supervisor"
    client.config["features"] = {"repo": False, "custom_secret": "do-not-copy"}
    exe = tmp_path / "opencode.exe"
    exe.touch()
    plugin = tmp_path / "tools" / "opencode_goal"
    plugin.mkdir(parents=True)
    (plugin / "index.js").touch()
    monkeypatch.setenv("OPENAI_API_KEY", "do-not-forward")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "do-not-forward")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "do-not-forward")
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "do-not-forward")
    monkeypatch.setenv("CUSTOM_AUTHORIZATION", "do-not-forward")
    monkeypatch.setenv("OPENCODE_DISABLE_MODELS_FETCH", "0")
    monkeypatch.setenv("PATH", "test-local-path")
    stale = tmp_path / "state" / "opencode-local" / "config" / "opencode.json"
    stale.parent.mkdir(parents=True)
    stale.write_text('{"plugins":["unwanted"]}', encoding="utf-8")
    seen = {}
    def child(argv, *, cwd, env, timeout):
        config_dir = Path(env["OPENCODE_CONFIG_DIR"])
        assert config_dir == Path(env["XDG_CONFIG_HOME"])
        runtime = json.loads(env["OPENCODE_CONFIG_CONTENT"])
        profile_path = Path(runtime["mcp"]["servers"]["local-ai"]["environment"]["LOCAL_AI_CONFIG"])
        assert profile_path.parent == config_dir and profile_path.is_file()
        profile = profile_path.read_text(encoding="utf-8")
        assert "secret-supervisor" not in profile and "x" * 40 not in profile
        assert "do-not-copy" not in profile and '"repo" = false' in profile
        assert "port = 11435" in profile
        seen.update(argv=argv, cwd=cwd, env=env, timeout=timeout)
        return 0
    result = launch_opencode(client, install_dir=tmp_path, hub_python=Path("python"), executable=exe,
                             project=tmp_path, model="model-a", run_child=child)
    assert result == 0
    assert [item[0] for item in client.calls] == ["/api/opencode/provider/start", "/api/opencode/provider/stop", "/api/opencode/provider/wait"]
    assert client.calls[1][1] == {"nonce": "n" * 32}
    assert seen["env"]["OPENCODE_DISABLE_PROJECT_CONFIG"] == "1"
    assert seen["env"]["OPENCODE_DISABLE_MODELS_FETCH"] == "1"
    assert seen["env"]["OPENCODE_DISABLE_AUTOUPDATE"] == "1"
    assert "OPENAI_API_KEY" not in seen["env"]
    assert all(name not in seen["env"] for name in ("AWS_SECRET_ACCESS_KEY", "GOOGLE_APPLICATION_CREDENTIALS", "AZURE_CLIENT_SECRET", "CUSTOM_AUTHORIZATION"))
    assert seen["env"]["PATH"] == "test-local-path"
    from local_ai_hub.opencode_boundary import derive_local_profile_token
    assert seen["env"]["LOCAL_AI_HUB_TOKEN"] == derive_local_profile_token("x" * 40, "n" * 32)
    assert "x" * 40 not in seen["env"].values()
    config = json.loads(seen["env"]["OPENCODE_CONFIG_CONTENT"])
    assert config["model"] == "local-hub/model-a"
    assert config["providers"]["local-hub"]["settings"]["baseURL"] == "http://127.0.0.1:12345/v1"
    assert "x" * 40 not in json.dumps(config)
    assert str(exe) == seen["argv"][0]
    assert not Path(seen["env"]["OPENCODE_CONFIG_DIR"]).exists()
    assert stale.is_file()


def test_unconfirmed_provider_start_never_launches_or_stops_another_session(tmp_path):
    client = Client(tmp_path)
    client.responses = [{"success": False, "outcome_unknown": True}]
    exe = tmp_path / "opencode.exe"
    exe.touch()
    plugin = tmp_path / "tools" / "opencode_goal"
    plugin.mkdir(parents=True)
    (plugin / "index.js").touch()
    with pytest.raises(LaunchError, match="not confirmed"):
        launch_opencode(client, install_dir=tmp_path, hub_python=Path("python"), executable=exe,
                        project=tmp_path, model="model-a", run_child=lambda *a, **k: pytest.fail("launched"))
    assert len(client.calls) == 1


def test_launcher_reports_unconfirmed_shutdown_instead_of_success(tmp_path):
    client = Client(tmp_path)
    client.responses[-1] = {"success": True, "state": "stopping"}
    exe = tmp_path / "opencode.exe"
    exe.touch()
    plugin = tmp_path / "tools" / "opencode_goal"
    plugin.mkdir(parents=True)
    (plugin / "index.js").touch()
    with pytest.raises(LaunchError, match="shutdown"):
        launch_opencode(client, install_dir=tmp_path, hub_python=Path("python"), executable=exe,
                        project=tmp_path, model="model-a", run_child=lambda *a, **k: 0)


def test_child_failure_still_stops_owned_provider(tmp_path):
    client = Client(tmp_path)
    exe = tmp_path / "opencode.exe"
    exe.touch()
    plugin = tmp_path / "tools" / "opencode_goal"
    plugin.mkdir(parents=True)
    (plugin / "index.js").touch()
    def fail(*args, **kwargs):
        raise RuntimeError("child failed")
    with pytest.raises(RuntimeError, match="child failed"):
        launch_opencode(client, install_dir=tmp_path, hub_python=Path("python"), executable=exe,
                        project=tmp_path, model="model-a", run_child=fail)
    assert [item[0] for item in client.calls][-2:] == ["/api/opencode/provider/stop", "/api/opencode/provider/wait"]
