from __future__ import annotations

from types import SimpleNamespace

import pytest

from local_ai_hub import http_server


@pytest.mark.parametrize(
    ("enabled", "expected_status"),
    [(True, "healthy"), (False, "disabled")],
)
def test_agent_state_status_detail_reports_enabled_state(monkeypatch, enabled, expected_status):
    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(config={}, agent_state=SimpleNamespace(enabled=enabled)),
    )
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *_args, **_kwargs: None)
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = "/api/status?detail=agent_state"
    handler.client_address = ("127.0.0.1", 12345)
    handler.headers = {}
    handler.server = None
    handler._begin_trace = lambda _path: None
    handler._require_authorized = lambda: True
    handler.responses = []
    handler._send = lambda status, payload: handler.responses.append((status, payload))

    handler.do_GET()

    status, payload = handler.responses[0]
    assert status == 200
    assert payload["success"] is True
    assert payload["enabled"] is enabled
    assert payload["status"] == expected_status


def test_summary_status_route_selects_cached_light_snapshot(monkeypatch):
    calls = []
    dependency_status = {
        "runtime.online": {"degraded": True, "deadline_ms": 250, "reason": "probe_timeout"}
    }
    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(
            config={},
            realtime_status=lambda **kwargs: calls.append(kwargs) or {
                "success": False,
                "cached": True,
                "dependency_status": dependency_status,
            },
        ),
    )
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *_args, **_kwargs: None)
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = "/api/status?detail=summary&scope=window"
    handler.client_address = ("127.0.0.1", 12345)
    handler.headers = {}
    handler.server = None
    handler._begin_trace = lambda _path: None
    handler._require_authorized = lambda: True
    handler.responses = []
    handler._send = lambda status, payload: handler.responses.append((status, payload))

    handler.do_GET()

    assert calls == [{"light": True, "scope": "window"}]
    assert handler.responses == [
        (
            200,
            {
                "success": False,
                "cached": True,
                "dependency_status": dependency_status,
                "detail_level": "summary",
            },
        )
    ]
