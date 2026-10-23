from __future__ import annotations



from local_ai_hub.response_budget import _budget_rejection
from local_ai_hub.token_accounting import json_tokens


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


def test_failed_command_rejection_preserves_protected_context_and_evidence() -> None:
    context_id = "ctx-0123456789abcdef"
    evidence_id = "E0123456789abcdef"
    result = _budget_rejection(
        requested=512,
        original=1800,
        source={
            "success": False,
            "exit_code": 1,
            "error": "command failed",
            "execution_id": "e" * 32,
            "context_id": context_id,
            "evidence_ids": [evidence_id],
        },
        protected_keys=("context_id", "evidence_ids"),
    )

    assert result["context_id"] == context_id
    assert result["evidence_ids"] == [evidence_id]
    assert json_tokens(result) <= 512
