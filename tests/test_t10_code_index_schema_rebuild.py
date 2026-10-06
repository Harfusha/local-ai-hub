from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from local_ai_hub import code_index as code_index_module
from local_ai_hub.code_index import CodeIndex


def _assert_workspace_code_index_import() -> None:
    expected = Path(__file__).resolve().parents[1] / "src" / "local_ai_hub" / "code_index.py"
    assert Path(code_index_module.__file__).resolve() == expected


def _write_legacy_code_index(state_dir: Path) -> tuple[Path, Path, bytes]:
    state_dir.mkdir(parents=True, exist_ok=True)
    cache_path = state_dir / "code-index.sqlite3"
    with closing(sqlite3.connect(cache_path)) as connection:
        connection.execute(
            "CREATE TABLE files(root TEXT, path TEXT, content_hash TEXT, language TEXT, "
            "updated_at REAL, PRIMARY KEY(root, path))"
        )
        connection.execute(
            "INSERT INTO files VALUES(?,?,?,?,?)",
            ("C:/repo", "src/old.py", "derived-hash", "python", 1.0),
        )
        connection.commit()

    agent_state_path = state_dir / "agent_state.sqlite3"
    with closing(sqlite3.connect(agent_state_path)) as connection:
        connection.execute("CREATE TABLE durable_marker(value TEXT NOT NULL)")
        connection.execute("INSERT INTO durable_marker VALUES(?)", ("keep",))
        connection.commit()
    return cache_path, agent_state_path, agent_state_path.read_bytes()


def test_legacy_code_index_schema_rebuilds_current_schema_and_preserves_agent_state(
    tmp_path: Path,
) -> None:
    _assert_workspace_code_index_import()
    state_dir = tmp_path / "state"
    cache_path, agent_state_path, agent_state_before = _write_legacy_code_index(state_dir)

    index = CodeIndex({"server": {"state_dir": str(state_dir)}}, repo_tools=None)

    with closing(sqlite3.connect(index.db_path)) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(files)")}
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        indexes = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='index'")
        }
        assert "analyzer_version" in columns
        assert {"files", "symbols", "refs", "edges", "parse_blobs"} <= tables
        assert {
            "idx_symbols_name", "idx_symbols_path", "idx_refs_name",
            "idx_edges_src", "idx_edges_dst", "idx_parse_blobs_updated",
        } <= indexes
        assert connection.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 0

    archived = list(state_dir.glob("code-index.sqlite3.corrupt-*"))
    assert len(archived) == 1
    with closing(sqlite3.connect(archived[0])) as connection:
        assert connection.execute("SELECT path,content_hash FROM files").fetchone() == (
            "src/old.py",
            "derived-hash",
        )
    assert cache_path == index.db_path
    assert agent_state_path.read_bytes() == agent_state_before


def test_legacy_code_index_schema_rebuild_failure_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_workspace_code_index_import()
    state_dir = tmp_path / "state"
    cache_path, agent_state_path, agent_state_before = _write_legacy_code_index(state_dir)
    original_replace = Path.replace

    def fail_cache_archive(path: Path, target: str | Path) -> Path:
        if path == cache_path:
            raise PermissionError("cache archive denied")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_cache_archive)
    with pytest.raises(sqlite3.DatabaseError, match="stale derived code-index schema"):
        CodeIndex({"server": {"state_dir": str(state_dir)}}, repo_tools=None)

    assert cache_path.exists()
    assert not list(state_dir.glob("code-index.sqlite3.corrupt-*"))
    assert agent_state_path.read_bytes() == agent_state_before
