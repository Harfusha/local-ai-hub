"""Pre-extraction public HTTP baseline; independent of helper/registry mapping."""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib import request as urllib_request

import pytest

from local_ai_hub import http_server
from local_ai_hub.app import LocalAIApp


TOKEN = "repository-analysis-baseline-secret"
TENANT_KEY = "repository-analysis-baseline-tenant-key-0123456789"


def _root_tenant(root):
    return http_server._derive_root_tenant("baseline-tenant", str(root), TENANT_KEY)


def _post(base_url, path, payload, *, token=TOKEN, raw_body=None):
    body = raw_body if raw_body is not None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["X-LocalAI-Token"] = token
    request = urllib_request.Request(
        f"{base_url}{path}", data=body, headers=headers, method="POST"
    )
    try:
        response = urllib_request.urlopen(request)
    except HTTPError as exc:
        response = exc
    with response:
        body = json.loads(response.read().decode("utf-8"))
        # RequestJournal adds a per-request identifier to otherwise unchanged
        # response bodies; keep this baseline focused on the route contract.
        if isinstance(body, dict):
            body.pop("request_id", None)
        return response.status, body


@pytest.fixture
def public_http_hub(tmp_path):
    config_path = tmp_path / "config.toml"
    state_dir = tmp_path / "state"
    config_path.write_text(
        "\n".join((
            "[server]",
            'bind = "127.0.0.1"',
            "port = 11435",
            f'state_dir = "{state_dir.as_posix()}"',
            "[security]",
            f'api_token = "{TOKEN}"',
            'api_token_tenant = "baseline-tenant"',
            f'allowed_roots = ["{tmp_path.as_posix()}"]',
            f'tenant_derivation_key = "{TENANT_KEY}"',
        )),
        encoding="utf-8",
    )
    app = LocalAIApp(str(config_path))
    previous_app = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", app, tmp_path
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        http_server.APP = previous_app
        app.close()


def _install_service_spies(monkeypatch, app):
    calls = []

    def record(name, *args, **kwargs):
        calls.append((name, args, kwargs))
        return {"success": True, "route": name}

    monkeypatch.setattr(app.deterministic, "git_status", lambda root: record("git_status", root))
    for name in ("git_diff", "git_history_search", "find_hotspots", "test_matrix"):
        monkeypatch.setattr(
            app.services,
            name,
            lambda *args, _name=name, **kwargs: record(_name, *args, **kwargs),
        )
    app.repo_state = SimpleNamespace(fingerprint=lambda root: record("repo_state", root))
    return calls


@pytest.mark.parametrize(("path", "payload_fields", "expected_call"), [
    ("/api/git/status", {}, ("git_status", (), {})),
    ("/api/repo/state", {}, ("repo_state", (), {})),
    ("/api/repo_state", {}, ("repo_state", (), {})),
    ("/api/git/diff", {"path": "src/a.py", "staged": True, "max_lines": 17},
     ("git_diff", (), {"path": "src/a.py", "staged": True, "max_lines": 17})),
    ("/api/git/history_search", {
        "query": "needle", "max_commits": 7, "author": "Ada",
        "since": "2026-01-01", "until": "2026-01-02", "path": "src/a.py",
    }, ("git_history_search", ("needle",), {
        "max_commits": 7, "author": "Ada", "since": "2026-01-01",
        "until": "2026-01-02", "path": "src/a.py",
    })),
    ("/api/repo/hotspots", {"days": 8, "limit": 4},
     ("find_hotspots", (), {"days": 8, "limit": 4})),
    ("/api/hotspots", {"days": 8, "limit": 4},
     ("find_hotspots", (), {"days": 8, "limit": 4})),
    ("/api/test_matrix", {}, ("test_matrix", (), {})),
])
def test_pre_extraction_public_http_route_baseline(
    public_http_hub, monkeypatch, path, payload_fields, expected_call
):
    base_url, app, root = public_http_hub
    calls = _install_service_spies(monkeypatch, app)
    canonical_root = str(root.resolve())
    payload = {"root": str(root), "tenant": _root_tenant(root), **payload_fields}

    status, response = _post(base_url, path, payload)

    name, args, kwargs = expected_call
    assert status == 200
    assert response == {"success": True, "route": name}
    assert calls == [(name, (canonical_root, *args), kwargs)]


