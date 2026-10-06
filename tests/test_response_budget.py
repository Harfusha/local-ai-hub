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


def test_budget_rejection_keeps_bounded_adaptive_context_identity_and_citation() -> None:
    pack = {
        "context_id": "ctx-123",
        "repo_revision": "rev-7",
        "evidence": [
            {
                "evidence_id": "E123",
                "path": "src/main.py",
                "start_line": 4,
                "end_line": 6,
                "source": "deterministic",
                "content": "private detail " * 500,
            }
            for _ in range(12)
        ],
        "warnings": [{"code": "scope_drift", "message": "large warning " * 500} for _ in range(12)],
    }

    result = budget_response(
        {"success": True, "adaptive_context_pack": pack},
        max_tokens=128,
        protected_keys=("success", "adaptive_context_pack"),
    )

    assert json_tokens(result) <= 128
    assert result["response_budget"]["requested_tokens"] == 128
    assert result["response_budget"]["returned_tokens"] == json_tokens(result)
    bounded = result["adaptive_context_pack"]
    assert bounded["context_id"] == "ctx-123"
    assert bounded["repo_revision"] == "rev-7"
    assert bounded["evidence"][0] == {
        "evidence_id": "E123",
        "path": "src/main.py",
        "start_line": 4,
        "end_line": 6,
        "source": "deterministic",
    }
    assert "content" not in repr(bounded)


def test_budget_rejection_keeps_bounded_legacy_context_pack_citation() -> None:
    result = budget_response(
        {
            "success": True,
            "context_pack": {
                "context_id": "legacy-ctx",
                "repo_revision": "rev-8",
                "evidence": [
                    {
                        "evidence_id": "E8",
                        "path": "src/legacy.py",
                        "start_line": 8,
                        "end_line": 9,
                        "source": "deterministic",
                        "content": "private detail " * 500,
                    }
                    for _ in range(10)
                ],
            },
        },
        max_tokens=128,
        protected_keys=("success", "context_pack"),
    )

    assert json_tokens(result) <= 128
    assert result["response_budget"]["requested_tokens"] == 128
    assert result["response_budget"]["returned_tokens"] == json_tokens(result)
    assert result["context_pack"]["context_id"] == "legacy-ctx"
    assert result["context_pack"]["evidence"][0] == {
        "evidence_id": "E8",
        "path": "src/legacy.py",
        "start_line": 8,
        "end_line": 9,
        "source": "deterministic",
    }
    assert "content" not in repr(result["context_pack"])

def test_budget_rejection_uses_first_complete_citation() -> None:
    result = budget_response(
        {
            "success": True,
            "adaptive_context_pack": {
                "context_id": "ctx-123",
                "repo_revision": "rev-7",
                "evidence": [
                    {"evidence_id": "E-incomplete"},
                    {
                        "evidence_id": "E-complete",
                        "path": "src/later.py",
                        "start_line": 20,
                        "end_line": 24,
                        "source": "deterministic",
                        "content": "private detail " * 500,
                    },
                ],
            },
        },
        max_tokens=128,
        protected_keys=("success", "adaptive_context_pack"),
    )

    assert json_tokens(result) <= 128
    assert result["response_budget"]["original_tokens"] > 128
    assert result["adaptive_context_pack"]["evidence"][0] == {
        "evidence_id": "E-complete",
        "path": "src/later.py",
        "start_line": 20,
        "end_line": 24,
        "source": "deterministic",
    }


def test_budget_rejection_uses_later_complete_legacy_citation() -> None:
    result = budget_response(
        {
            "success": True,
            "context_pack": {
                "context_id": "legacy-ctx",
                "repo_revision": "rev-legacy",
                "evidence": [
                    {"evidence_id": "E-incomplete"},
                    {
                        "evidence_id": "E-legacy-complete",
                        "path": "src/legacy-later.py",
                        "start_line": 30,
                        "end_line": 35,
                        "source": "deterministic",
                        "content": "private detail " * 500,
                    },
                ],
            },
        },
        max_tokens=220,
        protected_keys=("success", "context_pack"),
    )

    assert json_tokens(result) <= 220
    assert result["response_budget"]["original_tokens"] > 220
    assert result["context_pack"]["evidence"][0] == {
        "evidence_id": "E-legacy-complete",
        "path": "src/legacy-later.py",
        "start_line": 30,
        "end_line": 35,
        "source": "deterministic",
    }


def test_budget_rejection_preserves_bounded_error_and_retryability() -> None:
    result = budget_response(
        {
            "success": False,
            "status_code": 503,
            "terminal": True,
            "retryable": True,
            "error": "context backend unavailable",
            "adaptive_context_pack": {
                "context_id": "ctx-error",
                "repo_revision": "rev-error",
                "evidence": [{
                    "evidence_id": "E-error",
                    "path": "src/context.py",
                    "start_line": 7,
                    "end_line": 9,
                    "source": "deterministic",
                    "content": "private backend detail " * 500,
                }],
            },
        },
        max_tokens=128,
        protected_keys=("success", "status_code", "terminal", "retryable", "error", "adaptive_context_pack"),
    )

    assert json_tokens(result) <= 128
    assert result["success"] is False
    assert result["status_code"] == 503
    assert result["terminal"] is True
    assert result["retryable"] is True
    assert result["error"] == "context backend unavailable"
    assert result["adaptive_context_pack"]["context_id"] == "ctx-error"
    assert "content" not in repr(result["adaptive_context_pack"])
