from __future__ import annotations

from pathlib import Path
from local_ai_hub.client_adapters.adapters.opencode import (
    OpenCodeAdapter,
)

from local_ai_hub.client_adapters.registry import (
    get_adapter,
)
from tools.opencode_install import generate_opencode_plugin_config, get_opencode_goal_system_prompt


def test_opencode_adapter_capabilities():
    adapter = get_adapter("opencode")
    assert isinstance(adapter, OpenCodeAdapter)
    assert adapter.client_id == "opencode"
    assert adapter.capabilities.hook_support.value == "js_plugin"
    assert adapter.capabilities.has_goal_system is True
    assert "local_ai_work" in adapter.capabilities.tool_filter
    assert "local_ai_repo" in adapter.capabilities.tool_filter


def test_opencode_plugin_config_generation():
    config = generate_opencode_plugin_config(
        hub_install_dir="C:/LocalAI",
        python_exe="C:/Python/python.exe",
        hub_port=8080,
    )
    assert config["cwd"] == "C:/LocalAI"
    assert config["command"] == ["C:/Python/python.exe", "-m", "local_ai_hub.mcp_server"]
    assert config["environment"]["LOCAL_AI_HUB_PORT"] == "8080"
    assert config["environment"]["OPENCODE_SESSION"] == "1"
    assert config["environment"]["LOCAL_AI_AGENT"] == "opencode"
    assert config["environment"]["LOCAL_AI_AGENT_PROFILE"] == "opencode"


def test_opencode_goal_system_prompt():
    prompt = get_opencode_goal_system_prompt()
    assert "local_ai_work" in prompt
    assert "only when the live MCP schema advertises it" in prompt
    assert "explicitly requested" in prompt
    assert "LOCAL AI HUB" in prompt
