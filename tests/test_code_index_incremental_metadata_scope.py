from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from local_ai_hub.code_index import CodeIndex
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.sqlite_support import connect_sqlite


class ConnectionProxy:
    def __init__(self, con: sqlite3.Connection, queries: list[str]) -> None:
        self._con = con
        self._queries = queries

    def execute(self, sql: Any, parameters: Any = ()) -> sqlite3.Cursor:
        self._queries.append(str(sql))
        return self._con.execute(sql, parameters)

    def executemany(self, sql: Any, parameters: Any) -> sqlite3.Cursor:
        self._queries.append(str(sql))
        return self._con.executemany(sql, parameters)

    def commit(self) -> None:
        self._con.commit()

    def rollback(self) -> None:
        self._con.rollback()

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> ConnectionProxy:
        self._con.__enter__()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> Any:
        return self._con.__exit__(exc_type, exc_val, exc_tb)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._con, name)


@pytest.fixture
def isolated_code_index(tmp_path: Path) -> tuple[CodeIndex, str]:
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    project_root = str(tmp_path / "project_10k")
    Path(project_root).mkdir(parents=True, exist_ok=True)

    config = {"server": {"state_dir": str(state_dir)}}
    repo_tools = RepositoryTools({"rag": {"extensions": [".py"]}})
    idx = CodeIndex(config, repo_tools=repo_tools)
    idx._init_db()

    # Pre-populate code_index files table with 1,000 files to simulate large root
    con = connect_sqlite(idx.db_path)
    try:
        files_data = [
            (project_root, f"src/module_{i}.py", f"hash_{i}", "analyzer_v1", "python", 1000.0, 1000, 500)
            for i in range(1000)
        ]
        con.executemany(
            """
            INSERT INTO files(root, path, content_hash, analyzer_version, language, updated_at, mtime_ns, size_bytes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            files_data,
        )
        con.commit()
    finally:
        con.close()

    return idx, project_root


def test_single_file_update_does_not_scan_entire_root(isolated_code_index: tuple[CodeIndex, str]):
    idx, root = isolated_code_index
    target_file = Path(root) / "src/module_42.py"
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text("def target_function():\n    return 42\n", encoding="utf-8")

    executed_queries: list[str] = []
    original_connect = idx._connect

    def custom_connect():
        con = original_connect()
        return ConnectionProxy(con, executed_queries)

    idx._connect = custom_connect

    result = idx.update_files_batch(root, ["src/module_42.py"])
    assert result["success"] is True

    # Check that query has path IN clause
    metadata_queries = [
        q for q in executed_queries
        if "FROM files WHERE root=?" in q and "SELECT path," in q
    ]
    assert len(metadata_queries) == 1
    assert "path IN (" in metadata_queries[0]

    with closing(idx._connect()) as con:
        syms = con.execute(
            "SELECT name FROM symbols WHERE root=? AND path=?",
            (root, "src/module_42.py"),
        ).fetchall()
        assert any(row[0] == "target_function" for row in syms)


def test_update_files_batch_scales_with_input_paths_not_total_files(isolated_code_index: tuple[CodeIndex, str]):
    idx, root = isolated_code_index

    for name in ["src/module_10.py", "src/module_20.py", "src/module_30.py"]:
        p = Path(root) / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"def func_{name}(): pass\n", encoding="utf-8")

    executed_queries: list[str] = []
    original_connect = idx._connect

    def custom_connect():
        con = original_connect()
        return ConnectionProxy(con, executed_queries)

    idx._connect = custom_connect

    res = idx.update_files_batch(root, ["src/module_10.py", "src/module_20.py", "src/module_30.py"])
    assert res["success"] is True

    metadata_queries = [
        q for q in executed_queries
        if "FROM files WHERE root=?" in q and "SELECT path," in q
    ]
    assert len(metadata_queries) > 0
    for q in metadata_queries:
        assert "path IN (" in q, f"Query was not scoped with path IN: {q}"
