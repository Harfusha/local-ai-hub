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
@pytest.mark.parametrize("selector", ["detail", "action"])
def test_status_telemetry_wire_satisfies_output_contract_and_budget(
    monkeypatch: pytest.MonkeyPatch, profile: str, selector: str
) -> None:
    monkeypatch.setattr(
        mcp_server,
        "load_operational_mode",
        lambda _state_dir: OperationalModeSnapshot("active", 0, None),
    )
    monkeypatch.setattr(mcp_server.FEATURES, "status", True)
    monkeypatch.setattr(mcp_server.CLIENT, "get", lambda _path, timeout=None: _telemetry_report())
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, "record", lambda _event: None)
    monkeypatch.setattr(mcp_server.CONTEXT_LEDGER, "record", lambda **_kwargs: None)

    arguments = {
        selector: "telemetry",
        "max_response_tokens": 1800,
        "reuse_key": f"status-telemetry-wire:{selector}:{profile or 'default'}",
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
        assert REQUIRED_TELEMETRY_FIELDS <= payload.keys()
        assert validate_operation_output("local_ai_status", "telemetry", payload) is None
        assert isinstance(payload["summary"]["events"], int)
        assert isinstance(payload["summary"]["avg_duration_ms"], float)
        assert isinstance(payload["summary"]["net_cloud_token_delta_est"], float)
