from __future__ import annotations

import pytest

from tools import benchmark_live_search
from tools.benchmark_live_search import evaluate_case, load_cases, validate_cases


def test_live_query_set_is_independent_bilingual_and_source_anchored():
    cases = load_cases()
    validate_cases(ROOT, cases)

    assert len(cases) >= 8
    assert any(case["language"] == "cs" for case in cases)
    assert any(case["language"] == "en" for case in cases)
    assert any(case["query"] == "repo_search" for case in cases)
    assert any(case["negative"] for case in cases)
    negative = next(case for case in cases if case["id"] == "negative-unknown-symbol")
    assert negative["query"] not in benchmark_live_search.CASE_FILE.read_text(encoding="utf-8")


def test_live_query_labels_reject_broken_source_anchors():
    with pytest.raises(ValueError, match="anchor"):
        validate_cases(ROOT, [{
            "id": "invalid-anchor",
            "query": "repo_search", "expected_paths": ["src/local_ai_hub/services.py"],
            "evidence": [{"path": "src/local_ai_hub/services.py", "anchor": "def never_exists("}],
        }])


def test_live_metrics_deduplicate_paths_and_score_negative_cases():
    case = {"expected_paths": ["src/target.py"], "negative": False}
    assert evaluate_case([{"path": "src/noise.py"}, {"path": "src/target.py"},
                          {"path": "src/target.py"}], case)["reciprocal_rank"] == 0.5
    assert evaluate_case([], {"expected_paths": [], "negative": True})["negative_correct"] is True
    assert evaluate_case([{"path": "src/noise.py"}], {"expected_paths": [], "negative": True})["negative_correct"] is False


def test_live_benchmark_reports_progress_after_each_request(monkeypatch, capsys):
    monkeypatch.setattr(benchmark_live_search, "load_config", lambda **kwargs: {
        "server": {"bind": "127.0.0.1", "port": 11435}, "security": {},
        "hardware": {"profile": "high"}, "features": {"reranker": True}, "models": {},
    })
    monkeypatch.setattr(benchmark_live_search, "_request", lambda *args: (200, {
        "success": True, "results": [{"path": "src/local_ai_hub/services.py"}],
        "cache_hit": False,
        "result_source": "lexical",
        "rag_search_skipped": True,
        "rag_skip_reason": "exact_lexical_precision",
    }))
    case = {"id": "progress-case", "query": "repo_search", "language": "en",
            "expected_paths": ["src/local_ai_hub/services.py"], "negative": False,
            "evidence": [{"path": "src/local_ai_hub/services.py", "anchor": "def repo_search("}]}

    result = benchmark_live_search.run(root=ROOT, modes=("lexical",), repeats=1, cases=[case], progress=True)

    assert "lexical progress-case 1/1 HTTP 200" in capsys.readouterr().err
    row = result["cases"][0]
    assert row["result_source"] == "lexical"
    assert row["rag_search_skipped"] is True
    assert row["rag_skip_reason"] == "exact_lexical_precision"


ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]
