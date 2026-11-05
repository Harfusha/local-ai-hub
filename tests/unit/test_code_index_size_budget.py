from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor

import pytest

from local_ai_hub.config import ConfigError, validate_config
from local_ai_hub.code_index import CodeIndex
from local_ai_hub.preprocess import ProjectPreprocessor
from local_ai_hub.repo_tools import RepositoryTools


def _make_index(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    index = CodeIndex(
        {"server": {"state_dir": str(tmp_path / "state")}, "code_index": {"max_index_bytes": 64 * 1024 * 1024}},
        RepositoryTools({}),
    )
    for number in range(8):
        path = f"module_{number}.py"
        source = "\n".join(f"def item_{number}_{i}(): return {i}" for i in range(80)) + "\n"
        (root / path).write_text(source, encoding="utf-8")
        assert index.update_file(str(root), path)["success"]
    return index, root


def test_code_index_budget_configuration_is_bounded():
    validate_config({"code_index": {"max_index_bytes": 16 * 1024 * 1024}})
    with pytest.raises(ConfigError):
        validate_config({"code_index": {"max_index_bytes": 0}})


def test_oversized_database_skips_startup_vacuum_conversion(tmp_path, monkeypatch):
    index, _root = _make_index(tmp_path)
    index.max_index_bytes = 1
    monkeypatch.setattr(
        "local_ai_hub.code_index.ensure_incremental_vacuum",
        lambda *_args, **_kwargs: pytest.fail("large database must not start a full VACUUM"),
    )

    index._init_db()

    index.close()


def test_code_index_budget_dry_run_is_read_only_and_orders_cold_files(tmp_path):
    index, root = _make_index(tmp_path)
    index.record_usage(
        str(root),
        [
            {"path": "module_0.py", "uses": 50, "last_used_at": 20.0},
            {"path": "module_1.py", "uses": 2, "last_used_at": 10.0},
        ],
    )
    before = index.measure_storage()

    result = index.enforce_size_limit(max_bytes=max(1, before["physical_bytes"] - 1), dry_run=True)

    assert result["success"] is True
    assert result["dry_run"] is True
    assert result["evicted_paths"]
    assert result["evicted_paths"][0] == (str(root), "module_2.py")
    assert index.measure_storage()["physical_bytes"] == before["physical_bytes"]
    index.close()


def test_code_index_reclaims_freelist_before_evicting_live_files(tmp_path):
    index, root = _make_index(tmp_path)
    removed = root / "module_7.py"
    removed.unlink()
    assert index.update_file(str(root), "module_7.py")["success"]
    before = index.measure_storage()
    assert before["reusable_bytes"] > 0
    live_bytes = before["physical_bytes"] - before["reusable_bytes"]
    index.max_index_bytes = 1

    dry_run = index.enforce_size_limit(max_bytes=live_bytes, dry_run=True)

    assert dry_run["success"] is True
    assert dry_run["evicted_paths"] == []
    assert dry_run["within_budget"] is True
    assert index.measure_storage()["physical_bytes"] == before["physical_bytes"]

    result = index.enforce_size_limit(max_bytes=live_bytes)

    assert result["success"] is True
    assert result["evicted_paths"] == []
    assert result["physical_bytes_released"] > 0
    assert result["after"]["physical_bytes"] < before["physical_bytes"]
    with closing(index._connect()) as con:
        remaining = con.execute("SELECT COUNT(*) FROM files WHERE root=?", (str(root),)).fetchone()[0]
    assert remaining == 7
    index.close()


def test_code_index_budget_evicts_cold_rows_and_releases_sqlite_pages(tmp_path):
    index, root = _make_index(tmp_path)
    index.record_usage(
        str(root),
        [{"path": "module_0.py", "uses": 50, "last_used_at": 20.0}],
    )
    before = index.measure_storage()

    result = index.enforce_size_limit(max_bytes=max(1, before["physical_bytes"] - 1))

    after = index.measure_storage()
    assert result["success"] is True
    assert result["evicted_paths"]
    assert result["evicted_paths"][0] == (str(root), "module_1.py")
    assert after["physical_bytes"] < before["physical_bytes"]
    assert after["page_count"] < before["page_count"]
    with closing(index._connect()) as con:
        indexed = {str(row[0]) for row in con.execute("SELECT path FROM files WHERE root=?", (str(root),))}
    assert "module_0.py" in indexed
    assert "module_1.py" not in indexed
    index.close()


def test_size_limit_preserves_protected_roots_and_reports_remaining_overage(tmp_path):
    index, protected_root = _make_index(tmp_path)
    cold_root = tmp_path / "cold"
    cold_root.mkdir()
    for number in range(3):
        path = f"cold_{number}.py"
        (cold_root / path).write_text("def cold(): return 1\n", encoding="utf-8")
        assert index.update_file(str(cold_root), path)["success"]

    result = index.enforce_size_limit(
        max_bytes=1,
        protected_roots=(str(protected_root),),
    )

    assert result["success"] is True
    assert result["evicted_paths"]
    assert {root for root, _path in result["evicted_paths"]} == {str(cold_root)}
    assert result["within_budget"] is False
    with closing(index._connect()) as con:
        protected_count = con.execute(
            "SELECT COUNT(*) FROM files WHERE root=?", (str(protected_root),)
        ).fetchone()[0]
        cold_count = con.execute(
            "SELECT COUNT(*) FROM files WHERE root=?", (str(cold_root),)
        ).fetchone()[0]
    assert protected_count == 8
    assert cold_count == 0
    index.close()


def test_idle_maintenance_protects_running_roots_and_rechecks_over_budget(tmp_path, monkeypatch):
    db_path = tmp_path / "preprocess.sqlite3"
    registered_root = str(tmp_path / "active-worktree")
    with closing(sqlite3.connect(db_path)) as con:
        con.executescript(
            "CREATE TABLE content_cards(card_key TEXT, accessed_at REAL);"
            "CREATE TABLE file_refs(card_key TEXT);"
            "CREATE TABLE projects(root TEXT, status TEXT);"
        )
        con.executemany(
            "INSERT INTO projects(root,status) VALUES (?,?)",
            [(registered_root, "running"), (str(tmp_path / "waiting-worktree"), "waiting")],
        )
        con.commit()

    observed = {}
    calls = []
    clock = [10_000.0]
    monkeypatch.setattr("local_ai_hub.preprocess.time.time", lambda: clock[0])

    class RecordingIndex:
        def enforce_size_limit(self, **kwargs):
            observed.update(kwargs)
            calls.append(kwargs)
            return {"success": True, "within_budget": len(calls) > 1}

    worker = ProjectPreprocessor.__new__(ProjectPreprocessor)
    worker.db_path = db_path
    worker.state_dir = tmp_path
    worker.cfg = {"db_maintenance_interval_seconds": 1800}
    worker._db_lock = threading.RLock()
    worker._stats_lock = threading.RLock()
    worker._stats = {}
    worker._last_db_maintenance = 0.0
    worker._yield = lambda: False
    worker._connect = lambda: sqlite3.connect(db_path)
    worker.code_index = RecordingIndex()
    worker.deterministic = None
    worker.rag = None
    worker.cleanup_deleted_projects = lambda: None
    worker.cleanup_orphaned_indexes = lambda: None

    assert worker._run_idle_database_maintenance() is True
    assert observed["protected_roots"] == (registered_root,)
    assert observed["max_files"] == 512
    assert worker._last_db_maintenance == 10_000.0
    clock[0] = 10_299.0
    assert worker._run_idle_database_maintenance() is False
    clock[0] = 10_300.0
    assert worker._run_idle_database_maintenance() is True
    assert len(calls) == 2
    assert worker._db_maintenance_retry_interval is None
    clock[0] = 12_099.0
    assert worker._run_idle_database_maintenance() is False
    clock[0] = 12_100.0
    assert worker._run_idle_database_maintenance() is True
    assert len(calls) == 3


def test_size_limit_dry_run_bounds_candidate_inventory(tmp_path, monkeypatch):
    index, _root = _make_index(tmp_path)
    original_connect = index._connect
    candidate_limits = []

    class RecordingConnection:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, sql, params=()):
            if "FROM files f LEFT JOIN file_usage" in sql:
                candidate_limits.append(params[-1] if params else None)
            return self.connection.execute(sql, params)

        def close(self):
            self.connection.close()

    monkeypatch.setattr(
        index, "_connect",
        lambda: RecordingConnection(original_connect()),
    )

    result = index.enforce_size_limit(max_bytes=1, dry_run=True, max_files=3)

    assert result["success"] is True
    assert candidate_limits == [3]
    index.close()


