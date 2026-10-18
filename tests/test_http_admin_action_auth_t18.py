from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from local_ai_hub import http_server


class AuditTelemetry:
    def __init__(self):
        self.events = []

    def record_system(self, action, **event):
        self.events.append({"action": action, **event})


def test_admin_authorization_rejects_explicit_audit_queue_rejection(monkeypatch):
    app = SimpleNamespace(
        config={"security": {"api_token": "admin-token-long-enough"}},
        telemetry=SimpleNamespace(record_system=lambda *_args, **_kwargs: False),
    )
    monkeypatch.setattr(http_server, "APP", app)
    handler = _handler("/api/config/update", "admin-token-long-enough")

    assert handler._require_authorized() is False
    assert handler.responses == [(503, {"success": False, "error": "admin audit unavailable", "retryable": True})]


def test_authorized_status_read_survives_disabled_audit_transport(monkeypatch):
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(
        config={"security": {"api_token": "admin-token-long-enough"}},
        telemetry=SimpleNamespace(record_system=lambda *_args, **_kwargs: False),
    ))
    handler = _handler("/api/capabilities", "admin-token-long-enough")
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
    handler.server = None
    handler.responses = []
    handler._validate_host_and_origin = lambda: True
    handler._send = lambda status, payload: handler.responses.append((status, payload))
    return handler


def test_action_tokens_are_scoped_and_authorization_is_audited(monkeypatch):
    telemetry = AuditTelemetry()
    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(
            config={
                "security": {
                    "action_tokens": {
                        "trace.read": "trace-read-token-123456",
                        "config.write": "config-write-token-123456",
                    }
                }
            },
            telemetry=telemetry,
        ),
    )
    trace_reader = _handler("/api/debug-traces", "trace-read-token-123456")
    config_writer_with_wrong_scope = _handler(
        "/api/config/update", "trace-read-token-123456"
    )

    assert trace_reader._require_authorized() is True
    assert config_writer_with_wrong_scope._require_authorized() is False
    assert config_writer_with_wrong_scope.responses == [
        (401, {"success": False, "error": "unauthorized"})
    ]
    trace_reader._audit_admin_result(200)
    config_writer_with_wrong_scope._audit_admin_result(401)
    assert [(event["action"], event["operation"], event["success"]) for event in telemetry.events] == [
        ("admin.authorization", "trace.read", True),
        ("admin.authorization", "config.write", False),
        ("admin.action.result", "trace.read", True),
        ("admin.action.result", "config.write", False),
    ]


def test_mode_control_action_token_authorizes_only_remote_mode_update(monkeypatch):
    telemetry = AuditTelemetry()
    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(
            config={
                "security": {
                    "action_tokens": {
                        "mode.control": "mode-control-token-123456",
                    }
                }
            },
            telemetry=telemetry,
        ),
    )
    mode_writer = _handler("/api/admin/mode", "mode-control-token-123456")
    mode_writer.client_address = ("203.0.113.7", 23456)
    config_writer_with_mode_token = _handler(
        "/api/config/update", "mode-control-token-123456"
    )
    config_writer_with_mode_token.client_address = ("203.0.113.7", 23456)
    mode_reader_with_control_token = _handler(
        "/api/mode", "mode-control-token-123456"
    )
    mode_reader_with_control_token.command = "GET"
    mode_reader_with_control_token.client_address = ("203.0.113.7", 23456)

    assert http_server._http_admin_action("POST", "/api/admin/mode") == "mode.control"
    assert mode_writer._require_authorized() is True
    assert config_writer_with_mode_token._require_authorized() is False
    assert config_writer_with_mode_token.responses == [
        (401, {"success": False, "error": "unauthorized"})
    ]
    assert mode_reader_with_control_token._require_authorized() is False
    assert mode_reader_with_control_token.responses == [
        (401, {"success": False, "error": "unauthorized"})
    ]


