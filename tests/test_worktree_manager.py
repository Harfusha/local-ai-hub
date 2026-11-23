"""Unit tests for Git Native Worktree Lifecycle Manager."""

import os
import subprocess
import tempfile
from pathlib import Path

from local_ai_hub.worktree_manager import WorktreeLifecycleManager


def _init_test_git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # Create initial commit
    dummy_file = path / "README.md"
    dummy_file.write_text("# Test Repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=path, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def test_worktree_lifecycle_create_and_remove() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        repo_root = Path(tmp_dir)
        _init_test_git_repo(repo_root)

        manager = WorktreeLifecycleManager(repo_root)
        task_id = "test-task-123"

        # 1. Create worktree
        create_res = manager.create_worktree(task_id=task_id)
        assert create_res.success, f"Create failed: {create_res.error}"
        wt_path = Path(create_res.worktree_path)
        assert wt_path.exists()
        assert (wt_path / "README.md").exists()

        # 2. List worktrees
        wt_list = manager.list_worktrees()
        assert len(wt_list) == 1
        assert wt_list[0].task_id == task_id
        assert wt_list[0].status == "active"

        # 3. Add a file in worktree
        feature_file = wt_path / "feature.py"
        feature_file.write_text("print('feature')\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=wt_path, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["git", "commit", "-m", "Add feature"], cwd=wt_path, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # 4. Remove worktree
        rem_res = manager.remove_worktree(task_id=task_id, delete_branch=True)
        assert rem_res.success, f"Remove failed: {rem_res.error}"
        assert not wt_path.exists()


def test_worktree_path_confinement() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        repo_root = Path(tmp_dir)
        _init_test_git_repo(repo_root)
        manager = WorktreeLifecycleManager(repo_root)

        # Illegal task_id with traversal attempts
        res = manager.create_worktree(task_id="../escape")
        assert not res.success
        assert "Invalid task_id" in (res.error or "")


def test_worktree_merge_workflow() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        repo_root = Path(tmp_dir)
        _init_test_git_repo(repo_root)
        manager = WorktreeLifecycleManager(repo_root)

        task_id = "merge-task"
        create_res = manager.create_worktree(task_id=task_id)
        assert create_res.success

        wt_path = Path(create_res.worktree_path)
        new_file = wt_path / "new_module.py"
        new_file.write_text("CONSTANT = 42\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=wt_path, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["git", "commit", "-m", "Implement new module"], cwd=wt_path, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Merge into main/master
        merge_res = manager.merge_worktree(task_id=task_id, target_branch="master")
        assert merge_res.success, f"Merge failed: {merge_res.error}"
        assert (repo_root / "new_module.py").exists()
        assert not wt_path.exists()
