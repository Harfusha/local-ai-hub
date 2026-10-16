from __future__ import annotations

import math
from pathlib import Path
import pytest

from local_ai_hub.work_orchestrator import (
    _bounded_int,
    _safe_work_target,
    is_terminal_work_status,
    is_valid_work_order_id,
    WorkOrchestrator,
)
from local_ai_hub.worktrees import (
    active_worktree_count,
    get_worktree_status,
    is_git_worktree,
    is_hub_temporary_worktree,
    is_valid_worktree_name,
    parse_worktree_porcelain,
)


def test_work_orchestrator_bounded_int_and_safe_target(tmp_path: Path) -> None:
    # _bounded_int must not coerce bool to int
    assert _bounded_int(True, default=10, minimum=1, maximum=20) == 10
    assert _bounded_int(False, default=10, minimum=1, maximum=20) == 10
    assert _bounded_int(float("nan"), default=10, minimum=1, maximum=20) == 10

    # _safe_work_target must reject null bytes and non-str
    with pytest.raises(ValueError, match="unsafe"):
        _safe_work_target(tmp_path, "file\x00.py")

    with pytest.raises(ValueError, match="unsafe"):
        _safe_work_target(tmp_path, None)  # type: ignore[arg-type]


def test_work_orchestrator_helpers() -> None:
    # is_valid_work_order_id
    assert is_valid_work_order_id("work_1234abcd") is True
    assert is_valid_work_order_id("order-xyz") is True
    assert is_valid_work_order_id("") is False
    assert is_valid_work_order_id(None) is False
    assert is_valid_work_order_id("work\x00bad") is False
    assert is_valid_work_order_id("work/../escape") is False

    # is_terminal_work_status
    assert is_terminal_work_status("complete") is True
    assert is_terminal_work_status("failed") is True
    assert is_terminal_work_status("cancelled") is True
    assert is_terminal_work_status("needs_agent") is True
    assert is_terminal_work_status("partial") is True
    assert is_terminal_work_status("running") is False
    assert is_terminal_work_status("pending") is False
    assert is_terminal_work_status(None) is False
    assert is_terminal_work_status(123) is False


def test_work_orchestrator_init_and_inspection_helpers(tmp_path: Path) -> None:
    orchestrator = WorkOrchestrator(
        config=None,  # type: ignore[arg-type]
        state_dir=tmp_path,
        services=None,
        commands=None,
        leases=None,
        artifacts=None,
    )
    assert orchestrator.is_enabled() is True
    assert orchestrator.max_active_orders() >= 1
    assert orchestrator.default_timeout_seconds() >= 30


def test_worktrees_null_bytes_and_safe_checks(tmp_path: Path) -> None:
    # parse_worktree_porcelain strips null bytes
    raw_porcelain = f"worktree {tmp_path.as_posix()}\x00\nHEAD 1234\nbranch refs/heads/main\n"
    roots = parse_worktree_porcelain(raw_porcelain)
    assert len(roots) == 1
    assert "\x00" not in roots[0]

    # is_hub_temporary_worktree handles null bytes and invalid types safely
    assert is_hub_temporary_worktree(f"{tmp_path.as_posix()}\x00") is False
    assert is_hub_temporary_worktree(None) is False  # type: ignore[arg-type]
    assert is_hub_temporary_worktree(123) is False  # type: ignore[arg-type]

    # is_git_worktree handles null bytes and non-existent paths safely
    assert is_git_worktree(f"{tmp_path.as_posix()}\x00") is False
    assert is_git_worktree(None) is False  # type: ignore[arg-type]

    # get_worktree_status handles null bytes safely
    st = get_worktree_status(f"{tmp_path.as_posix()}\x00")
    assert st["exists"] is False

    # is_valid_worktree_name
    assert is_valid_worktree_name("feature-wave11") is True
    assert is_valid_worktree_name("lah-wt-task-154") is True
    assert is_valid_worktree_name("") is False
    assert is_valid_worktree_name(None) is False
    assert is_valid_worktree_name("wt\x00invalid") is False
    assert is_valid_worktree_name("../escape") is False
    assert is_valid_worktree_name("/absolute") is False
    assert is_valid_worktree_name("-leadingdash") is False

    # active_worktree_count
    count = active_worktree_count(tmp_path)
    assert count == 0
