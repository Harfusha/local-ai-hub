import importlib
import os


def _benchmark_module():
    offline_env = {key: os.environ.get(key) for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")}
    try:
        return importlib.import_module("tools.benchmark_rag_reranker")
    finally:
        for key, value in offline_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_unrun_embedding_cases_do_not_report_zero_recall():
    benchmark = _benchmark_module()
    rows = [
        {
            "offline_embedding_rank": None,
            "offline_embedding_metrics": {"successful_repeats": 0},
        },
        {
            "offline_embedding_rank": None,
            "offline_embedding_metrics": {"successful_repeats": 0},
        },
    ]

    assert benchmark.offline_embedding_rank_summary(rows, model_configured=True) is None


def test_successful_embedding_miss_counts_as_zero_recall():
    benchmark = _benchmark_module()
    rows = [
        {
            "expected_paths": ["target"],
            "offline_embedding_rank": None,
            "offline_embedding_ranked_paths": ["noise"],
            "offline_embedding_metrics": {"successful_repeats": 1},
        },
    ]

    assert benchmark.offline_embedding_rank_summary(rows, model_configured=True) == {
        "recall_at_8": 0.0,
        "recall_at_5": 0.0,
        "recall_at_10": 0.0,
        "ndcg_at_10": 0.0,
        "mrr": 0.0,
        "cases": 1,
        "hits": 0,
    }
