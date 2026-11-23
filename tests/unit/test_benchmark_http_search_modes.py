from __future__ import annotations

import pytest

from tools.benchmark_http_search import build_search_payload, search_coverage_metadata
from tools.benchmark_search_quality import make_holdout_fixture, noise_language_counts


def test_default_benchmark_payload_uses_endpoint_default_mode():
    assert build_search_payload("C:/repo", "Local AI Hub installation", "default") == {
        "root": "C:/repo",
        "query": "Local AI Hub installation",
        "limit": 10,
    }


@pytest.mark.parametrize("mode", ["lexical", "rag", "hybrid"])
def test_benchmark_payload_can_select_an_explicit_search_mode(mode: str):
    assert build_search_payload("C:/repo", "C++", mode) == {
        "root": "C:/repo",
        "query": "C++",
        "limit": 10,
        "search_mode": mode,
    }


def test_benchmark_rejects_unknown_search_mode():
    with pytest.raises(ValueError, match="search_mode"):
        build_search_payload("C:/repo", "query", "semantic")


def test_benchmark_preserves_incomplete_search_coverage_metadata():
    row = search_coverage_metadata({
        "success": True,
        "results": [],
        "coverage_complete": False,
        "truncated": True,
        "truncation_reasons": ["file_limit"],
        "scanned_files": 8000,
    })

    assert row["coverage_complete"] is False
    assert row["truncated"] is True
    assert row["truncation_reasons"] == ["file_limit"]
    assert row["scanned_files"] == 8000


def test_holdout_fixture_covers_php_python_and_typescript(tmp_path):
    cases = make_holdout_fixture(tmp_path, noise_files=20)

    assert {"src/access.php", "src/component.tsx", "src/db.py"}.issubset(
        {path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*") if path.is_file()}
    )
    assert {"src/access.php", "src/component.tsx"}.issubset(
        {path for case in cases for path in case["relevant"]}
    )
    noise_suffixes = [path.suffix for path in (tmp_path / "noise").iterdir()]
    assert {".php", ".py", ".tsx"}.issubset(noise_suffixes)
    assert noise_language_counts(20) == {"php": 1, "python": 18, "tsx": 1}
