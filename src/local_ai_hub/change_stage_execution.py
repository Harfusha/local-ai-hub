"""Explicit two-phase whole-path staging; preview uses isolated Git objects."""
from __future__ import annotations

import os
import re
import stat
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

from .change_commit_preflight import commit_preflight
from .process_utils import clean_git_env, run_hidden
from .repository_scope import authorized_repository_root, _is_redirecting_link

_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_MAX_INDEX = 16 * 1024 * 1024


def stage_selection(
    config: dict[str, Any], engine: Any, leases: Any, *, root: str, paths: list[str],
    expected_revision: str, expected_tree: str = "", apply: bool = False,
) -> dict[str, Any]:
    if type(apply) is not bool or (apply and not _OID.fullmatch(expected_tree)):
        return {"success": False, "error": "Apply requires the exact preview tree ID"}
    owner = "git-stage-" + uuid.uuid4().hex
    lease_id = ""
    lock_fd: int | None = None
    lock_path: Path | None = None
    lock_identity: tuple[int, int] | None = None
    replaced = False
    outcome: dict[str, Any] = {"success": False}

    def git(*args: str, extra: dict[str, str] | None = None, missing: bool = False) -> bytes:
        cp = run_hidden(
            ["git", "--no-pager", "-c", "core.fsmonitor=false", "-c", "core.splitIndex=false", *args],
            cwd=root, capture_output=True, check=False, stdin=subprocess.DEVNULL,
            timeout=20.0, max_output_bytes=4 * 1024 * 1024,
            env=clean_git_env(extra_env={"GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0",
                                        "GIT_NO_LAZY_FETCH": "1", "GIT_NO_REPLACE_OBJECTS": "1",
                                        "LC_ALL": "C", **(extra or {})}),
        )
        if getattr(cp, "stdout_truncated", False) or getattr(cp, "stderr_truncated", False):
            raise ValueError("Git output budget exceeded")
        if missing and cp.returncode == 1 and not cp.stdout and not cp.stderr:
            return b""
        if cp.returncode:
            raise ValueError("Git operation refused: " + args[0])
        return cp.stdout

    def oid(*args: str, extra: dict[str, str] | None = None) -> str:
        value = git(*args, extra=extra).strip().decode("ascii")
        if not _OID.fullmatch(value):
            raise ValueError("Invalid Git object identity")
        return value

    def check_lock() -> None:
        if lock_path is None or lock_identity is None:
            raise ValueError("Index lock not held")
        info = lock_path.lstat()
        if (info.st_dev, info.st_ino) != lock_identity or not stat.S_ISREG(info.st_mode):
            raise ValueError("Index lock ownership changed")

    def read_index(index: Path) -> bytes:
        if _is_redirecting_link(index) or not index.is_file() or index.stat().st_size > _MAX_INDEX:
            raise ValueError("Unsupported or oversized index")
        with index.open("rb") as stream:
            data = stream.read(_MAX_INDEX + 1)
        if len(data) > _MAX_INDEX:
            raise ValueError("Index exceeds budget")
        return data

    def require_supported(git_dir: Path) -> None:
        if git("config", "--get-regexp", r"^filter\.", missing=True):
            raise ValueError("Configured Git filters require manual staging")
        if git("config", "--get-all", "core.hooksPath", missing=True):
            raise ValueError("Custom Git hooks require manual staging")
        hooks = git_dir / "hooks"
        if _is_redirecting_link(hooks) or (hooks.exists() and any(not p.name.endswith(".sample") for p in hooks.iterdir())):
            raise ValueError("Installed Git hooks require manual staging")
        if git("rev-parse", "--shared-index-path").strip():
            raise ValueError("Split index requires manual staging")
        for key in ("core.sparseCheckout", "index.sparse"):
            setting = git("config", "--type=bool", "--get-all", key, missing=True)
            if setting and setting.strip().splitlines() != [b"false"]:
                raise ValueError("Sparse index requires manual staging")
        if any((git_dir / name).exists() for name in (
            "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "REBASE_HEAD",
            "rebase-merge", "rebase-apply", "sequencer", "BISECT_START",
        )):
            raise ValueError("Repository operation in progress")

    try:
        root = authorized_repository_root(config, root)
        git_dir = Path(root) / ".git"
        objects = git_dir / "objects"
        if not git_dir.is_dir() or _is_redirecting_link(git_dir) or not objects.is_dir() or _is_redirecting_link(objects):
            raise ValueError("Only a primary worktree with a local object database is supported")
        if Path(os.fsdecode(git("rev-parse", "--show-toplevel").rstrip(b"\r\n"))).resolve() != Path(root):
            raise ValueError("Expected exact worktree root")
        if Path(os.fsdecode(git("rev-parse", "--absolute-git-dir").rstrip(b"\r\n"))).resolve() != git_dir:
            raise ValueError("Unexpected Git metadata location")
        if any(c in str(objects) for c in (os.pathsep, "\n", "\r", '"')):
            raise ValueError("Unsupported object database path")
        claimed = leases.claim(owner=owner, root=root, paths=["."], ttl_seconds=600, purpose="explicit staging")
        if claimed.get("success") is not True or not claimed.get("lease_id"):
            raise ValueError("Repository write lease unavailable")
        lease_id = claimed["lease_id"]
        index = git_dir / "index"
        lock_path = git_dir / "index.lock"
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        info = os.fstat(lock_fd)
        lock_identity = (info.st_dev, info.st_ino)
        require_supported(git_dir)
        branch = git("symbolic-ref", "--quiet", "HEAD")
        parent = oid("rev-parse", "--verify", "HEAD^{commit}")
        plan = engine.split_changes(root, None)
        preflight = commit_preflight(plan, paths, expected_revision, allow_untracked=True)
        if (preflight.get("success") is not True or preflight.get("staging_preview_available") is not True
                or not preflight.get("unstaged_selection") or plan.get("git_snapshot_metadata", {}).get("head") != parent):
            raise ValueError("Selection is stale, blocked, or has no unstaged paths")
        original = read_index(index)
        index_mode = stat.S_IMODE(index.stat().st_mode)
        with tempfile.TemporaryDirectory(prefix="hub-stage-", dir=git_dir) as temp:
            temp_dir = Path(temp)
            temporary_index = temp_dir / "index"
            temporary_index.write_bytes(original)
            extra = {"GIT_INDEX_FILE": str(temporary_index)}
            if not apply:
                temporary_objects = temp_dir / "objects"
                temporary_objects.mkdir()
                extra.update(GIT_OBJECT_DIRECTORY=str(temporary_objects),
                             GIT_ALTERNATE_OBJECT_DIRECTORIES=str(objects))
            git("--literal-pathspecs", "add", "-A", "--", *preflight["unstaged_selection"], extra=extra)
            tree = oid("write-tree", extra=extra)
            actual = git("diff-tree", "--no-commit-id", "--name-only", "-z", "-r",
                         "--no-renames", parent, tree, "--", extra=extra)
            if not actual.endswith(b"\0") or set(actual.split(b"\0")[:-1]) != {os.fsencode(p) for p in paths}:
                raise ValueError("Prospective tree does not match exact selected paths")
            candidate_index = read_index(temporary_index)
        if read_index(index) != original or git("symbolic-ref", "--quiet", "HEAD") != branch or oid("rev-parse", "--verify", "HEAD^{commit}") != parent:
            raise ValueError("HEAD or index changed during staging")
        after = engine.split_changes(root, None)
        if (after.get("observed_change_set_id") != expected_revision
                or after.get("git_visible_observation_complete") is not True):
            raise ValueError("Worktree observation changed during staging")
        require_supported(git_dir)
        if apply:
            if tree != expected_tree:
                raise ValueError("Prepared tree differs from explicitly approved preview")
            if leases.renew(owner=owner, lease_id=lease_id, ttl_seconds=600).get("success") is not True:
                raise ValueError("Repository lease expired")
            check_lock()
            if read_index(index) != original or git("symbolic-ref", "--quiet", "HEAD") != branch or oid("rev-parse", "--verify", "HEAD^{commit}") != parent:
                raise ValueError("HEAD or index changed before publication")
            with os.fdopen(lock_fd, "wb", closefd=False) as stream:
                stream.write(candidate_index)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(lock_path, index_mode)
            os.close(lock_fd)
            lock_fd = None
            check_lock()
            os.replace(lock_path, index)
            replaced = True
        outcome = {"success": True, "applied": replaced, "prospective_tree_oid": tree, "parent_oid": parent,
                   "observed_change_set_id": expected_revision, "selected_paths": sorted(paths),
                   "verification_status": "unknown", "commit_ready": False,
                   "requires_post_stage_reinspection": True}
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        outcome = {"success": False, "error": str(exc), "applied": replaced, "retryable": False}
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
        if lock_identity is not None and not replaced:
            try:
                check_lock()
                lock_path.unlink()
            except (OSError, ValueError):
                outcome["cleanup_unconfirmed"] = True
        if lease_id:
            try:
                if leases.release(owner=owner, lease_id=lease_id).get("success") is not True:
                    outcome["cleanup_unconfirmed"] = True
            except Exception:
                outcome["cleanup_unconfirmed"] = True
    return outcome
