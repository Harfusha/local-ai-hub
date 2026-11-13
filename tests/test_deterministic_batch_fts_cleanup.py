from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path

import pytest

from local_ai_hub import deterministic as deterministic_module, sqlite_support
from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.repo_tools import RepositoryTools


@pytest.fixture
def engine(tmp_path):
    config = {"server": {"state_dir": str(tmp_path / "state")}}
    return DeterministicEngine(config, RepositoryTools(config))


def _write(root: Path, path: str, name: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / path).write_text(f"def {name}():\n    return 1\n", encoding="utf-8")


def _trace(engine, monkeypatch):
    statements = []
    connect = engine._connect

    def traced_connect():
        con = connect()
        con.set_trace_callback(statements.append)
        return con

    monkeypatch.setattr(engine, "_connect", traced_connect)
    return statements


def _fts_deletes(statements):
    return [sql for sql in statements if sql.lstrip().upper().startswith("DELETE FROM FACT_FTS ")]


def _snapshot(engine, root=None, path=None):
    with closing(engine._connect()) as con:
        where = " WHERE root=? AND path=?" if root is not None else ""
        params = (str(root), path) if root is not None else ()
        return {
            table: [tuple(row) for row in con.execute(f"SELECT rowid,* FROM {table}{where} ORDER BY rowid", params)]
            for table in ("files", "facts", "fact_fts")
        }


def _assert_facts_match_fts(engine):
    with closing(engine._connect()) as con:
        columns = "root,path,kind,name,value"
        ordinary = sorted(tuple(row) for row in con.execute(f"SELECT {columns} FROM facts"))
        fts = sorted(tuple(row) for row in con.execute(f"SELECT {columns} FROM fact_fts"))
    assert ordinary == fts


def test_query_cache_write_uses_bounded_transaction(engine, tmp_path, monkeypatch):
    observed = []
    real_write_transaction = sqlite_support.write_transaction

    def record_transaction(connection, **kwargs):
        observed.append(kwargs)
        return real_write_transaction(connection, **kwargs)

    monkeypatch.setattr(deterministic_module, "write_transaction", record_transaction)
    root = str((tmp_path / "repo").resolve())

    engine._query_cache_put(root, 0, "lookup", {"result": "cached"})

    cache_transactions = [
        item for item in observed if item.get("rollback_label") == "deterministic query cache"
    ]
    assert len(cache_transactions) == 1
    assert cache_transactions[0]["max_duration_seconds"] == 1.0


def test_deterministic_file_and_batch_writes_use_bounded_transactions(
    engine, tmp_path, monkeypatch
):
    observed = []
    real_write_transaction = sqlite_support.write_transaction

    def record_transaction(connection, **kwargs):
        observed.append(kwargs)
        return real_write_transaction(connection, **kwargs)

    monkeypatch.setattr(deterministic_module, "write_transaction", record_transaction)
    root = tmp_path / "repo"
    _write(root, "single.py", "single")
    single = engine.update_file(str(root), "single.py")
    _write(root, "batch.py", "batch")
    batch = engine.update_files_batch(str(root), ["batch.py"])

    assert single["success"] is True
    assert batch["success"] is True
    labels = {item.get("rollback_label"): item for item in observed}
    assert labels["deterministic update file"]["max_duration_seconds"] == 5.0
    assert labels["deterministic batch update"]["max_duration_seconds"] == 5.0


def test_manifest_refresh_uses_bounded_transaction(engine, tmp_path, monkeypatch):
    observed = []
    real_write_transaction = sqlite_support.write_transaction

    def record_transaction(connection, **kwargs):
        observed.append(kwargs)
        return real_write_transaction(connection, **kwargs)

    monkeypatch.setattr(deterministic_module, "write_transaction", record_transaction)
    root = tmp_path / "manifest-repo"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        '[project]\nname = "sample"\nversion = "1.0"\ndependencies = ["sample-dep>=1"]\n',
        encoding="utf-8",
    )

    result = engine.refresh_manifests(str(root))

    assert result["success"] is True
    transaction = next(
        item for item in observed if item.get("rollback_label") == "deterministic manifest refresh"
    )
    assert transaction["max_duration_seconds"] == 5.0


