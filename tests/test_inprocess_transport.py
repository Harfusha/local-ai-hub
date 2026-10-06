from __future__ import annotations

import logging
import subprocess
import socket
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest


class _Telemetry:
    def __init__(self):
        self.live_events = []

    def record_live(self, **event):
        self.live_events.append(event)

    def record_http(self, **_event):
        return None

    def record_error(self, *_args, **_kwargs):
        return None


class _Recovery:
    def __init__(self):
        self.requests = []

    def lookup(self, request_id, tenant, action):
        return None

    def begin(self, request_id, tenant, action, **_identity):
        self.requests.append((request_id, tenant, action))
        return {"claimed": True}

    def finish(self, *_args, **_kwargs):
        return None


class _App:
    def __init__(self, state_dir: Path):
        self.config = {
            "_config_path": str(state_dir.parent / "config.toml"),
            "server": {
                "bind": "127.0.0.1",
                "client_host": "127.0.0.1",
                "port": 11435,
                "state_dir": str(state_dir),
                "request_body_timeout_seconds": 1.0,
                "max_request_body_bytes": 1024,
            },
            "security": {
                "api_token": "test-secret",
                "allow_remote": False,
                "rate_limit_requests": 600,
                "rate_limit_window_seconds": 60.0,
                "allowed_origins": [],
            },
            "observability": {"exclude_http_paths": []},
        }
        self.telemetry = _Telemetry()
        self.recovery = _Recovery()
        self.debug_traces = None
        self.deterministic = object()
        self.logger = logging.getLogger("test-inprocess-transport")
        self.closed = False
        self.topology_calls = []
        self.cancel_calls = []
        self.delegate_calls = []
        self.services = SimpleNamespace(
            repo_topology=self.repo_topology,
            delegate=self.delegate,
        )
        self.work_orchestrator = SimpleNamespace(enabled=True, cancel=self.cancel)

    def repo_topology(self, root):
        self.topology_calls.append(root)
        return {"success": True, "root": root, "source": "service"}

    def delegate(self, payload, tenant):
        self.delegate_calls.append((dict(payload), tenant))
        return {"success": True, "tenant": tenant, "task": payload.get("task", "")}

    def cancel(self, tenant, work_id):
        self.cancel_calls.append((tenant, work_id))
        return {"success": True, "cancelled": work_id}

    def close(self):
        self.closed = True


@pytest.fixture
def inprocess_client(tmp_path, monkeypatch):
    from local_ai_hub import http_server
    from local_ai_hub.client import HubClient
    from local_ai_hub.inprocess_transport import InProcessTransport
    from local_ai_hub.operational_mode import set_operational_mode

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[server]\n"
        'bind = "127.0.0.1"\n'
        'client_host = "127.0.0.1"\n'
        "port = 11435\n"
        f'state_dir = "{state_dir.as_posix()}"\n'
        "[security]\n"
        'api_token = "test-secret"\n'
        "allow_remote = false\n"
        "rate_limit_requests = 600\n"
        "rate_limit_window_seconds = 60.0\n",
        encoding="utf-8",
    )
    set_operational_mode(state_dir, "active")
    app = _App(state_dir)
    monkeypatch.setattr(http_server, "APP", None)
    transport = InProcessTransport(config_path=str(config_path))
    monkeypatch.setattr(transport, "_create_app", lambda: app)
    client = HubClient(
        tenant="tenant-a",
        config_path=str(config_path),
        auto_start=True,
        inprocess_transport=transport,
    )
    try:
        yield client, transport, app, state_dir
    finally:
        client.close()
        monkeypatch.setattr(http_server, "APP", None)


