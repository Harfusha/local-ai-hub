from __future__ import annotations

from types import SimpleNamespace

from local_ai_hub import http_server


def _post_search(monkeypatch, repo_search, payload):
    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(config={}, services=SimpleNamespace(repo_search=repo_search)),
    )
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = "/api/search"
    handler.headers = {"Content-Type": "application/json"}
    handler._begin_trace = lambda _path: None
    handler._require_authorized = lambda: True
    handler._tenant = lambda: "tenant-a"
    handler._read_json = lambda limit=None: payload
    handler._validate_payload = lambda _path, _payload: None
    responses = []
    handler._send = lambda status, body: responses.append((status, body))

    handler.do_POST()
    return responses


def test_http_search_forwards_path_hints_when_service_supports_them(monkeypatch):
    hints = [{"path": "src/auth.py", "purpose": "repository_search", "scope": "repo_search"}]
    calls = []

    def repo_search(root, query, top_k, *, context_lines, enrich, path_hints):
        calls.append((root, query, top_k, context_lines, enrich, path_hints))
        return {"success": True}

    responses = _post_search(
        monkeypatch,
        repo_search,
        {"root": "repo", "query": "auth", "top_k": 5, "path_hints": hints},
    )

    assert responses == [(200, {"success": True})]
    assert calls == [("repo", "auth", 5, None, False, hints)]


def test_http_search_rejects_path_hints_for_legacy_service(monkeypatch):
    calls = []

    def repo_search(root, query, top_k, *, context_lines, enrich):
        calls.append((root, query, top_k, context_lines, enrich))
        return {"success": True}

    responses = _post_search(
        monkeypatch,
        repo_search,
        {"root": "repo", "query": "auth", "path_hints": []},
    )

    assert responses == [(
        501,
        {
            "success": False,
            "unsupported": True,
            "error": "path_hints are not supported by this repository search service",
        },
    )]
    assert calls == []
