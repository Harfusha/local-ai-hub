from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

import pytest

from local_ai_hub import http_server


def _post_handler(path: str, payload: dict[str, object]):
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = path
    handler.raw_requestline = b"POST / HTTP/1.1\r\n"
    handler.requestline = "POST / HTTP/1.1"
    handler.command = "POST"
    handler.request_version = "HTTP/1.1"
    handler.path = path
    handler.headers = {"Content-Type": "application/json"}
    handler._begin_trace = lambda _path: None
    handler._require_authorized = lambda: True
    handler._read_json = lambda: payload
    handler._validate_payload = lambda _path, _payload: None
    handler.responses = []
    handler._send = lambda status, data: handler.responses.append((status, data))
    return handler


@pytest.mark.parametrize("mode", ["gaming", "maintenance"])
def test_context_pack_is_retryably_gated_in_paused_modes(monkeypatch, mode: str):
    snapshot = SimpleNamespace(mode=mode, degraded=False)
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(
        config={"server": {"state_dir": "state"}}, recovery=None,
    ))
    monkeypatch.setattr(http_server, "load_operational_mode", lambda _state_dir: snapshot)

    handler = _post_handler("/api/context/pack", {"root": "C:/work", "query": "lookup"})
    handler.do_POST()

    assert handler.responses[0][0] == 503
    assert handler.responses[0][1]["retryable"] is True
    assert handler.responses[0][1]["terminal"] is False
    assert handler.responses[0][1]["mode"] == mode


def test_gaming_allows_safe_reads_but_maintenance_blocks_agent_reads():
    assert http_server._http_mode_policy("POST", "/api/artifact/get", {}) == "gaming_read"
    assert http_server._http_mode_policy("POST", "/api/memory/search", {}) == "gaming_read"
    assert http_server._http_mode_policy("POST", "/api/command", {"action": "run"}) == "blocked"
    assert http_server._http_mode_policy("GET", "/api/context/pack") == "blocked"
    assert http_server._http_mode_policy("POST", "/api/async-jobs", {"job_action": "result"}) == "existing_job"

@pytest.mark.parametrize(
    ("length", "should_drain"),
    [(0, False), (64 * 1024 + 1, True), (128 * 1024, True), (128 * 1024 + 1, False)],
)
def test_windows_rejected_mode_post_drains_only_after_the_response(monkeypatch, length, should_drain):
    monkeypatch.setattr(http_server, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(
        config={"server": {"max_request_body_bytes": 128 * 1024}},
    ))
    blocked = {"success": False, "mode": "preprocessing", "error_code": "operational_mode_blocked"}
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda _method, _path: blocked)
    events = []
    timeouts = []
    handler = _post_handler("/api/search", {})
    handler.headers["Content-Length"] = str(length)
    handler._send = lambda status, _data: events.append(status)
    handler._read_json = lambda: pytest.fail("a rejected POST must skip JSON parsing")
    handler.wfile = SimpleNamespace(flush=lambda: events.append("flush"))
    handler.connection = SimpleNamespace(
        shutdown=lambda how: events.append(how),
        settimeout=timeouts.append,
    )
    handler.rfile = BytesIO(b"x" * length)

    handler.do_POST()

    assert events == ([423, "flush", http_server.socket.SHUT_WR] if should_drain else [423])
    assert handler.rfile.tell() == (length if should_drain else 0)
    assert bool(timeouts) == should_drain
    assert all(0 < timeout <= 0.100001 for timeout in timeouts)
