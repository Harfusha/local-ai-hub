import pytest

from local_ai_hub.routing import semantic_handoff_hint


EVIDENCE_ACTIONS = [
    "search",
    "code_index",
    "context",
    "deterministic",
    "symbols",
    "callers",
    "dead_code",
    "impact",
    "refactor_impact",
    "affected_tests",
    "dependency_slice",
    "structural_search",
    "ast_outline",
    "test_matrix",
    "complexity",
    "profile",
    "map",
]

EXPECTED_PAYLOAD = {
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


def test_semantic_repo_evidence_requires_local_model_handoff():
    assert semantic_handoff_hint(
        "local_ai_repo", "search", local_tasks_enabled=True
    ) == EXPECTED_PAYLOAD


@pytest.mark.parametrize("action", EVIDENCE_ACTIONS)
def test_all_semantic_repo_evidence_actions_require_handoff(action):
    assert semantic_handoff_hint(
        "local_ai_repo", action, local_tasks_enabled=True
    ) == EXPECTED_PAYLOAD


def test_disabled_local_tasks_return_none():
    assert semantic_handoff_hint(
        "local_ai_repo", "search", local_tasks_enabled=False
    ) is None


def test_status_disabled_handoff_omits_status_bypass_metadata():
    hint = semantic_handoff_hint(
        "local_ai_repo", "search", local_tasks_enabled=True, status_enabled=False
    )

    assert hint == {
        "required": True,
        "tool": "local_ai_task",
        "actions": EXPECTED_PAYLOAD["actions"],
    }
    assert "local_ai_status" not in repr(hint)


def test_non_semantic_tools_return_none():
    assert semantic_handoff_hint(
        "local_ai_artifact", "get", local_tasks_enabled=True
    ) is None
    assert semantic_handoff_hint(
        "local_ai_command", "run", local_tasks_enabled=True
    ) is None
