from tools.benchmark_rag_reranker import CASES, rank_of_path


def test_rank_of_path_handles_missing_and_duplicate_paths():
    candidates = [{"path": "a"}, {"path": "a"}, {"path": "b"}]
    assert rank_of_path(candidates, "b") == 3
    assert rank_of_path(candidates, "missing") is None


def test_installation_reranker_cases_label_the_installation_document():
    assert [expected for _, expected in CASES[:2]] == [
        "docs/INSTALLATION.md",
        "docs/INSTALLATION.md",
    ]
