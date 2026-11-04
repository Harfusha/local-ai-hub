import sqlite3
import threading
from contextlib import closing

import pytest

from local_ai_hub.code_index import CodeIndex
from local_ai_hub.preprocess import ProjectPreprocessor
from local_ai_hub.repo_tools import RepositoryTools


def test_missing_file_prune_removes_trigrams_and_invalidates_index_cache(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    path = root / "a.py"
    path.write_text("def unusual_symbol_name():\n    pass\n", encoding="utf-8")
    index = CodeIndex({"server": {"state_dir": str(tmp_path / "state")}}, RepositoryTools({}))
    assert index.update_file(str(root), "a.py")["success"]
    with closing(index._connect()) as con:
        assert con.execute("SELECT COUNT(*) FROM symbol_trigrams").fetchone()[0] > 0
    before = index._cache_generation()
    path.unlink()

    db = tmp_path / "pre.sqlite"
    with closing(sqlite3.connect(db)) as con:
        for table in ("file_refs", "source_index", "source_fts"):
            con.execute(f"CREATE TABLE {table}(root TEXT,path TEXT)")
            con.execute(f"INSERT INTO {table} VALUES(?, 'a.py')", (str(root),))
        for table in ("module_cards", "project_cards", "hot_query_state", "task_capsules"):
            con.execute(f"CREATE TABLE {table}(root TEXT)")
        con.commit()

    def connect():
        return sqlite3.connect(db)

    def write(callback):
        with closing(connect()) as con:
            callback(con)
            con.commit()

    pre = ProjectPreprocessor.__new__(ProjectPreprocessor)
    pre._db_lock, pre._stats_lock = threading.RLock(), threading.RLock()
    pre._connect, pre._write_retry, pre._stats = connect, write, {}
    pre.code_index, pre.deterministic = index, None
    assert pre._prune_missing_file_refs(str(root)) == 1
    with closing(index._connect()) as con:
        assert con.execute("SELECT COUNT(*) FROM symbol_trigrams").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 0
    assert index._cache_generation() > before
    index.close()


def test_failed_code_index_prune_keeps_file_reference_for_retry(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    db = tmp_path / "pre.sqlite"
    with closing(sqlite3.connect(db)) as con:
        for table in ("file_refs", "source_index", "source_fts"):
            con.execute(f"CREATE TABLE {table}(root TEXT,path TEXT)")
            con.execute(f"INSERT INTO {table} VALUES(?, 'a.py')", (str(root),))
        for table in ("module_cards", "project_cards", "hot_query_state", "task_capsules"):
            con.execute(f"CREATE TABLE {table}(root TEXT)")
        con.commit()

    def connect():
        return sqlite3.connect(db)

    def write(callback):
        with closing(connect()) as con:
            callback(con)
            con.commit()

    class BrokenIndex:
        def _remove_indexed_paths(self, root, paths):
            raise sqlite3.OperationalError("database busy")

    pre = ProjectPreprocessor.__new__(ProjectPreprocessor)
    pre._db_lock, pre._stats_lock = threading.RLock(), threading.RLock()
    pre._connect, pre._write_retry, pre._stats = connect, write, {}
    pre.code_index, pre.deterministic = BrokenIndex(), None
    with pytest.raises(sqlite3.OperationalError):
        pre._prune_missing_file_refs(str(root))
    with closing(connect()) as con:
        assert con.execute("SELECT COUNT(*) FROM file_refs").fetchone()[0] == 1


def test_partial_index_never_claims_complete_dependency_graph(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.py").write_text("def target():\n    pass\n", encoding="utf-8")
    (root / "unindexed.py").write_text("from a import target\ntarget()\n", encoding="utf-8")
    index = CodeIndex({"server": {"state_dir": str(tmp_path / "state")}}, RepositoryTools({}))
    assert index.update_file(str(root), "a.py")["success"]
    result = index.impact(str(root), ["a.py"])
    assert result["success"]
    assert result["graph_complete"] is False
    assert result["dependency_graph_complete"] is False
    index.close()
