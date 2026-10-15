"""Deferred archive-policy checks; no checkout migration or reindex."""

import sqlite3
from contextlib import closing

import pytest

from local_ai_hub.code_index import _root_archive_path_sql
from local_ai_hub.repo_tools import is_root_archive_path


@pytest.mark.parametrize("path", [
    "docs/integration/archive/t13-opmode-resume-test_operational_mode.py.txt",
    "docs/integration/archive/old_module.py",
    "docs\\integration\\archive\\old_module.cs.txt",
])
def test_historical_source_copies_are_not_current_index_candidates(path):
    assert is_root_archive_path(path) is True


@pytest.mark.parametrize("path", [
    "src/local_ai_hub/operational_mode.py", "docs/integration/current/module.py",
    "docs/integration/archive/README.md", "docs/archive_history.md",
])
def test_current_source_and_archived_prose_remain_available(path):
    assert is_root_archive_path(path) is False


def test_legacy_index_rows_are_filtered_before_limit():
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.create_function("hub_root_archive_path", 1, is_root_archive_path, deterministic=True)
        connection.execute("CREATE TABLE symbols(path TEXT)")
        connection.executemany("INSERT INTO symbols VALUES(?)", [
            ("docs/integration/archive/a.py.txt",),
            ("src/current.py",),
        ])
        rows = connection.execute(
            "SELECT path FROM symbols WHERE " + _root_archive_path_sql() + " ORDER BY path LIMIT 1"
        ).fetchall()
    assert rows == [("src/current.py",)]
