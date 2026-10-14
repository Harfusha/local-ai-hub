from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from local_ai_hub.commands import CommandBroker, simulate_patch


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init")
    _git(path, "config", "user.name", "Patch Test")
    _git(path, "config", "user.email", "patch@example.invalid")
    _git(path, "config", "commit.gpgsign", "false")
    (path / "file1.txt").write_text("line 1\nline 2\nline 3\n", encoding="utf-8")
    _git(path, "add", "file1.txt")
    _git(path, "commit", "-m", "init")
    return path


def test_simulate_patch_valid_diff(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    patch = (
        "--- a/file1.txt\n"
        "+++ b/file1.txt\n"
        "@@ -1,3 +1,3 @@\n"
        " line 1\n"
        "-line 2\n"
        "+line 2 modified\n"
        " line 3\n"
    )

    sim = simulate_patch(repo, patch)

    assert sim["valid"] is True
    assert "file1.txt" in sim["files"]
    assert sim["additions"] == 1
    assert sim["deletions"] == 1
    assert sim["error"] is None

    # Guarantee zero mutation on disk
    assert (repo / "file1.txt").read_text(encoding="utf-8") == "line 1\nline 2\nline 3\n"
    assert _git(repo, "status", "--porcelain") == ""


def test_simulate_patch_conflict_reports_invalid(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    conflict_patch = (
        "--- a/file1.txt\n"
        "+++ b/file1.txt\n"
        "@@ -1,3 +1,3 @@\n"
        " line 1\n"
        "-nonexistent line\n"
        "+line replaced\n"
        " line 3\n"
    )

    sim = simulate_patch(repo, conflict_patch)

    assert sim["valid"] is False
    assert sim["error"] is not None
    assert len(sim["error"]) > 0

    # Guarantee zero mutation on disk
    assert (repo / "file1.txt").read_text(encoding="utf-8") == "line 1\nline 2\nline 3\n"
    assert _git(repo, "status", "--porcelain") == ""


def test_simulate_patch_whitespace_tolerance(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    _git(repo, "config", "core.autocrlf", "false")
    (repo / "file1.txt").write_bytes(b"line 1\r\nline 2\r\nline 3\r\n")
    _git(repo, "add", "file1.txt")
    _git(repo, "commit", "-m", "crlf commit")

    # Patch has LF endings
    diff = (
        "--- a/file1.txt\n"
        "+++ b/file1.txt\n"
        "@@ -1,3 +1,3 @@\n"
        " line 1\n"
        "-line 2\n"
        "+line 2 fuzzy\n"
        " line 3\n"
    )

    sim = simulate_patch(repo, diff, allow_whitespace_fallback=True)

    assert sim["valid"] is True
    assert sim["whitespace_fallback_used"] is True
    assert (repo / "file1.txt").read_bytes() == b"line 1\r\nline 2\r\nline 3\r\n"


def test_simulate_patch_empty_input(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")

    sim = simulate_patch(repo, "")
    assert sim["valid"] is False
    assert "empty" in sim["error"].lower()

    sim_whitespace = simulate_patch(repo, "   \n\t ")
    assert sim_whitespace["valid"] is False
    assert "empty" in sim_whitespace["error"].lower()


def test_patch_and_verify_dry_run_mode(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    patch = (
        "--- a/file1.txt\n"
        "+++ b/file1.txt\n"
        "@@ -1,3 +1,3 @@\n"
        " line 1\n"
        "-line 2\n"
        "+line 2 dryrun\n"
        " line 3\n"
    )

    cfg = {"server": {"state_dir": str(tmp_path / "state")}}
    broker = CommandBroker(cfg)
    result = broker.patch_and_verify(
        patch=patch,
        cwd=repo,
        tenant="test-tenant",
        dry_run=True,
    )

    assert result["dry_run"] is True
    assert result["success"] is True
    assert result["valid"] is True
    assert "file1.txt" in result["files"]
    assert result["additions"] == 1
    assert result["deletions"] == 1

    # In dry-run mode, disk remains completely untouched
    assert (repo / "file1.txt").read_text(encoding="utf-8") == "line 1\nline 2\nline 3\n"
    assert _git(repo, "status", "--porcelain") == ""
