from __future__ import annotations

import time
from pathlib import Path

import pytest

from local_ai_hub.git_history_search import (
    _merge_history_output,
    _prepare_history_filters,
    search_git_history,
)


def test_search_git_history_rejects_control_characters_before_launch(tmp_path: Path) -> None:
    result = search_git_history(
        str(tmp_path),
        "needle\n--all",
        root_resolver=lambda root: str(Path(root).resolve()),
        git_executable_fn=lambda _name: "git",
        run_hidden_fn=lambda *_args, **_kwargs: pytest.fail("Git must not run for a malformed query"),
        clean_git_env_fn=lambda **_kwargs: {},
    )

    assert result["success"] is False
    assert result["status_code"] == 400
    assert result["error"] == "query must be a bounded literal string"


def test_merge_history_output_keeps_valid_rows_and_marks_partial_trailing_data() -> None:
    commit = b"c" * 40
    raw_output = (
        commit
        + b"\0Ada\0"
        + b"2026-01-10T12:00:00+00:00\0needle subject\0\n"
        + b"broken\0"
    )
    commits = {}

    incomplete, field_count = _merge_history_output(
        raw_output,
        "message",
        commits,
        deadline=time.monotonic() + 5,
        since_epoch=None,
        until_epoch=None,
    )

    assert "message_malformed_output" in incomplete
    assert field_count == 5
    assert list(commits) == [commit.decode("ascii")]
    assert commits[commit.decode("ascii")]["subject"] == "needle subject"


def test_prepare_history_filters_normalizes_dates_and_repository_path(tmp_path: Path) -> None:
    filters, error = _prepare_history_filters(
        str(tmp_path),
        "  needle  ",
        5,
        author=" Ada ",
        since="2026-01-01",
        until="2026-01-31",
        path="src\\a.py",
    )

    assert error is None
    assert filters is not None
    assert filters.clean_query == "needle"
    assert filters.clean_author == "Ada"
    assert filters.pathspec == "src/a.py"
    assert filters.since_normalized == "2026-01-01T00:00:00Z"
    assert filters.until_normalized == "2026-01-31T23:59:59.999999Z"
