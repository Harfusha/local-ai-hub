from __future__ import annotations

import math
from pathlib import Path

import pytest

from tools.benchmark_rag_reranker import (
    _benchmark_embeddings,
    _offline_embedding_candidates,
    benchmark_state_dir,
    load_benchmark_dataset,
    local_embedding_model_path,
    negative_candidate_summary,
    offline_device_metrics,
    offline_embedding_rank_summary,
    rank_embeddings,
)


def test_embedding_quality_summary_reports_recall_mrr_and_ndcg() -> None:
    rows = [
        {
            "expected_paths": ["relevant-a", "relevant-b"],
            "offline_embedding_rank": 2,
            "offline_embedding_ranked_paths": ["noise", "relevant-a", "relevant-b"],
            "offline_embedding_metrics": {"successful_repeats": 2},
        },
        {
            "expected_paths": ["relevant-c"],
            "offline_embedding_rank": 1,
            "offline_embedding_ranked_paths": ["relevant-c"],
            "offline_embedding_metrics": {"successful_repeats": 1},
        },
        {
            "expected_paths": ["unmeasured"],
            "offline_embedding_rank": None,
            "offline_embedding_ranked_paths": [],
            "offline_embedding_metrics": {"successful_repeats": 0},
        },
    ]

    summary = offline_embedding_rank_summary(rows, model_configured=True)

    assert summary["recall_at_5"] == 1.0
    assert summary["recall_at_10"] == 1.0
    assert summary["mrr"] == pytest.approx(0.75)
    expected_first_ndcg = (
        1 / math.log2(3) + 1 / math.log2(4)
    ) / (1 + 1 / math.log2(3))
    assert summary["ndcg_at_10"] == pytest.approx((expected_first_ndcg + 1) / 2)
    assert summary["cases"] == 2


def test_negative_candidate_summary_counts_only_successful_lexical_queries() -> None:
    summary = negative_candidate_summary([
        {"candidate_source": "lexical", "candidate_count": 3},
        {"candidate_source": "lexical_empty", "candidate_count": 0},
        {"candidate_source": "rag_fallback", "candidate_count": 5},
        {"candidate_source": "lexical_unavailable", "candidate_count": 0},
    ])

    assert summary == {
        "negative_cases": 4,
        "lexical_cases_evaluated": 2,
        "candidate_false_positive_cases": 1,
        "candidate_false_positive_rate": 0.5,
    }


def test_source_anchored_dataset_covers_bilingual_polyglot_plan() -> None:
    root = Path(__file__).resolve().parents[2]
    dataset, cases = load_benchmark_dataset(root)
    by_id = {case["id"]: case for case in dataset["cases"]}

    assert len(dataset["cases"]) == 50
    assert len(cases) == 45
    assert dataset["case_set"] == "agent-search-manual-2026-11-13-v3"
    assert sum(case["language"] == "cs" for case in cases) == 20
    assert sum(case["language"] == "en" for case in cases) == 19
    assert sum(case["language"] == "symbol" for case in cases) == 6
    assert by_id["english-czech-audit-typescript"]["expected_paths"] == [
        "docs/AUDIT_ROUND_3_2026-11-08.md",
    ]
    assert by_id["czech-cakephp-detection"]["expected_paths"] == [
        "src/local_ai_hub/repo_tools.py",
    ]
    assert by_id["english-php8-outline"]["expected_paths"] == [
        "tests/test_php_js_ts_support.py",
    ]


class _SearchClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, path, payload, timeout):
        self.calls.append((path, payload, timeout))
        return self.response


def test_offline_candidates_use_lexical_pool_even_when_rag_has_candidates(tmp_path) -> None:
    client = _SearchClient({"success": True, "results": [{"path": "lexical.md", "text": "Lexical"}]})
    source = {"results": [{"path": "rag.md", "text": "RAG"}], "result_source": "rag"}

    candidates, candidate_source = _offline_embedding_candidates(client, tmp_path, "find setup", source)

    assert candidates == client.response["results"]
    assert candidate_source == "lexical"
    assert client.calls == [(
        "/api/search",
        {"root": str(tmp_path), "query": "find setup", "search_mode": "lexical", "limit": 10, "offset": 0},
        30,
    )]


