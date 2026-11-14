from __future__ import annotations

from local_ai_hub.batch_replace_dirty_hunks import parse_dirty_hunks


def test_parse_dirty_hunks_returns_current_file_line_ranges() -> None:
    diff = (
        b"diff --git a/app.py b/app.py\n"
        b"@@ -2,2 +4,3 @@\n"
        b"@@ -10 +15 @@\n"
    )

    assert parse_dirty_hunks(diff) == [(4, 6), (15, 15)]


def test_parse_dirty_hunks_fails_closed_for_missing_or_malformed_hunks() -> None:
    full_file = [(1, 2**31 - 1)]

    assert parse_dirty_hunks(b"diff --git a/app.py b/app.py\n") == full_file
    assert parse_dirty_hunks(b"@@ -1 +bad @@\n") == full_file
