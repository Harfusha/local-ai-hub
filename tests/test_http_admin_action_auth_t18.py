from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from local_ai_hub import http_server


def test_debug_trace_routes_require_read_or_manage_capabilities():
    assert http_server._http_admin_action("GET", "/api/debug-traces/trace-1") == "trace.read"
    assert http_server._http_admin_action("POST", "/api/debug-traces/purge") == "trace.manage"


class AuditTelemetry:
    def __init__(self):
        self.events = []

    def record_system(self, action, **event):
        self.events.append({"action": action, **event})


def test_admin_authorization_rejects_explicit_audit_queue_rejection(monkeypatch):
    app = SimpleNamespace(
        config={"security": {}},
        telemetry=SimpleNamespace(record_system=lambda *_args, **_kwargs: False),
    )
    monkeypatch.setattr(http_server, "APP", app)
    handler = _handler("/api/config/update", "")
    handler.client_address = ("127.0.0.1", 32100)

    assert handler._require_authorized() is False
    assert handler.responses == [(503, {"success": False, "error": "admin audit unavailable", "retryable": True})]


def test_authorization_rejects_malformed_security_configuration(monkeypatch):
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"security": "invalid"}))
    handler = _handler("/api/config/update", "admin-token-long-enough")

    assert handler._authorized() is False


def test_authorization_rejects_duplicate_configured_credentials(monkeypatch):
    token = "admin-token-long-enough"
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"security": {
        "api_token": token, "supervisor_token": token,
    }}))
    handler = _handler("/api/config/update", token)

    assert handler._authorized() is False


def test_authorized_status_read_survives_disabled_audit_transport(monkeypatch):
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(
        config={"security": {}},
        telemetry=SimpleNamespace(record_system=lambda *_args, **_kwargs: False),
    ))
    handler = _handler("/api/capabilities", "")
    handler.client_address = ("127.0.0.1", 32100)
    handler.command = "GET"

    assert handler._require_authorized() is True
    assert handler.responses == []


def test_admin_result_retains_failed_audit_outcome_without_duplicate_enqueue(monkeypatch):
    calls = []
    def rejected(*args, **kwargs):
        calls.append(args)
        return False
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(telemetry=SimpleNamespace(record_system=rejected)))
    handler = _handler("/api/config/update", "unused")
    handler._admin_action = "config.write"

    assert handler._audit_admin_result(200) is False
    assert handler._audit_admin_result(200) is False
    assert len(calls) == 1


def test_admin_response_reports_unknown_outcome_after_result_audit_rejection(monkeypatch):
    import io
    import json

    monkeypatch.setattr(http_server, "APP", SimpleNamespace(
        config={}, telemetry=SimpleNamespace(record_system=lambda *_args, **_kwargs: False),
    ))
    handler = _handler("/api/config/update", "unused")
    handler._admin_action = "config.write"
    handler._telemetry_finished = True
    handler._debug_trace_finished = True
    handler._finish_debug_trace = lambda *_args: None
    handler._close_trace_context = lambda: None
    handler._common_headers = lambda: None
    statuses = []
    handler.send_response = statuses.append
    handler.send_header = lambda *_args: None
    handler.end_headers = lambda: None
    handler.wfile = io.BytesIO()

    http_server.Handler._send(handler, 200, {"success": True, "updated": True})

    payload = json.loads(handler.wfile.getvalue())
    assert statuses == [503]
    assert payload["updated"] is True
    assert payload["success"] is False
    assert payload["outcome_unknown"] is True
    assert payload["retryable"] is False
    assert payload["terminal"] is True


def _handler(path, token):
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = path
    handler.command = "GET" if path.startswith("/api/debug-traces") else "POST"
    handler.headers = {"X-LocalAI-Token": token}
    handler.client_address = ("127.0.0.1", 23456)
    handler.server = None
    handler.responses = []
    handler._validate_host_and_origin = lambda: True
    handler._send = lambda status, payload: handler.responses.append((status, payload))
    return handler

def _dashboard_handler(path, *, fetch_site="same-origin", client_address=("127.0.0.1", 23456), origin="http://127.0.0.1:11435"):
    handler = _handler(path, "")
    handler.headers = {
        "X-LocalAI-Client": "dashboard",
        "Sec-Fetch-Site": fetch_site,
        "Host": "127.0.0.1:11435",
        "Origin": origin,
    }
    handler.client_address = client_address
    handler._validate_host_and_origin = lambda: http_server.Handler._validate_host_and_origin(handler)
    return handler


def test_same_origin_loopback_dashboard_uses_local_auth_without_api_token(monkeypatch):
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={
        "security": {},
        "server": {"bind": "127.0.0.1"},
    }, telemetry=SimpleNamespace(record_system=lambda *_args, **_kwargs: True)))
    handler = _dashboard_handler("/api/config/update")

    assert handler._require_authorized() is True
    assert handler._authorization_actor == "local"
    assert handler._authorization_status == 200
    assert handler._authorization_permissions == frozenset()
    assert handler.responses == []

