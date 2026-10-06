import json
from pathlib import Path

from local_ai_hub.model_quality import (
    CandidateRegistry,
    aggregate_metrics,
    evaluate_case,
    promote_candidate,
)


FIXTURE = Path(__file__).parent / "fixtures" / "model_quality_cases.jsonl"


def _cases():
    return [json.loads(line) for line in FIXTURE.read_text().splitlines() if line]


def test_synthetic_quality_corpus_covers_required_workflows_and_compression_fields():
    cases = _cases()
    required_workflows = {"reason", "review", "compress", "complete", "scaffold"}
    workflow_cases = [case for case in cases if case.get("workflow") in required_workflows]

    assert required_workflows <= {case["workflow"] for case in workflow_cases}

    # These records test deterministic evaluator behavior, not live-model quality.
    for case in workflow_cases:
        result = evaluate_case(**{key: case[key] for key in ("task", "evidence_paths", "output", "expected")})
        assert result["schema_pass"] is True
        assert result["hallucinated_paths"] == []
        assert all(case["output"].get(key) == value for key, value in case["expected"].items())

    compressed = next(case for case in cases if case["id"] == "compression_preserves_evidence")
    # Synthetic fixture checks field retention only; it is not live-model grounding evidence.
    assert compressed["output"]["facts"] == compressed["expected"]["facts"]
    assert compressed["output"]["facts"][0]["evidence_ids"] == ["synthetic-compress-1"]
    assert compressed["output"]["uncertainty"] == compressed["expected"]["uncertainty"]


def test_quality_evaluator_rejects_compression_that_drops_required_fields():
    case = next(case for case in _cases() if case["id"] == "compression_preserves_evidence")
    required_fields = ("facts", "uncertainty")

    for field in required_fields:
        incomplete = dict(case["output"])
        incomplete.pop(field)
        result = evaluate_case(
            task=case["task"],
            evidence_paths=case["evidence_paths"],
            output=incomplete,
            expected=case["expected"],
        )
        assert result["schema_pass"] is False

    incomplete_fact = dict(case["output"]["facts"][0])
    incomplete_fact.pop("evidence_ids")
    incomplete = {**case["output"], "facts": [incomplete_fact]}
    result = evaluate_case(
        task=case["task"],
        evidence_paths=case["evidence_paths"],
        output=incomplete,
        expected=case["expected"],
    )
    assert result["schema_pass"] is False


def test_quality_schema_checks_each_list_exemplar_and_last_shape_for_extras():
    expected = {
        "items": [
            {"kind": "alpha", "score": 1},
            {"kind": "beta", "label": "required"},
        ]
    }

    def schema_passes(items):
        return evaluate_case(
            task="",
            evidence_paths=[],
            output={"items": items},
            expected=expected,
        )["schema_pass"]

    assert schema_passes(
        [
            {"kind": "alpha", "score": 1},
            {"kind": "beta", "label": "required"},
        ]
    ) is True
    assert schema_passes(
        [
            {"kind": "alpha", "score": 1},
            {"kind": "beta", "score": 2},
        ]
    ) is False
    assert schema_passes(
        [
            {"kind": "alpha", "score": 1},
            {"kind": "beta", "label": "required"},
            {"kind": "gamma", "label": "extra"},
        ]
    ) is True
    assert schema_passes(
        [
            {"kind": "alpha", "score": 1},
            {"kind": "beta", "label": "required"},
            {"kind": "gamma", "score": 3},
        ]
    ) is False

def test_quality_schema_rejects_empty_required_lists_and_boolean_integers():
    case = next(case for case in _cases() if case["id"] == "compression_preserves_evidence")
    empty_facts = {**case["output"], "facts": []}
    result = evaluate_case(
        task=case["task"],
        evidence_paths=case["evidence_paths"],
        output=empty_facts,
        expected=case["expected"],
    )
    assert result["schema_pass"] is False

    result = evaluate_case(
        task="validate integer field type",
        evidence_paths=[],
        output={"count": True},
        expected={"count": 1},
    )
    assert result["schema_pass"] is False


