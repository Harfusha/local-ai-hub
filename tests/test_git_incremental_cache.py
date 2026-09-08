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


def test_git_snapshot_reuses_cached_index_probe(tmp_path: Path, monkeypatch):
    repo = make_git_repo(tmp_path)
    tools = make_tools()
    calls: list[list[str]] = []
    real_run = subprocess.run

    def counted(args, *extra, **kwargs):
        calls.append([str(item) for item in args])
        return real_run(args, *extra, **kwargs)

    monkeypatch.setattr("local_ai_hub.repo_tools.subprocess.run", counted)
    first = tools.git_snapshot(str(repo))
    second = tools.git_snapshot(str(repo))

    assert first.blobs == second.blobs
    assert sum("ls-files" in command for command in calls) == 1


def test_same_size_index_replacement_changes_signature(tmp_path: Path):
    repo = tmp_path / "repo"
    alternate = tmp_path / "alternate"
    repo.mkdir()
    alternate.mkdir()
    run_git(repo, "init")
    run_git(repo, "config", "user.name", "Snapshot Test")
    run_git(repo, "config", "user.email", "snapshot@example.test")
    write_and_commit(repo, "clean.py", "value = 'clean.py'\n")
    run_git(alternate, "init")
    run_git(alternate, "config", "user.name", "Snapshot Test")
    run_git(alternate, "config", "user.email", "snapshot@example.test")
    write_and_commit(alternate, "clean.py", "value = 'other.py'\n")
    tools = make_tools()

    first = tools.git_snapshot(str(repo))
    first_size = Path(first.index_path).stat().st_size

    alternate_snapshot = tools.git_snapshot(str(alternate))
    replacement = Path(alternate_snapshot.index_path).read_bytes()
    assert len(replacement) == first_size
    Path(first.index_path).write_bytes(replacement)

    second = tools.git_snapshot(str(repo))
    second_size = Path(second.index_path).stat().st_size

    assert first_size == second_size
    assert first.index_signature != second.index_signature
    assert tools._git_index_cache_identity(first.index_signature) != tools._git_index_cache_identity(second.index_signature)
    assert first.blobs["clean.py"].oid != second.blobs["clean.py"].oid


def test_git_snapshot_degrades_on_timeout_and_malformed_output(tmp_path: Path, monkeypatch):
    repo = make_git_repo(tmp_path)
    tools = make_tools()

    def timed_out(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 0.01)

    monkeypatch.setattr("local_ai_hub.repo_tools.subprocess.run", timed_out)
    timed_snapshot = tools.git_snapshot(str(repo))
    assert timed_snapshot.degraded is True
    assert timed_snapshot.blobs == {}

    tools = make_tools()
    monkeypatch.setattr(
        "local_ai_hub.repo_tools.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout=b"malformed\n", stderr=b""),
    )
    malformed_snapshot = tools.git_snapshot(str(repo))
    assert malformed_snapshot.degraded is True
    assert tools.git_blob_map(str(repo)) == {}


def test_git_snapshot_identity_is_worktree_specific(tmp_path: Path):
    repo = make_git_repo(tmp_path)
    worktree = tmp_path / "linked-worktree"
    run_git(repo, "worktree", "add", str(worktree), "HEAD")
    tools = make_tools()

    main_snapshot = tools.git_snapshot(str(repo))
    linked_snapshot = tools.git_snapshot(str(worktree))

    assert main_snapshot.degraded is False
    assert linked_snapshot.degraded is False
    assert main_snapshot.common_dir == linked_snapshot.common_dir
    assert main_snapshot.worktree_root != linked_snapshot.worktree_root
    assert main_snapshot.git_dir != linked_snapshot.git_dir
    assert main_snapshot.index_path != linked_snapshot.index_path
    assert tools.git_blob_map(str(repo)) == tools.git_blob_map(str(worktree))


# Symlink and submodule-like entries remain deferred because their Git/worktree
# behavior is platform-dependent; core porcelain-v2 parsing above is portable.
