from local_ai_hub import mcp_server


def test_lean_coord_description_lists_every_supported_action(monkeypatch):
    monkeypatch.setattr(mcp_server, "LEAN_SCHEMAS", True)

    supported = set(mcp_server.FEATURES.supported_coord_actions())
    description = mcp_server._desc_coord()

    missing = sorted(action for action in supported if action not in description)
    assert not missing, f"supported coordination actions missing from MCP description: {missing}"
    assert "skip Hub and use the authorized native tool directly" in description
    assert "task_data" in description and "no free-form `notes` field" in description
    assert "On a revision conflict, reload with `plan_get`" in description
    assert "Omit `blocker` when there is no blocker" in description
    assert "`clarifications` entries must be objects" in description
    assert "for large plans prefer `plan_board_view`" in description
    assert "never replay the unchanged oversized request" in description
    assert "repeat the same rejected cap" in description
    assert "If a `plan_task_edit` response has `mutation_applied=true`" in description
    assert "the edit already happened: do not retry it" in description
