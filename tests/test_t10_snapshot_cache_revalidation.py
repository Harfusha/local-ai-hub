from __future__ import annotations

import os
from pathlib import Path

import pytest

from local_ai_hub.repo_tools import RepositoryTools


@pytest.mark.parametrize("reader", ["decoded", "hash_only"])
def test_windows_snapshot_cache_revalidates_same_stat_rewrite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reader: str) -> None:
    if os.name != "nt":
        pytest.skip("Windows ctime is creation time; this regression targets NTFS identity")
    path = tmp_path / "same-size.py"
    path.write_bytes(b"first-value")
    tools = RepositoryTools({})
    monkeypatch.setattr(tools, "_windows_change_time", lambda _path: None)

    first = tools._read_snapshot(path)[0] if reader == "decoded" else tools._hash_file_only(path)
    original = path.stat()
    path.write_bytes(b"other-value")
    os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns))

    second = tools._read_snapshot(path)[0] if reader == "decoded" else tools._hash_file_only(path)

    assert second != first
    assert tools.snapshot_verified_rehashes >= 1
