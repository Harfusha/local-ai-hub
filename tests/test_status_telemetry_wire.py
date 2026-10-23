from __future__ import annotations

import asyncio
import json

import pytest

from local_ai_hub import mcp_server
from local_ai_hub.operation_contracts import validate_operation_output
from local_ai_hub.operational_mode import OperationalModeSnapshot
from local_ai_hub.token_accounting import json_tokens


REQUIRED_TELEMETRY_FIELDS = {
    "success",
    "window",
    "summary",
    "queue",
    "hotspots",
    "by_operation",
    "error_fingerprints",
    "detail",
    "decision_grade",
}


def _telemetry_report() -> dict:
    return {
        "success": True,
        "window": {"days": 30, "scope": "process"},
        "summary": {
            "events": 120,
            "cache_hits": 30,
            "coalesced": 4,
            "input_tokens": 8000,
            "output_tokens": 2200,
            "avoided_cloud_tokens": 700,
            "avg_duration_ms": 42.5,
            "failure_rate": 0.01,
            "avg_queue_wait_ms": 3.5,
            "fallback_count": 2,
            "degraded_count": 1,
            "retry_count": 3,
            "cache_hit_rate": 0.25,
            "net_cloud_token_delta_est": 680.5,
        },
        "queue": {"depth": 2, "dropped": 0},
        "hotspots": [
            {"type": "latency", "signal": "queue_wait", "count": 2},
            {"type": "efficiency", "signal": "low_cache_hit_rate", "count": 1},
        ],
        "by_operation": [
            {"action": "context", "events": 80, "avg_duration_ms": 38.0},
            {"action": "search", "events": 40, "avg_duration_ms": 51.0},
        ],
        "error_fingerprints": [
            {"component": "repository", "error_type": "TimeoutError", "operation": "search"},
        ],
        "detail": {"status": "complete", "omitted_sections": []},
        "decision_grade": {"counts": {"events": 120, "failures": 1}},
    }


def _wire_measure(result: object) -> tuple[int, dict, dict | None]:
    assert isinstance(result, tuple)
    contents, structured = result
    text = contents[0].text
    wire = {
        "content": [{"type": "text", "text": text}],
        "structuredContent": structured,
        "isError": False,
    }
    return json_tokens(wire), json.loads(text), structured


@pytest.mark.parametrize("profile", ["", "compact", "minimal"])
def test_readiness_wire_omits_backend_telemetry_and_respects_budget(
    monkeypatch: pytest.MonkeyPatch, profile: str
) -> None:
    monkeypatch.setattr(
        mcp_server,
        "load_operational_mode",
        lambda _state_dir: OperationalModeSnapshot("active", 0, None),
    )
    monkeypatch.setattr(mcp_server.FEATURES, "status", True)
    monkeypatch.setattr(mcp_server.CLIENT, "get", lambda _path, timeout=None: {
        "hub_online": True, "version": "test", "ollama_online": True, "scheduler": {},
        "report": _telemetry_report()})
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, "record", lambda _event: None)
    monkeypatch.setattr(mcp_server.CONTEXT_LEDGER, "record", lambda **_kwargs: None)

    arguments = {
        "detail": "brief",
        "max_response_tokens": 1800,
        "reuse_key": f"status-telemetry-wire:detail:{profile or 'default'}",
    }
    if profile:
        arguments["response_profile"] = profile
    result = asyncio.run(mcp_server.mcp.call_tool("local_ai_status", arguments))

    wire_tokens, decoded_text, structured = _wire_measure(result)
    assert structured is not None
    assert decoded_text == structured
    assert wire_tokens <= 1800

    for payload in (decoded_text, structured):
        assert payload["success"] is True
        assert {"success", "version", "ollama_online", "active_model", "degraded"} <= payload.keys()
        assert validate_operation_output("local_ai_status", "brief", payload) is None
        assert not {"report", "summary", "hotspots", "error_fingerprints"}.intersection(payload)


def test_http_aggregate_wire_preserves_metric_types_without_private_detail(monkeypatch):
    import io
    from types import SimpleNamespace
    from local_ai_hub import http_server
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={}, debug_traces=SimpleNamespace(enabled=False)))
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path, handler.headers, handler.wfile = "/api/telemetry/report", {}, io.BytesIO()
    handler._telemetry_finished = handler._debug_trace_finished = True
    handler.send_response = handler.send_header = lambda *args: None
    handler.end_headers = handler._common_headers = lambda: None
    handler._finish_debug_trace = lambda *args: None
    handler._send(200, {"success": True, "report": _telemetry_report()})
    report = json.loads(handler.wfile.getvalue())["report"]
    assert isinstance(report["summary"]["events"], int)
    assert isinstance(report["summary"]["avg_duration_ms"], float)
    assert isinstance(report["summary"]["net_cloud_token_delta_est"], float)
    assert report["summary"]["cache_hits"] == 30
    assert "hotspots" not in report
    assert "error_fingerprints" not in report


@pytest.mark.parametrize("profile", ["", "compact", "minimal"])
def test_status_telemetry_wire_rejects_retired_action_selector(
    monkeypatch: pytest.MonkeyPatch, profile: str,
) -> None:
    monkeypatch.setattr(
        mcp_server, "load_operational_mode",
        lambda _state_dir: OperationalModeSnapshot("active", 0, None),
    )
    monkeypatch.setattr(mcp_server.FEATURES, "status", True)
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, "record", lambda _event: None)
    monkeypatch.setattr(mcp_server.CONTEXT_LEDGER, "record", lambda **_kwargs: None)

    def forbidden_get(*_args, **_kwargs):
        raise AssertionError("invalid selector must reject before HTTP dispatch")

    monkeypatch.setattr(mcp_server.CLIENT, "get", forbidden_get)
    arguments = {"action": "telemetry", "max_response_tokens": 1800}
    if profile:
        arguments["response_profile"] = profile
    result = asyncio.run(mcp_server.mcp.call_tool("local_ai_status", arguments))
    wire_tokens, decoded_text, structured = _wire_measure(result)
    assert decoded_text == structured
    assert wire_tokens <= 1800
    assert structured["success"] is False
    assert structured["status_code"] == 400
    assert "action" in structured["error"]
    assert structured["terminal"] is True
    assert structured["retryable"] is False
