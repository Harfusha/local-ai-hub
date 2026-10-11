from __future__ import annotations

import os
import subprocess
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub import client as client_module
from local_ai_hub.client import HubClient


def _client_subprocess_proxy(run):
    class Proxy:
        def __getattr__(self, name):
            return getattr(subprocess, name)

    proxy = Proxy()
    proxy.run = run
    return proxy


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
    def run(*_args, **_kwargs):
        starts.append(True)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(client_module, "subprocess", _client_subprocess_proxy(run))
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
    online = iter((False, False, True))
    probe_timeouts: list[float | None] = []
    starts: list[bool] = []

    def is_online(timeout: float | None = None) -> bool:
        probe_timeouts.append(timeout)
        return next(online)

    monkeypatch.setattr(client, "_online", is_online)
    monkeypatch.setattr(client_module, "find_listening_pid", lambda _port: False)

    def run(*_args, **_kwargs):
        starts.append(True)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(client_module, "subprocess", _client_subprocess_proxy(run))
    monkeypatch.setattr(client_module, "_retain_detached_child", lambda _process: None)

    assert client.ensure_server(timeout=1) is True
    assert probe_timeouts
    assert all(timeout is not None and timeout <= client.health_timeout for timeout in probe_timeouts)
    assert loaded == [state_dir]
    assert len(starts) == 1
    assert state_dir.is_dir()
    lock = client_module._acquire_start_lock(state_dir / "hub.start.lock", client.start_lock_stale)
    assert lock is not None
    lock.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows console visibility contract")
@pytest.mark.parametrize("use_run", [True, False])
def test_ensure_server_fails_closed_when_hidden_launch_setup_fails(
    tmp_path: Path, monkeypatch, use_run: bool
) -> None:
    client = _client(tmp_path)
    _install_mode_loader(monkeypatch, "active")
    starts: list[bool] = []
    monkeypatch.setattr(client, "_online", lambda *_args: False)
    monkeypatch.setattr(client_module, "find_listening_pid", lambda _port: False)

    def fail_hidden_kwargs(**_kwargs):
        raise OSError("cannot configure hidden process startup")

    monkeypatch.setattr("local_ai_hub.process_utils.hidden_run_kwargs", fail_hidden_kwargs)

    if use_run:
        def run(*_args, **_kwargs):
            starts.append(True)
            return SimpleNamespace(returncode=0)

        monkeypatch.setattr(client_module, "subprocess", _client_subprocess_proxy(run))
    else:
        def popen(*_args, **_kwargs):
            starts.append(True)
            raise AssertionError("process must not start without hidden-window flags")

        monkeypatch.setattr(subprocess, "Popen", popen)

    assert client.ensure_server(timeout=1) is False
    assert starts == []


def test_ensure_server_keeps_start_cooldown_when_readiness_times_out(
    tmp_path: Path, monkeypatch
) -> None:
    client = _client(tmp_path)
    state_dir = Path(client.config["server"]["state_dir"])
    _install_mode_loader(monkeypatch, "active")
    monkeypatch.setattr(client, "_online", lambda *_args: False)
    monkeypatch.setattr(client_module, "find_listening_pid", lambda _port: False)
    monkeypatch.setattr(client_module, "_retain_detached_child", lambda _process: None)

    calls = []

    def run(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(client_module, "subprocess", _client_subprocess_proxy(run))

    assert client.ensure_server(timeout=0.2) is False
    assert len(calls) == 1
    assert calls[0][1]["timeout"] <= 0.2
    assert calls[0][0][0][-1] == "start"
    lock_path = state_dir / "hub.start.lock"
    assert lock_path.exists()
    assert client_module._acquire_start_lock(lock_path, client.start_lock_stale) is None


def test_ensure_server_uses_real_persisted_gaming_mode(tmp_path: Path, monkeypatch) -> None:
    from local_ai_hub.operational_mode import set_operational_mode

    client = _client(tmp_path)
    state_dir = Path(client.config["server"]["state_dir"])
    set_operational_mode(state_dir, "gaming")
    starts: list[bool] = []
    monkeypatch.setattr(client, "_online", lambda *_args: False)
    monkeypatch.setattr(client_module, "find_listening_pid", lambda _port: False)
    monkeypatch.setattr(
        client_module.subprocess,
        "Popen",
        lambda *_args, **_kwargs: starts.append(True),
    )

    assert client.ensure_server(timeout=0.2) is False
    assert starts == []
