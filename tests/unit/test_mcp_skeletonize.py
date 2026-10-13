def test_skeletonize_mcp_payload_includes_root(monkeypatch):
    captured = {}
    class DummyClient:
        def post(self, url, payload, **kwargs):
            captured.update(payload)
            return {"success": True, "skeleton": "def foo(): ..."}
    monkeypatch.setattr("local_ai_hub.mcp_server.CLIENT", DummyClient())
    from local_ai_hub.mcp_server import local_ai_repo
    local_ai_repo(action="skeletonize", root="C:/test/root", task="def bar():\n    pass")
    assert captured.get("root") == "C:/test/root"
    assert captured.get("code") == "def bar():\n    pass"