def test_model_case_records_grounding_and_schema_metrics():
    result = evaluate_case(
        task="classify input",
        evidence_paths=["fixtures/contact.txt"],
        output={"label": "phone", "reason": "matches phone pattern"},
        expected={"label": "phone"},
    )

    assert result["grounded"] is True
    assert result["grounded_relevance"] == 1.0
    assert result["schema_pass"] is True
    assert result["hallucinated_paths"] == []
    assert result["false_positive"] is False


def test_fixture_cases_cover_abstention_hallucinated_paths_and_false_positives():
    results = {case["id"]: evaluate_case(**{key: case[key] for key in ("task", "evidence_paths", "output", "expected")}) for case in _cases()}

    assert results["missing_evidence_abstention"]["abstention_correct"] is True
    assert results["unrelated_path_rejected"]["hallucinated_paths"] == ["fixtures/unrelated.txt"]
    assert results["unrelated_path_rejected"]["grounded"] is False
    assert results["invalid_contact_false_positive"]["false_positive"] is True


def test_aggregate_metrics_are_deterministic():
    results = [
        evaluate_case(
            task="classify",
            evidence_paths=["fixtures/contact.txt"],
            output={"label": "phone"},
            expected={"label": "phone", "valid": True},
        ),
        evaluate_case(
            task="classify",
            evidence_paths=["fixtures/contact.txt"],
            output={"label": "phone", "references": ["fixtures/ghost.txt"]},
            expected={"label": "phone", "valid": True},
        ),
        evaluate_case(
            task="review",
            evidence_paths=[],
            output={"abstain": True, "label": "unknown"},
            expected={"abstain": True, "label": "unknown"},
        ),
    ]

    metrics = aggregate_metrics(results)

    assert metrics["case_count"] == 3
    assert metrics["grounded_rate"] == 2 / 3
    assert metrics["schema_pass_rate"] == 1.0
    assert metrics["abstention_accuracy"] == 1.0
    assert metrics["hallucinated_path_rate"] == 1 / 3
    assert metrics["false_positive_rate"] == 0.0


def test_registry_rejects_below_quality_floor_before_receipt_gate():
    result = promote_candidate({"grounded_rate": 0.70, "hallucinated_path_rate": 0.08})

    assert result["status"] == "rejected"
    assert result["reason"] == "quality_floor_not_met"


def test_registry_requires_reproducible_receipt_for_promotion():
    metrics = {
        "grounded_rate": 1.0,
        "schema_pass_rate": 1.0,
        "abstention_accuracy": 1.0,
        "hallucinated_path_rate": 0.0,
        "false_positive_rate": 0.0,
    }

    missing_receipt = promote_candidate(metrics)
    promoted = promote_candidate(
        metrics,
        receipt={"receipt_id": "receipt-1", "evaluation_hash": "sha256:case-suite"},
    )

    assert missing_receipt["status"] == "rejected"
    assert missing_receipt["reason"] == "evaluation_receipt_required"
    assert promoted["status"] == "champion"
    assert promoted["receipt_id"] == "receipt-1"


def test_registry_exposes_candidate_champion_and_rejected_states():
    registry = CandidateRegistry()
    candidate = registry.register_candidate("model-a", {"grounded_rate": 1.0})
    champion = registry.promote_candidate(
        "model-a",
        metrics={
            "grounded_rate": 1.0,
            "schema_pass_rate": 1.0,
            "abstention_accuracy": 1.0,
            "hallucinated_path_rate": 0.0,
            "false_positive_rate": 0.0,
        },
        receipt={"receipt_id": "receipt-a", "evaluation_hash": "sha256:a"},
    )
    rejected = registry.register_candidate("model-b", {"grounded_rate": 0.1})

    assert candidate["status"] == "candidate"
    assert champion["status"] == "champion"
    assert rejected["status"] == "candidate"
    assert registry.get("model-a")["status"] == "champion"
