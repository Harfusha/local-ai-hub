from __future__ import annotations

import threading

import pytest


@pytest.fixture
def live_api(tmp_path, monkeypatch):
    from local_ai_hub import http_server
    from local_ai_hub.app import LocalAIApp
    from local_ai_hub.client import HubClient

    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    config = tmp_path / "config.toml"
    config.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = {server.server_address[1]}\n'
        f'state_dir = "{(tmp_path / "state").as_posix()}"\n',
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


def test_unsupported_chat_completions_rejects_valid_payload(live_api):
    _app, client = live_api
    result = client.post("/api/chat/completions", {"messages": [{"role": "user", "content": "hello"}]})
    assert result["success"] is False
    assert result["status_code"] == 404
    assert "messages" not in result["error"]


@pytest.mark.parametrize("messages", ["not-a-list", [], [{}] * 129, [{"role": "user", "content": "x" * 1_000_001}]])
def test_unsupported_chat_completions_invalid_payloads_reach_404(live_api, messages):
    _app, client = live_api
    result = client.post("/api/chat/completions", {"messages": messages})
    assert result["success"] is False
    assert result["status_code"] == 404


def test_client_list_tasks_serializes_query_and_preserves_positional_args(tmp_path, monkeypatch):
    from local_ai_hub.client import HubClient

    config = tmp_path / "config.toml"
    config.write_text(
        f"[server]\nport=39123\nstate_dir='{(tmp_path / 'state').as_posix()}'\n",
        encoding="utf-8",
    )
    client = HubClient(config_path=str(config), auto_start=False)
    calls = []
    monkeypatch.setattr(client, "post", lambda path, payload, **_kwargs: calls.append((path, dict(payload))) or {"success": True})

    client.list_tasks("active", 12)
    client.list_tasks("active", 12, query="needle")

    assert calls == [
        ("/api/agent-state/tasks", {"action": "list", "limit": 12, "status": "active"}),
        ("/api/agent-state/tasks", {"action": "list", "limit": 12, "status": "active", "query": "needle"}),
    ]
