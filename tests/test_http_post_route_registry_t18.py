from __future__ import annotations

import json
from pathlib import Path

import pytest

from local_ai_hub.http_route_registry import POST_ROUTE_HANDLER_BOUNDARIES, POST_ROUTE_REGISTRY, select_http_routes, select_post_handler


_FIXTURE = Path(__file__).parent / "fixtures" / "http_post_route_inventory_t18.json"
_INVENTORY = json.loads(_FIXTURE.read_text(encoding="utf-8"))
_CROSSWALK_FIXTURE = Path(__file__).parent / "fixtures" / "http_post_api_coverage_route_crosswalk_t18.json"
_CROSSWALK = json.loads(_CROSSWALK_FIXTURE.read_text(encoding="utf-8"))
_RETIRED_ROUTE_IDS = {"post_control_1"}
_ADDED_ROUTE_IDS = {"post_task_browser_1"}


def _rules_as_rows(registry):
    return [
        {"route_id": rule.route_id, "paths": sorted(rule.paths)}
        for rule in registry
    ]


def test_post_registry_matches_root_preimage_route_inventory_in_order() -> None:
    expected = [
        {"route_id": row["route_id"], "paths": sorted(row["paths"])}
        for row in _INVENTORY["post_route_rules"]
        if row["route_id"] not in _RETIRED_ROUTE_IDS
    ]
    assert _rules_as_rows(tuple(rule for rule in POST_ROUTE_REGISTRY if rule.route_id not in _ADDED_ROUTE_IDS)) == expected


def test_candidate_and_root_preimages_have_route_path_and_priority_parity() -> None:
    root_rules = _INVENTORY["post_route_rules"]
    candidate_rules = _INVENTORY["candidate_post_route_rules"]
    root_matches: dict[str, list[str]] = {}
    candidate_matches: dict[str, list[str]] = {}
    for rule in root_rules:
        for path in rule["paths"]:
            root_matches.setdefault(path, []).append(rule["route_id"])
    for rule in candidate_rules:
        for path in rule["paths"]:
            candidate_matches.setdefault(path, []).append(rule["route_id"])
    assert candidate_matches == root_matches
    for path, expected in root_matches.items():
        if path == "/api/control":
            continue  # Retained only in the immutable T18 preimage fixture.
        assert select_http_routes("POST", path) == tuple(expected)


def test_registry_is_post_only_and_miss_preserves_existing_catch_all() -> None:
    assert select_http_routes("GET", "/api/status") == ()
    assert select_http_routes("OPTIONS", "/api/browser/capture") == ()
    assert select_http_routes("POST", "/api/unregistered-route") == ()
    assert select_http_routes("POST", "/api/status?verbose=1") == ()
    assert select_http_routes("POST", "/api/control") == ()


def test_bundle_import_and_duplicate_embed_selection_keep_preimage_order() -> None:
    import_route = next(row["route_id"] for row in _INVENTORY["post_route_rules"] if "/api/bundle/import" in row["paths"])
    assert select_http_routes("POST", "/api/bundle/import") == (import_route,)
    assert select_http_routes("POST", "/api/embed") == tuple(_INVENTORY["expected_duplicate_paths"]["/api/embed"])


