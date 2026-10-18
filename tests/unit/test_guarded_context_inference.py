import json
import threading
from urllib.error import HTTPError
from urllib import request as urllib_request

import pytest

from local_ai_hub import http_server
from local_ai_hub.app import LocalAIApp


def test_context_infers_guarded_when_changed_paths_provided(monkeypatch):
    captured = {}
    class DummyClient:
        def post(self, url, payload, **kwargs):
            captured.update(payload)
            return {"success": True, "context": "test"}
    monkeypatch.setattr("local_ai_hub.mcp_server.CLIENT", DummyClient())
    from local_ai_hub.mcp_server import local_ai_repo

    res = local_ai_repo(action="context", root="C:/test/root", query="my task", changed_paths=["src/a.py"])
    assert res.get("success") is True
    assert captured.get("guarded") is True
    assert captured.get("changed_paths") == ["src/a.py"]

def test_context_infers_guarded_when_focus_provided(monkeypatch):
    captured = {}
    class DummyClient:
        def post(self, url, payload, **kwargs):
            captured.update(payload)
            return {"success": True, "context": "test"}
    monkeypatch.setattr("local_ai_hub.mcp_server.CLIENT", DummyClient())
    from local_ai_hub.mcp_server import local_ai_repo

    res = local_ai_repo(action="context", root="C:/test/root", query="my task", focus=["src/a.py"])
    assert res.get("success") is True
    assert captured.get("guarded") is True
    assert captured.get("focus") == ["src/a.py"]


@pytest.fixture
def context_http_hub(tmp_path, monkeypatch):
    token = "guarded-context-test-secret"
    tenant_key = "guarded-context-test-tenant-key-0123456789"
    state_dir = tmp_path / "state"
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join((
            "[server]",
            'bind = "127.0.0.1"',
            "port = 11435",
            f'state_dir = "{state_dir.as_posix()}"',
            "[security]",
            f'api_token = "{token}"',
            'api_token_tenant = "guarded-context-test"',
            f'allowed_roots = ["{tmp_path.as_posix()}"]',
            f'tenant_derivation_key = "{tenant_key}"',
        )),
        encoding="utf-8",
    )
    app = LocalAIApp(str(config_path))
    calls = []
    monkeypatch.setattr(
        app.services,
        "adaptive_context_pack",
        lambda request, **kwargs: calls.append((request, kwargs)) or {
            "success": True,
            "context": "isolated test context",
            "evidence": [],
        },
    )
    previous_app = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", token, calls, tmp_path
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        http_server.APP = previous_app
        app.close()


def _post_context(base_url, token, payload):
    request = urllib_request.Request(
        f"{base_url}/api/context/pack",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-LocalAI-Token": token},
        method="POST",
    )
    try:
        response = urllib_request.urlopen(request)
    except HTTPError as exc:
        response = exc
    with response:
        return response.status, json.loads(response.read().decode("utf-8"))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("changed_paths", []),
        ("focus", []),
        ("changed_paths", ["src/example.py"]),
        ("focus", ["src/example.py"]),
    ],
)
def test_http_context_requires_guard_activation_fields_to_be_explicit(context_http_hub, field, value):
    base_url, token, calls, root = context_http_hub

    status, response = _post_context(
        base_url,
        token,
        {"root": str(root), "query": "test context", field: value},
    )

    assert status == 400, response
    assert response["error"] == (
        f"guard-related fields require guarded=true, task_id, or phase: {field}"
    )
    assert calls == []


def test_http_context_rejects_malformed_explicit_guarded_even_with_empty_paths(context_http_hub):
    base_url, token, calls, root = context_http_hub

    status, response = _post_context(
        base_url,
        token,
        {"root": str(root), "query": "test context", "guarded": "false", "changed_paths": []},
    )

    assert status == 400, response
    assert response["error"] == "guarded must be boolean"
    assert calls == []


@pytest.mark.parametrize("field", ["changed_paths", "focus"])
def test_http_context_keeps_activation_field_validation(context_http_hub, field):
    base_url, token, calls, root = context_http_hub

    status, response = _post_context(
        base_url,
        token,
        {"root": str(root), "query": "test context", "guarded": True, field: "not-a-list"},
    )

    assert status == 400, response
    assert response["error"] == f"{field} must be a list"
    assert calls == []


def test_http_context_accepts_unscoped_request_without_guard_fields(context_http_hub):
    base_url, token, calls, root = context_http_hub

    status, response = _post_context(
        base_url,
        token,
        {"root": str(root), "query": "test context"},
    )

    assert status == 200, response
    assert response["success"] is True
