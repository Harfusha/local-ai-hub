from __future__ import annotations

import subprocess
from pathlib import Path

from .process_utils import hidden_run_kwargs


def parse_worktree_porcelain(payload: str) -> list[str]:
    """Return worktree roots from ``git worktree list --porcelain`` output."""
    roots: list[str] = []
    for line in str(payload).splitlines():
        if line.startswith("worktree "):
            root = line.removeprefix("worktree ").strip()
            if root:
                roots.append(root)
    return roots


def discover_worktree_roots(root: str, timeout_seconds: float = 5.0) -> list[str]:
    """Discover existing sibling worktrees without reading repository content."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "worktree", "list", "--porcelain"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=max(0.5, float(timeout_seconds)),
            check=False,
            **hidden_run_kwargs(),
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    roots: list[str] = []
    seen: set[str] = set()
    for raw in parse_worktree_porcelain(result.stdout):
        try:
            resolved = str(Path(raw).expanduser().resolve())
        except OSError:
            continue
        if resolved not in seen and Path(resolved).is_dir():
            seen.add(resolved)
            roots.append(resolved)
    return roots