def test_batch_write_is_deferred_when_budget_cannot_fit_and_preserves_parse_cache(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "hot.py"
    source.write_text("def hot_symbol(): return 1\n", encoding="utf-8")
    index = CodeIndex(
        {"server": {"state_dir": str(tmp_path / "state")}, "code_index": {"max_index_bytes": 1}},
        RepositoryTools({}),
    )

    result = index.update_files_batch(str(root), ["hot.py"])

    assert result["success"] is False
    assert result["budget_limited"] is True
    with closing(index._connect()) as con:
        assert con.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM parse_blobs").fetchone()[0] == 0
    index.close()


def test_single_file_write_is_deferred_when_budget_cannot_fit(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "hot.py").write_text("def hot_symbol(): return 1\n", encoding="utf-8")
    index = CodeIndex(
        {"server": {"state_dir": str(tmp_path / "state")}, "code_index": {"max_index_bytes": 1}},
        RepositoryTools({}),
    )

    result = index.update_file(str(root), "hot.py")

    assert result["success"] is False
    assert result["budget_limited"] is True
    with closing(index._connect()) as con:
        assert con.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM parse_blobs").fetchone()[0] == 0
    index.close()


def test_write_budget_pass_protects_current_and_active_roots(tmp_path, monkeypatch):
    index, root = _make_index(tmp_path)
    index.max_index_bytes = 100_000
    index.set_active_roots_provider(lambda: (str(root / "active"),))
    measured = iter((
        {"physical_bytes": 90_000, "reusable_bytes": 0},
        {"physical_bytes": 80_000, "reusable_bytes": 0},
    ))
    calls = []
    monkeypatch.setattr(index, "measure_storage", lambda: next(measured))
    monkeypatch.setattr(index, "enforce_size_limit", lambda **kwargs: calls.append(kwargs) or {"success": True})

    result = index._reserve_write_budget(str(root), 20_000)

    assert result["success"] is True
    assert calls[0]["max_bytes"] == 80_000
    assert set(calls[0]["protected_roots"]) == {str(root), str(root / "active")}
    index.close()


def test_active_root_snapshot_includes_only_running_projects(tmp_path):
    db_path = tmp_path / "preprocess.sqlite3"
    active = str(tmp_path / "active")
    waiting = str(tmp_path / "waiting")
    with closing(sqlite3.connect(db_path)) as con:
        con.execute("CREATE TABLE projects(root TEXT, status TEXT)")
        con.executemany("INSERT INTO projects(root,status) VALUES (?,?)", [
            (active, "running"), (waiting, "waiting"),
        ])
        con.commit()
    worker = ProjectPreprocessor.__new__(ProjectPreprocessor)
    worker._db_lock = threading.RLock()
    worker._connect = lambda: sqlite3.connect(db_path)

    assert worker._active_code_index_roots() == (active,)


def test_budget_limited_change_keeps_old_rows_for_freshness_filter(tmp_path):
    index, root = _make_index(tmp_path)
    before = index.files_needing_reindex(str(root), [("module_0.py", "old-hash")])
    with closing(index._connect()) as con:
        old_hash = con.execute(
            "SELECT content_hash FROM files WHERE root=? AND path=?", (str(root), "module_0.py")
        ).fetchone()[0]
    (root / "module_0.py").write_text("def changed_symbol(): return 2\n", encoding="utf-8")
    index.max_index_bytes = 1

    result = index.update_files_batch(str(root), [("module_0.py", "new-hash")])

    assert before == [("module_0.py", "old-hash")]
    assert result["budget_limited"] is True
    with closing(index._connect()) as con:
        kept_hash = con.execute(
            "SELECT content_hash FROM files WHERE root=? AND path=?", (str(root), "module_0.py")
        ).fetchone()[0]
    assert kept_hash == old_hash
    index.close()


def test_budget_limited_batch_still_removes_deleted_source(tmp_path):
    index, root = _make_index(tmp_path)
    (root / "module_7.py").unlink()
    (root / "new.py").write_text("def new_symbol(): return 1\n", encoding="utf-8")
    index.max_index_bytes = 1

    result = index.update_files_batch(str(root), ["module_7.py", "new.py"])

    assert result["budget_limited"] is True
    with closing(index._connect()) as con:
        assert con.execute(
            "SELECT COUNT(*) FROM files WHERE root=? AND path='module_7.py'", (str(root),)
        ).fetchone()[0] == 0
        assert con.execute(
            "SELECT COUNT(*) FROM files WHERE root=? AND path='new.py'", (str(root),)
        ).fetchone()[0] == 0
    index.close()


def test_concurrent_single_file_writers_share_budget_admission_lock(tmp_path, monkeypatch):
    index, root = _make_index(tmp_path)
    for name in ("parallel_a.py", "parallel_b.py"):
        (root / name).write_text(f"def {name[:-3]}(): return 1\n", encoding="utf-8")
    original = index._reserve_write_budget
    guard = threading.Lock()
    active = [0]
    peak = [0]

    def observed(*args, **kwargs):
        with guard:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.02)
        try:
            return original(*args, **kwargs)
        finally:
            with guard:
                active[0] -= 1

    monkeypatch.setattr(index, "_reserve_write_budget", observed)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda name: index.update_file(str(root), name), ("parallel_a.py", "parallel_b.py")))

    assert all(result["success"] for result in results)
    assert peak[0] == 1
    index.close()


