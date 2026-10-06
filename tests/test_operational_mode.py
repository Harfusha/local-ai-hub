from __future__ import annotations

import json

import pytest

from local_ai_hub.operational_mode import load_operational_mode, set_operational_mode


def test_missing_mode_file_defaults_to_active(tmp_path):
    snapshot = load_operational_mode(tmp_path)

    assert snapshot.mode == "active"
    assert snapshot.revision == 0
    assert snapshot.degraded is False
    assert snapshot.error == ""


def test_mode_updates_are_persisted_and_increment_revision(tmp_path):
    first = set_operational_mode(tmp_path, "gaming")
    second = set_operational_mode(tmp_path, "maintenance")

    assert first.mode == "gaming"
    assert first.revision == 1
    assert second.mode == "maintenance"
    assert second.revision == 2
    assert load_operational_mode(tmp_path) == second
    assert json.loads((tmp_path / "operational_mode.json").read_text(encoding="utf-8"))["mode"] == "maintenance"


def test_corrupt_mode_fails_closed_to_maintenance(tmp_path):
    (tmp_path / "operational_mode.json").write_text("{", encoding="utf-8")

    snapshot = load_operational_mode(tmp_path)

    assert snapshot.mode == "maintenance"
    assert snapshot.degraded is True
    assert snapshot.error


def test_invalid_mode_is_rejected_without_replacing_persisted_state(tmp_path):
    original = set_operational_mode(tmp_path, "gaming")

    with pytest.raises(ValueError):
        set_operational_mode(tmp_path, "paused")

    assert load_operational_mode(tmp_path) == original


def test_mcp_agent_tool_is_rejected_before_dispatch_but_status_remains_available(monkeypatch, tmp_path):
    from local_ai_hub import mcp_server

    set_operational_mode(tmp_path, "gaming")
    monkeypatch.setattr(mcp_server, "configured_state_dir", lambda *_args, **_kwargs: tmp_path)
    adoption_calls = []
    monkeypatch.setattr(mcp_server, "_record_adoption", lambda *args, **kwargs: adoption_calls.append(args))

    rejected = mcp_server.local_ai_repo(action="search", query="needle")

    assert rejected["error_code"] == "operational_mode_blocked"
    assert rejected["terminal"] is True
    assert rejected["retryable"] is False
    assert adoption_calls == []

    status_calls = []
    monkeypatch.setattr(mcp_server.FEATURES, "status", True)
    monkeypatch.setattr(
        mcp_server.CLIENT,
        "get",
        lambda path: status_calls.append(path) or {"hub_online": True, "runtime_stats": {}},
    )
    mcp_server.local_ai_status(action="health")
    assert status_calls


def test_http_mode_routes_read_and_update_persisted_mode(monkeypatch, tmp_path):
    from local_ai_hub import http_server

    unload_calls = []
    runtime = type("Runtime", (), {
        "unload_configured_models": lambda self, **kwargs: unload_calls.append(kwargs) or {
            "success": True, "backend_available": True, "unloaded": ["model-a"], "failed": {},
        },
    })()
    mode_changes = []
    guard_state = []

    class ModeGuard:
        def __enter__(self):
            guard_state.append("entered")

        def __exit__(self, *_exc):
            guard_state.append("exited")

    def mode_changed(_self, snapshot):
        assert guard_state == ["entered"]
        mode_changes.append((snapshot, load_operational_mode(tmp_path)))

    async_jobs = type("AsyncJobs", (), {
        "operational_mode_change_guard": lambda self: ModeGuard(),
        "on_operational_mode_changed": mode_changed,
    })()
    monkeypatch.setattr(http_server, "APP", type("App", (), {
        "config": {"server": {"state_dir": str(tmp_path)}}, "runtime": runtime, "async_jobs": async_jobs,
    })())
    responses = []
    handler = type("MockHandler", (), {
        "path": "/api/mode",
        "headers": {},
        "_begin_trace": lambda self, _path: None,
        "_require_authorized": lambda self: True,
        "_send": lambda self, status, payload: responses.append((status, payload)),
    })()

    http_server.Handler.do_GET(handler)
    assert responses[-1][0] == 200
    assert responses[-1][1]["mode"] == "active"

    handler.path = "/api/admin/mode"
    handler._read_json = lambda: {"mode": "gaming"}
    http_server.Handler.do_POST(handler)
    assert responses[-1][0] == 200
    assert responses[-1][1]["mode"] == "gaming"
    assert responses[-1][1]["runtime_unload"]["unloaded"] == ["model-a"]
    assert len(unload_calls) == 1
    assert 2.9 < unload_calls[0]["timeout_seconds"] <= 3.0
    assert mode_changes[0][0].mode == "gaming"
    assert mode_changes[0][1].mode == "gaming"
    assert guard_state == ["entered", "exited"]
    assert load_operational_mode(tmp_path).mode == "gaming"


def test_http_mode_update_rejects_invalid_and_unauthorized_requests(monkeypatch, tmp_path):
    from local_ai_hub import http_server

    monkeypatch.setattr(http_server, "APP", type("App", (), {
        "config": {"server": {"state_dir": str(tmp_path)}},
    })())
    responses = []
    handler = type("MockHandler", (), {
        "path": "/api/admin/mode",
        "headers": {},
        "_begin_trace": lambda self, _path: None,
        "_require_authorized": lambda self: True,
        "_send": lambda self, status, payload: responses.append((status, payload)),
        "_read_json": lambda self: {"mode": "paused"},
    })()

    http_server.Handler.do_POST(handler)
    assert responses[-1][0] == 400
    assert responses[-1][1]["terminal"] is True
    assert load_operational_mode(tmp_path).mode == "active"

    handler._require_authorized = lambda: False
    handler._read_json = lambda: pytest.fail("unauthorized request body must not be read")
    http_server.Handler.do_POST(handler)
    assert load_operational_mode(tmp_path).mode == "active"


def test_http_mode_update_reports_missing_async_cancellation_hook(monkeypatch, tmp_path):
    from local_ai_hub import http_server

    runtime = type("Runtime", (), {
        "unload_configured_models": lambda self, **kwargs: {
            "success": True, "backend_available": True, "unloaded": [], "failed": {},
        },
    })()
    monkeypatch.setattr(http_server, "APP", type("App", (), {
        "config": {"server": {"state_dir": str(tmp_path)}}, "runtime": runtime,
    })())
    responses = []
    handler = type("MockHandler", (), {
        "path": "/api/admin/mode",
        "headers": {},
        "_begin_trace": lambda self, _path: None,
        "_require_authorized": lambda self: True,
        "_send": lambda self, status, payload: responses.append((status, payload)),
        "_read_json": lambda self: {"mode": "maintenance"},
    })()

    http_server.Handler.do_POST(handler)

    assert responses[-1][0] == 200
    assert responses[-1][1]["success"] is True
    assert responses[-1][1]["job_cancellation"] == {
        "success": False, "error": "operational mode cancellation hook is unavailable",
    }
    assert load_operational_mode(tmp_path).mode == "maintenance"
