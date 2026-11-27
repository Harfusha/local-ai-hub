from __future__ import annotations

import asyncio

from local_ai_hub import mcp_server
import mcp.types as t


def test_tools_list_wire_exposes_action_scoped_repo_steps() -> None:
    request = t.ListToolsRequest(method="tools/list")
    result = asyncio.run(
        mcp_server.mcp._mcp_server.request_handlers[t.ListToolsRequest](request)
    )

    tool = next(item for item in result.root.tools if item.name == "local_ai_repo")
    schema = tool.inputSchema
    pipeline_rule = next(
        constraint for constraint in schema.get("then", {}).get("allOf", [])
        if constraint.get("if", {}).get("properties", {}).get("action", {}).get("const") == "pipeline"
    )
    assert "steps" not in pipeline_rule.get("then", {}).get("not", {}).get("anyOf", [])
    search_rule = next(
        constraint for constraint in schema.get("then", {}).get("allOf", [])
        if constraint.get("if", {}).get("properties", {}).get("action", {}).get("const") == "search"
    )
    assert {"required": ["steps"]} in search_rule.get("then", {}).get("not", {}).get("anyOf", [])


def test_context_compile_minimum_wire_budget_keeps_recovery_instruction() -> None:
    import json

    from local_ai_hub.token_accounting import json_tokens

    content, structured = mcp_server._mcp_budget_payload(
        "local_ai_coord",
        {"action": "context_compile", "max_response_tokens": 128, "response_profile": "minimal"},
        {"success": False, "error": "max_response_tokens too small",
         "next_action": "request_larger_response_budget",
         "response_budget": {"requested_tokens": 128, "returned_tokens": 0, "rejected": True}},
    )
    value = structured if structured is not None else json.loads(content[0].text)
    assert value["success"] is False
    assert value["next_action"] == "request_larger_response_budget"
    assert value["response_budget"]["rejected"] is True
    wire = {"content": [item.model_dump(mode="json", exclude_none=True) for item in content], "isError": False}
    if structured is not None:
        wire["structuredContent"] = structured
    assert json_tokens(wire) <= 128


def test_context_compile_lost_artifact_pointer_returns_exact_recovery(monkeypatch) -> None:
    import json

    from local_ai_hub.token_accounting import json_tokens

    pointer = "artifact-" + "a" * 64
    rejected = {"success": False, "error": "max_response_tokens too small"}
    monkeypatch.setattr(mcp_server, "_build_mcp_budget_payload",
                        lambda *args: ([t.TextContent(type="text", text=json.dumps(rejected))], rejected))
    content, structured = mcp_server._mcp_budget_payload(
        "local_ai_coord",
        {"action": "context_compile", "max_response_tokens": 1024, "response_profile": "compact"},
        {"success": False, "task_context_artifact_id": pointer, "next_action": "read_task_context_artifact"},
    )
    value = structured if structured is not None else json.loads(content[0].text)
    assert value["success"] is False and value["complete"] is False
    assert value["task_context_artifact_id"] == pointer
    assert value["next_action"] == "read_task_context_artifact"
    wire = {"content": [item.model_dump(mode="json", exclude_none=True) for item in content], "isError": False}
    if structured is not None:
        wire["structuredContent"] = structured
    assert json_tokens(wire) <= 1024
