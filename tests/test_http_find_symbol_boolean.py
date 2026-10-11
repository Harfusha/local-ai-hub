from __future__ import annotations

import logging
from types import SimpleNamespace

from local_ai_hub import http_server


def test_get_find_symbol_parses_false_query_as_false(monkeypatch) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(services=SimpleNamespace(code_find_symbol=lambda *args, **kwargs: calls.append(kwargs) or {"success": True})),
    )
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *_args: None)

    handler = object.__new__(http_server.Handler)
    handler.path = "/api/code/find_symbol?root=C%3A%5Crepo&pattern=Button&include_body=false"
    handler.client_address = ("127.0.0.1", 1234)
    handler._require_authorized = lambda: True
    handler._bind_repository_root_query = lambda _query: True
    handler._begin_trace = lambda _path: None
    handler._send = lambda *_args, **_kwargs: None

    handler.do_GET()

    assert len(calls) == 1
    assert calls[0]["include_body"] is False


def test_post_find_symbol_rejects_string_boolean(monkeypatch) -> None:
    calls: list[dict[str, object]] = []
    responses: list[tuple[int, object]] = []
    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(
            services=SimpleNamespace(code_find_symbol=lambda *args, **kwargs: calls.append(kwargs) or {"success": True}),
            recovery=None,
            logger=logging.getLogger(__name__),
        ),
    )
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *_args: None)

    handler = object.__new__(http_server.Handler)
    handler.path = "/api/code/find_symbol"
    handler.headers = {"Content-Type": "application/json"}
    handler._require_authorized = lambda: True
    handler._bind_repository_root_payload = lambda *_args, **_kwargs: True
    handler._begin_trace = lambda _path: None
    handler._read_json = lambda: {"root": "C:\\repo", "pattern": "Button", "include_body": "false"}
    handler._claim_recovery = lambda *_args: True
    handler._tenant = lambda: "tenant-test"
    handler._agent = lambda: "agent-test"
    handler._send = lambda status, body, **_kwargs: responses.append((status, body))

    handler.do_POST()

    assert calls == []
    assert responses[0][0] == 400
