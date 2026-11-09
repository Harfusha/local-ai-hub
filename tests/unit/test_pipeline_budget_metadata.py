from local_ai_hub.response_budget import budget_response, json_tokens


def test_unmodified_small_response_with_accounting_is_not_truncated():
    original = {"success": True, "path": "small.py", "line_count": 2}
    result = budget_response(original, max_tokens=8192, token_metadata={"activity": "test"})
    assert result["path"] == "small.py"
    assert result["response_budget"]["truncated"] is False
    assert result["response_budget"]["returned_tokens"] == json_tokens(result)


def test_existing_truncation_is_not_erased():
    original = {"success": True, "response_budget": {"truncated": True}, "path": "small.py"}
    result = budget_response(original, max_tokens=8192, token_metadata={"activity": "test"})
    assert result["response_budget"]["truncated"] is True


def test_large_response_still_obeys_hard_cap_and_reports_truncation():
    original = {"success": True, "text": "x" * 20000}
    result = budget_response(original, max_tokens=256, token_metadata={"activity": "test"})
    assert json_tokens(result) <= 256
    assert result["response_budget"]["truncated"] is True


def test_accounting_that_crowds_out_payload_reports_truncation():
    observed_reduction = False
    for size in range(80, 801, 40):
        original = {"success": True, "text": "x" * size}
        if json_tokens(original) > 128:
            break
        result = budget_response(original, max_tokens=128, token_metadata={"activity": "test"})
        assert json_tokens(result) <= 128
        if result.get("text") != original["text"]:
            observed_reduction = True
            assert result["response_budget"]["truncated"] is True
    assert observed_reduction, "test did not exercise metadata crowding"


def test_small_pipeline_step_through_loopback_mcp(tmp_path, monkeypatch):
    import asyncio
    import threading

    from local_ai_hub import http_server, mcp_server
    from local_ai_hub.app import LocalAIApp
    from local_ai_hub.client import HubClient

    project = tmp_path / "project"
    project.mkdir()
    (project / "small.py").write_text("value = 1\n", encoding="utf-8")
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
            "action": "pipeline", "root": str(project), "response_profile": "compact",
            "steps": [{"id": "stat", "action": "file_info", "path": "small.py"}],
        }))
        step = result["step_results"][0]["result"]
        assert step["success"] is True, result
        assert step["exists"] is True and step["line_count"] == 1
        assert step["response_budget"]["truncated"] is False
        assert result["response_budget"]["truncated"] is False
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)
        app.close()
