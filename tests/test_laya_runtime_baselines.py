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
        DecisionCategory.SUBAGENT_BUDGET: "request_delegation_budget",
        DecisionCategory.RETRIEVAL_STRATEGY: "hybrid_context_default",
    }
    for category, method in expected.items():
        assert _RUNTIME_BASELINE_METHODS.get(category) == method
