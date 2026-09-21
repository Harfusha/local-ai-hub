from __future__ import annotations

import json
from pathlib import Path

from local_ai_hub.response_budget import budget_response
from local_ai_hub.token_accounting import (
    finalize_tool_accounting,
    json_tokens,
    replay_accounting,
    token_efficiency_metadata,
)
from local_ai_hub.trace_context import current, reset_metadata, set_metadata


FIXTURE = Path(__file__).parent / "fixtures" / "token_efficiency_cases.jsonl"


def _cases() -> list[dict[str, object]]:
    return [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_future_metadata_is_bounded_and_never_keeps_payload_text() -> None:
    metadata = token_efficiency_metadata(
        {
            "root_family": "repo-family",
            "task_id": "task-14",
            "parent_task": "parent-1",
            "phase": "review",
            "activity": "redundant_review",
            "revision": "abc123",
            "context_digest": "digest-123",
            "raw_input_tokens_est": 1200,
            "reused_input_tokens_est": 840,
            "generated_output_tokens_est": 90,
            "output_tokens_est": 90,
            "reuse_state": "hit",
            "cache_state": "hit",
            "queue_wait_ms": 12.5,
            "bypass_reason": "",
            "prompt": "must not be stored",
            "source": "must not be stored",
            "model_output": "must not be stored",
        }
    )

    assert metadata["root_family"] == "repo-family"
    assert metadata["raw_input_tokens_est"] == 1200
    assert metadata["reused_input_tokens_est"] == 840
    assert metadata["generated_output_tokens_est"] == 90
    assert metadata["avoided_payload_tokens_est"] == 840
    assert "prompt" not in metadata
    assert "source" not in metadata
    assert "model_output" not in metadata
    assert "must not be stored" not in json.dumps(metadata)


def test_trace_context_exposes_optional_metadata_without_changing_base_fields() -> None:
    token = set_metadata(
        root_family="repo-family",
        task_id="task-14",
        parent_task="parent-1",
        phase="plan",
        activity="fanout",
        revision="abc123",
        context_digest="digest-123",
        input_tokens_est=100,
        output_tokens_est=20,
        reuse_state="miss",
        cache_state="miss",
        queue_wait_ms=2.0,
        bypass_reason="",
    )
    try:
        value = current()
        assert value["request_id"] == ""
        assert value["trace_id"] == ""
        assert value["token_efficiency"]["task_id"] == "task-14"
        assert value["token_efficiency"]["input_tokens_est"] == 100
    finally:
        reset_metadata(token)


def test_replay_fixture_reports_raw_reused_generated_and_avoided_separately() -> None:
    for case in _cases():
        result = replay_accounting(
            raw_input_tokens_est=case["raw_input_tokens_est"],
            reused_input_tokens_est=case["reused_input_tokens_est"],
            generated_output_tokens_est=case["generated_output_tokens_est"],
            output_tokens_est=case["output_tokens_est"],
            reuse_state=case["reuse_state"],
            cache_state=case["cache_state"],
            fanout_count=case["fanout_count"],
        )
        assert result["raw_input_tokens_est"] == case["raw_input_tokens_est"]
        assert result["reused_input_tokens_est"] == case["reused_input_tokens_est"]
        assert result["generated_output_tokens_est"] == case["generated_output_tokens_est"]
        assert result["avoided_payload_tokens_est"] == case["expected_avoided_payload_tokens_est"]


def test_reuse_only_response_is_bounded_pointer_for_duplicate_context() -> None:
    payload = {
        "success": True,
        "context_id": "ctx-1",
        "repo_revision": "abc123",
        "summary": "unchanged evidence",
        "text": "evidence " * 800,
        "evidence": [{"id": str(index), "text": "detail " * 100} for index in range(20)],
    }

    full = budget_response(payload, max_tokens=260, profile="compact", reuse_key="replay:ctx")
    pointer = budget_response(
        payload,
        max_tokens=260,
        profile="compact",
        reuse_key="replay:ctx",
        reuse_only=True,
        token_metadata={"reused_input_tokens_est": json_tokens(payload)},
    )

    assert json_tokens(full) <= 300
    assert json_tokens(pointer) <= 300
    assert pointer["reused"] is True
    assert pointer["reuse_key"] == "replay:ctx"
    assert "evidence" not in pointer
    assert pointer["token_efficiency"]["reused_input_tokens_est"] > 0


def test_finalized_accounting_carries_context_metadata_without_payload() -> None:
    token = set_metadata(
        root_family="repo-family",
        task_id="task-14",
        parent_task="parent-1",
        phase="verify",
        activity="compact_handoff",
        revision="abc123",
        context_digest="digest-123",
        queue_wait_ms="malformed",
        bypass_reason="quality_gate",
    )
    try:
        event = finalize_tool_accounting(
            tool_name="local_ai_repo",
            arguments={"action": "context", "root": "C:/repo"},
            response={"success": True, "summary": "bounded"},
            measured={"raw_input_tokens_est": 900, "reused_input_tokens_est": 700},
        )
    finally:
        reset_metadata(token)

    assert event["token_efficiency"]["root_family"] == "repo-family"
    assert event["token_efficiency"]["task_id"] == "task-14"
    assert event["token_efficiency"]["queue_wait_ms"] == 0.0
    assert event["token_efficiency"]["avoided_payload_tokens_est"] == 700
    assert "C:/repo" not in json.dumps(event)
