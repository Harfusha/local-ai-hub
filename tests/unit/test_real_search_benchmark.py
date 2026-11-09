import pytest

from tools import benchmark_real_search
from tools.benchmark_real_search import validate_cases


def test_real_benchmark_checks_ground_truth_against_source(tmp_path):
    (tmp_path / "module.py").write_text("def worker():\n    pass\n", encoding="utf-8")
    validate_cases(tmp_path, [{"query": "worker", "path": "module.py", "source_text": "def worker"}])
    with pytest.raises(ValueError, match="source_text"):
        validate_cases(tmp_path, [{"query": "worker", "path": "module.py", "source_text": "def other"}])
    with pytest.raises(ValueError, match="path"):
        validate_cases(tmp_path, [{"query": "worker", "path": "../outside.py", "source_text": "worker"}])


def test_real_benchmark_reports_live_source_cache_bypass(tmp_path, monkeypatch):
    (tmp_path / "module.py").write_text("def worker():\n    pass\n", encoding="utf-8")
    monkeypatch.setattr(benchmark_real_search, "CASES", [{"query": "worker", "path": "module.py", "source_text": "def worker"}])
    result = benchmark_real_search.run(tmp_path, repeats=2, use_cache=True)
    assert result["cases"][0]["cache_hits"] == [False, False]
    assert result["cases"][0]["p95_ms"] >= result["cases"][0]["median_ms"]
    assert result["cases"][0]["engine"]
    assert result["cases"][0]["terms"]
    assert result["cases"][0]["top_results"][0]["path"] == "module.py"


def test_real_benchmark_can_measure_without_cache(tmp_path, monkeypatch):
    (tmp_path / "module.py").write_text("def worker():\n    pass\n", encoding="utf-8")
    monkeypatch.setattr(benchmark_real_search, "CASES", [{"query": "worker", "path": "module.py", "source_text": "def worker"}])

    result = benchmark_real_search.run(tmp_path, repeats=1, use_cache=False)

    assert result["cases"][0]["rank"] == 1


def test_real_benchmark_reports_degraded_hybrid_without_semantic_backend(tmp_path, monkeypatch):
    (tmp_path / "module.py").write_text("def worker():\n    pass\n", encoding="utf-8")
    monkeypatch.setattr(benchmark_real_search, "CASES", [{"query": "worker", "path": "module.py", "source_text": "def worker"}])

    result = benchmark_real_search.run(tmp_path, repeats=1, use_cache=False, search_mode="hybrid")

    row = result["cases"][0]
    assert row["search_mode"] == "hybrid"
    assert row["result_source"] in {"lexical_fallback", "lexical"}


def test_real_benchmark_records_unavailable_explicit_rag_mode(tmp_path, monkeypatch):
    (tmp_path / "module.py").write_text("def worker():\n    pass\n", encoding="utf-8")
    monkeypatch.setattr(benchmark_real_search, "CASES", [{
        "query": "worker", "path": "module.py", "source_text": "def worker",
    }])

    result = benchmark_real_search.run(
        tmp_path, repeats=1, use_cache=False, search_mode="rag",
    )

    row = result["cases"][0]
    assert row["success"] is False
    assert row["degraded"] is True
    assert row["degradation_reason"]
    assert row["rank"] is None


def test_hybrid_fallback_keeps_original_installation_word(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "INSTALLATION.md").write_text("# Installation\n", encoding="utf-8")
    monkeypatch.setattr(
        benchmark_real_search,
        "CASES",
        [{"query": "Local AI Hub installation", "path": "docs/INSTALLATION.md", "source_text": "# Installation"}],
    )

    result = benchmark_real_search.run(tmp_path, repeats=1, use_cache=False, search_mode="hybrid")

    assert result["cases"][0]["rank"] == 1
