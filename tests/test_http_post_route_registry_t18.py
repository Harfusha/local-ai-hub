from __future__ import annotations

import json
from pathlib import Path

import pytest

from local_ai_hub.http_route_registry import POST_ROUTE_HANDLER_BOUNDARIES, POST_ROUTE_REGISTRY, select_http_routes, select_post_handler


_FIXTURE = Path(__file__).parent / "fixtures" / "http_post_route_inventory_t18.json"
_INVENTORY = json.loads(_FIXTURE.read_text(encoding="utf-8"))
_CROSSWALK_FIXTURE = Path(__file__).parent / "fixtures" / "http_post_api_coverage_route_crosswalk_t18.json"
_CROSSWALK = json.loads(_CROSSWALK_FIXTURE.read_text(encoding="utf-8"))
_RETIRED_ROUTE_IDS = {"post_control_1", "post_command_1", "post_command_preflight_1", "post_command_speculative_lint_1", "post_command_daemon_1", "post_command_lint_fix_1", "post_command_http_probe_1", "post_command_mock_server_1", "post_command_diff_hunk_stage_1", "post_command_flaky_detect_1", "post_command_webhook_replay_1"}
# Frozen, reviewed public-contract deltas from the immutable historical preimage.
_CURRENT_ROUTE_PATHS = {
 'post_leases_claim_1': ['/api/leases/claim_batch'],
 'post_repo_state_1': ['/api/repo/state'],
 'post_hotspots_1': ['/api/repo/hotspots'],
 'post_generate_tests_for_diff_1': ['/api/repo/generate_tests_for_diff'],
 'post_cross_repo_contract_1': ['/api/repo/cross_repo_contract'],
 'post_affected_tests_1': ['/api/repo/affected_tests'],
 'post_repo_topology_1': ['/api/repo/topology'],
 'post_ast_rename_1': ['/api/code/ast_rename'],
 'post_code_generate_mocks_1': ['/api/code/generate_mocks'],
 'post_code_batch_replace_1': ['/api/code/batch_replace'],
 'post_dead_code_1': ['/api/repo/dead_code'],
 'post_speculative_draft_1': ['/api/task/speculative_draft'],
 'post_scaffold_1': ['/api/task/scaffold'],
 'post_reachability_dead_code_1': ['/api/repo/reachability_dead_code'],
 'post_mutation_test_1': ['/api/repo/mutation_test'],
 'post_repo_type_stubs_1': ['/api/repo/type_stubs'],
 'post_repo_skeletonize_1': ['/api/repo/skeletonize'],
 'post_repo_split_changes_1': ['/api/repo/split_changes'],
 'post_repo_synthesize_rules_1': ['/api/repo/synthesize_rules'],
 'post_rag_docset_index_1': ['/api/rag/docset/index'],
 'post_rag_docset_search_1': ['/api/rag/docset/search'],
 'post_task_transcribe_1': ['/api/task/transcribe'],
 'post_code_invariants_1': ['/api/repo/code_invariants'],
 'post_generate_dataset_1': ['/api/repo/generate_dataset'],
 'post_profile_digest_1': ['/api/repo/profile_digest'],
 'post_coord_worktree_lease_1': ['/api/coord/worktree_lease'],
 'post_coord_worktree_release_1': ['/api/coord/worktree_release'],
 'post_coord_worktrees_1': ['/api/coord/worktrees'],
 'post_coord_worktree_prune_1': ['/api/coord/worktree_prune'],
 'post_callers_1': ['/api/repo/callers'],
 'post_repo_secret_scan_1': ['/api/repo/secret_scan'],
 'post_repo_schema_inspect_1': ['/api/repo/schema_inspect'],
 'post_explain_query_1': ['/api/repo/explain_query'],
 'post_env_compat_1': ['/api/repo/env_compat'],
 'post_coord_pubsub_publish_1': ['/api/coord/pubsub_publish'],
 'post_coord_pubsub_poll_1': ['/api/coord/pubsub_poll'],
 'post_coord_simulate_merge_1': ['/api/coord/simulate_merge'],
 'post_eval_suite_1': ['/api/task/eval_suite'],
 'post_prompt_eval_1': ['/api/task/prompt_eval'],
 'post_eval_drift_1': ['/api/task/eval_drift'],
 'post_circular_dependencies_1': ['/api/repo/circular_dependencies'],
 'post_generate_types_1': ['/api/repo/generate_types'],
 'post_complexity_1': ['/api/repo/complexity'],
 'post_api_spec_1': ['/api/repo/api_spec'],
 'post_dependency_slice_1': ['/api/repo/dependency_slice'],
 'post_migration_drift_1': ['/api/repo/migration_drift'],
 'post_package_audit_1': ['/api/repo/package_audit'],
 'post_repo_structural_search_1': ['/api/repo/structural_search'],
 'post_context_budget_1': ['/api/repo/context_budget'],
 'post_ingest_document_1': ['/api/rag/ingest_document'],
 'post_ingest_diagram_1': ['/api/rag/ingest_diagram'],
}
_CURRENT_ADDED_ROUTES = {'post_task_browser_1': {'paths': ['/api/task/browser'], 'before': 'post_repo_split_changes_1'},
 'post_task_automation_1': {'paths': ['/api/task/automation'], 'before': 'post_repo_split_changes_1'},
 'post_callees_1': {'paths': ['/api/code/callees'], 'before': 'post_repo_secret_scan_1'},
 'post_implementations_1': {'paths': ['/api/code/implementations'], 'before': 'post_repo_secret_scan_1'},
 'post_declaration_1': {'paths': ['/api/code/declaration'], 'before': 'post_repo_secret_scan_1'},
 'post_context_pack_1': {'paths': ['/api/context/pack'], 'before': 'post_ingest_document_1'},
 'post_coord_session_briefing_1': {'paths': ['/api/coord/session_briefing'], 'before': 'post_eval_suite_1'},
 'post_coord_milestone_status_1': {'paths': ['/api/coord/milestone_status'], 'before': 'post_coord_session_briefing_1'},
 'post_coord_milestone_create_1': {'paths': ['/api/coord/milestone_create'], 'before': 'post_coord_milestone_status_1'},
 'post_coord_board_summary_1': {'paths': ['/api/coord/board_summary'], 'before': 'post_coord_milestone_create_1'},
 'post_coord_board_item_list_1': {'paths': ['/api/coord/board_item_list'], 'before': 'post_coord_board_summary_1'},
 'post_coord_board_item_delete_1': {'paths': ['/api/coord/board_item_delete'], 'before': 'post_coord_board_item_list_1'},
 'post_coord_board_item_get_1': {'paths': ['/api/coord/board_item_get'], 'before': 'post_coord_board_item_delete_1'},
 'post_coord_board_item_update_1': {'paths': ['/api/coord/board_item_update'], 'before': 'post_coord_board_item_get_1'},
 'post_coord_board_item_create_1': {'paths': ['/api/coord/board_item_create'], 'before': 'post_coord_board_item_update_1'},
 'post_coord_semaphore_status_1': {'paths': ['/api/coord/semaphore_status'], 'before': 'post_coord_board_item_create_1'},
 'post_coord_semaphore_release_1': {'paths': ['/api/coord/semaphore_release'], 'before': 'post_coord_semaphore_status_1'},
 'post_coord_semaphore_acquire_1': {'paths': ['/api/coord/semaphore_acquire'], 'before': 'post_coord_semaphore_release_1'},
 'post_coord_wait_for_event_1': {'paths': ['/api/coord/wait_for_event'], 'before': 'post_coord_semaphore_acquire_1'},
 'post_coord_plan_init_1': {'paths': ['/api/coord/plan_init'], 'before': 'post_benchmark_run_1'},
 'post_coord_plan_list_1': {'paths': ['/api/coord/plan_list'], 'before': 'post_benchmark_run_1'},
 'post_coord_plan_get_1': {'paths': ['/api/coord/plan_get'], 'before': 'post_benchmark_run_1'},
 'post_coord_plan_create_1': {'paths': ['/api/coord/plan_create'], 'before': 'post_benchmark_run_1'},
 'post_coord_plan_update_1': {'paths': ['/api/coord/plan_update'], 'before': 'post_benchmark_run_1'},
 'post_coord_plan_task_edit_1': {'paths': ['/api/coord/plan_task_edit'], 'before': 'post_benchmark_run_1'},
 'post_coord_plan_task_delete_1': {'paths': ['/api/coord/plan_task_delete'], 'before': 'post_benchmark_run_1'},
 'post_coord_plan_validate_1': {'paths': ['/api/coord/plan_validate'], 'before': 'post_benchmark_run_1'},
 'post_coord_plan_archive_1': {'paths': ['/api/coord/plan_archive'], 'before': 'post_benchmark_run_1'},
 'post_coord_plan_board_view_1': {'paths': ['/api/coord/plan_board_view'], 'before': 'post_benchmark_run_1'},
 'post_coord_plan_adopt_legacy_board_1': {'paths': ['/api/coord/plan_adopt_legacy_board'], 'before': 'post_benchmark_run_1'},
 'post_coord_plan_bind_task_1': {'paths': ['/api/coord/plan_bind_task'], 'before': 'post_benchmark_run_1'},
 'post_coord_plan_reconcile_steering_1': {'paths': ['/api/coord/plan_reconcile_steering'], 'before': 'post_benchmark_run_1'},
 'post_repo_patch_1': {'paths': ['/api/repo/patch'], 'before': 'post_implementations_1'},
 'post_repo_call_graph_1': {'paths': ['/api/repo/call_graph'], 'before': 'post_implementations_1'},
 'post_repo_git_status_1': {'paths': ['/api/repo/git_status'], 'before': 'post_implementations_1'},
 'post_repo_revert_1': {'paths': ['/api/repo/revert'], 'before': 'post_implementations_1'},
 'post_repo_find_files_1': {'paths': ['/api/repo/find_files'], 'before': 'post_implementations_1'},
 'post_repo_file_info_1': {'paths': ['/api/repo/file_info'], 'before': 'post_implementations_1'},
 'post_telemetry_endpoint_stats_reset_1': {'paths': ['/api/telemetry/endpoint-stats/reset'], 'before': 'post_work_orders_1'}}
