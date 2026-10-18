from __future__ import annotations

from types import SimpleNamespace

import pytest

from local_ai_hub import http_server


def test_canonical_flaky_detect_post_reaches_registered_dispatch_without_running_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    responses: list[tuple[int, object]] = []
    services = SimpleNamespace(
        test_flaky_detect=lambda *args, **kwargs: calls.append((args, kwargs)) or {"success": True}
    )
    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(services=services, recovery=None, debug_traces=None),
    )
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *args, **kwargs: None)
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = "/api/command/flaky_detect"
    handler.headers = {"Content-Type": "application/json"}
    handler._require_authorized = lambda: True
    handler._begin_trace = lambda *_args, **_kwargs: None
    handler._claim_recovery = lambda *_args, **_kwargs: True
    handler._read_json = lambda: {"root": ".", "command": "never-run-by-this-test"}
    handler._validate_payload = lambda *_args, **_kwargs: None
    handler._send = lambda status, payload: responses.append((status, payload))

    handler.do_POST()

    assert calls == [((".", "never-run-by-this-test"), {"runs": 5, "timeout_per_run": 30})]
    assert responses == [(200, {"success": True})]
