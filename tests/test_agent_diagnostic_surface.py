from types import SimpleNamespace

import pytest

from local_ai_hub.agent_diagnostics import (
    detailed_diagnostics_enabled,
    project_agent_response,
)


def test_normal_response_keeps_decisions_and_evidence_without_internal_metrics():
    result = {
        "success": False, "terminal": True, "retryable": False,
        "error": "invalid root", "request_id": "request-1", "root": "C:/repo",
        "evidence_ids": ["E123"], "next_action": "choose an authorized root",
        "has_more": True, "next_offset": 3, "stale": True,
        "response_budget": {"requested_tokens": 800, "returned_tokens": 200},
        "_token_accounting": {"raw_response_tokens_est": 123},
        "phase_timings_ms": {"retrieval": 20},
        "token_efficiency": {"protocol_tokens_est": 100},
        "pipeline": {"stages": ["lexical"]},
        "results": [{"path": "a.py", "line": 7, "model_debug": "hidden"}],
    }
    projected = project_agent_response(result, enabled=False)
    assert projected == {
        key: value for key, value in result.items()
        if key not in {"_token_accounting", "phase_timings_ms", "token_efficiency", "pipeline", "results"}
    } | {"results": [{"path": "a.py", "line": 7}]}
    assert result["results"][0]["model_debug"] == "hidden"


def test_diagnostic_mode_keeps_detail_but_never_exposes_private_accounting():
    result = {"success": True, "debug": {"trace": "complete"}, "_token_accounting": {"internal": 1}}
    assert project_agent_response(result, enabled=True) == {
        "success": True, "debug": {"trace": "complete"},
    }


def test_user_memory_settings_and_compiler_diagnostics_remain_intact():
    result = {
        "value": {"debug": True, "telemetry": {"example": 1}},
        "settings": {"debug_traces.enabled": False},
        "state_data": {"raw": "user data"},
        "diagnostics": [{"path": "a.py", "line": 4, "message": "undefined name"}],
    }
    assert project_agent_response(result, enabled=False) == result


def test_pipeline_failure_and_requested_step_results_are_actionable():
    result = {"pipeline": {"stages": ["rag"], "ollama_calls": 1, "degraded": True,
                           "error": "index unavailable"}}
    assert project_agent_response(result, enabled=False) == {
        "pipeline": {"degraded": True, "error": "index unavailable"},
    }
    steps = {"pipeline": {"results": [{"success": True, "text": "done"}]}}
    assert project_agent_response(steps, enabled=False) == steps


def test_live_runtime_toggle_is_rechecked_without_restarting_mcp(tmp_path):
    runtime = tmp_path / "config.runtime.toml"
    config = {"debug_traces": {"enabled": False}, "_runtime_override_path": str(runtime)}
    assert detailed_diagnostics_enabled(config) is False
    runtime.write_text("[debug_traces]\nenabled = true\n", encoding="utf-8")
    assert detailed_diagnostics_enabled(config) is True
    runtime.write_text("[debug_traces]\nenabled = false\n", encoding="utf-8")
    assert detailed_diagnostics_enabled(config) is False
    runtime.write_text("malformed TOML!", encoding="utf-8")
    assert detailed_diagnostics_enabled(config) is False


def test_runtime_reset_does_not_restore_a_stale_startup_true(tmp_path):
    base = tmp_path / "config.toml"
    runtime = tmp_path / "config.runtime.toml"
    base.write_text("[debug_traces]\nenabled = false\n", encoding="utf-8")
    runtime.write_text("[debug_traces]\nenabled = true\n", encoding="utf-8")
    config = {"debug_traces": {"enabled": True}, "_config_path": str(base),
              "_runtime_override_path": str(runtime)}
    assert detailed_diagnostics_enabled(config) is True
    runtime.unlink()
    assert detailed_diagnostics_enabled(config) is False


@pytest.mark.parametrize("enabled", [False, None, "true", 1])
def test_dashboard_gate_requires_explicit_boolean_true(enabled):
    assert detailed_diagnostics_enabled({}, store=SimpleNamespace(enabled=enabled)) is False


def test_live_store_is_authoritative_over_startup_config():
    assert detailed_diagnostics_enabled(
        {"debug_traces": {"enabled": True}}, store=SimpleNamespace(enabled=False),
    ) is False


@pytest.mark.parametrize("arguments", [
    {}, {"response_profile": "debug"}, {"extra_fields": ["telemetry", "raw_model_output"]},
    {"action": "diagnostics"},
])
def test_mcp_callers_cannot_override_disabled_dashboard_diagnostics(monkeypatch, arguments):
    from local_ai_hub import mcp_server

    monkeypatch.setattr(mcp_server, "CFG", {"debug_traces": {"enabled": False}})
    result = mcp_server._agent_output(
        {"success": True, "text": "answer", "telemetry": {"requests": 2}, "raw_model_output": "hidden"},
        "local_ai_repo", arguments,
    )
    assert result == {"success": True, "text": "answer"}


