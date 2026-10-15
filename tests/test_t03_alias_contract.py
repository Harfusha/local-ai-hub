from __future__ import annotations

from local_ai_hub import mcp_server
from local_ai_hub.operation_contracts import operation_actions, validate_operation_call


def test_mcp_action_schema_and_dispatch_reject_noncanonical_action():
    tool = mcp_server.mcp._tool_manager._tools["local_ai_coord"]
    action_schema = tool.parameters["properties"]["action"]
    assert action_schema["enum"] == list(operation_actions("local_ai_coord", mcp_server.FEATURES))
    assert "task_new" not in action_schema["enum"]
    assert "task_create" in action_schema["enum"]

    rejection = validate_operation_call(
        "local_ai_coord", {"action": "task_new", "task": "alias contract"},
        features=mcp_server.FEATURES,
    )
    assert rejection is not None
    assert rejection[0] == 400
