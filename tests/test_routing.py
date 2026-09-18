from local_ai_hub.routing import semantic_handoff_hint


def test_semantic_repo_evidence_requires_local_model_handoff():
    assert semantic_handoff_hint("local_ai_repo", "search", True) == {
        "required": True,
        "tool": "local_ai_task",
        "actions": [
            "delegate",
            "explore",
            "reason",
            "review",
            "second_opinion",
            "compress",
        ],
        "bypass_tool": "local_ai_status",
        "bypass_action": "bypassed",
    }


def test_disabled_local_tasks_return_none():
    assert semantic_handoff_hint("local_ai_repo", "search", False) is None


def test_non_semantic_tools_return_none():
    assert semantic_handoff_hint("local_ai_artifact", "get", True) is None
    assert semantic_handoff_hint("local_ai_command", "run", True) is None
