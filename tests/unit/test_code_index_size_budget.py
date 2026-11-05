from __future__ import annotations

from contextlib import closing
from concurrent.futures import ThreadPoolExecutor

import pytest

from local_ai_hub.config import ConfigError, validate_config
from local_ai_hub.code_index import CodeIndex
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
