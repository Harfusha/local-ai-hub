from local_ai_hub.agent_context import CompiledContext, ContextElement, ContextRequest
from local_ai_hub.task_context import build_context_request, compose_task_context


def _compiled() -> CompiledContext:
    return CompiledContext(
        elements=[
            ContextElement(
                element_id="goal-1",
                source_kind="task_goal",
                content="Task Goal: harden context",
                estimated_tokens=5,
                reason="task goal",
            )
        ],
        estimated_tokens=5,
        token_budget=100,
        phase="review",
        repo_revision="rev-1",
    )


def test_build_context_request_forwards_task_scope_fields():
    request = build_context_request(
        {
            "task_id": "task-1",
            "root": "repo",
            "token_budget": 100,
            "phase": "review",
            "focus": ["context endpoint"],
            "preload_profile": "review",
            "repository_revision": "rev-1",
            "since_hash": "etag-1",
            "changed_paths": ["src/a.py"],
        },
        tenant="agent-a",
    )
    assert request == ContextRequest(
        task_id="task-1",
        token_budget=100,
        root="repo",
        tenant="agent-a",
        phase="review",
        focus=("context endpoint",),
        preload_profile="review",
        repository_revision="rev-1",
        repo_revision="rev-1",
        since_hash="etag-1",
        changed_paths=("src/a.py",),
    )


def test_compose_task_context_contains_agent_and_repository_layers():
    result = compose_task_context(
        task_id="task-1",
        compiled=_compiled(),
        repository={
            "success": True,
            "context": "Indexed evidence: src/a.py:10",
            "repo_revision": "rev-1",
            "evidence_ids": ["E1"],
            "adaptive_context_pack": {"context_id": "repo-ctx"},
        },
        token_budget=100,
    )
    assert result["success"] is True
    assert result["complete"] is True
    assert result["source_layers"] == ["agent_state", "repository"]
    assert "Task Goal: harden context" in result["text"]
    assert "Indexed evidence: src/a.py:10" in result["text"]
    assert result["evidence_ids"] == ["E1"]
    assert result["context_id"]


def test_compose_task_context_never_claims_complete_with_failed_repository_layer():
    result = compose_task_context(
        task_id="task-1",
        compiled=_compiled(),
        repository={"success": False, "error": "index unavailable", "retryable": True},
        token_budget=100,
    )
    assert result["success"] is False
    assert result["complete"] is False
    assert result["partial"] is True
    assert result["repository"]["error"] == "index unavailable"


def test_compose_task_context_rejects_revision_mismatch():
    compiled = CompiledContext(
        elements=[], estimated_tokens=0, token_budget=100, repo_revision="expected"
    )
    result = compose_task_context(
        task_id="task-1",
        compiled=compiled,
        repository={"success": True, "context": "stale index", "repo_revision": "actual"},
        token_budget=100,
    )
    assert result["complete"] is False
    assert result["stale"] is True
    assert any(item["code"] == "repository_revision_mismatch" for item in result["warnings"])