def test_dashboard_origin_guard_rejects_cross_site_and_invalid_origins(monkeypatch):
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={
        "security": {},
        "server": {"bind": "127.0.0.1"},
    }))
    cross_site = _dashboard_handler("/api/config/update", fetch_site="cross-site")
    remote = _dashboard_handler("/api/config/update", client_address=("203.0.113.7", 23456))
    markerless = _dashboard_handler("/api/config/update")
    markerless.headers.pop("X-LocalAI-Client")
    invalid_origin = _dashboard_handler("/api/config/update", origin="https://attacker.example")
    missing_origin = _dashboard_handler("/api/config/update", origin="")

    assert cross_site._validate_host_and_origin() is False
    assert remote._authorized() is False
    assert markerless._validate_host_and_origin() is True
    assert invalid_origin._validate_host_and_origin() is False
    assert missing_origin._validate_host_and_origin() is False

def test_loopback_routes_are_authorized_and_admin_actions_are_audited(monkeypatch):
    telemetry = AuditTelemetry()
    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(config={"security": {}}, telemetry=telemetry),
    )
    trace_reader = _handler("/api/debug-traces", "")
    config_writer = _handler("/api/config/update", "")

    assert trace_reader._require_authorized() is True
    assert config_writer._require_authorized() is True
    trace_reader._audit_admin_result(200)
    config_writer._audit_admin_result(200)
    assert [(event["action"], event["operation"], event["success"]) for event in telemetry.events] == [
        ("admin.authorization", "trace.read", True),
        ("admin.authorization", "config.write", True),
        ("admin.action.result", "trace.read", True),
        ("admin.action.result", "config.write", True),
    ]

def test_token_headers_do_not_authorize_non_loopback_requests(monkeypatch):
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"security": {}}))
    remote = _handler("/api/admin/mode", "mode-control-token-123456")
    remote.client_address = ("203.0.113.7", 23456)
    remote.headers["Authorization"] = "Bearer mode-control-token-123456"

    assert remote._authorized() is False
    assert remote._authorization_actor == "unrecognized"


def test_retired_token_configuration_fails_closed(monkeypatch):
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={
        "security": {"action_tokens": {"mode.control": "mode-control-token-123456"}},
    }))
    local = _handler("/api/admin/mode", "mode-control-token-123456")

    assert local._authorized() is False


def test_malformed_action_token_policy_fails_closed(monkeypatch):
    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(config={"security": {"action_tokens": "not-a-table"}}),
    )
    handler = _handler("/api/config/update", "unconfigured-local-token")

    assert handler._authorized() is False


def test_empty_token_policy_uses_actual_loopback_client_address(monkeypatch):
    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(config={"security": {}}),
    )
    local = _handler("/api/admin/mode", "")
    local.client_address = ("127.0.0.1", 32100)
    remote = _handler("/api/admin/mode", "")
    remote.client_address = ("203.0.113.7", 32100)
    remote.headers.update({
        "Host": "localhost",
        "Origin": "http://localhost",
        "X-LocalAI-Agent": "administrator",
    })

    assert local._authorized() is True
    assert local._authorization_actor == "local"
    assert remote._authorized() is False
    assert remote._authorization_actor == "unrecognized"


def test_http_server_rejects_non_loopback_peer_before_dispatch():
    server = object.__new__(http_server.LocalAIHTTPServer)

    assert server.verify_request(None, ("127.0.0.1", 32100)) is True
    assert server.verify_request(None, ("203.0.113.7", 32100)) is False


def test_http_server_rejects_non_loopback_bind_configuration():
    import pytest

    server = object.__new__(http_server.LocalAIHTTPServer)
    server.server_address = ("0.0.0.0", 11435)

    with pytest.raises(RuntimeError, match="server.bind must be 127.0.0.1"):
        server.server_bind()


def test_require_authorized_rejects_cross_origin_before_authorization(monkeypatch):
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(
        config={"security": {}, "server": {"bind": "127.0.0.1"}},
        telemetry=SimpleNamespace(record_system=lambda *_args, **_kwargs: True),
    ))
    handler = _dashboard_handler("/api/config/update", fetch_site="cross-site")

    assert handler._require_authorized() is False
    assert handler.responses[0][0] == 403


def test_require_authorized_rejects_retired_identity_query_fields(monkeypatch):
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"security": {}}))
    handler = _dashboard_handler("/api/capabilities?tenant_id=retired")

    assert handler._require_authorized() is False
    assert handler.responses[0][0] == 400


def test_require_authorized_enforces_rate_limit_after_authentication(monkeypatch):
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(
        config={"security": {}, "server": {"bind": "127.0.0.1"}},
        telemetry=SimpleNamespace(record_system=lambda *_args, **_kwargs: True),
    ))
    handler = _dashboard_handler("/api/capabilities")
    handler.server = SimpleNamespace(check_rate_limit=lambda: False)

    assert handler._require_authorized() is False
    assert handler.responses == [(429, {
        "success": False,
        "error": "rate limit exceeded; slow down",
        "retryable": True,
        "retry_after_seconds": 10,
    })]
