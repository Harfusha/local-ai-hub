from types import SimpleNamespace

from local_ai_hub import http_server


def _handler(path: str, client_ip: str, command: str = "POST"):
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = path
    handler.command = command
    handler.headers = {"X-LocalAI-Token": ""}
    handler.client_address = (client_ip, 23456)
    handler.server = None
    handler.responses = []
    handler._validate_host_and_origin = lambda: True
    handler._tenant_binding_allowed = lambda: True
    handler._send = lambda status, payload: handler.responses.append((status, payload))
    return handler


def test_empty_api_token_keeps_trusted_local_admin_and_read_only_badge(monkeypatch):
    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(
            config={
                "security": {
                    "api_token": "",
                    "action_tokens": {"trace.read": "trace-read-token-123456"},
                }
            },
            telemetry=SimpleNamespace(record_system=lambda *_args, **_kwargs: None),
        ),
    )

    local_update = _handler("/api/admin/mode", "127.0.0.1")
    remote_update = _handler("/api/admin/mode", "203.0.113.7")
    local_badge = _handler("/api/mode", "127.0.0.1", "GET")

    assert local_update._require_authorized() is True
    assert local_update._authorization_actor == "local"
    assert remote_update._require_authorized() is False
    assert remote_update.responses == [(401, {"success": False, "error": "unauthorized"})]
    assert local_badge._require_authorized() is True
