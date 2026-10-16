from __future__ import annotations

import math
import pytest

from local_ai_hub.router import ModelRouter, review_diff_complexity
from local_ai_hub import routing


def test_review_diff_complexity_edge_cases():
    # None or non-dict args, det_diff, diff
    assert review_diff_complexity(None, None, None) == "auto"  # type: ignore
    assert review_diff_complexity({}, {}, {}) == "auto"

    # NaN / Inf / bool values in diff or risk
    res_nan = review_diff_complexity(
        {"complexity": "auto"},
        {"risk": {"score": float("nan"), "level": None}},
        {"changed_files": None, "estimated_tokens": float("inf")},  # type: ignore
    )
    assert res_nan in {"auto", "heavy"}


def test_model_router_init_with_invalid_configs():
    # None or empty config
    router = ModelRouter(None)  # type: ignore
    assert router.model_for_role("fast_code")
    assert router.is_complex_term("architecture") is True
    assert router.is_semantic_term("explore") is True

    # classify with None and null bytes
    route = router.classify(None, context="sample\x00ctx")  # type: ignore
    assert route["task_type"]
    assert route["model"]

    # apply_model_override with None route
    overridden = router.apply_model_override(None)  # type: ignore
    assert isinstance(overridden, dict)


def test_routing_semantic_handoff_hint_and_helpers():
    # None or null byte tool/action
    assert routing.semantic_handoff_hint(None, None, local_tasks_enabled=True) is None  # type: ignore
    assert routing.semantic_handoff_hint("local_ai_repo\x00", "search", local_tasks_enabled=True) is None

    # Valid hint
    hint = routing.semantic_handoff_hint("local_ai_repo", "search", local_tasks_enabled=True)
    assert hint is not None
    assert hint["tool"] == "local_ai_task"

    # Inspection helpers
    assert routing.is_evidence_action("search") is True
    assert routing.is_evidence_action("unknown_action") is False
    assert routing.is_semantic_action("explore") is True
    assert routing.is_semantic_action("unknown_action") is False

    sem_actions = routing.list_semantic_actions()
    assert "delegate" in sem_actions
    assert "explore" in sem_actions

    ev_actions = routing.list_evidence_actions()
    assert "search" in ev_actions
    assert "deterministic" in ev_actions
