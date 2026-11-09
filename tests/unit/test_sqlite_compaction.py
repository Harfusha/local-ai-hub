from __future__ import annotations

import sqlite3

from local_ai_hub.sqlite_support import compact_sqlite_database


def _make_fragmented_database(path):
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA auto_vacuum=INCREMENTAL")
    connection.execute("CREATE TABLE records(id INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
    connection.executemany(
        "INSERT INTO records(payload) VALUES(?)",
        [(f"{index:08d}" + "x" * 4000,) for index in range(5000)],
    )
    connection.commit()
    connection.execute("DELETE FROM records WHERE id > 100")
    connection.commit()
    connection.close()


def test_compaction_dry_run_measures_reclaimable_pages_without_writes(tmp_path):
    path = tmp_path / "code-index.sqlite3"
    _make_fragmented_database(path)
    before = path.stat().st_size

    result = compact_sqlite_database(path, dry_run=True)

    assert result["success"] is True
    assert result["dry_run"] is True
    assert result["before"]["freelist_pages"] > 0
    assert result["estimated_reclaimable_bytes"] == (
        result["before"]["freelist_pages"] * result["before"]["page_size"]
    )
    assert path.stat().st_size == before


def test_compaction_vacuums_and_verifies_database_content(tmp_path):
    path = tmp_path / "code-index.sqlite3"
    _make_fragmented_database(path)
    before = path.stat().st_size

    result = compact_sqlite_database(path, dry_run=False, timeout_seconds=30, offline_confirmed=True)

    assert result["success"] is True
    assert result["verified"] is True
    assert result["row_counts_before"] == result["row_counts_after"] == {"records": 100}
    assert result["physical_bytes_released"] > before // 2
    assert result["after"]["physical_bytes"] < before // 2


def test_compaction_rejects_invalid_controls(tmp_path):
    path = tmp_path / "missing.sqlite3"

    assert compact_sqlite_database(path, dry_run=1)["success"] is False
    assert compact_sqlite_database(path, dry_run=False, timeout_seconds=0)["success"] is False


def test_compaction_requires_offline_confirmation(tmp_path):
    path = tmp_path / "code-index.sqlite3"
    _make_fragmented_database(path)

    result = compact_sqlite_database(path, dry_run=False)

    assert result["success"] is False
    assert result["error"] == "offline_confirmation_required"
