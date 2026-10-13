from pathlib import Path
from local_ai_hub.rag import RAGStore

def test_rag_auto_resolves_workspace_from_root(tmp_path):
    store = RAGStore({"server": {"state_dir": str(tmp_path)}}, services=None)
    ws_id = store.workspace_id(str(tmp_path))
    assert ws_id.startswith(f"{tmp_path.name}-")
    assert len(ws_id.split("-")[-1]) == 12

def test_mcp_rag_resolves_workspace_when_empty_or_path(monkeypatch, tmp_path):
    captured = {}
    class DummyClient:
        def post(self, url, payload, **kwargs):
            captured.update(payload)
            return {"success": True, "results": []}
    monkeypatch.setattr("local_ai_hub.mcp_server.CLIENT", DummyClient())
    from local_ai_hub.mcp_server import local_ai_rag
    
    # Empty workspace with root
    local_ai_rag(action="search", root=str(tmp_path), query="test query")
    expected_ws = RAGStore.workspace_id(str(tmp_path))
    assert captured.get("workspace") == expected_ws

    # Workspace passed as a root path instead of hash ID
    captured.clear()
    local_ai_rag(action="search", root=str(tmp_path), workspace=str(tmp_path), query="test query")
    assert captured.get("workspace") == expected_ws
