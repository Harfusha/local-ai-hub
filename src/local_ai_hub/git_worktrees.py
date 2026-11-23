# Git worktree lifecycle and branch operations extracted from process_utils.py
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from typing import Any
import uuid

from . import process_utils


def _deadline_timeout(*args: Any, **kwargs: Any) -> Any:
    return process_utils._deadline_timeout(*args, **kwargs)


def _run_hidden_with_deadline(*args: Any, **kwargs: Any) -> Any:
    return process_utils._run_hidden_with_deadline(*args, **kwargs)


def hidden_run_kwargs(*args: Any, **kwargs: Any) -> Any:
    return process_utils.hidden_run_kwargs(*args, **kwargs)


def process_identity(*args: Any, **kwargs: Any) -> Any:
    return process_utils.process_identity(*args, **kwargs)


def run_hidden(*args: Any, **kwargs: Any) -> Any:
    return process_utils.run_hidden(*args, **kwargs)

_WORKTREE_OWNERSHIP_FILE = "local-ai-hub-worktree-ownership.json"

def _git_worktree_admin_dir(
    repo: Path, target: Path, *, deadline_monotonic: float | None = None
) -> Path | None:
    common_timeout = _deadline_timeout(10, deadline_monotonic)
    if common_timeout is None:
        return None
    common_proc = run_hidden(
        ["git", "-C", str(repo), "rev-parse", "--git-common-dir"],
        capture_output=True,
        text=True,
        check=False,
        timeout=common_timeout,
        **hidden_run_kwargs(),
    )
    admin_timeout = _deadline_timeout(10, deadline_monotonic)
    if admin_timeout is None:
        return None
    admin_proc = run_hidden(
        ["git", "-C", str(target), "rev-parse", "--git-dir"],
        capture_output=True,
        text=True,
        check=False,
        timeout=admin_timeout,
        **hidden_run_kwargs(),
    )
    if common_proc.returncode != 0 or admin_proc.returncode != 0:
        return None
    common = Path(common_proc.stdout.strip())
    admin = Path(admin_proc.stdout.strip())
    if not common.is_absolute():
        common = repo / common
    if not admin.is_absolute():
        admin = target / admin
    common = common.resolve(strict=False)
    admin = admin.resolve(strict=False)
    try:
        admin.relative_to(common / "worktrees")
    except ValueError:
        return None
    return admin


def get_git_worktree_ownership(
    repo_root: str | Path, worktree_path: str | Path, *, deadline_monotonic: float | None = None
) -> dict[str, Any] | None:
    """Read ownership metadata stored outside a linked worktree's working files."""
    repo = Path(repo_root).expanduser().resolve(strict=False)
    target = Path(worktree_path).expanduser().resolve(strict=False)
    admin = _git_worktree_admin_dir(repo, target, deadline_monotonic=deadline_monotonic)
    if admin is None:
        return None
    marker = admin / _WORKTREE_OWNERSHIP_FILE
    if not marker.exists():
        fallback = admin / "local_ai_hub_worktree.json"
        if fallback.exists():
            marker = fallback
    try:
        import json

        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


@dataclass(frozen=True)
class PreparedGitWorktree:
    """Read-only reservation consumed by create_git_worktree after response preflight."""

    repo_root: str
    base_commit_ref: str
    base_commit_sha: str
    branch: str
    worktree_path: str
    lease_id: str
    worktree_id: str
    task_id: str
    owner: str
    created_at: float
    ttl_seconds: float
    expires_at: float | None
    creator_pid: int | None
    creator_creation_identity: int | str | None
    creator_creation_identity_type: str | None
    creator_executable: str | None

    def response_metadata(self) -> dict[str, Any]:
        return {
            "success": True, "lease_id": self.lease_id, "worktree_id": self.worktree_id,
            "worktree_path": self.worktree_path, "branch": self.branch,
            "base_commit": self.base_commit_sha, "repo_root": self.repo_root,
            "task_id": self.task_id, "owner": self.owner, "created_at": self.created_at,
            "ttl_seconds": self.ttl_seconds, "expires_at": self.expires_at,
            "creator_pid": self.creator_pid,
            "creator_creation_identity": self.creator_creation_identity,
            "creator_creation_identity_type": self.creator_creation_identity_type,
            "creator_executable": self.creator_executable,
        }


