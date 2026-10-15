from __future__ import annotations

from pathlib import Path

from local_ai_hub import mcp_server
from local_ai_hub.operation_contracts import (
    operation_tool_input_schema,
    operation_tool_output_schema,
    validate_operation_call,
)


def test_status_contract_has_no_legacy_action_field():
    overlay_root = Path(__file__).resolve().parents[1]
    assert Path(mcp_server.__file__).resolve() == overlay_root / "src/local_ai_hub/mcp_server.py"

    tool = mcp_server.mcp._tool_manager._tools["local_ai_status"]
    expected_input = operation_tool_input_schema("local_ai_status", mcp_server.FEATURES)
    expected_output = operation_tool_output_schema("local_ai_status", mcp_server.FEATURES)
    assert "action" not in expected_input["properties"]
    assert "action" not in tool.parameters["properties"]
    assert tool.parameters == expected_input
    assert tool.fn_metadata.output_schema == expected_output

    for legacy_action in ("status", "health", "check", "info"):
        result = validate_operation_call(
            "local_ai_status", {"action": legacy_action}, mcp_server.FEATURES
        )
        assert result is not None
        assert result[0] == 400
