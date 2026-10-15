from __future__ import annotations

import math

import pytest

from local_ai_hub import agent_policy
from local_ai_hub.agent_policy import (
    ActionRequest,
    CapabilityGrant,
    PolicyEngine,
    RiskClass,
)


def _request() -> ActionRequest:
    return ActionRequest(action="write", risk_class=RiskClass.WRITE)


def _grant(expires_at: object = None, **overrides: object) -> CapabilityGrant:
    values: dict[str, object] = {
        "grant_id": "fixture",
        "allowed": frozenset({"write"}),
        "expires_at": expires_at,
    }
    values.update(overrides)
    return CapabilityGrant(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "expires_at,expected,reason",
    [
        (None, True, "action permitted by capability grant"),
        (101.0, True, "action permitted by capability grant"),
        (100.0, False, "capability grant has expired"),
        (99.0, False, "capability grant has expired"),
        (math.nan, False, "capability grant has invalid expiry"),
        (math.inf, False, "capability grant has invalid expiry"),
        (True, False, "capability grant has invalid expiry"),
        (10**400, False, "capability grant has invalid expiry"),
    ],
)
def test_grant_expiry_must_be_finite_and_future(
    monkeypatch: pytest.MonkeyPatch,
    expires_at: object,
    expected: bool,
    reason: str,
) -> None:
    monkeypatch.setattr(agent_policy.time, "time", lambda: 100.0)
    decision = PolicyEngine().authorize(_request(), None, _grant(expires_at))
    assert decision.allowed is expected
    assert decision.reason == reason


def test_explicit_deny_is_preserved_even_when_grant_is_expired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_policy.time, "time", lambda: 100.0)
    grant = _grant(99.0, denied=frozenset({"write"}))
    decision = PolicyEngine().authorize(_request(), None, grant)
    assert decision.allowed is False
    assert "explicitly denied" in decision.reason


@pytest.mark.parametrize(
    "expires_at,depth",
    [
        (99.0, 2),
        (100.0, 2),
        (math.nan, 2),
        (math.inf, 2),
        (True, 2),
        ("101", 2),
        (10**400, 2),
        (None, 0),
        (None, -1),
        (None, True),
        (None, "2"),
    ],
)
def test_expired_or_exhausted_parent_cannot_delegate_permissions(
    monkeypatch: pytest.MonkeyPatch,
    expires_at: object,
    depth: object,
) -> None:
    monkeypatch.setattr(agent_policy.time, "time", lambda: 100.0)
    parent = _grant(expires_at, max_delegation_depth=depth)
    child = PolicyEngine().delegate(parent, {"write"})
    assert child.allowed == frozenset()
    assert child.denied == frozenset({"write"})


def test_valid_parent_delegates_only_requested_allowed_and_inherits_denials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_policy.time, "time", lambda: 100.0)
    parent = _grant(
        101.0,
        allowed=frozenset({"write", "network", "secret_access"}),
        denied=frozenset({"secret_access"}),
        max_delegation_depth=2,
    )
    child = PolicyEngine().delegate(parent, {"write", "secret_access", "unknown"})
    assert child.allowed == frozenset({"write"})
    assert child.denied == frozenset({"secret_access", "unknown"})
    assert child.max_delegation_depth == 1

