from __future__ import annotations

from types import SimpleNamespace

from local_ai_hub import http_server


def test_status_route_preserves_dependency_diagnostics(monkeypatch):
    dependency_status = {
        "scheduler": {
            "degraded": True,
            "deadline_ms": 250,
            "reason": "probe_error",
            "error_type": "RuntimeError",
        }
    }
    app = SimpleNamespace(
        config={},
        status=lambda **_kwargs: {
            "success": False,
            "hub_online": True,
            "dependency_status": dependency_status,
        },
    )
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *_args, **_kwargs: None)
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = "/api/status?scope=process"
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
    assert payload["success"] is False
    assert payload["dependency_status"] == dependency_status


def test_scoped_agent_state_status_needs_no_global_database_scan(monkeypatch):
    class State:
        enabled = True
        _initialized = True

    app = SimpleNamespace(config={}, agent_state=State())
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *_args, **_kwargs: None)
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = "/api/status?detail=agent_state"
    handler.client_address = ("127.0.0.1", 12345)
    handler.headers = {}
    handler.server = None
    handler._authorization_root = "C:/project"
    handler._begin_trace = lambda _path: None
    handler._require_authorized = lambda: True
    responses = []
    handler._send = lambda status, payload: responses.append((status, payload))

    handler.do_GET()

    assert responses == [(200, {
        "success": True,
        "enabled": True,
        "initialized": True,
        "status": "ok",
        "active_tasks": [],
        "tasks_count": 0,
        "incidents_count": 0,
        "candidates_count": 0,
    })]


def test_agent_state_status_avoids_unscoped_dependency_scan(monkeypatch):
    app = SimpleNamespace(
        config={},
        _status_dependency_lock=object(),
        _status_dependency_inflight={},
        _status_dependency_slots=object(),
        agent_tasks=SimpleNamespace(
            list_tasks=lambda: [SimpleNamespace(task_id="foreign-task", status=http_server.TaskStatus.ACTIVE)]
        ),
    )
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *_args, **_kwargs: None)
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = "/api/status?detail=agent_state"
    handler.client_address = ("127.0.0.1", 12345)
    handler.headers = {}
    handler.server = None
    handler._begin_trace = lambda _path: None
    handler._require_authorized = lambda: True
    responses = []
    handler._send = lambda status, payload: responses.append((status, payload))

    handler.do_GET()

    assert responses[0][0] == 200
    assert "foreign-task" not in repr(responses[0][1])
    assert responses[0][1]["tasks_count"] == 0


def test_summary_status_route_preserves_cached_dependency_diagnostics(monkeypatch):
    calls = []
    dependency_status = {
        "runtime.online": {
            "degraded": True,
            "deadline_ms": 250,
            "reason": "probe_timeout",
        }
    }
    app = SimpleNamespace(
        config={},
        realtime_status=lambda **kwargs: calls.append(kwargs)
        or {
            "success": False,
            "cached": True,
            "dependency_status": dependency_status,
        },
    )
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *_args, **_kwargs: None)
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = "/api/live/status?light=1&scope=window"
    handler.client_address = ("127.0.0.1", 12345)
    handler.headers = {}
    handler.server = None
    handler._begin_trace = lambda _path: None
    handler._require_authorized = lambda: True
    handler.responses = []
    handler._send = lambda status, payload: handler.responses.append((status, payload))

    handler.do_GET()

    assert calls == [{"light": True, "scope": "window"}]
    status, payload = handler.responses[0]
    assert status == 200
    assert payload["success"] is False
    assert payload["dependency_status"] == dependency_status
