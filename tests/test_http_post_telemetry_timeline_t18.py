from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub import http_server
from local_ai_hub.http_route_registry import select_http_routes, select_post_handler


def test_timeline_is_the_only_registered_t18_route_and_pack_stays_inline() -> None:
    ids = select_http_routes("POST", "/api/telemetry/timeline")
    assert ids == ("post_telemetry_timeline_1",)
    assert select_post_handler(ids) == "_handle_post_telemetry_timeline"
    assert select_http_routes("POST", "/api/context/pack") == ()


def test_timeline_handler_preserves_status_body_arguments_and_degrades_backend_error(monkeypatch) -> None:
    page = {"events": [{"event_id": "evt-1"}], "next_before_id": "evt-1"}
    calls = []
    warnings = []

    def get_page(limit, *, before_id):
        calls.append((limit, before_id))
        return page

    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(
            telemetry=SimpleNamespace(get_timeline_page=get_page),
            logger=SimpleNamespace(warning=lambda *args: warnings.append(args)),
        ),
    )
    handler = http_server.Handler.__new__(http_server.Handler)
    responses = []
    handler._send = lambda status, body: responses.append((status, body))
    handler._handle_post_telemetry_timeline({"limit": "25", "before_id": "evt-8"})
    assert calls == [("25", "evt-8")]
    assert responses == [(200, {"success": True, **page})]

    def fail_page(*args, **kwargs):
        raise RuntimeError("timeline backend failed")

    monkeypatch.setattr(http_server.APP.telemetry, "get_timeline_page", fail_page)
    handler._handle_post_telemetry_timeline({})
    assert responses[1] == (
        503,
        {
            "success": False,
            "error": {
                "code": "telemetry_page_unavailable",
                "message": "telemetry timeline is temporarily unavailable",
            },
            "status_code": 503,
            "retryable": True,
            "terminal": False,
        },
    )
    assert warnings == [("telemetry timeline page failed error_type=%s", "RuntimeError")]


def test_named_dispatch_keeps_existing_gate_and_exception_order() -> None:
    source_path = Path(http_server.__file__)
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    handler = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Handler")
    do_post = next(node for node in handler.body if isinstance(node, ast.FunctionDef) and node.name == "do_POST")
    calls = [
        (node.lineno, node.func.id if isinstance(node.func, ast.Name) else node.func.attr)
        for node in ast.walk(do_post)
        if isinstance(node, ast.Call) and (isinstance(node.func, ast.Name) or isinstance(node.func, ast.Attribute))
    ]
    dispatch_line = next(line for line, name in calls if name == "select_post_handler")
    auth_line = next(line for line, name in calls if name == "_require_authorized")
    mode_line = max(line for line, name in calls if name == "_http_mode_gate_error")
    parse_line = max(line for line, name in calls if name == "_read_json")
    recovery_lines = [line for line, name in calls if name in {"_claim_recovery", "begin"} and line < dispatch_line]
    assert auth_line < parse_line < mode_line < dispatch_line
    assert recovery_lines
    containing_try = [
        node for node in ast.walk(do_post)
        if isinstance(node, ast.Try) and node.lineno < dispatch_line < node.end_lineno
    ]
    assert containing_try
    assert any(
        isinstance(catch.type, ast.Name) and catch.type.id == "Exception"
        for node in containing_try for catch in node.handlers
    )
