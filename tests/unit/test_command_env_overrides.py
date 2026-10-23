import asyncio
import os
import sys
from pathlib import Path

from local_ai_hub.commands import CommandBroker

def test_command_run_with_custom_env(tmp_path, monkeypatch):
    config = {
        "commands": {
            "enabled": True,
            "timeout_seconds": 30,
        },
        "server": {
            "state_dir": str(tmp_path / "state"),
        },
    }
    broker = CommandBroker(config)
    cmd = f'"{sys.executable}" -c "import os; print(os.environ.get(\'TEST_HUB_ENV_VAR\', \'\'))"'

    monkeypatch.setenv("TEST_HUB_ENV_VAR", "parent_value")
    res = broker._execute(
        cmd,
        cwd=str(tmp_path),
        timeout=10,
        env_overrides={"TEST_HUB_ENV_VAR": "hello_env_world"},
    )
    assert res.get("success") is True, res
    assert "hello_env_world" in res.get("stdout", "").strip()
    assert os.environ.get("TEST_HUB_ENV_VAR") == "parent_value"






def test_command_modules_come_from_assigned_checkout():
    from local_ai_hub import commands, mcp_server

    expected_src = Path(__file__).resolve().parents[2] / "src"
    for module in (commands, mcp_server):
        assert Path(module.__file__).resolve().is_relative_to(expected_src.resolve())
