from types import SimpleNamespace

import pytest

from local_ai_hub import mcp_server
from local_ai_hub.features import FeatureSet


@pytest.fixture
def isolated_mcp_wrappers(monkeypatch):
    monkeypatch.setattr(
        mcp_server,
        "FEATURES",
        FeatureSet({"features": {"rag": True, "work_orchestrator": True}}),
    )
    monkeypatch.setattr(mcp_server, "configured_state_dir", lambda *args, **kwargs: ".")
    monkeypatch.setattr(
        mcp_server,
        "load_operational_mode",
        lambda *_args, **_kwargs: mcp_server.OperationalModeSnapshot("active", 1, None),
    )
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **_kwargs: None)
    monkeypatch.setattr(mcp_server, "_record_adoption", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mcp_server, "_client_root", lambda root: root)
    monkeypatch.setattr(mcp_server, "validate_operation_output", lambda *_args, **_kwargs: None)


@pytest.mark.parametrize("action", ["INDEX", "docset-search", " search ", []])
def test_rag_public_wrapper_rejects_noncanonical_actions_before_root_or_client(action, isolated_mcp_wrappers, monkeypatch):
    root_calls = []
    client_calls = []
    monkeypatch.setattr(mcp_server, "_client_root", lambda root: root_calls.append(root))
    monkeypatch.setattr(mcp_server, "CLIENT", SimpleNamespace(get=lambda *a, **k: client_calls.append(("get", a, k))))

    result = mcp_server.local_ai_rag(action=action)

    assert result["success"] is False
    assert "Unknown local_ai_rag action" in result["error"]
    assert root_calls == []
    assert client_calls == []


@pytest.mark.parametrize("action", ["SUBMIT", " submit ", "wait-status", []])
def test_work_public_wrapper_rejects_noncanonical_actions_before_root_or_client(action, isolated_mcp_wrappers, monkeypatch):
    root_calls = []
    client_calls = []
    monkeypatch.setattr(mcp_server, "_client_root", lambda root: root_calls.append(root))
    monkeypatch.setattr(mcp_server, "CLIENT", SimpleNamespace(post=lambda *a, **k: client_calls.append(("post", a, k))))

    result = mcp_server.local_ai_work(action=action)

    assert result["success"] is False
    assert "Unknown local_ai_work action" in result["error"]
    assert root_calls == []
    assert client_calls == []


def test_canonical_rag_and_work_actions_reach_only_fake_client(isolated_mcp_wrappers, monkeypatch, tmp_path):
    calls = []

    class FakeClient:
        def get(self, path, **kwargs):
            calls.append(("get", path))
            return {"success": True, "workspaces": []}

        def post(self, path, payload, **kwargs):
            calls.append(("post", path, payload))
            return {"success": True, "status": "accepted"}

    monkeypatch.setattr(mcp_server, "CLIENT", FakeClient())
    mcp_server.local_ai_rag(action="list")
    mcp_server.local_ai_work(action="submit", root=str(tmp_path), task="bounded fixture task")

    assert calls[0] == ("get", "/api/rag/workspaces")
    assert calls[1][0:2] == ("post", "/api/work-orders")
    assert calls[1][2]["action"] == "submit"
