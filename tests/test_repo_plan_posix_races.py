"""Adversarial POSIX path changes during repository plan publication."""

import errno
import multiprocessing
import os
from pathlib import Path

import pytest

from local_ai_hub.repo_plan.schema_validation import RepoPlanValidationError
from local_ai_hub.repo_plan.storage import RepoPlanStorage
from local_ai_hub.repo_plan.agent_bridge import _pinned_pending_directory
from local_ai_hub import file_locks
from local_ai_hub.file_locks import exclusive_file_update


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory guard required")
def test_nested_pending_directory_requires_identical_root(tmp_path: Path) -> None:
    root = tmp_path / "project"
    parent = root / "pending"
    parent.mkdir(parents=True)
    with _pinned_pending_directory(root, parent):
        with _pinned_pending_directory(root, parent):
            pass
        with pytest.raises(ValueError, match="root differs"):
            with _pinned_pending_directory(tmp_path, parent):
                pytest.fail("different root must be rejected")


def _hold_file_update_lock(target: str, ready, release) -> None:
    path = Path(target)
    parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with exclusive_file_update(path, timeout=2, parent_fd=parent_fd):
            ready.set()
            if not release.wait(20):
                raise TimeoutError("test did not release the lock")
    finally:
        os.close(parent_fd)


def _try_file_update_lock(target: str, result) -> None:
    path = Path(target)
    parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        try:
            with exclusive_file_update(path, timeout=0.25, parent_fd=parent_fd):
                result.put("acquired")
        except TimeoutError:
            result.put("blocked")
    finally:
        os.close(parent_fd)


@pytest.mark.skipif(os.name == "nt", reason="POSIX flock semantics required")
def test_replacing_lock_file_does_not_split_two_writers(tmp_path: Path) -> None:
    ctx = multiprocessing.get_context("spawn")
    target = tmp_path / "plan"
    ready = ctx.Event()
    release = ctx.Event()
    result = ctx.Queue()
    holder = ctx.Process(target=_hold_file_update_lock, args=(str(target), ready, release))
    contender = ctx.Process(target=_try_file_update_lock, args=(str(target), result))
    holder.start()
    try:
        assert ready.wait(5), "first writer failed to acquire its lock"
        target.with_name(target.name + ".lock").rename(tmp_path / "replaced.lock")
        contender.start()
        contender.join(5)
        assert not contender.is_alive(), "second writer did not complete"
        assert contender.exitcode == 0
        assert result.get(timeout=2) == "blocked"
    finally:
        release.set()
        holder.join(5)
        if holder.is_alive():
            holder.terminate()
            holder.join(5)
        if contender.pid is not None and contender.is_alive():
            contender.terminate()
            contender.join(5)
        result.close()


@pytest.mark.skipif(os.name == "nt", reason="POSIX flock semantics required")
def test_nested_different_locks_share_the_parent_guard(tmp_path: Path) -> None:
    parent_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with exclusive_file_update(tmp_path / "first", timeout=0.5, parent_fd=parent_fd):
            with exclusive_file_update(tmp_path / "second", timeout=0.5, parent_fd=parent_fd):
                pass
    finally:
        os.close(parent_fd)


@pytest.mark.skipif(os.name == "nt", reason="POSIX flock semantics required")
def test_reentrant_file_lock_cannot_skip_requested_parent_guard(tmp_path: Path) -> None:
    target = tmp_path / "plan"
    parent_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with exclusive_file_update(target, timeout=0.5, reentrant=True):
            with pytest.raises(RuntimeError, match="cannot upgrade"):
                with exclusive_file_update(target, timeout=0.5, reentrant=True, parent_fd=parent_fd):
                    pytest.fail("parent guard must not be skipped")
    finally:
        os.close(parent_fd)


