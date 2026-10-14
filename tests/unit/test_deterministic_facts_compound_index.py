import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

from local_ai_hub.deterministic import DeterministicEngine


def _engine(tmp_path: Path) -> DeterministicEngine:
    config = {"server": {"state_dir": str(tmp_path / "state")}}
    return DeterministicEngine(config, repo_tools=SimpleNamespace())


def _index_columns(con: sqlite3.Connection, name: str) -> list[str]:
    return [str(row[2]) for row in con.execute(f"PRAGMA index_info({name})")]


def test_facts_root_name_query_uses_compound_index(tmp_path):
    engine = _engine(tmp_path)
    with closing(engine._connect()) as con:
        con.executemany(
            "INSERT INTO facts(root,path,kind,name,value) VALUES(?,?,?,?,?)",
            [
                (f"root-{i % 8}", f"file-{i}.py", f"kind-{i % 12}", f"name-{i % 80}", "v")
                for i in range(2400)
            ],
        )
        con.commit()
        columns = _index_columns(con, "idx_facts_root_name_kind")
        plan = con.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM facts WHERE root=? AND name=?",
            ("root-3", "name-27"),
        ).fetchall()
    details = " ".join(str(row[3]) for row in plan)
    assert "SEARCH facts USING INDEX idx_facts_root_name_kind (root=? AND name=?)" in details, details
    assert columns == ["root", "name", "kind"]


def test_existing_database_reopen_adds_index_and_preserves_facts_and_indexes(tmp_path):
    first = _engine(tmp_path)
    with closing(first._connect()) as con:
        con.execute(
            "INSERT INTO facts(root,path,kind,name,value) VALUES(?,?,?,?,?)",
            ("kept-root", "kept.py", "function", "kept_name", "kept-value"),
        )
        con.commit()
        con.execute("DROP INDEX IF EXISTS idx_facts_root_name_kind")

    second = _engine(tmp_path)
    with closing(second._connect()) as con:
        assert tuple(con.execute(
            "SELECT root,path,kind,name,value FROM facts WHERE root=?", ("kept-root",)
        ).fetchone()) == ("kept-root", "kept.py", "function", "kept_name", "kept-value")
        names = {str(row[1]) for row in con.execute("PRAGMA index_list(facts)")}
        assert {
            "idx_facts_root_kind_name",
            "idx_facts_root_path",
            "idx_facts_root_name_kind",
        } <= names
        assert _index_columns(con, "idx_facts_root_name_kind") == ["root", "name", "kind"]
    second._init_db()
    with closing(second._connect()) as con:
        assert _index_columns(con, "idx_facts_root_name_kind") == ["root", "name", "kind"]
