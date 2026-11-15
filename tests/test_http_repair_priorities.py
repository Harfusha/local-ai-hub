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
    assert payload["diagnostic_details_available"] is False


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


def test_repair_priorities_exposes_error_page_cursor(monkeypatch):
    report = {
        "enabled": True,
        "success": True,
        "error_fingerprints": [{"component": "repo", "count": 1}],
        "error_fingerprints_page": {"total": 125, "next_offset": 100},
        "http_tail_latency": {"by_action": []},
        "hotspots": [],
        "evaluation": {"cohorts": {"hub_on": {"quality_evaluated": 0}}},
    }
    app = SimpleNamespace(
        config={},
        debug_traces=SimpleNamespace(enabled=True),
        status=lambda **_kwargs: {"success": True, "degraded": False},
        telemetry=SimpleNamespace(report=lambda **_kwargs: report),
        endpoint_stats=SimpleNamespace(get_stats=lambda **_kwargs: {"success": True, "items": []}),
    )
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server, "detailed_diagnostics_enabled", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(http_server, "project_status_response", lambda value, **_kwargs: value)
    monkeypatch.setattr(http_server, "project_aggregate_response", lambda value, **_kwargs: value)
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
    assert payload["coverage"]["next_error_offset"] == 100
    assert payload["complete"] is False


def test_repair_priorities_uses_rolling_samples_and_ignores_lifetime_failures(monkeypatch):
    report_calls = []
    app = SimpleNamespace(
        config={},
        debug_traces=SimpleNamespace(enabled=True),
        status=lambda **_kwargs: {"success": True, "degraded": False, "dependency_status": {}},
        telemetry=SimpleNamespace(report=lambda **kwargs: report_calls.append(kwargs) or {
            "enabled": True,
            "error_fingerprints": [
                {"component": "worker", "error_type": "RuntimeError", "fingerprint": "open", "count": 6, "recovered_count": 1, "last_seen": 123},
                {"component": "worker", "error_type": "RuntimeError", "fingerprint": "resolved", "count": 8, "recovered_count": 8, "last_seen": 123},
            ],
            "error_fingerprints_page": {"total": 2, "next_offset": None},
            "http_tail_latency": {"by_action": [
                {"action": "/api/down", "events": 5, "failures": 4, "failure_rate": 0.8, "p95_duration_ms": 12000},
                {"action": "/api/small-sample", "events": 1, "failures": 1, "failure_rate": 1.0, "p95_duration_ms": 40000},
                {"action": "/api/slow", "events": 20, "failures": 0, "failure_rate": 0.0, "p95_duration_ms": 15000, "p95_queue_wait_ms": 1200},
            ]},
            "evaluation": {"matched_tasks": 12, "cohorts": {"hub_on": {"quality_evaluated": 12, "quality_pass_rate": 0.7}}},
            "hotspots": [],
        }),
        endpoint_stats=SimpleNamespace(get_stats=lambda **_kwargs: {"success": True, "items": [
            {"type": "endpoint", "name": "/api/down", "calls": 100, "issues": ["failing"]},
            {"type": "endpoint", "name": "/api/never", "calls": 100, "issues": ["failing"]},
        ]}),
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
    assert report_calls[0]["scope"] == "window"
    assert report_calls[0]["days"] == 7
    issues = payload["priorities"]
    assert issues == sorted(issues, key=lambda issue: -issue["priority_score"])
    assert next(issue for issue in issues if issue["name"] == "/api/down")["priority"] == "P1"
    assert next(issue for issue in issues if issue["name"] == "/api/small-sample")["confidence"] == "low"
    assert all(issue["evidence"].get("fingerprint") != "resolved" for issue in issues)
    assert all(issue["name"] != "/api/never" for issue in issues)
    assert next(issue for issue in issues if issue["kind"] == "quality")["evidence"]["endpoint_attribution"] is False
    assert "/api/never" in payload["coverage"]["unobserved_routes"]
    assert payload["complete"] is True


def test_repair_priorities_paginates_error_groups(monkeypatch):
    report_calls = []
    app = SimpleNamespace(
        config={},
        debug_traces=SimpleNamespace(enabled=True),
        status=lambda **_kwargs: {"success": True, "degraded": False},
        telemetry=SimpleNamespace(report=lambda **kwargs: report_calls.append(kwargs) or {
            "enabled": True,
            "error_fingerprints": [{"component": "worker", "count": 1, "recovered_count": 0}],
            "error_fingerprints_page": {"total": 201, "next_offset": 200},
            "http_tail_latency": {"by_action": []},
        }),
        endpoint_stats=SimpleNamespace(get_stats=lambda **_kwargs: {"success": True, "items": []}),
    )
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *_args, **_kwargs: None)
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = "/api/repair-priorities?error_offset=100"
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
    assert report_calls[0]["error_offset"] == 100
    assert payload["coverage"]["error_groups_more"] is True
    assert payload["coverage"]["next_error_offset"] == 200
    assert payload["complete"] is False
