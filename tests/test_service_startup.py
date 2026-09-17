from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock


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


def test_wmi_spawn_detached_passes_active_config(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('test_hub_service_wmi', Path(__file__).parents[1] / 'tools' / 'service.py')
    service = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(service)

    called = []
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
    monkeypatch.setattr(service, "all_supervisor_pids", iter([[], [4321]]).__next__)
    spawn = MagicMock()
    monkeypatch.setattr(service, "spawn_detached", spawn)

    service.native_start()

    spawn.assert_not_called()
