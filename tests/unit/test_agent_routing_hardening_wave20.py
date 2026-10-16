import pytest
from local_ai_hub.agent_routing import RouteRequest, RoutingDecision, TestSelection, ToolObservation


def test_route_request_and_decision_hardening():
    req = RouteRequest(cost_limit=True)
    assert req.cost_limit == 1.0

    req_inf = RouteRequest(cost_limit=float("inf"))
    assert req_inf.cost_limit == 0.0

    dec = RoutingDecision(kind="cache", target="t1", reason="r1", confidence=True)
    assert dec.confidence == 1.0

    dec_inf = RoutingDecision(kind="cache", target="t1", reason="r1", confidence=float("inf"))
    assert dec_inf.confidence == 0.0


def test_test_selection_and_tool_observation_hardening():
    ts = TestSelection(
        selected_tests=[True, False, None, "test_one.py", "test_two\x00.py"],
        flaky_candidates=True,
    )
    assert True not in ts.selected_tests
    assert "True" not in ts.selected_tests
    assert ts.selected_tests == ("test_one.py", "test_two.py")
    assert ts.flaky_candidates == ()

    obs = ToolObservation(
        tool_name="test_tool",
        duration_ms=True,
        success=True,
        cost_estimate=float("inf"),
    )
    assert obs.duration_ms == 0.0
    assert obs.cost_estimate == 0.0
