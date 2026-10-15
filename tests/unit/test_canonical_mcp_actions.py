import inspect

from local_ai_hub import mcp_server
from local_ai_hub.operation_contracts import (
    operation_actions,
    operation_tool_input_schema,
    validate_operation_call,
)


def test_registered_action_enums_publish_only_canonical_names():
    for tool in ("local_ai_repo", "local_ai_task", "local_ai_command", "local_ai_coord"):
        schema = operation_tool_input_schema(tool, mcp_server.FEATURES)
        assert schema["properties"]["action"]["enum"] == list(operation_actions(tool, mcp_server.FEATURES))
        manager = getattr(mcp_server.mcp, "_tool_manager", None)
        registered = getattr(manager, "_tools", {}).get(tool) if manager is not None else None
        assert registered is not None
        assert registered.parameters["properties"]["action"]["enum"] == list(
            operation_actions(tool, mcp_server.FEATURES)
        )
    removed_repo_actions = {"sec", "idx", "ctx", "review"}
    assert not removed_repo_actions.intersection(
        operation_tool_input_schema("local_ai_repo", mcp_server.FEATURES)["properties"]["action"]["enum"]
    )


def test_short_and_normalized_action_aliases_are_rejected():
    aliases = {
        "local_ai_repo": ("sec", "idx", "review", "ctx"),
        "local_ai_task": ("gen", "rev", "del"),
        "local_ai_command": ("patch", "fix", "repair", "fmt"),
        "local_ai_coord": (
            "ctx", "compile_ctx", "neg_rec", "neg_find", "mem_put", "mem_rec",
            "mem_get", "mem_find", "mem_search", "task_new", "task_chk", "task_done",
        ),
    }
    for tool, values in aliases.items():
        for action in values:
            rejection = validate_operation_call(
                tool, {"action": action, "root": "."}, features=mcp_server.FEATURES,
            )
            assert rejection is not None
            assert rejection[0] == 400
            assert "invalid action" in rejection[1]

    for action in ("SEC", "security-audit"):
        rejection = validate_operation_call(
            "local_ai_repo", {"action": action, "root": "."}, features=mcp_server.FEATURES,
        )
        assert rejection is not None
        assert rejection[0] == 400
        assert "invalid action" in rejection[1]


def test_registered_repo_tool_rejects_alias_before_client_call(monkeypatch):
    calls = []
    monkeypatch.setattr(mcp_server, "operational_mode_gate_error", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        mcp_server.CLIENT,
        "post",
        lambda *args, **kwargs: calls.append((args, kwargs)) or {"success": True},
    )

    result = mcp_server.local_ai_repo(action="sec", root="/repo")

    assert calls == []
    assert result["status_code"] == 400
    assert result["terminal"] is True
    assert result["retryable"] is False


def test_status_selector_is_detail_only_and_rejects_action_backdoor():
    assert "action" not in inspect.signature(mcp_server.local_ai_status).parameters
    assert "action" not in operation_tool_input_schema(
        "local_ai_status", mcp_server.FEATURES,
    )["properties"]
    rejection = validate_operation_call(
        "local_ai_status", {"action": "health"}, features=mcp_server.FEATURES,
    )
    assert rejection is not None
    assert rejection[0] == 400
    assert "unexpected argument" in rejection[1]
