from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

from local_ai_hub.operation_contracts import operation_tool_input_schema, operation_tool_output_schema
from mcp_stdio_catalog_support import explicit_catalog_environment, stdio_catalog


def _assert_advertised_actions_match_schema(tool: dict) -> None:
    for field, label in (("action", "Actions"), ("detail", "detail")):
        advertised = {
            action
            for clause in re.findall(label + r":\s*([a-z_]+(?:,\s*[a-z_]+)*)", tool["description"])
            for action in re.findall(r"[a-z_]+", clause)
        }
        supported = set(tool["inputSchema"].get("properties", {}).get(field, {}).get("enum", []))
        assert advertised <= supported, (tool["name"], field, sorted(advertised - supported))


@pytest.mark.parametrize("lean", [True, False])
@pytest.mark.parametrize("local_enabled", [True, False])
@pytest.mark.parametrize("speculative_enabled", [True, False])
@pytest.mark.parametrize("disabled_module", [None, "agent_os", "vision"])
def test_projected_descriptions_advertise_only_schema_actions(
    tmp_path, monkeypatch, lean, local_enabled, speculative_enabled, disabled_module,
):
    from local_ai_hub import mcp_server

    root = Path(__file__).resolve().parents[1]
    _, features = explicit_catalog_environment(tmp_path, root=root)
    monkeypatch.setattr(features, "tasks", local_enabled)
    monkeypatch.setattr(features, "has_any_model", lambda: local_enabled)
    monkeypatch.setattr(features, "speculative_lint", speculative_enabled)
    if disabled_module is not None:
        monkeypatch.setattr(features, disabled_module, False)
    monkeypatch.setattr(mcp_server, "FEATURES", features)
    monkeypatch.setattr(mcp_server, "LEAN_SCHEMAS", lean)
    for name in features.enabled_tools:
        _assert_advertised_actions_match_schema({
            "name": name,
            "description": mcp_server._all_desc_map[name](),
            "inputSchema": mcp_server._input_schema_with_action_aliases(
                name, operation_tool_input_schema(name, features),
            ),
        })


def test_stdio_handshake_publishes_all_registered_live_schemas(tmp_path: Path) -> None:
    from local_ai_hub import mcp_server

    root = Path(__file__).resolve().parents[1]
    env, features = explicit_catalog_environment(tmp_path, root=root)
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "local-ai-hub-schema-test", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ]

    initialized, listed = stdio_catalog(
        [
            sys.executable,
            "-B",
            "-c",
            "from local_ai_hub import mcp_server; "
            "mcp_server.CLIENT.ensure_server = lambda **_kwargs: True; "
            "mcp_server.main()",
        ],
        cwd=root,
        env=env,
        initialize_params=messages[0]["params"],
        timeout=15,
    )

    assert initialized["protocolVersion"] == "2025-06-18"
    wire_tools = {tool["name"]: tool for tool in listed["tools"]}
    expected_names = set(features.enabled_tools)
    assert set(wire_tools) == expected_names

    from unittest.mock import patch

    with patch.object(mcp_server, "FEATURES", features):
        for name in expected_names:
            expected_input = mcp_server._input_schema_with_action_aliases(
                name, operation_tool_input_schema(name, features)
            )
            expected_output = operation_tool_output_schema(name, features)
            assert wire_tools[name]["inputSchema"] == expected_input, name
            assert wire_tools[name]["outputSchema"] == expected_output, name
            _assert_advertised_actions_match_schema(wire_tools[name])
            if name == "local_ai_rag":
                results_schema = expected_output["x-action-output-contracts"]["search"]["results"]
                assert results_schema["type"] == "array"
                assert results_schema["items"]["properties"]["chunk_no"] == {"type": "integer"}


def test_stdio_list_hides_feature_disabled_tools(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    config = tmp_path / "disabled-features.toml"
    config.write_text("[features]\nrag = false\ncommands = false\n", encoding="utf-8")
    env = os.environ.copy()
    env["LOCAL_AI_CONFIG"] = str(config)
    env["PYTHONPATH"] = os.pathsep.join(
        value for value in (str(root / "src"), env.get("PYTHONPATH", "")) if value
    )
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "disabled-schema-test", "version": "1"},
        }},
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ]
    initialized, listed = stdio_catalog(
        [sys.executable, "-B", "-c", "from local_ai_hub import mcp_server; "
         "mcp_server.CLIENT.ensure_server = lambda **_kwargs: True; mcp_server.main()"],
        cwd=root,
        env=env,
        initialize_params=messages[0]["params"],
        timeout=15,
    )
    assert initialized["protocolVersion"] == "2025-06-18"
    wire_tools = {tool["name"]: tool for tool in listed["tools"]}
    assert "local_ai_rag" not in wire_tools
    assert "local_ai_command" not in wire_tools
    assert all(tool.get("outputSchema") for tool in wire_tools.values())
