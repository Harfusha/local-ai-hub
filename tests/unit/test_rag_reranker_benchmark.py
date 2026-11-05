from pathlib import Path

from tools.benchmark_rag_reranker import load_benchmark_cases, rank_of_path


def test_rank_of_path_handles_missing_and_duplicate_paths():
    candidates = [{"path": "a"}, {"path": "a"}, {"path": "b"}]
    assert rank_of_path(candidates, "b") == 3
    assert rank_of_path(candidates, "missing") is None


def test_installation_reranker_cases_label_the_installation_document():
    cases = load_benchmark_cases(Path.cwd())
    installation_cases = [
        case for case in cases
        if case.get("id") in {"english-installation", "english-install-without-ollama"}
    ]
    assert [case["expected_paths"][0] for case in installation_cases] == [
        "docs/INSTALLATION.md", "docs/INSTALLATION.md",
    ]
