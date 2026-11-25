"""Read-only checkout synchronization diagnostics for Git-owned project state.

Do not fetch, merge, commit, stash, or report a remote as current. A Git status
is an observation of one checkout, not authorization or verified project truth.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .process_utils import clean_git_env, hidden_run_kwargs
from .repo_plan.storage import get_git_context

_PATHS = (
    ".local-ai-hub/project.json", ".local-ai-hub/knowledge",
    ".local-ai-hub/agent-os", ".local-ai-hub/plans",
    ".local-ai-hub/specs", ".local-ai-hub/decisions", ".local-ai.toml",
    ".local-ai-hub/.gitignore",
)
_MAX_OUTPUT = 256 * 1024
_MAX_ENTRIES = 256


def _git(root: Path, *args: str) -> bytes | None:
    """Use Git without refreshing the index or running fsmonitor hooks."""
    try:
        result = subprocess.run(
            ["git", "--no-optional-locks", "-c", "core.fsmonitor=false",
             "-C", str(root), *args],
            capture_output=True, timeout=5,
            env=clean_git_env(), **hidden_run_kwargs(),
        )
        if result.returncode or len(result.stdout) > _MAX_OUTPUT:
            return None
        return result.stdout
    except (OSError, subprocess.SubprocessError):
        return None


def checkout_sync_status(root: Path) -> dict[str, Any]:
    """Report shared-state Git changes; never expose local journal contents."""
    if not (root / ".git").exists():
        return {"state": "not_git_checkout", "complete": False}
    branch, head = get_git_context(root)
    raw = _git(root, "status", "--porcelain=v1", "-z", "--no-renames",
               "--untracked-files=all", "--ignored=matching", "--", *_PATHS)
    local_tracked = _git(root, "ls-files", "-z", "--", ".local-ai-hub/local")
    if raw is None or local_tracked is None:
        return {"state": "unavailable", "complete": False}
    entries: list[dict[str, str]] = []
    complete = True
    for field in raw.split(b"\0"):
        if not field:
            continue
        if len(field) < 4 or field[2:3] != b" ":
            complete = False
            continue
        if len(entries) == _MAX_ENTRIES:
            complete = False
            break
        try:
            code = field[:2].decode("ascii")
            path = field[3:].decode("utf-8")
        except UnicodeError:
            complete = False
            continue
        if any(not char.isprintable() for char in path) or not any(
            path == prefix or path.startswith(prefix + "/") for prefix in _PATHS
        ):
            complete = False
            continue
        kind = (
            "conflict" if code in {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}
            else "untracked" if code == "??"
            else "ignored" if code == "!!"
            else "modified"
        )
        entries.append({"path": path, "index_worktree_status": code, "state": kind})
    upstream = _git(root, "rev-list", "--left-right", "--count", "HEAD...@{upstream}")
    divergence: dict[str, Any] = {"status": "unknown_or_no_upstream"}
    if upstream is not None:
        parts = upstream.split()
        if len(parts) == 2 and all(part.isdigit() for part in parts):
            divergence = {"status": "local_tracking_ref_only", "ahead": int(parts[0]), "behind": int(parts[1])}
    if get_git_context(root) != (branch, head):
        return {"state": "changed_during_read", "complete": False}
    # Ignored shareable files cannot silently count as synchronized.
    state = (
        "conflict" if any(item["state"] == "conflict" for item in entries)
        else "unsafe_local_tracking" if local_tracked
        else "partial" if not complete
        else "local_changes" if entries
        else "clean_shared_paths"
    )
    return {
        "state": state, "complete": complete, "branch": branch, "head": head,
        "entries": entries, "tracked_local_state": bool(local_tracked),
        "divergence": divergence, "remote_verified": False,
    }
