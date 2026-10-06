from __future__ import annotations

import ast
from pathlib import Path

import pytest

from local_ai_hub import http_server
from local_ai_hub.http_route_registry import select_http_routes, select_post_handler


def test_db_query_selects_named_t18_handler() -> None:
    route_ids = select_http_routes("POST", "/api/db/query")
    assert route_ids == ("post_db_query_1",)
    assert select_post_handler(route_ids) == "_handle_post_db_query"


def test_db_query_handler_preserves_payload_defaults_and_response_contract() -> None:
    handler = http_server.Handler.__new__(http_server.Handler)
    calls = []
    responses = []
    result = {"success": False, "error": "query execution exceeded work limit"}
    handler._handle_db_query = lambda db_name, sql: calls.append((db_name, sql)) or result
    handler._send = lambda status, body: responses.append((status, body))

    handler._handle_post_db_query({"db": "agent_state", "query": "SELECT count(*) FROM tasks"})
    handler._handle_post_db_query({})

    assert calls == [
        ("agent_state", "SELECT count(*) FROM tasks"),
        ("agent_state", "SELECT name FROM sqlite_master WHERE type=\'table\'"),
    ]
    assert responses == [(200, result), (200, result)]


def test_db_query_handler_propagates_errors_to_shared_http_boundary() -> None:
    handler = http_server.Handler.__new__(http_server.Handler)

    def fail_query(db_name, sql):
        raise RuntimeError("db query failed")

    handler._handle_db_query = fail_query
    with pytest.raises(RuntimeError, match="db query failed"):
        handler._handle_post_db_query({"query": "SELECT 1"})


def test_db_query_keeps_auth_mode_recovery_and_error_boundary_order() -> None:
    source = Path(http_server.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    handler = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Handler")
    do_post = next(node for node in handler.body if isinstance(node, ast.FunctionDef) and node.name == "do_POST")
    calls = [
        (node.lineno, node.func.id if isinstance(node.func, ast.Name) else node.func.attr)
        for node in ast.walk(do_post)
        if isinstance(node, ast.Call) and (isinstance(node.func, ast.Name) or isinstance(node.func, ast.Attribute))
    ]
    auth_line = next(line for line, name in calls if name == "_require_authorized")
    parse_line = max(line for line, name in calls if name == "_read_json")
    mode_line = max(line for line, name in calls if name == "_http_mode_gate_error")
    dispatch_line = next(line for line, name in calls if name == "select_post_handler")
    recovery_line = max(line for line, name in calls if name in {"_claim_recovery", "begin"} and line < dispatch_line)
    assert auth_line < parse_line < mode_line < recovery_line < dispatch_line
    assert "/api/db/query" in http_server.HTTP_MODE_GAMING_READ_POST_PATHS

    enclosing_tries = [
        node for node in ast.walk(do_post)
        if isinstance(node, ast.Try) and node.lineno < dispatch_line < node.end_lineno
    ]
    assert enclosing_tries
    assert any(
        isinstance(catch.type, ast.Name) and catch.type.id == "Exception"
        for node in enclosing_tries for catch in node.handlers
    )