def test_deterministic_projection_cache_and_prune_writes_are_bounded(
    engine, tmp_path, monkeypatch
):
    observed = []
    real_write_transaction = sqlite_support.write_transaction

    def record_transaction(connection, **kwargs):
        observed.append(kwargs)
        return real_write_transaction(connection, **kwargs)

    monkeypatch.setattr(deterministic_module, "write_transaction", record_transaction)
    root = str((tmp_path / "repo").resolve())
    engine.record_test_source_links(root, [("src/app.py", "tests/test_app.py", 1.0)])
    engine._fact_blob_put("fact-hash", "python", [{"kind": "class", "name": "App"}])
    engine._manifest_blob_put("manifest-hash", "pyproject.toml", [], [])
    with closing(engine._connect()) as con:
        con.execute(
            "INSERT INTO files(root,path,content_hash,language,is_test,updated_at) VALUES(?,?,?,?,?,?)",
            (root, "stale.py", "stale-hash", "python", 0, 1.0),
        )
        con.commit()
    assert engine.prune(root, []) == 1
    monkeypatch.setattr(
        engine,
        "detect_dead_code",
        lambda _root, limit=500: {"success": True, "dead_symbols": [{"path": "a.py", "name": "unused", "kind": "function"}]},
    )
    assert engine.precompute_dead_code(root)["count"] == 1

    labels = {item.get("rollback_label"): item for item in observed}
    expected = {
        "deterministic test source links": 5.0,
        "deterministic fact blob cache": 1.0,
        "deterministic manifest blob cache": 1.0,
        "deterministic prune": 5.0,
        "deterministic dead-code projection": 5.0,
    }
    for label, duration in expected.items():
        assert labels[label]["max_duration_seconds"] == duration


@pytest.mark.parametrize("paths", [None, []], ids=["omitted", "empty"])
def test_deterministic_build_never_expands_to_the_whole_project(engine, tmp_path, monkeypatch, paths):
    root = tmp_path / "repo"
    root.mkdir()

    def unexpected(*_args, **_kwargs):
        pytest.fail("demand build must not enumerate the project")

    monkeypatch.setattr(engine.repo_tools, "iter_files", unexpected)
    monkeypatch.setattr(engine, "update_file", unexpected)
    monkeypatch.setattr(engine, "prune", unexpected)
    monkeypatch.setattr(engine, "refresh_manifests", unexpected)

    result = engine.build(str(root), paths=paths)

    if paths is None:
        assert result["success"] is False
        assert result["coverage_complete"] is False
        assert result["reason"] == "explicit_paths_required"
    else:
        assert result["success"] is True
        assert result["coverage_complete"] is True
        assert result["files"] == 0


