from __future__ import annotations

import json
from types import SimpleNamespace

from local_ai_hub.client import HubClient


def _client(tmp_path, port=39123):
    config = tmp_path / "config.toml"
    config.write_text(
        f"[server]\nport={port}\nstate_dir='" + (tmp_path / "state").as_posix() + "'\n",
        encoding="utf-8",
    )
    return HubClient(config_path=str(config), auto_start=False)


def test_post_forwards_path_hints_only_to_search(tmp_path, monkeypatch):
    client = _client(tmp_path)
    calls = []

    def capture_request(path, payload, **_kwargs):
        calls.append((path, payload))
        return {"success": True}

    monkeypatch.setattr(client, "request", capture_request)
    hints = ({"path": "src/app.py", "purpose": "implementation", "scope": "repository"},)

    client.post("/api/search", {"query": "needle"}, path_hints=hints)
    client.post("/api/command", {"command": "pytest"}, path_hints=hints)

    assert calls == [
        (
            "/api/search",
            {"query": "needle", "path_hints": list(hints)},
        ),
        (
            "/api/command",
            {"command": "pytest"},
        ),
    ]


def test_post_omits_empty_path_hints(tmp_path, monkeypatch):
    client = _client(tmp_path)
    calls = []
    monkeypatch.setattr(client, "request", lambda path, payload, **kwargs: calls.append((path, payload)) or {"success": True})

    client.post("/api/search", {"query": "needle"}, path_hints=[])

    assert calls == [("/api/search", {"query": "needle"})]


def test_explicit_path_takes_precedence_and_does_not_mutate_payload(tmp_path, monkeypatch):
    client = _client(tmp_path)
    calls = []
    monkeypatch.setattr(client, "request", lambda path, payload, **kwargs: calls.append((path, payload, kwargs)) or {"success": True})
    payload = {"query": "needle", "path": "src/explicit.py"}

    client.post(
        "/api/search",
        payload,
        path_hints=({"path": "src/hinted.py", "purpose": "implementation", "scope": "repository"},),
    )

    assert calls[0][1] == payload
    assert "path_hints" not in calls[0][1]
    assert payload == {"query": "needle", "path": "src/explicit.py"}


def test_post_does_not_forward_hints_to_unapproved_routes_or_create_paths_alias(tmp_path, monkeypatch):
    client = _client(tmp_path)
    calls = []
    monkeypatch.setattr(client, "request", lambda path, payload, **kwargs: calls.append((path, payload)) or {"success": True})
    payload = {"paths": ["src/explicit.py"], "query": "needle"}

    command_payload = {"command": "pytest"}
    client.post("/api/command", command_payload, path_hints=({"path": "src/hinted.py", "purpose": "implementation", "scope": "repository"},))
    client.post("/api/context/pack", payload, path_hints=({"path": "src/hinted.py", "purpose": "implementation", "scope": "repository"},))

    assert calls == [("/api/command", command_payload), ("/api/context/pack", payload)]
    assert "path_hints" not in calls[0][1]
    assert "path_hints" not in calls[1][1]
    assert calls[1][1]["paths"] == ["src/explicit.py"]


def test_post_transmits_path_hints_over_http_and_returns_search_result(tmp_path):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        payloads = []
        request_ids = []

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            self.payloads.append(json.loads(self.rfile.read(length).decode("utf-8")))
            self.request_ids.append(self.headers.get("X-LocalAI-Request-ID"))
            response = json.dumps(
                {
                    "success": True,
                    "results": [
                        {"path": "templates/element/button.py", "snippet": "owner-result"}
                    ],
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = _client(tmp_path, port=server.server_port)
    hints = [
        {
            "path": "templates/element",
            "purpose": "repository_search",
            "scope": "repository_search",
        }
    ]
    try:
        result = client.post(
            "/api/search",
            {"root": str(tmp_path), "query": "needle"},
            request_id="t04-path-hints-http",
            path_hints=hints,
        )
    finally:
        client._drop_connection()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert Handler.payloads == [
        {"root": str(tmp_path), "query": "needle", "path_hints": hints}
    ]
    assert Handler.request_ids == ["t04-path-hints-http"]
    assert result == {
        "success": True,
        "results": [
            {"path": "templates/element/button.py", "snippet": "owner-result"}
        ],
    }


def test_post_serializes_path_hint_objects_and_omits_empty_metadata(tmp_path, monkeypatch):
    client = _client(tmp_path)
    calls = []
    monkeypatch.setattr(client, "request", lambda path, payload, **kwargs: calls.append(payload) or {"success": True})
    hint = SimpleNamespace(
        path="src/app.py",
        purpose="implementation",
        scope="repository",
        evidence_id=None,
        provenance=None,
        repository_revision=None,
        config_digest=None,
        expires_at=None,
    )

    client.post("/api/search", {"query": "needle"}, path_hints=(hint,))

    assert calls == [
        {
            "query": "needle",
            "path_hints": [{"path": "src/app.py", "purpose": "implementation", "scope": "repository"}],
        }
    ]


def test_search_sends_exact_typed_path_hints_request_body(tmp_path, monkeypatch):
    client = _client(tmp_path)
    calls = []

    def capture_open(method, path, body, headers, _timeout):
        calls.append((method, path, body, headers))
        return b'{"success":true}'

    monkeypatch.setattr(client, "_pooled_open", capture_open)
    hint = SimpleNamespace(
        path="src/auth.py",
        purpose="implementation",
        scope="repository",
        evidence_id="evidence-42",
        provenance="repo-search",
        repository_revision="rev-abc",
        config_digest="cfg-123",
        expires_at="2030-01-01T00:00:00Z",
    )
    request_payload = {"root": str(tmp_path), "query": "authorization flow", "top_k": 12}
    expected_payload = {
        **request_payload,
        "path_hints": [{
            "path": "src/auth.py",
            "purpose": "implementation",
            "scope": "repository",
            "evidence_id": "evidence-42",
            "provenance": "repo-search",
            "repository_revision": "rev-abc",
            "config_digest": "cfg-123",
            "expires_at": "2030-01-01T00:00:00Z",
        }],
    }

    client.post("/api/search", request_payload, path_hints=(hint,))

    assert len(calls) == 1
    method, path, body, headers = calls[0]
    assert (method, path) == ("POST", "/api/search")
    assert body == json.dumps(expected_payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    assert all("src/auth.py" not in value for value in headers.values())


def test_post_caps_path_hints_and_drops_unlisted_fields(tmp_path, monkeypatch):
    client = _client(tmp_path)
    calls = []
    monkeypatch.setattr(client, "request", lambda path, payload, **kwargs: calls.append(payload) or {"success": True})
    hints = tuple(
        {"path": f"src/{index}.py", "purpose": "implementation", "scope": "repository", "private": "drop"}
        for index in range(65)
    )

    client.post("/api/search", {"query": "needle"}, path_hints=hints)

    records = calls[0]["path_hints"]
    assert len(records) == 64
    assert records[0] == {"path": "src/0.py", "purpose": "implementation", "scope": "repository"}
    assert all("private" not in record for record in records)
