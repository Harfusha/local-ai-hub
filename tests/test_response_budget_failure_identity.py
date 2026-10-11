from __future__ import annotations

import json

import pytest

from local_ai_hub import mcp_server
from local_ai_hub.response_budget import _budget_rejection
from local_ai_hub.token_accounting import json_tokens


@pytest.mark.parametrize("include_error", [False, True])
def test_failed_command_wire_budget_preserves_failure_identity(include_error: bool, monkeypatch) -> None:
    monkeypatch.setattr(mcp_server, "_REUSE_DIGESTS", mcp_server.OrderedDict())
    monkeypatch.setattr(mcp_server, "_REUSE_VALUES", mcp_server.OrderedDict())
    request_id = "req_0123456789abcdef0123456789abcdef"
    execution_id = "e" * 32
    result = {
        "success": False,
        "exit_code": 1,
        "summary": "Command failed: process exited with code 1. " + "trace detail " * 60,
        "request_id": request_id,
        "execution_id": execution_id,
        "outcome_unknown": True,
        "terminal": True,
        "retryable": False,
        "details": "optional artifact payload " * 1800,
    }
    if include_error:
        result["error"] = "command execution failed"

    contents, structured = mcp_server._mcp_budget_payload(
        "local_ai_command",
        {"max_response_tokens": 1200},
        result,
    )
    parsed = json.loads(contents[0].text)
    wire = {
        "content": [{"type": "text", "text": contents[0].text}],
        "structuredContent": structured,
        "isError": False,
    }

    assert json_tokens(wire) <= 1200
    assert parsed["request_id"] == request_id
    assert parsed["execution_id"] == execution_id
    assert parsed["exit_code"] == 1
    assert parsed["outcome_unknown"] is True
    assert parsed["terminal"] is True
    assert parsed["retryable"] is False
    assert parsed["summary"].startswith("Command failed:")
    assert (parsed.get("error") == "command execution failed") is include_error
    assert parsed["response_budget"]["returned_tokens"] == json_tokens(wire)


def test_failed_command_rejection_keeps_full_identity_at_compact_inner_budget() -> None:
    request_id = "req_0123456789abcdef0123456789abcdef"
    execution_id = "e" * 32
    source = {
        "success": False,
        "exit_code": 1,
        "summary": "Command failed: process exited with code 1. " + "trace detail " * 60,
        "request_id": request_id,
        "execution_id": execution_id,
        "outcome_unknown": True,
        "terminal": True,
        "retryable": False,
        "artifact_ids": [f"artifact-{index}" for index in range(24)],
    }

    result = _budget_rejection(
        requested=128,
        original=1215,
        source=source,
        protected_keys=(
            "exit_code", "summary", "request_id", "execution_id", "artifact_ids",
            "outcome_unknown", "terminal", "retryable",
        ),
    )

    assert json_tokens(result) <= 128
    assert result["request_id"] == request_id
    assert result["execution_id"] == execution_id
    assert result["exit_code"] == 1
    assert result["outcome_unknown"] is True
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert result["summary"].startswith("Command failed:")