_ADDED_ROUTE_IDS = set(_CURRENT_ADDED_ROUTES)


def _rules_as_rows(registry):
    return [
        {"route_id": rule.route_id, "paths": sorted(rule.paths)}
        for rule in registry
    ]


def _expected_current_routes():
    rows = [
        {"route_id": row["route_id"], "paths": sorted(_CURRENT_ROUTE_PATHS.get(row["route_id"], row["paths"]))}
        for row in _INVENTORY["post_route_rules"]
        if row["route_id"] not in _RETIRED_ROUTE_IDS
    ]
    for route_id, addition in _CURRENT_ADDED_ROUTES.items():
        position = next((i for i, row in enumerate(rows) if row["route_id"] == addition["before"]), len(rows))
        rows.insert(position, {"route_id": route_id, "paths": addition["paths"]})
    return rows


def test_post_registry_matches_root_preimage_route_inventory_in_order() -> None:
    expected = _expected_current_routes()
    assert _rules_as_rows(POST_ROUTE_REGISTRY) == expected
    current_matches: dict[str, list[str]] = {}
    for row in expected:
        for path in row["paths"]:
            current_matches.setdefault(path, []).append(row["route_id"])
    for path, route_ids in current_matches.items():
        assert select_http_routes("POST", path) == tuple(route_ids)
    historical_paths = {path for row in _INVENTORY["post_route_rules"] for path in row["paths"]}
    for retired_path in historical_paths - set(current_matches):
        assert select_http_routes("POST", retired_path) == ()


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
        and any(isinstance(value, ast.Constant) and isinstance(value.value, str)
                and value.value.startswith("post_") for value in ast.walk(node.test))
    ]
    selected_ids = [
        next(
            item.value
            for item in ast.walk(node.test)
            if isinstance(item, ast.Constant) and isinstance(item.value, str) and item.value.startswith("post_")
        )
        for node in branches
    ]
    expected_orders = [[row["route_id"] for row in _expected_current_routes()]]
    early_routes = {"post_admin_mode_1", "post_bundle_import_1"}
    named_boundaries = set(POST_ROUTE_HANDLER_BOUNDARIES)
    known_ids = set(expected_orders[0])
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
    body_lines = [line for line, name in calls if name == "_read_json"]
    trace_lines = [line for line, name in calls if name == "_begin_trace"]
    request_id_lines = [line for line, name in calls if name == "validate_request_id"]
    route_select_line = min(selector_lines)
    handler_select_lines = [line for line, name in calls if name == "select_post_handler"]
    dispatch_lines = [node.lineno for node in branches]
    assert len(selector_lines) == 1
    assert len(handler_select_lines) == 1
    assert body_lines
    assert trace_lines
    assert request_id_lines
    assert dispatch_lines
    startup_line = next(
        node.lineno
        for node in do_post.body
        if isinstance(node, ast.If) and "APP is None" in (ast.get_source_segment(source, node.test) or "")
    )
    assert route_select_line < startup_line < auth_line < min(mode_lines) < min(trace_lines)
    assert min(trace_lines) < min(request_id_lines) < min(body_lines)
    payload_mode_lines = [
        node.lineno for node in ast.walk(do_post)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id == "_http_mode_gate_error" and len(node.args) == 3
    ]
    validation_lines = [line for line, name in calls if name == "_validate_payload"]
    recovery_lines = [line for line, name in calls if name == "_claim_recovery"]
    assert len(payload_mode_lines) == 1
    assert max(body_lines) < min(validation_lines) < payload_mode_lines[0]
    assert payload_mode_lines[0] < max(recovery_lines) < min(handler_select_lines)
    assert route_select_line < min(handler_select_lines) < min(dispatch_lines)

    bundle_branch = next(
        node for node in do_post.body if isinstance(node, ast.If)
        and ast.unparse(node.test) == "path == '/api/bundle/import'"
    )
    bundle_calls = {
        node.func.id if isinstance(node.func, ast.Name) else node.func.attr: node.lineno
        for node in ast.walk(bundle_branch)
        if isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute))
    }
    assert bundle_calls["_http_mode_gate_error"] < bundle_calls["_read_body"]
    assert bundle_calls["_read_body"] < bundle_calls["_claim_recovery"] < bundle_calls["import_bundle"]


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


