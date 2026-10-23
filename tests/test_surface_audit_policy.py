from pathlib import Path

import pytest

from local_ai_hub.agent_surface import (
    diagnostic_http_operation,
    diagnostic_mcp_operation,
    diagnostics_disabled_response,
)


@pytest.mark.parametrize("tool,arguments", [
    ("local_ai_task", {"action": "benchmark"}),
    ("local_ai_task", {"action": "evaluation_report"}),
    ("local_ai_task", {"action": "candidate_promote"}),
    ("local_ai_task", {"action": "submit", "job_action": "eval_suite"}),
    ("local_ai_task", {"action": "batch", "tasks": [{"action": "hardware_benchmark"}]}),
    ("local_ai_repo", {"action": "route"}),
    ("local_ai_repo", {"action": "pipeline", "steps": [{"action": "route"}]}),
    ("local_ai_coord", {"action": "curate_dataset"}),
    ("local_ai_coord", {"action": "context_compile", "include_diagnostics": True}),
    ("local_ai_repo", {"action": "context", "include_diagnostics": True}),
])
def test_operator_diagnostics_are_identified_before_execution(tool, arguments):
    assert diagnostic_mcp_operation(tool, arguments)


@pytest.mark.parametrize("tool,arguments", [
    ("local_ai_repo", {"action": "diagnose"}),
    ("local_ai_repo", {"action": "code_index"}),
    ("local_ai_task", {"action": "review"}),
    ("local_ai_task", {"action": "cancel", "job_id": 1}),
    ("local_ai_coord", {"action": "task_create", "contract": {"action": "benchmark"}}),
    ("local_ai_coord", {"action": "memory_record", "value": {"action": "benchmark"}}),
])
def test_work_and_control_are_not_mistaken_for_internal_diagnostics(tool, arguments):
    assert not diagnostic_mcp_operation(tool, arguments)


@pytest.mark.parametrize("method,path,payload", [
    ("GET", "/api/doctor", {}),
    ("POST", "/api/doctor", {}),
    ("GET", "/api/hardware/system", {}),
    ("GET", "/api/db/query", {}),
    ("POST", "/api/evaluation", {}),
    ("POST", "/api/async-jobs", {"action": "submit", "job_action": "benchmark"}),
    ("POST", "/api/agent-state/tasks", {"action": "curate_dataset"}),
    ("POST", "/api/agent-state/context", {"include_diagnostics": True}),
    ("POST", "/api/context/pack", {"include_diagnostics": True}),
])
def test_alternate_http_entry_points_cannot_bypass_diagnostic_policy(method, path, payload):
    assert diagnostic_http_operation(method, path, payload)


def test_code_diagnostics_and_aggregate_dashboard_metrics_remain_working_surfaces():
    assert not diagnostic_http_operation("POST", "/api/code/diagnostics", {})
    assert not diagnostic_http_operation("GET", "/api/metrics", {})
    assert not diagnostic_http_operation("GET", "/api/telemetry/report", {})
    assert not diagnostic_http_operation("POST", "/api/async-jobs", {"action": "cancel"})


def test_disabled_diagnostics_error_is_actionable_and_never_invites_a_retry_loop():
    result = diagnostics_disabled_response()
    assert result["success"] is False
    assert result["status_code"] == 409
    assert result["error_code"] == "detailed_diagnostics_disabled"
    assert result["terminal"] is True
    assert result["retryable"] is False


def test_completion_verification_is_work_evidence_not_raw_model_debug():
    from local_ai_hub.agent_diagnostics import project_agent_response
    completion = {"task_id": "task-1", "passed": False, "missing_criteria": ["tests"]}
    result = project_agent_response({"success": False, "completion": completion,
        "model_debug": {"completion": "private model draft"}}, enabled=False)
    assert result == {"success": False, "completion": completion}


@pytest.mark.parametrize("location", [{"range": {"start": {"line": 0, "character": 0}}}, {"severity": 0}])
def test_lsp_diagnostics_keep_valid_location_and_zero_values(location):
    from local_ai_hub.agent_diagnostics import project_agent_response
    issue = {"message": "Unknown symbol", **location}
    assert project_agent_response({"diagnostics": [issue]}, enabled=False) == {"diagnostics": [issue]}