def prepare_git_worktree(
    repo_root: str | Path,
    branch_name: str | None = None,
    base_commit: str = "HEAD",
    *,
    task_id: str = "",
    owner: str = "",
    created_at: float | None = None,
    ttl_seconds: float = 86400.0,
    expires_at: float | None = None,
) -> PreparedGitWorktree:
    """Reserve exact worktree response metadata using bounded read-only probes."""

    repo = Path(repo_root).expanduser().resolve(strict=False)
    if not (repo / ".git").exists():
        raise ValueError("not a git repository")
    if not shutil.which("git"):
        raise ValueError("git executable not found in PATH")
    created = float(created_at) if created_at is not None else time.time()
    ttl = float(ttl_seconds)
    expiry = float(expires_at) if expires_at is not None else None
    if not math.isfinite(created) or not math.isfinite(ttl) or (expiry is not None and not math.isfinite(expiry)):
        raise ValueError("invalid worktree metadata: values must be finite")
    ttl = max(60.0, min(ttl, 30 * 24 * 60 * 60.0))

    lease_id = f"lease_{uuid.uuid4().hex[:12]}"
    worktree_id = f"worktree_{uuid.uuid4().hex[:12]}"
    branch = branch_name or f"lease/{lease_id}"
    target = (Path(tempfile.gettempdir()).resolve(strict=False) / f"lah_wt_{worktree_id}")
    try:
        target.relative_to(Path(tempfile.gettempdir()).resolve(strict=False))
    except ValueError as exc:
        raise ValueError("worktree path escapes the temporary root") from exc
    if target.exists() or target.is_symlink():
        raise ValueError("reserved worktree path already exists")

    base_result = run_hidden(
        ["git", "-C", str(repo), "rev-parse", "--verify", f"{base_commit}^{{commit}}"],
        capture_output=True, text=True, check=False, timeout=5, **hidden_run_kwargs(),
    )
    if base_result.returncode != 0:
        raise ValueError("worktree base commit could not be resolved")
    base_sha = base_result.stdout.strip()
    if not base_sha:
        raise ValueError("worktree base commit could not be resolved")
    creator = process_identity(os.getpid()) or {}
    required_creator_fields = (
        "pid", "creation_identity", "creation_identity_type", "executable",
    )
    if any(not creator.get(key) for key in required_creator_fields):
        raise ValueError("worktree creator identity could not be established")
    return PreparedGitWorktree(
        repo_root=str(repo), base_commit_ref=str(base_commit), base_commit_sha=base_sha,
        branch=branch, worktree_path=str(target), lease_id=lease_id, worktree_id=worktree_id,
        task_id=str(task_id), owner=str(owner), created_at=created, ttl_seconds=ttl,
        expires_at=expiry, creator_pid=creator.get("pid"),
        creator_creation_identity=creator.get("creation_identity"),
        creator_creation_identity_type=creator.get("creation_identity_type"),
        creator_executable=creator.get("executable"),
    )


