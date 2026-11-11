from __future__ import annotations
import math
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
    for line in str(payload or "").splitlines():
        if line.startswith("worktree "):
            root = line.removeprefix("worktree ").replace("\x00", "").strip()
            if root:
                roots.append(root)
    return roots


def discover_worktree_roots(root: str | Path, timeout_seconds: float = 5.0) -> list[str]:
    """Discover existing sibling worktrees without reading repository content."""
    if not isinstance(root, (str, Path)) or isinstance(root, bool) or not str(root).strip() or "\x00" in str(root):
        return []
    timeout = 5.0 if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not math.isfinite(timeout_seconds) else timeout_seconds
    try:
        root_path = Path(root)
        if not root_path.is_dir():
            return []
    except (TypeError, ValueError, OSError):
        return []
    try:
        result = subprocess.run(
            ["git", "-C", str(root_path), "worktree", "list", "--porcelain"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=max(0.5, float(timeout)),
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

    if not isinstance(path, (str, Path)):
        return False
    clean_path = str(path).replace("\x00", "").strip()
    if not clean_path or "\x00" in str(path):
        return False
    try:
        candidate = Path(clean_path).expanduser()
        if candidate.is_symlink() or not candidate.name.startswith("lah_wt_"):
            return False
        resolved = candidate.resolve(strict=True)
        temp_root = Path(tempfile.gettempdir()).resolve(strict=True)
        is_same_temp = False
        try:
            is_same_temp = resolved.parent.samefile(temp_root)
        except OSError:
            is_same_temp = resolved.parent == temp_root
        return is_same_temp and resolved.is_dir()
    except (OSError, RuntimeError, ValueError):
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
    if not repo.is_dir():
        return False, "repository root is not a directory"
    if not checkout.is_dir():
        return False, "worktree path is not a directory"
    clean_base = str(base_commit or "").strip()
    if not clean_base:
        return False, "base_commit must be a non-empty commit hash"

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
    base = git(repo, "rev-parse", "--verify", f"{clean_base}^{{commit}}")
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
) -> tuple[bool | None, str]:
    """Check if worktree is locked using git worktree list --porcelain."""
    try:
        repo = Path(repo_root).resolve(strict=True)
        target = Path(worktree).resolve(strict=False)
        proc = subprocess.run(
            ["git", "-C", str(repo), "worktree", "list", "--porcelain"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            **hidden_run_kwargs(),
        )
        if proc.returncode != 0:
            return None, "worktree lock status unavailable"

        current_wt: Path | None = None
        found_target = False
        for line in proc.stdout.splitlines():
            line_str = line.strip()
            if line_str.startswith("worktree "):
                raw_wt = line_str.removeprefix("worktree ").strip()
                try:
                    current_wt = Path(raw_wt).resolve(strict=False)
                except (OSError, RuntimeError, ValueError):
                    current_wt = None
                    continue
                if current_wt == target:
                    found_target = True
            elif current_wt == target and line_str.startswith("locked"):
                reason = line_str.removeprefix("locked").strip()
                return True, reason
        if not found_target:
            return None, "worktree lock status unavailable"
        return False, ""
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
        return None, "worktree lock status unavailable"

def check_worktree_uncommitted_changes(
    worktree_path: str | Path,
    *,
    force: bool = False,
    timeout_seconds: float = 5.0,
) -> tuple[bool, str]:
    """Check if worktree has uncommitted changes before branch switch or removal.

    Returns (is_allowed, error_code).
    """
    if force:
        return True, ""
    try:
        target = Path(worktree_path).resolve(strict=False)
        if not target.is_dir():
            return False, "worktree_not_found"
        proc = subprocess.run(
            ["git", "-C", str(target), "status", "--porcelain", "--untracked-files=all"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=max(0.5, float(timeout_seconds)),
            check=False,
            **hidden_run_kwargs(),
        )
        if proc.returncode != 0:
            return False, "status_failed"

        output = proc.stdout.strip()
        if output:
            return False, "uncommitted_changes_in_worktree"
        return True, ""
    except Exception:
        return False, "status_failed"


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


def _worktree_git_metadata(
    repo: Path, target: Path, timeout: float
) -> tuple[Path, Path] | None:
    """Return common and per-worktree Git dirs only when their backlinks agree."""
    def git_value(cwd: Path, *args: str) -> str | None:
        result = subprocess.run(
            ["git", "-C", str(cwd), *args],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            **hidden_run_kwargs(),
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip()

    def resolve_git_path(cwd: Path, raw: str) -> Path:
        value = Path(raw)
        return value.resolve(strict=True) if value.is_absolute() else (cwd / value).resolve(strict=True)

    repo_common_text = git_value(repo, "rev-parse", "--git-common-dir")
    target_common_text = git_value(target, "rev-parse", "--git-common-dir")
    git_dir_text = git_value(target, "rev-parse", "--absolute-git-dir")
    if not repo_common_text or not target_common_text or not git_dir_text:
        return None

    repo_common = resolve_git_path(repo, repo_common_text)
    target_common = resolve_git_path(target, target_common_text)
    git_dir = Path(git_dir_text).resolve(strict=True)
    if repo_common != target_common:
        return None

    worktrees_root = (repo_common / "worktrees").resolve(strict=True)
    if git_dir.parent != worktrees_root:
        return None
    gitdir_file = git_dir / "gitdir"
    commondir_file = git_dir / "commondir"
    target_marker = target / ".git"
    if any(path.is_symlink() for path in (gitdir_file, commondir_file, target_marker)):
        return None
    if not gitdir_file.is_file() or not commondir_file.is_file() or not target_marker.is_file():
        return None

    recorded_gitdir = Path(gitdir_file.read_text(encoding="utf-8").strip())
    if not recorded_gitdir.is_absolute():
        recorded_gitdir = git_dir / recorded_gitdir
    if recorded_gitdir.resolve(strict=True) != target_marker.resolve(strict=True):
        return None

    recorded_common = Path(commondir_file.read_text(encoding="utf-8").strip())
    if not recorded_common.is_absolute():
        recorded_common = git_dir / recorded_common
    if recorded_common.resolve(strict=True) != repo_common:
        return None
    return repo_common, git_dir


def unlock_worktree(
    repo_root: str | Path,
    worktree: str | Path,
    timeout: float = 5.0,
) -> bool:
    """Unlock a registered worktree, verifying its Git metadata on fallback."""
    try:
        repo = Path(repo_root).resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return False
    target_str = str(worktree).strip()
    if not target_str or "\x00" in target_str:
        return False
    candidate = Path(target_str).expanduser()
    target = (candidate if candidate.is_absolute() else repo / candidate).resolve(
        strict=False
    )
    if not target.is_dir():
        return False

    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "worktree", "unlock", str(target)],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            **hidden_run_kwargs(),
        )
        if proc.returncode == 0:
            return True
    except (OSError, subprocess.SubprocessError, ValueError):
        pass

    try:
        is_locked, _ = is_worktree_locked(repo, target, timeout=timeout)
        if is_locked is not True:
            return False
        metadata = _worktree_git_metadata(repo, target, timeout)
        if metadata is None:
            return False
        _, git_dir = metadata
        lock_file = git_dir / "locked"
        if lock_file.is_symlink():
            return False
        if not lock_file.is_file():
            return False
        lock_file.unlink()
        return True
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
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
                    gitdir_file = wt_folder / "gitdir"
                    if gitdir_file.is_symlink() or not gitdir_file.is_file():
                        continue
                    raw_gitdir = gitdir_file.read_text(encoding="utf-8").strip()
                    gitdir_marker = Path(raw_gitdir)
                    if not gitdir_marker.is_absolute() or gitdir_marker.name != ".git":
                        continue
                    worktree_path = gitdir_marker.resolve(strict=True).parent
                    metadata = _worktree_git_metadata(repo, worktree_path, timeout)
                    if metadata is None or metadata[1] != wt_folder.resolve(strict=True):
                        continue
                    if unlock_worktree(repo, worktree_path, timeout=timeout):
                        unlocked_list.append({
                            "worktree": worktree_path.name,
                            "pid": owner_pid,
                            "reason": content,
                            "status": "unlocked",
                        })
    except Exception:
        pass
    return unlocked_list


def switch_worktree_branch(
    worktree_path: str | Path,
    target_branch: str,
    *,
    force: bool = False,
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    """Switch worktree branch, aborting if uncommitted changes exist unless force=True."""
    allowed, error = check_worktree_uncommitted_changes(worktree_path, force=force, timeout_seconds=timeout_seconds)
    if not allowed:
        return {"success": False, "error": error}
    try:
        cmd = ["git", "-C", str(worktree_path), "switch"]
        if force:
            cmd.append("--discard-changes")
        cmd.append(str(target_branch))
        proc = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=max(0.5, float(timeout_seconds)),
            check=False,
            **hidden_run_kwargs(),
        )
        if proc.returncode != 0:
            checkout_cmd = ["git", "-C", str(worktree_path), "checkout"]
            if force:
                checkout_cmd.append("-f")
            checkout_cmd.append(str(target_branch))
            proc = subprocess.run(
                checkout_cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=max(0.5, float(timeout_seconds)),
                check=False,
                **hidden_run_kwargs(),
            )
        if proc.returncode != 0:
            return {"success": False, "error": proc.stderr.strip() or "git switch failed"}
        return {"success": True, "branch": target_branch}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def remove_worktree_safe(
    repo_root: str | Path,
    worktree_path: str | Path,
    *,
    force: bool = False,
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    """Remove worktree, aborting if uncommitted changes exist unless force=True."""
    allowed, error = check_worktree_uncommitted_changes(worktree_path, force=force, timeout_seconds=timeout_seconds)
    if not allowed:
        return {"success": False, "error": error}
    try:
        cmd = ["git", "-C", str(repo_root), "worktree", "remove"]
        if force:
            cmd.append("--force")
        cmd.append(str(worktree_path))
        proc = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=max(0.5, float(timeout_seconds)),
            check=False,
            **hidden_run_kwargs(),
        )
        if proc.returncode != 0:
            return {"success": False, "error": proc.stderr.strip() or "git worktree remove failed"}
        return {"success": True, "removed": str(worktree_path)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def is_git_worktree(path: str | Path) -> bool:
    """Check if the directory is a git worktree or git repository."""
    if not isinstance(path, (str, Path)) or isinstance(path, bool) or not str(path).strip() or "\x00" in str(path):
        return False
    try:
        target = Path(path).resolve(strict=False)
        if not target.is_dir():
            return False
        git_entry = target / ".git"
        if git_entry.is_file():
            content = git_entry.read_text(encoding="utf-8", errors="replace").strip()
            return content.startswith("gitdir:")
        if git_entry.is_dir():
            return True
        return False
    except (OSError, RuntimeError, ValueError):
        return False


def get_worktree_status(
    worktree_path: str | Path,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    """Inspect status of a worktree (exists, branch, dirty files, locked)."""
    if not isinstance(worktree_path, (str, Path)) or "\x00" in str(worktree_path):
        return {
            "exists": False,
            "clean": False,
            "uncommitted_files": [],
            "branch": None,
            "locked": None,
            "lock_status": "unknown",
            "lock_reason": "worktree path unavailable",
        }
    try:
        target = Path(worktree_path).resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return {
            "exists": False,
            "clean": False,
            "uncommitted_files": [],
            "branch": None,
            "locked": None,
            "lock_status": "unknown",
            "lock_reason": "worktree path unavailable",
        }
    if not target.is_dir():
        return {
            "exists": False,
            "clean": False,
            "uncommitted_files": [],
            "branch": None,
            "locked": None,
            "lock_status": "unknown",
            "lock_reason": "worktree path unavailable",
        }

    branch: str | None = None
    try:
        proc_br = subprocess.run(
            ["git", "-C", str(target), "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=max(0.5, float(timeout_seconds)),
            check=False,
            **hidden_run_kwargs(),
        )
        if proc_br.returncode == 0 and proc_br.stdout.strip():
            branch = proc_br.stdout.strip()
    except Exception:
        pass

    uncommitted_files: list[str] = []
    clean = False
    try:
        proc_st = subprocess.run(
            ["git", "-C", str(target), "status", "--porcelain", "--untracked-files=all"],
            capture_output=True,
            text=True,
            timeout=max(0.5, float(timeout_seconds)),
            check=False,
            **hidden_run_kwargs(),
        )
        if proc_st.returncode == 0:
            lines = [line.strip() for line in proc_st.stdout.splitlines() if line.strip()]
            uncommitted_files = lines
            clean = len(lines) == 0
    except Exception:
        pass

    locked, lock_reason = is_worktree_locked(
        target, target, timeout=max(0.5, float(timeout_seconds))
    )
    lock_status = "unknown" if locked is None else "locked" if locked else "unlocked"

    return {
        "exists": True,
        "clean": clean,
        "uncommitted_files": uncommitted_files,
        "branch": branch,
        "locked": locked,
        "lock_status": lock_status,
        "lock_reason": lock_reason,
    }


def is_valid_worktree_name(name: Any) -> bool:
    """Return True if worktree name or branch identifier is safe and valid."""
    if not isinstance(name, str) or isinstance(name, bool):
        return False
    clean = name.strip()
    if not clean or "\x00" in clean or len(clean) > 200:
        return False
    if clean.startswith("-") or clean.startswith("/") or clean.startswith("\\"):
        return False
    if ".." in clean or clean.endswith(("/", "\\", ".")):
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9_./-]+", clean))


def active_worktree_count(repo_root: str | Path, timeout_seconds: float = 5.0) -> int:
    """Return count of active sibling worktrees for repository."""
    try:
        roots = discover_worktree_roots(repo_root, timeout_seconds=timeout_seconds)
        return len(roots)
    except Exception:
        return 0