@pytest.mark.skipif(os.name == "nt", reason="POSIX flock semantics required")
def test_parent_guard_is_released_when_lock_file_open_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with monkeypatch.context() as scoped:
            def fail(*_args, **_kwargs):
                raise OSError(errno.EIO, "injected lock open failure")

            scoped.setattr(file_locks, "_open_lock_file", fail)
            with pytest.raises(OSError, match="injected lock open failure"):
                with exclusive_file_update(tmp_path / "first", timeout=0.5, parent_fd=parent_fd):
                    pytest.fail("lock must not be acquired")
        with exclusive_file_update(tmp_path / "second", timeout=0.5, parent_fd=parent_fd):
            pass
        ctx = multiprocessing.get_context("spawn")
        result = ctx.Queue()
        contender = ctx.Process(target=_try_file_update_lock, args=(str(tmp_path / "third"), result))
        contender.start()
        try:
            contender.join(5)
            assert not contender.is_alive(), "subsequent writer did not complete"
            assert contender.exitcode == 0
            assert result.get(timeout=2) == "acquired"
        finally:
            if contender.is_alive():
                contender.terminate()
                contender.join(5)
            result.close()
    finally:
        os.close(parent_fd)


@pytest.mark.skipif(os.name == "nt", reason="POSIX flock semantics required")
def test_unsupported_parent_flock_uses_file_lock_and_reports_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import fcntl

    parent_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    original_flock = fcntl.flock
    first = True

    def unsupported_once(descriptor, operation):
        nonlocal first
        if first:
            first = False
            raise OSError(errno.EBADF, "directory flock unsupported")
        return original_flock(descriptor, operation)

    monkeypatch.setattr(fcntl, "flock", unsupported_once)
    try:
        target = tmp_path / "plan"
        with exclusive_file_update(target, timeout=0.5, reentrant=True, parent_fd=parent_fd):
            with exclusive_file_update(target, timeout=0.5, reentrant=True, parent_fd=parent_fd):
                pass
        assert "replacing its name may split concurrent writers" in caplog.text
    finally:
        os.close(parent_fd)


@pytest.mark.skipif(os.name == "nt", reason="POSIX flock semantics required")
def test_parent_guard_permanent_error_is_not_a_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import fcntl

    parent_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with monkeypatch.context() as scoped:
            def fail(*_args):
                raise OSError(errno.EIO, "injected directory lock error")

            scoped.setattr(fcntl, "flock", fail)
            with pytest.raises(OSError) as error:
                with exclusive_file_update(tmp_path / "target", timeout=0, parent_fd=parent_fd):
                    pytest.fail("lock must not be acquired")
            assert error.value.errno == errno.EIO
        with exclusive_file_update(tmp_path / "target", timeout=0.5, parent_fd=parent_fd):
            pass
    finally:
        os.close(parent_fd)


@pytest.mark.skipif(os.name == "nt", reason="POSIX flock semantics required")
def test_flock_permanent_error_is_not_reported_as_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import fcntl

    def fail(*_args):
        raise OSError(errno.EIO, "filesystem error")

    monkeypatch.setattr(fcntl, "flock", fail)
    with pytest.raises(OSError) as error:
        with exclusive_file_update(tmp_path / "target", timeout=0):
            pytest.fail("lock must not be acquired")
    assert error.value.errno == errno.EIO


