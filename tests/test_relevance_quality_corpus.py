from __future__ import annotations

import json
from pathlib import Path

import pytest

CORPUS_PATH = Path(__file__).parent / "fixtures" / "relevance_quality_corpus.json"


@pytest.fixture(scope="module")
def corpus_data():
    assert CORPUS_PATH.exists(), f"Corpus fixture missing at {CORPUS_PATH}"
    return json.loads(CORPUS_PATH.read_text(encoding="utf-8"))


def test_corpus_structure_and_minimum_count(corpus_data):
    assert corpus_data.get("schema_version") == "relevance_corpus.v1"
    queries = corpus_data.get("queries", [])
    assert len(queries) >= 100
    assert corpus_data.get("total_queries") == len(queries)

    categories = {q["category"] for q in queries}
    required_categories = {
        "exact_symbol",
        "substring",
        "described_problem_cz",
        "described_problem_en",
        "cross_file_relation",
        "negative_no_match",
        "scope_confinement",
        "minimal_budget",
    }
    assert required_categories.issubset(categories)


def test_corpus_expected_paths_exist_in_repository(corpus_data):
    root = Path(__file__).resolve().parents[1]
    missing_paths = []
    for q in corpus_data["queries"]:
        for expected in q.get("expected_paths", []):
            full_path = root / expected
            if not full_path.exists():
                missing_paths.append((q["id"], expected))
    assert not missing_paths, f"Expected corpus paths do not exist: {missing_paths}"


def test_corpus_exact_symbols_present_in_expected_files(corpus_data):
    root = Path(__file__).resolve().parents[1]
    symbol_mismatches = []
    exact_queries = [q for q in corpus_data["queries"] if q["category"] == "exact_symbol"]
    assert len(exact_queries) >= 15

    for q in exact_queries:
        for expected_path, expected_sym in zip(q["expected_paths"], q["expected_symbols"]):
            content = (root / expected_path).read_text(encoding="utf-8", errors="ignore")
            if expected_sym not in content:
                symbol_mismatches.append((q["id"], expected_sym, expected_path))

    assert not symbol_mismatches, f"Symbols not found in files: {symbol_mismatches}"


def test_corpus_negative_queries_have_zero_expected_results(corpus_data):
    neg_queries = [q for q in corpus_data["queries"] if q["category"] == "negative_no_match"]
    assert len(neg_queries) >= 15
    for q in neg_queries:
        assert q["negative"] is True
        assert len(q["expected_paths"]) == 0
        assert len(q["expected_symbols"]) == 0


def test_corpus_bilingual_coverage(corpus_data):
    queries = corpus_data["queries"]
    cz_queries = [q for q in queries if q.get("language") == "cz"]
    en_queries = [q for q in queries if q.get("language") == "en"]
    assert len(cz_queries) >= 15, "Insufficient Czech queries"
    assert len(en_queries) >= 15, "Insufficient English queries"
