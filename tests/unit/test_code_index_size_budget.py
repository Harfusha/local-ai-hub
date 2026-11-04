from __future__ import annotations

from contextlib import closing

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
