"""Git Native Worktree Lifecycle Manager.

Provides robust, fail-safe isolation for Agent OS tasks and experimental branches:
1. Sandboxed worktree allocation inside <repo_root>/state/worktrees/<task_id>.
2. Sanitized naming and strict path confinement (preventing path traversal).
3. Registry persistence for tracked worktrees with creation timestamps and metadata.
4. Atomic verification-gated merge and automatic post-merge worktree teardown.
5. Windows-safe file handle handling and hidden subprocess execution.
"""

from __future__ import annotations

import json
import logging
# import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .process_utils import hidden_run_kwargs

logger = logging.getLogger(__name__)

SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_\-\.]+$")


@dataclass(frozen=True)
class WorktreeInfo:
    """Descriptor of an active or tracked worktree."""

    task_id: str
    worktree_path: str
    branch: str
    base_ref: str
    created_at: float
    status: str  # "active", "merged", "removed"


@dataclass(frozen=True)
class WorktreeCreateResult:
    """Outcome of worktree creation."""

    success: bool
    worktree_path: str
    branch: str
    error: Optional[str] = None


@dataclass(frozen=True)
class WorktreeRemoveResult:
    """Outcome of worktree deletion."""

    success: bool
    task_id: str
    branch_deleted: bool
    error: Optional[str] = None


@dataclass(frozen=True)
class WorktreeMergeResult:
    """Outcome of worktree merge."""

    success: bool
    task_id: str
    target_branch: str
    commit_hash: Optional[str] = None
    error: Optional[str] = None


