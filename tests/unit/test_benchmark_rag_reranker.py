from __future__ import annotations

import pytest

from tools.benchmark_rag_reranker import (
    _benchmark_embeddings,
    benchmark_state_dir,
    local_embedding_model_path,
    offline_device_metrics,
    rank_embeddings,
)


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
