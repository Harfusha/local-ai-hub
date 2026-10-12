from __future__ import annotations

import os
import sys
from pathlib import Path

from local_ai_hub.operation_contracts import operation_tool_output_schema
from mcp_stdio_catalog_support import stdio_catalog


def test_stdio_handshake_publishes_all_registered_live_schemas() -> None:
    from local_ai_hub import mcp_server

    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        value for value in (str(root / "src"), env.get("PYTHONPATH", "")) if value
    )
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
    expected_names = set(mcp_server.FEATURES.enabled_tools)
    assert set(wire_tools) == expected_names
    assert expected_names == set(mcp_server.mcp._tool_manager._tools)

    for name in expected_names:
        registered = mcp_server.mcp._tool_manager._tools[name]
        assert wire_tools[name]["inputSchema"] == registered.parameters, name
        assert registered.output_schema is not None, name
        assert registered.output_schema == operation_tool_output_schema(name, mcp_server.FEATURES), name
        assert wire_tools[name]["outputSchema"] == registered.output_schema, name
        if name == "local_ai_rag":
            results_schema = registered.output_schema["x-action-output-contracts"]["search"]["results"]
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
