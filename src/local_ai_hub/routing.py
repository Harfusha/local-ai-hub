from typing import Any, NotRequired, TypedDict


class SemanticHandoffHint(TypedDict):
    required: bool
    advisory: NotRequired[bool]
    tool: str
    actions: list[str]
    bypass_tool: NotRequired[str]
    bypass_action: NotRequired[str]
    purpose: NotRequired[str]


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


def is_evidence_action(action: str) -> bool:
    if not isinstance(action, str) or "\x00" in action:
        return False
    return action in _EVIDENCE_ACTIONS


def is_semantic_action(action: str) -> bool:
    if not isinstance(action, str) or "\x00" in action:
        return False
    return action in _SEMANTIC_ACTIONS


def list_semantic_actions() -> list[str]:
    return list(_SEMANTIC_ACTIONS)


def list_evidence_actions() -> list[str]:
    return sorted(_EVIDENCE_ACTIONS)


def targeted_semantic_handoff(tool: str, action: str, result: Any, enabled: bool) -> SemanticHandoffHint | None:
    """Offer test ideas only when a successful test-impact query produced paths."""
    if not enabled or tool != "local_ai_repo" or action not in {"affected_tests", "test_matrix"}:
        return None
    if not isinstance(result, dict) or result.get("success") is not True:
        return None
    paths = result.get("test_files")
    if not isinstance(paths, list) or not any(isinstance(path, str) and path.strip() for path in paths):
        return None
    return {"required": False, "advisory": True, "tool": "local_ai_task", "actions": ["delegate"],
            "purpose": "Suggest behavioral and boundary tests using the returned evidence; the primary agent selects and runs them."}


def semantic_handoff_hint(
    tool: str,
    action: str,
    local_tasks_enabled: bool,
    status_enabled: bool = True,
) -> SemanticHandoffHint | None:
    if not isinstance(tool, str) or not isinstance(action, str):
        return None
    if "\x00" in tool or "\x00" in action:
        return None
    if (
        not local_tasks_enabled
        or tool != "local_ai_repo"
        or action not in _EVIDENCE_ACTIONS
    ):
        return None
    hint: SemanticHandoffHint = {
        "required": False,
        "advisory": True,
        "tool": "local_ai_task",
        "actions": list(_SEMANTIC_ACTIONS),
    }
    if status_enabled:
        hint.update({"bypass_tool": "local_ai_status", "bypass_action": "bypassed"})
    return hint
