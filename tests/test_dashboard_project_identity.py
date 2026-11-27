from __future__ import annotations

from pathlib import Path
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
