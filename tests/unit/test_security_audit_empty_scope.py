from types import SimpleNamespace

from local_ai_hub.deterministic import DeterministicEngine


def test_zero_scanned_files_cannot_be_certified_clean(tmp_path):
    inventory = {"complete": True, "reasons": [], "_identity": {}}
    engine = SimpleNamespace(
        _root=lambda _: str(tmp_path),
        repo_tools=SimpleNamespace(
            security_inventory=lambda *_args, **_kwargs: ([], dict(inventory)),
            max_file_bytes=2_000_000,
        ),
    )
    result = DeterministicEngine.security_audit(engine, str(tmp_path))
    assert result["scanned_files"] == 0
    assert result["scan_complete"] is False
    assert result["is_clean"] is False
    assert result["stop_reason"] == "no_files_scanned"


def test_empty_security_audit_on_loopback_mcp(tmp_path, monkeypatch):
    import asyncio
    import json
    import threading

    from local_ai_hub import http_server, mcp_server
    from local_ai_hub.app import LocalAIApp
    from local_ai_hub.client import HubClient

    project = tmp_path / "project"
    project.mkdir()
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    config = tmp_path / "hub-test.toml"
    config.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = {server.server_address[1]}\n'
        f'state_dir = "{(tmp_path / "state").as_posix()}"\n'
        f'[security]\nallowed_roots = ["{project.as_posix()}"]\n',
        encoding="utf-8",
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
        contents, result = asyncio.run(mcp_server.mcp.call_tool("local_ai_repo", {
            "action": "security_audit", "root": str(project), "response_profile": "compact",
        }))
        assert result["scanned_files"] == 0
        assert result["scan_complete"] is False
        assert result["is_clean"] is False
        assert result["stop_reason"] == "no_files_scanned"
        assert json.loads(contents[0].text)["is_clean"] is False
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)
        app.close()
