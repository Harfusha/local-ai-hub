from __future__ import annotations

import logging
from types import SimpleNamespace

from local_ai_hub import http_server


def test_post_repo_call_graph_rejects_invalid_depth_before_service_call(monkeypatch) -> None:
    calls: list[tuple[object, ...]] = []
    responses: list[tuple[int, object]] = []
    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(
            services=SimpleNamespace(call_graph=lambda *args, **kwargs: calls.append(args) or {"success": True}),
            recovery=None,
            logger=logging.getLogger(__name__),
        ),
    )
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *_args: None)

    handler = object.__new__(http_server.Handler)
    handler.path = "/api/repo/call_graph"
    handler.headers = {"Content-Type": "application/json"}
    handler._require_authorized = lambda: True
    handler._bind_repository_root_payload = lambda *_args, **_kwargs: True
    handler._begin_trace = lambda _path: None
    handler._read_json = lambda: {"root": "C:\\repo", "symbol": "Widget", "depth": "deep"}
    handler._claim_recovery = lambda *_args: True
    handler._agent = lambda: "agent-test"
    handler._send = lambda status, body, **_kwargs: responses.append((status, body))

    handler.do_POST()

    assert calls == []
    assert responses[0][0] == 400
    assert responses[0][1]["error"] == "depth must be an integer from 1 to 2"
