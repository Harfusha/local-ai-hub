from contextlib import closing
from pathlib import Path
import sqlite3

import pytest

from local_ai_hub.code_index import CodeIndex
from local_ai_hub.repo_tools import RepositoryTools


def test_archive_relation_rows_cannot_starve_live_retrieval_or_impact(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "base.py").write_text("\n", encoding="utf-8")
    (root / "src" / "current.py").write_text("\n", encoding="utf-8")
    config = {"server": {"state_dir": str(tmp_path / "state")}}
    index = CodeIndex(config, repo_tools=RepositoryTools(config))
    indexed = index.update_files_batch(str(root), ["src/base.py", "src/current.py"])
    assert indexed["success"] is True

    resolved_root = str(root.resolve())
    live_path = "src/current.py"
    archive_paths = [
        f"artifacts/t08-global-tombstone-{number}/src/local_ai_hub/agent_memory.py"
        for number in range(201)
    ]
    with index._lock, closing(index._connect()) as con:
        con.execute(
            "INSERT INTO symbols(root,path,name,kind,line,end_line,container,name_path,signature,access,docstring) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (resolved_root, "src/base.py", "Base", "class", 1, 1, "", "Base", "class Base", "public", ""),
        )
        con.execute(
            "INSERT INTO symbols(root,path,name,kind,line,end_line,container,name_path,signature,access,docstring) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (resolved_root, live_path, "LiveCaller", "function", 1, 1, "", "LiveCaller", "def LiveCaller()", "public", ""),
        )
        for archived_path in archive_paths:
            con.execute(
                "INSERT INTO files(root,path,content_hash,analyzer_version,language,updated_at) VALUES(?,?,?,?,?,?)",
                (resolved_root, archived_path, "stale", "legacy", "python", 0.0),
            )
            con.execute(
                "INSERT INTO symbols(root,path,name,kind,line,end_line,container,name_path,signature,access,docstring) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (resolved_root, archived_path, "LiveCaller", "function", 1, 1, "", "LiveCaller", "def LiveCaller()", "public", ""),
            )
            con.execute(
                "INSERT INTO refs(root,path,name,line,kind) VALUES(?,?,?,?,?)",
                (resolved_root, archived_path, "Base", 2, "read"),
            )
            con.executemany(
                "INSERT INTO edges(root,src,dst,src_name,dst_name,kind,path,line) VALUES(?,?,?,?,?,?,?,?)",
                [
                    (resolved_root, "LiveCaller", "Base", "LiveCaller", "Base", "calls", archived_path, 2),
                    (resolved_root, "Concrete", "Base", "Concrete", "Base", "inherits", archived_path, 1),
                    (resolved_root, "src/current.py", "src/base.py", "current.py", "base.py", "imports", archived_path, 1),
                ],
            )
        con.execute(
            "INSERT INTO refs(root,path,name,line,kind) VALUES(?,?,?,?,?)",
            (resolved_root, live_path, "Base", 2, "read"),
        )
        con.executemany(
            "INSERT INTO edges(root,src,dst,src_name,dst_name,kind,path,line) VALUES(?,?,?,?,?,?,?,?)",
            [
                (resolved_root, "LiveCaller", "Base", "LiveCaller", "Base", "calls", live_path, 2),
                (resolved_root, "Concrete", "Base", "Concrete", "Base", "inherits", live_path, 1),
                (resolved_root, "src/current.py", "src/base.py", "current.py", "base.py", "imports", live_path, 1),
            ],
        )
        index._replace_symbol_trigrams(
            con,
            resolved_root,
            [str(row[0]) for row in con.execute(
                "SELECT DISTINCT path FROM symbols WHERE root=?", (resolved_root,),
            )],
        )
        con.commit()

    symbols = index.find_symbol(str(root), "LiveCaller", limit=1)
    assert [item["path"] for item in symbols["symbols"]] == [live_path]
    assert index.find_symbol(str(root), "LiveCaller", relative_path=archive_paths[0])["symbols"] == []
    assert index.get_symbols_overview(str(root), archive_paths[0])["symbols"] == []
    assert index.file_summary(str(root), archive_paths[0])["indexed"] is False
    assert [item["path"] for item in index.find_referencing_symbols(str(root), "Base")["references"]] == [live_path]
    assert [item["path"] for item in index.find_implementations(str(root), "Base")["implementations"]] == [live_path]
    assert [item["path"] for item in index.find_callers(str(root), "Base", limit=1)["callers"]] == [live_path]
    assert [item["path"] for item in index.find_callees(str(root), "LiveCaller", limit=1)["callees"]] == [live_path]
    assert all(not path.startswith("artifacts/") for path in index.related_paths(str(root), "Base", limit=20))

    impact = index.impact(str(root), ["src/base.py"], max_symbols=10, max_dependents=1)
    assert impact["success"] is True
    assert impact["coverage"]["dependent_candidate_count"] == 1
    assert [item["path"] for item in impact["likely_dependents"]] == [live_path]
    assert impact["coverage"]["dependent_candidate_count_exact"] is True


@pytest.mark.parametrize("old_edges,old_files", [(True, False), (False, True), (True, True)])
def test_old_derived_index_is_rebuilt_without_in_place_migration(tmp_path: Path, old_edges: bool, old_files: bool):
    state = tmp_path / "state"
    state.mkdir()
    database = state / "code-index.sqlite3"
    endpoint_columns = "" if old_edges else ",src_name TEXT,dst_name TEXT"
    metadata_columns = "" if old_files else ",mtime_ns INTEGER,size_bytes INTEGER"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            "CREATE TABLE files(root TEXT,path TEXT,content_hash TEXT,analyzer_version TEXT,"
            f"language TEXT,updated_at REAL{metadata_columns},PRIMARY KEY(root,path))"
        )
        connection.execute(
            f"CREATE TABLE edges(root TEXT,src TEXT,dst TEXT,kind TEXT,path TEXT,line INTEGER{endpoint_columns})"
        )
        connection.execute("INSERT INTO files(root,path) VALUES('old-root','old.py')")
        connection.commit()
    config = {"server": {"state_dir": str(state)}}
    index = CodeIndex(config, repo_tools=RepositoryTools(config))
    with closing(index._connect()) as connection:
        assert {"src_name", "dst_name"} <= {row["name"] for row in connection.execute("PRAGMA table_info(edges)")}
        assert {"mtime_ns", "size_bytes"} <= {row["name"] for row in connection.execute("PRAGMA table_info(files)")}
        assert connection.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 0
    archives = list(state.glob("code-index.sqlite3.corrupt-*"))
    assert len(archives) == 1
    with closing(sqlite3.connect(archives[0])) as connection:
        assert connection.execute("SELECT path FROM files").fetchone()[0] == "old.py"
        if old_edges:
            assert "src_name" not in {row[1] for row in connection.execute("PRAGMA table_info(edges)")}
        if old_files:
            assert "mtime_ns" not in {row[1] for row in connection.execute("PRAGMA table_info(files)")}
