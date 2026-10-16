from __future__ import annotations

from contextlib import closing
import sqlite3
from types import SimpleNamespace

from local_ai_hub.code_index import CodeIndex


def test_exact_identifier_query_uses_name_index_without_python_score_udf(monkeypatch, tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    index = CodeIndex(
        {"server": {"state_dir": str(tmp_path / "state")}},
        SimpleNamespace(ignore_dirs=set()),
    )
    with closing(sqlite3.connect(index.db_path)) as con:
        con.executemany(
            """INSERT INTO symbols(
                   root,path,name,kind,line,end_line,container,name_path,signature,access,docstring
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (str(root), "src/a.py", "generate_tests", "function", 1, 4, "", "generate_tests", "", "public", ""),
                (str(root), "src/b.py", "generate_test_report", "function", 2, 5, "", "generate_test_report", "", "public", ""),
                (str(root), "src/c.py", "generate_tests_archive", "function", 3, 6, "", "generate_tests_archive", "", "public", ""),
            ],
        )
        con.commit()

    statements: list[str] = []
    connect = index._connect

    def traced_connect():
        con = connect()
        con.set_trace_callback(statements.append)
        return con

    monkeypatch.setattr(index, "_connect", traced_connect)
    try:
        result = index.query(str(root), "generate_tests")
    finally:
        close = getattr(index, "close", None)
        if callable(close):
            close()

    assert result["success"] is True
    assert result["total_matches"] == 1
    assert result["symbols"][0]["name"] == "generate_tests"
    assert any("lower(name)" in statement and "generate_tests" in statement for statement in statements)
    assert not any("hub_code_index_score" in statement for statement in statements)