def create_git_worktree(
    repo_root: str | Path,
    branch_name: str | None = None,
    worktree_path: str | Path | None = None,
    base_commit: str = "HEAD",
    *,
    task_id: str = "",
    owner: str = "",
    created_at: float | None = None,
    ttl_seconds: float = 86400.0,
    expires_at: float | None = None,
    prepared_plan: PreparedGitWorktree | None = None,
) -> dict[str, Any]:
    """Create an isolated temporary Git worktree for safe agent modifications."""
    repo = Path(repo_root).expanduser().resolve(strict=False)
    if not (repo / ".git").exists():
        return {"success": False, "error": f"not a git repository: {repo}",
                "mutation_applied": False, "operation_not_started": True,
                "outcome_unknown": False}
    if not shutil.which("git"):
        return {"success": False, "error": "git executable not found in PATH",
                "mutation_applied": False, "operation_not_started": True,
                "outcome_unknown": False}

    import tempfile
    import uuid
    try:
        created_at_value = float(created_at) if created_at is not None else time.time()
        ttl_value = float(ttl_seconds)
        expires_at_value = float(expires_at) if expires_at is not None else None
        task_id_value = str(task_id)
        owner_value = str(owner)
    except Exception as exc:
        return {"success": False, "error": f"invalid worktree metadata: {exc}",
                "mutation_applied": False, "operation_not_started": True,
                "outcome_unknown": False}
    if (
        not math.isfinite(created_at_value)
        or not math.isfinite(ttl_value)
        or (expires_at_value is not None and not math.isfinite(expires_at_value))
    ):
        return {"success": False, "error": "invalid worktree metadata: values must be finite",
                "mutation_applied": False, "operation_not_started": True,
                "outcome_unknown": False}
    ttl_value = max(60.0, min(ttl_value, 30 * 24 * 60 * 60.0))
    if prepared_plan is not None:
        if not isinstance(prepared_plan, PreparedGitWorktree):
            return {"success": False, "error": "invalid prepared worktree plan",
                    "mutation_applied": False, "operation_not_started": True,
                    "outcome_unknown": False}
        if (
            prepared_plan.repo_root != str(repo)
            or prepared_plan.base_commit_ref != str(base_commit)
            or prepared_plan.task_id != task_id_value
            or prepared_plan.owner != owner_value
            or prepared_plan.created_at != created_at_value
            or prepared_plan.ttl_seconds != ttl_value
            or prepared_plan.expires_at != expires_at_value
            or (branch_name is not None and branch_name != prepared_plan.branch)
            or (worktree_path is not None and str(Path(worktree_path).expanduser().resolve(strict=False)) != prepared_plan.worktree_path)
            or not re.fullmatch(r"lease_[0-9a-f]{12}", prepared_plan.lease_id)
            or not re.fullmatch(r"worktree_[0-9a-f]{12}", prepared_plan.worktree_id)
            or prepared_plan.worktree_path != str(Path(tempfile.gettempdir()).resolve(strict=False) / f"lah_wt_{prepared_plan.worktree_id}")
            or (branch_name is None and prepared_plan.branch != f"lease/{prepared_plan.lease_id}")
        ):
            return {"success": False, "error": "prepared worktree plan does not match create request",
                    "mutation_applied": False, "operation_not_started": True,
                    "outcome_unknown": False}
        lease_id = prepared_plan.lease_id
        worktree_id = prepared_plan.worktree_id
        branch = prepared_plan.branch
    else:
        lease_id = f"lease_{uuid.uuid4().hex[:12]}"
        worktree_id = f"worktree_{uuid.uuid4().hex[:12]}"
        branch = branch_name or f"lease/{lease_id}"
    temp_root = Path(tempfile.gettempdir()).resolve(strict=False)
    if not worktree_path:
        target_dir = temp_root / f"lah_wt_{worktree_id}"
    else:
        raw_target = Path(worktree_path).expanduser()
        if ".." in raw_target.parts:
            return {"success": False, "error": "worktree path traversal is not allowed",
                    "mutation_applied": False, "operation_not_started": True,
                    "outcome_unknown": False}
        target_dir = raw_target.resolve(strict=False)
    try:
        target_dir.relative_to(temp_root)
    except ValueError:
        return {"success": False, "error": "worktree path escapes the temporary root",
                "mutation_applied": False, "operation_not_started": True,
                "outcome_unknown": False}

    if prepared_plan is not None:
        if str(target_dir) != prepared_plan.worktree_path or target_dir.exists() or target_dir.is_symlink():
            return {"success": False, "error": "prepared worktree target changed before creation",
                    "mutation_applied": False, "operation_not_started": True,
                    "outcome_unknown": False}
        try:
            current_base = run_hidden(
                ["git", "-C", str(repo), "rev-parse", "--verify", f"{base_commit}^{{commit}}"],
                capture_output=True, text=True, check=False, timeout=5, **hidden_run_kwargs(),
            )
            current_creator = process_identity(os.getpid()) or {}
        except Exception as exc:
            return {
                "success": False,
                "error": f"prepared worktree identity could not be revalidated: {type(exc).__name__}",
                "mutation_applied": False, "operation_not_started": True,
                "outcome_unknown": False,
            }
        expected_creator = {
            "pid": prepared_plan.creator_pid,
            "creation_identity": prepared_plan.creator_creation_identity,
            "creation_identity_type": prepared_plan.creator_creation_identity_type,
            "executable": prepared_plan.creator_executable,
        }
        if (
            current_base.returncode != 0
            or current_base.stdout.strip() != prepared_plan.base_commit_sha
            or any(not value or current_creator.get(key) != value for key, value in expected_creator.items())
        ):
            return {
                "success": False, "error": "prepared worktree identity changed before creation",
                "mutation_applied": False, "operation_not_started": True,
                "outcome_unknown": False,
            }
    add_base = prepared_plan.base_commit_sha if prepared_plan is not None else base_commit
    cmd = ["git", "-C", str(repo), "worktree", "add", "-b", branch, str(target_dir), add_base]
    created_checkout = False
    try:
        completed = run_hidden(cmd, capture_output=True, text=True, check=False, timeout=30, **hidden_run_kwargs())
        if completed.returncode != 0:
            return {
                "success": False,
                "error": completed.stderr.strip() or "failed to create git worktree",
                "exit_code": completed.returncode,
                "mutation_applied": None,
                "operation_not_started": False,
                "outcome_unknown": True,
            }
        created_checkout = True
        metadata_path = _worktree_ownership_path(target_dir)
        if metadata_path is None:
            raise RuntimeError("could not locate worktree administrative directory")
        if prepared_plan is not None:
            creator = {
                "pid": prepared_plan.creator_pid,
                "creation_identity": prepared_plan.creator_creation_identity,
                "creation_identity_type": prepared_plan.creator_creation_identity_type,
                "executable": prepared_plan.creator_executable,
            }
            base_sha = prepared_plan.base_commit_sha
        else:
            base_result = run_hidden(
                ["git", "-C", str(repo), "rev-parse", "--verify", f"{base_commit}^{{commit}}"],
                capture_output=True, text=True, check=False, timeout=5,
                **hidden_run_kwargs(),
            )
            creator = process_identity(os.getpid())
            base_sha = base_result.stdout.strip() if base_result.returncode == 0 else ""
        metadata = {
            "schema_version": 1,
            "worktree_id": worktree_id,
            "task_id": task_id_value,
            "owner": owner_value,
            "repo_root": str(repo),
            "worktree_path": str(target_dir),
            "branch": branch,
            "created_at": created_at_value,
            "ttl_seconds": ttl_value,
            "expires_at": expires_at_value,
            "base_commit": base_sha,
            "creator_pid": creator.get("pid") if creator else None,
            "creator_creation_identity": creator.get("creation_identity") if creator else None,
            "creator_creation_identity_type": creator.get("creation_identity_type") if creator else None,
            "creator_executable": creator.get("executable") if creator else None,
        }
        metadata_tmp = metadata_path.with_name(f".{metadata_path.name}.{uuid.uuid4().hex}.tmp")
        metadata_tmp.write_text(json.dumps(metadata, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        os.replace(metadata_tmp, metadata_path)
        return {
            "success": True,
            "lease_id": lease_id,
            "worktree_id": worktree_id,
            "worktree_path": str(target_dir),
            "branch": branch,
            "repo_root": str(repo),
            "task_id": task_id_value,
            "owner": owner_value,
            "created_at": created_at_value,
            "ttl_seconds": ttl_value,
            "expires_at": expires_at_value,
            "base_commit": base_sha,
            "creator_pid": creator.get("pid") if creator else None,
            "creator_creation_identity": creator.get("creation_identity") if creator else None,
            "creator_creation_identity_type": creator.get("creation_identity_type") if creator else None,
            "creator_executable": creator.get("executable") if creator else None,
        }
    except Exception as exc:
        cleanup_succeeded = False
        cleanup_outcome_unknown = False
        if created_checkout:
            try:
                removed = run_hidden(
                    ["git", "-C", str(repo), "worktree", "remove", str(target_dir)],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=30,
                    **hidden_run_kwargs(),
                )
                # `worktree remove` leaves the created branch in place. Report
                # the attempted cleanup honestly; deleting a branch here could
                # erase work another actor added after worktree creation.
                cleanup_succeeded = False
                cleanup_outcome_unknown = removed.returncode != 0
            except Exception:
                cleanup_outcome_unknown = True
        return {
            "success": False,
            "error": str(exc),
            "mutation_applied": True if created_checkout else None,
            "operation_not_started": False,
            "outcome_unknown": cleanup_outcome_unknown or not created_checkout,
            "cleanup_succeeded": cleanup_succeeded if created_checkout else None,
        }


def _git_value(
    root: Path, *arguments: str, timeout: float = 15.0, deadline_monotonic: float | None = None
) -> str:
    bounded_timeout = _deadline_timeout(timeout, deadline_monotonic)
    if bounded_timeout is None:
        return ""
    try:
        result = run_hidden(
            ["git", "-C", str(root), *arguments],
            capture_output=True,
            text=True,
            check=False,
            timeout=bounded_timeout,
            **hidden_run_kwargs(),
        )
    except Exception:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _worktree_ownership_path(
    worktree_path: str | Path, *, deadline_monotonic: float | None = None
) -> Path | None:
    git_dir = _git_value(
        Path(worktree_path), "rev-parse", "--absolute-git-dir", deadline_monotonic=deadline_monotonic
    )
    if not git_dir:
        return None
    return Path(git_dir).expanduser().resolve(strict=False) / _WORKTREE_OWNERSHIP_FILE


def verify_git_worktree_cleanup_complete(
    repo_root: str | Path,
    worktree_path: str | Path,
    *,
    branch_name: str,
    delete_branch: bool,
    timeout_seconds: float = 10.0,
    deadline_monotonic: float | None = None,
) -> dict[str, Any]:
    """Reconcile a durable cleanup intent against Git's current state."""
    repo = Path(repo_root).expanduser().resolve(strict=False)
    raw_target = Path(worktree_path).expanduser()
    if raw_target.is_symlink():
        return {"success": False, "error": "worktree path must not be a symlink"}
    target = Path(os.path.abspath(raw_target))
    if target.exists() or raw_target.is_symlink():
        return {"success": False, "error": "worktree path still exists"}
    if not branch_name or any(char in branch_name for char in "\r\n\0"):
        return {"success": False, "error": "worktree branch identity is invalid"}
    timeout = max(0.5, min(float(timeout_seconds), 30.0))
    listed = _run_hidden_with_deadline(
        ["git", "-C", str(repo), "worktree", "list", "--porcelain"],
        capture_output=True, text=True, check=False, timeout=timeout,
        deadline_monotonic=deadline_monotonic, **hidden_run_kwargs(),
    )
    if listed.returncode != 0:
        return {"success": False, "error": listed.stderr.strip() or "Git worktree list failed"}
    target_key = os.path.normcase(str(target))
    registered = {
        os.path.normcase(os.path.abspath(line[len("worktree "):]))
        for line in listed.stdout.splitlines()
        if line.startswith("worktree ")
    }
    if target_key in registered:
        return {"success": False, "error": "worktree remains registered"}
    if delete_branch:
        branch_ref = f"refs/heads/{branch_name}"
        valid_ref = _run_hidden_with_deadline(
            ["git", "-C", str(repo), "check-ref-format", branch_ref],
            capture_output=True, text=True, check=False, timeout=timeout,
            deadline_monotonic=deadline_monotonic, **hidden_run_kwargs(),
        )
        if valid_ref.returncode != 0:
            return {"success": False, "error": "worktree branch identity is invalid"}
        branch = _run_hidden_with_deadline(
            ["git", "-C", str(repo), "show-ref", "--verify", "--quiet", branch_ref],
            capture_output=True, text=True, check=False, timeout=timeout,
            deadline_monotonic=deadline_monotonic, **hidden_run_kwargs(),
        )
        if branch.returncode == 0:
            return {"success": False, "error": "cleanup branch still exists"}
        if branch.returncode != 1:
            return {"success": False, "error": branch.stderr.strip() or "Git branch verification failed"}
    if raw_target.is_symlink() or target.exists():
        return {"success": False, "error": "worktree path changed during cleanup reconciliation"}
    return {"success": True, "worktree_removed": True, "branch_deleted": bool(delete_branch)}


def remove_git_worktree(
    *args: Any,
    repo_root: str | Path | None = None,
    root: str | Path | None = None,
    worktree_path: str | Path | None = None,
    delete_branch: bool = True,
    branch_name: str | None = None,
    force: bool = False,
    worktree_id: str = "",
    expected_task_id: str = "",
    expected_owner: str = "",
    expected_created_at: float | None = None,
    expected_ttl_seconds: float | None = None,
    expected_expires_at: float | None = None,
    timeout_seconds: float = 30.0,
    required_base_commit: str = "",
    deadline_monotonic: float | None = None,
) -> dict[str, Any]:
    """Remove only clean worktree whose persisted owner metadata matches caller."""
    repo_root = repo_root or root
    if len(args) >= 2:
        resolved_repo = args[0]
        resolved_target = args[1]
    elif len(args) == 1:
        if repo_root is not None:
            resolved_repo = repo_root
            resolved_target = args[0]
        else:
            resolved_repo = args[0]
            resolved_target = worktree_path
    else:
        resolved_repo = repo_root
        resolved_target = worktree_path

    if resolved_repo is None or resolved_target is None:
        return {"success": False, "error": "repository or worktree path is unavailable"}
    repo = Path(resolved_repo).expanduser().resolve(strict=False)
    timeout = max(0.5, min(float(timeout_seconds), 30.0))
    raw_target = Path(resolved_target).expanduser()
    if raw_target.is_symlink():
        return {"success": False, "error": "worktree path must not be a symlink"}
    target = raw_target.resolve(strict=False)
    if not shutil.which("git"):
        return {"success": False, "error": "git executable not found"}
    if not worktree_id.strip():
        return {"success": False, "error": "worktree ownership identifier is required"}
    try:
        temp_root = Path(tempfile.gettempdir()).resolve(strict=False)
        try:
            target.relative_to(temp_root)
        except ValueError:
            return {"success": False, "error": "worktree path escapes the temporary root"}
        if not target.is_dir() or not (repo / ".git").exists():
            return {"success": False, "error": "repository or worktree path is unavailable"}

        repo_common_raw = _git_value(repo, "rev-parse", "--git-common-dir", timeout=timeout, deadline_monotonic=deadline_monotonic)
        target_common_raw = _git_value(target, "rev-parse", "--git-common-dir", timeout=timeout, deadline_monotonic=deadline_monotonic)
        if not repo_common_raw or not target_common_raw:
            return {"success": False, "error": "repository worktree identity is unavailable"}
        repo_common = Path(repo_common_raw)
        target_common = Path(target_common_raw)
        if not repo_common.is_absolute():
            repo_common = repo / repo_common
        if not target_common.is_absolute():
            target_common = target / target_common
        if repo_common.resolve(strict=False) != target_common.resolve(strict=False):
            return {"success": False, "error": "worktree belongs to another repository"}

        top_level = _git_value(target, "rev-parse", "--show-toplevel", timeout=timeout, deadline_monotonic=deadline_monotonic)
        if not top_level or Path(top_level).resolve(strict=False) != target:
            return {"success": False, "error": "worktree path does not match checkout root"}
        listed = _git_value(repo, "worktree", "list", "--porcelain", timeout=timeout, deadline_monotonic=deadline_monotonic)
        listed_paths = {
            Path(line.removeprefix("worktree ")).resolve(strict=False)
            for line in listed.splitlines()
            if line.startswith("worktree ")
        }
        if target not in listed_paths:
            return {"success": False, "error": "checkout is not registered to this repository"}

        metadata_path = _worktree_ownership_path(target, deadline_monotonic=deadline_monotonic)
        if metadata_path is None or not metadata_path.is_file():
            return {"success": False, "error": "worktree ownership metadata is unavailable"}
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if not isinstance(metadata, dict):
            return {"success": False, "error": "worktree ownership metadata is invalid"}
        recorded_branch = str(metadata.get("branch", ""))
        current_branch = _git_value(target, "symbolic-ref", "--short", "HEAD", timeout=timeout, deadline_monotonic=deadline_monotonic)
        if (
            metadata.get("schema_version") != 1
            or str(metadata.get("worktree_id", "")) != worktree_id
            or Path(str(metadata.get("repo_root", ""))).resolve(strict=False) != repo
            or Path(str(metadata.get("worktree_path", ""))).resolve(strict=False) != target
            or not recorded_branch
            or recorded_branch != (branch_name or recorded_branch)
            or current_branch != recorded_branch
        ):
            return {"success": False, "error": "worktree ownership or branch metadata does not match"}
        if expected_task_id and str(metadata.get("task_id", "")) != expected_task_id:
            return {"success": False, "error": "worktree task ownership does not match"}
        if expected_owner and str(metadata.get("owner", "")) != expected_owner:
            return {"success": False, "error": "worktree owner metadata does not match"}

        try:
            created_at = float(metadata.get("created_at"))
            ttl_seconds = float(metadata.get("ttl_seconds"))
            expires_at_raw = metadata.get("expires_at")
            expires_at = float(expires_at_raw) if expires_at_raw is not None else None
        except (TypeError, ValueError):
            return {"success": False, "error": "worktree time metadata is invalid"}
        import math
        if (
            not math.isfinite(created_at)
            or not math.isfinite(ttl_seconds)
            or ttl_seconds < 60
            or ttl_seconds > 30 * 24 * 60 * 60
            or (expires_at is not None and (not math.isfinite(expires_at) or abs(expires_at - (created_at + ttl_seconds)) > max(1e-6, ttl_seconds * 1e-9)))
        ):
            return {"success": False, "error": "worktree time metadata is inconsistent"}
        for expected, actual in (
            (expected_created_at, created_at),
            (expected_ttl_seconds, ttl_seconds),
            (expected_expires_at, expires_at),
        ):
            if expected is not None and (actual is None or abs(float(expected) - float(actual)) > max(1e-6, ttl_seconds * 1e-9)):
                return {"success": False, "error": "worktree time metadata does not match task ownership"}

        if not force:
            status = _run_hidden_with_deadline(
                ["git", "-C", str(target), "status", "--porcelain", "--untracked-files=all", "--ignored"],
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout, deadline_monotonic=deadline_monotonic,
                **hidden_run_kwargs(),
            )
            if status.returncode != 0 or status.stdout.strip():
                return {"success": False, "error": "uncommitted_changes_in_worktree"}

        if required_base_commit:
            status_now = _run_hidden_with_deadline(
                ["git", "-C", str(target), "status", "--porcelain", "--untracked-files=all", "--ignored"],
                capture_output=True, text=True, check=False, timeout=timeout, deadline_monotonic=deadline_monotonic, **hidden_run_kwargs(),
            )
            root_head = _git_value(repo, "rev-parse", "--verify", "HEAD^{commit}", timeout=timeout, deadline_monotonic=deadline_monotonic)
            worktree_head = _git_value(target, "rev-parse", "--verify", "HEAD^{commit}", timeout=timeout, deadline_monotonic=deadline_monotonic)
            if status_now.returncode != 0 or status_now.stdout.strip() or not root_head or not worktree_head:
                return {"success": False, "error": "worktree changed during automatic cleanup"}
            for ancestor in (required_base_commit, worktree_head):
                proof = _run_hidden_with_deadline(
                    ["git", "-C", str(repo), "merge-base", "--is-ancestor", ancestor, root_head],
                    capture_output=True, text=True, check=False, timeout=timeout, deadline_monotonic=deadline_monotonic, **hidden_run_kwargs(),
                )
                if proof.returncode != 0:
                    return {"success": False, "error": "worktree changed outside approved repository history"}
            latest_head = _git_value(target, "rev-parse", "--verify", "HEAD^{commit}", timeout=timeout, deadline_monotonic=deadline_monotonic)
            latest_status = _run_hidden_with_deadline(
                ["git", "-C", str(target), "status", "--porcelain", "--untracked-files=all", "--ignored"],
                capture_output=True, text=True, check=False, timeout=timeout, deadline_monotonic=deadline_monotonic, **hidden_run_kwargs(),
            )
            if latest_head != worktree_head or latest_status.returncode != 0 or latest_status.stdout.strip():
                return {"success": False, "error": "worktree changed during automatic cleanup"}

        remove_cmd = ["git", "-C", str(repo), "worktree", "remove"]
        if force:
            remove_cmd.append("--force")
        remove_cmd.append(str(target))
        removed = _run_hidden_with_deadline(
            remove_cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout, deadline_monotonic=deadline_monotonic,
            **hidden_run_kwargs(),
        )
        if removed.returncode != 0:
            return {"success": False, "error": removed.stderr.strip() or "Git refused to remove worktree"}

        pruned = process_utils.prune_git_worktrees(repo, expire="now", timeout_seconds=timeout, deadline_monotonic=deadline_monotonic)
        if not pruned.get("success"):
            return {
                "success": False,
                "error": pruned.get("error") or "Git worktree prune failed",
                "worktree_removed": not target.exists(),
                "repo_root": str(repo),
                "worktree_path": str(target),
                "worktree_id": worktree_id,
            }

        branch_deleted = False
        if delete_branch:
            flag = "-D" if force else "-d"
            cmd_branch = ["git", "-C", str(repo), "branch", flag, recorded_branch]
            proc_b = _run_hidden_with_deadline(cmd_branch, capture_output=True, text=True, check=False, timeout=10, deadline_monotonic=deadline_monotonic, **hidden_run_kwargs())
            branch_deleted = (proc_b.returncode == 0)
            if not branch_deleted:
                return {
                    "success": False,
                    "error": proc_b.stderr.strip() or "worktree removed but Git refused to delete its branch",
                    "worktree_removed": not target.exists(),
                    "branch_deleted": False,
                    "repo_root": str(repo),
                    "worktree_path": str(target),
                    "worktree_id": worktree_id,
                }
        return {
            "success": True,
            "worktree_removed": not target.exists(),
            "branch_deleted": branch_deleted,
            "repo_root": str(repo),
            "worktree_path": str(target),
            "worktree_id": worktree_id,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def switch_git_worktree_branch(
    worktree_path: str | Path,
    target_branch: str,
    *,
    force: bool = False,
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    """Switch worktree branch, aborting if uncommitted changes exist unless force=True."""
    from .worktrees import switch_worktree_branch
    return switch_worktree_branch(worktree_path, target_branch, force=force, timeout_seconds=timeout_seconds)


def list_git_worktrees(repo_root: str | Path) -> dict[str, Any]:
    """Enumerate active Git worktrees and metadata."""
    repo = Path(repo_root).expanduser().resolve(strict=False)
    if not shutil.which("git"):
        return {"success": False, "error": "git executable not found"}
    try:
        proc = run_hidden(
            ["git", "-C", str(repo), "worktree", "list", "--porcelain"],
            capture_output=True, text=True, check=False, timeout=15, **hidden_run_kwargs()
        )
        if proc.returncode != 0:
            err_msg = proc.stderr.strip()
            if "not a git repository" in err_msg.lower():
                return {"success": True, "repo_root": str(repo), "worktrees": [], "count": 0, "is_git": False}
            return {"success": False, "error": err_msg or "git worktree list failed"}
        worktrees: list[dict[str, Any]] = []
        current: dict[str, Any] = {}
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line:
                if current.get("worktree"):
                    worktrees.append(current)
                current = {}
                continue
            if line.startswith("worktree "):
                current["worktree"] = line[len("worktree "):].strip()
            elif line.startswith("HEAD "):
                current["head"] = line[len("HEAD "):].strip()
            elif line.startswith("branch "):
                current["branch"] = line[len("branch "):].strip().replace("refs/heads/", "")
            elif line.startswith("bare"):
                current["bare"] = True
            elif line.startswith("locked"):
                current["locked"] = True
            elif line.startswith("prunable"):
                current["prunable"] = True
        if current.get("worktree"):
            worktrees.append(current)
        return {"success": True, "repo_root": str(repo), "worktrees": worktrees, "count": len(worktrees)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def prune_git_worktrees(
    repo_root: str | Path, expire: str | None = None, timeout_seconds: float = 15.0, *, deadline_monotonic: float | None = None
) -> dict[str, Any]:
    """Prune stale Git worktrees."""
    repo = Path(repo_root).expanduser().resolve(strict=False)
    if not shutil.which("git"):
        return {"success": False, "error": "git executable not found"}
    try:
        cmd = ["git", "-C", str(repo), "worktree", "prune", "-v"]
        if expire:
            cmd.extend(["--expire", expire])
        proc = _run_hidden_with_deadline(
            cmd,
            capture_output=True, text=True, check=False,
            timeout=max(0.5, min(float(timeout_seconds), 30.0)), deadline_monotonic=deadline_monotonic, **hidden_run_kwargs()
        )
        if proc.returncode != 0:
            err_msg = proc.stderr.strip()
            if "not a git repository" in err_msg.lower():
                return {"success": True, "repo_root": str(repo), "is_git": False, "output": "not a git repository"}
            return {"success": False, "repo_root": str(repo), "error": err_msg or "git worktree prune failed"}
        return {
            "success": True,
            "repo_root": str(repo),
            "output": proc.stdout.strip() or proc.stderr.strip() or "pruned successfully",
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}



def simulate_git_merge(
    repo_root: str | Path,
    source_branch: str,
    target_branch: str = "HEAD",
) -> dict[str, Any]:
    """Simulate a 3-way merge without touching the working tree or index via git merge-tree."""
    repo = Path(repo_root).expanduser().resolve(strict=False)
    if not shutil.which("git"):
        return {"success": False, "error": "git executable not found"}

    try:
        cmd = ["git", "-C", str(repo), "merge-tree", "--write-tree", target_branch, source_branch]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=30, **hidden_run_kwargs())
        first_line = proc.stdout.splitlines()[0].strip() if proc.stdout else ""
        has_tree_oid = len(first_line) in (40, 64) and all(
            char in "0123456789abcdefABCDEF" for char in first_line
        )
        if proc.returncode not in (0, 1) or (proc.returncode == 1 and not has_tree_oid):
            return {
                "success": False,
                "exit_code": proc.returncode,
                "error": (proc.stderr.strip() or "git merge-tree failed")[:500],
            }

        clean = (proc.returncode == 0)
        output = proc.stdout.strip()
        conflicts: list[str] = []
        for line in output.splitlines():
            line_str = line.strip()
            if "conflict" in line_str.lower() or "auto-merging" in line_str.lower():
                conflicts.append(line_str)
        if proc.stderr:
            for line in proc.stderr.splitlines():
                if line.strip():
                    conflicts.append(line.strip())

        return {
            "success": True,
            "mergeable": clean,
            "exit_code": proc.returncode,
            "source_branch": source_branch,
            "target_branch": target_branch,
            "conflicts": conflicts,
            "conflict_count": len(conflicts) if not clean else 0,
            "output_preview": output[:500],
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}