def test_offline_candidates_use_rag_when_lexical_search_fails(tmp_path) -> None:
    client = _SearchClient({"success": False, "results": [], "error": "offline"})
    source = {"results": [{"path": "rag.md", "text": "RAG"}], "result_source": "rag"}

    candidates, candidate_source = _offline_embedding_candidates(
        client, tmp_path, "find setup", source,
    )

    assert candidates == source["results"]
    assert candidate_source == "rag_fallback"
    assert client.calls == [(
        "/api/search",
        {"root": str(tmp_path), "query": "find setup", "search_mode": "lexical", "limit": 10, "offset": 0},
        30,
    )]


def test_offline_candidates_distinguish_successful_empty_lexical_results(tmp_path) -> None:
    client = _SearchClient({"success": True, "results": []})

    candidates, candidate_source = _offline_embedding_candidates(
        client, tmp_path, "unknown query", {},
    )

    assert candidates == []
    assert candidate_source == "lexical_empty"


def test_offline_cuda_metrics_report_cpu_fallback_and_successful_throughput() -> None:
    report = offline_device_metrics(
        "cuda",
        {"device": "cpu", "backend": "torch"},
        [
            {"latency_ms": 100.0, "phase": "cold", "success": True},
            {"latency_ms": 200.0, "phase": "warm", "success": True},
            {"latency_ms": 900.0, "phase": "rejected", "success": False},
        ],
        candidate_count=4,
    )

    assert report["requested_device"] == "cuda"
    assert report["actual_device"] == "cpu"
    assert report["fallback_observed"] is True
    assert report["latency"] == {"median_ms": 150.0, "p95_ms": 200.0}
    assert report["cold_latency_ms"] == 100.0
    assert report["warm_latency"] == {"median_ms": 200.0, "p95_ms": 200.0}
    assert report["candidates_per_second"] == pytest.approx(4 * 2 * 1000 / 300)
    assert report["successful_repeats"] == 2


def test_offline_cuda_metrics_leave_actual_device_unknown_on_admission_failure() -> None:
    report = offline_device_metrics(
        "cuda",
        {"success": False, "error_code": "gpu_reserved"},
        [{"latency_ms": 1.0, "phase": "rejected", "success": False}],
        candidate_count=4,
    )

    assert report["actual_device"] is None
    assert report["fallback_observed"] is None
    assert report["candidates_per_second"] is None
    assert report["successful_repeats"] == 0


def test_offline_cpu_metrics_do_not_report_cuda_fallback() -> None:
    report = offline_device_metrics(
        "cpu",
        {"device": "cpu", "backend": "torch"},
        [{"latency_ms": 50.0, "phase": "cold", "success": True}],
        candidate_count=2,
    )

    assert report["fallback_observed"] is None
    assert report["candidates_per_second"] == 40.0


def test_offline_metrics_do_not_count_empty_candidate_noop_as_device_success() -> None:
    report = offline_device_metrics(
        "cuda",
        {"success": True, "device": "cuda", "backend": "torch"},
        [{"latency_ms": 0.001, "phase": "cold", "success": True}],
        candidate_count=0,
    )

    assert report["actual_device"] is None
    assert report["backend"] is None
    assert report["fallback_observed"] is None
    assert report["latency"] == {"median_ms": None, "p95_ms": None}
    assert report["cold_latency_ms"] is None
    assert report["warm_latency"] == {"median_ms": None, "p95_ms": None}
    assert report["candidates_per_second"] is None
    assert report["successful_repeats"] == 0


def test_cpu_benchmark_keeps_isolated_state_without_reading_hub_config(tmp_path) -> None:
    assert benchmark_state_dir(tmp_path / "missing.toml", "cpu", "isolated") == "isolated"


