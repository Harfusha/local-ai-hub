from __future__ import annotations

import subprocess
import sys
from pathlib import Path
import json

import pytest

from local_ai_hub import process_utils
from tools import hubctl


def test_hubctl_cleanup_ports_cli_arg():
    root = Path(__file__).resolve().parent.parent
    hubctl = root / "tools" / "hubctl.py"
    # Test --help contains --ports and --vacuum
    res = subprocess.run([sys.executable, str(hubctl), "--help"], capture_output=True, text=True, timeout=10)
    assert res.returncode == 0
    assert "--ports" in res.stdout
    assert "--vacuum" in res.stdout


@pytest.mark.parametrize("offline", [False, True])
def test_cleanup_preserves_online_endpoint_without_autostart_or_unowned_signals(
    monkeypatch, capsys, offline,
):
    clients = []
    ports = []

    class FakeClient:
        def __init__(self, *, config_path, auto_start):
            assert config_path == "resolved:test-config.toml"
            assert auto_start is False
            self.posts = []
            self.closed = False
            clients.append(self)

        def post(self, route, payload, *, timeout):
            self.posts.append((route, payload, timeout))
            if offline:
                raise OSError("connection refused")
            return {"success": True, "cleanup": "done"}

        def close(self):
            self.closed = True

        def ensure_server(self, **_kwargs):
            pytest.fail("cleanup must not autostart")

    def listener(port):
        ports.append(port)
        return 43210

    def forbidden_signal(*_args, **_kwargs):
        pytest.fail("port occupancy is not process ownership")

    monkeypatch.setattr(hubctl, "HubClient", FakeClient)
    monkeypatch.setattr(hubctl, "_config_arg", lambda explicit: f"resolved:{explicit}")
    monkeypatch.setattr(process_utils, "find_listening_pid", listener)
    monkeypatch.setattr(process_utils, "terminate_tree", forbidden_signal)
    monkeypatch.setattr(hubctl, "terminate_tree", forbidden_signal)
    monkeypatch.setattr(sys, "argv", [
        "hubctl.py", "cleanup", "--ports", "--config", "test-config.toml",
    ])

    exit_code = hubctl.main()
    result = json.loads(capsys.readouterr().out)
    assert exit_code == (1 if offline else 0)
    assert ports == [11436, 11437, 11439]
    assert len(clients) == 1
    assert clients[0].posts == [("/api/agent-state/cleanup", {}, 3.0)]
    assert clients[0].closed is True
    assert result["success"] is (not offline)
    assert result["cleaned_ports"] == []
    assert result["skipped_ports"] == [
        {"port": port, "pid": 43210, "status": "skipped", "reason": "ownership_unverified"}
        for port in ports
    ]
    if offline:
        assert result["server_status"] == "offline"


