from typing import TypedDict


class SemanticHandoffHint(TypedDict):
    required: bool
    tool: str
    actions: list[str]
    bypass_tool: str
    bypass_action: str


_SEMANTIC_ACTIONS = (
    "delegate",
    "explore",
    "reason",
    "review",
    "second_opinion",
    "compress",
)

_EVIDENCE_ACTIONS = frozenset(
    {
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
    }
)


def semantic_handoff_hint(
    tool: str, action: str, local_tasks_enabled: bool
) -> SemanticHandoffHint | None:
    if (
        not local_tasks_enabled
        or tool != "local_ai_repo"
        or action not in _EVIDENCE_ACTIONS
    ):
        return None
    return {
        "required": True,
        "tool": "local_ai_task",
        "actions": list(_SEMANTIC_ACTIONS),
        "bypass_tool": "local_ai_status",
        "bypass_action": "bypassed",
    }