def test_eviction_preserves_parse_blob_still_shared_by_an_active_root(tmp_path):
    root_a = tmp_path / "active"
    root_b = tmp_path / "cold"
    root_a.mkdir()
    root_b.mkdir()
    source = "def shared_symbol(): return 1\n"
    (root_a / "same.py").write_text(source, encoding="utf-8")
    (root_b / "same.py").write_text(source, encoding="utf-8")
    index = CodeIndex(
        {"server": {"state_dir": str(tmp_path / "state")}, "code_index": {"max_index_bytes": 64 * 1024 * 1024}},
        RepositoryTools({}),
    )
    assert index.update_file(str(root_a), "same.py")["success"]
    assert index.update_file(str(root_b), "same.py")["success"]

    result = index.enforce_size_limit(max_bytes=1, protected_roots=(str(root_a),))

    assert (str(root_b), "same.py") in result["evicted_paths"]
    with closing(index._connect()) as con:
        assert con.execute(
            "SELECT COUNT(*) FROM parse_blobs WHERE content_hash=(SELECT content_hash FROM files WHERE root=? AND path=?)",
            (str(root_a), "same.py"),
        ).fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM files WHERE root=?", (str(root_a),)).fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM files WHERE root=?", (str(root_b),)).fetchone()[0] == 0
    index.close()


