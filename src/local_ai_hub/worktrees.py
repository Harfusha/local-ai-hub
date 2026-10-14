from __future__ import annotations
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from .process_utils import hidden_run_kwargs, pid_alive


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


def is_worktree_locked(
    repo_root: str | Path,
    worktree: str | Path,
    timeout: float = 5.0,
) -> tuple[bool, str]:
    """Check if worktree is locked using git worktree list --porcelain."""
    repo = Path(repo_root).resolve(strict=True)
    target = Path(worktree).resolve(strict=False)
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            **hidden_run_kwargs(),
        )
        if proc.returncode != 0:
            return False, ""

        current_wt: Path | None = None
        for line in proc.stdout.splitlines():
            line_str = line.strip()
            if line_str.startswith("worktree "):
                raw_wt = line_str.removeprefix("worktree ").strip()
                try:
                    current_wt = Path(raw_wt).resolve(strict=False)
                except Exception:
                    current_wt = None
            elif current_wt == target and line_str.startswith("locked"):
                reason = line_str.removeprefix("locked").strip()
                return True, reason
        return False, ""
    except Exception:
        return False, ""


def lock_worktree(
    repo_root: str | Path,
    worktree: str | Path,
    reason: str = "",
    pid: int | None = None,
    timeout: float = 5.0,
) -> bool:
    """Lock worktree with git worktree lock, embedding owner PID in reason."""
    repo = Path(repo_root).resolve(strict=True)
    target = Path(worktree).resolve(strict=False)
    target_pid = int(pid if pid is not None else os.getpid())
    full_reason = f"pid: {target_pid}; {reason}" if reason else f"pid: {target_pid}"
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "worktree", "lock", "--reason", full_reason, str(target)],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            **hidden_run_kwargs(),
        )
        return proc.returncode == 0
    except Exception:
        return False


def unlock_worktree(
    repo_root: str | Path,
    worktree: str | Path,
    timeout: float = 5.0,
) -> bool:
    """Unlock worktree with git worktree unlock or fallback to unlinking lock file."""
    repo = Path(repo_root).resolve(strict=True)
    target = Path(worktree).resolve(strict=False)
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "worktree", "unlock", str(target)],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            **hidden_run_kwargs(),
        )
        if proc.returncode == 0:
            return True
    except Exception:
        pass

    try:
        cmn_proc = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            **hidden_run_kwargs(),
        )
        if cmn_proc.returncode == 0:
            raw_cmn = cmn_proc.stdout.strip()
            cmn_dir = Path(raw_cmn) if Path(raw_cmn).is_absolute() else (repo / raw_cmn).resolve()
            wt_name = target.name
            lock_file = cmn_dir / "worktrees" / wt_name / "locked"
            if lock_file.exists():
                lock_file.unlink(missing_ok=True)
                return True
    except Exception:
        pass
    return False


def unlock_zombie_worktrees(
    repo_root: str | Path,
    timeout: float = 5.0,
) -> list[dict[str, Any]]:
    """Scan and unlock worktrees locked by dead/crashed processes."""
    repo = Path(repo_root).resolve(strict=True)
    unlocked_list: list[dict[str, Any]] = []
    try:
        cmn_proc = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            **hidden_run_kwargs(),
        )
        if cmn_proc.returncode != 0:
            return []
        raw_cmn = cmn_proc.stdout.strip()
        cmn_dir = Path(raw_cmn) if Path(raw_cmn).is_absolute() else (repo / raw_cmn).resolve()
        worktrees_dir = cmn_dir / "worktrees"
        if not worktrees_dir.is_dir():
            return []

        for wt_folder in worktrees_dir.iterdir():
            if not wt_folder.is_dir():
                continue
            lock_file = wt_folder / "locked"
            if not lock_file.is_file():
                continue

            try:
                content = lock_file.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                continue

            pid_match = re.search(r"\bpid[:=\s]+(\d+)\b", content, re.IGNORECASE)
            if pid_match:
                try:
                    owner_pid = int(pid_match.group(1))
                except ValueError:
                    continue

                if not pid_alive(owner_pid):
                    if unlock_worktree(repo, wt_folder.name, timeout=timeout):
                        unlocked_list.append({
                            "worktree": wt_folder.name,
                            "pid": owner_pid,
                            "reason": content,
                            "status": "unlocked",
                        })
    except Exception:
        pass
    return unlocked_list

