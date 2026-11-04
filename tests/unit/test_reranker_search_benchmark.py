from __future__ import annotations

import math

import pytest

from tools.benchmark_reranker import CASES, evaluate_ranking, validate_cases
from tools import benchmark_reranker


def test_reranker_metrics_measure_order_and_relevance():
    result = evaluate_ranking(["noise", "target", "target"], ["target"])

    assert result["recall_at_k"] == 1.0
    assert result["precision_at_k"] == 0.5
    assert result["reciprocal_rank"] == 0.5
    assert result["ndcg_at_k"] == pytest.approx(1 / math.log2(3))


def test_reranker_query_set_has_verified_english_and_czech_cases():
    validate_cases(CASES)

    queries = [case["query"] for case in CASES]
    assert any("install" in query.lower() for query in queries)
    assert any("Jak " in query for query in queries)
    assert any("velikost" in query.lower() for query in queries)


def test_reranker_query_set_rejects_missing_labels_or_duplicate_candidate_ids():
    invalid = [{"query": "x", "candidates": [
        {"id": "same", "text": "a"}, {"id": "same", "text": "b"},
    ], "relevant_ids": ["missing"]}]

    with pytest.raises(ValueError):
        validate_cases(invalid)


def test_benchmark_respects_disabled_active_reranker_config(monkeypatch):
    seen = {}

    class DisabledReranker:
        def __init__(self, config):
            seen["enabled"] = config["features"]["reranker"]
            self.model_name = "disabled"
            self.device = "cpu"
            self.active_backend = self.active_device = None
            self._cache_hits = 0

        def rerank(self, *_args, **_kwargs):
            return {"success": False, "results": []}

        def is_loaded(self):
            return False

        def is_enabled(self):
            return False

    monkeypatch.setattr(benchmark_reranker, "load_config", lambda *_args, **_kwargs: {
        "hardware": {"profile": "high"}, "models": {}, "features": {"reranker": False},
    })
    monkeypatch.setattr(benchmark_reranker, "Reranker", DisabledReranker)

    result = benchmark_reranker.run(repeats=1)

    assert seen["enabled"] is False
    assert result["reranker_enabled"] is False
