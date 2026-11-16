from __future__ import annotations

from types import SimpleNamespace
from local_ai_hub.pipeline import (
    _queue_laya_context_budget_shadow,
    _queue_laya_delegation_shadow,
    _queue_laya_redundant_step_shadow,
    _queue_laya_next_step_shadow,
)


def test_queue_laya_redundant_step_and_next_step_shadow():
    observed = []
    services = SimpleNamespace(
        _queue_laya_shadow_observation=lambda args, root, category, options, state, training_content, baseline: (
            observed.append((category, baseline["method"], baseline["suggestion"])) or True
        )
    )

    args = {"session_id": "sess-pipeline-1"}

    # 1. Redundant step
    ok_red = _queue_laya_redundant_step_shadow(
        services,
        args,
        root="C:/repo",
        task="Test task",
        step_name="worker_stage",
        is_duplicate=True,
        evidence_ids=["ev-1"],
    )
    assert ok_red is True
    assert observed[-1] == ("redundant_step", "command_broker_dedup", "possible_duplicate")

    # 2. Next step
    ok_nxt = _queue_laya_next_step_shadow(
        services,
        args,
        root="C:/repo",
        task="Test task",
        current_stage="pipeline_completion",
        suggestion="run_test",
        evidence_ids=["ev-1"],
    )
    assert ok_nxt is True
    assert observed[-1] == ("next_step", "pipeline_step_progress", "run_test")


def test_queue_laya_delegation_and_budget_adhoc_session():
    observed = []
    services = SimpleNamespace(
        _queue_laya_shadow_observation=lambda args, root, category, options, state, training_content, baseline: (
            observed.append((category, baseline["method"], baseline["suggestion"])) or True
        )
    )

    # Missing task_id, only session_id
    args = {"session_id": "sess-pipeline-adhoc"}

    # Session alone is insufficient for durable shadow attribution.
    assert _queue_laya_delegation_shadow(
        services, args, root="C:/repo", task="Test delegation",
        mode="adaptive", route={"task_type": "code", "complexity": "fast"},
        risk_score=10.0, plan={"worker": True}, need_worker=True,
        explorer={"success": True, "structured": {"evidence": [{"evidence_id": "ev-del-1"}]}},
        packed={"success": True, "evidence": [{"evidence_id": "ev-del-1"}]},
        response={"success": True, "text": "worker output"},
    ) is False
    assert observed == []
    args["task_id"] = "task-pipeline-adhoc"
    ok_del = _queue_laya_delegation_shadow(
        services,
        args,
        root="C:/repo",
        task="Test delegation",
        mode="adaptive",
        route={"task_type": "code", "complexity": "fast"},
        risk_score=10.0,
        plan={"worker": True},
        need_worker=True,
        explorer={"success": True, "structured": {"evidence": [{"evidence_id": "ev-del-1"}]}},
        packed={"success": True, "evidence": [{"evidence_id": "ev-del-1"}]},
        response={"success": True, "text": "worker output"},
    )
    assert ok_del is True
    assert observed[-1] == ("delegation", "pipeline_worker_escalation", "delegate_bounded")
