from __future__ import annotations

import asyncio
import json
import pytest

from local_ai_hub import mcp_server
from local_ai_hub.token_accounting import json_tokens


@pytest.fixture(autouse=True)
def qualified_semantic_actions(monkeypatch):
    monkeypatch.setattr(mcp_server.FEATURES, "tasks", True)
    monkeypatch.setattr(mcp_server.FEATURES, "hardware_profile", "balanced")
    monkeypatch.setattr(mcp_server.FEATURES, "local_semantic_analysis", True)
    monkeypatch.setattr(mcp_server.FEATURES, "has_any_model", lambda: True)


def _wire_measure(result) -> tuple[int, dict, dict | None]:
    if isinstance(result, tuple):
        contents, structured = result
    else:
        contents, structured = result, None
    text = contents[0].text
    wire = {"content": [{"type": "text", "text": text}]}
    if structured is not None:
        wire["structuredContent"] = structured
        wire["isError"] = False
    return json_tokens(wire), json.loads(text), structured


def test_lease_mutation_wire_budget_keeps_identity_and_outcome(tmp_path, monkeypatch):
    lease_id = "lease_0123456789abcdef0123"
    monkeypatch.setattr(mcp_server.CLIENT, "post", lambda path, *_a, **_kw: (
        {"success": True, "lease_id": lease_id, "expires_at": 1793613360.0}
        if path.endswith("claim_batch") else {"success": True, "released_rows": 1}))
    monkeypatch.setattr(mcp_server, "_record_adoption", lambda *_a, **_kw: None)
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **_kw: None)
    common = {"root": str(tmp_path), "owner": "test-owner", "max_response_tokens": 512,
              "response_profile": "minimal"}
    for arguments in ({**common, "action": "claim", "paths": ["a.txt"], "purpose": "test"},
                      {**common, "action": "release", "lease_id": lease_id}):
        result = asyncio.run(mcp_server.mcp.call_tool("local_ai_coord", arguments))
        tokens, parsed, structured = _wire_measure(result)
        assert tokens <= 512
        assert parsed == structured
        assert parsed["response_budget"]["returned_tokens"] == tokens
        assert parsed["mutation_applied"] is True
        if arguments["action"] == "claim":
            assert parsed["lease_id"] == lease_id
        else:
            assert parsed["released_rows"] == 1


def test_admission_diagnostics_survive_minimal_mcp_wire(monkeypatch):
    monkeypatch.setattr(mcp_server.FEATURES, "tasks", True)
    monkeypatch.setattr(mcp_server.FEATURES, "has_any_model", lambda: True)
    monkeypatch.setattr(mcp_server.CLIENT, "post", lambda *_a, **_kw: {
        "success": False, "error": "insufficient VRAM for model admission", "retryable": True,
        "last_admission_state": "rejected", "last_admission_reason": "vram_budget", "last_admission_model": "qwen2.5-coder:7b"})
    monkeypatch.setattr(mcp_server, "_record_adoption", lambda *_a, **_kw: None)
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **_kw: None)
    result = asyncio.run(mcp_server.mcp.call_tool("local_ai_task", {"action": "second_opinion",
        "task": "Check", "candidate": "A", "response_profile": "minimal", "max_response_tokens": 512}))
    tokens, parsed, structured = _wire_measure(result)
    assert tokens <= 512 and parsed == structured
    assert parsed["success"] is False and parsed["retryable"] is True
    assert parsed["last_admission_state"] == "rejected" and parsed["last_admission_reason"] == "vram_budget"
    assert parsed["last_admission_model"] == "qwen2.5-coder:7b"


def test_truncated_model_output_stays_failure_on_minimal_mcp_wire(monkeypatch):
    monkeypatch.setattr(mcp_server.FEATURES, "tasks", True)
    monkeypatch.setattr(mcp_server.FEATURES, "has_any_model", lambda: True)
    monkeypatch.setattr(mcp_server.CLIENT, "post", lambda *_a, **_kw: {
        "success": False, "error": "local model output reached its token limit", "terminal": True,
        "retryable": False, "output_truncated": True, "stop_reason": "length", "text": "partial"})
    monkeypatch.setattr(mcp_server, "_record_adoption", lambda *_a, **_kw: None)
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **_kw: None)
    result = asyncio.run(mcp_server.mcp.call_tool("local_ai_task", {"action": "delegate", "task": "Check",
        "response_profile": "minimal", "max_response_tokens": 512}))
    tokens, parsed, structured = _wire_measure(result)
    assert tokens <= 512 and parsed == structured
    assert parsed["success"] is False and parsed["output_truncated"] is True
    assert parsed["stop_reason"] == "length" and parsed["retryable"] is False


