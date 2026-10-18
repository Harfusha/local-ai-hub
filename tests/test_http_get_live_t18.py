from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub import http_server
from local_ai_hub.http_route_registry import select_get_handler


def test_live_named_boundary_is_exact_path_only() -> None:
    assert select_get_handler("/api/live") == "_handle_get_live"
    assert select_get_handler("/api/live?after=3") is None
    assert select_get_handler("/api/status") is None


def test_live_handler_preserves_cursor_limits_clamp_and_response(monkeypatch) -> None:
    calls = []
    live_page = {"events": [{"id": 11}], "next_after": 11}
    monkeypatch.setattr(
        http_server, "APP",
        SimpleNamespace(config={"monitoring": {"live_max_batch": 250}}, telemetry=SimpleNamespace(live=lambda after, limit: calls.append((after, limit)) or live_page)),
    )
    handler = http_server.Handler.__new__(http_server.Handler)
    responses = []
    handler._send = lambda status, body: responses.append((status, body))

    handler._handle_get_live({"after": ["10"], "limit": ["400"]})
    handler._handle_get_live({})

    assert calls == [(10, 250), (0, 200)]
    assert responses == [(200, live_page), (200, live_page)]


def test_live_handler_propagates_parse_and_service_errors_to_shared_boundary(monkeypatch) -> None:
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={}, telemetry=SimpleNamespace(live=lambda *_args: (_ for _ in ()).throw(RuntimeError("live read failed")))))
    handler = http_server.Handler.__new__(http_server.Handler)
    handler._send = lambda *_args: None
    with pytest.raises(ValueError):
        handler._handle_get_live({"after": ["invalid"]})
    with pytest.raises(RuntimeError, match="live read failed"):
        handler._handle_get_live({})


def test_live_named_dispatch_follows_shared_gates_and_keeps_read_policy() -> None:
    source = Path(http_server.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    handler = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Handler")
    do_get = next(node for node in handler.body if isinstance(node, ast.FunctionDef) and node.name == "do_GET")
    calls = [
        (node.lineno, node.func.id if isinstance(node.func, ast.Name) else node.func.attr)
        for node in ast.walk(do_get)
        if isinstance(node, ast.Call) and (isinstance(node.func, ast.Name) or isinstance(node.func, ast.Attribute))
    ]
    dispatch = next(line for line, name in calls if name == "select_get_handler")
    prelude = []
    for statement in do_get.body:
        if isinstance(statement, ast.Try):
            break
        prelude.append(statement)
    prelude_calls = [
        (node.lineno, node.func.id if isinstance(node.func, ast.Name) else node.func.attr)
        for statement in prelude for node in ast.walk(statement)
        if isinstance(node, ast.Call) and (isinstance(node.func, ast.Name) or isinstance(node.func, ast.Attribute))
    ]
    auth = max(line for line, name in prelude_calls if name == "_require_authorized")
    mode = next(line for line, name in prelude_calls if name == "_http_mode_gate_error")
    trace = next(line for line, name in prelude_calls if name == "_begin_trace")
    parses = sorted(line for line, name in prelude_calls if name == "parse_qs")
    retired_query_validation = next(
        line for line, name in prelude_calls if name == "_reject_identity_fields"
    )
    assert retired_query_validation == parses[0]
    assert parses[0] < auth < mode < trace < parses[-1] < dispatch
    assert "/api/live" not in http_server.HTTP_MODE_OPERATOR_GET_PATHS
    assert "/api/live" not in http_server.HTTP_MODE_GAMING_READ_GET_PATHS
    assert http_server._http_mode_policy("GET", "/api/live") == "blocked"
    assert not any(name in {"_claim_recovery", "begin"} for _, name in calls)

    dispatch_try = next(node for node in ast.walk(do_get) if isinstance(node, ast.Try) and node.lineno < dispatch < node.end_lineno)
    assert any(isinstance(catch.type, ast.Name) and catch.type.id == "Exception" for catch in dispatch_try.handlers)
