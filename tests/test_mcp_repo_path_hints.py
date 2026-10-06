from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from local_ai_hub import mcp_server


def test_repo_search_forwards_known_path_as_scoped_path_hint(monkeypatch, tmp_path):
    calls = []

    def post(path, payload, **kwargs):
        calls.append({"path": path, "payload": payload, "kwargs": kwargs})
        return {"success": True, "results": []}

    monkeypatch.setattr(mcp_server, "CLIENT", SimpleNamespace(post=post))

    result = mcp_server.local_ai_repo(
        action="search",
        root=str(tmp_path),
        query="button",
        path="templates/element",
    )

    assert result["success"] is True
    search_call = next(call for call in calls if call["path"] == "/api/search")
    assert search_call["path"] == "/api/search"
    assert search_call["kwargs"]["path_hints"] == [
        {
            "path": "templates/element",
            "purpose": "repository_search",
            "scope": "repo_search",
        }
    ]


def test_repo_search_forwards_legacy_path_before_typed_path_hints(
    monkeypatch, tmp_path
):
    captured = {}

    def post(path, payload, **kwargs):
        captured.update(path=path, payload=payload, kwargs=kwargs)
        return {"success": True, "results": []}

    monkeypatch.setattr(mcp_server, "CLIENT", SimpleNamespace(post=post))
    supplied_hint = {
        "path": "src/auth.py",
        "purpose": "repository_search",
        "scope": "repo_search",
        "evidence_id": "evidence-1",
        "provenance": "verified_search",
    }

    result = mcp_server.local_ai_repo(
        action="search",
        root=str(tmp_path),
        query="auth",
        path="templates/element",
        path_hints=[supplied_hint],
    )

    assert result["success"] is True
    assert captured["path"] == "/api/search"
    assert captured["kwargs"]["path_hints"] == [
        {
            "path": "templates/element",
            "purpose": "repository_search",
            "scope": "repo_search",
        },
        supplied_hint,
    ]


def test_api_search_route_consumes_t03_hint_and_returns_repository_hit(
    monkeypatch, tmp_path: Path
) -> None:
    import threading
    from http.server import ThreadingHTTPServer

    import subprocess
    from pathlib import Path
    from local_ai_hub import http_server, project_config
    from local_ai_hub.repo_tools import RepositoryTools
    from local_ai_hub.services import LocalAIServices
    from local_ai_hub.client import HubClient
    from local_ai_hub.resilience import RecoveryJournal

    monkeypatch.setattr(project_config, "_git_common_dir", lambda _root: None)
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    hinted_file = tmp_path / "templates" / "element" / "button.php"
    hinted_file.parent.mkdir(parents=True)
    hinted_file.write_text("button()", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "--", "templates/element/button.php"],
        check=True,
    )

    state_dir = tmp_path / "runtime"
    repo_tools = RepositoryTools(
        {"server": {"state_dir": str(state_dir)}, "rag": {}, "search": {}}
    )
    monkeypatch.setattr(
        repo_tools,
        "search",
        lambda *_args, **_kwargs: {
            "success": True,
            "root": str(tmp_path),
            "results": [],
        },
    )
    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"server": {"state_dir": str(state_dir)}, "features": {}}
    services._touch_project = lambda _root: None
    services._repo_cache_state = lambda _root: {
        "fingerprint": "revision-1",
        "stale": False,
        "degraded": False,
    }
    services._repo_cached = lambda _operation, _root, _params, compute: compute()
    services.repo_tools = repo_tools
    services.learner = None
    services.deterministic = None
    services.code_index = None
    services.preprocessor = None
    services.evidence_store = None

    app = SimpleNamespace(
        config={},
        debug_traces=None,
        recovery=RecoveryJournal(state_dir),
        services=services,
    )
    monkeypatch.setattr(http_server, "APP", app)

    class AuthorizedHandler(http_server.Handler):
        def _require_authorized(self):
            return True

        def _validate_payload(self, _path, _payload):
            return None

        def _tenant(self):
            return "default"

        def _agent(self):
            return "t21-test"

        def log_message(self, *_args):
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), AuthorizedHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    client_config = tmp_path / "client.toml"
    client_config.write_text(
        f"[server]\nport={server.server_port}\nstate_dir='{state_dir.as_posix()}'\n",
        encoding="utf-8",
    )
    client = HubClient(config_path=str(client_config), auto_start=False)
    try:
        result = client.post(
            "/api/search",
            {"root": str(tmp_path), "query": "button"},
            path_hints=(
                {
                    "path": "templates/element/button.php",
                    "purpose": "repository_search",
                    "scope": "repo_search",
                },
            ),
        )
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)

    assert result["success"] is True
    assert [hit["path"] for hit in result["results"]] == [
        "templates/element/button.php"
    ]
