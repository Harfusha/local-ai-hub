"""Reject completion claims that overstate explicitly supplied model-free evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def validate_claims(manifest: dict[str, object], receipt: dict[str, object]) -> list[str]:
    errors: list[str] = []
    matrix = manifest.get("t02_required_matrix")
    manifest_validation = manifest.get("model_free_per_case_validation")
    coverage = receipt.get("coverage")
    cases = receipt.get("measured_model_free_cases")
    if not isinstance(matrix, dict) or not isinstance(manifest_validation, dict):
        return ["missing T02 manifest acceptance data"]
    if not isinstance(coverage, dict) or not isinstance(cases, list):
        return ["missing model-free receipt coverage"]

    required = matrix.get("required_case_count")
    measured = len(cases)
    if matrix.get("matrix_measurement_status") != "unavailable":
        errors.append("T02 matrix must remain unavailable until its required runs exist")
    if type(required) is not int or required < 1:
        errors.append("invalid required matrix case count")
    else:
        if type(coverage.get("t02_required_cases")) is not int or coverage["t02_required_cases"] != required:
            errors.append("receipt required-case count differs from manifest")
        if type(coverage.get("measured_per_case")) is not int or coverage["measured_per_case"] != measured:
            errors.append("receipt measured-case count differs from case rows")
        if measured < required and coverage.get("matrix_acceptance") != "unavailable":
            errors.append("incomplete matrix must remain unavailable")
        if measured < required and coverage.get("plan_grade") is not False:
            errors.append("incomplete matrix cannot be plan-grade")
        if measured >= required and coverage.get("plan_grade") is not True:
            errors.append("complete case count requires explicit plan-grade evidence")

    if manifest_validation.get("status") != "partial_per_case_measurement":
        errors.append("manifest must describe the current evidence as partial per-case measurement")
    if manifest_validation.get("plan_grade") is not False:
        errors.append("manifest per-case evidence cannot be plan-grade")
    manifest_cases = manifest_validation.get("measured_cases")
    if not isinstance(manifest_cases, list) or len(manifest_cases) != measured:
        errors.append("manifest measured-case count differs from receipt")
    elif any(not isinstance(case, dict) or case.get("readiness") != "per_case" for case in manifest_cases):
        errors.append("manifest cases must retain per-case readiness")

    for case in cases:
        if not isinstance(case, dict) or case.get("readiness") != "per_case":
            errors.append("receipt cases must retain per-case readiness")
            break

    if any(not isinstance(case, dict) or case.get("inference") != "skipped_not_requested" for case in cases):
        errors.append("every model-free case must disclose that inference was skipped")
    receipt_validation = receipt.get("manifest_validation")
    if not isinstance(receipt_validation, dict) or receipt_validation.get("status") != "passed":
        errors.append("receipt manifest validation must be passed")
    return errors


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("receipt", type=Path)
    args = parser.parse_args()
    manifest = _read_json(args.manifest)
    receipt = _read_json(args.receipt)
    errors = validate_claims(manifest, receipt)
    if errors:
        print("T02 acceptance claim guard: REJECTED")
        for error in errors:
            print(f"- {error}")
        return 1
    print("T02 acceptance claim guard: PASS (partial/model-free evidence remains explicitly incomplete)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