def test_write_budget_refuses_eviction_when_active_root_snapshot_fails(tmp_path, monkeypatch):
    index, root = _make_index(tmp_path)
    physical = index._physical_storage_bytes()
    index.max_index_bytes = physical + 10
    index.set_active_roots_provider(lambda: (_ for _ in ()).throw(OSError("snapshot unavailable")))
    calls = []
    monkeypatch.setattr(index, "enforce_size_limit", lambda **kwargs: calls.append(kwargs) or {"success": True})

    result = index._reserve_write_budget(str(root), 20)

    assert result["budget_limited"] is True
    assert result["reason"] == "active_roots_unavailable"
    assert calls == []
    index.close()


def test_stale_cleanup_only_prunes_paths_confirmed_stale_at_scan_time(tmp_path, monkeypatch):
    index, root = _make_index(tmp_path)
    (root / "module_7.py").unlink()
    original_prune = index.prune

    def add_file_before_prune(root_path, current_paths, *, stale_paths=None):
        (root / "arrived_during_cleanup.py").write_text(
            "def new_during_cleanup(): return 1\n", encoding="utf-8"
        )
        index.update_file(root_path, "arrived_during_cleanup.py")
        return original_prune(root_path, current_paths, stale_paths=stale_paths)

    monkeypatch.setattr(index, "prune", add_file_before_prune)
    result = index.cleanup_stale_files(dry_run=False)

    assert result["success"] is True
    assert result["files_pruned"] == 1
    with closing(index._connect()) as con:
        indexed = {
            str(row[0]) for row in con.execute(
                "SELECT path FROM files WHERE root=?", (str(root),)
            )
        }
        assert "module_7.py" not in indexed
        assert "arrived_during_cleanup.py" in indexed
    index.close()


