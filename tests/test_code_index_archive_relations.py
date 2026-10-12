from contextlib import closing
from pathlib import Path

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
                "INSERT INTO edges(root,src,dst,kind,path,line) VALUES(?,?,?,?,?,?)",
                [
                    (resolved_root, "LiveCaller", "Base", "calls", archived_path, 2),
                    (resolved_root, "Concrete", "Base", "inherits", archived_path, 1),
                    (resolved_root, "src/current.py", "src/base.py", "imports", archived_path, 1),
                ],
            )
        con.execute(
            "INSERT INTO refs(root,path,name,line,kind) VALUES(?,?,?,?,?)",
            (resolved_root, live_path, "Base", 2, "read"),
        )
        con.executemany(
            "INSERT INTO edges(root,src,dst,kind,path,line) VALUES(?,?,?,?,?,?)",
            [
                (resolved_root, "LiveCaller", "Base", "calls", live_path, 2),
                (resolved_root, "Concrete", "Base", "inherits", live_path, 1),
                (resolved_root, "src/current.py", "src/base.py", "imports", live_path, 1),
            ],
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
