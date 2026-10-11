from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from tools.run_t02_paired_matrix import (
    CASE_KEYS,
    _case_receipts,
    build_matrix_command,
    evaluate_pair_acceptance,
    load_manifest,
    measurement_blockers,
    prepare_summary,
    score_performance,
    score_quality,
    SOURCE_PIN_PATHS,
    validate_source_pin,
)
import tools.benchmark_surfaces as surface_benchmarks


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "handoff/T02-paired-matrix-20261002-v1/manifest.json"
REQUIRED_GOLDENS = {
    "symbols", "graph", "affected_tests", "retrieval_relevance",
    "code_generation", "vision", "speech", "context_pack",
}


@pytest.mark.parametrize("include_baseline_record", [False, True])
def test_matrix_runner_wires_manifest_seed_through_surface_cli(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    include_baseline_record: bool,
) -> None:
    manifest = load_manifest(MANIFEST)
    seed = manifest["input_generator"]["seed"]
    command = build_matrix_command(
        ROOT,
        tmp_path / "state",
        tmp_path / "scratch",
        manifest,
        tmp_path / "baseline.json" if include_baseline_record else None,
    )

    class ParserAccepted(Exception):
        def __init__(self, namespace: object) -> None:
            self.namespace = namespace

    original_parse_args = surface_benchmarks.argparse.ArgumentParser.parse_args

    def parse_then_stop(parser: object, args: object = None, namespace: object = None) -> None:
        parsed = original_parse_args(parser, args, namespace)
        raise ParserAccepted(parsed)

    monkeypatch.setattr(surface_benchmarks.argparse.ArgumentParser, "parse_args", parse_then_stop)
    with pytest.raises(ParserAccepted) as caught:
        surface_benchmarks.main(command[2:])

    parsed = caught.value.namespace
    assert parsed.full_matrix is True
    assert parsed.input_seed == seed
    assert parsed.light_repetitions == manifest["run_parameters"]["light_repetitions"]
    assert parsed.comparison_repetitions == manifest["run_parameters"]["comparison_repetitions"]
    assert parsed.concurrency == manifest["run_parameters"]["concurrency"]
    assert parsed.timeout_seconds == manifest["run_parameters"]["timeout_seconds"]
    assert (parsed.compare_with is not None) is include_baseline_record


def test_synthetic_input_provenance_emits_version_seed_and_fingerprint() -> None:
    implementation_path = Path(surface_benchmarks.__file__).resolve()
    expected_path = (ROOT / "tools/benchmark_surfaces.py").resolve()
    assert implementation_path == expected_path
    assert hashlib.sha256(implementation_path.read_bytes()).hexdigest() == hashlib.sha256(
        expected_path.read_bytes()
    ).hexdigest()

    provenance = surface_benchmarks._synthetic_input_provenance(42, "a" * 64)

    assert provenance == {
        "synthetic_input_generator_version": surface_benchmarks._SYNTHETIC_INPUT_GENERATOR_VERSION,
        "synthetic_input_seed": 42,
        "synthetic_input_fingerprint": "a" * 64,
    }