def test_stale_cleanup_dry_run_reports_without_deleting_shared_parse_cache(tmp_path):
    index, root = _make_index(tmp_path)
    (root / "module_6.py").unlink()
    with closing(index._connect()) as con:
        parse_count_before = int(con.execute("SELECT COUNT(*) FROM parse_blobs").fetchone()[0])
    before = index.measure_storage()

    result = index.cleanup_stale_files(dry_run=True)

    assert result["success"] is True
    assert result["stale_file_count"] == 1
    assert result["logical_source_bytes"] > 0
    assert result["storage_after"] == before
    with closing(index._connect()) as con:
        assert int(con.execute("SELECT COUNT(*) FROM parse_blobs").fetchone()[0]) == parse_count_before
        assert con.execute(
            "SELECT 1 FROM files WHERE root=? AND path=?", (str(root), "module_6.py")
        ).fetchone() is not None
    index.close()


def test_record_usage_uses_evidence_recency_not_preprocess_time(tmp_path):
    index, root = _make_index(tmp_path)
    indexed_path = "module_0.py"
    with closing(index._connect()) as con:
        con.execute(
            "INSERT INTO file_usage(root,path,use_count,last_used_at) VALUES(?,?,?,?)",
            (str(root), indexed_path, 40, 2_000.0),
        )
        con.execute(
            "INSERT INTO file_usage(root,path,use_count,last_used_at) VALUES(?,?,?,?)",
            (str(root), "module_1.py", 30, 2_000.0),
        )
        con.commit()

    index.record_usage(
        str(root), [{"path": indexed_path, "uses": 41, "last_used": 1_000.0}]
    )

    with closing(index._connect()) as con:
        row = con.execute(
            "SELECT use_count,last_used_at FROM file_usage WHERE root=? AND path=?",
            (str(root), indexed_path),
        ).fetchone()
    assert tuple(row) == (41, 1_000.0)
    with closing(index._connect()) as con:
        absent = con.execute(
            "SELECT use_count,last_used_at FROM file_usage WHERE root=? AND path=?",
            (str(root), "module_1.py"),
        ).fetchone()
    assert tuple(absent) == (30, 0.0)
    index.close()


