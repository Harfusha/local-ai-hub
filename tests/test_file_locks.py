"""Lock files must not follow links into unrelated files."""

import os
import subprocess

import pytest

from local_ai_hub.file_locks import exclusive_file_update


def test_lock_file_rejects_hardlink_without_modifying_target(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.write_bytes(b"")
    try:
        os.link(outside, repo / "task.lock")
    except OSError as exc:
        pytest.skip(f"Hard links unavailable: {exc}")
    with pytest.raises((OSError, ValueError)):
        with exclusive_file_update(repo / "task"):
            pytest.fail("A hard-linked lock must not be acquired")
    assert outside.read_bytes() == b""


def test_lock_file_rejects_symlink_without_modifying_target(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.write_bytes(b"")
    try:
        (repo / "task.lock").symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"File symlinks unavailable: {exc}")
    with pytest.raises((OSError, ValueError)):
        with exclusive_file_update(repo / "task"):
            pytest.fail("A symlinked lock must not be acquired")
    assert outside.read_bytes() == b""


@pytest.mark.skipif(os.name != "nt", reason="Windows junction behavior")
def test_lock_file_rejects_directory_junction(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_bytes(b"unchanged")
    env = {**os.environ, "LAH_RACE_LINK": str(repo / "task.lock"), "LAH_RACE_TARGET": str(outside)}
    created = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command",
         "New-Item -ItemType Junction -Path $env:LAH_RACE_LINK -Target $env:LAH_RACE_TARGET | Out-Null"],
        env=env, capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if created.returncode:
        pytest.skip("Cannot create a Windows junction in this test environment")
    with pytest.raises((OSError, ValueError)):
        with exclusive_file_update(repo / "task"):
            pytest.fail("A junction must not be acquired as a lock")
    assert sentinel.read_bytes() == b"unchanged"


def test_regular_lock_still_supports_reentrant_calls(tmp_path):
    path = tmp_path / "task"
    with exclusive_file_update(path, reentrant=True):
        with exclusive_file_update(path, reentrant=True):
            assert (tmp_path / "task.lock").is_file()


@pytest.mark.skipif(os.name != "nt", reason="Windows share-delete behavior")
def test_open_windows_lock_cannot_be_renamed(tmp_path):
    path = tmp_path / "task"
    lock = tmp_path / "task.lock"
    with exclusive_file_update(path):
        with pytest.raises(OSError):
            lock.rename(tmp_path / "moved.lock")
    assert lock.is_file()
