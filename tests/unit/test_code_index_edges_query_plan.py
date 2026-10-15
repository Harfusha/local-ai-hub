import sqlite3
import hashlib
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

from local_ai_hub.code_index import CodeIndex


def _index(tmp_path: Path) -> CodeIndex:
    def read_snapshot(path: Path, **_kwargs):
        content = path.read_bytes()
        return hashlib.sha256(content).hexdigest(), content.decode("utf-8").splitlines()

    return CodeIndex(
        {"server": {"state_dir": str(tmp_path / "state")}},
        SimpleNamespace(max_file_bytes=10_000_000, _read_snapshot=read_snapshot),
    )


def _record_query(monkeypatch, index: CodeIndex, call):
    original_connect = index._connect
    recorded: list[tuple[str, tuple[object, ...]]] = []

    class RecordingConnection:
        def __init__(self, connection: sqlite3.Connection):
            self.connection = connection

        def execute(self, sql: str, parameters=()):
            recorded.append((sql, tuple(parameters)))
            return self.connection.execute(sql, parameters)

        def close(self) -> None:
            self.connection.close()

    monkeypatch.setattr(
        index, "_connect", lambda **kwargs: RecordingConnection(original_connect(**kwargs))
    )
    try:
        result = call()
    finally:
        monkeypatch.setattr(index, "_connect", original_connect)
    assert recorded
    return result, recorded[-1]


def _plan_uses_named_point_index(index: CodeIndex, sql: str, params: tuple[object, ...], name: str) -> None:
    with closing(index._connect()) as con:
        rows = con.execute(f"EXPLAIN QUERY PLAN {sql}", params).fetchall()
    details = " ".join(str(row[3]) for row in rows)
    assert f"SEARCH edges USING INDEX {name} (root=? AND kind=? AND" in details, details


def _insert_edge(
    index: CodeIndex,
    root: str,
    src: str,
    dst: str,
    *,
    kind: str = "calls",
    path: str = "manual.py",
) -> None:
    src_name = src.replace("\\", "/").rsplit("/", 1)[-1].rsplit("::", 1)[-1]
    dst_name = dst.replace("\\", "/").rsplit("/", 1)[-1].rsplit("::", 1)[-1]
    with closing(index._connect()) as con:
        con.execute(
            "INSERT INTO edges(root, src, dst, src_name, dst_name, kind, path, line) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (root, src, dst, src_name, dst_name, kind, path, 1),
        )
        con.commit()


def test_public_caller_and_callee_queries_use_named_point_indices(tmp_path, monkeypatch):
    index = _index(tmp_path)
    root = tmp_path / "repo"
    root.mkdir()
    (root / "calls.py").write_text(
        "def target():\n    pass\n\ndef caller():\n    target()\n", encoding="utf-8"
    )
    assert index.update_file(str(root), "calls.py")["success"]
    with closing(index._connect()) as con:
        con.executemany(
            "INSERT INTO edges(root, src, dst, src_name, dst_name, kind, path, line) "
            "VALUES(?,?,?,?,?,?,?,?)",
            [
                (str(root), f"caller_{n}", f"target_{n}", f"caller_{n}", f"target_{n}", "calls", f"noise/{n}.py", 1)
                for n in range(500)
            ],
        )
        con.execute("ANALYZE edges")
        con.commit()

    callers, caller_query = _record_query(
        monkeypatch, index, lambda: index.find_callers(str(root), "target")
    )
    callees, callee_query = _record_query(
        monkeypatch, index, lambda: index.find_callees(str(root), "caller")
    )

    assert callers["success"] and [row["caller"] for row in callers["callers"]] == ["caller"]
    assert callees["success"] and [row["callee"] for row in callees["callees"]] == ["target"]
    _plan_uses_named_point_index(index, *caller_query, "idx_edges_root_kind_dst_name")
    _plan_uses_named_point_index(index, *callee_query, "idx_edges_root_kind_src_name")


