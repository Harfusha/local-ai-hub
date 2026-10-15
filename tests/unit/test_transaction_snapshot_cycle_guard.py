from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path
import pytest

from local_ai_hub import command_transactions


@pytest.mark.parametrize("limit", [0, -1, True, 513, 1.5, "64"])
def test_invalid_depth_is_rejected_before_snapshot_operations(tmp_path, monkeypatch, limit):
    monkeypatch.setattr(command_transactions, "_git_output", lambda *args: pytest.fail("invalid limit reached Git"))
    with pytest.raises(ValueError, match="maximum depth must be an integer"):
        command_transactions.create_private_transaction_snapshot(tmp_path, tmp_path / "snapshot", max_depth=limit)


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def _init_repo(source: Path) -> None:
    source.mkdir(parents=True, exist_ok=True)
    _git(source, "init", "--quiet")
    _git(source, "config", "user.name", "Test Agent")
    _git(source, "config", "user.email", "agent@example.com")
    (source / "root_file.txt").write_text("hello\n", encoding="utf-8")
    _git(source, "add", "root_file.txt")
    _git(source, "commit", "-m", "initial", "--quiet")


def test_tree_manifest_depth_limit_rejection(tmp_path: Path):
    source = tmp_path / "source_repo"
    _init_repo(source)

    # Create directories nested 6 levels deep: a/b/c/d/e/f
    deep_dir = source / "a" / "b" / "c" / "d" / "e" / "f"
    deep_dir.mkdir(parents=True)
    (deep_dir / "leaf.txt").write_text("deep", encoding="utf-8")
    _git(source, "add", ".")
    _git(source, "commit", "-m", "deep tree", "--quiet")

    # With max_depth=3, scanning must raise ValueError for exceeding depth limit
    with pytest.raises(ValueError, match="maximum directory depth exceeded"):
        command_transactions._tree_manifest(source, max_depth=3)


def test_tree_manifest_depth_limit_allowed_when_within_bound(tmp_path: Path):
    source = tmp_path / "source_repo"
    _init_repo(source)

    deep_dir = source / "a" / "b"
    deep_dir.mkdir(parents=True)
    (deep_dir / "leaf.txt").write_text("ok", encoding="utf-8")

    manifest = command_transactions._tree_manifest(source, max_depth=5)
    assert "a/b/leaf.txt" in manifest


def test_create_private_transaction_snapshot_enforces_depth_limit(tmp_path: Path):
    source = tmp_path / "source_repo"
    _init_repo(source)

    deep_dir = source / "d1" / "d2" / "d3" / "d4"
    deep_dir.mkdir(parents=True)
    (deep_dir / "file.txt").write_text("content", encoding="utf-8")
    _git(source, "add", ".")
    _git(source, "commit", "-m", "commit deep", "--quiet")

    dest = tmp_path / "dest_snapshot"
    with pytest.raises(ValueError, match="maximum directory depth exceeded"):
        command_transactions.create_private_transaction_snapshot(source, dest, max_depth=3)


def test_tree_manifest_detects_directory_cycle(tmp_path: Path, monkeypatch):
    source = tmp_path / "source_repo"
    _init_repo(source)

    dir_a = source / "sub_a"
    dir_a.mkdir()

    # Simulate a directory cycle where directory scanner reports an already visited directory inode/path
    real_stat = os.stat

    class FakeDirEntry:
        def __init__(self, name: str, path: str):
            self.name = name
            self.path = path

        def is_symlink(self):
            return False

        def stat(self, follow_symlinks=False):
            return real_stat(self.path, follow_symlinks=follow_symlinks)

    # Monkeypatch os.scandir in sub_a to re-yield sub_a
    original_scandir = os.scandir

    class FakeScandir:
        def __init__(self, entries):
            self.entries = entries

        def __enter__(self):
            return iter(self.entries)

        def __exit__(self, *args):
            pass

    def cyclic_scandir(path_str):
        p = Path(path_str).resolve()
        if p == dir_a.resolve():
            # Returns sub_a inside sub_a with the exact same device/inode or path
            return FakeScandir([FakeDirEntry("loop_a", str(dir_a))])
        return original_scandir(path_str)

    monkeypatch.setattr(os, "scandir", cyclic_scandir)

    with pytest.raises(ValueError, match="directory cycle detected"):
        command_transactions._tree_manifest(source, max_depth=10)
