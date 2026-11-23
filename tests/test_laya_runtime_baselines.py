from __future__ import annotations

import pytest
from local_ai_hub.laya_decisions import DecisionCategory
from local_ai_hub.laya_candidates import _RUNTIME_BASELINE_METHODS
from local_ai_hub.services import LocalAIServices


def test_runtime_baseline_methods_mapping():
    expected = {
        DecisionCategory.MODEL_ROUTE: "model_router_classify",
        DecisionCategory.CONTEXT_BUDGET: "repo_context_token_budget",
        DecisionCategory.DELEGATION: "pipeline_worker_escalation",
        DecisionCategory.COMPLETION_GAP: "agent_os_completion_gate",
        DecisionCategory.WATCHDOG: "agent_os_task_lifecycle",
        DecisionCategory.REDUNDANT_STEP: "command_broker_dedup",
        DecisionCategory.NEXT_STEP: "pipeline_step_progress",
    }
    for category, method in expected.items():
        assert _RUNTIME_BASELINE_METHODS.get(category) == method


def test_services_queue_shadow_observation_runtime_baselines():
    service = LocalAIServices.__new__(LocalAIServices)
    observed = []
    service.laya_decision_observer = lambda op, root, baseline: (
        observed.append((op, root, baseline)) or {"status": "queued"}
    )

    # 1. Redundant step with command_broker_dedup
    ok = service._queue_laya_shadow_observation(
        {"task_id": "task-s1", "session_id": "s1"},
        root="C:/repo",
        category="redundant_step",
        options=["possible_duplicate", "validation_still_required"],
        state={"command": "pytest", "seen_before": "true"},
        training_content={"tool_output_excerpt": "pytest output"},
        baseline={
            "method": "command_broker_dedup",
            "suggestion": "possible_duplicate",
            "evidence_id": "ev-cmd-1",
        },
    )
    assert ok is True
    assert len(observed) == 1
    assert observed[0][0]["decision"]["category"] == "redundant_step"

    # Mismatched method for redundant step should be rejected
    bad = service._queue_laya_shadow_observation(
        {"task_id": "task-s1", "session_id": "s1"},
        root="C:/repo",
        category="redundant_step",
        options=["possible_duplicate", "validation_still_required"],
        state={"command": "pytest", "seen_before": "true"},
        training_content={"tool_output_excerpt": "pytest output"},
        baseline={
            "method": "invalid_method",
            "suggestion": "possible_duplicate",
            "evidence_id": "ev-cmd-1",
        },
    )
    assert bad is False

    # 2. Next step with pipeline_step_progress
    ok2 = service._queue_laya_shadow_observation(
        {"task_id": "task-s2", "session_id": "s2"},
        root="C:/repo",
        category="next_step",
        options=["inspect_source", "run_test", "retrieve_evidence", "ask_human"],
        state={"current_stage": "implementation"},
        training_content={"task_input": "Implement feature"},
        baseline={
            "method": "pipeline_step_progress",
            "suggestion": "run_test",
            "evidence_id": "ev-pipe-1",
        },
    )
    assert ok2 is True
    assert len(observed) == 2
    assert observed[1][0]["decision"]["category"] == "next_step"
