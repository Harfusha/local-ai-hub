from __future__ import annotations

import math
import pytest

from local_ai_hub.agent_routing import (
    RouteRequest,
    RoutingDecision,
    RoutingEngine,
    TestSelection,
    ToolObservation,
)
from local_ai_hub.agent_verification import ChangeIntent


def test_route_request_validation_and_helpers() -> None:
    req = RouteRequest(
        query=" search query\x00 ",
        task_type=" code_search\x00 ",
        has_fresh_cache=True,
        has_indexed_evidence=False,
        needs_semantic=False,
        needs_model=True,
        cost_limit=-10.0,
    )
    assert req.query == "search query"
    assert req.task_type == "code_search"
    assert req.cost_limit == 0.0
    assert req.is_cached() is True
    assert req.is_indexed() is False
    assert req.requires_semantic() is False
    assert req.requires_model() is True

    # NaN cost limit fallback
    req_nan = RouteRequest(cost_limit=float("nan"))  # type: ignore
    assert req_nan.cost_limit == 0.0

    # Invalid boolean/null budgets must not restore the permissive default.
    assert RouteRequest(cost_limit=True).cost_limit == 0.0  # type: ignore[arg-type]
    assert RouteRequest(cost_limit=False).cost_limit == 0.0  # type: ignore[arg-type]
    assert RouteRequest(cost_limit=None).cost_limit == 0.0  # type: ignore[arg-type]


def test_routing_decision_validation_and_helpers() -> None:
    dec = RoutingDecision(
        kind="invalid_kind",
        target=" target_worker\x00 ",
        reason=" reason text\x00 ",
        confidence=2.5,
    )
    assert dec.kind == "deterministic"
    assert dec.target == "target_worker"
    assert dec.reason == "reason text"
    assert dec.confidence == 1.0
    assert dec.is_deterministic() is True
    assert dec.is_high_confidence() is True

    # Check kind helpers
    dec_cache = RoutingDecision(kind="cache", target="cache_hit", reason="fresh")
    assert dec_cache.is_cache() is True
    assert dec_cache.is_index() is False

    dec_idx = RoutingDecision(kind="index", target="code_index", reason="indexed")
    assert dec_idx.is_index() is True

    dec_sem = RoutingDecision(kind="semantic", target="rag", reason="semantic")
    assert dec_sem.is_semantic() is True

    dec_mod = RoutingDecision(kind="local_model", target="qwen", reason="model")
    assert dec_mod.is_model() is True


def test_test_selection_invariants_and_helpers() -> None:
    ts = TestSelection(
        selected_tests=(" tests/test_a.py\x00 ", ""),
        flaky_candidates=(" tests/test_b.py::flaky\x00 ",),
        synthetic_passes=(" tests/test_fake.py ",),  # MUST be forced to ()
    )
    assert ts.selected_tests == ("tests/test_a.py",)
    assert ts.flaky_candidates == ("tests/test_b.py::flaky",)
    assert ts.synthetic_passes == ()
    assert ts.has_tests() is True
    assert ts.test_count() == 1
    assert ts.has_flakes() is True
    assert ts.flake_count() == 1

    empty_ts = TestSelection(selected_tests=())
    assert empty_ts.has_tests() is False
    assert empty_ts.test_count() == 0
    assert empty_ts.has_flakes() is False
    assert empty_ts.flake_count() == 0


def test_tool_observation_validation_and_helpers() -> None:
    obs = ToolObservation(
        tool_name=" repo_state\x00 ",
        duration_ms=-50.0,
        success=True,
        cache_hit=True,
        cost_estimate=float("nan"),  # type: ignore
    )
    assert obs.tool_name == "repo_state"
    assert obs.duration_ms == 0.0
    assert obs.cost_estimate == 0.0
    assert obs.is_cached() is True
    assert obs.is_successful() is True


def test_routing_engine_test_selection_and_flake_management() -> None:
    engine = RoutingEngine()

    # Flake management
    assert engine.flake_count() == 0
    assert engine.known_flakes() == ()
    assert engine.is_flake("tests/test_net.py") is False

    engine.mark_flake(" tests/test_net.py::test_timeout\x00 ")
    assert engine.flake_count() == 1
    assert engine.is_flake("tests/test_net.py::test_timeout") is True
    assert engine.known_flakes() == ("tests/test_net.py::test_timeout",)

    # Empty mark ignored
    engine.mark_flake(" \x00 ")
    assert engine.flake_count() == 1

    # Unmark flake
    engine.unmark_flake("tests/test_net.py::test_timeout")
    assert engine.flake_count() == 0
    assert engine.is_flake("tests/test_net.py::test_timeout") is False

    # Clear flakes
    engine.mark_flake("flake1")
    engine.mark_flake("flake2")
    assert engine.flake_count() == 2
    engine.clear_flakes()
    assert engine.flake_count() == 0

    # Test selection bug test: when test file is affected, do not generate test_test_*.py
    change_test_file = ChangeIntent.create(
        task_id="t1",
        affected_paths=["tests/unit/test_network.py"],
        expected_impact="unit test update",
    )
    selection = engine.select_tests(change_test_file)
    assert selection.selected_tests == ("tests/unit/test_network.py",)

    # When source file is affected, map to tests/test_<module>.py
    change_src_file = ChangeIntent.create(
        task_id="t2",
        affected_paths=["src/local_ai_hub/network.py"],
        expected_impact="fix timeout",
    )
    selection_src = engine.select_tests(change_src_file)
    assert selection_src.selected_tests == ("tests/test_network.py",)

    # Observations count
    assert engine.observations_count() == 0
    engine.record_observation(
        ToolObservation(tool_name="test_tool", duration_ms=10.0, success=True)
    )
    assert engine.observations_count() == 1