def test_mcp_coord_completion_keeps_actionable_proof_with_detail_off(monkeypatch, tmp_path):
    from local_ai_hub import mcp_server
    from local_ai_hub.operational_mode import OperationalModeSnapshot
    monkeypatch.setattr(mcp_server, "CFG", {"debug_traces": {"enabled": False}})
    monkeypatch.setattr(mcp_server, "load_operational_mode", lambda _: OperationalModeSnapshot("active", 0, None))
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **kwargs: None)
    completion = {"task_id": "task-1", "passed": False, "missing_criteria": ["tests"]}
    monkeypatch.setattr(mcp_server.CLIENT, "post", lambda *args, **kwargs: {
        "success": False, "error": "verification incomplete", "completion": completion,
        "debug": "internal observation"})
    result = mcp_server.local_ai_coord(action="verify_completion", root=str(tmp_path), task_id="task-1")
    assert result["success"] is False
    assert result["completion"] == completion
    assert "debug" not in result


def test_receipt_http_binding_cannot_manufacture_a_missing_repository_root(monkeypatch):
    from types import SimpleNamespace
    from local_ai_hub import http_server
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={}))
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.headers = {}
    errors = []
    handler._send = lambda status, payload: errors.append((status, payload))
    assert handler._bind_task_payload({"action": "receipt", "receipt": {"task_id": "task-1"}}) is False
    assert errors and errors[0][0] == 400
    assert "root" in errors[0][1]["error"].lower()
    assert not getattr(handler, "_authorization_root", None)


@pytest.mark.parametrize("payload", [
    {"action": " SUBMIT ", "job_action": "Hardware-Benchmark"},
    {"action": "submit", "job_action": " ROUTE "},
])
def test_http_async_diagnostic_gate_matches_existing_dispatch_normalization(payload):
    assert diagnostic_http_operation("POST", "/api/async-jobs", payload)


def test_mcp_gate_prevents_diagnostic_work_instead_of_only_hiding_its_output(monkeypatch):
    from local_ai_hub import mcp_server
    from local_ai_hub.operational_mode import OperationalModeSnapshot

    monkeypatch.setattr(mcp_server, "CFG", {"debug_traces": {"enabled": False}})
    monkeypatch.setattr(mcp_server, "load_operational_mode", lambda _: OperationalModeSnapshot("active", 0, None))
    monkeypatch.setattr(mcp_server, "_record_adoption", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **_kwargs: None)
    executed = []

    @mcp_server._instrumented_tool()
    def local_ai_task(action="benchmark"):
        executed.append(action)
        return {"success": True, "text": "must not execute"}

    result = local_ai_task(action="benchmark")
    assert result["error_code"] == "detailed_diagnostics_disabled"
    assert executed == []


@pytest.mark.parametrize("method,path,payload", [
    ("GET", "/api/doctor", {}),
    ("GET", "/api/hardware/system", {}),
    ("POST", "/api/benchmark", {}),
    ("POST", "/api/async-jobs", {"action": "submit", "job_action": "benchmark"}),
])
def test_http_gate_prevents_backend_access(monkeypatch, method, path, payload):
    from types import SimpleNamespace
    from local_ai_hub import http_server

    def forbidden(*_args, **_kwargs):
        pytest.fail("disabled operator diagnostics reached a backend")

    app = SimpleNamespace(config={}, debug_traces=SimpleNamespace(enabled=False),
                          doctor=forbidden, async_jobs=SimpleNamespace(submit=forbidden))
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *_args: None)
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path, handler.command, handler.headers = path, method, {}
    handler._require_authorized = lambda *_args: True
    handler._reject_identity_fields = lambda *_args: True
    handler._begin_trace = lambda *_args: None
    handler._read_json = lambda: payload
    handler._validate_payload = lambda *_args: None
    handler._bind_repository_root_payload = lambda *_args: True
    responses = []
    handler._send = lambda status, data, **_kwargs: responses.append((status, data))
    getattr(handler, "do_" + method)()
    assert responses == [(409, diagnostics_disabled_response())]


