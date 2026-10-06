from __future__ import annotations

import sys
import subprocess
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub import client as client_module
from local_ai_hub.client import HubClient


def _client_subprocess_proxy(popen):
    class Proxy:
        def __getattr__(self, name):
            return getattr(subprocess, name)

    proxy = Proxy()
    proxy.Popen = popen
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
    monkeypatch.setattr(client_module, "subprocess", _client_subprocess_proxy(lambda *_a, **_k: starts.append(True)))
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
    starts: list[bool] = []
    monkeypatch.setattr(client, "_online", lambda *_args: next(online))
    monkeypatch.setattr(client_module, "find_listening_pid", lambda _port: False)

    def popen(*_args, **_kwargs):
        starts.append(True)
        return SimpleNamespace(
            poll=lambda: None,
            terminate=lambda: None,
            wait=lambda timeout=None: 0,
            kill=lambda: None,
        )

    monkeypatch.setattr(client_module, "subprocess", _client_subprocess_proxy(popen))
    monkeypatch.setattr(client_module, "_retain_detached_child", lambda _process: None)

    assert client.ensure_server(timeout=1) is True
    assert loaded == [state_dir]
    assert len(starts) == 1
    assert state_dir.is_dir()
    lock = client_module._acquire_start_lock(state_dir / "hub.start.lock", client.start_lock_stale)
    assert lock is not None
    lock.close()


def test_ensure_server_stops_only_its_child_when_readiness_times_out(
    tmp_path: Path, monkeypatch
) -> None:
    client = _client(tmp_path)
    state_dir = Path(client.config["server"]["state_dir"])
    _install_mode_loader(monkeypatch, "active")
    monkeypatch.setattr(client, "_online", lambda *_args: False)
    monkeypatch.setattr(client_module, "find_listening_pid", lambda _port: False)
    monkeypatch.setattr(client_module, "_retain_detached_child", lambda _process: None)

    class Child:
        stopped = False

        def poll(self):
            return None

        def terminate(self):
            self.stopped = True

        def wait(self, timeout=None):
            return 0

        def kill(self):
            raise AssertionError("already terminated child should not be killed")

    child = Child()
    monkeypatch.setattr(client_module, "subprocess", _client_subprocess_proxy(lambda *_args, **_kwargs: child))

    assert client.ensure_server(timeout=0.2) is False
    assert child.stopped is True
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