def test_live_mcp_budget_measures_final_envelope_and_accounting(monkeypatch) -> None:
    events = []
    monkeypatch.setattr(mcp_server, "CLIENT", mcp_server.HubClient(auto_start=False))
    monkeypatch.setattr(mcp_server.CLIENT, "get", lambda path, timeout=None: {
        "hub_online": True, "scheduler": {}, "observability": {},
    })
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, "record", lambda event: events.append(dict(event)))
    monkeypatch.setattr(mcp_server.CONTEXT_LEDGER, "record", lambda **kwargs: None)
    requested = 512

    result = asyncio.run(mcp_server.mcp.call_tool(
        "local_ai_status", {"detail": "brief", "max_response_tokens": requested},
    ))

    wire_tokens, parsed, structured = _wire_measure(result)
    assert wire_tokens <= requested
    assert parsed["response_budget"]["requested_tokens"] == requested
    assert parsed["response_budget"]["returned_tokens"] == wire_tokens
    assert structured is not None
    assert structured["response_budget"]["returned_tokens"] == wire_tokens
    assert len(events) == 1
    assert events[0]["agent_tool_response_tokens_est"] == wire_tokens
    assert events[0]["projected_response_tokens_est"] == wire_tokens
    assert events[0]["agent_protocol_tokens_est"] == (
        events[0]["agent_tool_request_tokens_est"] + wire_tokens
    )
    assert events[0]["tool_schema_tokens_est"] > 0
    assert events[0]["net_after_schema_token_delta_est"] == (
        events[0]["net_cloud_token_delta_est"] - events[0]["tool_schema_tokens_est"]
    )


def test_wire_budget_preserves_error_and_evidence(monkeypatch) -> None:
    monkeypatch.setattr(mcp_server, "_REUSE_DIGESTS", mcp_server.OrderedDict())
    monkeypatch.setattr(mcp_server, "_REUSE_VALUES", mcp_server.OrderedDict())
    result = mcp_server._mcp_budget_payload(
        "local_ai_status",
        {"max_response_tokens": 128},
        {
            "success": False,
            "status_code": 500,
            "terminal": True,
            "retryable": False,
            "error": "specific route failure " + "x" * 5000,
            "evidence_ids": ["E123"],
            "details": "y" * 5000,
        },
    )

    wire_tokens, parsed, _structured = _wire_measure(result)
    assert wire_tokens <= 128
    assert parsed["response_budget"]["requested_tokens"] == 128
    assert parsed["response_budget"]["returned_tokens"] == wire_tokens
    assert parsed["success"] is False
    assert parsed["error"].startswith("specific route failure")
    assert parsed["evidence_ids"] == ["E123"]


def test_wire_budget_preserves_context_file_line_evidence(monkeypatch) -> None:
    monkeypatch.setattr(mcp_server, "_REUSE_DIGESTS", mcp_server.OrderedDict())
    monkeypatch.setattr(mcp_server, "_REUSE_VALUES", mcp_server.OrderedDict())
    result = mcp_server._mcp_budget_payload(
        "local_ai_repo",
        {"action": "context", "max_response_tokens": 128},
        {
            "success": True,
            "adaptive_context_pack": {
                "context_id": "ctx-wire",
                "evidence": [{
                    "evidence_id": "E123", "path": "src/main.py",
                    "start_line": 7, "end_line": 9, "source": "deterministic",
                }],
                "context": "large context " * 2000,
            },
        },
    )

    wire_tokens, parsed, _structured = _wire_measure(result)
    evidence = parsed["adaptive_context_pack"]["evidence"][0]
    assert wire_tokens <= 128
    assert parsed["response_budget"]["requested_tokens"] == 128
    assert parsed["response_budget"]["returned_tokens"] == wire_tokens
    assert evidence["evidence_id"] == "E123"
    assert evidence["path"] == "src/main.py"
    assert evidence["start_line"] == 7
    assert evidence["end_line"] == 9
