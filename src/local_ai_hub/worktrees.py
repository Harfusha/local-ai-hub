from __future__ import annotations

import subprocess
import time
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


def is_hub_temporary_worktree(path: str | Path) -> bool:
    """Accept only a direct, non-symlink lah_wt_* child of the system temp root."""
    import tempfile

    candidate = Path(path).expanduser()
    if candidate.is_symlink() or not candidate.name.startswith("lah_wt_"):
        return False
    try:
        resolved = candidate.resolve(strict=True)
        temp_root = Path(tempfile.gettempdir()).resolve(strict=True)
        return resolved.parent == temp_root and resolved.is_dir()
    except (OSError, RuntimeError):
        return False


def worktree_is_clean_ancestor(
    repo_root: str | Path,
    worktree_path: str | Path,
    base_commit: str,
    timeout_seconds: float = 5.0,
    deadline_monotonic: float | None = None,
) -> tuple[bool, str]:
    """Prove a clean checkout and its creation base are already in repo HEAD."""
    repo = Path(repo_root).resolve(strict=False)
    checkout = Path(worktree_path).resolve(strict=False)

    def git(path: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
        try:
            timeout = max(0.5, min(float(timeout_seconds), 8.0))
            if deadline_monotonic is not None:
                remaining = deadline_monotonic - time.monotonic()
                if remaining <= 0:
                    return None
                timeout = min(timeout, remaining)
            return subprocess.run(
                ["git", "-C", str(path), *args], stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                timeout=timeout, check=False,
                **hidden_run_kwargs(),
            )
        except (OSError, subprocess.SubprocessError, ValueError):
            return None

    status = git(checkout, "status", "--porcelain", "--untracked-files=all", "--ignored")
    if status is None or status.returncode != 0 or status.stdout.strip():
        return False, "worktree is dirty or status is unavailable"
    root_head = git(repo, "rev-parse", "--verify", "HEAD^{commit}")
    wt_head = git(checkout, "rev-parse", "--verify", "HEAD^{commit}")
    base = git(repo, "rev-parse", "--verify", f"{base_commit}^{{commit}}")
    if any(result is None or result.returncode != 0 for result in (root_head, wt_head, base)):
        return False, "worktree ancestry metadata is unavailable"
    assert root_head is not None and wt_head is not None and base is not None
    for ancestor in (wt_head.stdout.strip(), base.stdout.strip()):
        proof = git(repo, "merge-base", "--is-ancestor", ancestor, root_head.stdout.strip())
        if proof is None or proof.returncode != 0:
            return False, "worktree contains commits outside the approved repository history"
    return True, ""
