from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from local_ai_hub.preprocess_ingest import SinglePassIngestCache
from local_ai_hub.repo_tools import RepositoryTools


def test_cross_project_ingest_cache_isolation(tmp_path):
    project_a = tmp_path / "project_a"
    project_b = tmp_path / "project_b"
    project_a.mkdir()
    project_b.mkdir()

    (project_a / "config.py").write_text("PROJECT = 'A'\n", encoding="utf-8")
    (project_b / "config.py").write_text("PROJECT = 'B'\n", encoding="utf-8")

    tools = RepositoryTools({})
    cache = SinglePassIngestCache(max_entries=10)

    # Ingest for project A
    file_a = cache.get_or_ingest(project_a, "config.py", tools)
    assert file_a.text.strip() == "PROJECT = 'A'"

    # Ingest for project B - must NOT return cached project A!
    file_b = cache.get_or_ingest(project_b, "config.py", tools)
    assert file_b.text.strip() == "PROJECT = 'B'"

    # Targeted get with root
    assert cache.get("config.py", root=str(project_a)).text.strip() == "PROJECT = 'A'"
    assert cache.get("config.py", root=str(project_b)).text.strip() == "PROJECT = 'B'"


def test_evict_if_needed_does_not_keep_single_oversized_item(tmp_path):
    cache = SinglePassIngestCache(max_entries=5, max_bytes=100)
    # File larger than max_bytes
    large_text = "x" * 200
    cache.put("large.txt", text=large_text)
    assert len(cache) == 0
    assert cache._total_bytes == 0


@pytest.mark.parametrize("root", [None, ""])
def test_invalidate_relative_path_requires_nonempty_root(tmp_path, root):
    project_a = tmp_path / "project_a"
    project_b = tmp_path / "project_b"
    project_a.mkdir()
    project_b.mkdir()

    (project_a / "common.py").write_text("A = 1\n", encoding="utf-8")
    (project_b / "common.py").write_text("B = 2\n", encoding="utf-8")

    tools = RepositoryTools({})
    cache = SinglePassIngestCache(max_entries=10)

    cache.get_or_ingest(project_a, "common.py", tools)
    cache.get_or_ingest(project_b, "common.py", tools)

    with pytest.raises(ValueError, match="root is required"):
        cache.invalidate("common.py", root=root)

    assert cache.has("common.py", root=str(project_a)) is True
    assert cache.has("common.py", root=str(project_b)) is True


def test_invalidate_relative_path_is_scoped_to_root(tmp_path):
    project_a = tmp_path / "project_a"
    project_b = tmp_path / "project_b"
    project_a.mkdir()
    project_b.mkdir()

    (project_a / "common.py").write_text("A = 1\n", encoding="utf-8")
    (project_b / "common.py").write_text("B = 2\n", encoding="utf-8")

    tools = RepositoryTools({})
    cache = SinglePassIngestCache(max_entries=10)

    cache.get_or_ingest(project_a, "common.py", tools)
    cache.get_or_ingest(project_b, "common.py", tools)

    cache.invalidate("common.py", root=str(project_a))

    assert cache.has("common.py", root=str(project_a)) is False
    assert cache.has("common.py", root=str(project_b)) is True
