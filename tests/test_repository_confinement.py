from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from local_ai_hub.agent_task_models import _canonical_repository_root
from local_ai_hub.http_server import _strict_root_path
from local_ai_hub.repository_scope import (
    RepositoryScopeError,
    authorized_repository_root,
    canonical_repository_root,
    confine_child_path,
)


def test_canonical_repository_root_accepts_valid_directory(tmp_path: Path):
    repo = tmp_path / "valid_repo"
    repo.mkdir()
    res = canonical_repository_root(str(repo))
    assert res == repo.resolve()


def test_canonical_repository_root_rejects_missing_or_file(tmp_path: Path):
    missing = tmp_path / "nonexistent"
    with pytest.raises(RepositoryScopeError):
        canonical_repository_root(str(missing))

    a_file = tmp_path / "some_file.txt"
    a_file.write_text("hello", encoding="utf-8")
    with pytest.raises(RepositoryScopeError):
        canonical_repository_root(str(a_file))


def test_canonical_repository_root_rejects_traversal_and_null_bytes(tmp_path: Path):
    with pytest.raises(RepositoryScopeError):
        canonical_repository_root(f"{tmp_path}\x00/bad")

    with pytest.raises(RepositoryScopeError):
        canonical_repository_root("")

    with pytest.raises(RepositoryScopeError):
        canonical_repository_root("   ")


def test_confine_child_path_accepts_valid_children(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    src = repo / "src"
    src.mkdir()
    f = src / "main.py"
    f.write_text("print(1)", encoding="utf-8")

    assert confine_child_path(repo, "src/main.py") == f.resolve()
    assert confine_child_path(repo, "src") == src.resolve()


def test_confine_child_path_rejects_traversals(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("secret", encoding="utf-8")

    with pytest.raises(RepositoryScopeError, match="escapes"):
        confine_child_path(repo, "../secret.txt")

    with pytest.raises(RepositoryScopeError, match="escapes"):
        confine_child_path(repo, "../../etc/passwd")

    with pytest.raises(RepositoryScopeError, match="invalid|null"):
        confine_child_path(repo, "src/\x00evil.py")


def test_authorized_repository_root_enforces_allowlist(tmp_path: Path):
    allowed_dir = tmp_path / "allowed_repo"
    allowed_dir.mkdir()
    denied_dir = tmp_path / "denied_repo"
    denied_dir.mkdir()

    cfg = {"security": {"allowed_roots": [str(allowed_dir)]}}

    assert authorized_repository_root(cfg, str(allowed_dir)) == str(allowed_dir.resolve())

    with pytest.raises(RepositoryScopeError, match="outside allowed_roots"):
        authorized_repository_root(cfg, str(denied_dir))


def test_junction_rejection_on_windows(tmp_path: Path):
    if sys.platform != "win32":
        pytest.skip("Junction test is Windows specific")

    real_repo = tmp_path / "real_repo"
    real_repo.mkdir()
    junction_repo = tmp_path / "junction_repo"

    cmd = ["cmd", "/c", "mklink", "/j", str(junction_repo), str(real_repo)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        pytest.skip(f"mklink /j failed or not permitted: {proc.stderr}")

    try:
        # canonical_repository_root must reject the junction
        with pytest.raises(RepositoryScopeError, match="symlinks or junctions"):
            canonical_repository_root(str(junction_repo))

        # _canonical_repository_root must reject the junction
        with pytest.raises(ValueError, match="symlinks or junctions"):
            _canonical_repository_root(str(junction_repo))

        # _strict_root_path must reject the junction
        with pytest.raises(ValueError, match="symlink or junction"):
            _strict_root_path(str(junction_repo))
    finally:
        subprocess.run(["cmd", "/c", "rmdir", str(junction_repo)], capture_output=True)
