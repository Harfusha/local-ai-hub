from __future__ import annotations

from types import SimpleNamespace

import pytest

from local_ai_hub import http_server


@pytest.mark.parametrize("path", ["/api/command/flaky_detect", "/api/flaky_detect"])
def test_retired_flaky_detect_paths_return_404_without_dispatch(
    monkeypatch: pytest.MonkeyPatch, path: str,
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
    handler.path = path
    handler.headers = {"Content-Type": "application/json"}
    handler._require_authorized = lambda: pytest.fail("retired route reached authorization")
    handler._begin_trace = lambda *_args, **_kwargs: pytest.fail("retired route began execution")
    handler._claim_recovery = lambda *_args, **_kwargs: pytest.fail("retired route claimed a mutation")
    handler._read_json = lambda: pytest.fail("retired route read the request body")
    handler._send = lambda status, payload: responses.append((status, payload))

    handler.do_POST()

    assert calls == []
    assert len(responses) == 1
    assert responses[0][0] == 404