def test_do_post_registered_dispatch_branches_match_inventory_without_moving_gates() -> None:
    import ast

    source_path = Path(__file__).parents[1] / "src" / "local_ai_hub" / "http_server.py"
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    handler = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Handler")
    do_post = next(node for node in handler.body if isinstance(node, ast.FunctionDef) and node.name == "do_POST")
    dispatch = max((node for node in do_post.body if isinstance(node, ast.Try)), key=lambda node: len(node.body))
    branches = [
        node
        for node in do_post.body + dispatch.body
        if isinstance(node, ast.If)
        and any(isinstance(name, ast.Name) and name.id == "post_route_ids" for name in ast.walk(node.test))
    ]
    selected_ids = [
        next(
            item.value
            for item in ast.walk(node.test)
            if isinstance(item, ast.Constant) and isinstance(item.value, str) and item.value.startswith("post_")
        )
        for node in branches
    ]
    expected_orders = [
        [row["route_id"] for row in _INVENTORY["post_route_rules"]],
        [row["route_id"] for row in _INVENTORY["candidate_post_route_rules"]],
    ]
    early_routes = {"post_admin_mode_1", "post_bundle_import_1"}
    named_boundaries = set(POST_ROUTE_HANDLER_BOUNDARIES)
    known_ids = set(expected_orders[0]) | set(expected_orders[1]) | _ADDED_ROUTE_IDS
    assert selected_ids
    assert len(selected_ids) == len(set(selected_ids))
    assert set(selected_ids) <= known_ids
    assert not (named_boundaries & set(selected_ids))
    assert all(select_post_handler((route_id,)) is None for route_id in early_routes)
    inventory_order = {route_id: index for index, route_id in enumerate(expected_orders[0])}
    selected_order = [inventory_order[route_id] for route_id in selected_ids if route_id not in _ADDED_ROUTE_IDS]
    assert selected_order == sorted(selected_order)

    calls = [
        (node.lineno, node.func.id if isinstance(node.func, ast.Name) else node.func.attr)
        for node in ast.walk(do_post)
        if isinstance(node, ast.Call)
        and (isinstance(node.func, ast.Name) or isinstance(node.func, ast.Attribute))
    ]
    auth_line = next(line for line, name in calls if name == "_require_authorized")
    selector_lines = [line for line, name in calls if name == "select_http_routes"]
    mode_lines = [line for line, name in calls if name == "_http_mode_gate_error"]
    main_selector_line = min(
        node.lineno
        for node in dispatch.body
        if isinstance(node, ast.If) and "post_route_ids" in (ast.get_source_segment(source, node.test) or "")
    )
    recovery_lines = [line for line, name in calls if name in {"begin", "_claim_recovery"} and line < main_selector_line]
    assert len(selector_lines) == 1
    assert recovery_lines
    assert auth_line < min(mode_lines) < min(recovery_lines) < selector_lines[0]


def test_root_api_coverage_route_crosswalk_is_row_exact() -> None:
    rows = _CROSSWALK["rows"]
    assert _CROSSWALK["root_api_coverage_sha256"] == "66b5c89fe088021e5d32feebd1bf953edffad729ec16a55e2b814dc9dacc40f0"
    assert _CROSSWALK["root_post_rows"] == 223
    assert _CROSSWALK["candidate_post_rows"] == 222
    assert _CROSSWALK["candidate_missing_root_paths"] == ["/api/admin/mode"]
    assert len(rows) == 223
    assert len({row["operation_id"] for row in rows}) == 223

    root_matches: dict[str, list[str]] = {}
    candidate_matches: dict[str, list[str]] = {}
    for rule in _INVENTORY["post_route_rules"]:
        for path in rule["paths"]:
            root_matches.setdefault(path, []).append(rule["route_id"])
    for rule in _INVENTORY["candidate_post_route_rules"]:
        for path in rule["paths"]:
            candidate_matches.setdefault(path, []).append(rule["route_id"])

    for row in rows:
        path = row["path"]
        assert row["method"] == "POST"
        assert row["root_route_ids"] == root_matches[path]
        assert row["candidate_route_ids"] == candidate_matches[path]
        assert row["owner_evidence"] == "unassigned"
        assert row["source_handler"] == "do_POST"
    assert [row["path"] for row in rows if len(row["root_route_ids"]) > 1] == ["/api/embed"]


def test_agent2_context_pack_stays_outside_t18_registry() -> None:
    assert select_http_routes("POST", "/api/context/pack") == ()
    source_path = Path(__file__).parents[1] / "src" / "local_ai_hub" / "http_server.py"
    source = source_path.read_text(encoding="utf-8")
    assert 'if path == "/api/context/pack":' in source
    assert "post_context_pack_1" not in source
    assert "/api/context/pack" not in [row["path"] for row in _CROSSWALK["rows"]]


def test_telemetry_timeline_selects_named_handler_boundary() -> None:
    route_ids = select_http_routes("POST", "/api/telemetry/timeline")
    assert route_ids == ("post_telemetry_timeline_1",)
    assert select_post_handler(route_ids) == "_handle_post_telemetry_timeline"
    assert select_post_handler(("unmigrated_route",)) is None