def test_mode_control_action_token_runs_remote_mode_post(monkeypatch):
    telemetry = AuditTelemetry()
    mode_writes = []

    @contextmanager
    def transition_guard():
        yield

    jobs = SimpleNamespace(
        path=Path("state/jobs.sqlite3"),
        operational_mode_change_guard=transition_guard,
        on_operational_mode_changed=lambda _snapshot: {"inference_active": True},
    )
    snapshot = SimpleNamespace(
        mode="active", revision=9, degraded=False,
        to_dict=lambda: {"mode": "active", "revision": 9, "degraded": False},
    )
    app = SimpleNamespace(
        config={
            "security": {
                "api_token": "",
                "action_tokens": {"mode.control": "mode-control-token-123456"},
            }
        },
        telemetry=telemetry,
        async_jobs=jobs,
        scheduler=SimpleNamespace(foreground_busy=lambda: False),
    )
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(http_server, "_operational_mode_api", lambda: SimpleNamespace(
        load_operational_mode=lambda state_dir: snapshot,
        set_operational_mode=lambda state_dir, mode: mode_writes.append((mode, state_dir)) or snapshot,
    ))
    handler = _handler("/api/admin/mode", "mode-control-token-123456")
    handler.client_address = ("203.0.113.7", 23456)
    handler._begin_trace = lambda _path: None
    handler._read_json = lambda: {"mode": "active"}
    handler._validate_payload = lambda _path, _payload: None

    handler.do_POST()

    assert http_server._http_admin_action("POST", "/api/admin/mode") == "mode.control"
    assert mode_writes == [("active", Path("state"))]
    assert handler.responses[0][0] == 200
    assert handler.responses[0][1]["success"] is True
    assert handler.responses[0][1]["mode"] == "active"
    assert handler.responses[0][1]["revision"] == 9
    assert telemetry.events == [{
        "action": "admin.authorization",
        "success": True,
        "component": "http_admin",
        "operation": "mode.control",
        "path": "/api/admin/mode",
        "actor": "action_token",
    }]


def test_config_view_masks_global_and_action_tokens():
    view = http_server._redact_config_secrets(
        {
            "security": {
                "api_token": "legacy-secret-value",
                "action_tokens": {"trace.read": "trace-secret-value"},
            }
        }
    )

    assert view["security"] == {
        "api_token": "***configured***",
        "action_tokens": {"trace.read": "***configured***"},
    }


def test_mutating_admin_routes_have_separate_action_scopes():
    assert http_server._http_admin_action("POST", "/api/maintenance/purge_cache") == "maintenance"
    assert http_server._http_admin_action("POST", "/api/config/update") == "config.write"
    assert http_server._http_admin_action("POST", "/api/control") is None
    assert http_server.select_http_routes("POST", "/api/control") == ()
    assert 'id="restartHub"' not in http_server.DASHBOARD_HTML
    assert 'id="stopService"' not in http_server.DASHBOARD_HTML
    assert http_server._http_admin_action("POST", "/api/models/manage") == "model.manage"
    assert http_server._http_admin_action("POST", "/api/bundle/import") == "bundle.import"


def test_detailed_telemetry_toggle_applies_live():
    store = SimpleNamespace(enabled=False)
    app = SimpleNamespace(debug_traces=store)

    assert http_server._apply_live_debug_trace_toggle(app, {"debug_traces.enabled": True}) is True
    assert store.enabled is True
    assert http_server._apply_live_debug_trace_toggle(app, {"debug_traces.enabled": False}) is True
    assert store.enabled is False
    assert http_server._apply_live_debug_trace_toggle(app, {"preprocessing.enabled": True}) is False


def test_legacy_global_token_keeps_admin_superuser_access(monkeypatch):
    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(
            config={
                "security": {
                    "api_token": "legacy-admin-token-123456",
                    "action_tokens": {"trace.read": "trace-read-token-123456"},
                }
            }
        ),
    )
    handler = _handler("/api/config/update", "legacy-admin-token-123456")

    assert handler._authorized() is True


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
        SimpleNamespace(config={"security": {"api_token": ""}}),
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
