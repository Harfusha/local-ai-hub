from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub import client as client_module
from local_ai_hub.client import HubClient


def _client(tmp_path: Path) -> HubClient:
    state_dir = tmp_path / "state"
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f"[server]\nport=39123\nstate_dir='{state_dir.as_posix()}'\n",
        encoding="utf-8",
    )
    return HubClient(config_path=str(config_path))


def _install_mode_loader(monkeypatch, mode: str, *, degraded: bool = False):
    module = types.ModuleType("local_ai_hub.operational_mode")
    observed: list[Path] = []

    def load_operational_mode(state_dir: str | Path):
        path = Path(state_dir)
        assert not path.exists()
        observed.append(path)
        return SimpleNamespace(mode=mode, degraded=degraded)

    module.load_operational_mode = load_operational_mode
    monkeypatch.setitem(sys.modules, module.__name__, module)
    return observed


@pytest.mark.parametrize(
    ("mode", "degraded"),
    [("gaming", False), ("maintenance", False), ("active", True)],
)
def test_ensure_server_refuses_autostart_before_state_creation_when_mode_blocks(
    tmp_path: Path, monkeypatch, mode: str, degraded: bool
) -> None:
    client = _client(tmp_path)
    state_dir = Path(client.config["server"]["state_dir"])
    loaded = _install_mode_loader(monkeypatch, mode, degraded=degraded)
    online = iter((False, False, True))
    starts: list[bool] = []
    monkeypatch.setattr(client, "_online", lambda *_args: next(online))
    monkeypatch.setattr(client_module, "find_listening_pid", lambda _port: False)
    monkeypatch.setattr(client_module.subprocess, "Popen", lambda *_a, **_k: starts.append(True))
    monkeypatch.setattr(client_module, "_retain_detached_child", lambda _process: None)

    assert client.ensure_server(timeout=1) is False
    assert loaded == [state_dir]
    assert not state_dir.exists()
    assert starts == []


@pytest.mark.parametrize("stored_mode", ["active", None])
def test_ensure_server_autostarts_for_active_or_missing_mode(
    tmp_path: Path, monkeypatch, stored_mode: str | None
) -> None:
    client = _client(tmp_path)
    state_dir = Path(client.config["server"]["state_dir"])
    loaded = _install_mode_loader(monkeypatch, stored_mode or "active")
    starts: list[bool] = []
    monkeypatch.setattr(client, "_online", lambda *_args: bool(starts))
    monkeypatch.setattr(client_module, "find_listening_pid", lambda _port: False)

    def start_service(*_args, **_kwargs):
        starts.append(True)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(
        client_module.subprocess,
        "run",
        start_service,
    )
    monkeypatch.setattr(client_module, "_retain_detached_child", lambda _process: None)

    assert client.ensure_server(timeout=1) is True
    assert loaded == [state_dir]
    assert len(starts) == 1
    assert state_dir.is_dir()
    assert not (state_dir / "hub.start.lock").exists()
