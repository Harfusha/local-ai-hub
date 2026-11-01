import json
from pathlib import Path

from local_ai_hub.generator import generate_opencode_mcp_config, generate_opencode_runtime_config, write_all_generated
import pytest


def test_opencode_manifest_uses_v2_schema_and_preserves_paths():
    install = Path("C:/Hub with spaces")
    python = Path("C:/Python with spaces/python.exe")
    result = generate_opencode_mcp_config({}, install, python)
    server = result["mcp"]["servers"]["local-ai"]
    assert server["type"] == "local"
    assert server["command"] == [str(python), "-m", "local_ai_hub.mcp_server"]
    assert server["cwd"] == str(install)
    assert server["environment"]["LOCAL_AI_AGENT"] == "opencode-local"
    assert server["environment"]["LOCAL_AI_AGENT_PROFILE"] == "opencode-local"
    assert server["environment"]["PYTHONPATH"] == str(install / "src")
    assert "enabled" not in server


def test_opencode_manifest_defines_inheriting_local_agent_roles():
    config = generate_opencode_mcp_config({}, Path("/hub"), Path("/python"))
    assert config["default_agent"] == "local-builder"
    agents = config["agents"]
    assert set(agents) == {"local-builder", "local-planner", "local-reviewer", "local-debugger"}
    assert agents["local-builder"]["mode"] == "primary"
    for name, agent in agents.items():
        assert agent["system"] and agent["description"]
        assert "model" not in agent
        if name != "local-builder":
            assert agent["mode"] == "subagent"
            assert {"action": "edit", "resource": "*", "effect": "deny"} in agent["permissions"]
            assert {"action": "shell", "resource": "*", "effect": "deny"} in agent["permissions"]
    assert "verification" in agents["local-builder"]["system"].lower()


def test_opencode_manifest_preserves_optional_serena(tmp_path):
    serena = tmp_path / "Serena Tools" / "serena.exe"
    result = generate_opencode_mcp_config(
        {"code_intelligence": {"direct_agent_mcp": True}}, tmp_path,
        tmp_path / "python.exe", serena,
    )
    server = result["mcp"]["servers"]["serena"]
    assert server["command"][0] == str(serena)
    assert server["type"] == "local"


def test_runtime_config_uses_only_hub_provider_and_secret_environment(tmp_path):
    config = generate_opencode_runtime_config({}, tmp_path, tmp_path / "python.exe", model="model-a", provider_port=12345, hub_port=11435)
    assert config["model"] == "local-hub/model-a"
    provider = config["providers"]["local-hub"]
    assert provider["settings"] == {"baseURL": "http://127.0.0.1:12345/v1", "apiKey": "{env:LOCAL_AI_OPENCODE_PROVIDER_TOKEN}"}
    assert config["policies"] == [
        {"action": "provider.use", "resource": "*", "effect": "deny"},
        {"action": "provider.use", "resource": "local-hub", "effect": "allow"},
    ]
    assert config["plugins"] == [{"package": str(tmp_path / "tools" / "opencode_goal"),
        "options": {"hubURL": "http://127.0.0.1:11435", "tokenEnv": "LOCAL_AI_HUB_TOKEN"}}]
    assert config["mcp"]["servers"]["local-ai"]["environment"]["LOCAL_AI_AGENT_PROFILE"] == "opencode-local"


@pytest.mark.parametrize("model,provider_port,hub_port", [("", 1234, 11435), ("../bad model", 1234, 11435), ("good", True, 11435), ("good", 0, 11435), ("good", 1234, 65536)])
def test_runtime_config_rejects_invalid_model_or_ports(tmp_path, model, provider_port, hub_port):
    with pytest.raises(ValueError):
        generate_opencode_runtime_config({}, tmp_path, tmp_path / "python.exe", model=model, provider_port=provider_port, hub_port=hub_port)


def test_generated_opencode_manifest_survives_regeneration(tmp_path):
    python = tmp_path / "Python with spaces" / "python.exe"
    first = write_all_generated({}, tmp_path, hub_python=python)
    target = tmp_path / "generated" / "opencode-mcp.json"
    assert str(target) in first["mcp"]
    initial = json.loads(target.read_text(encoding="utf-8"))
    write_all_generated({}, tmp_path, hub_python=python)
    assert json.loads(target.read_text(encoding="utf-8")) == initial
