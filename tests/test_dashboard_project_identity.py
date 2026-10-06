from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from local_ai_hub.dashboard import DASHBOARD_HTML
from local_ai_hub.preprocess import _project_git_identity


def test_project_git_identity_uses_git_metadata_not_directory_name(tmp_path: Path) -> None:
    generic_root = tmp_path / ".codex" / "worktrees"
    generic_root.mkdir(parents=True)
    identity, is_worktree = _project_git_identity(str(generic_root))
    assert identity == str(generic_root.resolve())
    assert is_worktree is False

    primary = tmp_path / "actual-repository"
    common_dir = primary / ".git"
    common_dir.mkdir(parents=True)
    linked = generic_root / "linked-checkout"
    linked.mkdir()
    git_dir = common_dir / "worktrees" / "linked-checkout"
    git_dir.mkdir(parents=True)
    (linked / ".git").write_text(f"gitdir: {git_dir}\n", encoding="utf-8")
    (git_dir / "commondir").write_text("../..\n", encoding="utf-8")

    linked_identity, is_worktree = _project_git_identity(str(linked))
    assert linked_identity == str(common_dir.resolve())
    assert is_worktree is True

    separate = generic_root / "another-repository"
    separate_git_dir = separate / ".git"
    separate_git_dir.mkdir(parents=True)
    separate_identity, is_worktree = _project_git_identity(str(separate))
    assert separate_identity == str(separate_git_dir.resolve())
    assert separate_identity != linked_identity
    assert is_worktree is False


def test_dashboard_groups_only_using_git_identity_and_explicit_worktree_flag() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to execute the dashboard identity helper")
    start = DASHBOARD_HTML.index("function projectIdentity(project)")
    end = DASHBOARD_HTML.index("function renderProjects(items)", start)
    render_start = DASHBOARD_HTML.index("function renderProjects(items)")
    render_end = DASHBOARD_HTML.index("async function projectAction", render_start)
    script = "function $(name){return name==='projectGroupWorktrees'?{checked:true}:null;}\n"
    script += DASHBOARD_HTML[start:end] + DASHBOARD_HTML[render_start:render_end]
    script += "\nconst groups=groupedProjects(["
    script += "{root:'C:/Users/Adam/.codex/worktrees'},"
    script += "{root:'C:/Users/Adam/.codex/worktrees/repo-a'},"
    script += "{root:'C:/repo-a',git_common_dir:'C:/repo-a/.git',is_worktree:false},"
    script += "{root:'C:/repo-a/worktrees/linked',git_common_dir:'C:/repo-a/.git',is_worktree:true}"
    script += "]); console.log(JSON.stringify(groups.map(g=>({identity:projectIdentity(g),variants:g.variants.length,root:g.root}))))\n"
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=10, check=True)
    groups = json.loads(result.stdout)
    assert groups == [
        {"identity": "C:/Users/Adam/.codex/worktrees", "variants": 1, "root": "C:/Users/Adam/.codex/worktrees"},
        {"identity": "C:/Users/Adam/.codex/worktrees/repo-a", "variants": 1, "root": "C:/Users/Adam/.codex/worktrees/repo-a"},
        {"identity": "C:/repo-a/.git", "variants": 2, "root": "C:/repo-a"},
    ]
    assert "includes('worktree')" not in DASHBOARD_HTML[render_start:render_end]
    assert "x.is_worktree===true" in DASHBOARD_HTML[render_start:render_end]
