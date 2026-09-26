from __future__ import annotations

import threading

import pytest


@pytest.fixture
def live_api(tmp_path, monkeypatch):
    from local_ai_hub import http_server
    from local_ai_hub.app import LocalAIApp
    from local_ai_hub.client import HubClient

    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    state_dir = tmp_path / "state"
    config = tmp_path / "config.toml"
    config.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = {server.server_address[1]}\n'
        f'state_dir = "{state_dir.as_posix()}"\n',
        encoding="utf-8",
    )
    app = LocalAIApp(str(config))
    monkeypatch.setattr(http_server, "APP", app)
    client = HubClient(config_path=str(config), auto_start=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield app, client
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        app.close()


def test_resolve_imports_get_and_post_share_auto_default(live_api):
    app, client = live_api
    calls = []

    def resolve_imports(root, symbols, language):
        calls.append((root, symbols, language))
        return {"success": True, "language": language}

    app.services.resolve_imports = resolve_imports

    get_result = client.get("/api/resolve_imports?root=repo&symbol=Thing")
    post_result = client.post("/api/resolve_imports", {"root": "repo", "symbol": "Thing"})

    assert get_result["language"] == "auto"
    assert post_result["language"] == "auto"
    assert calls == [("repo", ["Thing"], "auto"), ("repo", ["Thing"], "auto")]


def test_unsupported_chat_completions_rejects_before_payload_validation(live_api):
    _app, client = live_api

    result = client.post("/api/chat/completions", {"messages": []})

    assert result["success"] is False
    assert result["status_code"] == 404
    assert "messages" not in result["error"]


def test_lean_rag_description_lists_every_supported_action(monkeypatch):
    from local_ai_hub import mcp_server

    monkeypatch.setattr(mcp_server, "LEAN_SCHEMAS", True)
    description = mcp_server._desc_rag()

    for action in (
        "index",
        "search",
        "list",
        "docset_index",
        "docset_search",
        "ingest_document",
        "ingest_diagram",
    ):
        assert action in description
    for control in ("max_response_tokens", "response_profile", "delta", "reuse_key", "extra_fields"):
        assert control in description


def test_lean_work_description_lists_continuation_and_response_controls(monkeypatch):
    from local_ai_hub import mcp_server

    monkeypatch.setattr(mcp_server, "LEAN_SCHEMAS", True)
    description = mcp_server._desc_work()

    for control in (
        "continue",
        "return_fields",
        "max_output_tokens",
        "max_response_tokens",
        "response_profile",
        "reuse_key",
        "extra_fields",
        "delta",
    ):
        assert control in description


def test_semantic_diff_action_uses_public_call_graph_diff_route(monkeypatch):
    from local_ai_hub import mcp_server

    captured = {}

    def fake_post(path, payload, **kwargs):
        captured.update(path=path, payload=payload)
        return {"success": True, "changes": []}

    monkeypatch.setattr(mcp_server.CLIENT, "post", fake_post)
    result = mcp_server.local_ai_repo(
        action="semantic_diff",
        root="repo",
        diff="diff --git a/a.cs b/a.cs",
    )

    assert result.get("success") is True, result
    assert captured["path"] == "/api/repo/call_graph_diff"
    assert captured["payload"]["root"].endswith("repo")
    assert captured["payload"]["diff"] == "diff --git a/a.cs b/a.cs"