def test_cuda_benchmark_requires_absolute_shared_state_dir(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text('[server]\nstate_dir = "state"\n', encoding="utf-8")

    with pytest.raises(ValueError, match="absolute server.state_dir"):
        benchmark_state_dir(config_path, "cuda", "isolated")


def test_cuda_benchmark_uses_explicit_shared_state_dir(tmp_path) -> None:
    shared_state = tmp_path / "hub-state"
    config_path = tmp_path / "config.toml"
    config_path.write_text(f'[server]\nstate_dir = "{shared_state.as_posix()}"\n', encoding="utf-8")

    assert benchmark_state_dir(config_path, "cuda", "isolated") == str(shared_state)


def test_rank_embeddings_uses_cosine_similarity_for_unnormalized_vectors() -> None:
    ranked = rank_embeddings(
        [3.0, 4.0],
        [[1.0, 0.0], [0.6, 0.8], [-3.0, -4.0]],
        [{"path": "off-axis"}, {"path": "match"}, {"path": "opposite"}],
    )

    assert [item["path"] for item in ranked] == ["match", "off-axis", "opposite"]


def test_rank_embeddings_rejects_invalid_or_inconsistent_vectors() -> None:
    with pytest.raises(ValueError, match="same nonzero dimension"):
        rank_embeddings([1.0, 0.0], [[1.0], [0.0]], [{}, {}])
    with pytest.raises(ValueError, match="finite nonzero norm"):
        rank_embeddings([0.0, 0.0], [[1.0, 0.0]], [{}])


def test_embedding_model_path_requires_existing_local_directory(tmp_path) -> None:
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    assert local_embedding_model_path(model_dir) == model_dir.resolve()

    with pytest.raises(ValueError, match="existing local directory"):
        local_embedding_model_path(tmp_path / "missing")


def test_embedding_benchmark_ranks_candidates_and_reports_device() -> None:
    class StubEmbeddingModel:
        def encode(self, texts, query=False):
            common = {
                "success": True, "backend": "sentence-transformers", "device": "cpu",
                "embedding_space_id": "local-model:v1",
            }
            if query:
                return {**common, "embeddings": [[1.0, 0.0]]}
            return {**common, "embeddings": [[0.0, 1.0], [1.0, 0.0]]}

    candidates = [{"path": "weak", "text": "weak"}, {"path": "match", "text": "match"}]
    ranked, samples, metrics, cold_recorded = _benchmark_embeddings(
        StubEmbeddingModel(), "query", candidates, repeats=2, requested_device="cpu",
    )

    assert [item["path"] for item in ranked] == ["match", "weak"]
    assert [sample["phase"] for sample in samples] == ["cold", "warm"]
    assert metrics["actual_device"] == "cpu"
    assert metrics["embedding_space_match"] is True
    assert metrics["successful_repeats"] == 2
    assert cold_recorded is True

    _ranked, later_samples, _metrics, _cold_recorded = _benchmark_embeddings(
        StubEmbeddingModel(), "next query", candidates, repeats=1, requested_device="cpu",
        cold_inference_recorded=cold_recorded,
    )
    assert later_samples[0]["phase"] == "warm"


def test_embedding_benchmark_discards_rank_if_admission_fails() -> None:
    class DeniedEmbeddingModel:
        def encode(self, texts, query=False):
            return {"success": False, "error_code": "gpu_reserved", "error": "GPU admission is unavailable"}

    ranked, samples, metrics, cold_recorded = _benchmark_embeddings(
        DeniedEmbeddingModel(), "query", [{"path": "match", "text": "match"}],
        repeats=2, requested_device="cuda",
    )

    assert ranked == []
    assert len(samples) == 1
    assert samples[0]["success"] is False
    assert metrics["actual_device"] is None
    assert metrics["fallback_observed"] is None
    assert cold_recorded is False


def test_embedding_benchmark_rejects_empty_candidate_set_without_inference() -> None:
    class UnexpectedEmbeddingModel:
        def encode(self, texts, query=False):
            raise AssertionError("empty-candidate benchmark must not run inference")

    ranked, samples, metrics, cold_recorded = _benchmark_embeddings(
        UnexpectedEmbeddingModel(), "query", [], repeats=2, requested_device="cuda",
    )

    assert ranked == []
    assert len(samples) == 1
    assert samples[0]["success"] is False
    assert samples[0]["error"] == "no_candidates"
    assert metrics["actual_device"] is None
    assert metrics["embeddings_per_second"] is None
    assert metrics["successful_repeats"] == 0
    assert cold_recorded is False
