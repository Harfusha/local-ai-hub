from __future__ import annotations

from pathlib import Path
from typing import get_args

from local_ai_hub import mcp_server
from local_ai_hub.operation_contracts import (
    operation_actions,
    operation_tool_input_schema,
    operation_tool_output_schema,
)


def test_status_alias_type_and_registered_mcp_schema_are_unchanged():
    expected_aliases = ("status", "health", "check", "info")
    overlay_root = Path(__file__).resolve().parents[1]
    assert Path(mcp_server.__file__).resolve() == overlay_root / "src/local_ai_hub/mcp_server.py"
    expected_type_values = tuple(dict.fromkeys((
        *operation_actions("local_ai_status"), *expected_aliases,
    )))
    assert get_args(mcp_server.StatusAction) == expected_type_values

    tool = mcp_server.mcp._tool_manager._tools["local_ai_status"]
    expected_input = operation_tool_input_schema("local_ai_status", mcp_server.FEATURES)
    expected_output = operation_tool_output_schema("local_ai_status", mcp_server.FEATURES)
    assert tool.parameters == expected_input
    assert tool.parameters["properties"]["action"]["enum"] == list(expected_type_values)
    assert tool.fn_metadata.output_schema == expected_output
