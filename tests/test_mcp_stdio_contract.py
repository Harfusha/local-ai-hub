from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from local_ai_hub.operation_contracts import MCP_OPERATION_CONTRACTS, operation_tool_output_schema


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

    completed = subprocess.run(
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
        input="".join(json.dumps(message, separators=(",", ":")) + "\n" for message in messages),
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr[-2000:]
    responses = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
    initialize = next(response for response in responses if response.get("id") == 1)
    listing = next(response for response in responses if response.get("id") == 2)
    assert initialize.get("result", {}).get("protocolVersion") == "2025-06-18"
    wire_tools = {tool["name"]: tool for tool in listing["result"]["tools"]}
    expected_names = set(mcp_server.FEATURES.enabled_tools)
    assert set(wire_tools) == expected_names
    assert expected_names == {
        contract.name
        for contract in MCP_OPERATION_CONTRACTS
        if contract.name in mcp_server.FEATURES.enabled_tools
    }

    for name in expected_names:
        registered = mcp_server.mcp._tool_manager._tools[name]
        assert wire_tools[name]["inputSchema"] == registered.parameters, name
        assert registered.output_schema is not None, name
        action_enum = registered.parameters.get("properties", {}).get("action", {}).get("enum", [])
        assert registered.output_schema == operation_tool_output_schema(name, action_enum), name
        assert wire_tools[name]["outputSchema"] == registered.output_schema, name
        if name == "local_ai_rag":
            results_schema = registered.output_schema["properties"]["results"]
            assert results_schema["type"] == "array"
            assert results_schema["items"]["properties"]["chunk_no"] == {"type": "integer"}
            assert registered.output_schema["x-action-output-contracts"]["search"]["properties"]["results"] == results_schema


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
    completed = subprocess.run(
        [sys.executable, "-B", "-c", "from local_ai_hub import mcp_server; "
         "mcp_server.CLIENT.ensure_server = lambda **_kwargs: True; mcp_server.main()"],
        cwd=root,
        env=env,
        input="".join(json.dumps(message, separators=(",", ":")) + "\n" for message in messages),
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr[-2000:]
    responses = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
    listing = next(response for response in responses if response.get("id") == 2)
    wire_tools = {tool["name"]: tool for tool in listing["result"]["tools"]}
    assert "local_ai_rag" not in wire_tools
    assert "local_ai_command" not in wire_tools
    assert all(tool.get("outputSchema") for tool in wire_tools.values())