def test_context_pack_current_route_stays_outside_preimage_coverage() -> None:
    assert select_http_routes("POST", "/api/context/pack") == ("post_context_pack_1",)
    source_path = Path(__file__).parents[1] / "src" / "local_ai_hub" / "http_server.py"
    source = source_path.read_text(encoding="utf-8")
    assert 'if path == "/api/context/pack":' in source
    assert "post_context_pack_1" in {rule.route_id for rule in POST_ROUTE_REGISTRY}
    assert _CROSSWALK["excluded_post_paths"] == ["/api/context/pack"]
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
    ("status", None, ("status", "job-1")),
    ("WAIT", "2.5", ("wait", "job-1", 2.5)),
    ("result", None, ("result", "job-1")),
    ("cancel", None, ("cancel", "job-1")),
])
def test_async_named_handler_dispatches_action_without_tenant_identity(monkeypatch, action, timeout, expected):
    from types import SimpleNamespace
    from local_ai_hub import http_server

    assert select_post_handler(select_http_routes("POST", "/api/async-jobs")) == "_handle_post_async_jobs"
    jobs = SimpleNamespace(**{
        name: (lambda *args, name=name: {"success": True, "observed": (name, *args)})
        for name in ("status", "wait", "result", "cancel")
    })
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(async_jobs=jobs))
    handler = http_server.Handler.__new__(http_server.Handler)
    responses = []
    handler._send = lambda status, payload: responses.append((status, payload))
    payload = {"action": action, "job_id": "job-1"}
    if timeout is not None:
        payload["timeout_seconds"] = timeout
    handler._handle_post_async_jobs(payload)
    assert responses == [(200, {"success": True, "observed": expected})]


