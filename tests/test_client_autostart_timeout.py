from __future__ import annotations

import subprocess

from local_ai_hub import client as client_module
from local_ai_hub.client import HubClient


def test_daemon_start_does_not_exceed_remaining_deadline(tmp_path, monkeypatch) -> None:
    state_dir = tmp_path / "state"
    config = tmp_path / "config.toml"
    config.write_text(
        "[server]\nport=39125\nstate_dir='" + state_dir.as_posix() + "'\n",
        encoding="utf-8",
    )
    client = HubClient(config_path=str(config))
    launch_timeouts: list[float] = []

    def timeout_start(args, *, timeout, **_kwargs):
        launch_timeouts.append(float(timeout))
        raise subprocess.TimeoutExpired(args, timeout)

    monkeypatch.setattr(client, "_online", lambda _timeout=None: False)
    monkeypatch.setattr(client_module, "find_listening_pid", lambda _port: None)
    monkeypatch.setattr(client_module.subprocess, "run", timeout_start)

    assert client.ensure_server(timeout=0.06) is False
    assert len(launch_timeouts) == 1
    assert 0 < launch_timeouts[0] <= 0.06
