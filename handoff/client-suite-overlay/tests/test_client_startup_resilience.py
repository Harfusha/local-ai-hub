from __future__ import annotations

import os
import subprocess
import sys
import time
from types import SimpleNamespace
from pathlib import Path

import pytest

from local_ai_hub import client as client_module
from local_ai_hub.client import HubClient


def _start_lock_owner(lock: Path, ready: Path) -> subprocess.Popen:
    source_root = Path(__file__).resolve().parents[1] / "src"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(source_root) + os.pathsep + env.get("PYTHONPATH", "")
    script = (
        "import time\n"
        "from pathlib import Path\n"
        "from local_ai_hub.client import _acquire_start_lock\n"
        f"handle = _acquire_start_lock(Path({str(lock)!r}))\n"
        f"Path({str(ready)!r}).write_text('locked' if handle else 'busy')\n"
        "time.sleep(30)\n"
    )
    return subprocess.Popen([sys.executable, "-c", script], env=env)


def _client_config(tmp_path: Path) -> Path:
    config = tmp_path / "config.toml"
    state = tmp_path / "state"
    config.write_text(
        "[server]\nport=11435\nstate_dir='" + state.as_posix() + "'\n"
        "[client]\nstartup_wait_seconds=1.0\nstartup_poll_seconds=0.01\n"
        "start_lock_stale_seconds=0.01\n"
        "[headless]\nrespect_disabled_marker=true\n",
        encoding="utf-8",
    )
    return config


def _enable_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        from local_ai_hub import operational_mode
    except ImportError:
        return
    monkeypatch.setattr(
        operational_mode,
        "load_operational_mode",
        lambda _state: SimpleNamespace(mode="active", degraded=False),
    )


def test_startup_lock_survives_stale_mtime_and_recovers_after_owner_exit(tmp_path: Path):
    lock = tmp_path / "hub.start.lock"
    ready = tmp_path / "owner-ready"
    owner = _start_lock_owner(lock, ready)
    try:
        deadline = time.monotonic() + 5.0
        while not ready.exists() and owner.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists() and ready.read_text(encoding="utf-8") == "locked"
        stale = time.time() - 120.0
        os.utime(lock, (stale, stale))
        assert client_module._acquire_start_lock(lock) is None
    finally:
        owner.kill()
        owner.wait(timeout=5)

    recovered = client_module._acquire_start_lock(lock)
    assert recovered is not None
    recovered.close()


def test_ensure_server_waits_for_live_owner_past_stale_age(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _enable_startup(monkeypatch)
    config = _client_config(tmp_path)
    state = tmp_path / "state"
    state.mkdir()
    lock = state / "hub.start.lock"
    ready = tmp_path / "owner-ready"
    owner = _start_lock_owner(lock, ready)
    try:
        deadline = time.monotonic() + 5.0
        while not ready.exists() and owner.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists() and ready.read_text(encoding="utf-8") == "locked"
        stale = time.time() - 120.0
        os.utime(lock, (stale, stale))

        client = HubClient(tenant="test", config_path=str(config))
        monkeypatch.setattr(client, "_online", lambda *_args: False)
        monkeypatch.setattr(client_module, "find_listening_pid", lambda _port: 0)
        monkeypatch.setattr(
            client_module.subprocess,
            "Popen",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not spawn")),
        )
        monkeypatch.setattr(
            client_module.subprocess,
            "run",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not spawn")),
        )
        assert client.ensure_server(timeout=0.1) is False
    finally:
        owner.kill()
        owner.wait(timeout=5)


def test_failed_owner_metadata_write_releases_startup_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _enable_startup(monkeypatch)
    config = _client_config(tmp_path)
    client = HubClient(tenant="test", config_path=str(config))
    monkeypatch.setattr(client, "_online", lambda *_args: False)
    monkeypatch.setattr(client_module, "find_listening_pid", lambda _port: 0)

    def fail_owner_write(_handle) -> None:
        raise OSError("write failed")

    with monkeypatch.context() as patcher:
        patcher.setattr(client_module, "_write_start_lock_owner", fail_owner_write)
        assert client.ensure_server(timeout=0.1) is False

    lock = tmp_path / "state" / "hub.start.lock"
    recovered = client_module._acquire_start_lock(lock)
    assert recovered is not None
    recovered.close()


def test_startup_retry_cooldown_expires_while_owner_client_stays_alive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _enable_startup(monkeypatch)
    config = _client_config(tmp_path)
    calls = {"count": 0}

    class Child:
        pid = os.getpid()

        def poll(self):
            return None

    def fake_popen(*_args, **_kwargs):
        calls["count"] += 1
        return Child()

    def fake_run(*_args, **_kwargs):
        calls["count"] += 1
        return subprocess.CompletedProcess([], 1)

    monkeypatch.setattr(client_module, "find_listening_pid", lambda _port: 0)
    monkeypatch.setattr(client_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(client_module.subprocess, "run", fake_run)
    first = HubClient(tenant="first", config_path=str(config))
    second = HubClient(tenant="second", config_path=str(config))
    monkeypatch.setattr(first, "_online", lambda *_args: False)
    monkeypatch.setattr(second, "_online", lambda *_args: False)

    assert first.ensure_server(timeout=0.1) is False
    assert calls["count"] == 1
    assert second.ensure_server(timeout=0.1) is False
    assert calls["count"] == 1

    lock = tmp_path / "state" / "hub.start.lock"
    stale = time.time() - 120.0
    os.utime(lock, (stale, stale))
    assert second.ensure_server(timeout=0.1) is False
    assert calls["count"] == 2
