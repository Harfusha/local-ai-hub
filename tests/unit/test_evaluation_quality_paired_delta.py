from __future__ import annotations

from local_ai_hub.evaluation_quality import paired_retrieval_delta


def _case(case: str, query: str, *, symbols: bool, metrics: dict) -> dict:
    row = {
        "case": case,
        "query": query,
        "expected_path": f"src/{case}.py",
        "metrics": metrics,
    }
    if symbols:
        row.update(
            {
                "expected_symbols": {f"src/{case}.py": ["target"]},
                "intent": "production",
                "k": 1,
            }
        )
    return row


def test_paired_retrieval_delta_aggregates_mixed_scopes_separately() -> None:
    baseline = {
        "retrieval": [
            _case(
                "path",
                "find path",
                symbols=False,
                metrics={
                    "status": "measured",
                    "measurement_scope": "path_only",
                    "recall_at_k": 0.5,
                    "reciprocal_rank": 0.5,
                    "citation_validity": 0.5,
                },
            ),
            _case(
                "symbol",
                "find symbol",
                symbols=True,
                metrics={
                    "status": "measured",
                    "measurement_scope": "symbol_ast",
                    "recall_at_k": 0.2,
                    "reciprocal_rank": 0.3,
                    "citation_validity": 0.8,
                    "expected_symbol_recall_at_k": 0.4,
                    "citation_precision": 0.5,
                    "source_evidence_sufficient": False,
                },
            ),
        ]
    }
    candidate = {
        "retrieval": [
            _case(
                "path",
                "find path",
                symbols=False,
                metrics={
                    "status": "measured",
                    "measurement_scope": "path_only",
                    "recall_at_k": 1.0,
                    "reciprocal_rank": 1.0,
                    "citation_validity": 1.0,
                },
            ),
            _case(
                "symbol",
                "find symbol",
                symbols=True,
                metrics={
                    "status": "measured",
                    "measurement_scope": "symbol_ast",
                    "recall_at_k": 0.8,
                    "reciprocal_rank": 0.7,
                    "citation_validity": 1.0,
                    "expected_symbol_recall_at_k": 0.9,
                    "citation_precision": 1.0,
                    "source_evidence_sufficient": True,
                },
            ),
        ]
    }

    result = paired_retrieval_delta(baseline, candidate)

    assert result["success"] is True
    assert result["measurement_scope"] == "mixed"
    assert result["case_count"] == 2
    assert result["answer_scope"] == "mixed"
    assert result["aggregates"]["path_only"]["case_count"] == 1
    assert result["aggregates"]["path_only"]["signed_deltas"]["recall_at_k"] == 0.5
    assert result["aggregates"]["symbol_ast"]["case_count"] == 1
    assert result["aggregates"]["symbol_ast"]["signed_deltas"]["expected_symbol_recall_at_k"] == 0.5
    assert result["model_quality_verified"] is False


def test_paired_retrieval_delta_preserves_homogeneous_top_level_shape() -> None:
    baseline = {
        "retrieval": [
            _case(
                "path",
                "find path",
                symbols=False,
                metrics={
                    "status": "measured",
                    "measurement_scope": "path_only",
                    "recall_at_k": 0.5,
                    "reciprocal_rank": 0.5,
                    "citation_validity": 0.5,
                },
            )
        ]
    }
    candidate = {
        "retrieval": [
            _case(
                "path",
                "find path",
                symbols=False,
                metrics={
                    "status": "measured",
                    "measurement_scope": "path_only",
                    "recall_at_k": 1.0,
                    "reciprocal_rank": 1.0,
                    "citation_validity": 1.0,
                },
            )
        ]
    }

    result = paired_retrieval_delta(baseline, candidate)

    assert result["success"] is True
    assert result["measurement_scope"] == "path_only"
    assert result["signed_deltas"]["recall_at_k"] == 0.5
    assert "aggregates" not in result


def test_paired_retrieval_delta_converts_metric_keyerror_to_unverified() -> None:
    class KeyErrorMetrics(dict):
        def get(self, key, default=None):
            if key == "status":
                raise KeyError(key)
            return super().get(key, default)

    result = paired_retrieval_delta(
        {"retrieval": [_case("path", "find path", symbols=False, metrics=KeyErrorMetrics())]},
        {"retrieval": [_case("path", "find path", symbols=False, metrics={"status": "measured"})]},
    )

    assert result["success"] is False
    assert result["status"] == "unverified"
    assert result["reason"] == "'status'"
