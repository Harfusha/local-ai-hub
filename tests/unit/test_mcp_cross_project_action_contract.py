from local_ai_hub import mcp_server
from local_ai_hub.features import FeatureSet
from local_ai_hub.operation_contracts import operation_actions, validate_operation_arguments


_CURRENT_ACTIONS = ("cross_project_graph", "cross_project_symbols", "cross_project_impact")
_RETIRED_NAMES = ("cross_repo_graph", "cross_repo_symbols", "cross_repo_impact")


def test_repo_action_schema_and_contract_use_only_current_cross_project_names():
    features = FeatureSet({"features": {"agent_os": True}})
    available = operation_actions("local_ai_repo", features)
    advertised = tuple(mcp_server.RepoAction.__args__)

    assert all(action in available and action in advertised for action in _CURRENT_ACTIONS)
    assert all(action not in available and action not in advertised for action in _RETIRED_NAMES)
    assert "cross_repo_contract" in available and "cross_repo_contract" in advertised
    for action in _RETIRED_NAMES:
        assert validate_operation_arguments("local_ai_repo", action, {}, features=features)


def test_repo_wrapper_rejects_retired_cross_repo_names_before_client(monkeypatch, tmp_path):
    features = FeatureSet({"features": {"agent_os": True}})
    monkeypatch.setattr(mcp_server, "FEATURES", features)
    monkeypatch.setattr(mcp_server, "configured_state_dir", lambda *_args, **_kwargs: str(tmp_path))
    monkeypatch.setattr(
        mcp_server,
        "load_operational_mode",
        lambda *_args, **_kwargs: mcp_server.OperationalModeSnapshot("active", 1, None),
    )
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **_kwargs: None)
    monkeypatch.setattr(mcp_server, "_record_adoption", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mcp_server, "_client_root", lambda root: root)
    calls = []
    monkeypatch.setattr(mcp_server, "CLIENT", type("FakeClient", (), {"post": lambda *_args, **_kwargs: calls.append("post")})())

    for action in _RETIRED_NAMES:
        result = mcp_server.local_ai_repo(action=action, root=str(tmp_path))
        assert result["success"] is False
    assert calls == []


def test_current_cross_project_actions_reach_the_matching_fake_http_routes(monkeypatch, tmp_path):
    features = FeatureSet({"features": {"agent_os": True}})
    monkeypatch.setattr(mcp_server, "FEATURES", features)
    monkeypatch.setattr(mcp_server, "configured_state_dir", lambda *_args, **_kwargs: str(tmp_path))
    monkeypatch.setattr(
        mcp_server,
        "load_operational_mode",
        lambda *_args, **_kwargs: mcp_server.OperationalModeSnapshot("active", 1, None),
    )
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **_kwargs: None)
    monkeypatch.setattr(mcp_server, "_record_adoption", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mcp_server, "_client_root", lambda root: root)
    calls = []

    class FakeClient:
        def post(self, path, payload, **kwargs):
            calls.append((path, payload))
            return {"success": True}

    monkeypatch.setattr(mcp_server, "CLIENT", FakeClient())
    for action in _CURRENT_ACTIONS:
        mcp_server.local_ai_repo(action=action, root=str(tmp_path), query="Symbol")

    assert [path for path, _payload in calls] == [
        "/api/cross_project_graph",
        "/api/cross_project_symbols",
        "/api/cross_project_impact",
    ]
