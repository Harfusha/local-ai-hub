from __future__ import annotations

from types import SimpleNamespace

import pytest

from local_ai_hub import http_server


@pytest.mark.parametrize("detail,expected", [("brief", "summary"), ("summary", "summary"), ("full", "full")])
def test_status_detail_uses_requested_level_when_diagnostics_enabled(monkeypatch, detail, expected):
    app = SimpleNamespace(
        config={},
        realtime_status=lambda **_kwargs: {"success": True, "source": "summary"},
        status=lambda **_kwargs: {"success": True, "source": "full"},
    )
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *_args: None)
    monkeypatch.setattr(http_server, "detailed_diagnostics_enabled", lambda *_args, **_kwargs: True)
    handler = object.__new__(http_server.Handler)
    handler.path = f"/api/status?detail={detail}"
    handler.command = "GET"
    handler.headers = {}
    handler.server = SimpleNamespace()
    handler._require_authorized = lambda *_args, **_kwargs: True
    handler._begin_trace = lambda *_args: None
    responses = []
    handler._send = lambda status, payload, **_kwargs: responses.append((status, payload))
    handler.do_GET()
    assert len(responses) == 1
    status, payload = responses[0]
    assert status == 200
    assert payload["detail_level"] == expected
    assert payload["source"] == expected