def test_deterministic_build_bounds_explicit_paths_and_skips_global_cleanup(engine, tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    engine.config["preprocessing"] = {"deterministic_files_per_step": 2}
    indexed: list[str] = []

    def update_file(_root: str, path: str) -> dict[str, bool]:
        indexed.append(path)
        return {"success": True}

    def unexpected(*_args, **_kwargs):
        pytest.fail("bounded demand build must not scan or prune the project")

    monkeypatch.setattr(engine, "update_file", update_file)
    monkeypatch.setattr(engine.repo_tools, "iter_files", unexpected)
    monkeypatch.setattr(engine, "prune", unexpected)
    monkeypatch.setattr(engine, "refresh_manifests", unexpected)

    result = engine.build(str(root), paths=["used.py", "related.py", "unrelated.py"])

    assert indexed == ["used.py", "related.py"]
    assert result["files"] == 2
    assert result["coverage_complete"] is False
    assert result["remaining"] == 1


@pytest.mark.parametrize("batch_size", [1, 32, 128])
def test_batch_fts_cleanup_one_delete_with_isolated_scaling_measurement(
    engine, tmp_path, monkeypatch, batch_size
):
    root = tmp_path / "repo"
    paths = [f"file_{index}.py" for index in range(batch_size)]
    for index, path in enumerate(paths):
        _write(root, path, f"old_{index}")
    engine.update_files_batch(str(root), paths)
    # An isolated background corpus makes repeated FTS scans measurable.
    with closing(engine._connect()) as con:
        filler = [(str(tmp_path / "other"), f"filler_{index}.py", "function", f"filler_{index}", "", 1, "{}") for index in range(8192)]
        con.executemany("INSERT INTO facts(root,path,kind,name,value,line,extra_json) VALUES(?,?,?,?,?,?,?)", filler)
        con.executemany("INSERT INTO fact_fts(root,path,kind,name,value) VALUES(?,?,?,?,?)", [row[:5] for row in filler])
        con.commit()
        plan = [str(row[3]) for row in con.execute(
            "EXPLAIN QUERY PLAN DELETE FROM fact_fts WHERE root=? AND path=?", (str(root), paths[0])
        )]
    assert any("VIRTUAL TABLE INDEX 0:" in detail for detail in plan)
    for index, path in enumerate(paths):
        _write(root, path, f"new_{index}")
    statements = _trace(engine, monkeypatch)

    started = time.perf_counter()
    result = engine.update_files_batch(str(root), paths)
    elapsed_ms = (time.perf_counter() - started) * 1000
    deletes = _fts_deletes(statements)

    assert result["updated"] == batch_size
    _assert_facts_match_fts(engine)
    with closing(engine._connect()) as con:
        assert not con.execute("SELECT 1 FROM facts WHERE root=? AND name LIKE 'old_%' LIMIT 1", (str(root),)).fetchone()
        assert con.execute("SELECT COUNT(*) FROM fact_fts WHERE root=?", (str(tmp_path / "other"),)).fetchone()[0] == 8192
    print("FTS_BATCH_METRIC " + json.dumps({"batch_size": batch_size, "fts_delete_statements": len(deletes), "elapsed_ms": round(elapsed_ms, 3), "background_facts": 8192}))
    assert len(deletes) == 1


def test_batch_fts_cleanup_isolates_cached_file_and_other_root(engine, tmp_path, monkeypatch):
    root = tmp_path / "repo's"
    other = tmp_path / "other"
    paths = ["a's.py", "b.py", "unchanged.py"]
    for index, path in enumerate(paths):
        _write(root, path, f"old_{index}")
    _write(other, paths[0], "other_root")
    engine.update_files_batch(str(root), paths)
    engine.update_files_batch(str(other), [paths[0]])
    unchanged = _snapshot(engine, root, paths[2])
    other_before = _snapshot(engine, other, paths[0])
    _write(root, paths[0], "new_a")
    _write(root, paths[1], "new_b")
    statements = _trace(engine, monkeypatch)

    result = engine.update_files_batch(str(root), paths)

    assert result["updated"] == 2
    assert result["cached"] == 1
    assert _snapshot(engine, root, paths[2]) == unchanged
    assert _snapshot(engine, other, paths[0]) == other_before
    _assert_facts_match_fts(engine)
    assert len(_fts_deletes(statements)) == 1
    statements.clear()
    assert engine.update_files_batch(str(root), paths)["cached"] == 3
    assert not _fts_deletes(statements)


def test_batch_fts_cleanup_duplicate_input_has_no_duplicate_facts(engine, tmp_path):
    root = tmp_path / "repo"
    _write(root, "a.py", "old_a")
    engine.update_files_batch(str(root), ["a.py"])
    _write(root, "a.py", "new_a")

    result = engine.update_files_batch(str(root), ["a.py", "a.py"])

    assert result["updated"] == 2
    _assert_facts_match_fts(engine)


def test_duplicate_batch_keeps_last_occurrence_order_for_bounded_fts_candidates(engine, tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    source = "\n".join(f"def shared_{index:03d}():\n    return 1\n" for index in range(400))
    for name in ("a.py", "b.py"):
        (root / name).write_text(source, encoding="utf-8")

    engine.update_files_batch(str(root), ["a.py", "b.py", "a.py"])

    # The legacy repeated delete/reinsert puts b before the final a. Equal
    # BM25 scores hit the 300-candidate bound before the final path sort.
    found = engine._facts(str(root), terms=["shared"], limit=1)
    assert len(found) == 1
    assert found[0]["path"] == "b.py"
    _assert_facts_match_fts(engine)


def test_batch_fts_cleanup_rolls_back_facts_fts_files_blobs_and_generation(engine, tmp_path, monkeypatch):
    root = tmp_path / "repo"
    for name in ("a", "b"):
        _write(root, f"{name}.py", f"old_{name}")
    engine.update_files_batch(str(root), ["a.py", "b.py"])
    before = _snapshot(engine)
    with closing(engine._connect()) as con:
        blobs = [tuple(row) for row in con.execute("SELECT * FROM fact_blobs ORDER BY content_hash")]
        generation = [tuple(row) for row in con.execute("SELECT * FROM project_state ORDER BY root")]
        con.execute("CREATE TRIGGER fail_second_fact BEFORE INSERT ON facts WHEN NEW.name='new_b' BEGIN SELECT RAISE(ABORT,'injected fact failure'); END")
        con.commit()
    for name in ("a", "b"):
        _write(root, f"{name}.py", f"new_{name}")
    statements = _trace(engine, monkeypatch)

    with pytest.raises(sqlite3.IntegrityError, match="injected fact failure"):
        engine.update_files_batch(str(root), ["a.py", "b.py"])

    assert _fts_deletes(statements)
    assert _snapshot(engine) == before
    with closing(engine._connect()) as con:
        assert [tuple(row) for row in con.execute("SELECT * FROM fact_blobs ORDER BY content_hash")] == blobs
        assert [tuple(row) for row in con.execute("SELECT * FROM project_state ORDER BY root")] == generation


def test_batch_fts_cleanup_works_without_fts_table(engine, tmp_path):
    root = tmp_path / "repo"
    _write(root, "a.py", "old_a")
    engine.update_files_batch(str(root), ["a.py"])
    with closing(engine._connect()) as con:
        con.execute("DROP TABLE fact_fts")
        con.commit()
    _write(root, "a.py", "new_a")
    _write(root, "b.py", "new_b")

    result = engine.update_files_batch(str(root), ["a.py", "b.py"])

    assert result["success"] is True
    assert result["updated"] == 2
    with closing(engine._connect()) as con:
        assert con.execute("SELECT name FROM facts WHERE root=? AND name='new_a'", (str(root),)).fetchone()
        assert con.execute("SELECT name FROM facts WHERE root=? AND name='new_b'", (str(root),)).fetchone()
        assert not con.execute("SELECT 1 FROM facts WHERE root=? AND name='old_a'", (str(root),)).fetchone()
        assert not con.execute("SELECT 1 FROM sqlite_master WHERE name LIKE '_deterministic_batch%' ").fetchone()
