import subprocess
from pathlib import Path
from local_ai_hub.process_utils import create_git_worktree, remove_git_worktree, prune_git_worktrees

def test_remove_git_worktree_prunes_stale_metadata(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo), check=True)
    (repo / "README.md").write_text("# Test")
    subprocess.run(["git", "add", "README.md"], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(repo), check=True)

    # Create worktree
    res = create_git_worktree(repo, owner="agent-1")
    assert res.get("success") is True
    wt_path = res["worktree_path"]
    wt_id = res["worktree_id"]
    assert Path(wt_path).exists()

    # Add an untracked file to worktree to verify force removal works
    (Path(wt_path) / "untracked.txt").write_text("untracked")

    # Remove worktree
    del_res = remove_git_worktree(wt_path, repo_root=repo, worktree_id=wt_id, force=True)
    assert del_res.get("success") is True
    assert not Path(wt_path).exists()

    # Verify worktree list only contains the main repo
    p = subprocess.run(["git", "-C", str(repo), "worktree", "list", "--porcelain"], capture_output=True, text=True, check=True)
    assert wt_path not in p.stdout