def test_async_named_submit_preserves_explicit_request_id_and_conversation_rejection(monkeypatch):
    from types import SimpleNamespace
    from local_ai_hub import http_server

    assert select_post_handler(select_http_routes("POST", "/api/async-jobs")) == "_handle_post_async_jobs"
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(async_jobs=SimpleNamespace(
        submit=lambda action, payload: {"success": True, "action": action, "payload": payload},
    )))
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.headers = {"X-LocalAI-Request-ID": "header-id"}
    responses = []
    handler._send = lambda status, payload: responses.append((status, payload))
    original = {"action": "submit", "job_action": "reason", "request_id": "explicit-id"}
    handler._handle_post_async_jobs(original)
    assert responses[-1] == (200, {"success": True, "action": "reason", "payload": original})
    assert original["request_id"] == "explicit-id"
    handler._handle_post_async_jobs({"action": "submit"})
    assert responses[-1][1]["payload"]["request_id"] == "header-id"
    handler._handle_post_async_jobs({"action": "submit", "conversation": True})
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
    handler._handle_post_work_orders({"action": "get", "work_id": " work-1 ", "response_profile": "compact", "return_fields": ["summary"], "max_output_tokens": "512"})
    assert responses[-1] == (200, {"success": True, "args": ("work-1",), "options": {
        "profile": "compact", "return_fields": ["summary"], "max_output_tokens": 512,
    }})
    work.enabled = False
    handler._handle_post_work_orders({"action": "submit"})
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
    handler._handle_post_work_orders(payload)
    assert responses == [(200, {"success": True, "observed": tail})]


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
    getattr(handler, name)({"action": "unknown"})
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
