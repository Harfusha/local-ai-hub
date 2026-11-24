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
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(
        config={"telemetry": {"mode": "full"}},
        realtime_status=lambda **kwargs: snapshots.append(kwargs) or result,
    ))
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
    from local_ai_hub import http_api_get
    source = Path(http_api_get.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    do_get = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "do_GET")
    calls = [
        (node.lineno, node.func.id if isinstance(node.func, ast.Name) else node.func.attr)
        for node in ast.walk(do_get)
        if isinstance(node, ast.Call) and (isinstance(node.func, ast.Name) or isinstance(node.func, ast.Attribute))
    ]
    ordered_calls = sorted(calls)
    auth = min(line for line, name in ordered_calls if name == "_require_authorized")
    mode = min(line for line, name in ordered_calls if name == "_http_mode_gate_error")
    trace = min(line for line, name in ordered_calls if name == "_begin_trace")
    parses = sorted(line for line, name in ordered_calls if name == "parse_qs")
    dispatch = min(line for line, name in ordered_calls if name == "select_get_handler")
    route_query_parse = min(line for line in parses if trace < line < dispatch)
    retired_query_validation = min(
        line for line, name in ordered_calls if name == "_reject_identity_fields"
    )
    assert retired_query_validation == parses[0]
    assert parses[0] < auth < mode < trace < route_query_parse < dispatch
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


def test_agent_state_summary_uses_exact_count_apis() -> None:
    from local_ai_hub.agent_tasks import TaskStatus
    from local_ai_hub.app import LocalAIApp

    task_count_calls = []

    def count_tasks(status=None, *, include_stale=True):
        task_count_calls.append((status, include_stale))
        return 137 if status is None else 3

    fake = SimpleNamespace(
        agent_state=SimpleNamespace(enabled=True),
        agent_tasks=SimpleNamespace(
            count=count_tasks,
            list_tasks=lambda **_kwargs: pytest.fail("status must not load task records"),
        ),
        agent_incidents=SimpleNamespace(
            summary_count=lambda: 211,
            list_incidents=lambda **_kwargs: pytest.fail("status must not load incident records"),
        ),
        agent_learning=SimpleNamespace(
            candidate_count=lambda: 307,
            list_candidates=lambda **_kwargs: pytest.fail("status must not load candidates"),
        ),
        agent_memory=SimpleNamespace(count=lambda: 401),
        config={"agent_state": {"retention_days": 30}},
    )

    summary = LocalAIApp._agent_state_summary(fake)

    assert summary["tasks_count"] == 137
    assert summary["active_tasks_count"] == 3
    assert summary["incidents_count"] == 211
    assert summary["candidates_count"] == 307
    assert summary["memory_records_count"] == 401
    assert task_count_calls == [(TaskStatus.ACTIVE, False), (None, False)]
