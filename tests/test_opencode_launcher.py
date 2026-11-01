import json
from pathlib import Path

import pytest

from local_ai_hub.opencode_launcher import LaunchError, launch_opencode


class Client:
    def __init__(self, root):
        self.config = {"server": {"port": 11435, "state_dir": str(root / "state"), "ollama_url": "http://127.0.0.1:11434"}, "security": {"api_token": "x" * 40}}
        self.calls = []
        self.responses = [
            {"success": True, "host": "127.0.0.1", "port": 12345, "model": "model-a", "nonce": "n" * 32},
            {"success": True, "state": "stopping"},
            {"success": True, "state": "stopped"},
        ]

    def post(self, path, payload, timeout):
        self.calls.append((path, payload, timeout))
        return self.responses.pop(0)


@pytest.fixture(autouse=True)
def installed_model(monkeypatch):
    monkeypatch.setattr("local_ai_hub.opencode_launcher.local_inventory", lambda origin: {"model-a"})


def test_missing_model_fails_before_provider_start(tmp_path, monkeypatch):
    monkeypatch.setattr("local_ai_hub.opencode_launcher.local_inventory", lambda origin: set())
    client = Client(tmp_path)
    exe = tmp_path / "opencode.exe"
    exe.touch()
    plugin = tmp_path / "tools" / "opencode_goal"
    plugin.mkdir(parents=True)
    (plugin / "index.js").touch()
    with pytest.raises(LaunchError, match="not installed"):
        launch_opencode(client, install_dir=tmp_path, hub_python=Path("python"), executable=exe,
                        project=tmp_path, model="model-a", run_child=lambda *a, **k: pytest.fail("launched"))
    assert client.calls == []


def test_unavailable_inventory_fails_before_provider_start(tmp_path, monkeypatch):
    from local_ai_hub.opencode_models import ModelPreparationError
    def unavailable(origin):
        raise ModelPreparationError("inventory unavailable")
    monkeypatch.setattr("local_ai_hub.opencode_launcher.local_inventory", unavailable)
    client = Client(tmp_path)
    exe = tmp_path / "opencode.exe"
    exe.touch()
    plugin = tmp_path / "tools" / "opencode_goal"
    plugin.mkdir(parents=True)
    (plugin / "index.js").touch()
    with pytest.raises(LaunchError, match="inventory unavailable"):
        launch_opencode(client, install_dir=tmp_path, hub_python=Path("python"), executable=exe,
                        project=tmp_path, model="model-a", run_child=lambda *a, **k: pytest.fail("launched"))
    assert client.calls == []


def test_launcher_starts_child_with_isolated_config_then_stops_owned_provider(tmp_path, monkeypatch):
    client = Client(tmp_path)
    exe = tmp_path / "opencode.exe"
    exe.touch()
    plugin = tmp_path / "tools" / "opencode_goal"
    plugin.mkdir(parents=True)
    (plugin / "index.js").touch()
    monkeypatch.setenv("OPENAI_API_KEY", "do-not-forward")
    stale = tmp_path / "state" / "opencode-local" / "config" / "opencode.json"
    stale.parent.mkdir(parents=True)
    stale.write_text('{"plugins":["unwanted"]}', encoding="utf-8")
    seen = {}
    def child(argv, *, cwd, env, timeout):
        config_dir = Path(env["OPENCODE_CONFIG_DIR"])
        assert config_dir == Path(env["XDG_CONFIG_HOME"])
        assert not list(config_dir.iterdir())
        seen.update(argv=argv, cwd=cwd, env=env, timeout=timeout)
        return 0
    result = launch_opencode(client, install_dir=tmp_path, hub_python=Path("python"), executable=exe,
                             project=tmp_path, model="model-a", run_child=child)
    assert result == 0
    assert [item[0] for item in client.calls] == ["/api/opencode/provider/start", "/api/opencode/provider/stop", "/api/opencode/provider/wait"]
    assert client.calls[1][1] == {"nonce": "n" * 32}
    assert seen["env"]["OPENCODE_DISABLE_PROJECT_CONFIG"] == "1"
    assert "OPENAI_API_KEY" not in seen["env"]
    assert seen["env"]["LOCAL_AI_HUB_TOKEN"] == "x" * 40
    config = json.loads(seen["env"]["OPENCODE_CONFIG_CONTENT"])
    assert config["model"] == "local-hub/model-a"
    assert config["providers"]["local-hub"]["settings"]["baseURL"] == "http://127.0.0.1:12345/v1"
    assert "x" * 40 not in json.dumps(config)
    assert str(exe) == seen["argv"][0]
    assert not Path(seen["env"]["OPENCODE_CONFIG_DIR"]).exists()
    assert stale.is_file()


def test_unconfirmed_provider_start_never_launches_or_stops_another_session(tmp_path):
    client = Client(tmp_path)
    client.responses = [{"success": False, "outcome_unknown": True}]
    exe = tmp_path / "opencode.exe"
    exe.touch()
    plugin = tmp_path / "tools" / "opencode_goal"
    plugin.mkdir(parents=True)
    (plugin / "index.js").touch()
    with pytest.raises(LaunchError, match="not confirmed"):
        launch_opencode(client, install_dir=tmp_path, hub_python=Path("python"), executable=exe,
                        project=tmp_path, model="model-a", run_child=lambda *a, **k: pytest.fail("launched"))
    assert len(client.calls) == 1


def test_launcher_reports_unconfirmed_shutdown_instead_of_success(tmp_path):
    client = Client(tmp_path)
    client.responses[-1] = {"success": True, "state": "stopping"}
    exe = tmp_path / "opencode.exe"
    exe.touch()
    plugin = tmp_path / "tools" / "opencode_goal"
    plugin.mkdir(parents=True)
    (plugin / "index.js").touch()
    with pytest.raises(LaunchError, match="shutdown"):
        launch_opencode(client, install_dir=tmp_path, hub_python=Path("python"), executable=exe,
                        project=tmp_path, model="model-a", run_child=lambda *a, **k: 0)


def test_child_failure_still_stops_owned_provider(tmp_path):
    client = Client(tmp_path)
    exe = tmp_path / "opencode.exe"
    exe.touch()
    plugin = tmp_path / "tools" / "opencode_goal"
    plugin.mkdir(parents=True)
    (plugin / "index.js").touch()
    def fail(*args, **kwargs):
        raise RuntimeError("child failed")
    with pytest.raises(RuntimeError, match="child failed"):
        launch_opencode(client, install_dir=tmp_path, hub_python=Path("python"), executable=exe,
                        project=tmp_path, model="model-a", run_child=fail)
    assert [item[0] for item in client.calls][-2:] == ["/api/opencode/provider/stop", "/api/opencode/provider/wait"]
