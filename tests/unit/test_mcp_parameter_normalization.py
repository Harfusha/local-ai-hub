def test_mcp_command_accepts_root_and_normalizes_to_cwd(monkeypatch):
    captured = {}
    class DummyClient:
        def post(self, url, payload, **kwargs):
            captured.update(payload)
            return {"success": True, "exit_code": 0, "stdout": "1\n"}
    monkeypatch.setattr("local_ai_hub.mcp_server.CLIENT", DummyClient())
    from local_ai_hub.mcp_server import local_ai_command

    res = local_ai_command(action="run", root="C:/test/root", command="echo 1")
    assert res.get("success") is True
    assert captured.get("cwd") == "C:/test/root" or captured.get("cwd").startswith("C:")

def test_mcp_repo_accepts_paths_and_normalizes_to_changed_paths(monkeypatch):
    captured = {}
    class DummyClient:
        def post(self, url, payload, **kwargs):
            captured.update(payload)
            return {"success": True, "results": []}
    monkeypatch.setattr("local_ai_hub.mcp_server.CLIENT", DummyClient())
    from local_ai_hub.mcp_server import local_ai_repo

    res = local_ai_repo(action="context", root="C:/test/root", query="find test", paths=["foo.py", "bar.py"])
    assert res.get("success") is True
    assert captured.get("changed_paths") == ["foo.py", "bar.py"]

def test_mcp_repo_accepts_symbol_and_normalizes_to_query(monkeypatch):
    captured = {}
    class DummyClient:
        def post(self, url, payload, **kwargs):
            captured.update(payload)
            return {"success": True, "results": []}
    monkeypatch.setattr("local_ai_hub.mcp_server.CLIENT", DummyClient())
    from local_ai_hub.mcp_server import local_ai_repo

    res = local_ai_repo(action="callers", root="C:/test/root", symbol="my_func")
    assert res.get("success") is True
    assert captured.get("symbol") == "my_func" or captured.get("query") == "my_func"
