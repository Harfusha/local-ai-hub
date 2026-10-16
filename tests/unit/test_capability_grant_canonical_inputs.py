from __future__ import annotations

import math

import pytest

from local_ai_hub import agent_policy
from local_ai_hub.agent_policy import ActionRequest, CapabilityGrant, PolicyEngine, RiskClass


@pytest.mark.parametrize("field", ["grant_id", "task_id"])
@pytest.mark.parametrize("value", [" spaced ", "bad\x00identity"])
def test_identity_must_be_canonical_without_sanitization(field, value):
    with pytest.raises(ValueError, match=field):
        CapabilityGrant.from_dict({"grant_id": "grant-1", field: value})


@pytest.mark.parametrize("field", ["allowed", "denied"])
@pytest.mark.parametrize("value", [[], {}, ["write"], 1, None])
def test_array_entries_reject_before_freezing_or_hashing(field, value):
    with pytest.raises(ValueError, match="entries must be strings"):
        CapabilityGrant.from_dict({"grant_id": "grant-1", field: [value]})


def test_canonical_json_round_trip_preserves_grant_identity_and_authority() -> None:
    raw = {
        "grant_id": "grant-1",
        "task_id": "task-1",
        "allowed": ["write", "read"],
        "denied": ["network"],
        "expires_at": 123.5,
        "max_delegation_depth": 2,
    }

    grant = CapabilityGrant.from_dict(raw)

    assert grant.grant_id == "grant-1"
    assert grant.task_id == "task-1"
    assert grant.allowed == frozenset({"write", "read"})
    assert grant.denied == frozenset({"network"})
    assert grant.expires_at == 123.5
    assert grant.max_delegation_depth == 2
    assert CapabilityGrant.from_dict(grant.to_dict()) == grant


@pytest.mark.parametrize(
    "raw",
    [
        {},
        {"grant_id": None},
        {"grant_id": "  "},
        {"grant_id": "g", "task_id": None},
        {"grant_id": "g", "allowed": None},
        {"grant_id": "g", "allowed": "write"},
        {"grant_id": "g", "allowed": {"write": True}},
        {"grant_id": "g", "allowed": [None]},
        {"grant_id": "g", "allowed": [" write"]},
        {"grant_id": "g", "denied": ["write\x00"]},
        {"grant_id": "g", "expires_at": "123"},
        {"grant_id": "g", "expires_at": True},
        {"grant_id": "g", "expires_at": math.nan},
        {"grant_id": "g", "expires_at": math.inf},
        {"grant_id": "g", "expires_at": 10**400},
        {"grant_id": "g", "max_delegation_depth": True},
        {"grant_id": "g", "max_delegation_depth": "2"},
        {"grant_id": "g", "max_delegation_depth": -1},
    ],
)
def test_from_dict_rejects_noncanonical_or_invalid_authority(raw: object) -> None:
    with pytest.raises(ValueError):
        CapabilityGrant.from_dict(raw)  # type: ignore[arg-type]


def test_string_denied_cannot_be_interpreted_as_characters_or_mask_write() -> None:
    with pytest.raises(ValueError):
        CapabilityGrant.from_dict({"grant_id": "g", "denied": "write"})

    grant = CapabilityGrant.from_dict({"grant_id": "g", "allowed": ["write"]})
    decision = PolicyEngine().authorize(
        ActionRequest(action="write", risk_class=RiskClass.WRITE), None, grant,
    )
    assert decision.allowed is True


def test_explicit_canonical_deny_overrides_allow() -> None:
    grant = CapabilityGrant.from_dict({
        "grant_id": "g", "allowed": ["write"], "denied": ["write"],
    })
    decision = PolicyEngine().authorize(
        ActionRequest(action="write", risk_class=RiskClass.WRITE), None, grant,
    )
    assert decision.allowed is False
    assert "explicitly denied" in decision.reason


def test_direct_constructor_rejects_mutable_capability_sets() -> None:
    with pytest.raises(ValueError):
        CapabilityGrant(grant_id="g", allowed={"write"})  # type: ignore[arg-type]


def test_expired_grant_remains_expired_after_canonical_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agent_policy.time, "time", lambda: 100.0)
    grant = CapabilityGrant.from_dict({
        "grant_id": "expired",
        "allowed": ["write"],
        "expires_at": 99.0,
    })

    decision = PolicyEngine().authorize(
        ActionRequest(action="write", risk_class=RiskClass.WRITE), None, grant,
    )

    assert decision.allowed is False
    assert "has expired" in decision.reason
