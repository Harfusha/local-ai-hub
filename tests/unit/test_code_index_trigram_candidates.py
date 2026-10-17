from __future__ import annotations

from contextlib import closing
import sqlite3
from types import SimpleNamespace

from local_ai_hub import code_index as code_index_module
from local_ai_hub.code_index import CodeIndex
from local_ai_hub.repo_tools import RepositoryTools


def _index(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    index = CodeIndex(
        {"server": {"state_dir": str(tmp_path / "state")}},
        SimpleNamespace(ignore_dirs=set()),
    )
    return root, index


def _insert_symbols(index, root, records):
    paths = sorted({record[0] for record in records})
    with closing(sqlite3.connect(index.db_path)) as con:
        con.executemany(
            """INSERT INTO symbols(
                   root,path,name,kind,line,end_line,container,name_path,signature,access,docstring
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            [(str(root), *record) for record in records],
        )
        index._replace_symbol_trigrams(con, str(root), paths)
        con.commit()


def test_trigram_replacement_streams_long_fields_in_bounded_chunks(tmp_path):
    root, index = _index(tmp_path)
    path = "src/large.py"
    long_name = "a" * 12000
    batch_sizes = []

    with closing(sqlite3.connect(index.db_path)) as con:
        con.execute(
            """INSERT INTO symbols(
                   root,path,name,kind,line,end_line,container,name_path,signature,access,docstring
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (str(root), path, long_name, "function", 1, 2, "", long_name, "", "public", ""),
        )

        class TrackingConnection:
            def execute(self, *args, **kwargs):
                return con.execute(*args, **kwargs)

            def executemany(self, sql, parameters):
                if sql.startswith("INSERT OR IGNORE INTO symbol_trigrams"):
                    batch_sizes.append(len(parameters))
                return con.executemany(sql, parameters)

        index._replace_symbol_trigrams(TrackingConnection(), str(root), [path])
        con.commit()

        assert batch_sizes
        assert max(batch_sizes) == 2048
        assert all(size <= 2048 for size in batch_sizes)
        postings = dict(
            con.execute(
                "SELECT field,COUNT(*) FROM symbol_trigrams WHERE root=? AND path=? GROUP BY field",
                (str(root), path),
            )
        )
        assert postings["name"] == 1
        assert postings["name_path"] == 1


def test_trigram_candidates_preserve_full_results_scores_and_pages(tmp_path):
    root, index = _index(tmp_path)
    _insert_symbols(index, root, [
        ("src/a.py", "generate_tests", "function", 1, 2, "", "generate_tests", "", "public", ""),
        ("src/b.py", "generate_test_report", "function", 2, 3, "", "generate_test_report", "", "public", ""),
        ("src/c.py", "generate_tests_archive", "function", 3, 4, "", "generate_tests_archive", "", "public", ""),
        ("src/unicode.py", "café_café", "function", 4, 5, "", "café_café", "", "public", ""),
        ("src/repeated.py", "aaaaaa_token", "function", 5, 6, "", "aaaaaa_token", "", "public", ""),
        ("src/short.py", "ab_helper", "function", 6, 7, "", "ab_helper", "", "public", ""),
        ("src/generate/worker.py", "path_only", "function", 7, 8, "Client", "Client.path_only", "", "public", ""),
    ])

    queries = [
        ("generate", 2, 0), ("generate", 2, 2), ("CAFÉ", 10, 0),
        ("aaaaaa", 10, 0), ("ab", 10, 0), ("worker", 10, 0), ("Client", 10, 0),
    ]
    indexed = [
        index.query(str(root), query, limit=limit, offset=offset)
        for query, limit, offset in queries
    ]

    # Dropping only disposable postings exercises the complete-scan fallback as
    # an oracle over the same canonical symbols and scorer.
    with closing(sqlite3.connect(index.db_path)) as con:
        con.execute("DROP TABLE symbol_trigrams")
        con.commit()
    index._query_l1.clear()
    scanned = [
        index.query(str(root), query, limit=limit, offset=offset)
        for query, limit, offset in queries
    ]

    for actual, expected in zip(indexed, scanned):
        assert actual["total_matches"] == expected["total_matches"]
        assert actual["symbols"] == expected["symbols"]
        assert actual["has_more"] == expected["has_more"]


def test_prune_removes_postings_for_deleted_paths(tmp_path):
    root, index = _index(tmp_path)
    _insert_symbols(index, root, [
        ("src/stale.py", "stale_worker", "function", 1, 2, "", "stale_worker", "", "public", ""),
    ])
    with closing(sqlite3.connect(index.db_path)) as con:
        con.execute(
            "INSERT INTO files(root,path,content_hash,analyzer_version,language,updated_at,mtime_ns,size_bytes) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (str(root), "src/stale.py", "hash", "version", "python", 0.0, None, None),
        )
        con.commit()

    result = index.prune(str(root), [])

    assert result["success"] is True
    with closing(sqlite3.connect(index.db_path)) as con:
        assert con.execute("SELECT COUNT(*) FROM symbol_trigrams WHERE root=?", (str(root),)).fetchone()[0] == 0


def test_trigram_candidates_reduce_scored_rows_for_selective_term(tmp_path, monkeypatch):
    root, index = _index(tmp_path)
    records = []
    for number in range(32):
        name = f"unrelated_symbol_{number:03}"
        records.append((
            f"src/{number:03}.py", name, "function", number, number, "", name, "", "public", "",
        ))
    records.append(("src/match.py", "needle_worker", "function", 33, 33, "", "needle_worker", "", "public", ""))
    _insert_symbols(index, root, records)

    original = code_index_module._code_index_candidate_score
    calls = 0

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(code_index_module, "_code_index_candidate_score", counted)
    indexed = index.query(str(root), "needle")
    indexed_calls = calls
    with closing(sqlite3.connect(index.db_path)) as con:
        con.execute("DROP TABLE symbol_trigrams")
        con.commit()
    index._query_l1.clear()
    calls = 0
    scanned = index.query(str(root), "needle")

    assert indexed["symbols"] == scanned["symbols"]
    assert indexed_calls == 1
    assert calls == len(records)


def test_batch_update_and_unindexable_path_replace_postings_atomically(tmp_path):
    root = tmp_path / "repo"
    source = root / "src" / "worker.py"
    source.parent.mkdir(parents=True)
    source.write_text("def needle_worker():\n    return 1\n", encoding="utf-8")
    config = {"server": {"state_dir": str(tmp_path / "state")}}
    index = CodeIndex(config, RepositoryTools(config))

    assert index.update_files_batch(str(root), ["src/worker.py"])["success"] is True
    assert index.query(str(root), "needle_worker")["total_matches"] == 1

    source.write_text("def replacement_worker():\n    return 2\n", encoding="utf-8")
    assert index.update_files_batch(str(root), ["src/worker.py"])["success"] is True
    old_name_matches = index.query(str(root), "needle_worker")
    assert [symbol["name"] for symbol in old_name_matches["symbols"]] == ["replacement_worker"]
    assert index.query(str(root), "replacement_worker")["total_matches"] == 1

    index._mark_file_unindexable(str(root), "src/worker.py", "python")
    assert index.query(str(root), "replacement_worker")["total_matches"] == 0


def test_old_derived_schema_is_archived_and_rebuilt_without_migration(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    db_path = state / "code-index.sqlite3"
    with closing(sqlite3.connect(db_path)) as con:
        con.execute("CREATE TABLE symbols(root TEXT,path TEXT,name TEXT)")
        con.execute("INSERT INTO symbols VALUES('repo','old.py','old_symbol')")
        con.commit()

    index = CodeIndex({"server": {"state_dir": str(state)}}, SimpleNamespace(ignore_dirs=set()))

    assert list(state.glob("code-index.sqlite3.corrupt-*"))
    with closing(sqlite3.connect(index.db_path)) as con:
        assert con.execute("SELECT COUNT(*) FROM symbols").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM symbol_trigrams").fetchone()[0] == 0
