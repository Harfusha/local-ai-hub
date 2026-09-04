from __future__ import annotations

from local_ai_hub.worktrees import parse_worktree_porcelain


def test_parse_worktree_porcelain_keeps_each_declared_root():
    payload = """worktree C:/repo/main
HEAD abc123
branch refs/heads/main

worktree C:/repo/worktrees/feature
HEAD def456
branch refs/heads/feature
"""

    assert parse_worktree_porcelain(payload) == ["C:/repo/main", "C:/repo/worktrees/feature"]
