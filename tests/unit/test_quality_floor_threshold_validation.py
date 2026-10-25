"""Invalid custom thresholds cannot bypass the quality gate, even for best metrics."""
import pytest

from local_ai_hub import model_quality


@pytest.mark.parametrize("key,value", [("accuracy", 1.0), ("false_positive_rate", 0.0)])
@pytest.mark.parametrize("threshold", [float("nan"), float("inf"), float("-inf"), True, False, None, "0.5"])
def test_invalid_threshold_fails_closed(key, value, threshold):
    assert model_quality.quality_floor_failures({key: value}, {key: threshold}) == [key]


@pytest.mark.parametrize("key,value,threshold,failures", [
    ("accuracy", 0.5, 0.5, []),
    ("accuracy", 0.49, 0.5, ["accuracy"]),
    ("false_positive_rate", 0.5, 0.5, []),
    ("false_positive_rate", 0.51, 0.5, ["false_positive_rate"]),
    ("accuracy", 0.0, 0.0, []),
    ("false_positive_rate", 0.0, 0.0, []),
    ("accuracy", 1.0, 1, []),
])
def test_valid_threshold_preserves_boundary_and_direction(key, value, threshold, failures):
    assert model_quality.quality_floor_failures({key: value}, {key: threshold}) == failures


@pytest.mark.parametrize("key,value", [("accuracy", 1.0), ("false_positive_rate", 0.0)])
def test_invalid_floor_rejects_promotion_before_receipt_gate(monkeypatch, key, value):
    def unexpected_receipt_check(_receipt):
        pytest.fail("invalid floor must reject before evaluating any receipt")

    monkeypatch.setattr(model_quality, "_reproducible_receipt", unexpected_receipt_check)
    result = model_quality.promote_candidate({"metrics": {key: value}}, quality_floor={key: float("nan")})
    assert result["status"] == model_quality.REJECTED
    assert result["reason"] == "quality_floor_not_met"
    assert result["failed_metrics"] == [key]


def test_custom_floor_validation_preserves_default_floor():
    before = dict(model_quality.DEFAULT_QUALITY_FLOOR)
    assert model_quality.quality_floor_failures(dict(before)) == []
    assert model_quality.quality_floor_failures(dict(before), {}) == []
    assert model_quality.quality_floor_failures({"accuracy": 1.0}, {"accuracy": float("nan")}) == ["accuracy"]
    assert model_quality.DEFAULT_QUALITY_FLOOR == before
