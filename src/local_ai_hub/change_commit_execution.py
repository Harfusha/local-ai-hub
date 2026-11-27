"""Explicit local-only commit of an already reviewed, exact staged index.

No automatic staging, push, hook bypass or assertion of verification. The
branch update is a Git compare-and-swap; the real index is never rewritten.
"""
from __future__ import annotations

import os
import re
import subprocess
import sqlite3
import tempfile
import uuid
from pathlib import Path
from typing import Any

from .change_commit_preflight import commit_preflight
from .process_utils import clean_git_env, run_hidden
from .repository_scope import authorized_repository_root, _is_redirecting_link

_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_MAX_INDEX = 16 * 1024 * 1024


def execute_staged_commit(
    config: dict[str, Any], engine: Any, lease_store: Any, *,
    root: str, paths: list[str], expected_revision: str, expected_tree: str,
    message: str, approved: bool, journal: Any | None = None, allow_mixed_staged: bool = False,
    sequence: list[dict[str, Any]] | None = None, preview_only: bool = False, preview_digest: str = "",
    verification_manifest: Any | None = None,
) -> dict[str, Any]:
    """Commit a reviewed stage-zero tree only, under a root lease and index lock."""
    if (approved is not True and not (preview_only is True and sequence is not None)) or not isinstance(expected_tree, str) or not _OID.fullmatch(expected_tree):
        return {"success": False, "error": "Explicit approval and exact tree ID required"}
    if sequence is None and (
        not isinstance(message, str) or not message.strip() or len(message) > 4096
        or any(ord(c) < 32 and c not in "\n\t" for c in message)
    ):
        return {"success": False, "error": "Invalid commit message"}
    operation_id = uuid.uuid4().hex
    owner = "git-commit-" + operation_id
    lease_id = ""
    candidate = ""
    branch = ""
    update_attempted = False
    lock_fd: int | None = None
    lock_path: Path | None = None
    outcome: dict[str, Any] = {"success": False, "commit_ready": False}

    def git(*args: str, extra: dict[str, str] | None = None, allow_missing: bool = False) -> bytes:
        cp = run_hidden(
            ["git", "--no-pager", "-c", "core.fsmonitor=false", *args],
            cwd=root, capture_output=True, check=False, stdin=subprocess.DEVNULL,
            env=clean_git_env(extra_env={
                "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0",
                "GIT_NO_LAZY_FETCH": "1", "GIT_NO_REPLACE_OBJECTS": "1", "LC_ALL": "C",
                **(extra or {}),
            }),
            timeout=20.0, max_output_bytes=4 * 1024 * 1024,
        )
        if getattr(cp, "stdout_truncated", False) or getattr(cp, "stderr_truncated", False):
            raise ValueError("Git output budget exceeded")
        if allow_missing and cp.returncode == 1 and not cp.stdout and not cp.stderr:
            return b""
        if cp.returncode:
            raise ValueError("Git operation refused: " + args[0])
        return cp.stdout

    def oid(*args: str, extra: dict[str, str] | None = None) -> str:
        value = git(*args, extra=extra).strip().decode("ascii")
        if not _OID.fullmatch(value):
            raise ValueError("Invalid Git object identity")
        return value

    def require_supported_state(git_dir: Path) -> None:
        # This plumbing transaction does not run commit hooks. Refuse any
        # custom hook configuration or installed hook, rather than skip it.
        hooks_path = git("config", "--get-all", "core.hooksPath", allow_missing=True)
        if hooks_path:
            raise ValueError("Custom hooks require the normal Git commit workflow")
        hooks = git_dir / "hooks"
        if _is_redirecting_link(hooks) or (hooks.exists() and any(not p.name.endswith(".sample") for p in hooks.iterdir())):
            raise ValueError("Installed hooks require the normal Git commit workflow")
        signing = git("config", "--type=bool", "--get-all", "commit.gpgsign", allow_missing=True)
        if signing and signing.strip().splitlines() != [b"false"]:
            raise ValueError("Configured signing requires the normal Git commit workflow")
        if any((git_dir / name).exists() for name in (
            "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "REBASE_HEAD",
            "rebase-merge", "rebase-apply", "sequencer", "BISECT_START",
        )):
            raise ValueError("Repository operation in progress")

    try:
        root = authorized_repository_root(config, root)
        git_dir = Path(root) / ".git"
        if not git_dir.is_dir() or _is_redirecting_link(git_dir):
            raise ValueError("Only a primary worktree with a local .git directory is supported")
        if Path(os.fsdecode(git("rev-parse", "--show-toplevel").rstrip(b"\r\n"))).resolve() != Path(root):
            raise ValueError("Expected exact worktree root")
        if Path(os.fsdecode(git("rev-parse", "--absolute-git-dir").rstrip(b"\r\n"))).resolve() != git_dir:
            raise ValueError("Unexpected Git metadata location")
        claimed = lease_store.claim(owner=owner, root=root, paths=["."], ttl_seconds=600,
                                    purpose="explicit staged commit")
        if claimed.get("success") is not True or not claimed.get("lease_id"):
            raise ValueError("Repository write lease unavailable")
        lease_id = claimed["lease_id"]
        index = git_dir / "index"
        lock_path = git_dir / "index.lock"
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        require_supported_state(git_dir)
        branch = git("symbolic-ref", "--quiet", "HEAD").strip().decode("utf-8")
        if not branch.startswith("refs/heads/") or "\n" in branch:
            raise ValueError("Attached local branch required")
        parent = oid("rev-parse", "--verify", "HEAD^{commit}")
        plan = engine.split_changes(root, None)
        preflight = commit_preflight(plan, paths, expected_revision, allow_mixed="commit" if allow_mixed_staged is True else "")
        if (
            preflight.get("success") is not True or preflight.get("index_scope_matches_selection") is not True
            or preflight.get("prospective_index_tree_oid") != expected_tree
            or plan.get("git_snapshot_metadata", {}).get("head") != parent
        ):
            raise ValueError("Reviewed staged scope, parent or tree changed; refresh preflight")
        if _is_redirecting_link(index) or not index.is_file() or index.stat().st_size > _MAX_INDEX:
            raise ValueError("Unsupported or oversized index")
        with index.open("rb") as stream:
            original = stream.read(_MAX_INDEX + 1)
        if len(original) > _MAX_INDEX:
            raise ValueError("Index exceeds budget")
        sequence_plan = None
        verification_receipts: list[str] = []
        if sequence is not None:
            from .change_commit_sequence import plan_sequence

            sequence_plan = plan_sequence(
                git("ls-tree", "-r", "-z", parent), git("ls-files", "--stage", "-z"),
                parent, expected_tree, sequence, plan["clusters"], expected_revision,
            )
            if preview_only is True:
                outcome = {"success": True, "applied": False, **sequence_plan}
                return outcome
            if preview_digest != sequence_plan["preview_digest"]:
                raise ValueError("Sequence differs from approved preview")
            if verification_manifest is not None:
                from .change_tree_verification import require_sequence_receipts

                if journal is None:
                    raise ValueError("Verification receipt journal unavailable")
                verification_receipts = require_sequence_receipts(root, sequence_plan, verification_manifest, journal)
        candidates: list[str] = []
        with tempfile.TemporaryDirectory(prefix="hub-commit-", dir=git_dir) as temp:
            temporary_index = Path(temp) / "index"
            temporary_index.write_bytes(original)
            actual_tree = oid("write-tree", extra={"GIT_INDEX_FILE": str(temporary_index)})
            if actual_tree != expected_tree:
                raise ValueError("Materialized Git tree does not match approved tree")
            actual_paths = git("diff-tree", "--no-commit-id", "--name-only", "-z", "-r",
                               "--no-renames", parent, actual_tree, "--")
            if not actual_paths.endswith(b"\0") or set(actual_paths.split(b"\0")[:-1]) != {os.fsencode(path) for path in paths}:
                raise ValueError("Exact tree diff does not match the reviewed path selection")
            # Candidate object creation does not publish a commit or alter the
            # index. An unsuccessful CAS may leave a normal unreachable object.
            if sequence_plan is None:
                candidate = oid("commit-tree", actual_tree, "-p", parent, "-m", message)
                candidates.append(candidate)
            else:
                from .change_commit_sequence import _entries

                target = _entries(git("ls-files", "--stage", "-z"), staged=True)
                sequence_index = Path(temp) / "sequence-index"
                extra = {"GIT_INDEX_FILE": str(sequence_index)}
                git("read-tree", parent, extra=extra)
                current_parent = parent
                for step in sequence_plan["steps"]:
                    for path in step["paths"]:
                        if os.fsencode(path) not in target:
                            git("--literal-pathspecs", "update-index", "--force-remove", "--", path, extra=extra)
                    for path in step["paths"]:
                        entry = target.get(os.fsencode(path))
                        if entry is not None:
                            mode, blob = (value.decode("ascii") for value in entry)
                            git("update-index", "--add", "--cacheinfo", f"{mode},{blob},{path}", extra=extra)
                    step_tree = oid("write-tree", extra=extra)
                    if step_tree != step["tree_oid"]:
                        raise ValueError("Intermediate tree differs from approved plan")
                    step_paths = git("diff-tree", "--no-commit-id", "--name-only", "-z", "-r",
                                     "--no-renames", current_parent, step_tree, "--")
                    if not step_paths.endswith(b"\0") or set(step_paths.split(b"\0")[:-1]) != {os.fsencode(p) for p in step["paths"]}:
                        raise ValueError("Intermediate tree diff differs from approved scope")
                    candidate = oid("commit-tree", step_tree, "-p", current_parent, "-m", step["message"])
                    candidates.append(candidate)
                    current_parent = candidate
        if _is_redirecting_link(index) or index.stat().st_size != len(original):
            raise ValueError("Index changed while locked")
        with index.open("rb") as stream:
            current_index = stream.read(_MAX_INDEX + 1)
        if current_index != original:
            raise ValueError("Index changed while locked")
        require_supported_state(git_dir)
        if git("symbolic-ref", "--quiet", "HEAD").strip().decode("utf-8") != branch:
            raise ValueError("Branch changed during transaction")
        renewed = lease_store.renew(owner=owner, lease_id=lease_id, ttl_seconds=600)
        if renewed.get("success") is not True:
            raise ValueError("Repository lease expired")
        if journal is not None:
            journal.prepare(operation_id=operation_id, root=root, branch=branch, parent=parent,
                            tree=actual_tree, candidate=candidate)
        if sequence_plan is not None and verification_manifest is not None:
            verification_receipts = require_sequence_receipts(root, sequence_plan, verification_manifest, journal)
        update_attempted = True
        git("update-ref", "--no-deref", "-m", "Local AI Hub: approved staged commit", branch, candidate, parent)
        outcome = {
            "success": True, "commit_oid": candidate, "parent_oid": parent, "tree_oid": actual_tree,
            "branch": branch, "index_rewritten": False, "pushed": False,
            "verification_status": "configured_commands_passed" if verification_receipts else "not_assessed",
            "tree_check_receipt_ids": verification_receipts, "explicit_user_approval": True,
            "operation_id": operation_id, "commit_oids": candidates,
        }
        if journal is not None:
            try:
                journal.published(operation_id)
            except Exception:
                outcome["journal_update_unconfirmed"] = True
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, sqlite3.Error) as exc:
        outcome = {"success": False, "error": str(exc), "commit_ready": False,
                   "outcome_unknown": update_attempted, "retryable": False, "operation_id": operation_id}
        if candidate:
            outcome.update(candidate_commit_oid=candidate, branch=branch)
        if update_attempted:
            outcome["recovery"] = "Inspect the branch and candidate commit before retrying; never retry blindly."
    finally:
        if lock_fd is not None and lock_path is not None:
            try:
                held = os.fstat(lock_fd)
                current = lock_path.lstat()
                same = (held.st_dev, held.st_ino) == (current.st_dev, current.st_ino)
                os.close(lock_fd)
                lock_fd = None
                if same:
                    lock_path.unlink()
                else:
                    outcome["cleanup_unconfirmed"] = True
            except OSError:
                outcome["cleanup_unconfirmed"] = True
            finally:
                if lock_fd is not None:
                    os.close(lock_fd)
        if lease_id:
            try:
                released = lease_store.release(owner=owner, lease_id=lease_id)
                if released.get("success") is not True:
                    outcome["cleanup_unconfirmed"] = True
            except Exception:
                outcome["cleanup_unconfirmed"] = True
    return outcome
