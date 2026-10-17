from __future__ import annotations

import math
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from local_ai_hub import process_utils
from local_ai_hub.preprocess import ProjectPreprocessor, _project_git_identity


def test_process_utils_path_helpers(tmp_path: Path):
    # canonical_root edge cases
    c_root = process_utils.canonical_root(tmp_path)
    assert Path(c_root).is_absolute()
    with pytest.raises(ValueError):
        process_utils.canonical_root("repo\x00bad")

    # canonical_workspace_id edge cases
    ws_id = process_utils.canonical_workspace_id("my_project")
    assert "my_project" in ws_id

    # is_rooted_path edge cases
    assert process_utils.is_rooted_path("") is False
    assert process_utils.is_rooted_path(None) is False  # type: ignore
    assert process_utils.is_rooted_path("path\x00bad") is False
    assert process_utils.is_rooted_path("/var/log") is True
    assert process_utils.is_rooted_path("C:\\Windows") is True
    assert process_utils.is_rooted_path("relative/sub/path") is False

    # ensure_extended_path edge cases
    ext_null = process_utils.ensure_extended_path("some\x00path")
    assert "\x00" not in str(ext_null)
    ext_bool = process_utils.ensure_extended_path("short_path", threshold=True)  # type: ignore
    assert str(ext_bool)

    # is_valid_pid
    assert process_utils.is_valid_pid(None) is False
    assert process_utils.is_valid_pid(True) is False
    assert process_utils.is_valid_pid(False) is False
    assert process_utils.is_valid_pid("1234") is False
    assert process_utils.is_valid_pid(0) is False
    assert process_utils.is_valid_pid(-5) is False
    assert process_utils.is_valid_pid(1234) is True

    # is_safe_path
    assert process_utils.is_safe_path(None) is False
    assert process_utils.is_safe_path(True) is False
    assert process_utils.is_safe_path("") is False
    assert process_utils.is_safe_path("  ") is False
    assert process_utils.is_safe_path("bad\x00path") is False
    assert process_utils.is_safe_path("good/path.txt") is True


def test_project_git_identity_edge_cases(tmp_path: Path):
    non_git = tmp_path / "no_git"
    non_git.mkdir()
    root, is_wt = _project_git_identity(str(non_git))
    assert str(non_git.resolve()) in root
    assert is_wt is False

    root_null, is_wt_null = _project_git_identity("repo\x00bad")
    assert "\x00" not in root_null


def test_project_preprocessor_init_with_invalid_configs(tmp_path: Path):
    # None or empty config with defaults
    prep = ProjectPreprocessor(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "preprocessing": {
                "enabled": False,
                "max_preprocessing_projects": float("nan"),
                "worktree_discovery_ttl_seconds": True,
                "cpu_workers": float("inf"),
                "touch_debounce_seconds": float("nan"),
                "sqlite_busy_timeout_seconds": False,
                "lookup_l1_ttl_seconds": -5.0,
            },
        },
        services=MagicMock(),
        rag=MagicMock(),
        scheduler=MagicMock(),
        runtime=MagicMock(),
        repo_tools=MagicMock(),
    )
    assert prep.is_enabled() is False
    assert prep.is_paused() is False
    assert prep.max_preprocessing_projects >= 1
    assert math.isfinite(prep.worktree_discovery_ttl)
    assert prep.cpu_workers >= 1
    assert math.isfinite(prep._touch_debounce_seconds)
    assert math.isfinite(prep._lookup_cache_ttl)
    assert "inventory" in prep.phases()

    st = prep.stats()
    assert isinstance(st, dict)
    assert "loops" in st
    assert prep._last_db_maintenance > 0.0

    prep._cpu_pool.shutdown(wait=False)


def test_cleanup_orphaned_indexes_preserves_existing_directories(tmp_path: Path):
    import sqlite3
    import threading
    from contextlib import closing

    existing_dir = tmp_path / "my_project"
    existing_dir.mkdir()

    class _MockDb:
        def __init__(self, path: Path):
            self._lock = threading.RLock()
            self.path = path
            with closing(sqlite3.connect(path)) as con:
                con.executescript("CREATE TABLE files(root TEXT, path TEXT); CREATE TABLE symbols(root TEXT, path TEXT);")
                con.executemany("INSERT INTO files VALUES(?,?)", [("non_existent_orphan", "o.py"), (str(existing_dir), "e.py")])
                con.executemany("INSERT INTO symbols VALUES(?,?)", [("non_existent_orphan", "o.py"), (str(existing_dir), "e.py")])
                con.commit()

        def _connect(self):
            return sqlite3.connect(self.path)

    prep = ProjectPreprocessor(
        {"server": {"state_dir": str(tmp_path / "state")}, "preprocessing": {"enabled": False}},
        services=MagicMock(),
        rag=MagicMock(),
        scheduler=MagicMock(),
        runtime=MagicMock(),
        repo_tools=MagicMock(),
        code_index=_MockDb(tmp_path / "code.sqlite3"),
    )
    try:
        assert prep._last_db_maintenance > 0.0
        result = prep.cleanup_orphaned_indexes(max_roots=4)
        assert result["success"] is True
        with closing(sqlite3.connect(tmp_path / "code.sqlite3")) as con:
            assert con.execute("SELECT count(*) FROM files WHERE root='non_existent_orphan'").fetchone()[0] == 0
            assert con.execute("SELECT count(*) FROM files WHERE root=?", (str(existing_dir),)).fetchone()[0] == 1
    finally:
        prep._cpu_pool.shutdown(wait=False)
        prep.close()
