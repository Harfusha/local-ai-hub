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


def test_normalize_status_clears_stale_running_state():
    from tools import service

    stale = {
        "state": "running",
        "pid": 38580,
        "hub_pid": 34944,
        "last_error": "",
    }
    normalized = service.normalize_status(stale, supervisor_alive=False, hub_alive=False)
    assert normalized["state"] == "stopped"
    assert normalized["pid"] == 0
    assert normalized["hub_pid"] == 0
    assert normalized["last_error"] == "supervisor process not running"