def test_baseline_candidate_harness_pins_match_immutable_commit_blobs() -> None:
    manifest = load_manifest(MANIFEST)
    harness_path = "tools/benchmark_surfaces.py"
    pinned_hashes = []
    for side in ("baseline", "candidate"):
        pin = manifest["source_pins"][side]
        result = subprocess.run(
            ["git", "show", f"{pin['commit_sha']}:{harness_path}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        )
        pinned_sha = hashlib.sha256(result.stdout).hexdigest()
        assert pin["file_sha256"][harness_path] == pinned_sha
        pinned_hashes.append(pinned_sha)

    assert pinned_hashes[0] == pinned_hashes[1]


def test_preparation_receipt_hashes_bind_its_historical_artifacts() -> None:
    receipt = json.loads(
        (ROOT / "handoff/T02-paired-matrix-20261002-v1/preparation-receipt.json")
        .read_text(encoding="utf-8")
    )
    last_attempt = receipt["last_test_attempt"]
    pinned_manifest = ROOT / receipt["manifest_path"]

    assert receipt["status"] == "terminal_contaminated_slot_released_no_valid_paired_receipt"
    assert receipt["artifacts"]["runner"]["sha256"] == last_attempt["runner_sha256_after_test"]
    assert receipt["artifacts"]["tests"]["sha256"] == last_attempt["test_sha256_after_test"]
    assert receipt["artifacts"]["benchmark_harness"]["sha256"] == last_attempt["harness_sha256_after_test"]
    assert receipt["manifest_sha256"] == hashlib.sha256(pinned_manifest.read_bytes()).hexdigest().upper()
RETRIEVAL_METRICS = {
    "recall_at_10": 0.9,
    "ndcg_at_10": 0.8,
    "file_line_evidence_accuracy": 1.0,
}


def _manifest_without_source_pins() -> dict[str, object]:
    manifest = load_manifest(MANIFEST)
    manifest["source_pins"] = {"baseline": None, "candidate": None}
    manifest["cpu_slot"]["status"] = "reserved"
    return manifest


def test_manifest_defines_six_cases_and_four_missing_pairs() -> None:
    manifest = load_manifest(MANIFEST)
    cases = {(item["file_count"], item["rag_chunk_count"]): item for item in manifest["cases"]}

    assert set(cases) == CASE_KEYS
    assert {
        pair for pair, case in cases.items() if case["status"] == "deferred"
    } == {
        (100, 100_000), (10_000, 100_000),
        (100_000, 10_000), (100_000, 100_000),
    }
    assert manifest["run_parameters"] == {
        "light_repetitions": 1_000,
        "comparison_repetitions": 30,
        "concurrency": [1, 4, 16, 32],
        "timeout_seconds": 3_600,
    }


def test_prepare_summary_never_authorizes_measurement_without_pins_and_slot() -> None:
    summary = prepare_summary(_manifest_without_source_pins())

    assert summary["measurement_allowed"] is False
    assert summary["status"] == "prepared_waiting_for_pins"
    assert set(summary["pending"]) == {"baseline_pin", "candidate_pin"}


def test_measurement_blockers_keep_reserved_slot_safe_until_both_pins_exist() -> None:
    manifest = _manifest_without_source_pins()

    blockers = measurement_blockers(manifest)

    assert any(item.startswith("baseline:source_pin_missing") for item in blockers)
    assert any(item.startswith("candidate:source_pin_missing") for item in blockers)
    assert "cpu_slot_assignment_missing" not in blockers


def test_source_pin_requires_immutable_revision_and_snapshot_digest() -> None:
    assert validate_source_pin({
        "commit_sha": "A" * 40,
        "snapshot_sha256": "B" * 64,
        "generator_sha256": "C" * 64,
        "file_sha256": {path: "D" * 64 for path in SOURCE_PIN_PATHS},
    }) == []
    assert "commit_sha_must_be_full_40_hex" in validate_source_pin(
        {
            "commit_sha": "main", "snapshot_sha256": "b" * 64,
            "generator_sha256": "c" * 64,
            "file_sha256": {path: "d" * 64 for path in SOURCE_PIN_PATHS},
        },
    )
    assert "snapshot_sha256_must_be_full_64_hex" in validate_source_pin(
        {
            "commit_sha": "a" * 40, "snapshot_sha256": "pending",
            "generator_sha256": "c" * 64,
            "file_sha256": {path: "d" * 64 for path in SOURCE_PIN_PATHS},
        },
    )


def test_quality_score_stays_not_established_when_semantic_evidence_is_missing() -> None:
    goldens = {name: True for name in REQUIRED_GOLDENS}
    quality = {
        "golden_operations": goldens,
        "retrieval": None,
        "model": {
            "output_schema_pass": True,
            "test_pass": True,
            "evidence_grounded": True,
            "critical_false_success_count": 0,
        },
    }

    result = score_quality(quality, quality)

    assert result["status"] == "not_established"
    assert result["score_pct"] is None
    assert "baseline_retrieval_quality_missing" in result["reasons"]
    assert "candidate_retrieval_quality_missing" in result["reasons"]


def test_quality_score_rejects_golden_or_retrieval_regression() -> None:
    baseline = {
        "golden_operations": {name: True for name in REQUIRED_GOLDENS},
        "retrieval": RETRIEVAL_METRICS,
        "retrieval_by_case": {"100:10000": RETRIEVAL_METRICS},
        "model": {
            "output_schema_pass": True,
            "test_pass": True,
            "evidence_grounded": True,
            "critical_false_success_count": 0,
        },
    }
    candidate = {
        **baseline,
        "golden_operations": {**baseline["golden_operations"], "retrieval_relevance": False},
        "retrieval": {**RETRIEVAL_METRICS, "recall_at_10": 0.89},
        "retrieval_by_case": {
            "100:10000": {**RETRIEVAL_METRICS, "recall_at_10": 0.89},
        },
    }

    result = score_quality(baseline, candidate)

    assert result["status"] == "failed"
    assert result["score_pct"] < 100
    assert "golden_operation_failed:retrieval_relevance" in result["reasons"]
    assert "retrieval_metric_regressed:100:10000:recall_at_10" in result["reasons"]
    assert "retrieval_metric_below_minimum:recall_at_10" in result["reasons"]


def test_quality_score_rejects_any_critical_false_success() -> None:
    quality = {
        "golden_operations": {name: True for name in REQUIRED_GOLDENS},
        "retrieval": RETRIEVAL_METRICS,
        "model": {
            "output_schema_pass": True,
            "test_pass": True,
            "evidence_grounded": True,
            "critical_false_success_count": 1,
        },
    }

    result = score_quality(quality, quality)

    assert result["status"] == "failed"
    assert "critical_false_success_count_must_be_zero" in result["reasons"]


def test_performance_gate_uses_paired_ten_percent_p95_p99_cap() -> None:
    baseline = {"p95_ms": 100.0, "p99_ms": 200.0}
    within = score_performance(baseline, {"p95_ms": 110.0, "p99_ms": 220.0})
    over = score_performance(baseline, {"p95_ms": 111.0, "p99_ms": 220.0})

    assert within["status"] == "within_tolerance"
    assert over["status"] == "regression"
    assert over["regression_tolerance_pct"] == 10.0


def test_plan_grade_requires_six_complete_paired_case_receipts() -> None:
    manifest = load_manifest(MANIFEST)
    cases = [
        {
            "file_count": file_count,
            "rag_chunk_count": rag_chunks,
            "status": "passed",
            "baseline_input_fingerprint": "a" * 64,
            "candidate_input_fingerprint": "a" * 64,
            "generator_version_match": True,
            "cold_warm_independent": True,
        }
        for file_count, rag_chunks in sorted(CASE_KEYS)
    ]
    quality = {"status": "passed", "score_pct": 100.0}
    performance = {"status": "within_tolerance"}

    incomplete = evaluate_pair_acceptance(manifest, cases[:-1], quality, performance)
    complete = evaluate_pair_acceptance(manifest, cases, quality, performance)

    assert incomplete["plan_grade"] is False
    assert "paired_case_receipts_incomplete" in incomplete["reasons"]
    assert complete["plan_grade"] is True


def test_pair_grade_rejects_input_mismatch_or_cold_warm_overlap() -> None:
    manifest = load_manifest(MANIFEST)
    cases = [
        {
            "file_count": file_count,
            "rag_chunk_count": rag_chunks,
            "status": "passed",
            "baseline_input_fingerprint": "a" * 64,
            "candidate_input_fingerprint": "b" * 64,
            "generator_version_match": False,
            "cold_warm_independent": False,
        }
        for file_count, rag_chunks in sorted(CASE_KEYS)
    ]

    result = evaluate_pair_acceptance(
        manifest,
        cases,
        {"status": "passed", "score_pct": 100.0},
        {"status": "within_tolerance"},
    )

    assert result["plan_grade"] is False
    assert "paired_input_fingerprint_mismatch" in result["reasons"]
    assert "paired_generator_version_mismatch" in result["reasons"]
    assert "cold_warm_samples_not_independent" in result["reasons"]


def test_case_receipts_fail_closed_when_generator_or_epoch_receipts_are_missing() -> None:
    cases = [
        {
            "file_count": file_count,
            "rag_chunk_count": rag_chunks,
            "record": {
                "success": True,
                "metadata": {
                    "synthetic_input_fingerprint": "a" * 64,
                    "synthetic_input_generator_version": 1,
                    "synthetic_input_seed": 42,
                },
                "stages": {},
            },
        }
        for file_count, rag_chunks in sorted(CASE_KEYS)
    ]
    baseline = {"cases": cases, "metadata": {}}
    candidate = {"cases": cases, "metadata": {}}

    receipts = _case_receipts(baseline, candidate)

    assert len(receipts) == 6
    assert all(item["status"] == "failed" for item in receipts)
    assert all(item["generator_version_match"] is False for item in receipts)
    assert all(item["cold_warm_independent"] is False for item in receipts)


def test_synthetic_input_builder_repeats_same_seed_and_fingerprints_different_seed(tmp_path: Path) -> None:
    _files_a, _test_a, _corpus_a, fingerprint_a = surface_benchmarks._build_synthetic_repo(
        tmp_path / "a", 3, 17, input_seed=42,
    )
    _files_b, _test_b, _corpus_b, fingerprint_b = surface_benchmarks._build_synthetic_repo(
        tmp_path / "b", 3, 17, input_seed=42,
    )
    _files_c, _test_c, _corpus_c, fingerprint_c = surface_benchmarks._build_synthetic_repo(
        tmp_path / "c", 3, 17, input_seed=43,
    )

    assert fingerprint_a == fingerprint_b
    assert fingerprint_a != fingerprint_c
