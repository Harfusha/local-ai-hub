def test_context_infers_guarded_when_changed_paths_provided(monkeypatch):
    captured = {}
    class DummyClient:
        def post(self, url, payload, **kwargs):
            captured.update(payload)
            return {"success": True, "context": "test"}
    monkeypatch.setattr("local_ai_hub.mcp_server.CLIENT", DummyClient())
    from local_ai_hub.mcp_server import local_ai_repo

    res = local_ai_repo(action="context", root="C:/test/root", query="my task", changed_paths=["src/a.py"])
    assert res.get("success") is True
    assert captured.get("guarded") is True
    assert captured.get("changed_paths") == ["src/a.py"]

def test_context_infers_guarded_when_focus_provided(monkeypatch):
    captured = {}
    class DummyClient:
        def post(self, url, payload, **kwargs):
            captured.update(payload)
            return {"success": True, "context": "test"}
    monkeypatch.setattr("local_ai_hub.mcp_server.CLIENT", DummyClient())
    from local_ai_hub.mcp_server import local_ai_repo

    res = local_ai_repo(action="context", root="C:/test/root", query="my task", focus=["src/a.py"])
    assert res.get("success") is True
    assert captured.get("guarded") is True
    assert captured.get("focus") == ["src/a.py"]
