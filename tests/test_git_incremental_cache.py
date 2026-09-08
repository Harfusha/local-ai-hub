from __future__ import annotations

import subprocess
from pathlib import Path

from local_ai_hub.process_utils import hidden_run_kwargs
from local_ai_hub.repo_tools import RepositoryTools


def run_git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        timeout=10.0,
        **hidden_run_kwargs(text=True),
    )
    return completed.stdout


def write_file(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def fail_if_byte_hashed(path: Path) -> str:
    raise AssertionError(f"snapshot must not byte-hash: {path}")


def write_and_commit(repo: Path, name: str, content: str) -> None:
    write_file(repo / name, content)
    run_git(repo, "add", "--", name)
    run_git(repo, "commit", "-m", f"add {name}")


def make_git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init")
    run_git(repo, "config", "user.name", "Snapshot Test")
    run_git(repo, "config", "user.email", "snapshot@example.test")
    for name in (
        "clean.py",
        "staged.py",
        "modified.py",
        "mixed.py",
        "deleted.py",
        "rename.py",
    ):
        write_and_commit(repo, name, f"value = {name!r}\n")
    return repo


def make_tools() -> RepositoryTools:
    return RepositoryTools(
        {
            "rag": {},
            "search": {
                "prefer_git_files": True,
                "git_files_timeout_seconds": 5,
            },
        }
    )


def test_git_snapshot_separates_clean_dirty_and_untracked_paths(tmp_path: Path, monkeypatch):
    repo = make_git_repo(tmp_path)

    write_file(repo / "staged.py", "value = 'staged update'\n")
    run_git(repo, "add", "--", "staged.py")
    write_file(repo / "modified.py", "value = 'worktree update'\n")
    write_file(repo / "mixed.py", "value = 'index update'\n")
    run_git(repo, "add", "--", "mixed.py")
    write_file(repo / "mixed.py", "value = 'worktree update'\n")
    write_file(repo / "untracked.py", "value = 'new'\n")
    run_git(repo, "rm", "--", "deleted.py")
    run_git(repo, "mv", "rename.py", "renamed.py")

    tools = make_tools()
    monkeypatch.setattr(tools, "_hash_file_only", fail_if_byte_hashed)
    snapshot = tools.git_snapshot(str(repo))

    assert snapshot.blobs["clean.py"].state == "clean"
    assert snapshot.blobs["staged.py"].state == "staged"
    assert snapshot.blobs["modified.py"].state == "modified"
    assert snapshot.blobs["mixed.py"].state == "staged_and_worktree_modified"
    assert snapshot.blobs["untracked.py"].state == "untracked"
    assert snapshot.blobs["deleted.py"].state == "deleted"
    assert snapshot.deleted == ("deleted.py",)
    assert snapshot.renames == {"renamed.py": "rename.py"}


def test_git_snapshot_clean_blob_uses_git_oid_identity(tmp_path: Path, monkeypatch):
    repo = make_git_repo(tmp_path)
    tools = make_tools()
    monkeypatch.setattr(tools, "_hash_file_only", fail_if_byte_hashed)
    snapshot = tools.git_snapshot(str(repo))
    blob = snapshot.blobs["clean.py"]
    expected_oid = run_git(repo, "rev-parse", "HEAD:clean.py").strip()

    assert blob.state == "clean"
    assert blob.oid == expected_oid
    assert blob.identity == f"git:{expected_oid}"


# Symlink and submodule-like entries remain deferred because their Git/worktree
# behavior is platform-dependent; core porcelain-v2 parsing above is portable.
