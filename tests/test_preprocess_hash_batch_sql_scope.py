from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from local_ai_hub.preprocess import ProjectPreprocessor
from local_ai_hub.preprocess_lexical import LEGACY_FTS, SHARED_FTS_ROWS, advance_fts_migration, fts_layout
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
def isolated_preprocessor(tmp_path: Path, request) -> tuple[ProjectPreprocessor, str]:
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    backend = getattr(request, "param", "shared")
    if backend != "shared":
        with closing(sqlite3.connect(state_dir / "preprocess.sqlite3")) as con:
            con.execute("CREATE VIRTUAL TABLE source_fts USING fts5(root UNINDEXED,path UNINDEXED,content)")
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
    if backend == "copying":
        with closing(prep._connect()) as con:
            assert advance_fts_migration(con)

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


@pytest.mark.parametrize("phase", ["hash", "reuse"])
@pytest.mark.parametrize("isolated_preprocessor", ["legacy", "copying", "shared"], indirect=True)
def test_fts_repairs_missing_rows_without_rescanning_per_path(
    isolated_preprocessor: tuple[ProjectPreprocessor, str], phase: str,
) -> None:
    prep, root = isolated_preprocessor
    other_root = root + "-other"
    files = ("src/file_0.py", "src/file_1.py")
    original_connect = prep._connect
    statements: list[str] = []

    def traced_connect():
        con = original_connect()
        con.set_trace_callback(statements.append)
        return con

    try:
        with closing(original_connect()) as con:
            con.execute("UPDATE file_refs SET needs_hash=0 WHERE root=?", (root,))
            for path in files:
                source = Path(root) / path
                digest = prep.repo_tools._hash_file_only(source)
                con.execute(
                    "UPDATE file_refs SET content_hash=?,needs_hash=? WHERE root=? AND path=?",
                    (digest, int(phase == "hash"), root, path),
                )
                con.execute(
                    "INSERT INTO source_index(root,path,content_hash,text,updated_at) VALUES (?,?,?,?,0)",
                    (root, path, digest, source.read_text(encoding="utf-8")),
                )
            present = (root, files[0], "existing")
            foreign = (other_root, files[1], "other root")
            prep._insert_fts_rows(con, [present, foreign])
            if fts_layout(con) == LEGACY_FTS:
                con.execute("INSERT INTO source_fts VALUES(?,?,?)", (root, None, "legacy null path"))
            con.commit()

        prep._connect = traced_connect
        if phase == "hash":
            assert prep._step_hash({"root": root, "generation": 1})
        else:
            prep._link_content_reuse(root)
        repair = next(sql for sql in statements if "SELECT s.root, s.path, s.path || char(10)" in sql)
        with closing(original_connect()) as con:
            rows = [tuple(row) for row in con.execute(
                "SELECT root,path,content FROM source_fts WHERE path IS NOT NULL ORDER BY root,path"
            )]
            plan = con.execute("EXPLAIN QUERY PLAN " + repair).fetchall()
            published = SHARED_FTS_ROWS if fts_layout(con) == SHARED_FTS_ROWS else LEGACY_FTS
        assert rows == [
            present, (root, files[1], files[1] + "\n" + (Path(root) / files[1]).read_text(encoding="utf-8")),
            foreign,
        ]
        assert not any(sql.lstrip().startswith(f"DELETE FROM {published} ") for sql in statements)
        assert not any("CORRELATED" in row[-1] for row in plan)
    finally:
        prep.close()


def test_hash_rolls_back_stale_lexical_cleanup_if_fts_repair_fails(
    isolated_preprocessor: tuple[ProjectPreprocessor, str],
) -> None:
    prep, root = isolated_preprocessor
    path = "src/file_0.py"
    original_connect = prep._connect

    class FailedRepair(ConnectionProxy):
        def execute(self, sql, parameters=()):
            if "SELECT s.root, s.path, s.path || char(10)" in str(sql):
                raise sqlite3.OperationalError("simulated FTS write failure")
            return super().execute(sql, parameters)

    try:
        with closing(original_connect()) as con:
            con.execute("UPDATE file_refs SET needs_hash=(path=?) WHERE root=?", (path, root))
            con.execute(
                "INSERT INTO source_index(root,path,content_hash,text,updated_at) VALUES (?,?,?,?,0)",
                (root, path, "old", "stale"),
            )
            prep._insert_fts_rows(con, [(root, path, "stale")])
            con.commit()
        prep._connect = lambda: FailedRepair(original_connect(), [])

        with pytest.raises(sqlite3.OperationalError, match="simulated FTS write failure"):
            prep._step_hash({"root": root, "generation": 1})
        with closing(original_connect()) as con:
            assert tuple(con.execute(
                "SELECT content_hash,needs_hash FROM file_refs WHERE root=? AND path=?", (root, path),
            ).fetchone()) == ("", 1)
            assert con.execute(
                "SELECT text FROM source_index WHERE root=? AND path=?", (root, path),
            ).fetchone()[0] == "stale"
            assert con.execute(
                "SELECT content FROM source_fts WHERE root=? AND path=?", (root, path),
            ).fetchone()[0] == "stale"
    finally:
        prep.close()


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
    card_queries = [q for q in executed_queries if "FROM content_cards" in q or "SET card_key =" in q]
    assert card_queries
    assert all("path IN (" in q for q in card_queries)


def test_content_card_reuse_preserves_linking_for_scoped_batch(isolated_preprocessor: tuple[ProjectPreprocessor, str]):
    prep, root = isolated_preprocessor

    # Create a pre-existing content card for file_0's content
    file_0 = Path(root) / "src/file_0.py"
    digest = prep.repo_tools._hash_file_only(file_0)

    from local_ai_hub.preprocess import PREPROCESS_ANALYZER_VERSION
    con = connect_sqlite(prep.db_path)
    try:
        con.execute(
            """
            INSERT INTO content_cards(card_key, content_hash, model, analyzer_version, card_json, created_at, accessed_at, hits)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("card_key_file_0", digest, "deterministic", PREPROCESS_ANALYZER_VERSION, "{}", 1000.0, 1000.0, 1),
        )
        con.execute(
            "INSERT INTO file_refs(root,path,content_hash,size,needs_hash,generation,updated_at) VALUES(?,?,?,?,0,1,0)",
            (root, "src/zz_outside_batch.py", digest, 100),
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
        outside_batch = con.execute(
            "SELECT card_key FROM file_refs WHERE root=? AND path=?", (root, "src/zz_outside_batch.py"),
        ).fetchone()
        assert outside_batch[0] is None
