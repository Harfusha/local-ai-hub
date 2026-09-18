from __future__ import annotations


def test_semantic_request_keeps_one_local_explorer_even_with_strong_evidence():
    from local_ai_hub.planner import AdaptivePlanner

    planner = AdaptivePlanner({"execution_planner": {"direct_confidence": 0.90}})
    plan = planner.plan(
        {"task_type": "reasoning", "complexity": "fast", "complexity_score": 0, "semantic_required": True},
        risk=0,
        graph={"confidence": 0.99},
        evidence_count=0,
        mode="adaptive",
    )

    assert plan["explorer"] is True
    assert plan["worker"] is False
    assert plan["critic"] is False
    assert plan["reason"] == "semantic-request"


def test_fast_mode_still_runs_local_explorer_for_semantic_request():
    from local_ai_hub.planner import AdaptivePlanner

    planner = AdaptivePlanner({"execution_planner": {}})
    plan = planner.plan(
        {"task_type": "general", "complexity": "fast", "complexity_score": 0, "semantic_required": True},
        risk=0,
        graph={"confidence": 0.99},
        evidence_count=0,
        mode="fast",
    )

    assert plan["explorer"] is True
    assert plan["worker"] is False
    assert plan["reason"] == "semantic-request"