@pytest.mark.parametrize("path, expected", [
    ("/api/async-jobs", "_handle_post_async_jobs"),
    ("/api/work-orders", "_handle_post_work_orders"),
])
def test_job_routes_select_scoped_named_handler(path, expected) -> None:
    assert select_post_handler(select_http_routes("POST", path)) == expected


@pytest.mark.parametrize("action, timeout, expected", [
    ("status", None, ("status", "tenant-a", " job-1 ")),
    ("WAIT", "2.5", ("wait", "tenant-a", " job-1 ", 2.5)),
    ("result", None, ("result", "tenant-a", " job-1 ")),
    ("cancel", None, ("cancel", "tenant-a", " job-1 ")),
])
def test_async_named_handler_preserves_bound_tenant_and_action(monkeypatch, action, timeout, expected):
    from types import SimpleNamespace
    from local_ai_hub import http_server

    assert select_post_handler(select_http_routes("POST", "/api/async-jobs")) == "_handle_post_async_jobs"
    jobs = SimpleNamespace(**{
        name: (lambda *args, name=name: {"success": True, "observed": (name, *args)})
        for name in ("status", "wait", "result", "cancel")
    })
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(async_jobs=jobs))
    handler = http_server.Handler.__new__(http_server.Handler)
    handler._authorization_tenant = "different-late-tenant"
    responses = []
    handler._send = lambda status, payload: responses.append((status, payload))
    payload = {"action": action, "job_id": " job-1 "}
    if timeout is not None:
        payload["timeout_seconds"] = timeout
    handler._handle_post_async_jobs(payload, tenant="tenant-a")
    assert responses == [(200, {"success": True, "observed": expected})]


def test_async_named_submit_preserves_explicit_request_id_and_conversation_rejection(monkeypatch):
    from types import SimpleNamespace
    from local_ai_hub import http_server

    assert select_post_handler(select_http_routes("POST", "/api/async-jobs")) == "_handle_post_async_jobs"
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(async_jobs=SimpleNamespace(
        submit=lambda tenant, action, payload: {"success": True, "tenant": tenant, "action": action, "payload": payload},
    )))
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.headers = {"X-LocalAI-Request-ID": "header-id"}
    responses = []
    handler._send = lambda status, payload: responses.append((status, payload))
    original = {"action": "submit", "job_action": "reason", "request_id": "explicit-id"}
    handler._handle_post_async_jobs(original, tenant="tenant-a")
    assert responses[-1] == (200, {"success": True, "tenant": "tenant-a", "action": "reason", "payload": original})
    assert original["request_id"] == "explicit-id"
    handler._handle_post_async_jobs({"action": "submit"}, tenant="tenant-a")
    assert responses[-1][1]["payload"]["request_id"] == "header-id"
    handler._handle_post_async_jobs({"action": "submit", "conversation": True}, tenant="tenant-a")
    assert responses[-1] == (400, {
        "success": False, "error": "conversations require delivery=sync", "terminal": True, "retryable": False,
    })


def test_work_order_named_handler_preserves_scoped_get_and_disabled_result(monkeypatch):
    from types import SimpleNamespace
    from local_ai_hub import http_server

    assert select_post_handler(select_http_routes("POST", "/api/work-orders")) == "_handle_post_work_orders"
    work = SimpleNamespace(enabled=True, get=lambda *args, **kwargs: {"success": True, "args": args, "options": kwargs})
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(work_orchestrator=work))
    handler = http_server.Handler.__new__(http_server.Handler)
    responses = []
    handler._send = lambda status, payload: responses.append((status, payload))
    handler._handle_post_work_orders({"action": "get", "work_id": " work-1 ", "response_profile": "compact", "return_fields": ["summary"], "max_output_tokens": "512"}, tenant="tenant-a")
    assert responses[-1] == (200, {"success": True, "args": ("tenant-a", "work-1"), "options": {
        "profile": "compact", "return_fields": ["summary"], "max_output_tokens": 512,
    }})
    work.enabled = False
    handler._handle_post_work_orders({"action": "submit"}, tenant="tenant-a")
    assert responses[-1] == (403, {"success": False, "unsupported": True, "error": "work orchestrator is disabled", "terminal": True})


