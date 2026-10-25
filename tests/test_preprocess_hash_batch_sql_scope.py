from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from local_ai_hub.preprocess import ProjectPreprocessor
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
def isolated_preprocessor(tmp_path: Path) -> tuple[ProjectPreprocessor, str]:
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    project_root = str(tmp_path / "test_repo")
    Path(project_root).mkdir(parents=True, exist_ok=True)

    config = {
        "server": {"state_dir": str(state_dir)},
        "preprocess": {"hash_files_per_step": 32},
        "rag": {"extensions": [".py"]},
    }
    repo_tools = RepositoryTools(config)
    prep = ProjectPreprocessor(
        config,
        services=None,
        rag=None,
        scheduler=None,
        runtime=None,
        repo_tools=repo_tools,
    )
    prep._init_db()

    # Pre-populate file_refs with 200 files
    # Columns: root, path, content_hash, size, mtime_ns, needs_hash, rag_hash, last_accessed_at, generation, card_key, updated_at
    con = connect_sqlite(prep.db_path)
    try:
        refs_data = [
            (project_root, f"src/file_{i}.py", "", 100, 0, 1, None, 0.0, 1, None, 1000.0)
            for i in range(200)
        ]
        con.executemany(
            """
            INSERT INTO file_refs (root, path, content_hash, size, mtime_ns, needs_hash, rag_hash, last_accessed_at, generation, card_key, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            refs_data,
        )
        con.commit()
    finally:
        con.close()

    # Create files on disk
    for i in range(32):
        f = Path(project_root) / f"src/file_{i}.py"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f"# Python file {i}\ndef function_{i}(): return {i}\n", encoding="utf-8")

    return prep, project_root


def test_step_hash_scopes_queries_to_batch_paths(isolated_preprocessor: tuple[ProjectPreprocessor, str]):
    prep, root = isolated_preprocessor

    executed_queries: list[str] = []
    original_connect = prep._connect

    def tracking_connect():
        con = original_connect()
        return ConnectionProxy(con, executed_queries)

    prep._connect = tracking_connect

    # Run _step_hash for generation 1
    row = {"root": root, "generation": 1}
    success = prep._step_hash(row)
    assert success is True

    # Check the executed queries for card linking
    linking_queries = [
        q for q in executed_queries
        if "UPDATE file_refs" in q and "card_key =" in q
    ]
    assert len(linking_queries) >= 1, "Expected card linking query to execute"
    for q in linking_queries:
        assert "path IN (" in q, f"Card linking query was not scoped to batch paths: {q}"


def test_content_card_reuse_preserves_linking_for_scoped_batch(isolated_preprocessor: tuple[ProjectPreprocessor, str]):
    prep, root = isolated_preprocessor

    # Create a pre-existing content card for file_0's content
    file_0 = Path(root) / "src/file_0.py"
    digest = prep.repo_tools._hash_file_only(file_0)

    from local_ai_hub import __version__
    con = connect_sqlite(prep.db_path)
    try:
        con.execute(
            """
            INSERT INTO content_cards(card_key, content_hash, model, analyzer_version, card_json, created_at, accessed_at, hits)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("card_key_file_0", digest, "model_v1", __version__, "{}", 1000.0, 1000.0, 1),
        )
        con.commit()
    finally:
        con.close()

    # Run _step_hash
    row = {"root": root, "generation": 1}
    prep._step_hash(row)

    # Verify that file_0 has card_key linked
    with closing(prep._connect()) as con:
        r = con.execute(
            "SELECT card_key FROM file_refs WHERE root=? AND path=?",
            (root, "src/file_0.py"),
        ).fetchone()
        assert r is not None
        assert r[0] == "card_key_file_0", "Content card was not linked for scoped batch!"