def test_inprocess_transport_routes_to_services_without_http_or_spawn(inprocess_client, monkeypatch):
    import http.client

    client, _transport, app, _state_dir = inprocess_client

    def forbidden(*_args, **_kwargs):
        raise AssertionError("in-process transport attempted HTTP or process startup")

    monkeypatch.setattr(http.client, "HTTPConnection", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(client, "ensure_server", forbidden)

    result = client.get(
        "/api/repo/topology?root=fixture-root",
        operational_action="repo_topology",
    )

    assert result == {"success": True, "root": "fixture-root", "source": "service"}
    assert app.topology_calls == ["fixture-root"]
    event = app.telemetry.live_events[0]
    assert event["tenant"] == "tenant-a"
    assert event["agent"] == client.agent
    assert event["request_id"].startswith("req_")


def test_inprocess_transport_lazily_creates_app_without_http_or_process(inprocess_client, monkeypatch):
    import http.client
    import socket

    client, transport, _fake_app, _state_dir = inprocess_client
    from local_ai_hub import http_server
    from local_ai_hub.inprocess_transport import InProcessTransport

    created = []
    create_app = InProcessTransport._create_app.__get__(transport, InProcessTransport)

    def create_real_app():
        app = create_app()
        app.services.repo_topology = lambda root: {
            "success": True,
            "root": root,
            "source": "real-app-service",
        }
        created.append(app)
        return app

    monkeypatch.setattr(transport, "_create_app", create_real_app)
    monkeypatch.setattr(http_server, "APP", None)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("in-process app attempted HTTP or child-process startup")

    monkeypatch.setattr(http.client, "HTTPConnection", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(client, "ensure_server", forbidden)

    result = client.get(
        "/api/repo/topology?root=fixture-root",
        operational_action="repo_topology",
    )

    assert result == {
        "success": True,
        "root": "fixture-root",
        "source": "real-app-service",
    }
    assert len(created) == 1
    assert http_server.APP is created[0]
    client.close()
    assert created[0]._closed is True


def test_inprocess_transport_preserves_request_identity_and_cancel_route(inprocess_client):
    client, _transport, app, _state_dir = inprocess_client

    result = client.request(
        "/api/work-orders",
        {"action": "cancel", "work_id": "work-17"},
        request_id="stable-cancel-17",
        operational_action="work_orders",
    )

    assert result == {
        "success": True,
        "cancelled": "work-17",
        "request_id": "stable-cancel-17",
    }
    assert app.cancel_calls == [("tenant-a", "work-17")]
    assert app.recovery.requests == [
        ("stable-cancel-17", "tenant-a", "/api/work-orders")
    ]


def test_inprocess_transport_keeps_http_rate_limit_across_requests(inprocess_client):
    client, transport, _app, _state_dir = inprocess_client
    transport._admission._rate_limit_requests = 1

    first = client.get(
        "/api/repo/topology?root=fixture-root",
        operational_action="repo_topology",
    )
    second = client.get(
        "/api/repo/topology?root=fixture-root",
        operational_action="repo_topology",
    )

    assert first["success"] is True
    assert second["status_code"] == 429
    assert second["retryable"] is True


def test_inprocess_transport_preserves_auth_and_payload_validation(inprocess_client):
    client, _transport, _app, _state_dir = inprocess_client
    from local_ai_hub.operational_mode import set_operational_mode

    set_operational_mode(_state_dir, "gaming")
    client.api_token = "wrong-token"

    unauthorized = client.get(
        "/api/repo/topology?root=fixture-root",
        operational_action="repo_topology",
    )
    assert unauthorized["status_code"] == 401
    assert unauthorized["success"] is False

    set_operational_mode(_state_dir, "active")
    client.api_token = "test-secret"
    invalid_action = client.request(
        "/api/work-orders",
        {"action": "not-a-work-order-action"},
        operational_action="work_orders",
    )
    assert invalid_action["status_code"] == 400
    assert invalid_action["terminal"] is True
    assert "unsupported work-order action" in invalid_action["error"]


def test_inprocess_transport_fails_closed_in_restricted_operational_mode(inprocess_client, monkeypatch):
    client, _transport, app, state_dir = inprocess_client
    from local_ai_hub.operational_mode import set_operational_mode

    set_operational_mode(state_dir, "gaming")

    result = client.request(
        "/api/delegate",
        {"task": "heavy work"},
        operational_action="delegate",
    )

    assert app.delegate_calls == []
    assert result["error_code"] == "operational_mode_blocked"
    assert result["operational_mode"] == "gaming"
    assert result["action"] == "delegate"
    assert result["retryable"] is True


def test_inprocess_transport_keeps_deterministic_read_allowed_in_restricted_mode(inprocess_client):
    client, _transport, app, state_dir = inprocess_client
    from local_ai_hub.operational_mode import set_operational_mode

    set_operational_mode(state_dir, "gaming")
    result = client.get(
        "/api/repo/topology?root=fixture-root",
        operational_action="repo_topology",
        requires_heavy_work=False,
    )

    assert result == {"success": True, "root": "fixture-root", "source": "service"}
    assert app.topology_calls == ["fixture-root"]


def test_inprocess_timeout_reports_uncertain_result_but_does_not_cancel_service(inprocess_client):
    client, _transport, app, _state_dir = inprocess_client
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def slow_cancel(tenant, work_id):
        started.set()
        release.wait(2.0)
        finished.set()
        return {"success": True, "tenant": tenant, "cancelled": work_id}

    app.work_orchestrator.cancel = slow_cancel

    try:
        result = client.request(
            "/api/work-orders",
            {"action": "cancel", "work_id": "timeout-probe"},
            timeout=0.2,
            operational_action="work_orders",
        )
        assert started.is_set()
        assert result["outcome_unknown"] is True
        assert result["request_id"]
    finally:
        release.set()
    assert finished.wait(1.0)


def test_inprocess_cancel_after_dispatch_reports_unknown_and_stops_waiting(inprocess_client):
    client, _transport, app, _state_dir = inprocess_client
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    cancel = threading.Event()
    response = {}
    request_done = threading.Event()

    def slow_cancel(tenant, work_id):
        started.set()
        release.wait(2.0)
        finished.set()
        return {"success": True, "tenant": tenant, "cancelled": work_id}

    def send_request():
        response["value"] = client.request(
            "/api/work-orders",
            {"action": "cancel", "work_id": "cancel-probe"},
            timeout=2.0,
            operational_action="work_orders",
            cancel_event=cancel,
        )
        request_done.set()

    app.work_orchestrator.cancel = slow_cancel
    worker = threading.Thread(target=send_request, daemon=True)
    worker.start()
    try:
        assert started.wait(1.0)
        cancel.set()
        assert request_done.wait(1.0)
        result = response["value"]
        assert result["cancelled"] is True
        assert result["outcome_unknown"] is True
        assert result.get("request_not_sent") is not True
    finally:
        release.set()
    assert finished.wait(1.0)


def test_inprocess_timeout_before_admission_does_not_dispatch_later(inprocess_client):
    client, transport, app, _state_dir = inprocess_client
    transport._overload_wait_seconds = 0.5
    transport._handler_slots = threading.BoundedSemaphore(1)
    assert transport._handler_slots.acquire(blocking=False)

    result = client.request(
        "/api/work-orders",
        {"action": "cancel", "work_id": "late-dispatch-probe"},
        timeout=0.2,
        operational_action="work_orders",
    )

    assert result["request_not_sent"] is True
    transport._handler_slots.release()
    with transport._condition:
        assert transport._condition.wait_for(lambda: not transport._active, timeout=1.0)
    assert app.cancel_calls == []
