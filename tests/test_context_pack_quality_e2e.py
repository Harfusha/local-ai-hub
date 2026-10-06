from __future__ import annotations

from pathlib import Path
import subprocess

import pytest
from local_ai_hub.repo_tools import RepositoryTools
from tools.benchmark_context_pack_quality import RELEVANT, _fixture, run_benchmark


def test_live_fixture_context_pack_quality_and_security(tmp_path: Path) -> None:
    root = tmp_path / "fixture-repo"
    _fixture(root)
    tools = RepositoryTools({"rag": {"extensions": [".py", ".md"]}, "search": {"max_files": 32}})

    result = tools.context_pack_paths(
        str(root), "tenant policy identity context request", ["src", "docs", "vendor"],
        directory_hints=["src", "docs", "vendor"],
        exclude_paths=["vendor/private.py"],
        max_directory_files=16,
        max_tokens=512,
        top_k=8,
    )

    assert result["success"] is True
    paths = [str(item["path"]) for item in result["evidence"]]
    top_three = set(paths[:3])
    assert RELEVANT <= top_three
    assert "vendor/private.py" not in paths
    assert "secret fixture marker" not in result["context"]
    assert result["scanned_files"] <= 5
    assert result["estimated_tokens"] <= 512

    outside = tmp_path / "outside.py"
    outside.write_text("tenant policy identity context request secret", encoding="utf-8")
    traversal = tools.context_pack_paths(str(root), "tenant policy", ["../outside.py"])
    assert traversal["success"] is False
    assert "outside.py" not in str(traversal.get("evidence", []))


@pytest.mark.parametrize("indexed", [False, True], ids=["bounded-fallback", "git-index"])
def test_context_pack_hint_scan_stays_bounded_without_full_inventory(
    tmp_path: Path, monkeypatch, indexed: bool,
) -> None:
    root = tmp_path / ("indexed" if indexed else "fallback")
    _fixture(root)
    if indexed:
        subprocess.run(["git", "init", "--quiet", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "add", "--all"], check=True)
    tools = RepositoryTools({"rag": {"extensions": [".py", ".md"]}, "search": {"max_files": 32}})

    def reject_full_inventory(*_args, **_kwargs):
        raise AssertionError("targeted context pack must not call iter_files")

    monkeypatch.setattr(tools, "iter_files", reject_full_inventory)
    result = tools.context_pack_paths(
        str(root), "tenant policy", ["src"], directory_hints=["src"],
        max_directory_files=1, max_tokens=512, top_k=8,
    )

    assert result["success"] is True
    assert result["scanned_files"] == 1
    assert len({str(item["path"]) for item in result["evidence"]}) <= 1
    assert all(str(item["path"]).startswith("src/") for item in result["evidence"])


def test_fixture_benchmark_reports_cold_warm_and_quality_metrics() -> None:
    report = run_benchmark(repetitions=3)

    assert report["success"] is True
    assert report["precision_at_3"] == 1.0
    assert report["recall_at_3"] == 1.0
    assert report["cold_ms"]["p50"] >= 0
    assert report["cold_ms"]["p95"] >= report["cold_ms"]["p50"]
    assert report["warm_cache"] == {
        "layer": "benchmark_response_cache", "hits": 3, "requests": 3,
    }
    assert report["visited_files"] <= 5
    assert report["output_bytes"] > 0
    assert report["output_tokens_est"] > 0
    assert report["excluded_path_present"] is False
    assert "not exercised" in report["backend_behavior"]
    assert set(report["concurrency"]) == {"1", "4", "16"}
    for scenario in report["concurrency"].values():
        assert scenario["latency_ms"]["p50"] >= 0
        assert scenario["latency_ms"]["p95"] >= scenario["latency_ms"]["p50"]
        assert scenario["cache"]["hits"] == scenario["requests"]
        assert scenario["cache"]["misses"] == 0
        assert scenario["visited_files"] <= 5
        assert scenario["output_bytes"] == report["output_bytes"]
        assert scenario["output_tokens_est"] == report["output_tokens_est"]
        assert scenario["precision_at_3"] == 1.0
        assert scenario["recall_at_3"] == 1.0
