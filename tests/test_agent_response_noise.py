from __future__ import annotations

import pytest

from local_ai_hub import mcp_server
from local_ai_hub.operational_mode import OperationalModeSnapshot
from local_ai_hub.token_accounting import json_tokens


@pytest.mark.parametrize("profile", ["minimal", "compact"])
def test_live_status_contract_accepts_brief_without_internal_metrics(monkeypatch, profile):
    import asyncio
    import json

    monkeypatch.setattr(mcp_server, "load_operational_mode", lambda _: OperationalModeSnapshot("active", 0, None))
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **kw: None)
    monkeypatch.setattr(mcp_server.CLIENT, "get", lambda path: {
        "success": True, "hub_online": True, "version": "4.0.0", "ollama_online": True,
        "scheduler": {"active_model": None, "queued": 0, "inflight": 0},
        "observability": {"net_cloud_token_delta_est": 9, "cache_hits": 2, "coalesced_waiters": 1},
    })
    contents, _ = asyncio.run(mcp_server.mcp.call_tool("local_ai_status", {
        "detail": "brief", "response_profile": profile, "max_response_tokens": 512,
    }))
    result = json.loads(contents[0].text)
    assert result["success"] is True, result
    assert result["version"] == "4.0.0"
    assert not set(result) & {"net_cloud_token_delta_est", "cache_hits", "coalesced_waiters"}


def test_accounting_send_resets_original_context_when_module_context_changes(monkeypatch):
    from contextvars import ContextVar

    original = ContextVar("original", default=("", True))
    replacement = ContextVar("replacement", default=("", True))
    monkeypatch.setattr(mcp_server, "_CURRENT_OPERATIONAL_CONTEXT", original)
    monkeypatch.setattr(mcp_server, "load_operational_mode", lambda _: OperationalModeSnapshot("active", 0, None))

    def post(*args, **kwargs):
        monkeypatch.setattr(mcp_server, "_CURRENT_OPERATIONAL_CONTEXT", replacement)
        return {"success": True}

    monkeypatch.setattr(mcp_server.CLIENT, "post", post)
    mcp_server._ProtocolAccountingReporter()._send([{"operation": "status"}])
    assert original.get() == ("", True)
    assert replacement.get() == ("", True)


@pytest.mark.parametrize("profile", ["", "minimal", "compact", "delta"])
def test_mcp_boundary_omits_infrastructure_noise_and_preserves_outcome(monkeypatch, profile):
    monkeypatch.setattr(mcp_server, "CFG", {"debug_traces": {"enabled": False}})
    recorded = []
    monkeypatch.setattr(mcp_server, "load_operational_mode", lambda _: OperationalModeSnapshot("active", 0, None))
    monkeypatch.setattr(mcp_server, "_record_adoption", lambda *a, **k: None)
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **kw: recorded.append(kw))
    payload = {
        "success": False, "error": "command failed", "terminal": True,
        "retryable": False, "outcome_unknown": True, "request_id": "request-1",
        "task_id": "task-1", "evidence_ids": ["E1"], "context_id": "ctx-1",
        "summary": "One test failed", "exit_code": 1,
        "stdout": "private output", "stderr": "private error",
        "diagnostics": [{"message": "private diagnostic"}],
        "phase_timings_ms": {"startup": 12}, "token_efficiency": {"schema_tokens_est": 200},
        "telemetry": {"cpu": 4}, "retrieval": {"latency_ms": 400},
    }

    @mcp_server._instrumented_tool()
    def local_ai_task(action="review", response_profile="", extra_fields=None):
        return dict(payload)

    result = local_ai_task(response_profile=profile)
    assert all(result[key] == payload[key] for key in (
        "success", "error", "terminal", "retryable", "outcome_unknown", "request_id",
        "task_id", "evidence_ids", "context_id", "summary", "exit_code",
    ))
    assert not set(result) & {
        "stdout", "stderr", "diagnostics", "phase_timings_ms", "token_efficiency", "telemetry", "retrieval",
    }
    assert recorded[0]["response"] == result
    assert payload["stdout"] == "private output"


def test_mcp_boundary_detail_requires_dashboard_toggle(monkeypatch):
    monkeypatch.setattr(mcp_server, "CFG", {"debug_traces": {"enabled": False}})
    monkeypatch.setattr(mcp_server, "load_operational_mode", lambda _: OperationalModeSnapshot("active", 0, None))
    monkeypatch.setattr(mcp_server, "_record_adoption", lambda *a, **k: None)
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **kw: None)

    @mcp_server._instrumented_tool()
    def local_ai_task(action="review", response_profile="", extra_fields=None):
        return {"success": True, "stdout": "log", "telemetry": {"cpu": 1},
                "response_budget": {"requested_tokens": 3200, "returned_tokens": 0}}

    explicit = local_ai_task(extra_fields=["stdout"])
    assert "stdout" not in explicit
    assert "telemetry" not in explicit
    assert explicit["response_budget"]["returned_tokens"] == json_tokens(explicit)
    debug = local_ai_task(response_profile="debug")
    assert "telemetry" not in debug
    monkeypatch.setattr(mcp_server, "CFG", {"debug_traces": {"enabled": True}})
    debug = local_ai_task(response_profile="debug")
    assert debug["telemetry"] == {"cpu": 1}


@pytest.mark.parametrize("budget", [512, 3200])
def test_final_wire_projection_removes_noise_before_budgeting(budget):
    import json

    payload = {"success": True, "evidence_ids": ["E1"], "context_id": "ctx-1",
               "telemetry": {"debug": "x" * 20000},
               "retrieval": {"latency_ms": 123, "trace": "y" * 20000},
               "token_efficiency": {"schema_tokens_est": 200}, "stdout": "z" * 20000}
    contents, structured = mcp_server._mcp_budget_payload(
        "local_ai_repo", {"action": "search", "max_response_tokens": budget}, payload,
    )
    parsed = json.loads(contents[0].text)
    wire = {"content": [{"type": "text", "text": contents[0].text}]}
    if structured is not None:
        wire.update(structuredContent=structured, isError=False)
    assert parsed["success"] is True
    assert not set(parsed) & {"telemetry", "retrieval", "token_efficiency", "stdout"}
    assert json_tokens(wire) <= budget
    assert parsed["response_budget"]["returned_tokens"] == json_tokens(wire)
