import time
from pathlib import Path
import pytest
from local_ai_hub.preprocess_ingest import SinglePassIngestCache, IngestedFile
from local_ai_hub.repo_tools import RepositoryTools


def test_single_pass_ingest_caches_and_avoids_repeated_reads(tmp_path: Path):
    f = tmp_path / "hello.py"
    f.write_text("x = 1\ny = 2\n", encoding="utf-8")
    tools = RepositoryTools({})
    cache = SinglePassIngestCache(max_entries=10)

    ingested1 = cache.get_or_ingest(tmp_path, "hello.py", tools)
    assert isinstance(ingested1, IngestedFile)
    assert ingested1.content_hash != ""
    assert ingested1.text == "x = 1\ny = 2"
    assert ingested1.lines == ("x = 1", "y = 2")
    assert ingested1.ast_tree is not None

    # Modify file on disk without invalidating cache
    f.write_text("x = 999\n", encoding="utf-8")
    ingested2 = cache.get_or_ingest(tmp_path, "hello.py", tools)
    # Should return cached version
    assert ingested2.text == "x = 1\ny = 2"
    assert ingested1 is ingested2

    # Invalidate and re-read
    cache.invalidate("hello.py")
    tools.invalidate_snapshot(f)
    ingested3 = cache.get_or_ingest(tmp_path, "hello.py", tools)
    assert ingested3.text == "x = 999"


def test_single_pass_ingest_lru_bounds(tmp_path: Path):
    tools = RepositoryTools({})
    cache = SinglePassIngestCache(max_entries=3)
    for i in range(5):
        p = tmp_path / f"file_{i}.txt"
        p.write_text(f"content {i}\n", encoding="utf-8")
        cache.get_or_ingest(tmp_path, f"file_{i}.txt", tools)

    assert len(cache) <= 3
    # file_0 and file_1 should have been evicted
    assert cache.has("file_4.txt")
    assert cache.has("file_3.txt")
