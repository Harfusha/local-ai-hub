from __future__ import annotations

from local_ai_hub.response_budget import budget_response
from local_ai_hub.token_accounting import json_tokens


def _large_result() -> dict[str, object]:
    return {
        "success": True,
        "status": "ok",
        "summary": "Decision-grade summary",
        "artifact_id": "artifact-123",
        "evidence_ids": ["E1", "E2"],
        "changed_paths": ["src/a.py"],
        "text": "line\n" * 500,
        "results": [{"path": f"src/{i}.py", "text": "detail " * 80} for i in range(40)],
        "evidence": [{"path": f"src/{i}.py", "text": "evidence " * 80} for i in range(30)],
    }


def test_budget_response_applies_aggregate_limit_and_preserves_decision_fields() -> None:
    result = budget_response(_large_result(), max_tokens=260, profile="compact")

    assert json_tokens(result) <= 300
    assert result["success"] is True
    assert result["status"] == "ok"
    assert result["summary"] == "Decision-grade summary"
    assert result["artifact_id"] == "artifact-123"
    assert result["evidence_ids"] == ["E1", "E2"]
    assert result["response_budget"]["truncated"] is True


def test_budget_response_does_not_change_small_values() -> None:
    value = {"success": True, "summary": "small", "evidence_ids": ["E1"]}

    assert budget_response(value, max_tokens=300) == value


def test_budget_response_can_return_reuse_envelope() -> None:
    result = budget_response(
        _large_result(),
        max_tokens=260,
        profile="minimal",
        reuse_key="repo:search:abc",
        reuse_only=True,
    )

    assert json_tokens(result) <= 300
    assert result["reuse_key"] == "repo:search:abc"
    assert result["reused"] is True
    assert result["artifact_id"] == "artifact-123"
    assert "results" not in result
    assert "evidence" not in result


def test_budget_response_preserves_bounded_task_context_contract() -> None:
    result = budget_response(
        {
            "success": True,
            "complete": True,
            "partial": False,
            "etag": "etag-1",
            "context_id": "taskctx-1",
            "evidence_ids": ["E1"],
            "task_context": {
                "success": True,
                "complete": True,
                "partial": False,
                "task_id": "task-1",
                "context_id": "taskctx-1",
                "etag": "etag-1",
                "text": "authoritative task facts\n" * 800,
                "source_layers": ["agent_state", "repository"],
                "next_action": "use_compiled_context",
            },
            "text": "authoritative task facts\n" * 800,
        },
        max_tokens=320,
        profile="compact",
        protected_keys=(
            "success", "complete", "partial", "task_context", "context_id", "etag",
            "evidence_ids", "next_action",
        ),
    )

    assert json_tokens(result) <= 320
    assert result["task_context"]["context_id"] == "taskctx-1"
    assert result["task_context"]["etag"] == "etag-1"
    assert result["evidence_ids"] == ["E1"]


def test_budget_response_keeps_guarded_repository_context_pointer() -> None:
    result = budget_response(
        {
            "success": True,
            "context": "deterministic repository facts",
            "context_pack": {"contract": {"goal": "inspect logs"}, "evidence": [{"evidence_id": "E1"}]},
            "context_id": "ctx-1",
            "evidence_ids": ["E1"],
        },
        max_tokens=220,
        profile="compact",
        protected_keys=("success", "context", "context_pack", "context_id", "evidence_ids"),
    )

    assert json_tokens(result) <= 220
    assert result["context_id"] == "ctx-1"
    assert result["context"]
    assert result["context_pack"]
