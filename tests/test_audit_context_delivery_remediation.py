from __future__ import annotations

import pytest


def project(payload, budget=3200):
    import local_ai_hub.mcp_server as module
    token = module._CURRENT_RESPONSE_OPTIONS.set({"tool": "local_ai_repo", "action": "context",
        "max_response_tokens": budget, "response_profile": "compact"})
    try:
        return module._context_pack_projection(payload)
    finally:
        module._CURRENT_RESPONSE_OPTIONS.reset(token)


def test_large_context_has_an_exact_artifact_recovery_path_without_false_completeness():
    result = project({"success": True, "guarded": True, "context_id": "repository-context",
        "task_context_artifact_id": "fixture-full-context",
        "task_context": {"success": True, "complete": True, "partial": False,
            "task_id": "task", "context_id": "compiled-context", "etag": "version",
            "artifact_id": "fixture-full-context", "text": "task evidence scope identity\n" * 800}})
    assert result.get("error") != "max_response_tokens too small"
    assert result["task_context_artifact_id"] == "fixture-full-context"
    assert result["next_action"] == "read_task_context_artifact"
    assert result["success"] is False and result["complete"] is False
    assert result["task_context"]["complete"] is False
    assert result["task_context"]["partial"] is True


@pytest.mark.parametrize("context", [
    {"success": "true", "complete": True, "text": "invalid"},
    {"success": True, "complete": 1, "text": "invalid"},
    {"success": True, "complete": True},
])
def test_compiled_context_requires_exact_flags_and_nested_text(context):
    result = project({"success": True, "guarded": True, "text": "top-level substitute", "task_context": context})
    assert result["success"] is False
    assert result["complete"] is False
    assert result["task_context"]["success"] is False


def test_small_valid_compiled_context_keeps_exact_text_and_success():
    context = {"success": True, "complete": True, "text": "Exact useful compiled context.",
               "task_id": "task", "context_id": "compiled-context"}
    result = project({"success": True, "guarded": True, "task_context": context})
    assert result["success"] is True
    assert result["task_context"]["text"] == context["text"]
    assert result["task_context"]["complete"] is True
