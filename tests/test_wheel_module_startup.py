from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub import client as client_module
from local_ai_hub import operational_mode, process_utils
from local_ai_hub.client import HubClient


class FakeProcess:
    pid = 4242

    def poll(self) -> None:
        return None


def _wheel_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[HubClient, Path]:
    config_path = tmp_path / "config.toml"
    state_dir = tmp_path / "state"
    config_path.write_text(
        "[server]\nport=11435\nstate_dir='" + state_dir.as_posix() + "'\n"
        "[client]\nstartup_wait_seconds=1.0\nstartup_poll_seconds=0.01\n"
        "start_lock_stale_seconds=0.01\n"
        "[headless]\nrespect_disabled_marker=true\n",
        encoding="utf-8",
    )
    wheel_site = tmp_path / "wheel" / "site-packages"
    package_dir = wheel_site / "local_ai_hub"
    package_dir.mkdir(parents=True)
    wheel_client_file = package_dir / "client.py"

    monkeypatch.setattr(client_module, "__file__", str(wheel_client_file))
    monkeypatch.setattr(
        operational_mode,
        "load_operational_mode",
        lambda _state: SimpleNamespace(mode="active", degraded=False),
    )
    monkeypatch.setattr(client_module, "find_listening_pid", lambda _port: 0)
    monkeypatch.setattr(process_utils, "hidden_run_kwargs", lambda **_kwargs: {})
    monkeypatch.setattr(client_module, "process_identity", lambda pid: {"pid": pid})
    monkeypatch.setattr(client_module, "_retain_detached_child", lambda _process: None)
    return HubClient(tenant="test", config_path=str(config_path)), wheel_site


def test_wheel_install_starts_module_supervisor_without_tools_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, wheel_site = _wheel_client(tmp_path, monkeypatch)
    probes = iter((False, False, True))
    monkeypatch.setattr(client, "_online", lambda *_args: next(probes))
    started: list[tuple[list[str], dict[str, object]]] = []

    def fake_popen(command: list[str], **kwargs: object) -> FakeProcess:
        started.append((command, kwargs))
        return FakeProcess()

    monkeypatch.setattr(client_module.subprocess, "Popen", fake_popen)

    assert client.ensure_server(timeout=1.0) is True

    assert len(started) == 1
    command, kwargs = started[0]
    expected_python = client_module.sys.executable
    pythonw = Path(expected_python).parent / "pythonw.exe"
    if client_module.sys.platform == "win32" and pythonw.exists():
        expected_python = str(pythonw)
    assert command == [
        expected_python,
        "-m",
        "local_ai_hub.supervisor",
        "--config",
        client.config["_config_path"],
    ]
    assert kwargs["env"]["LOCAL_AI_CONFIG"] == client.config["_config_path"]
    assert str(wheel_site) in kwargs["env"]["PYTHONPATH"].split(client_module.os.pathsep)
    assert not (wheel_site.parent / "tools" / "service.py").exists()


def test_patched_service_runner_stays_fail_closed_without_service_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, wheel_site = _wheel_client(tmp_path, monkeypatch)
    monkeypatch.setattr(client, "_online", lambda *_args: False)
    run_calls: list[object] = []
    popen_calls: list[object] = []
    monkeypatch.setattr(
        client_module.subprocess,
        "run",
        lambda *args, **kwargs: run_calls.append((args, kwargs)),
    )
    monkeypatch.setattr(
        client_module.subprocess,
        "Popen",
        lambda *args, **kwargs: popen_calls.append((args, kwargs)),
    )

    assert client.ensure_server(timeout=0.1) is False

    assert not (wheel_site.parent / "tools" / "service.py").exists()
    assert run_calls == []
    assert popen_calls == []