@pytest.mark.parametrize("payload, method, tail", [
    ({}, "submit", ({},)),
    ({"action": "status", "work_id": " work-1 "}, "status", ("work-1",)),
    ({"action": "WAIT", "work_id": "work-1", "timeout_seconds": "2.5"}, "wait", ("work-1", 2.5)),
    ({"action": "cancel", "work_id": "work-1"}, "cancel", ("work-1",)),
    ({"action": "continue", "work_id": "work-1", "answer": "yes"}, "continue_work", ("work-1", "yes")),
])
def test_work_order_named_actions_keep_arguments(monkeypatch, payload, method, tail):
    from types import SimpleNamespace
    from local_ai_hub import http_server

    work = SimpleNamespace(enabled=True)
    setattr(work, method, lambda *args: {"success": True, "observed": args})
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(work_orchestrator=work))
    handler = http_server.Handler.__new__(http_server.Handler)
    responses = []
    handler._send = lambda status, value: responses.append((status, value))
    handler._handle_post_work_orders(payload, tenant="tenant-a")
    assert responses == [(200, {"success": True, "observed": ("tenant-a", *tail)})]


@pytest.mark.parametrize("name, message, retryable", [
    ("_handle_post_async_jobs", "unknown async job action", False),
    ("_handle_post_work_orders", "unknown work-order action", None),
])
def test_named_job_handlers_keep_unknown_action_error(monkeypatch, name, message, retryable):
    from types import SimpleNamespace
    from local_ai_hub import http_server

    monkeypatch.setattr(http_server, "APP", SimpleNamespace(work_orchestrator=SimpleNamespace(enabled=True)))
    handler = http_server.Handler.__new__(http_server.Handler)
    responses = []
    handler._send = lambda status, payload: responses.append((status, payload))
    getattr(handler, name)({"action": "unknown"}, tenant="tenant-a")
    expected = {"success": False, "error": message, "terminal": True}
    if retryable is not None:
        expected["retryable"] = retryable
    assert responses == [(400, expected)]


def test_telemetry_timeline_handler_preserves_success_and_error_contract(monkeypatch) -> None:
    from types import SimpleNamespace

    from local_ai_hub import http_server

    calls = []
    page = {"events": [{"event_id": "evt-1"}], "next_before_id": "evt-1"}

    def get_timeline_page(limit, *, before_id):
        calls.append((limit, before_id))
        return page

    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(telemetry=SimpleNamespace(get_timeline_page=get_timeline_page)),
    )
    handler = http_server.Handler.__new__(http_server.Handler)
    responses = []
    handler._send = lambda status, payload: responses.append((status, payload))

    handler._handle_post_telemetry_timeline({"limit": "25", "before_id": "evt-8"})
    assert calls == [("25", "evt-8")]
    assert responses == [(200, {"success": True, **page})]

    def fail_timeline_page(_limit, *, before_id):
        raise RuntimeError(f"timeline read failed before={before_id}")

    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(
            telemetry=SimpleNamespace(get_timeline_page=fail_timeline_page),
            logger=SimpleNamespace(warning=lambda *_args, **_kwargs: None),
        ),
    )
    handler._handle_post_telemetry_timeline({"limit": 25, "before_id": "evt-9"})
    assert responses[-1] == (
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
    assert "evt-9" not in repr(responses[-1][1])


def test_named_telemetry_dispatch_stays_after_recovery_and_inside_error_boundary() -> None:
    import ast

    source_path = Path(__file__).parents[1] / "src" / "local_ai_hub" / "http_server.py"
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    handler = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Handler")
    do_post = next(node for node in handler.body if isinstance(node, ast.FunctionDef) and node.name == "do_POST")
    named_dispatch = next(
        node for node in ast.walk(do_post)
        if isinstance(node, ast.Try)
        and any(isinstance(exc.type, ast.Name) and exc.type.id == "Exception" for exc in node.handlers)
        and any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "select_post_handler"
            for call in ast.walk(node)
        )
    )
    dispatch_line = min(
        call.lineno for call in ast.walk(named_dispatch)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "select_post_handler"
    )
    recovery_begin_line = min(
        call.lineno for call in ast.walk(do_post)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "_claim_recovery"
    )
    mode_gate_line = min(
        call.lineno for call in ast.walk(do_post)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "_http_mode_gate_error"
    )
    assert mode_gate_line < recovery_begin_line < dispatch_line
