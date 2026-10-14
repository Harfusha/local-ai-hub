import sys
from pathlib import Path
import pytest

from local_ai_hub.commands import CommandBroker


def test_command_receives_piped_stdin(tmp_path: Path):
    broker = CommandBroker({"server": {"state_dir": str(tmp_path / "state")}})
    cmd = f'"{sys.executable}" -c "import sys; data = sys.stdin.read(); print(f\'RECEIVED:{{data.strip()}}\')"'
    res = broker.run(
        cmd,
        str(tmp_path),
        stdin="test interactive input 123",
    )
    assert res["success"] is True, res
    assert "RECEIVED:test interactive input 123" in res["stdout"]


def test_command_receives_empty_stdin_by_default(tmp_path: Path):
    broker = CommandBroker({"server": {"state_dir": str(tmp_path / "state")}})
    cmd = f'"{sys.executable}" -c "import sys; data = sys.stdin.read(); print(f\'LENGTH:{{len(data)}}\')"'
    res = broker.run(
        cmd,
        str(tmp_path),
    )
    assert res["success"] is True, res
    assert "LENGTH:0" in res["stdout"]


def test_mcp_command_stdin_input(monkeypatch):
    from local_ai_hub import mcp_server

    captured_payloads = []
    def fake_post(path, payload, **kwargs):
        captured_payloads.append((path, payload))
        return {"success": True, "stdout": f"echo {payload.get('stdin', '')}"}

    monkeypatch.setattr(mcp_server.CLIENT, "post", fake_post)
    res = mcp_server.local_ai_command(action="run", command="cat", stdin="interactive input line")
    assert res["success"] is True
    assert len(captured_payloads) == 1
    assert captured_payloads[0][0] == "/api/command"
    assert captured_payloads[0][1]["stdin"] == "interactive input line"