def test_public_http_baseline_authorization_precedes_route_service(
    public_http_hub, monkeypatch
):
    base_url, app, root = public_http_hub
    calls = _install_service_spies(monkeypatch, app)
    payload = {"root": str(root), "tenant": _root_tenant(root)}

    status, response = _post(base_url, "/api/git/status", payload, token=None)

    assert status == 401
    assert response == {
        "success": False,
        "error": "unauthorized",
        "status_code": 401,
        "retryable": False,
        "terminal": True,
    }
    assert calls == []


def test_public_http_baseline_maintenance_gate_precedes_body_and_service(
    public_http_hub, monkeypatch
):
    base_url, app, root = public_http_hub
    calls = _install_service_spies(monkeypatch, app)
    rejection = {
        "success": False,
        "error": "operational mode blocks repository analysis",
        "error_code": "operational_mode_blocked",
        "mode": "maintenance",
        "retryable": True,
        "terminal": False,
        "status_code": 423,
    }
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *_args: rejection)

    status, response = _post(
        base_url,
        "/api/git/status",
        {"root": str(root), "tenant": _root_tenant(root)},
        raw_body=b"not-json",
    )

    assert status == 423
    assert response == rejection
    assert calls == []


def test_public_http_baseline_body_validation_precedes_route_service(
    public_http_hub, monkeypatch
):
    base_url, app, root = public_http_hub
    calls = _install_service_spies(monkeypatch, app)
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *_args: None)

    status, response = _post(
        base_url,
        "/api/git/status",
        {},
        raw_body=b"not-json",
    )

    assert status == 400
    assert response["success"] is False
    assert response["error"].startswith("invalid JSON body:")
    assert response["terminal"] is True
    assert response["retryable"] is False
    assert calls == []


def test_public_http_baseline_preserves_central_conversion_error(
    public_http_hub, monkeypatch
):
    base_url, app, root = public_http_hub
    calls = _install_service_spies(monkeypatch, app)
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *_args: None)
    payload = {
        "root": str(root),
        "tenant": _root_tenant(root),
        "max_lines": "invalid-integer",
    }

    status, response = _post(base_url, "/api/git/diff", payload)

    assert status == 400
    assert response == {
        "success": False,
        "error": "invalid literal for int() with base 10: 'invalid-integer'",
        "status_code": 400,
        "terminal": True,
        "retryable": False,
    }
    assert calls == []


def test_public_http_baseline_preserves_tracker_unavailable_response(
    public_http_hub, monkeypatch
):
    base_url, app, root = public_http_hub
    calls = _install_service_spies(monkeypatch, app)
    app.repo_state = SimpleNamespace(
        fingerprint=lambda _root: (_ for _ in ()).throw(RuntimeError("private tracker detail"))
    )
    payload = {"root": str(root), "tenant": _root_tenant(root)}

    status, response = _post(base_url, "/api/repo/state", payload)

    assert status == 200
    assert response == {
        "success": False,
        "error": "repo state unavailable",
        "error_code": "repo_state_unavailable",
    }
    assert calls == []


def test_public_http_baseline_preserves_service_exception_translation(
    public_http_hub, monkeypatch
):
    base_url, app, root = public_http_hub
    calls = _install_service_spies(monkeypatch, app)

    def fail_diff(*_args, **_kwargs):
        calls.append(("git_diff", "raised"))
        raise RuntimeError("private service detail")

    monkeypatch.setattr(app.services, "git_diff", fail_diff)
    payload = {"root": str(root), "tenant": _root_tenant(root)}

    status, response = _post(base_url, "/api/git/diff", payload)

    assert status == 500
    assert response == {
        "success": False,
        "error": "internal server error",
        "error_code": "internal_error",
        "status_code": 500,
        "terminal": True,
        "retryable": False,
    }, response
    assert calls == [("git_diff", "raised")]


def test_public_http_baseline_preserves_disabled_deterministic_response(
    public_http_hub, monkeypatch
):
    base_url, app, root = public_http_hub
    calls = _install_service_spies(monkeypatch, app)
    monkeypatch.setattr(app, "deterministic", None)
    payload = {"root": str(root), "tenant": _root_tenant(root)}

    status, response = _post(base_url, "/api/git/status", payload)

    assert status == 200
    assert response == {"success": False, "error": "deterministic engine disabled"}
    assert calls == []
