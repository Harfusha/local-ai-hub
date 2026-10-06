from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub import http_server
from local_ai_hub.http_route_registry import select_get_handler


def test_live_status_named_boundary_is_exact_path_only() -> None:
    assert select_get_handler("/api/live/status") == "_handle_get_live_status"
    assert select_get_handler("/api/live/status?light=1") is None
    assert select_get_handler("/api/status") is None


def test_live_status_handler_preserves_query_defaults_and_200_snapshot(monkeypatch) -> None:
    snapshots = []
    result = {"success": True, "status": "degraded", "dependencies": {"db": "timeout"}}
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(realtime_status=lambda **kwargs: snapshots.append(kwargs) or result))
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.server = object()
    responses = []
    handler._send = lambda status, body: responses.append((status, body))

    handler._handle_get_live_status({"light": ["YES"], "scope": ["1h"]})
    handler._handle_get_live_status({})

    assert snapshots == [{"light": True, "scope": "1h"}, {"light": False, "scope": "process"}]
    assert responses == [(200, result), (200, result)]


def test_live_status_handler_propagates_errors_to_shared_boundary(monkeypatch) -> None:
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(realtime_status=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("status failed"))))
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.server = object()
    handler._send = lambda *_args: None
    with pytest.raises(RuntimeError, match="status failed"):
        handler._handle_get_live_status({})


def test_live_status_named_dispatch_stays_after_auth_mode_trace_and_parse() -> None:
    source = Path(http_server.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    handler = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Handler")
    do_get = next(node for node in handler.body if isinstance(node, ast.FunctionDef) and node.name == "do_GET")
    calls = [
        (node.lineno, node.func.id if isinstance(node.func, ast.Name) else node.func.attr)
        for node in ast.walk(do_get)
        if isinstance(node, ast.Call) and (isinstance(node.func, ast.Name) or isinstance(node.func, ast.Attribute))
    ]
    ordered_calls = sorted(calls)
    auth = next(line for line, name in ordered_calls if name == "_require_authorized")
    mode = next(line for line, name in ordered_calls if name == "_http_mode_gate_error")
    trace = next(line for line, name in ordered_calls if name == "_begin_trace")
    parse = next(line for line, name in ordered_calls if name == "parse_qs")
    dispatch = next(line for line, name in ordered_calls if name == "select_get_handler")
    assert auth < mode < trace < parse < dispatch
    assert "/api/live/status" in http_server.HTTP_MODE_OPERATOR_GET_PATHS
    assert not any(name in {"_claim_recovery", "begin"} for _, name in calls)
    dispatch_try = next(
        node for node in ast.walk(do_get)
        if isinstance(node, ast.Try) and node.lineno < dispatch < node.end_lineno
    )
    assert any(
        isinstance(catch.type, ast.Name) and catch.type.id == "Exception"
        for catch in dispatch_try.handlers
    )


def test_live_status_includes_concurrency_snapshot_for_managed_server(monkeypatch) -> None:
    snapshot = {"success": True, "status": "healthy"}
    concurrency = {"active": 2, "rejected": 0}
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(realtime_status=lambda **_kwargs: snapshot))
    monkeypatch.setattr(http_server.LocalAIHTTPServer, "concurrency_stats", lambda _self: concurrency)
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.server = object.__new__(http_server.LocalAIHTTPServer)
    responses = []
    handler._send = lambda status, body: responses.append((status, body))

    handler._handle_get_live_status({})

    assert responses == [(200, {**snapshot, "http_concurrency": concurrency})]

