from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def test_denied_scheduler_keeps_user_logon_startup(tmp_path, monkeypatch):
    from local_ai_hub import config
    monkeypatch.setattr(config, 'load_config', lambda *args: {'server': {'state_dir': str(tmp_path)}})
    spec = importlib.util.spec_from_file_location('test_hub_service', Path(__file__).parents[1] / 'tools' / 'service.py')
    service = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(service)
    registry = MagicMock()
    monkeypatch.setitem(sys.modules, 'winreg', registry)
    monkeypatch.setattr(service.shutil, 'which', lambda name: None)
    monkeypatch.setattr(service, 'run', lambda *args, **kwargs: subprocess.CompletedProcess([], 1))
    monkeypatch.setattr(service, 'managed_service_running', lambda: False)
    start = MagicMock()
    monkeypatch.setattr(service, 'spawn_detached', start)

    assert service.install_windows() == 'windows-user-startup'
    assert registry.CreateKey.call_args.args[0] == registry.HKEY_CURRENT_USER
    assert registry.SetValueEx.call_args.args[1] == 'LocalAIHubSupervisor'
    assert 'service_entry.py' in registry.SetValueEx.call_args.args[4]
    start.assert_called_once()
    assert service.set_windows_user_startup(False)
    registry.DeleteValue.assert_called_once()


