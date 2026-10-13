from contextlib import closing
from pathlib import Path

import local_ai_hub.code_index as code_index_module
from local_ai_hub.code_index import CodeIndex
from local_ai_hub.repo_tools import RepositoryTools


def test_find_dead_code_uses_indexed_archive_filter_without_sqlite_callback(
    tmp_path: Path, monkeypatch
) -> None:
    expected_module = Path(__file__).parents[2] / "src" / "local_ai_hub" / "code_index.py"
    assert Path(code_index_module.__file__).resolve() == expected_module.resolve()
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "target.py").write_text("def target():\n    pass\n", encoding="utf-8")
    (root / "src" / "archive_notes.py").write_text(
        "def archive_notes():\n    pass\n", encoding="utf-8"
    )
    config = {"server": {"state_dir": str(tmp_path / "state")}}
    index = CodeIndex(config, repo_tools=RepositoryTools(config))
    indexed = index.update_files_batch(str(root), ["src/target.py", "src/archive_notes.py"])
    assert indexed["success"] is True

    resolved_root = str(root.resolve())
    other_root = str((tmp_path / "other-repo").resolve())
    with index._lock, closing(index._connect()) as con:
        con.execute(
            "INSERT INTO refs(root,path,name,line,kind) VALUES(?,?,?,?,?)",
            (resolved_root, "handoff/legacy.py", "target", 1, "read"),
        )
        con.execute(
            "INSERT INTO refs(root,path,name,line,kind) VALUES(?,?,?,?,?)",
            (other_root, "src/foreign.py", "target", 1, "read"),
        )
        con.execute(
            "INSERT INTO symbols(root,path,name,kind,line,end_line,container,name_path,signature,access,docstring) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (resolved_root, "handoff/legacy.py", "Archived", "function", 1, 1, "", "Archived", "def Archived()", "public", ""),
        )
        con.executemany(
            "INSERT INTO refs(root,path,name,line,kind) VALUES(?,?,?,?,?)",
            (
                (resolved_root, f"src/reference-{number}.py", f"unused_{number}", 1, "read")
                for number in range(600)
            ),
        )
        con.commit()

    archive_registrations: list[str] = []
    archive_calls: list[str] = []
    path_scan_fetchall: list[bool] = []
    path_scan_batch_rows: list[int] = []
    path_scan_cursor_closed: list[bool] = []
    connect_sqlite = code_index_module.connect_sqlite
    path_scan_sql = "SELECT path FROM symbols WHERE root=? UNION SELECT path FROM refs WHERE root=?"

    class ObservedConnection:
        def __init__(self, connection):
            self.connection = connection

        def create_function(self, name, argument_count, function, **kwargs):
            if name == "hub_root_archive_path":
                archive_registrations.append(name)
                callback = function

                def tracked(path):
                    archive_calls.append(path)
                    return callback(path)

                function = tracked
            return self.connection.create_function(name, argument_count, function, **kwargs)

        def execute(self, sql, parameters=()):
            cursor = self.connection.execute(sql, parameters)
            if path_scan_sql in sql:
                return ObservedCursor(cursor)
            return cursor

        def __getattr__(self, name):
            return getattr(self.connection, name)

    class ObservedCursor:
        def __init__(self, cursor):
            self.cursor = cursor

        def fetchall(self):
            path_scan_fetchall.append(True)
            return self.cursor.fetchall()

        def fetchmany(self, size=None):
            rows = self.cursor.fetchmany(size)
            path_scan_batch_rows.append(len(rows))
            return rows

        def close(self):
            path_scan_cursor_closed.append(True)
            return self.cursor.close()

        def __getattr__(self, name):
            return getattr(self.cursor, name)

    monkeypatch.setattr(
        code_index_module,
        "connect_sqlite",
        lambda *args, **kwargs: ObservedConnection(connect_sqlite(*args, **kwargs)),
    )

    result = index.find_dead_code(str(root), limit=10)

    assert result["success"] is True, result
    names = {symbol["name"] for symbol in result["dead_symbols"]}
    assert "archive_notes" in names
    assert "target" in names
    assert "Archived" not in names
    assert archive_calls == []
    assert archive_registrations == []
    assert path_scan_fetchall == []
    assert len(path_scan_batch_rows) >= 3
    assert max(path_scan_batch_rows) <= 250
    assert path_scan_cursor_closed == [True]