@pytest.mark.skipif(os.name == "nt", reason="POSIX flock semantics required")
def test_flock_contention_remains_a_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import fcntl

    def busy(*_args):
        raise OSError(errno.EWOULDBLOCK, "busy")

    monkeypatch.setattr(fcntl, "flock", busy)
    with pytest.raises(TimeoutError, match="file update lock timed out"):
        with exclusive_file_update(tmp_path / "target", timeout=0):
            pytest.fail("lock must not be acquired")


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory descriptor semantics required")
def test_read_rejects_final_symlink_swapped_after_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    target = root / "docs" / "plan.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"{}")
    outside = tmp_path / "outside.json"
    outside.write_bytes(b"not a project plan")
    real_open = os.open
    swapped = False

    def open_after_swap(path, flags, *args, **kwargs):
        nonlocal swapped
        if path == target.name and kwargs.get("dir_fd") is not None and not swapped:
            target.unlink()
            target.symlink_to(outside)
            swapped = True
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", open_after_swap)
    with pytest.raises((OSError, RepoPlanValidationError)):
        RepoPlanStorage(root).read_plan_file("docs/plan.json")
    assert swapped
    assert outside.read_bytes() == b"not a project plan"


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory descriptor semantics required")
def test_parent_symlink_swap_cannot_overwrite_unrelated_outside_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    target_dir = root / "docs"
    target_dir.mkdir(parents=True)
    target = target_dir / "plan.json"
    target.write_bytes(b"original")
    displaced = root / "displaced-docs"
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / target.name
    sentinel.write_bytes(b"outside")
    real_replace = os.replace
    swapped = False

    def replace_after_swap(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
        nonlocal swapped
        if src_dir_fd is not None and not swapped:
            target_dir.rename(displaced)
            target_dir.symlink_to(outside, target_is_directory=True)
            swapped = True
        return real_replace(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

    monkeypatch.setattr(os, "replace", replace_after_swap)
    try:
        RepoPlanStorage(root)._atomic_write_bytes(target, b"candidate")
    except (OSError, RepoPlanValidationError):
        pass

    assert swapped, "the symlink substitution must occur during publication"
    assert sentinel.read_bytes() == b"outside"


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory descriptor semantics required")
def test_publishing_to_moved_directory_preserves_unrelated_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    target_dir = root / "docs"
    target_dir.mkdir(parents=True)
    target = target_dir / "plan.json"
    target.write_bytes(b"original")
    outside = tmp_path / "outside"
    outside.mkdir()
    unrelated = outside / "unrelated.txt"
    unrelated.write_bytes(b"untouched")
    moved = outside / "moved"
    real_replace = os.replace
    move_attempted = False
    moved_during_publication = False
    published = False

    def replace_after_move(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
        nonlocal move_attempted, moved_during_publication
        if src_dir_fd is not None and not move_attempted:
            move_attempted = True
            target_dir.rename(moved)
            moved_during_publication = True
        return real_replace(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

    monkeypatch.setattr(os, "replace", replace_after_move)
    try:
        RepoPlanStorage(root)._atomic_write_bytes(target, b"candidate")
        published = True
    except (OSError, RepoPlanValidationError):
        pass

    assert move_attempted, "the adversarial move must be attempted during publication"
    if moved_during_publication:
        assert (moved / target.name).read_bytes() == (b"candidate" if published else b"original")
    else:
        assert target.read_bytes() == b"original"
        assert not moved.exists()
    assert unrelated.read_bytes() == b"untouched"


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory descriptor semantics required")
def test_publishing_to_moved_repository_preserves_unrelated_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    target = root / "docs" / "plan.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"original")
    outside = tmp_path / "outside"
    outside.mkdir()
    unrelated = outside / "unrelated.txt"
    unrelated.write_bytes(b"untouched")
    moved = outside / "moved-repo"
    real_replace = os.replace
    move_attempted = False
    moved_during_publication = False
    published = False

    def replace_after_move(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
        nonlocal move_attempted, moved_during_publication
        if src_dir_fd is not None and not move_attempted:
            move_attempted = True
            root.rename(moved)
            moved_during_publication = True
        return real_replace(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

    monkeypatch.setattr(os, "replace", replace_after_move)
    try:
        RepoPlanStorage(root)._atomic_write_bytes(target, b"candidate")
        published = True
    except (OSError, RepoPlanValidationError):
        pass

    assert move_attempted, "the adversarial move must be attempted during publication"
    if moved_during_publication:
        assert (moved / "docs" / target.name).read_bytes() == (b"candidate" if published else b"original")
    else:
        assert target.read_bytes() == b"original"
        assert not moved.exists()
    assert unrelated.read_bytes() == b"untouched"
