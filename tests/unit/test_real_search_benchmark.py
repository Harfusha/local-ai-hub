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


def test_real_benchmark_can_measure_cold_and_warm_cache(tmp_path, monkeypatch):
    (tmp_path / "module.py").write_text("def worker():\n    pass\n", encoding="utf-8")
    monkeypatch.setattr(benchmark_real_search, "CASES", [{"query": "worker", "path": "module.py", "source_text": "def worker"}])
    result = benchmark_real_search.run(tmp_path, repeats=2, use_cache=True)
    assert result["cases"][0]["cache_hits"] == [False, True]