def test_retained_async_diagnostics_cannot_be_read_after_toggle_off(monkeypatch):
    from types import SimpleNamespace
    from local_ai_hub import http_server

    def forbidden(*_args, **_kwargs):
        pytest.fail("disabled diagnostic job result was read")

    app = SimpleNamespace(config={}, debug_traces=SimpleNamespace(enabled=False),
                          async_jobs=SimpleNamespace(diagnostic_result=lambda **_kwargs: True, result=forbidden))
    monkeypatch.setattr(http_server, "APP", app)
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.headers = {}
    responses = []
    handler._send = lambda status, data: responses.append((status, data))
    handler._handle_post_async_jobs({"action": "result", "job_id": "job-1"})
    assert responses == [(409, diagnostics_disabled_response())]


def test_async_diagnostic_classification_reads_metadata_without_result_payload(tmp_path):
    import sqlite3
    from contextlib import closing
    from local_ai_hub.async_jobs import AsyncJobManager

    db = tmp_path / "jobs.sqlite3"
    with closing(sqlite3.connect(db)) as connection:
        # Deliberately no result_json column: classification must not read it.
        connection.execute("CREATE TABLE async_jobs (job_id TEXT, artifact_id TEXT, action TEXT, payload_json TEXT)")
        connection.executemany("INSERT INTO async_jobs VALUES (?,?,?,?)", [
            ("diag", "diag-artifact", "benchmark", "{}"),
            ("work", "work-artifact", "review", "{}"),
            ("context", "context-artifact", "context", '{"include_diagnostics": true}'),
        ])
        connection.commit()
    manager = AsyncJobManager.__new__(AsyncJobManager)
    manager._connect = lambda: sqlite3.connect(db)
    assert manager.diagnostic_result(job_id="diag") is True
    assert manager.diagnostic_result(artifact_id="context-artifact") is True
    assert manager.diagnostic_result(artifact_id="work-artifact") is False
    assert manager.diagnostic_result(artifact_id="missing") is None


@pytest.mark.parametrize("kind,job_classification,blocked", [
    ("diagnostic-async-job", None, True),
    ("async-job", True, True),
    ("async-job", None, True),
    ("async-job", False, False),
    ("command_execution_record.v2", None, False),
])
def test_artifact_download_respects_diagnostic_origin(monkeypatch, kind, job_classification, blocked):
    from types import SimpleNamespace
    from local_ai_hub import http_server

    reads = []
    app = SimpleNamespace(config={}, debug_traces=SimpleNamespace(enabled=False),
        async_jobs=SimpleNamespace(diagnostic_result=lambda **_kwargs: job_classification),
        artifacts=SimpleNamespace(kind=lambda _identifier: kind,
            get=lambda identifier, **_kwargs: reads.append(identifier) or {"success": True, "text": "proof"}))
    monkeypatch.setattr(http_server, "APP", app)
    handler = http_server.Handler.__new__(http_server.Handler)
    responses = []
    handler._send = lambda status, data: responses.append((status, data))
    handler._handle_post_artifact_get({"artifact_id": "artifact-1"})
    if blocked:
        assert reads == []
        assert responses == [(409, diagnostics_disabled_response())]
    else:
        assert reads == ["artifact-1"]
        assert responses == [(200, {"success": True, "text": "proof"})]


def test_status_keeps_operational_health_but_moves_component_internals_to_detail():
    from local_ai_hub.agent_diagnostics import project_status_response

    original = {"success": False, "degraded": True, "hub_online": True,
        "scheduler": {"active_model": "model", "context_pressure": "high"},
        "debug_traces": {"enabled": False}, "hardware": {"ram": {"used_pct": 70}},
        "repo_cache": {"entries": 50}, "commands": {"executions": 200},
        "http_concurrency": {"waiting": 1}, "runtime_stats": {"switches": 3},
        "dependency_status": {"models": {"degraded": True, "error": "offline", "duration_ms": 42, "deadline_ms": 1000}}}
    projected = project_status_response(original, enabled=False)
    assert not {"repo_cache", "commands", "http_concurrency", "runtime_stats"}.intersection(projected)
    assert projected["scheduler"] == original["scheduler"]
    assert projected["degraded"] is True
    assert projected["dependency_status"] == {"models": {"degraded": True, "error": "offline"}}
    assert project_status_response(original, enabled=True) == original


