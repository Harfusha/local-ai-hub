from __future__ import annotations

from contextlib import closing
import sqlite3
from types import SimpleNamespace

from local_ai_hub.code_index import CodeIndex


def test_exact_identifier_keeps_fuzzy_matches_with_one_materialized_score_pass(monkeypatch, tmp_path):
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
    assert result["total_matches"] == 3
    assert result["symbols"][0]["name"] == "generate_tests"
    assert {item["name"] for item in result["symbols"]} == {
        "generate_tests",
        "generate_test_report",
        "generate_tests_archive",
    }
    score_queries = [statement for statement in statements if "WITH scored AS MATERIALIZED" in statement]
    assert len(score_queries) == 1
    assert score_queries[0].count("hub_code_index_score") == 1