@pytest.mark.skipif(os.name != "nt", reason="Windows service launcher only")
def test_wmi_spawn_detached_passes_active_config(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('test_hub_service_wmi', Path(__file__).parents[1] / 'tools' / 'service.py')
    service = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(service)

    called = []
    monkeypatch.setattr(service, "all_supervisor_pids", lambda: [])
    monkeypatch.setattr(service, "supervisor_pid", lambda: 0)
    monkeypatch.setattr(service, "_ACTIVE_CONFIG_ARG", "C:\\custom\\config.toml")
    monkeypatch.setattr(service.shutil, "which", lambda name: "powershell.exe")
    monkeypatch.setattr(service, "run", lambda cmd, **kwargs: called.append(cmd) or subprocess.CompletedProcess([], 0))

    service.spawn_detached()

    assert len(called) == 1
    script = " ".join(str(x) for x in called[0])
    assert "--config" in script
    assert "C:\\custom\\config.toml" in script


def test_native_start_does_not_spawn_duplicate_after_scheduler_race(monkeypatch):
    module = importlib.util.spec_from_file_location(
        "test_hub_service_native_start", Path(__file__).parents[1] / "tools" / "service.py"
    )
    service = importlib.util.module_from_spec(module)
    module.loader.exec_module(service)

    monkeypatch.setattr(service, "mark_managed", lambda: None)
    monkeypatch.setattr(service, "mark_disabled", lambda _disabled: None)
    monkeypatch.setattr(service, "run", lambda *args, **kwargs: subprocess.CompletedProcess([], 1))
    monkeypatch.setattr(service, "supervisor_pid", iter([0, 4321]).__next__)
    spawn = MagicMock()
    monkeypatch.setattr(service, "spawn_detached", spawn)

    service.native_start()

    spawn.assert_not_called()


@pytest.mark.skipif(os.name != "nt", reason="Windows service launcher only")
def test_all_supervisor_pids_does_not_match_its_own_powershell_query(monkeypatch):
    module = importlib.util.spec_from_file_location(
        "test_hub_service_process_query", Path(__file__).parents[1] / "tools" / "service.py"
    )
    service = importlib.util.module_from_spec(module)
    module.loader.exec_module(service)

    commands = []
    monkeypatch.setattr(service, "supervisor_pid", lambda: 0)
    monkeypatch.setattr(
        service.subprocess,
        "run",
        lambda cmd, **kwargs: commands.append(cmd) or subprocess.CompletedProcess(cmd, 0, stdout="", stderr=""),
    )

    assert service.all_supervisor_pids() == []
    script = commands[0][-1]
    assert "-Filter" in script
    assert "python.exe" in script


def test_kill_hub_terminates_verified_listener_child_before_launcher(tmp_path, monkeypatch):
    module = importlib.util.spec_from_file_location(
        "test_hub_service_child_cleanup", Path(__file__).parents[1] / "tools" / "service.py"
    )
    service = importlib.util.module_from_spec(module)
    module.loader.exec_module(service)
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    launcher_pid = 101
    listener_pid = 202
    launcher_owner = {
        "pid": launcher_pid,
        "role": "hub",
        "state_dir": str(state_dir),
        "executable": "launcher.exe",
    }
    listener_owner = {
        "pid": listener_pid,
        "role": "hub",
        "state_dir": str(state_dir),
        "executable": "pythonw.exe",
    }
    (state_dir / "hub.owner.json").write_text(json.dumps(launcher_owner), encoding="utf-8")
    (state_dir / "hub.pid").write_text(str(listener_pid), encoding="utf-8")
    monkeypatch.setattr(service, "STATE", state_dir)
    monkeypatch.setattr(service, "find_listening_pid", lambda _port: listener_pid)
    monkeypatch.setattr(service, "process_owner_state", lambda *_args: "owned")
    monkeypatch.setattr(service, "pid_alive", lambda _pid: True)
    monkeypatch.setattr(
        service,
        "process_parent_pid",
        lambda pid: launcher_pid if pid == listener_pid else None,
        raising=False,
    )
    monkeypatch.setattr(
        service,
        "process_owner_record",
        lambda pid, *_args: listener_owner if pid == listener_pid else None,
        raising=False,
    )
    stopped = []

    def terminate(owner, *_args, **_kwargs):
        stopped.append(owner["pid"])
        return True

    monkeypatch.setattr(service, "terminate_owned_process", terminate)
    monkeypatch.setattr(service, "_role_stopped", lambda _role: True)

    assert service.kill_hub() is True
    assert stopped == [listener_pid, launcher_pid]


def test_kill_hub_ignores_dead_stale_listener_pid(tmp_path, monkeypatch):
    module = importlib.util.spec_from_file_location(
        "test_hub_service_stale_listener", Path(__file__).parents[1] / "tools" / "service.py"
    )
    service = importlib.util.module_from_spec(module)
    module.loader.exec_module(service)
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    launcher_pid, stale_listener_pid = 101, 202
    owner = {
        "pid": launcher_pid,
        "role": "hub",
        "state_dir": str(state_dir),
        "executable": "launcher.exe",
    }
    (state_dir / "hub.owner.json").write_text(json.dumps(owner), encoding="utf-8")
    (state_dir / "hub.pid").write_text(str(stale_listener_pid), encoding="utf-8")
    monkeypatch.setattr(service, "STATE", state_dir)
    monkeypatch.setattr(service, "find_listening_pid", lambda _port: None)
    monkeypatch.setattr(service, "process_owner_state", lambda *_args: "owned")
    monkeypatch.setattr(service, "pid_alive", lambda pid: pid != stale_listener_pid)
    monkeypatch.setattr(
        service,
        "process_parent_pid",
        lambda _pid: pytest.fail("dead stale listener PID must not be inspected"),
    )
    stopped = []
    monkeypatch.setattr(
        service,
        "terminate_owned_process",
        lambda process_owner, *_args, **_kwargs: stopped.append(process_owner["pid"]) or True,
    )
    monkeypatch.setattr(service, "_role_stopped", lambda _role: True)

    assert service.kill_hub() is True
    assert stopped == [launcher_pid]


def test_kill_hub_does_not_signal_unverified_listener_child(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "test_hub_service_unverified_child",
        Path(__file__).parents[1] / "tools" / "service.py",
    )
    service = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(service)
    launcher_pid, listener_pid = 101, 202
    owner = {
        "pid": launcher_pid,
        "role": "hub",
        "state_dir": str(tmp_path),
        "executable": "launcher.exe",
    }
    (tmp_path / "hub.owner.json").write_text(json.dumps(owner), encoding="utf-8")
    (tmp_path / "hub.pid").write_text(str(listener_pid), encoding="utf-8")
    monkeypatch.setattr(service, "STATE", tmp_path)
    monkeypatch.setattr(service, "find_listening_pid", lambda _port: listener_pid)
    monkeypatch.setattr(service, "process_owner_state", lambda *_args: "owned")
    monkeypatch.setattr(service, "pid_alive", lambda _pid: True)
    monkeypatch.setattr(service, "process_parent_pid", lambda _pid: 303)
    stopped = []
    monkeypatch.setattr(
        service,
        "terminate_owned_process",
        lambda process_owner, *_args, **_kwargs: stopped.append(process_owner["pid"]) or True,
    )

    assert service.kill_hub() is False
    assert stopped == []
