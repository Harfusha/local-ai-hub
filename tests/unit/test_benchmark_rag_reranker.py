from pathlib import Path

from tools import benchmark_rag_reranker


ROOT = Path(__file__).resolve().parents[2]


def test_reranker_benchmark_reuses_verified_positive_search_cases():
    cases = benchmark_rag_reranker.load_benchmark_cases(ROOT)

    assert len(cases) >= 20
    assert all(not case["negative"] for case in cases)
    assert all(case["expected_paths"] for case in cases)
    assert any(case["query"] == "repo_search" for case in cases)
    assert any(case["language"] == "cs" for case in cases)
    assert any(case["language"] == "en" for case in cases)


def test_rank_of_paths_uses_any_manually_relevant_target():
    results = [
        {"path": "src/unrelated.py"},
        {"path": "src/unrelated.py"},
        {"path": "docs/INSTALLATION.md"},
        {"path": "src/local_ai_hub/services.py"},
    ]

    assert benchmark_rag_reranker.rank_of_paths(
        results, ["src/local_ai_hub/services.py", "docs/INSTALLATION.md"]
    ) == 2
    assert benchmark_rag_reranker.rank_of_paths(results, ["missing.py"]) is None


def test_rank_of_paths_does_not_count_duplicate_chunks_as_separate_sources():
    results = [
        {"path": "src/unrelated.py"},
        {"path": "src/unrelated.py"},
        {"path": "docs/INSTALLATION.md"},
    ]

    assert benchmark_rag_reranker.rank_of_paths(results, ["docs/INSTALLATION.md"]) == 2


def test_rank_summary_reports_recall_and_mrr_without_counting_misses():
    summary = benchmark_rag_reranker.rank_summary([1, 3, None], k=3)

    assert summary == {
        "recall_at_3": 2 / 3,
        "mrr": 4 / 9,
        "cases": 3,
        "hits": 2,
    }


def test_rank_summary_does_not_claim_quality_when_reranker_is_unavailable():
    summary = benchmark_rag_reranker.rank_summary([])

    assert summary == {
        "recall_at_8": None,
        "mrr": None,
        "cases": 0,
        "hits": 0,
    }
