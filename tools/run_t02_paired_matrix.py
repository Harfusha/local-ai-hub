"""Prepare and run the existing T02 six-case matrix as a pinned pair.

The default ``prepare`` path is read-only and never launches the benchmark.
The ``run`` path fails closed until T20 provides two source pins and a CPU slot.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any


CASE_KEYS = frozenset({
    (100, 10_000), (100, 100_000),
    (10_000, 10_000), (10_000, 100_000),
    (100_000, 10_000), (100_000, 100_000),
})
DEFERRED_CASE_KEYS = frozenset({
    (100, 100_000), (10_000, 100_000),
    (100_000, 10_000), (100_000, 100_000),
})
REQUIRED_GOLDEN_OPERATIONS = (
    "symbols", "graph", "affected_tests", "retrieval_relevance",
    "code_generation", "vision", "speech", "context_pack",
)
RETRIEVAL_METRICS = (
    "recall_at_10", "ndcg_at_10", "file_line_evidence_accuracy",
)
RETRIEVAL_MINIMUMS = {
    "recall_at_10": 0.9,
    "ndcg_at_10": 0.8,
    "file_line_evidence_accuracy": 1.0,
}
MODEL_GATES = ("output_schema_pass", "test_pass", "evidence_grounded")
REGRESSION_TOLERANCE_PCT = 10.0
INPUT_GENERATOR_VERSION = 1
REQUIRED_INPUT_SEED = 42
SOURCE_PIN_PATHS = (
    "src/local_ai_hub/commands.py",
    "tests/test_surface_benchmarks.py",
    "tools/benchmark_surfaces.py",
)


class PreparationRequired(RuntimeError):
    """Raised when immutable pins or explicit slot assignment are missing."""


def validate_manifest(manifest: Any) -> list[str]:
    if not isinstance(manifest, dict):
        return ["manifest_must_be_object"]
    reasons: list[str] = []
    if manifest.get("schema_version") != 1:
        reasons.append("unsupported_manifest_schema")
    cases = manifest.get("cases")
    if not isinstance(cases, list):
        reasons.append("cases_must_be_list")
        cases = []
    case_map: dict[tuple[int, int], dict[str, Any]] = {}
    for case in cases:
        if not isinstance(case, dict):
            reasons.append("case_must_be_object")
            continue
        try:
            key = (int(case["file_count"]), int(case["rag_chunk_count"]))
        except (KeyError, TypeError, ValueError):
            reasons.append("case_size_invalid")
            continue
        if key in case_map:
            reasons.append("case_size_duplicate")
        case_map[key] = case
        if case.get("status") not in {"historical_unpaired", "deferred"}:
            reasons.append(f"case_status_invalid:{key[0]}:{key[1]}")
    if set(case_map) != CASE_KEYS:
        reasons.append("case_set_must_match_existing_six_case_flow")
    deferred = {key for key, case in case_map.items() if case.get("status") == "deferred"}
    if deferred != DEFERRED_CASE_KEYS:
        reasons.append("deferred_case_set_mismatch")
    parameters = manifest.get("run_parameters")
    if parameters != {
        "light_repetitions": 1_000,
        "comparison_repetitions": 30,
        "concurrency": [1, 4, 16, 32],
        "timeout_seconds": 3_600,
    }:
        reasons.append("run_parameters_mismatch")
    generator = manifest.get("input_generator")
    if (
        not isinstance(generator, dict)
        or generator.get("name") != "synthetic_repo_generator"
        or generator.get("version") != INPUT_GENERATOR_VERSION
        or generator.get("seed") != REQUIRED_INPUT_SEED
        or generator.get("same_generator_version_seed_required") is not True
        or generator.get("input_fingerprint_required") is not True
    ):
        reasons.append("input_generator_seed_mismatch")
    pins = manifest.get("source_pins")
    if not isinstance(pins, dict) or set(pins) != {"baseline", "candidate"}:
        reasons.append("source_pins_malformed")
    limits = manifest.get("acceptance_limits")
    if not isinstance(limits, dict) or limits.get("max_p95_regression_pct") != 10.0 or limits.get("max_p99_regression_pct") != 10.0:
        reasons.append("regression_limits_mismatch")
    quality = manifest.get("quality_gates")
    if not isinstance(quality, dict) or quality.get("retrieval_minimums") != RETRIEVAL_MINIMUMS:
        reasons.append("retrieval_quality_minimums_mismatch")
    if not isinstance(quality, dict) or quality.get("critical_false_success_count_max") != 0:
        reasons.append("critical_false_success_limit_mismatch")
    if not isinstance(quality, dict) or quality.get("golden_operations") != list(REQUIRED_GOLDEN_OPERATIONS):
        reasons.append("golden_operation_set_mismatch")
    if not isinstance(quality, dict) or quality.get("model_requirements") != list(MODEL_GATES):
        reasons.append("model_quality_gates_mismatch")
    if not isinstance(quality, dict) or quality.get("candidate_must_not_regress_from_baseline") is not True:
        reasons.append("quality_nonregression_gate_missing")
    if not isinstance(quality, dict) or quality.get("missing_evidence_status") != "not_established":
        reasons.append("quality_missing_evidence_policy_mismatch")
    pairing = manifest.get("pairing")
    if not isinstance(pairing, dict) or any(
        pairing.get(name) is not True for name in (
            "isolated_state_and_scratch_per_side", "cold_and_warm_epochs_separate",
            "cold_warm_sample_ids_disjoint",
        )
    ) or pairing.get("side_execution_order") != "baseline_then_candidate_no_overlap":
        reasons.append("pairing_protocol_incomplete")
    policy = manifest.get("measurement_policy")
    if not isinstance(policy, dict) or any(
        policy.get(name) is not True for name in (
            "require_immutable_source_pins", "require_t20_cpu_slot_assignment",
        )
    ) or policy.get("measurements_started") is not False or policy.get("historical_unpaired_rows_count_as_paired_receipts") is not False:
        reasons.append("measurement_policy_mismatch")
    if not isinstance(limits, dict) or limits.get("plan_grade_requires_all_six_paired_receipts") is not True:
        reasons.append("plan_grade_case_receipt_gate_missing")
    return reasons


def load_manifest(path: Path | str) -> dict[str, Any]:
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    reasons = validate_manifest(manifest)
    if reasons:
        raise ValueError("invalid T02 paired matrix manifest: " + ", ".join(reasons))
    return manifest


def prepare_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    pins = manifest.get("source_pins", {})
    pending = [
        f"{name}_pin" for name in ("baseline", "candidate")
        if validate_source_pin(pins.get(name))
    ]
    slot = manifest.get("cpu_slot")
    if (
        not isinstance(slot, dict) or slot.get("owner") != "T20"
        or slot.get("status") != "reserved"
        or not str(slot.get("assignment_id", "")).strip()
    ):
        pending.append("cpu_slot")
    return {
        "status": (
            "prepared_waiting_for_pins_and_slot" if "cpu_slot" in pending
            else "prepared_waiting_for_pins" if pending
            else "ready_for_pin_verification"
        ),
        "measurement_allowed": not pending,
        "pending": pending,
        "required_cases": [
            {"file_count": files, "rag_chunk_count": rag}
            for files, rag in sorted(CASE_KEYS)
        ],
    }


def validate_source_pin(pin: Any) -> list[str]:
    if not isinstance(pin, dict):
        return ["source_pin_missing"]
    reasons: list[str] = []
    commit_sha = pin.get("commit_sha")
    snapshot_sha = pin.get("snapshot_sha256")
    if not isinstance(commit_sha, str) or re.fullmatch(r"[0-9a-fA-F]{40}", commit_sha) is None:
        reasons.append("commit_sha_must_be_full_40_hex")
    if not isinstance(snapshot_sha, str) or re.fullmatch(r"[0-9a-fA-F]{64}", snapshot_sha) is None:
        reasons.append("snapshot_sha256_must_be_full_64_hex")
    generator_sha = pin.get("generator_sha256")
    if not isinstance(generator_sha, str) or re.fullmatch(r"[0-9a-fA-F]{64}", generator_sha) is None:
        reasons.append("generator_sha256_must_be_full_64_hex")
    file_hashes = pin.get("file_sha256")
    if not isinstance(file_hashes, dict) or set(file_hashes) != set(SOURCE_PIN_PATHS):
        reasons.append("file_sha256_paths_must_match_pinned_snapshot")
    elif any(
        not isinstance(value, str) or re.fullmatch(r"[0-9a-fA-F]{64}", value) is None
        for value in file_hashes.values()
    ):
        reasons.append("file_sha256_values_must_be_full_64_hex")
    return reasons


def score_quality(baseline: Any, candidate: Any) -> dict[str, Any]:
    if not isinstance(baseline, dict) or not isinstance(candidate, dict):
        return {"status": "not_established", "score_pct": None, "reasons": ["quality_record_missing"]}
    reasons: list[str] = []
    missing: list[str] = []
    checks: dict[str, bool] = {}
    critical_false_success_detected = False
    for side, evidence in (("baseline", baseline), ("candidate", candidate)):
        goldens = evidence.get("golden_operations")
        retrieval = evidence.get("retrieval")
        retrieval_by_case = evidence.get("retrieval_by_case")
        model = evidence.get("model")
        if not isinstance(goldens, dict):
            missing.append(f"{side}_golden_operations_missing")
        else:
            for name in REQUIRED_GOLDEN_OPERATIONS:
                value = goldens.get(name)
                checks[f"{side}_golden:{name}"] = value is True
                if value is not True:
                    reasons.append(f"golden_operation_failed:{name}" if value is False else f"golden_operation_missing:{name}")
        if not isinstance(retrieval, dict):
            missing.append(f"{side}_retrieval_quality_missing")
        else:
            for name in RETRIEVAL_METRICS:
                value = retrieval.get(name)
                if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
                    missing.append(f"{side}_retrieval_metric_missing:{name}")
                else:
                    checks[f"{side}_retrieval:{name}"] = 0.0 <= float(value) <= 1.0
                    if not checks[f"{side}_retrieval:{name}"]:
                        reasons.append(f"retrieval_metric_out_of_range:{name}")
                    elif float(value) < RETRIEVAL_MINIMUMS[name]:
                        checks[f"{side}_retrieval_minimum:{name}"] = False
                        reasons.append(f"retrieval_metric_below_minimum:{name}")
                    else:
                        checks[f"{side}_retrieval_minimum:{name}"] = True
        if not isinstance(retrieval_by_case, dict) or not retrieval_by_case:
            missing.append(f"{side}_retrieval_cases_missing")
        else:
            for case_key, case_metrics in retrieval_by_case.items():
                if not isinstance(case_metrics, dict):
                    missing.append(f"{side}_retrieval_case_invalid:{case_key}")
                    continue
                for name in RETRIEVAL_METRICS:
                    value = case_metrics.get(name)
                    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
                        missing.append(f"{side}_retrieval_case_metric_missing:{case_key}:{name}")
                    else:
                        checks[f"{side}_retrieval_case_minimum:{case_key}:{name}"] = float(value) >= RETRIEVAL_MINIMUMS[name]
                        if float(value) < RETRIEVAL_MINIMUMS[name]:
                            reasons.append(f"retrieval_metric_below_minimum:{case_key}:{name}")
        if not isinstance(model, dict):
            missing.append(f"{side}_model_quality_missing")
        else:
            for name in MODEL_GATES:
                value = model.get(name)
                checks[f"{side}_model:{name}"] = value is True
                if value is not True:
                    reasons.append(f"model_quality_gate_failed:{name}" if value is False else f"model_quality_gate_missing:{name}")
            critical = model.get("critical_false_success_count")
            checks[f"{side}_critical_false_success_zero"] = type(critical) is int and critical == 0
            critical_false_success_detected = critical_false_success_detected or (
                type(critical) is int and critical > 0
            )
            if not checks[f"{side}_critical_false_success_zero"]:
                reasons.append("critical_false_success_count_must_be_zero")
    baseline_cases = baseline.get("retrieval_by_case") if isinstance(baseline, dict) else None
    candidate_cases = candidate.get("retrieval_by_case") if isinstance(candidate, dict) else None
    if isinstance(baseline_cases, dict) and isinstance(candidate_cases, dict):
        if set(baseline_cases) != set(candidate_cases):
            reasons.append("retrieval_case_set_mismatch")
        for case_key in sorted(set(baseline_cases) & set(candidate_cases)):
            for name in RETRIEVAL_METRICS:
                base = baseline_cases[case_key].get(name) if isinstance(baseline_cases[case_key], dict) else None
                cand = candidate_cases[case_key].get(name) if isinstance(candidate_cases[case_key], dict) else None
                if isinstance(base, (int, float)) and not isinstance(base, bool) and isinstance(cand, (int, float)) and not isinstance(cand, bool):
                    checks[f"retrieval_nonregression:{case_key}:{name}"] = float(cand) >= float(base)
                    if float(cand) < float(base):
                        reasons.append(f"retrieval_metric_regressed:{case_key}:{name}")
    if missing:
        return {
            # A proven safety failure must remain a failure even when other
            # quality evidence is incomplete. Missing evidence cannot mask it.
            "status": "failed" if critical_false_success_detected else "not_established",
            "score_pct": None,
            "checks": checks,
            "reasons": sorted(set(missing + reasons)),
        }
    total = len(checks)
    passed = sum(value is True for value in checks.values())
    score = round(100.0 * passed / total, 3) if total else None
    return {
        "status": "passed" if not reasons and score == 100.0 else "failed",
        "score_pct": score,
        "checks": checks,
        "reasons": sorted(set(reasons)),
    }


def score_performance(baseline: Any, candidate: Any, *, tolerance_pct: float = REGRESSION_TOLERANCE_PCT) -> dict[str, Any]:
    if not isinstance(baseline, dict) or not isinstance(candidate, dict):
        return {"status": "inconclusive", "regression_tolerance_pct": tolerance_pct, "reasons": ["performance_record_missing"]}
    deltas: dict[str, float] = {}
    reasons: list[str] = []
    for metric in ("p95_ms", "p99_ms"):
        base, cand = baseline.get(metric), candidate.get(metric)
        if (
            not isinstance(base, (int, float)) or isinstance(base, bool)
            or not isinstance(cand, (int, float)) or isinstance(cand, bool)
            or not math.isfinite(float(base)) or not math.isfinite(float(cand))
            or float(base) <= 0 or float(cand) <= 0
        ):
            reasons.append(f"performance_metric_missing_or_invalid:{metric}")
            continue
        delta = (float(cand) / float(base) - 1.0) * 100.0
        deltas[metric] = round(delta, 6)
        if delta > tolerance_pct + 1e-9:
            reasons.append(f"performance_regression_over_limit:{metric}")
    status = "inconclusive" if any(reason.endswith("missing_or_invalid:p95_ms") or reason.endswith("missing_or_invalid:p99_ms") for reason in reasons) else "regression" if reasons else "within_tolerance"
    return {
        "status": status,
        "regression_tolerance_pct": tolerance_pct,
        "deltas_pct": deltas,
        "reasons": reasons,
    }


def evaluate_pair_acceptance(
    manifest: dict[str, Any], paired_case_receipts: list[dict[str, Any]],
    quality: dict[str, Any], performance: dict[str, Any],
) -> dict[str, Any]:
    expected = CASE_KEYS
    found: dict[tuple[int, int], dict[str, Any]] = {}
    reasons: list[str] = []
    for item in paired_case_receipts:
        try:
            key = (int(item["file_count"]), int(item["rag_chunk_count"]))
        except (KeyError, TypeError, ValueError):
            reasons.append("paired_case_key_invalid")
            continue
        if key in found:
            reasons.append(f"paired_case_duplicate:{key[0]}:{key[1]}")
        found[key] = item
        if item.get("status") != "passed":
            reasons.append(f"paired_case_not_passed:{key[0]}:{key[1]}")
        if item.get("baseline_input_fingerprint") != item.get("candidate_input_fingerprint"):
            reasons.append("paired_input_fingerprint_mismatch")
        fingerprint = item.get("baseline_input_fingerprint")
        if not isinstance(fingerprint, str) or re.fullmatch(r"[0-9a-fA-F]{64}", fingerprint) is None:
            reasons.append("paired_input_fingerprint_missing_or_invalid")
        if item.get("generator_version_match") is not True:
            reasons.append("paired_generator_version_mismatch")
        if item.get("cold_warm_independent") is not True:
            reasons.append("cold_warm_samples_not_independent")
    if set(found) != expected:
        reasons.append("paired_case_receipts_incomplete")
    if quality.get("status") != "passed" or quality.get("score_pct") != 100.0:
        reasons.append("quality_acceptance_not_passed")
    if performance.get("status") not in {"within_tolerance", "improved"}:
        reasons.append("performance_acceptance_not_passed")
    unique_reasons = sorted(set(reasons))
    return {
        "plan_grade": not unique_reasons,
        "case_receipt_count": len(found),
        "required_case_count": len(expected),
        "quality_score_pct": quality.get("score_pct"),
        "performance_status": performance.get("status"),
        "reasons": unique_reasons,
    }


def _generator_digest(root: Path) -> str:
    path = root / "tools/benchmark_surfaces.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    wanted = {"_synthetic_source", "_build_synthetic_repo"}
    pieces = [
        ast.dump(node, include_attributes=False)
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in wanted
    ]
    if len(pieces) != len(wanted):
        raise ValueError("synthetic input generator functions are missing")
    return hashlib.sha256("\n".join(pieces).encode("utf-8")).hexdigest()


def compute_source_pin(root: Path | str) -> dict[str, Any]:
    repo = Path(root).expanduser().resolve()
    commit = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"], cwd=repo,
        check=True, capture_output=True, text=True, timeout=5,
    ).stdout.strip()
    file_hashes = {
        relative: hashlib.sha256((repo / relative).read_bytes()).hexdigest()
        for relative in SOURCE_PIN_PATHS
    }
    snapshot = {"commit_sha": commit, "file_sha256": file_hashes}
    payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "commit_sha": commit,
        "snapshot_sha256": hashlib.sha256(payload).hexdigest(),
        "generator_sha256": _generator_digest(repo),
        "file_sha256": file_hashes,
    }


def verify_source_pin(root: Path | str, expected: dict[str, Any]) -> list[str]:
    reasons = validate_source_pin(expected)
    if reasons:
        return reasons
    try:
        actual = compute_source_pin(root)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return [f"source_pin_compute_failed:{type(exc).__name__}"]
    for field in ("commit_sha", "snapshot_sha256", "generator_sha256"):
        if str(actual.get(field, "")).lower() != str(expected.get(field, "")).lower():
            reasons.append(f"source_pin_mismatch:{field}")
    expected_files = expected.get("file_sha256", {})
    normalized_expected_files = {
        path: value.lower() if isinstance(value, str) else value
        for path, value in expected_files.items()
    } if isinstance(expected_files, dict) else expected_files
    if normalized_expected_files != actual.get("file_sha256"):
        reasons.append("source_pin_mismatch:file_sha256")
    return reasons


def measurement_blockers(manifest: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    pins = manifest.get("source_pins", {})
    for side in ("baseline", "candidate"):
        reasons.extend(f"{side}:{reason}" for reason in validate_source_pin(pins.get(side)))
    slot = manifest.get("cpu_slot")
    if (
        not isinstance(slot, dict) or slot.get("owner") != "T20"
        or slot.get("status") != "reserved"
        or not str(slot.get("assignment_id", "")).strip()
    ):
        reasons.append("cpu_slot_assignment_missing")
    return reasons


def build_matrix_command(source_root: Path, state_dir: Path, scratch_dir: Path, manifest: dict[str, Any], baseline_record: Path | None = None) -> list[str]:
    command = [
        sys.executable,
        str(source_root / "tools/benchmark_surfaces.py"),
        "--state-dir", str(state_dir),
        "--scratch-dir", str(scratch_dir),
        "--full-matrix",
        "--light-repetitions", str(manifest["run_parameters"]["light_repetitions"]),
        "--comparison-repetitions", str(manifest["run_parameters"]["comparison_repetitions"]),
        "--concurrency", *[str(level) for level in manifest["run_parameters"]["concurrency"]],
        "--input-seed", str(manifest["input_generator"]["seed"]),
        "--timeout-seconds", str(manifest["run_parameters"]["timeout_seconds"]),
    ]
    if baseline_record is not None:
        command.extend(["--compare-with", str(baseline_record)])
    return command


def _run_matrix(source_root: Path, state_dir: Path, scratch_dir: Path, manifest: dict[str, Any], baseline_record: Path | None) -> dict[str, Any]:
    state_dir.mkdir(parents=True, exist_ok=False)
    scratch_dir.mkdir(parents=True, exist_ok=False)
    command = build_matrix_command(source_root, state_dir, scratch_dir, manifest, baseline_record)
    stdout_path, stderr_path = state_dir / "runner.stdout.json", state_dir / "runner.stderr.txt"
    started = time.perf_counter()
    with stdout_path.open("w", encoding="utf-8", newline="\n") as stdout, stderr_path.open("w", encoding="utf-8", newline="\n") as stderr:
        completed = subprocess.run(
            command, cwd=source_root, stdout=stdout, stderr=stderr,
            text=True, timeout=manifest["run_parameters"]["timeout_seconds"], check=False,
        )
    if not stdout_path.is_file() or stdout_path.stat().st_size == 0:
        raise RuntimeError(f"matrix runner produced no record; stderr={stderr_path}")
    record = json.loads(stdout_path.read_text(encoding="utf-8"))
    record["runner_return_code"] = completed.returncode
    record["runner_command"] = command
    record["runner_wall_time_seconds"] = round(time.perf_counter() - started, 3)
    record["runner_stdout_path"] = str(stdout_path)
    record["runner_stderr_path"] = str(stderr_path)
    if not isinstance(record.get("record_path"), str):
        raise RuntimeError("matrix runner output lacks record_path")
    return record


def _case_map(record: dict[str, Any]) -> dict[tuple[int, int], dict[str, Any]]:
    result: dict[tuple[int, int], dict[str, Any]] = {}
    for item in record.get("cases", []):
        try:
            key = (int(item["file_count"]), int(item["rag_chunk_count"]))
        except (KeyError, TypeError, ValueError):
            continue
        if key in result:
            raise ValueError("matrix record contains duplicate case key")
        result[key] = item.get("record", {})
    return result


def _case_receipts(baseline: dict[str, Any], candidate: dict[str, Any]) -> list[dict[str, Any]]:
    old_cases, new_cases = _case_map(baseline), _case_map(candidate)
    receipts: list[dict[str, Any]] = []
    for file_count, rag_count in sorted(CASE_KEYS):
        old, new = old_cases.get((file_count, rag_count), {}), new_cases.get((file_count, rag_count), {})
        old_meta = old.get("metadata") if isinstance(old.get("metadata"), dict) else {}
        new_meta = new.get("metadata") if isinstance(new.get("metadata"), dict) else {}
        old_input = old_meta.get("synthetic_input_fingerprint")
        new_input = new_meta.get("synthetic_input_fingerprint")
        valid_fingerprint = lambda value: isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None
        generator_match = (
            type(old_meta.get("synthetic_input_generator_version")) is int
            and type(old_meta.get("synthetic_input_seed")) is int
            and old_meta.get("synthetic_input_generator_version") == INPUT_GENERATOR_VERSION
            and old_meta.get("synthetic_input_seed") == REQUIRED_INPUT_SEED
            and old_meta.get("synthetic_input_generator_version") == new_meta.get("synthetic_input_generator_version")
            and old_meta.get("synthetic_input_seed") == new_meta.get("synthetic_input_seed")
        )
        fingerprints_match = valid_fingerprint(old_input) and valid_fingerprint(new_input) and old_input == new_input
        baseline_meta = baseline.get("metadata") if isinstance(baseline.get("metadata"), dict) else {}
        candidate_meta = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        proof_ok = all(
            meta.get("baseline_readiness") == "plan_grade"
            and meta.get("baseline_readiness_reasons") == []
            for meta in (baseline_meta, candidate_meta)
        )
        # The paired generator receipt is valid only inside a plan-grade run.
        # That run-level receipt includes validated cold/warm epoch evidence.
        generator_match = generator_match and proof_ok
        receipts.append({
            "file_count": file_count,
            "rag_chunk_count": rag_count,
            "status": "passed" if (
                old.get("success") is True and new.get("success") is True
                and baseline.get("runner_return_code") == 0
                and candidate.get("runner_return_code") == 0
                and fingerprints_match and generator_match and proof_ok
            ) else "failed",
            "baseline_input_fingerprint": old_input,
            "candidate_input_fingerprint": new_input,
            "generator_version_match": generator_match,
            "cold_warm_independent": proof_ok,
        })
    return receipts


def _quality_from_matrix(record: dict[str, Any]) -> dict[str, Any]:
    cases = _case_map(record)
    if set(cases) != CASE_KEYS:
        return {}
    all_goldens = {name: True for name in REQUIRED_GOLDEN_OPERATIONS}
    retrieval_values: dict[str, list[float]] = {name: [] for name in RETRIEVAL_METRICS}
    retrieval_by_case: dict[str, dict[str, float]] = {}
    model_values = {name: True for name in MODEL_GATES}
    critical_errors = 0
    for (file_count, rag_count), case in cases.items():
        goldens = case.get("metadata", {}).get("golden_operations", {})
        for name in REQUIRED_GOLDEN_OPERATIONS:
            all_goldens[name] = all_goldens[name] and goldens.get(name) is True
        quality = case.get("quality_metrics")
        if not isinstance(quality, dict):
            return {
                "golden_operations": all_goldens, "retrieval": None,
                "retrieval_by_case": None, "model": None,
            }
        retrieval = quality.get("retrieval", {})
        model = quality.get("model", {})
        case_retrieval: dict[str, float] = {}
        for name in RETRIEVAL_METRICS:
            value = retrieval.get(name) if isinstance(retrieval, dict) else None
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return {
                    "golden_operations": all_goldens, "retrieval": None,
                    "retrieval_by_case": None, "model": None,
                }
            retrieval_values[name].append(float(value))
            case_retrieval[name] = float(value)
        retrieval_by_case[f"{file_count}:{rag_count}"] = case_retrieval
        for name in MODEL_GATES:
            model_values[name] = model_values[name] and isinstance(model, dict) and model.get(name) is True
        critical_errors += int(model.get("critical_false_success_count", 0)) if isinstance(model, dict) else 1
    retrieval_summary = {name: min(values) for name, values in retrieval_values.items()}
    return {
        "golden_operations": all_goldens,
        "retrieval": retrieval_summary,
        "retrieval_by_case": retrieval_by_case,
        "model": {**model_values, "critical_false_success_count": critical_errors},
    }


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def run_paired_matrix(manifest_path: Path, baseline_root: Path, candidate_root: Path, output_dir: Path) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    blockers = measurement_blockers(manifest)
    if blockers:
        raise PreparationRequired("measurement blocked: " + ", ".join(blockers))
    baseline_pin, candidate_pin = manifest["source_pins"]["baseline"], manifest["source_pins"]["candidate"]
    for side, root, pin in (("baseline", baseline_root, baseline_pin), ("candidate", candidate_root, candidate_pin)):
        mismatches = verify_source_pin(root, pin)
        if mismatches:
            raise PreparationRequired(f"{side} source pin mismatch: " + ", ".join(mismatches))
    if baseline_pin["generator_sha256"].lower() != candidate_pin["generator_sha256"].lower():
        raise PreparationRequired("baseline and candidate synthetic input generator fingerprints differ")
    if baseline_pin["file_sha256"]["tools/benchmark_surfaces.py"].lower() != candidate_pin["file_sha256"]["tools/benchmark_surfaces.py"].lower():
        raise PreparationRequired("baseline and candidate benchmark harness pins differ")
    output = output_dir.expanduser().resolve()
    for root in (baseline_root.resolve(), candidate_root.resolve()):
        if output == root or output.is_relative_to(root) or root.is_relative_to(output):
            raise ValueError("paired matrix output must be disjoint from both source roots")
    if output.exists():
        raise ValueError("paired matrix output directory must not already exist")
    baseline_state = output / "baseline" / "state"
    baseline_scratch = output / "baseline" / "scratch"
    candidate_state = output / "candidate" / "state"
    candidate_scratch = output / "candidate" / "scratch"
    baseline_command = build_matrix_command(baseline_root, baseline_state, baseline_scratch, manifest)
    try:
        baseline_result = _run_matrix(baseline_root, baseline_state, baseline_scratch, manifest, None)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        _write_json_atomic(output / "paired-receipt.json", {
            "schema_version": 1,
            "status": "aborted_baseline_runner_failure",
            "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "baseline_source_pin": baseline_pin,
            "candidate_source_pin": candidate_pin,
            "runner_commands": {"baseline": baseline_command, "candidate": None},
            "log_paths": {
                "stdout": str(baseline_state / "runner.stdout.json"),
                "stderr": str(baseline_state / "runner.stderr.txt"),
            },
            "error": f"{type(exc).__name__}: {exc}",
            "candidate_measurement_started": False,
        })
        raise
    if baseline_result.get("runner_return_code") != 0:
        _write_json_atomic(output / "paired-receipt.json", {
            "schema_version": 1,
            "status": "aborted_baseline_runner_failure",
            "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "baseline_source_pin": baseline_pin,
            "candidate_source_pin": candidate_pin,
            "baseline_result": baseline_result,
            "candidate_measurement_started": False,
        })
        raise RuntimeError("baseline matrix runner failed; candidate measurement not started")
    post_baseline_checks = {
        "baseline": verify_source_pin(baseline_root, baseline_pin),
        "candidate": verify_source_pin(candidate_root, candidate_pin),
    }
    baseline_drift = [
        f"{side}:{reason}" for side, mismatches in post_baseline_checks.items()
        for reason in mismatches
    ]
    if baseline_drift:
        _write_json_atomic(output / "paired-receipt.json", {
            "schema_version": 1,
            "status": "aborted_source_pin_drift_after_baseline",
            "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "baseline_source_pin": baseline_pin,
            "candidate_source_pin": candidate_pin,
            "baseline_record_path": baseline_result.get("record_path"),
            "baseline_result": baseline_result,
            "source_pin_checks": {"before": {"baseline": [], "candidate": []}, "after_baseline": post_baseline_checks},
            "reasons": baseline_drift,
            "candidate_measurement_started": False,
        })
        raise PreparationRequired("source pin drift after baseline; candidate measurement stopped: " + ", ".join(baseline_drift))
    baseline_record_path = Path(baseline_result["record_path"])
    candidate_command = build_matrix_command(
        candidate_root, candidate_state, candidate_scratch, manifest, baseline_record_path,
    )
    try:
        candidate_result = _run_matrix(
            candidate_root, candidate_state, candidate_scratch, manifest, baseline_record_path,
        )
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        _write_json_atomic(output / "paired-receipt.json", {
            "schema_version": 1,
            "status": "aborted_candidate_runner_failure",
            "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "baseline_source_pin": baseline_pin,
            "candidate_source_pin": candidate_pin,
            "runner_commands": {"baseline": baseline_command, "candidate": candidate_command},
            "baseline_record_path": str(baseline_record_path),
            "baseline_wall_time_seconds": baseline_result.get("runner_wall_time_seconds"),
            "log_paths": {
                "baseline_stdout": baseline_result.get("runner_stdout_path"),
                "baseline_stderr": baseline_result.get("runner_stderr_path"),
                "candidate_stdout": str(candidate_state / "runner.stdout.json"),
                "candidate_stderr": str(candidate_state / "runner.stderr.txt"),
            },
            "error": f"{type(exc).__name__}: {exc}",
            "candidate_measurement_started": True,
        })
        raise
    post_candidate_checks = {
        "baseline": verify_source_pin(baseline_root, baseline_pin),
        "candidate": verify_source_pin(candidate_root, candidate_pin),
    }
    paired_cases = _case_receipts(baseline_result, candidate_result)
    quality = score_quality(_quality_from_matrix(baseline_result), _quality_from_matrix(candidate_result))
    comparison = candidate_result.get("comparison", {})
    performance = {
        "status": comparison.get("status", "inconclusive"),
        "regression_tolerance_pct": REGRESSION_TOLERANCE_PCT,
        "reasons": [] if comparison.get("status") in {"within_tolerance", "improved"} else [str(comparison.get("reason", "matrix_comparison_incomplete"))],
    }
    acceptance = evaluate_pair_acceptance(manifest, paired_cases, quality, performance)
    final_pin_drift = [
        f"{side}:{reason}" for side, mismatches in post_candidate_checks.items()
        for reason in mismatches
    ]
    if final_pin_drift:
        acceptance["plan_grade"] = False
        acceptance["reasons"] = sorted(set(acceptance["reasons"] + [
            "source_pin_changed_during_measurement:" + reason for reason in final_pin_drift
        ]))
    baseline_metadata = baseline_result.get("metadata") if isinstance(baseline_result.get("metadata"), dict) else {}
    candidate_metadata = candidate_result.get("metadata") if isinstance(candidate_result.get("metadata"), dict) else {}
    receipt = {
        "schema_version": 1,
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "baseline_source_pin": baseline_pin,
        "candidate_source_pin": candidate_pin,
        "generator_sha256": baseline_pin["generator_sha256"],
        "input_seed": manifest["input_generator"]["seed"],
        "baseline_record_path": str(baseline_record_path),
        "candidate_record_path": candidate_result["record_path"],
        "source_pin_checks": {
            "before": {"baseline": [], "candidate": []},
            "after_baseline": post_baseline_checks,
            "after_candidate": post_candidate_checks,
        },
        "wall_time_seconds": {
            "baseline": baseline_result.get("runner_wall_time_seconds"),
            "candidate": candidate_result.get("runner_wall_time_seconds"),
        },
        "runner_commands": {
            "baseline": baseline_result.get("runner_command"),
            "candidate": candidate_result.get("runner_command"),
        },
        "environment": {
            "baseline": {
                "platform": baseline_metadata.get("platform"),
                "hardware_fingerprint": baseline_metadata.get("hardware_fingerprint"),
            },
            "candidate": {
                "platform": candidate_metadata.get("platform"),
                "hardware_fingerprint": candidate_metadata.get("hardware_fingerprint"),
            },
        },
        "comparison": comparison,
        "quality": quality,
        "performance": performance,
        "paired_cases": paired_cases,
        **acceptance,
    }
    _write_json_atomic(output / "paired-receipt.json", receipt)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare", help="validate manifest and show pending pins/slot")
    prepare.add_argument("--manifest", type=Path, required=True)
    run = sub.add_parser("run", help="run paired six-case matrix after explicit T20 pin/slot assignment")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--baseline-root", type=Path, required=True)
    run.add_argument("--candidate-root", type=Path, required=True)
    run.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
        if args.command == "prepare":
            print(json.dumps(prepare_summary(manifest), sort_keys=True))
            return 0
        receipt = run_paired_matrix(args.manifest, args.baseline_root, args.candidate_root, args.output_dir)
        print(json.dumps({key: receipt[key] for key in ("plan_grade", "case_receipt_count", "required_case_count", "reasons")}, sort_keys=True))
        return 0 if receipt["plan_grade"] else 2
    except (OSError, ValueError, RuntimeError, PreparationRequired, subprocess.SubprocessError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
