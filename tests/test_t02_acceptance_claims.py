from __future__ import annotations

import json
from pathlib import Path

from tools.validate_t02_acceptance_claims import validate_claims


ROOT = Path(__file__).resolve().parents[1]


def _current_evidence() -> tuple[dict[str, object], dict[str, object]]:
    manifest = json.loads((ROOT / "handoff/T02-cross-task-dataset-manifest.json").read_text(encoding="utf-8"))
    receipt = json.loads((ROOT / "handoff/T02-model-free-baseline-receipt-2026-10-01.json").read_text(encoding="utf-8"))
    return manifest, receipt


def test_current_model_free_evidence_is_accepted_as_partial() -> None:
    manifest, receipt = _current_evidence()
    assert validate_claims(manifest, receipt) == []


def test_rejects_claim_that_incomplete_matrix_is_available_or_plan_grade() -> None:
    manifest, receipt = _current_evidence()
    receipt["coverage"]["matrix_acceptance"] = "passed"
    receipt["coverage"]["plan_grade"] = True
    errors = validate_claims(manifest, receipt)
    assert "incomplete matrix must remain unavailable" in errors
    assert "incomplete matrix cannot be plan-grade" in errors


def test_rejects_case_count_that_overstates_receipt_rows() -> None:
    manifest, receipt = _current_evidence()
    receipt["coverage"]["measured_per_case"] = 6
    assert "receipt measured-case count differs from case rows" in validate_claims(manifest, receipt)


def test_rejects_per_case_evidence_promoted_to_plan_grade() -> None:
    manifest, receipt = _current_evidence()
    manifest["model_free_per_case_validation"]["plan_grade"] = True
    receipt["measured_model_free_cases"][0]["readiness"] = "plan_grade"
    errors = validate_claims(manifest, receipt)
    assert "manifest per-case evidence cannot be plan-grade" in errors
    assert "receipt cases must retain per-case readiness" in errors


def test_rejects_inference_claim_added_to_model_free_receipt() -> None:
    manifest, receipt = _current_evidence()
    receipt["measured_model_free_cases"][0]["inference"] = "completed"
    assert "every model-free case must disclose that inference was skipped" in validate_claims(manifest, receipt)
