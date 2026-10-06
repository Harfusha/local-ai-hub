from __future__ import annotations

from types import SimpleNamespace

from local_ai_hub.client import HubClient


def _client(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(
        "[server]\nport=39123\nstate_dir='" + (tmp_path / "state").as_posix() + "'\n",
        encoding="utf-8",
    )
    return HubClient(config_path=str(config), auto_start=False)


def test_post_forwards_path_hints_to_search_and_command(tmp_path, monkeypatch):
    client = _client(tmp_path)
    calls = []

    def capture_request(path, payload, **kwargs):
        calls.append((path, payload, kwargs))
        return {"success": True}

    monkeypatch.setattr(client, "request", capture_request)
    hints = ({"path": "src/app.py", "purpose": "implementation", "scope": "repository"},)

    client.post("/api/search", {"query": "needle"}, path_hints=hints, request_id="search-1")
    client.post("/api/command", {"command": "pytest"}, path_hints=hints, request_id="command-1")

    assert calls == [
        (
            "/api/search",
            {"query": "needle", "path_hints": list(hints)},
            {"timeout": 360.0, "replay_safe": False, "request_id": "search-1"},
        ),
        (
            "/api/command",
            {"command": "pytest", "path_hints": list(hints)},
            {"timeout": 360.0, "replay_safe": False, "request_id": "command-1"},
        ),
    ]


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


def test_post_does_not_forward_hints_to_other_routes_or_create_paths_alias(tmp_path, monkeypatch):
    client = _client(tmp_path)
    calls = []
    monkeypatch.setattr(client, "request", lambda path, payload, **kwargs: calls.append((path, payload)) or {"success": True})
    payload = {"paths": ["src/explicit.py"], "query": "needle"}

    client.post("/api/context/pack", payload, path_hints=({"path": "src/hinted.py", "purpose": "implementation", "scope": "repository"},))

    assert calls == [("/api/context/pack", payload)]
    assert "path_hints" not in calls[0][1]
    assert calls[0][1]["paths"] == ["src/explicit.py"]


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


def test_post_caps_path_hints_and_drops_unlisted_fields(tmp_path, monkeypatch):
    client = _client(tmp_path)
    calls = []
    monkeypatch.setattr(client, "request", lambda path, payload, **kwargs: calls.append(payload) or {"success": True})
    hints = tuple(
        {"path": f"src/{index}.py", "purpose": "implementation", "scope": "repository", "private": "drop"}
        for index in range(65)
    )

    client.post("/api/command", {"command": "pytest"}, path_hints=hints)

    records = calls[0]["path_hints"]
    assert len(records) == 64
    assert records[0] == {"path": "src/0.py", "purpose": "implementation", "scope": "repository"}
    assert all("private" not in record for record in records)
