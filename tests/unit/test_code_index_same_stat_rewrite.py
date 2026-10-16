"""Metadata-preserving rewrites must invalidate both index update paths."""

from contextlib import closing
import hashlib
import os

import pytest

from local_ai_hub.code_index import CodeIndex
from local_ai_hub.process_utils import canonical_root
from local_ai_hub.repo_tools import RepositoryTools


@pytest.mark.parametrize("batch", [False, True])
@pytest.mark.parametrize("supply_old_hash", [False, True])
def test_update_detects_rewrite_with_same_size_and_mtime(tmp_path, batch, supply_old_hash):
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "module.py"
    original = b"def old_name(): pass\n"
    source.write_bytes(original)
    old_hash = hashlib.sha256(original).hexdigest()
    before = source.stat()
    config = {"server": {"state_dir": str(tmp_path / "state")}}
    index = CodeIndex(config, RepositoryTools(config))

    def update():
        if batch:
            items = [("module.py", old_hash)] if supply_old_hash else ["module.py"]
            return index.update_files_batch(str(root), items)
        return index.update_file(str(root), "module.py", old_hash if supply_old_hash else None)

    assert update()["success"] is True
    replacement = b"def new_name(): pass\n"
    source.write_bytes(replacement)
    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert source.stat().st_size == before.st_size
    assert source.stat().st_mtime_ns == before.st_mtime_ns
    assert update()["success"] is True

    with closing(index._connect()) as con:
        row = con.execute(
            "SELECT content_hash FROM files WHERE root=? AND path=?",
            (canonical_root(str(root)), "module.py"),
        ).fetchone()
    assert row["content_hash"] == hashlib.sha256(replacement).hexdigest()
