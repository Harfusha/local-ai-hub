from __future__ import annotations

from types import SimpleNamespace

from local_ai_hub import http_server


def test_api_search_forwards_path_hints_to_repo_search(monkeypatch):
    captured = {}
    responses = []

    class Recovery:
        def lookup(self, *_args):
            return None

        def begin(self, *_args, **_kwargs):
            return {"claimed": True}

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
    handler._trace_request_id = "req-1"
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
