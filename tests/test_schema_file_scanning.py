from __future__ import annotations

import time
from pathlib import Path

import pytest

from local_ai_hub.schema_file_scanning import scan_schema_files


def test_scan_schema_files_skips_excluded_trees_and_filters_migrations(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "src" / "db").mkdir(parents=True)
    (root / "src" / "migrations").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / ".hidden").mkdir()
    (root / "node_modules").mkdir()
    (root / "src" / "db" / "schema.sql").write_text("CREATE TABLE app;")
    (root / "src" / "migrations" / "001.sql").write_text("ALTER TABLE app;")
    (root / "tests" / "test_schema.sql").write_text("ignored")
    (root / ".hidden" / "hidden.sql").write_text("ignored")
    (root / "node_modules" / "vendor.sql").write_text("ignored")

    all_files = scan_schema_files(
        root,
        suffix=".sql",
        deadline=time.monotonic() + 10,
        migrations_only=False,
        max_dirs=20,
        max_entries=100,
        max_files=20,
    )
    migration_files = scan_schema_files(
        root,
        suffix=".sql",
        deadline=time.monotonic() + 10,
        migrations_only=True,
        max_dirs=20,
        max_entries=100,
        max_files=20,
    )

    assert all_files == sorted([root / "src" / "db" / "schema.sql", root / "src" / "migrations" / "001.sql"])
    assert migration_files == [root / "src" / "migrations" / "001.sql"]


def test_scan_schema_files_enforces_candidate_limit(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "one.sql").write_text("one")
    (root / "two.sql").write_text("two")

    with pytest.raises(TimeoutError, match="schema scan exceeded 1 files"):
        scan_schema_files(
            root,
            suffix=".sql",
            deadline=time.monotonic() + 10,
            migrations_only=False,
            max_dirs=20,
            max_entries=100,
            max_files=1,
        )
