from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace
import pytest

from local_ai_hub.planner import AdaptivePlanner
from local_ai_hub import project_policy_adapter


def test_adaptive_planner_init_with_invalid_configs():
    # None or non-dict config
    p1 = AdaptivePlanner(None)  # type: ignore
    assert p1.is_enabled() is True
    assert p1.direct_confidence == 0.93
    assert p1.worker_below == 0.78
    assert p1.critic_below == 0.68
    assert p1.critic_risk_score == 4

    p2 = AdaptivePlanner("not_a_dict")  # type: ignore
    assert p2.is_enabled() is True

    # Malformed execution_planner value
    p3 = AdaptivePlanner({"execution_planner": "invalid"})
    assert p3.is_enabled() is True

    # NaN / Inf / bool values in execution_planner
    p4 = AdaptivePlanner({
        "execution_planner": {
            "enabled": False,
            "direct_confidence": float("nan"),
            "worker_below_confidence": float("inf"),
            "critic_below_confidence": True,
            "critic_risk_score": float("nan"),
            "graph_weight": -1.0,
            "evidence_weight_per_item": float("inf"),
            "max_evidence_confidence": False,
        }
    })
    assert p4.is_enabled() is False
    assert math.isfinite(p4.direct_confidence)
    assert 0.0 <= p4.direct_confidence <= 1.0
    assert math.isfinite(p4.worker_below)
    assert 0.0 <= p4.worker_below <= 1.0
    assert math.isfinite(p4.critic_below)
    assert p4.critic_risk_score == 4


def test_adaptive_planner_confidence_edge_cases():
    planner = AdaptivePlanner({})
    # Graph is None or not dict
    conf, comp = planner._confidence(None, 0)
    assert conf == 0.0
    assert comp["graph"] == 0.0
    assert comp["evidence"] == 0.0

    # Graph confidence is NaN, Inf, bool, string
    conf_nan, _ = planner._confidence({"confidence": float("nan")}, 0)
    assert conf_nan == 0.0

    conf_inf, _ = planner._confidence({"confidence": float("inf")}, 0)
    assert conf_inf == 0.0

    conf_bool, _ = planner._confidence({"confidence": True}, 0)
    assert conf_bool == 0.0

    # evidence_count edge cases: bool, negative, NaN
    conf_ev_bool, comp_ev_bool = planner._confidence({"confidence": 0.5}, True)  # bool True must not count as 1
    assert comp_ev_bool["evidence"] == 0.0

    conf_ev_neg, comp_ev_neg = planner._confidence({"confidence": 0.5}, -10)
    assert comp_ev_neg["evidence"] >= 0.0


def test_adaptive_planner_plan_edge_cases():
    planner = AdaptivePlanner({})

    # Route is None or non-dict
    plan = planner.plan(None, risk=0, graph={}, evidence_count=0, mode="adaptive")
    assert "explorer" in plan
    assert "worker" in plan
    assert "critic" in plan

    # Risk is bool, NaN, or string
    plan_risk = planner.plan({}, risk=float("nan"), graph={}, evidence_count=0, mode="adaptive")
    assert isinstance(plan_risk["critic"], bool)

    # Mode normalization
    plan_mode = planner.plan({}, risk=0, graph={}, evidence_count=0, mode="  QUALITY  ")
    assert plan_mode["explorer"] is True
    assert plan_mode["worker"] is True
    assert plan_mode["critic"] is True
    assert plan_mode["reason"] == "quality-mode"

    # Helpers
    assert planner.is_heavy({"complexity": "heavy"}) is True
    assert planner.is_heavy({"complexity_score": 4}) is True
    assert planner.is_heavy({"complexity": "fast", "complexity_score": 1}) is False
    assert planner.is_heavy(None) is False

    assert planner.should_use_critic(4) is True
    assert planner.should_use_critic(1, "review") is True
    assert planner.should_use_critic(1, "general") is False


def test_project_policy_adapter_edge_cases():
    # is_available
    assert isinstance(project_policy_adapter.is_available(), bool)

    # resolve_project_context with null bytes or empty
    assert project_policy_adapter.resolve_project_context("", "") is None
    assert project_policy_adapter.resolve_project_context("root\x00bad", "state") is None
    assert project_policy_adapter.resolve_project_context("root", "state\x00bad") is None

    # phase_allowed with None context or context without settings
    assert project_policy_adapter.phase_allowed(None, "preprocess") is True
    dummy_no_settings = SimpleNamespace(foo="bar")
    assert project_policy_adapter.phase_allowed(dummy_no_settings, "preprocess") is True
    assert project_policy_adapter.phase_allowed(None, "phase\x00bad") is True
    assert project_policy_adapter.phase_allowed(dummy_no_settings, "") is True

    # custom_extension_kind
    assert project_policy_adapter.custom_extension_kind(None, "foo.py") is None
    assert project_policy_adapter.custom_extension_kind(dummy_no_settings, "foo.py") is None
    assert project_policy_adapter.custom_extension_kind(dummy_no_settings, "foo\x00.py") is None

    # path_allowed
    ok, kind = project_policy_adapter.path_allowed("root", "path", None, phase="preprocess")
    assert ok is True
    assert kind is None

    ok2, kind2 = project_policy_adapter.path_allowed("root", "path", dummy_no_settings, phase="preprocess")
    assert ok2 is True
    assert kind2 is None

    # path_allowed with null bytes
    ok3, kind3 = project_policy_adapter.path_allowed("root\x00bad", "path", None, phase="preprocess")
    assert ok3 is False

    ok4, kind4 = project_policy_adapter.path_allowed("root", "path\x00bad", None, phase="preprocess")
    assert ok4 is False

    # size_bytes edge cases
    ok5, _ = project_policy_adapter.path_allowed("root", "path", None, phase="preprocess", size_bytes=True)
    assert ok5 is True

    # may_descend
    assert project_policy_adapter.may_descend("root", "dir", None, phase="preprocess") is True
    assert project_policy_adapter.may_descend("root", "dir", None, phase="preprocess", hard_denied=True) is False
    assert project_policy_adapter.may_descend("root", "dir", dummy_no_settings, phase="preprocess") is True
    assert project_policy_adapter.may_descend("root\x00bad", "dir", None, phase="preprocess") is False
    assert project_policy_adapter.may_descend("root", "dir\x00bad", None, phase="preprocess") is False
