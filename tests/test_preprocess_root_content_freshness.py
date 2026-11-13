from __future__ import annotations

import os
from pathlib import Path

from local_ai_hub.preprocess_ingest import SinglePassIngestCache
from local_ai_hub.repo_tools import RepositoryTools


def test_same_relative_path_stays_root_scoped_and_revalidates_same_stat_content(
    tmp_path: Path,
    monkeypatch,
) -> None:
    first_root = tmp_path / "project-a"
    second_root = tmp_path / "project-b"
    first_root.mkdir()
    second_root.mkdir()
    first_path = first_root / "same.py"
    second_path = second_root / "same.py"
    first_path.write_text("marker = 'alpha'\n", encoding="utf-8")
    second_path.write_text("marker = 'bravo'\n", encoding="utf-8")

    tools = RepositoryTools({})
    monkeypatch.setattr(tools, "_windows_change_time", lambda _path: None)
    cache = SinglePassIngestCache()

    first = cache.get_or_ingest(first_root, "same.py", tools)
    second = cache.get_or_ingest(second_root, "same.py", tools)
    assert first.text == "marker = 'alpha'"
    assert second.text == "marker = 'bravo'"
    assert first.content_hash != second.content_hash

    original_stat = first_path.stat()
    first_path.write_text("marker = 'gamma'\n", encoding="utf-8")
    os.utime(first_path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))

    current_first = cache.get_or_ingest(first_root, "same.py", tools)
    current_second = cache.get_or_ingest(second_root, "same.py", tools)
    assert current_first.text == "marker = 'gamma'"
    assert current_first.content_hash != first.content_hash
    assert current_second is second
    assert current_second.text == "marker = 'bravo'"

    fresh_cache = SinglePassIngestCache()
    assert fresh_cache.get_or_ingest(first_root, "same.py", tools).text == "marker = 'gamma'"
    assert fresh_cache.get_or_ingest(second_root, "same.py", tools).text == "marker = 'bravo'"
