import sys
from pathlib import Path
import pytest

from local_ai_hub.commands import CommandBroker


def test_command_receives_piped_stdin(tmp_path: Path):
    broker = CommandBroker({"server": {"state_dir": str(tmp_path / "state")}})
    cmd = f'"{sys.executable}" -c "import sys; data = sys.stdin.read(); print(f\'RECEIVED:{{data.strip()}}\')"'
    res = broker._execute(
        cmd,
        str(tmp_path),
        timeout=10,
        stdin="test interactive input 123",
    )
    assert res["success"] is True, res
    assert "RECEIVED:test interactive input 123" in res["stdout"]


def test_command_receives_empty_stdin_by_default(tmp_path: Path):
    broker = CommandBroker({"server": {"state_dir": str(tmp_path / "state")}})
    cmd = f'"{sys.executable}" -c "import sys; data = sys.stdin.read(); print(f\'LENGTH:{{len(data)}}\')"'
    res = broker._execute(
        cmd,
        str(tmp_path),
        timeout=10,
    )
    assert res["success"] is True, res
    assert "LENGTH:0" in res["stdout"]