def test_unreferenced_parse_blob_cleanup_is_bounded_and_preserves_shared_cache(tmp_path):
    index, root = _make_index(tmp_path)
    orphan_payload = "x" * 100_000
    with closing(index._connect()) as con:
        con.executemany(
            "INSERT INTO parse_blobs(content_hash,analyzer_version,language,payload_json,updated_at) "
            "VALUES(?,?,?,?,?)",
            [
                ("orphan-old", "old-analyzer", "python", orphan_payload, 1.0),
                ("orphan-current", "current-analyzer", "python", orphan_payload, 2.0),
            ],
        )
        shared = con.execute(
            "SELECT content_hash,analyzer_version,language FROM files WHERE root=? AND path=?",
            (str(root), "module_0.py"),
        ).fetchone()
        con.commit()
    before = index.measure_storage()

    dry_run = index.prune_unreferenced_parse_blobs(dry_run=True, max_blobs=1)

    assert dry_run["success"] is True
    assert dry_run["candidate_blob_count"] == 2
    assert dry_run["selected_blob_count"] == 1
    assert dry_run["selected_payload_bytes"] == len(orphan_payload)
    assert index.measure_storage() == before

    first = index.prune_unreferenced_parse_blobs(dry_run=False, max_blobs=1)
    assert first["deleted_blob_count"] == 1
    assert first["logical_bytes_released"] == len(orphan_payload)
    assert first["remaining_unreferenced_blob_count"] == 1
    second = index.prune_unreferenced_parse_blobs(dry_run=False, max_blobs=1)
    assert second["deleted_blob_count"] == 1
    assert second["remaining_unreferenced_blob_count"] == 0
    with closing(index._connect()) as con:
        assert con.execute(
            "SELECT 1 FROM parse_blobs WHERE content_hash=? AND analyzer_version=? AND language=?",
            tuple(shared),
        ).fetchone() is not None
    index.close()


def test_size_limit_dry_run_includes_unreferenced_parse_cache_without_mutating(tmp_path):
    index, _root = _make_index(tmp_path)
    orphan_payload = "x" * 100_000
    with closing(index._connect()) as con:
        con.execute(
            "INSERT INTO parse_blobs(content_hash,analyzer_version,language,payload_json,updated_at) "
            "VALUES(?,?,?,?,?)",
            ("orphan", "old-analyzer", "python", orphan_payload, 1.0),
        )
        con.commit()
    before = index.measure_storage()
    live_bytes = before["physical_bytes"] - before["reusable_bytes"]

    result = index.enforce_size_limit(max_bytes=live_bytes - 50_000, dry_run=True)

    assert result["success"] is True
    assert result["parse_cache_cleanup"]["selected_blob_count"] == 1
    assert result["parse_cache_cleanup"]["selected_payload_bytes"] == len(orphan_payload)
    assert result["evicted_paths"] == []
    assert result["within_budget"] is True
    assert index.measure_storage() == before
    with closing(index._connect()) as con:
        assert con.execute(
            "SELECT 1 FROM parse_blobs WHERE content_hash='orphan'"
        ).fetchone() is not None
    index.close()


def test_unreferenced_parse_blob_cleanup_serializes_independent_connections(tmp_path):
    index, root = _make_index(tmp_path)
    second = CodeIndex(
        {"server": {"state_dir": str(tmp_path / "state")}, "code_index": {"max_index_bytes": 64 * 1024 * 1024}},
        RepositoryTools({}),
    )
    with closing(index._connect()) as con:
        con.executemany(
            "INSERT INTO parse_blobs(content_hash,analyzer_version,language,payload_json,updated_at) "
            "VALUES(?,?,?,?,?)",
            [
                (f"orphan-{n}", "old-analyzer", "python", "x" * 1000, float(n))
                for n in range(4)
            ],
        )
        shared = con.execute(
            "SELECT content_hash,analyzer_version,language FROM files WHERE root=? AND path=?",
            (str(root), "module_0.py"),
        ).fetchone()
        con.commit()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda worker: worker.prune_unreferenced_parse_blobs(dry_run=False, max_blobs=2),
            (index, second),
        ))

    assert all(result["success"] is True for result in results)
    assert sum(result["deleted_blob_count"] for result in results) == 4
    assert sorted(result["remaining_unreferenced_blob_count"] for result in results) == [0, 2]
    with closing(index._connect()) as con:
        assert con.execute(
            "SELECT COUNT(*) FROM parse_blobs WHERE content_hash LIKE 'orphan-%'"
        ).fetchone()[0] == 0
        assert con.execute(
            "SELECT 1 FROM parse_blobs WHERE content_hash=? AND analyzer_version=? AND language=?",
            tuple(shared),
        ).fetchone() is not None
    second.close()
    index.close()