def test_single_and_batch_ingestion_populate_endpoint_names_and_isolate_roots(tmp_path):
    index = _index(tmp_path)
    single_root = tmp_path / "single"
    batch_root = tmp_path / "batch"
    single_root.mkdir()
    batch_root.mkdir()
    (single_root / "one.py").write_text(
        "def shared_target():\n    pass\n\ndef single_caller():\n    shared_target()\n",
        encoding="utf-8",
    )
    (batch_root / "one.py").write_text(
        "def shared_target():\n    pass\n\ndef batch_caller():\n    shared_target()\n",
        encoding="utf-8",
    )

    assert index.update_file(str(single_root), "one.py")["success"]
    assert index.update_files_batch(str(batch_root), ["one.py"])["success"]
    with closing(index._connect()) as con:
        names = con.execute(
            "SELECT root, src_name, dst_name FROM edges WHERE kind='calls' ORDER BY root"
        ).fetchall()
    assert {(row[0], row[1], row[2]) for row in names} == {
        (str(single_root.resolve()), "single_caller", "shared_target"),
        (str(batch_root.resolve()), "batch_caller", "shared_target"),
    }
    assert [r["caller"] for r in index.find_callers(str(single_root), "shared_target")["callers"]] == [
        "single_caller"
    ]


def test_qualified_unqualified_and_literal_wildcard_names_keep_semantics(tmp_path):
    index = _index(tmp_path)
    root_path = tmp_path / "repo"
    root_path.mkdir()
    root = str(root_path.resolve())
    _insert_edge(index, root, "pkg::Owner::method", "target")
    _insert_edge(index, root, "other::method", "other_target")
    _insert_edge(index, root, "wildcard_caller", "wild%_card")
    _insert_edge(index, root, "wildcard_false_positive", "wildXXcard")
    _insert_edge(index, root, "not_a_call", "wild%_card", kind="reference")

    assert [r["caller"] for r in index.find_callers(root, "target")["callers"]] == [
        "pkg::Owner::method"
    ]
    assert [r["callee"] for r in index.find_callees(root, "pkg::Owner::method")["callees"]] == [
        "target"
    ]
    assert {r["callee"] for r in index.find_callees(root, "method")["callees"]} == {
        "target",
        "other_target",
    }
    assert [r["caller"] for r in index.find_callers(root, "wild%_card")["callers"]] == [
        "wildcard_caller"
    ]


def test_existing_edges_with_missing_endpoint_names_are_backfilled(tmp_path):
    index = _index(tmp_path)
    root = str((tmp_path / "repo").resolve())
    _insert_edge(index, root, "pkg::owner", "target")
    with closing(index._connect()) as con:
        con.execute("DROP INDEX idx_edges_root_kind_dst_name")
        con.execute("DROP INDEX idx_edges_root_kind_src_name")
        con.execute("ALTER TABLE edges DROP COLUMN src_name")
        con.execute("ALTER TABLE edges DROP COLUMN dst_name")
        con.commit()
        index._schema(con)
        con.execute("UPDATE edges SET src_name=NULL, dst_name=NULL")
        index._schema(con)
        row = con.execute("SELECT src_name, dst_name FROM edges").fetchone()
        index_names = {
            str(item[1]) for item in con.execute("PRAGMA index_list(edges)").fetchall()
        }
        con.commit()

    assert tuple(row) == ("owner", "target")
    assert "idx_edges_root_kind_dst_name" in index_names
    assert "idx_edges_root_kind_src_name" in index_names


def test_caller_order_and_limit_metadata_are_preserved(tmp_path):
    index = _index(tmp_path)
    root_path = tmp_path / "repo"
    root_path.mkdir()
    root = str(root_path.resolve())
    _insert_edge(index, root, "later_caller", "limited_target", path="z.py")
    _insert_edge(index, root, "first_caller", "limited_target", path="a.py")

    limited = index.find_callers(root, "limited_target", limit=1)
    next_page = index.find_callers(root, "limited_target", limit=1, offset=1)

    assert [row["caller"] for row in limited["callers"]] == ["first_caller"]
    assert limited["truncated"] is True
    assert [row["caller"] for row in next_page["callers"]] == ["later_caller"]
    assert next_page["offset"] == 1
    assert next_page["total_matches"] == 2
    assert next_page["has_more"] is False