def test_status_default_uses_light_producer_without_inspecting_full_runtime(monkeypatch):
    from types import SimpleNamespace
    from local_ai_hub import http_server

    calls = []
    def full(**_kwargs):
        pytest.fail("ordinary status triggered full runtime diagnostics")
    app = SimpleNamespace(config={}, debug_traces=SimpleNamespace(enabled=False), status=full,
        realtime_status=lambda **kwargs: calls.append(kwargs) or {"success": True, "hub_online": True})
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *_args: None)
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path, handler.command, handler.headers = "/api/status", "GET", {}
    handler.server = SimpleNamespace()
    handler._reject_identity_fields = lambda *_args: True
    handler._require_authorized = lambda *_args: True
    handler._begin_trace = lambda *_args: None
    responses = []
    handler._send = lambda status, data, **_kwargs: responses.append((status, data))
    handler.do_GET()
    assert responses[0][0] == 200
    assert calls == [{"light": True, "scope": "process"}]


@pytest.mark.parametrize("enabled", [False, True])
def test_redundant_pagination_aliases_are_removed_from_both_output_modes(enabled):
    from local_ai_hub.agent_diagnostics import project_agent_response

    result = project_agent_response({
        "success": True, "results": [{"path": "a.py"}], "returned_count": 1,
        "matches_count": 1, "returned_limit": 1, "total_matches": 5,
        "observed_match_count": 5, "count_exact": True, "has_more": True, "next_offset": 1,
    }, enabled=enabled)
    assert not {"matches_count", "returned_limit", "observed_match_count"}.intersection(result)
    assert result["returned_count"] == 1
    assert result["total_matches"] == 5
    assert result["next_offset"] == 1
    distinct = {"symbols": [], "returned_count": 0, "total_matches": 100, "observed_match_count": 20}
    assert project_agent_response(distinct, enabled=enabled)["observed_match_count"] == 20


def test_wire_budget_retains_limits_and_actual_size_without_internal_before_size():
    from local_ai_hub.agent_diagnostics import project_agent_response

    result = {"response_budget": {"requested_tokens": 500, "returned_tokens": 100,
                                  "original_tokens": 2000, "truncated": True}}
    normal = project_agent_response(result, enabled=False)
    assert normal["response_budget"] == {"requested_tokens": 500, "returned_tokens": 100, "truncated": True}
    assert project_agent_response(result, enabled=True) == result


def test_generated_schemas_do_not_resurrect_retired_command_tool():
    from local_ai_hub.generator import generate_mcp_tool_schemas
    from local_ai_hub.operation_contracts import operation_contract

    assert "local_ai_command" not in generate_mcp_tool_schemas({})
    assert operation_contract("local_ai_command") is None


def test_coordination_has_one_canonical_public_owner():
    from local_ai_hub.operation_contracts import operation_actions

    duplicates = {"context_compile", "verify_receipt", "verify_completion"}
    assert not duplicates.intersection(operation_actions("local_ai_repo"))
    assert duplicates.issubset(operation_actions("local_ai_coord"))


@pytest.mark.parametrize("path", [
    "/api/repo/config", "/api/repo_state", "/api/worktrees",
    "/api/affected_tests", "/api/topology", "/api/dead_code",
])
def test_retired_http_aliases_do_not_dispatch(monkeypatch, tmp_path, path):
    from types import SimpleNamespace
    from urllib.parse import quote
    from local_ai_hub import http_server

    monkeypatch.setattr(http_server, "APP", SimpleNamespace(
        config={}, debug_traces=SimpleNamespace(enabled=False), deterministic=None, services=SimpleNamespace()))
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *_args: None)
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = path + "?root=" + quote(str(tmp_path))
    handler.command, handler.headers = "GET", {}
    handler._reject_identity_fields = lambda *_args: True
    handler._require_authorized = lambda *_args: True
    handler._begin_trace = lambda *_args: None
    handler._bind_repository_root_query = lambda *_args: True
    responses = []
    handler._send = lambda status, data, **_kwargs: responses.append((status, data))
    handler.do_GET()
    assert len(responses) == 1
    assert responses[0][0] == 404


