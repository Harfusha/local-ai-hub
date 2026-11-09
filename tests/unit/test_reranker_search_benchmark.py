from __future__ import annotations

import math

import pytest

from tools.benchmark_reranker import CASES, cache_state, evaluate_ranking, validate_cases
from tools import benchmark_reranker


def test_reranker_metrics_measure_order_and_relevance():
    result = evaluate_ranking(["noise", "target", "target"], ["target"])

    assert result["recall_at_k"] == 1.0
    assert result["precision_at_k"] == 0.5
    assert result["reciprocal_rank"] == 0.5
    assert result["ndcg_at_k"] == pytest.approx(1 / math.log2(3))


def test_reranker_benchmark_distinguishes_full_warm_hits_from_mixed_calls():
    assert cache_state({"cache_enabled": True, "cache_hits": 3, "computed": 0}, 3) == "warm_hit"
    assert cache_state({"cache_enabled": True, "cache_hits": 1, "computed": 2}, 3) == "mixed_hit_and_inference"
    assert cache_state({"cache_enabled": True, "cache_hits": 0, "computed": 3}, 3) == "inference_or_cold"


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
    assert result["model_loaded_at_start"] is False
    assert result["cases"][0]["samples"][0]["model_load_included"] is True


def test_benchmark_measures_uncached_inference_then_cached_latency(monkeypatch):
    calls = []

    class Reranker:
        def __init__(self, _config):
            self.model_name = "test-reranker"
            self.device = "cuda"
            self.active_backend = "torch"
            self.active_device = "cuda"
            self.cache_enabled = True

        def rerank(self, _query, documents, **_kwargs):
            calls.append(self.cache_enabled)
            return {
                "success": True,
                "results": [{"index": i, "score": float(len(documents) - i)} for i in range(len(documents))],
                "cache_enabled": self.cache_enabled,
                "cache_hits": len(documents) if self.cache_enabled else 0,
                "computed": 0 if self.cache_enabled else len(documents),
            }

        def is_loaded(self):
            return True

        def is_enabled(self):
            return True

        def release(self):
            pass

    monkeypatch.setattr(benchmark_reranker, "load_config", lambda *_args, **_kwargs: {
        "hardware": {"profile": "high"}, "models": {}, "features": {"reranker": True},
    })
    monkeypatch.setattr(benchmark_reranker, "Reranker", Reranker)
    monkeypatch.setattr(benchmark_reranker, "CASES", [CASES[0]])

    result = benchmark_reranker.run(repeats=1)

    assert calls == [False, True]
    case = result["cases"][0]
    assert case["inference_sample"]["cache_state"] == "bypassed_for_inference"
    assert case["inference_sample"]["model_load_included"] is False
    assert case["inference_sample"]["computed"] == len(CASES[0]["candidates"])
    assert case["samples"][0]["cache_state"] == "warm_hit"
    assert case["reranker_success"] is True


def test_benchmark_separates_failed_cold_ranking_from_warm_cache(monkeypatch):
    class FailingInferenceReranker:
        def __init__(self, _config):
            self.model_name = "test-reranker"
            self.device = "cuda"
            self.active_backend = "torch"
            self.active_device = "cuda"
            self.cache_enabled = True

        def rerank(self, _query, documents, **_kwargs):
            if not self.cache_enabled:
                return {
                    "success": False,
                    "error": "GPU inference timed out",
                    "results": [],
                    "cache_enabled": False,
                    "computed": None,
                }
            return {
                "success": True,
                "results": [
                    {"index": index, "score": float(index)}
                    for index in range(len(documents))
                ],
                "cache_enabled": True,
                "cache_hits": len(documents),
                "computed": 0,
            }

        def is_loaded(self):
            return True

        def is_enabled(self):
            return True

        def release(self):
            pass

    monkeypatch.setattr(benchmark_reranker, "load_config", lambda *_args, **_kwargs: {
        "hardware": {"profile": "high"}, "models": {}, "features": {"reranker": True},
    })
    monkeypatch.setattr(benchmark_reranker, "Reranker", FailingInferenceReranker)
    monkeypatch.setattr(benchmark_reranker, "CASES", [CASES[0]])

    result = benchmark_reranker.run(repeats=1)
    case = result["cases"][0]

    assert case["inference_sample"]["success"] is False
    assert case["inference_sample"]["error"] == "GPU inference timed out"
    assert case["reranked_order"] is None
    assert case["reranked"] is None
    assert case["samples"][0]["cache_state"] == "warm_hit"
    assert case["samples"][0]["ranked_order"] == ["install", "index", "search"]
    assert case["latency_by_cache_state"]["warm_hit"]["sample_count"] == 1
    assert case["reranker_success"] is False
