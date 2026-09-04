from __future__ import annotations

import pytest

from local_ai_hub.agent_routing import (
    RouteRequest,
    RoutingDecision,
    RoutingEngine,
    TestSelection,
    ToolObservation,
)
from local_ai_hub.agent_verification import ChangeIntent


@pytest.fixture
def engine() -> RoutingEngine:
    return RoutingEngine()


def route_request(with_fresh_cache: bool = False) -> RouteRequest:
    return RouteRequest(
        query="find symbol Foo",
        has_fresh_cache=with_fresh_cache,
    )


def change_with_flaky_test() -> ChangeIntent:
    return ChangeIntent.create(
        task_id="task-1",
        affected_paths=["src/network.py"],
        expected_impact="update network timeout",
    )


def test_router_uses_cached_evidence_before_model_candidate(engine: RoutingEngine):
    decision = engine.select(route_request(with_fresh_cache=True))
    assert decision.kind == "cache"


def test_router_escalation_hierarchy(engine: RoutingEngine):
    # Index before semantic
    req_index = RouteRequest(query="symbol", has_indexed_evidence=True)
    assert engine.select(req_index).kind == "index"

    # Semantic before local model
    req_sem = RouteRequest(query="symbol", needs_semantic=True)
    assert engine.select(req_sem).kind == "semantic"

    # Local model
    req_model = RouteRequest(query="reasoning", needs_model=True)
    assert engine.select(req_model).kind == "local_model"


def test_known_flake_is_reported_but_not_converted_to_pass(engine: RoutingEngine):
    engine.mark_flake("tests/test_network.py::test_retry")
    selection = engine.select_tests(change_with_flaky_test())
    assert selection.flaky_candidates == ("tests/test_network.py::test_retry",)
    assert selection.synthetic_passes == ()
