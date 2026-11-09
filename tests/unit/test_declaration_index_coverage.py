from types import SimpleNamespace

from local_ai_hub.code_index import CodeIndex


def test_empty_index_does_not_claim_repository_absence():
    index = SimpleNamespace(find_symbol=lambda *args, **kwargs: {"success": True, "symbols": []})
    result = CodeIndex.find_declaration(index, "/fixture", "normalize_path")
    assert result["success"] is False
    assert result["error_code"] == "declaration_not_found"
    assert result["coverage"]["complete"] is False
    assert result["coverage"]["scope"] == "indexed_symbols"
    assert result["freshness"]["status"] == "not_checked"
    assert "index" in result["error"].lower()


def test_index_failure_is_not_replaced_by_not_found():
    failure = {"success": False, "status_code": 503, "error": "index unavailable", "retryable": True}
    index = SimpleNamespace(find_symbol=lambda *args, **kwargs: failure)
    assert CodeIndex.find_declaration(index, "/fixture", "normalize_path") == failure


def test_existing_declaration_is_preserved():
    symbol = {"name": "normalize_path", "path": "module.py", "line": 2}
    index = SimpleNamespace(find_symbol=lambda *args, **kwargs: {"success": True, "symbols": [symbol]})
    result = CodeIndex.find_declaration(index, "/fixture", "normalize_path")
    assert result == {"success": True, "declaration": symbol}


def test_unindexed_declaration_through_loopback_mcp(tmp_path, monkeypatch):
    import asyncio
    import threading

    from local_ai_hub import http_server, mcp_server
    from local_ai_hub.app import LocalAIApp
    from local_ai_hub.client import HubClient

    project = tmp_path / "project"
    project.mkdir()
    (project / "module.py").write_text("def normalize_path(path):\n    return path\n", encoding="utf-8")
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    config = tmp_path / "hub-test.toml"
    config.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = {server.server_address[1]}\n'
        f'state_dir = "{(tmp_path / "state").as_posix()}"\n'
        f'[security]\nallowed_roots = ["{project.as_posix()}"]\n', encoding="utf-8",
    )
    app = LocalAIApp(str(config))
    monkeypatch.setattr(http_server, "APP", app)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    client = HubClient(config_path=str(config), auto_start=False)
    monkeypatch.setattr(mcp_server, "CLIENT", client)
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **_: None)
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, "record", lambda _event: None)
    try:
        _, result = asyncio.run(mcp_server.mcp.call_tool("local_ai_repo", {
            "action": "definition", "root": str(project), "query": "normalize_path",
            "response_profile": "compact",
        }))
        assert result["success"] is False, result
        assert result["error_code"] == "declaration_not_found"
        assert result["coverage"]["complete"] is False
        assert result["freshness"]["status"] == "not_checked"
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)
        app.close()