def test_mcp_wire_filter_catches_accounting_added_by_pagination(monkeypatch):
    import json
    from local_ai_hub import mcp_server
    from local_ai_hub.token_accounting import json_tokens

    monkeypatch.setattr(mcp_server, "CFG", {"debug_traces": {"enabled": False}})
    contents, structured = mcp_server._mcp_budget_payload(
        "local_ai_repo", {"action": "code_index", "max_response_tokens": 1600},
        {"success": True, "root": "C:/repo", "query": "thing", "symbols": [
            {"name": "thing", "path": "a.py", "line": 3},
        ], "total_matches": 1, "returned_count": 1, "has_more": False,
         "_token_accounting": {"raw_response_tokens_est": 500}},
    )
    assert "_token_accounting" not in structured
    assert "token_efficiency" not in structured
    assert json.loads(contents[0].text) == structured
    assert structured["symbols"][0]["name"] == "thing"
    wire = {"content": [{"type": "text", "text": contents[0].text}],
            "structuredContent": structured, "isError": False}
    assert structured["response_budget"]["returned_tokens"] == json_tokens(wire)
    assert json_tokens(wire) <= 1600


def test_detailed_wire_accounting_uses_the_final_sanitized_response(monkeypatch):
    from local_ai_hub import mcp_server
    from local_ai_hub.token_accounting import json_tokens, tool_request_tokens

    monkeypatch.setattr(mcp_server, "CFG", {"debug_traces": {"enabled": True}})
    arguments = {"action": "code_index", "max_response_tokens": 2400}
    contents, structured = mcp_server._mcp_budget_payload("local_ai_repo", arguments, {
        "success": True, "root": "C:/repo", "query": "thing",
        "symbols": [{"name": "thing", "path": "a.py", "line": 3}],
        "total_matches": 1, "returned_count": 1, "has_more": False,
        "token_efficiency": {"protocol_tokens_est": 1},
    })
    wire = {"content": [{"type": "text", "text": contents[0].text}],
            "structuredContent": structured, "isError": False}
    returned = json_tokens(wire)
    assert "_token_accounting" not in structured
    assert structured["response_budget"]["returned_tokens"] == returned
    assert structured["token_efficiency"]["protocol_tokens_est"] == (
        tool_request_tokens("local_ai_repo", arguments) + returned
    )


@pytest.mark.parametrize("enabled", [False, True])
def test_http_filters_wire_only_and_keeps_full_local_trace(monkeypatch, enabled):
    import io
    import json
    from local_ai_hub import http_server

    app = SimpleNamespace(config={}, debug_traces=SimpleNamespace(enabled=enabled))
    monkeypatch.setattr(http_server, "APP", app)
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = "/api/repo/context"
    handler.headers = {}
    handler._telemetry_finished = True
    handler._debug_trace_finished = True
    handler.wfile = io.BytesIO()
    handler.send_response = lambda _status: None
    handler.send_header = lambda *_args: None
    handler.end_headers = lambda: None
    handler._common_headers = lambda: None
    handler._close_trace_context = lambda: None
    recorded = []
    handler._finish_debug_trace = lambda _status, data: recorded.append(data)
    original = {"success": True, "text": "answer", "model_debug": "full detail",
                "phase_timings_ms": {"retrieval": 2},
                "response_budget": {"requested_tokens": 800, "returned_tokens": 0}}
    handler._send(200, original)
    wire = json.loads(handler.wfile.getvalue())
    assert ("model_debug" in wire) is enabled
    assert ("phase_timings_ms" in wire) is enabled
    assert wire["text"] == "answer"
    from local_ai_hub.token_accounting import json_tokens
    assert wire["response_budget"]["returned_tokens"] == json_tokens(wire)
    assert recorded == [original]


@pytest.mark.parametrize("path", [
    "/api/debug-traces", "/api/debug-traces/old-trace", "/api/debug-traces/old-trace/metrics",
    "/api/telemetry/timeline", "/api/logs/tail",
])
def test_disabled_detail_routes_do_not_read_retained_payloads(monkeypatch, path):
    from local_ai_hub import http_server

    def forbidden(*_args, **_kwargs):
        pytest.fail("disabled diagnostics must not read retained payloads")

    store = SimpleNamespace(enabled=False, list=forbidden, detail=forbidden,
                            request_id_for_trace=forbidden)
    app = SimpleNamespace(config={}, debug_traces=store,
                          telemetry=SimpleNamespace(tail=forbidden, timeline=forbidden))
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *_args: None)
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = path
    handler.headers = {}
    handler._reject_identity_fields = lambda *_args: True
    handler._require_authorized = lambda *_args: True
    handler._begin_trace = lambda *_args: None
    responses = []
    handler._send = lambda status, data, **_kwargs: responses.append((status, data))
    handler.do_GET()
    assert len(responses) == 1
    status, data = responses[0]
    if path == "/api/debug-traces":
        assert status == 200
        assert data["enabled"] is False
        assert data["items"] == []
    else:
        assert status == 409
        assert data["error_code"] == "detailed_diagnostics_disabled"
