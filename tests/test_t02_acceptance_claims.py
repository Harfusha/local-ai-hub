from __future__ import annotations

import pytest

from tools.validate_t02_acceptance_claims import validate_claims


def _partial_evidence_fixture() -> tuple[dict[str, object], dict[str, object]]:
    """Synthetic validator inputs; never evidence of current project acceptance."""
    manifest = {
        "t02_required_matrix": {
            "required_case_count": 2, "matrix_measurement_status": "unavailable",
        },
        "model_free_per_case_validation": {
            "status": "partial_per_case_measurement", "plan_grade": False,
            "measured_cases": [{"readiness": "per_case"}],
        },
    }
    receipt = {
        "coverage": {
            "t02_required_cases": 2, "measured_per_case": 1,
            "matrix_acceptance": "unavailable", "plan_grade": False,
        },
        "measured_model_free_cases": [
            {"readiness": "per_case", "inference": "skipped_not_requested"},
        ],
        "manifest_validation": {"status": "passed"},
    }
    return manifest, receipt


def test_synthetic_model_free_fixture_is_accepted_as_partial() -> None:
    manifest, receipt = _partial_evidence_fixture()
    assert validate_claims(manifest, receipt) == []


@pytest.mark.parametrize("field", ["required_case_count", "t02_required_cases", "measured_per_case"])
@pytest.mark.parametrize("invalid", [True, False, 1.0, 2.0, "1", "2"])
def test_rejects_noninteger_evidence_counts(field, invalid) -> None:
    manifest, receipt = _partial_evidence_fixture()
    if field == "required_case_count":
        manifest["t02_required_matrix"][field] = invalid
    else:
        receipt["coverage"][field] = invalid
    assert validate_claims(manifest, receipt)


def test_rejects_claim_that_incomplete_matrix_is_available_or_plan_grade() -> None:
    manifest, receipt = _partial_evidence_fixture()
    receipt["coverage"]["matrix_acceptance"] = "passed"
    receipt["coverage"]["plan_grade"] = True
    errors = validate_claims(manifest, receipt)
    assert "incomplete matrix must remain unavailable" in errors
    assert "incomplete matrix cannot be plan-grade" in errors


def test_rejects_case_count_that_overstates_receipt_rows() -> None:
    manifest, receipt = _partial_evidence_fixture()
    receipt["coverage"]["measured_per_case"] = 6
    assert "receipt measured-case count differs from case rows" in validate_claims(manifest, receipt)


def test_rejects_per_case_evidence_promoted_to_plan_grade() -> None:
    manifest, receipt = _partial_evidence_fixture()
    manifest["model_free_per_case_validation"]["plan_grade"] = True
    receipt["measured_model_free_cases"][0]["readiness"] = "plan_grade"
    errors = validate_claims(manifest, receipt)
    assert "manifest per-case evidence cannot be plan-grade" in errors
    assert "receipt cases must retain per-case readiness" in errors


def test_rejects_inference_claim_added_to_model_free_receipt() -> None:
    manifest, receipt = _partial_evidence_fixture()
    receipt["measured_model_free_cases"][0]["inference"] = "completed"
    assert "every model-free case must disclose that inference was skipped" in validate_claims(manifest, receipt)