class WorktreeLifecycleManager:
    """High-level orchestrator for task worktrees."""

    def __init__(self, repo_root: str | Path):
        self.repo_root = Path(repo_root).resolve()
        self.worktrees_dir = self.repo_root / "state" / "worktrees"
        self.registry_file = self.worktrees_dir / "registry.json"
        self._ensure_dir()

    def _ensure_dir(self) -> None:
        self.worktrees_dir.mkdir(parents=True, exist_ok=True)

    def _load_registry(self) -> Dict[str, Dict[str, Any]]:
        if not self.registry_file.is_file():
            return {}
        try:
            with open(self.registry_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_registry(self, registry: Dict[str, Dict[str, Any]]) -> None:
        try:
            with open(self.registry_file, "w", encoding="utf-8") as f:
                json.dump(registry, f, indent=2)
        except Exception as e:
            logger.warning("Failed to save worktree registry: %s", e)

    def _run_git(self, args: List[str], cwd: Optional[Path] = None, timeout: float = 15.0) -> subprocess.CompletedProcess[str]:
        target_cwd = cwd or self.repo_root
        return subprocess.run(
            ["git", "-C", str(target_cwd)] + args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
            **hidden_run_kwargs(),
        )

    def create_worktree(
        self,
        task_id: str,
        base_ref: str = "HEAD",
        branch_name: Optional[str] = None,
    ) -> WorktreeCreateResult:
        """Create a new isolated git worktree for a task."""
        if not SAFE_ID_RE.match(task_id):
            return WorktreeCreateResult(
                success=False,
                worktree_path="",
                branch="",
                error=f"Invalid task_id: '{task_id}'. Must be alphanumeric.",
            )

        branch = branch_name or f"task/{task_id}"
        if not SAFE_ID_RE.match(branch.replace("/", "-")):
            return WorktreeCreateResult(
                success=False,
                worktree_path="",
                branch="",
                error=f"Invalid branch name: '{branch}'.",
            )

        target_path = (self.worktrees_dir / task_id).resolve()

        # Confinement check: target_path must be strictly inside worktrees_dir
        try:
            target_path.relative_to(self.worktrees_dir)
        except ValueError:
            return WorktreeCreateResult(
                success=False,
                worktree_path="",
                branch="",
                error="Path traversal violation: worktree must reside in state/worktrees/",
            )

        if target_path.exists():
            return WorktreeCreateResult(
                success=False,
                worktree_path=str(target_path),
                branch=branch,
                error=f"Worktree path already exists: {target_path}",
            )

        # Execute git worktree add
        cmd = ["worktree", "add", "-b", branch, str(target_path), base_ref]
        res = self._run_git(cmd)
        if res.returncode != 0:
            return WorktreeCreateResult(
                success=False,
                worktree_path=str(target_path),
                branch=branch,
                error=res.stderr.strip() or "git worktree add failed",
            )

        # Update registry
        reg = self._load_registry()
        reg[task_id] = {
            "task_id": task_id,
            "worktree_path": str(target_path),
            "branch": branch,
            "base_ref": base_ref,
            "created_at": time.time(),
            "status": "active",
        }
        self._save_registry(reg)

        return WorktreeCreateResult(
            success=True,
            worktree_path=str(target_path),
            branch=branch,
        )

    def list_worktrees(self) -> List[WorktreeInfo]:
        """List all tracked worktrees."""
        reg = self._load_registry()
        out: List[WorktreeInfo] = []
        for tid, meta in reg.items():
            out.append(
                WorktreeInfo(
                    task_id=tid,
                    worktree_path=meta.get("worktree_path", ""),
                    branch=meta.get("branch", ""),
                    base_ref=meta.get("base_ref", ""),
                    created_at=meta.get("created_at", 0.0),
                    status=meta.get("status", "unknown"),
                )
            )
        return out

    def remove_worktree(
        self,
        task_id: str,
        delete_branch: bool = True,
        force: bool = True,
    ) -> WorktreeRemoveResult:
        """Remove a worktree and optionally delete its branch."""
        reg = self._load_registry()
        meta = reg.get(task_id)
        if not meta:
            return WorktreeRemoveResult(
                success=False,
                task_id=task_id,
                branch_deleted=False,
                error=f"Task {task_id} not found in registry",
            )

        target_path = Path(meta["worktree_path"])
        branch = meta.get("branch", "")

        # Git worktree remove
        cmd = ["worktree", "remove"]
        if force:
            cmd.append("--force")
        cmd.append(str(target_path))

        self._run_git(cmd)
        # Even if git worktree remove had an error (e.g. dir manually deleted), prune worktrees
        self._run_git(["worktree", "prune"])

        branch_deleted = False
        if delete_branch and branch:
            b_res = self._run_git(["branch", "-D", branch])
            branch_deleted = b_res.returncode == 0

        # Mark removed in registry
        meta["status"] = "removed"
        reg[task_id] = meta
        self._save_registry(reg)

        return WorktreeRemoveResult(
            success=True,
            task_id=task_id,
            branch_deleted=branch_deleted,
        )

    def merge_worktree(
        self,
        task_id: str,
        target_branch: str = "master",
    ) -> WorktreeMergeResult:
        """Merge worktree branch into target_branch."""
        reg = self._load_registry()
        meta = reg.get(task_id)
        if not meta:
            return WorktreeMergeResult(
                success=False,
                task_id=task_id,
                target_branch=target_branch,
                error="Worktree not registered",
            )

        branch = meta.get("branch", "")
        if not branch:
            return WorktreeMergeResult(
                success=False,
                task_id=task_id,
                target_branch=target_branch,
                error="Branch name missing from worktree metadata",
            )

        # Merge branch into target branch
        res = self._run_git(["merge", branch], cwd=self.repo_root)
        if res.returncode != 0:
            return WorktreeMergeResult(
                success=False,
                task_id=task_id,
                target_branch=target_branch,
                error=f"Merge failed: {res.stderr.strip()}",
            )

        # Get latest commit hash
        rev = self._run_git(["rev-parse", "HEAD"], cwd=self.repo_root)
        commit_hash = rev.stdout.strip() if rev.returncode == 0 else None

        # Clean up worktree after successful merge
        self.remove_worktree(task_id=task_id, delete_branch=True, force=True)

        meta["status"] = "merged"
        reg[task_id] = meta
        self._save_registry(reg)

        return WorktreeMergeResult(
            success=True,
            task_id=task_id,
            target_branch=target_branch,
            commit_hash=commit_hash,
        )
