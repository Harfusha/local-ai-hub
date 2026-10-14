from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
import pytest
import sqlite3
import time

from local_ai_hub.code_index import CodeIndex
from local_ai_hub.repo_tools import RepositoryTools


def test_mtime_and_size_stored_and_bypasses_hashing_when_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "repo"
    root.mkdir()
    file_path = root / "code.py"
    file_path.write_text("def hello(): return 1\n", encoding="utf-8")
    
    config = {
        "server": {"state_dir": str(tmp_path / "state")},
        "rag": {"max_file_bytes": 2_000_000},
    }
    repo_tools = RepositoryTools(config)
    index = CodeIndex(config, repo_tools=repo_tools)
    
    # Initial index
    res1 = index.update_file(str(root), "code.py")
    assert res1["success"] is True
    
    # Verify mtime_ns and size_bytes are populated in files table
    with index._lock, closing(index._connect()) as con:
        row = con.execute("SELECT mtime_ns, size_bytes, content_hash FROM files WHERE root=? AND path=?", (str(root.resolve()), "code.py")).fetchone()
        assert row is not None
        assert row["mtime_ns"] is not None
        assert row["size_bytes"] is not None
        assert row["size_bytes"] == file_path.stat().st_size
    
    # Now monkeypatch _read_snapshot to fail if called
    read_calls = []
    original_read = repo_tools._read_snapshot
    def guarded_read(path, **kwargs):
        read_calls.append(path)
        return original_read(path, **kwargs)
    monkeypatch.setattr(repo_tools, "_read_snapshot", guarded_read)
    
    # Calling update_file on unchanged file should bypass _read_snapshot
    res2 = index.update_file(str(root), "code.py")
    assert res2["success"] is True
    assert res2.get("cached") is True
    assert len(read_calls) == 0, f"Expected 0 reads but got {len(read_calls)}"
    
    # Calling update_files_batch on unchanged file should also bypass _read_snapshot
    batch_res = index.update_files_batch(str(root), ["code.py"])
    assert batch_res["success"] is True
    assert batch_res.get("cached") == 1
    assert len(read_calls) == 0, f"Expected 0 reads in batch but got {len(read_calls)}"
    
    # files_needing_reindex should not select unchanged file
    pending = index.files_needing_reindex(str(root), [("code.py", "")])
    assert pending == []


def test_mtime_change_triggers_reindex(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    file_path = root / "code.py"
    file_path.write_text("def v1(): return 1\n", encoding="utf-8")
    
    config = {
        "server": {"state_dir": str(tmp_path / "state")},
        "rag": {"max_file_bytes": 2_000_000},
    }
    repo_tools = RepositoryTools(config)
    index = CodeIndex(config, repo_tools=repo_tools)
    
    res1 = index.update_file(str(root), "code.py")
    assert res1["success"] is True
    assert len(index.find_callers(str(root), "v1")["callers"]) == 0
    
    # Modify file
    time.sleep(0.01)
    file_path.write_text("def v2(): return 2\n", encoding="utf-8")
    
    res2 = index.update_file(str(root), "code.py")
    assert res2["success"] is True
    assert res2.get("cached") is not True
    
    with index._lock, closing(index._connect()) as con:
        syms = [r[0] for r in con.execute("SELECT name FROM symbols WHERE root=? AND path=?", (str(root.resolve()), "code.py")).fetchall()]
        assert "v2" in syms
        assert "v1" not in syms
