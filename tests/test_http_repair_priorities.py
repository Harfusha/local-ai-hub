from types import SimpleNamespace

from local_ai_hub import http_server


def test_repair_priorities_hides_detailed_telemetry_when_toggle_is_off(monkeypatch):
    app = SimpleNamespace(
        config={},
        debug_traces=SimpleNamespace(enabled=False),
        status=lambda **_kwargs: {
            "success": True,
            "degraded": True,
            "dependency_status": {"scheduler": {
                "degraded": True,
                "deadline_ms": 250,
                "reason": "probe_error",
                "error_type": "RuntimeError",
            }},
        },
        telemetry=SimpleNamespace(report=lambda **_kwargs: {
            "enabled": True,
            "error_fingerprints": [{"component": "scheduler", "count": 7}],
            "hotspots": [{"type": "reliability", "signal": "scheduler.timeout"}],
            "evaluation": {"cohorts": {"hub_on": {"quality_evaluated": 12, "quality_pass_rate": 0.2}}},
        }),
        endpoint_stats=SimpleNamespace(get_stats=lambda **_kwargs: {"success": True, "items": []}),
    )
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *_args, **_kwargs: None)
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = "/api/repair-priorities"
    handler.client_address = ("127.0.0.1", 12345)
    handler.headers = {}
    handler.server = None
    handler._begin_trace = lambda _path: None
    handler._require_authorized = lambda: True
    responses = []
    handler._send = lambda status, payload: responses.append((status, payload))

    handler.do_GET()

    status, payload = responses[0]
    assert status == 200
    assert payload["health"]["dependencies"]["scheduler"] == {
        "degraded": True,
        "error_type": "RuntimeError",
    }
    assert [item["kind"] for item in payload["priorities"]] == ["component"]


def test_repair_priorities_marks_missing_sources_unavailable(monkeypatch):
    app = SimpleNamespace(
        config={},
        debug_traces=SimpleNamespace(enabled=False),
        status=lambda **_kwargs: {"success": True, "degraded": False},
        telemetry=SimpleNamespace(report=lambda **_kwargs: {}),
        endpoint_stats=SimpleNamespace(get_stats=lambda **_kwargs: {"success": False, "items": []}),
    )
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *_args, **_kwargs: None)
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = "/api/repair-priorities"
    handler.client_address = ("127.0.0.1", 12345)
    handler.headers = {}
    handler.server = None
    handler._begin_trace = lambda _path: None
    handler._require_authorized = lambda: True
    responses = []
    handler._send = lambda status, payload: responses.append((status, payload))

    handler.do_GET()

    payload = responses[0][1]
    assert payload["telemetry_available"] is False
    assert payload["endpoint_stats_available"] is False
