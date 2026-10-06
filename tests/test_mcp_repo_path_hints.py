from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

from local_ai_hub import mcp_server
from local_ai_hub import http_server
from local_ai_hub import project_config
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.services import LocalAIServices


def test_repo_search_forwards_known_path_as_scoped_path_hint(monkeypatch, tmp_path):
    calls = []

    def post(path, payload, **kwargs):
        calls.append({"path": path, "payload": payload, "kwargs": kwargs})
        return {"success": True, "results": []}

    monkeypatch.setattr(mcp_server, "CLIENT", SimpleNamespace(post=post))

    result = mcp_server._local_ai_repo_impl(
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

    result = mcp_server._local_ai_repo_impl(
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


def test_repo_search_normalizes_absolute_hint_inside_root(monkeypatch, tmp_path):
    captured = {}
    (tmp_path / "src").mkdir()

    def post(path, payload, **kwargs):
        captured.update(path=path, payload=payload, kwargs=kwargs)
        return {"success": True, "results": []}

    monkeypatch.setattr(mcp_server, "CLIENT", SimpleNamespace(post=post))

    result = mcp_server._local_ai_repo_impl(
        action="search",
        root=str(tmp_path),
        query="auth",
        path_hints=[
            {
                "path": str(tmp_path / "src"),
                "purpose": "repository_search",
                "scope": "repo_search",
            }
        ],
    )

    assert result["success"] is True
    assert captured["kwargs"]["path_hints"] == [
        {
            "path": "src",
            "purpose": "repository_search",
            "scope": "repo_search",
        }
    ]


def test_repo_search_rejects_hint_outside_root_before_transport(monkeypatch, tmp_path):
    calls = []

    def post(*args, **kwargs):
        calls.append((args, kwargs))
        return {"success": True, "results": []}

    monkeypatch.setattr(mcp_server, "CLIENT", SimpleNamespace(post=post))

    result = mcp_server._local_ai_repo_impl(
        action="search",
        root=str(tmp_path),
        query="auth",
        path_hints=[
            {
                "path": "../outside",
                "purpose": "repository_search",
                "scope": "repo_search",
            }
        ],
    )

    assert result["success"] is False
    assert result["status_code"] == 400
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert calls == []


def test_registered_local_ai_repo_passes_public_path_hints(monkeypatch, tmp_path):
    captured = {}
    (tmp_path / "src").mkdir()

    def post(path, payload, **kwargs):
        captured.update(path=path, payload=payload, kwargs=kwargs)
        return {"success": True, "results": []}

    monkeypatch.setattr(mcp_server, "CLIENT", SimpleNamespace(post=post))

    result = mcp_server.local_ai_repo(
        action="search",
        root=str(tmp_path),
        query="auth",
        path_hints=[
            {
                "path": str(tmp_path / "src"),
                "purpose": "repository_search",
                "scope": "repo_search",
            }
        ],
    )

    assert result["success"] is True
    assert captured["path"] == "/api/search"
    assert captured["kwargs"]["path_hints"] == [
        {
            "path": "src",
            "purpose": "repository_search",
            "scope": "repo_search",
        }
    ]


def test_api_search_forwards_path_hints_to_repo_search(monkeypatch):
    captured = {}
    responses = []

    class Recovery:
        def lookup(self, *_args):
            return None

        def begin(self, *_args):
            return None

    class Services:
        def repo_search(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return {"success": True, "results": []}

    app = SimpleNamespace(
        config={},
        debug_traces=None,
        recovery=Recovery(),
        services=Services(),
    )
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = "/api/search"
    handler.headers = {"Content-Type": "application/json"}
    handler._begin_trace = lambda _path: None
    handler._require_authorized = lambda: True
    handler._read_json = lambda: {
        "root": "repo",
        "query": "button",
        "path_hints": [
            {"path": "templates/element", "purpose": "repository_search", "scope": "repo_search"}
        ],
    }
    handler._validate_payload = lambda _path, _payload: None
    handler._tenant = lambda: "default"
    handler._agent = lambda: "agent"
    handler._send = lambda status, data: responses.append((status, data))
    monkeypatch.setattr(http_server, "APP", app)

    handler.do_POST()

    assert captured["kwargs"]["path_hints"] == [
        {"path": "templates/element", "purpose": "repository_search", "scope": "repo_search"}
    ]
    assert responses == [(200, {"success": True, "results": []})]


def test_api_search_route_consumes_t03_hint_and_returns_repository_hit(
    monkeypatch, tmp_path: Path
) -> None:
    import threading
    import subprocess
    from http.server import ThreadingHTTPServer

    from local_ai_hub import http_server, project_config
    from local_ai_hub.client import HubClient
    from local_ai_hub.repo_tools import RepositoryTools
    from local_ai_hub.resilience import RecoveryJournal
    from local_ai_hub.services import LocalAIServices

    monkeypatch.setattr(project_config, "_git_common_dir", lambda _root: None)
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    hinted_file = tmp_path / "templates" / "element" / "button.php"
    hinted_file.parent.mkdir(parents=True)
    hinted_file.write_text("button()", encoding="utf-8")
    unhinted_file = tmp_path / "src" / "button_helper.php"
    unhinted_file.parent.mkdir(parents=True)
    unhinted_file.write_text("button helper", encoding="utf-8")
    subprocess.run(
        [
            "git", "-C", str(tmp_path), "add", "--",
            "templates/element/button.php", "src/button_helper.php",
        ],
        check=True,
    )

    state_dir = tmp_path / "runtime"
    repo_tools = RepositoryTools(
        {
            "server": {"state_dir": str(state_dir)},
            "rag": {},
            "search": {"max_files": 32, "python_fallback_max_files": 1},
        }
    )
    monkeypatch.setattr(repo_tools, "_ripgrep_candidates", lambda *_args: (None, False))
    monkeypatch.setattr(repo_tools, "_git_grep_candidates", lambda *_args: (None, False))
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
    assert result["python_fallback_limit"] == 1
    assert result["python_fallback_scanned_files"] == 1
    assert result["python_fallback_truncated"] is True
    assert result["path_hint_usage"] == {
        "hint_used": True,
        "fallback_used": False,
        "hint_helped": None,
    }
    assert [hit["path"] for hit in result["results"]] == [
        "templates/element/button.php"
    ]
