"""Malformed confidence must not manufacture a fully confident decision."""
import pytest

from local_ai_hub.agent_routing import RoutingDecision


@pytest.mark.parametrize("value", [True, False, None])
def test_malformed_confidence_has_no_positive_confidence(value):
    decision = RoutingDecision("deterministic", "builtin", "structured route", confidence=value)
    assert decision.confidence == 0.0


@pytest.mark.parametrize("value", [0.0, 0.5, 1.0])
def test_valid_numeric_confidence_is_preserved(value):
    decision = RoutingDecision("deterministic", "builtin", "structured route", confidence=value)
    assert decision.confidence == value


def test_omitted_confidence_retains_declared_default():
    assert RoutingDecision("deterministic", "builtin", "structured route").confidence == 1.0
