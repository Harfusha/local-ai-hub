import sys
from local_ai_hub.commands import CommandBroker

def test_command_run_with_custom_env(tmp_path):
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
    
    res = broker.run(
        cmd,
        cwd=str(tmp_path),
        env={"TEST_HUB_ENV_VAR": "hello_env_world"},
    )
    assert res.get("success") is True
    assert "hello_env_world" in res.get("stdout", "").strip()


def test_mcp_local_ai_command_forwards_env(monkeypatch):
    captured = {}
    class DummyClient:
        def post(self, url, payload, **kwargs):
            captured.update(payload)
            return {"success": True, "stdout": "ok"}
    monkeypatch.setattr("local_ai_hub.mcp_server.CLIENT", DummyClient())
    from local_ai_hub.mcp_server import local_ai_command
    local_ai_command(action="run", command="echo 1", env={"CUSTOM_VAR": "custom_val"})
    assert captured.get("env") == {"CUSTOM_VAR": "custom_val"}
