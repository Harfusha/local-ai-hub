from __future__ import annotations

from types import SimpleNamespace

import pytest

from local_ai_hub import http_server


_RETIRED_POST_ALIASES = (
    "/api/transcribe",
    "/api/worktree_release",
    "/api/worktrees",
    "/api/lint_fix",
    "/api/pubsub_poll",
    "/api/simulate_merge",
    "/api/flaky_detect",
    "/api/webhook_replay",
)


@pytest.mark.parametrize("path", _RETIRED_POST_ALIASES)
def test_retired_post_alias_returns_404_before_auth_or_service(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    events: list[str] = []
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(services=SimpleNamespace()))
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = path
    handler._require_authorized = lambda: events.append("authorization")
    handler._read_json = lambda: pytest.fail("retired alias must not read its request body")
    handler._begin_trace = lambda *_args, **_kwargs: pytest.fail("retired alias must not start a trace")
    handler._send = lambda status, payload: events.append(f"response:{status}")

    handler.do_POST()

    assert http_server.select_http_routes("POST", path) == ()
    assert events == ["response:404"]


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
    handler._tenant = lambda: "test-tenant"
    handler._read_json = lambda: {"root": ".", "command": "never-run-by-this-test"}
    handler._validate_payload = lambda *_args, **_kwargs: None
    handler._send = lambda status, payload: responses.append((status, payload))

    handler.do_POST()

    assert calls == [((".", "never-run-by-this-test"), {"runs": 5, "timeout_per_run": 30})]
    assert responses == [(200, {"success": True})]
