from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path

from local_ai_hub.preprocess import ProjectPreprocessor


class _CountingIndex:
    def __init__(self, path: Path, roots: list[str]) -> None:
        self.path = path
        self.connect_calls = 0
        self.queries: list[str] = []
        with closing(sqlite3.connect(path)) as con:
            con.execute("CREATE TABLE files(root TEXT NOT NULL, path TEXT NOT NULL)")
            con.executemany(
                "INSERT INTO files(root, path) VALUES(?, ?)",
                [(root, "one.py") for root in roots[1:]],
            )
            con.commit()

    def _connect(self) -> sqlite3.Connection:
        self.connect_calls += 1
        con = sqlite3.connect(self.path)
        con.set_trace_callback(self.queries.append)
        return con


class _MissingFilesIndex:
    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(":memory:")


def _status_preprocessor(tmp_path: Path, project_count: int = 70) -> tuple[ProjectPreprocessor, list[str], list[str]]:
    roots = [str((tmp_path / f"project-{index:03}").resolve()) for index in range(project_count)]
    for root in roots:
        Path(root).mkdir()

    main_db = tmp_path / "preprocess.sqlite3"
    with closing(sqlite3.connect(main_db)) as con:
        con.executescript(
            """
            CREATE TABLE projects (
                root TEXT PRIMARY KEY, workspace TEXT, status TEXT, phase TEXT,
                registered_at REAL, updated_at REAL, last_complete_at REAL,
                retry_after REAL, paused INTEGER, last_error TEXT, stats_json TEXT
            );
            CREATE TABLE file_refs (
                root TEXT, path TEXT, card_key TEXT, needs_hash INTEGER,
                content_hash TEXT, rag_hash TEXT
            );
            CREATE TABLE source_index(root TEXT, path TEXT);
            CREATE TABLE module_cards(root TEXT, module TEXT);
            CREATE TABLE project_cards(root TEXT);
            CREATE TABLE external_index_state(
                root TEXT, backend TEXT, status TEXT, error TEXT, updated_at REAL
            );
            """
        )
        now = time.time()
        con.executemany(
            "INSERT INTO projects VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    root,
                    "workspace",
                    "complete" if index == 0 else "running",
                    "complete" if index == 0 else "code_index",
                    now,
                    now,
                    now if index == 0 else None,
                    0,
                    0,
                    None,
                    "{}",
                )
                for index, root in enumerate(roots)
            ],
        )
        for index, root in enumerate(roots):
            con.executemany(
                "INSERT INTO file_refs VALUES(?, ?, ?, ?, ?, ?)",
                [
                    (root, "one.py", "card-1" if index == 0 else None, 0, "hash-1", "hash-1" if index == 0 else ""),
                    (root, "two.py", None, 1, "", ""),
                ],
            )
            if index:
                con.execute("INSERT INTO source_index VALUES(?, ?)", (root, "one.py"))
                con.execute("INSERT INTO module_cards VALUES(?, ?)", (root, "module"))
                con.execute("INSERT INTO project_cards VALUES(?)", (root,))
            con.execute(
                "INSERT INTO external_index_state VALUES(?, ?, ?, ?, ?)",
                (root, "serena", "skipped" if index == 0 else "ready", "", now),
            )
        con.commit()

    pre = object.__new__(ProjectPreprocessor)
    pre.db_path = main_db

    def connect_main() -> sqlite3.Connection:
        con = sqlite3.connect(main_db)
        con.row_factory = sqlite3.Row
        return con

    pre._connect = connect_main
    pre._stats_lock = threading.Lock()
    pre._speed_tracker = {}
    pre._paused = threading.Event()
    pre.enabled = True
    pre.scheduler = type("Scheduler", (), {"background_allowed": lambda _self: True})()
    pre.max_preprocessing_projects = 3
    pre.code_index = _CountingIndex(tmp_path / "code-index.sqlite3", roots)
    pre.deterministic = _CountingIndex(tmp_path / "deterministic.sqlite3", roots)
    pre._status_cache = {}
    pre._background_work_allowed = lambda: True
    pre.ingestion_reuse_rate = lambda: 0.0

    return pre, roots, roots[1:]


def test_status_batches_registered_project_counts_and_reuses_index_connections(tmp_path: Path) -> None:
    pre, roots, incomplete_roots = _status_preprocessor(tmp_path)
    sql_trace: list[str] = []
    original_connect = pre._connect

    def traced_connect() -> sqlite3.Connection:
        con = original_connect()
        con.set_trace_callback(sql_trace.append)
        return con

    pre._connect = traced_connect

    result = pre.status()

    projects = {project["root"]: project for project in result["projects"]}
    assert len(projects) == 70
    assert projects[roots[0]]["status"] == "complete"
    assert projects[roots[0]]["phase_progress_pct"] == 100.0
    assert projects[roots[0]]["file_cards"] == 2
    assert projects[roots[0]]["hashed_files"] == 2
    assert projects[roots[0]]["rag_files"] == 2
    assert projects[roots[0]]["external_indexes"]["serena"]["status"] == "unavailable"
    assert projects[roots[1]]["status"] == "running"
    assert projects[roots[1]]["files"] == 2
    assert projects[roots[1]]["hashed_files"] == 1
    assert projects[roots[1]]["rag_files"] == 0
    assert projects[roots[1]]["phase_progress_pct"] == 50.0
    assert projects[roots[1]]["active_detail"] == "AST symbol extraction: 1/2 files (50.0%)"
    assert projects[roots[1]]["git_common_dir"] == roots[1]
    assert projects[roots[1]]["is_worktree"] is False

    for table in ("file_refs", "external_index_state", "source_index", "module_cards", "project_cards"):
        reads = [statement for statement in sql_trace if f"from {table}" in statement.lower()]
        assert len(reads) == 1, f"expected one grouped {table} read, got {len(reads)}"
        if table != "external_index_state":
            assert "group by root" in reads[0].lower()
    assert pre.code_index.connect_calls == 1
    assert pre.deterministic.connect_calls == 1
    for index in (pre.code_index, pre.deterministic):
        file_queries = [statement for statement in index.queries if "from files" in statement.lower()]
        assert len(file_queries) == 1
        assert "group by root" in file_queries[0].lower()


def test_status_keeps_sqlite_index_error_fallback(tmp_path: Path) -> None:
    pre, roots, _ = _status_preprocessor(tmp_path)
    pre.code_index = _MissingFilesIndex()

    result = pre.status(root=roots[1])

    assert result["success"] is True
    assert len(result["projects"]) == 1
    assert result["projects"][0]["root"] == roots[1]
    assert result["projects"][0]["phase_progress_pct"] == 0.0
    assert result["projects"][0]["active_detail"] == "AST symbol extraction: 0/2 files (0.0%)"
