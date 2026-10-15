"""Deferred scalar-boundary coverage; no stores, runtime or persistent state."""

import pytest

from local_ai_hub.agent_verification import VerificationReceipt


def receipt_data():
    return {
        "receipt_id": "r1", "task_id": "t1", "criterion": "review",
        "passed": False, "observed_at": 10.0, "expires_at": 20.0,
        "evidence_id": "E-fixture",
    }


@pytest.mark.parametrize("field", ["observed_at", "expires_at"])
@pytest.mark.parametrize("value", [True, "20", float("nan"), float("inf"), -float("inf"), 10**400])
@pytest.mark.parametrize("parse", [False, True])
def test_invalid_receipt_time_rejects_without_becoming_unlimited(field, value, parse):
    data = {**receipt_data(), field: value}
    with pytest.raises(ValueError, match=field):
        if parse:
            VerificationReceipt.from_dict(data)
        else:
            VerificationReceipt(**data)


@pytest.mark.parametrize("value", [True, "1", 1.0, -1])
def test_receipt_factory_rejects_noncanonical_generation(value):
    with pytest.raises(ValueError, match="mutation_generation"):
        VerificationReceipt.create("t1", "review", passed=False, mutation_generation=value)


@pytest.mark.parametrize("value", [True, "20", float("nan"), float("inf"), 10**400])
def test_receipt_factory_rejects_invalid_expiry(value):
    with pytest.raises(ValueError, match="expires_at"):
        VerificationReceipt.create("t1", "review", passed=False, expires_at=value)


@pytest.mark.parametrize("value", [0, 1, None, "false"])
def test_constructor_and_factory_reject_nonboolean_passed(value):
    with pytest.raises(ValueError, match="passed"):
        VerificationReceipt(**{**receipt_data(), "passed": value})
    with pytest.raises(ValueError, match="passed"):
        VerificationReceipt.create("t1", "review", passed=value)


@pytest.mark.parametrize("expiry", [20, 20.5, None])
def test_valid_time_round_trip_preserves_exact_expiry(expiry):
    receipt = VerificationReceipt.from_dict({**receipt_data(), "expires_at": expiry})
    assert receipt.expires_at == expiry
    assert VerificationReceipt.from_dict(receipt.to_dict()) == receipt


def test_finite_expired_positive_receipt_remains_expired():
    receipt = VerificationReceipt.from_dict({**receipt_data(), "passed": True})
    assert receipt.is_fresh(21.0) is False
    assert receipt.is_fresh(19.0) is True
