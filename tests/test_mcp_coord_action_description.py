from local_ai_hub import mcp_server


def test_lean_coord_description_lists_every_supported_action(monkeypatch):
    monkeypatch.setattr(mcp_server, "LEAN_SCHEMAS", True)

    supported = set(mcp_server.FEATURES.supported_coord_actions())
    description = mcp_server._desc_coord()

    missing = sorted(action for action in supported if action not in description)
    assert not missing, f"supported coordination actions missing from MCP description: {missing}"
