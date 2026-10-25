from __future__ import annotations

from pathlib import Path

import pytest

from local_ai_hub.repo_tools import RepositoryTools


@pytest.fixture
def repo_with_files(tmp_path: Path) -> tuple[RepositoryTools, str]:
    root = tmp_path / "test_repo"
    root.mkdir(parents=True, exist_ok=True)
    src = root / "src"
    src.mkdir(parents=True, exist_ok=True)

    # Create several files with search terms
    (src / "module_a.py").write_text(
        "def compute_alpha():\n    return 'alpha_value'\n",
        encoding="utf-8",
    )
    (src / "module_b.py").write_text(
        "def compute_beta():\n    return compute_alpha() + '_beta'\n",
        encoding="utf-8",
    )
    (src / "module_c.py").write_text(
        "class AlphaBetaRunner:\n    pass\n",
        encoding="utf-8",
    )

    tools = RepositoryTools({"rag": {"extensions": [".py"]}})
    return tools, str(root)


def test_search_path_resolution_caching_eliminates_repeated_resolves(repo_with_files: tuple[RepositoryTools, str]):
    tools, root = repo_with_files

    # First search populates resolution cache
    res1 = tools.search(root, "compute_alpha", limit=10)
    assert res1["success"] is True
    assert res1["matches_count"] >= 2

    # Check cache has entries
    with tools._resolved_paths_lock:
        cache_count = len(tools._resolved_paths)
    assert cache_count > 0

    # Second search with another term in the same files reuses resolved path cache
    res2 = tools.search(root, "compute_beta", limit=10)
    assert res2["success"] is True

    # Parity check: results have exact structure
    for hit in res1["results"] + res2["results"]:
        assert "path" in hit
        assert "score" in hit
        assert "text" in hit
        assert not hit["path"].startswith("/")
        assert ".." not in hit["path"]


def test_path_escape_attempt_is_rejected_and_cached_as_none(repo_with_files: tuple[RepositoryTools, str]):
    tools, root = repo_with_files
    base = Path(root)

    # Attempt resolving a path outside base
    res = tools._resolve_under_base(base, "../../outside_secret.txt")
    assert res is None

    # Cached failure
    with tools._resolved_paths_lock:
        assert (str(base), "../../outside_secret.txt") in tools._resolved_paths
        assert tools._resolved_paths[(str(base), "../../outside_secret.txt")] is None


def test_invalidate_snapshot_clears_resolved_path_cache(repo_with_files: tuple[RepositoryTools, str]):
    tools, root = repo_with_files
    base = Path(root)

    # Populate cache
    tools._resolve_under_base(base, "src/module_a.py")
    with tools._resolved_paths_lock:
        assert len(tools._resolved_paths) > 0

    # Invalidate
    tools.invalidate_snapshot(base / "src/module_a.py")
    with tools._resolved_paths_lock:
        assert len(tools._resolved_paths) == 0
