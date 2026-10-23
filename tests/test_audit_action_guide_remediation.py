from __future__ import annotations

import pytest


@pytest.mark.parametrize("tool,action,required,excluded", [
    ("local_ai_repo", "context", "query", "task"),
    ("local_ai_repo", "solve", "task", "task_id"),
    ("local_ai_coord", "memory_find", None, "limit"),
])
def test_action_guide_is_narrowed_from_the_canonical_contract(tool, action, required, excluded):
    import local_ai_hub.operation_contracts as module
    guide = getattr(module, "operation_action_guide", None)
    assert callable(guide), "action-specific help must come from the canonical registry"
    result = guide(tool, action)
    assert result["success"] is True, result
    assert excluded not in result["input_schema"]["properties"]
    if required:
        assert required in result["input_schema"]["required"]
    assert module.validate_operation_arguments(tool, action, result["example"]) is None


def test_retired_public_guide_rejects_before_health_queries(monkeypatch):
    import asyncio
    import local_ai_hub.mcp_server as module
    def forbidden(*args, **kwargs):
        pytest.fail("retired guide must not query runtime health")
    monkeypatch.setattr(module.CLIENT, "get", forbidden)
    result = asyncio.run(module.mcp.call_tool("local_ai_status", {
        "detail": "guide", "guide_tool": "local_ai_repo", "guide_action": "context"}))[1]
    assert result["success"] is False
    assert result["status_code"] == 400


def test_guide_fields_are_rejected_for_regular_status_actions():
    from local_ai_hub.operation_contracts import validate_operation_call
    result = validate_operation_call("local_ai_status", {"detail": "brief", "guide_tool": "local_ai_repo", "guide_action": "context"})
    assert result and result[0] == 400


def test_argument_hint_lists_only_fields_allowed_for_the_selected_action():
    import local_ai_hub.operation_contracts as module
    hint = getattr(module, "operation_argument_hint", None)
    assert callable(hint)
    result = hint("local_ai_coord", "memory_find")
    assert "limit" not in result["allowed_arguments"]
    assert "required_arguments" in result
    assert "help_call" not in result