def test_lease_claim_has_one_http_entry_point():
    from local_ai_hub.http_route_registry import select_http_routes

    assert not select_http_routes("POST", "/api/leases/claim")
    assert select_http_routes("POST", "/api/leases/claim_batch")


@pytest.mark.parametrize("enabled", [False, True])
def test_get_timeline_remains_a_gated_real_reader(monkeypatch, enabled):
    from types import SimpleNamespace
    from local_ai_hub import http_server
    calls = []
    def timeline(limit, *, before_id=None):
        calls.append((limit, before_id))
        return {"timeline": [{"id": 1}], "has_more": False}
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={},
        debug_traces=SimpleNamespace(enabled=enabled), services=SimpleNamespace(),
        telemetry=SimpleNamespace(get_timeline_page=timeline)))
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *args: None)
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path, handler.command, handler.headers = "/api/telemetry/timeline?limit=7&before_id=10", "GET", {}
    handler._reject_identity_fields = handler._require_authorized = lambda *args: True
    handler._begin_trace = lambda *args: None
    responses = []
    handler._send = lambda status, data, **kwargs: responses.append((status, data))
    handler.do_GET()
    assert len(responses) == 1
    assert responses[0][0] == (200 if enabled else 409)
    assert calls == ([("7", "10")] if enabled else [])
    if enabled:
        assert responses[0][1]["timeline"] == [{"id": 1}]


def test_current_surface_has_no_missing_or_stale_audit_disposition():
    from tools.audit_agent_surface import check_audit

    assert check_audit(Path(__file__).resolve().parents[1]) == []


def test_aggregate_reports_keep_counts_without_a_raw_detail_bypass():
    from local_ai_hub.agent_diagnostics import project_aggregate_response
    source = {"success": True, "report": {"metrics": {"cache_hits": 3},
        "token_efficiency": {"net_cloud_token_delta_est": -2, "raw": "private"},
        "runtime_snapshots": [{"payloads": "private"}],
        "error_messages": ["private"], "debug": "private"}}
    normal = project_aggregate_response(source, enabled=False)
    assert normal == {"success": True, "report": {"metrics": {"cache_hits": 3},
        "token_efficiency": {"net_cloud_token_delta_est": -2}}}
    assert project_aggregate_response(source, enabled=True) == source


def test_artifact_kind_reads_real_metadata_without_loading_payload(tmp_path):
    from local_ai_hub.artifacts import ArtifactStore
    store = ArtifactStore(tmp_path)
    item = store.put("secret diagnostic body", kind="diagnostic-async-job")
    assert store.kind(item) == "diagnostic-async-job"
    assert store.kind("missing") is None


@pytest.mark.parametrize("enabled", [False, True])
def test_sse_replay_projects_detail_without_changing_persisted_event(tmp_path, monkeypatch, enabled):
    import io
    from types import SimpleNamespace
    from local_ai_hub import http_server
    from local_ai_hub.agent_events import AgentEvent, AgentStateStore
    store = AgentStateStore(tmp_path / "events.sqlite3")
    store.append(AgentEvent.create("task-1", "task.updated",
        {"text": "work result", "debug": "private-observation"}, "audit-event"))
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(agent_state=store,
        config={"server": {"max_stream_duration_seconds": 1}},
        debug_traces=SimpleNamespace(enabled=enabled)))
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.headers, handler.wfile = {}, io.BytesIO()
    handler.send_response = handler.send_header = lambda *args: None
    handler.end_headers = handler._common_headers = lambda: None
    handler._finish_stream_request = lambda *args, **kwargs: None
    handler._stream_agent_events(stream_id="task-1", after_seq=0, timeout=0.001)
    output = handler.wfile.getvalue().decode()
    assert "work result" in output
    assert ("private-observation" in output) is enabled
    assert "private-observation" in str(store.event_page(stream_id="task-1", after_seq=0, limit=10))


def test_inventory_retains_real_get_output_despite_preflight_comparisons():
    from tools.audit_agent_surface import collect_surface
    from pathlib import Path
    facts = collect_surface(Path(__file__).resolve().parents[1])["GET /api/telemetry/timeline"]
    assert "APP.telemetry.get_timeline_page" in facts["response_producers"]
    assert "success" in facts["literal_response_fields"]
