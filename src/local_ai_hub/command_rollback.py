from __future__ import annotations

import ctypes
import errno
import hashlib
import ntpath
import os
import stat
import subprocess
import sys
import tempfile
import uuid
from functools import wraps
from pathlib import Path
from typing import Any

from .command_patch_paths import (
    _patch_relative_parts,
    _patch_target_path,
)
from .command_transactions import (
    PatchFileSnapshot,
    PatchTargetsSnapshot,
    RollbackFileSnapshot,
    RollbackPostimage,
    RollbackSnapshot,
)
from .process_utils import hidden_run_kwargs

__all__ = [
    "_MAX_ROLLBACK_PATHS",
    "_MAX_ROLLBACK_FILE_BYTES",
    "_MAX_ROLLBACK_TOTAL_BYTES",
    "_MAX_ROLLBACK_METADATA_BYTES",
    "_MAX_ROLLBACK_PATCH_BYTES",
    "_RollbackPostimageChanged",
    "_snapshot_patch_targets",
    "_assert_patch_root",
    "_hash_patch_target",
    "_restore_patch_targets",
    "_get_windows_dacl",
    "_set_windows_dacl",
    "_set_windows_dacl_path",
    "_restore_windows_file_attributes",
    "_restore_windows_file_times",
    "_restore_windows_atime",
    "_delete_windows_handle",
    "_rename_windows_handle",
    "_windows_dacl_bytes",
    "_acquire_rollback_root",
    "_close_rollback_root",
    "_rollback_snapshot_open_flags",
    "_open_rollback_snapshot_file",
    "_open_rollback_parent_handle",
    "_open_rollback_relative_handle",
    "_windows_handle_attributes",
    "_windows_handle_identity",
    "_rollback_root_identity",
    "_snapshot_rollback_scope",
    "_rename_exchange_at",
    "_rename_noreplace_at",
    "_restore_existing_rollback_leaf",
    "_restore_rollback_scope",
    "_rollback_postimage_at",
    "_capture_rollback_postimages",
    "_same_rollback_postimage_after_owned_rename",
    "_patch_write_paths",
    "simulate_patch",
    "patch_dry_run",
    "_stable_rollback_status",
]

_MAX_ROLLBACK_PATHS = 128
_MAX_ROLLBACK_FILE_BYTES = 16 * 1024 * 1024
_MAX_ROLLBACK_TOTAL_BYTES = 64 * 1024 * 1024
_MAX_ROLLBACK_METADATA_BYTES = 1024 * 1024
_MAX_ROLLBACK_PATCH_BYTES = 64 * 1024 * 1024


def _snapshot_patch_targets(
    root: Path,
    raw_paths: list[str],
    *,
    retain_contents: bool = True,
    max_file_bytes: int | None = None,
    max_total_bytes: int | None = None,
) -> PatchTargetsSnapshot:
    if not raw_paths or len(raw_paths) > _MAX_ROLLBACK_PATHS:
        raise ValueError("patch must affect between 1 and 128 files for safe rollback")
    file_limit = _MAX_ROLLBACK_FILE_BYTES if max_file_bytes is None else max_file_bytes
    total_limit = _MAX_ROLLBACK_TOTAL_BYTES if max_total_bytes is None else max_total_bytes
    root = root.resolve(strict=True)
    root_info = root.stat()
    snapshots: dict[str, PatchFileSnapshot] = {}
    total_bytes = 0
    total_metadata_bytes = 0
    for raw in raw_paths:
        parts = _patch_relative_parts(raw)
        target = _patch_target_path(root, parts)
        relative = Path(*parts).as_posix()
        if relative in snapshots:
            continue
        absent_parents: list[str] = []
        parent = root
        parent_missing = False
        for part in parts[:-1]:
            parent = parent / part
            if parent_missing:
                absent_parents.append(parent.relative_to(root).as_posix())
                continue
            try:
                parent.lstat()
            except FileNotFoundError:
                parent_missing = True
                absent_parents.append(parent.relative_to(root).as_posix())
        try:
            info = target.lstat()
        except FileNotFoundError:
            snapshots[relative] = PatchFileSnapshot(None, None, None, None, created_parent_dirs=tuple(absent_parents))
            continue
        if stat.S_ISLNK(info.st_mode):
            raise ValueError(f"patch target is already a symlink: {relative}")
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"patch target is not a regular file: {relative}")
        if info.st_size > file_limit or total_bytes + info.st_size > total_limit:
            raise ValueError("patch rollback snapshot exceeds the configured per-file or aggregate limit")
        fd = os.open(target, _rollback_snapshot_open_flags())
        try:
            opened = os.fstat(fd)
            # Path and descriptor timestamp values can differ on Windows even
            # when both identify the same stable file. Pin identity here; the
            # descriptor metadata is checked for stability across the read below.
            if not stat.S_ISREG(opened.st_mode) or (
                opened.st_dev,
                opened.st_ino,
                opened.st_size,
            ) != (
                info.st_dev,
                info.st_ino,
                info.st_size,
            ):
                raise ValueError(f"patch target changed during snapshot before read: {relative}")
            chunks: list[bytes] = []
            digest = hashlib.sha256()
            read_size = 0
            while True:
                chunk = os.read(fd, min(64 * 1024, file_limit - read_size + 1))
                if not chunk:
                    break
                read_size += len(chunk)
                if read_size > file_limit or total_bytes + read_size > total_limit:
                    raise ValueError(f"patch target exceeds rollback snapshot limit: {relative}")
                digest.update(chunk)
                if retain_contents:
                    chunks.append(chunk)
            content = b"".join(chunks) if retain_contents else None
            final = os.fstat(fd)
            if (
                read_size != final.st_size
                or (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns)
                != (final.st_size, final.st_mtime_ns, final.st_ctime_ns)
            ):
                raise ValueError(
                    f"patch target changed during snapshot after read: {relative} "
                    f"(bytes={read_size}, opened_size={opened.st_size}, final_size={final.st_size})"
                )
            xattrs: dict[str, bytes] = {}
            if os.name != "nt" and hasattr(os, "listxattr"):
                for attr_name in os.listxattr(fd):
                    attr_value = os.getxattr(fd, attr_name)
                    total_metadata_bytes += len(attr_name.encode("utf-8", errors="surrogateescape")) + len(attr_value)
                    if total_metadata_bytes > _MAX_ROLLBACK_METADATA_BYTES:
                        raise ValueError("patch rollback metadata exceeds 1 MiB")
                    xattrs[attr_name] = attr_value
            windows_dacl = _get_windows_dacl(fd) if os.name == "nt" else None
            if windows_dacl is not None:
                total_metadata_bytes += len(windows_dacl)
                if total_metadata_bytes > _MAX_ROLLBACK_METADATA_BYTES:
                    raise ValueError("patch rollback metadata exceeds 1 MiB")
            if os.name != "nt" and not getattr(os, "O_NOATIME", 0):
                try:
                    os.utime(fd, ns=(info.st_atime_ns, info.st_mtime_ns))
                except (OSError, TypeError, ValueError) as exc:
                    raise ValueError("cannot preserve file access time during patch snapshot") from exc
            elif os.name == "nt":
                # The CRT descriptor is intentionally read-only, so SetFileTime
                # on its handle fails with ERROR_ACCESS_DENIED. Restore through
                # the path only after confirming it still names the pinned file.
                current = target.stat(follow_symlinks=False)
                if (current.st_dev, current.st_ino) != (final.st_dev, final.st_ino):
                    raise ValueError(f"patch target changed while restoring access time: {relative}")
                os.utime(
                    target,
                    ns=(info.st_atime_ns, info.st_mtime_ns),
                )
        finally:
            os.close(fd)
        total_bytes += read_size
        snapshots[relative] = PatchFileSnapshot(
            content, stat.S_IMODE(info.st_mode), info.st_atime_ns, info.st_mtime_ns,
            created_parent_dirs=tuple(absent_parents), xattrs=xattrs, windows_dacl=windows_dacl,
            device=info.st_dev, inode=info.st_ino,
            owner_uid=getattr(info, "st_uid", None), owner_gid=getattr(info, "st_gid", None),
            content_digest=digest.hexdigest(), size=read_size,
        )
    root_identity = (root_info.st_dev, root_info.st_ino)
    root_guard = _acquire_rollback_root(root)
    try:
        guarded_root = os.fstat(root_guard) if os.name != "nt" else root.stat()
        if (guarded_root.st_dev, guarded_root.st_ino) != root_identity:
            raise OSError("patch rollback root changed during snapshot")
        result = PatchTargetsSnapshot(root, root_identity, snapshots, root_guard)
        import weakref

        weakref.finalize(result, _close_rollback_root, root_guard)
        return result
    except BaseException:
        _close_rollback_root(root_guard)
        raise


def _assert_patch_root(root: Path, snapshot: PatchTargetsSnapshot) -> None:
    root = root.resolve(strict=True)
    root_info = root.stat()
    guarded_root = os.fstat(snapshot.root_guard) if os.name != "nt" else root_info
    if (
        root != snapshot.root
        or (root_info.st_dev, root_info.st_ino) != snapshot.root_identity
        or (guarded_root.st_dev, guarded_root.st_ino) != snapshot.root_identity
    ):
        raise OSError("patch rollback root changed since snapshot")


def _hash_patch_target(target: Path, expected_info: os.stat_result) -> str:
    fd = os.open(target, _rollback_snapshot_open_flags())
    try:
        opened = os.fstat(fd)
        expected_signature = (
            expected_info.st_dev,
            expected_info.st_ino,
            expected_info.st_size,
            expected_info.st_mtime_ns,
        )
        if not stat.S_ISREG(opened.st_mode) or (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            opened.st_mtime_ns,
        ) != expected_signature:
            raise OSError("patch target changed during validation")
        digest = hashlib.sha256()
        read_size = 0
        while True:
            chunk = os.read(fd, min(64 * 1024, expected_info.st_size - read_size + 1))
            if not chunk:
                break
            read_size += len(chunk)
            if read_size > expected_info.st_size:
                raise OSError("patch target changed during validation")
            digest.update(chunk)
        final = os.fstat(fd)
        if read_size != expected_info.st_size or (
            final.st_dev,
            final.st_ino,
            final.st_size,
            final.st_mtime_ns,
        ) != expected_signature:
            raise OSError("patch target changed during validation")
        return digest.hexdigest()
    finally:
        os.close(fd)


def _restore_patch_targets(
    root: Path,
    snapshot: PatchTargetsSnapshot,
    expected_after: PatchTargetsSnapshot | None = None,
) -> None:
    _assert_patch_root(root, snapshot)
    root = snapshot.root
    if expected_after is not None:
        if expected_after.root != snapshot.root or expected_after.root_identity != snapshot.root_identity:
            raise OSError("patch root changed during validation")
        for relative in snapshot.files:
            expected = expected_after.files.get(relative)
            if expected is None:
                raise OSError(f"patch ownership state is missing for {relative}")
            target = root.joinpath(*relative.split("/"))
            try:
                current = target.lstat()
            except FileNotFoundError:
                current = None
            expected_size = expected.size if expected.size is not None else (
                len(expected.content) if expected.content is not None else None
            )
            if expected_size is None:
                if current is not None:
                    raise OSError(f"patch target changed during validation: {relative}")
                continue
            if (
                current is None
                or not stat.S_ISREG(current.st_mode)
                or stat.S_ISLNK(current.st_mode)
                or current.st_size != expected_size
                or stat.S_IMODE(current.st_mode) != expected.mode
                or current.st_mtime_ns != expected.mtime_ns
                or (expected.device, expected.inode) != (current.st_dev, current.st_ino)
            ):
                raise OSError(f"patch target changed during validation: {relative}")
            expected_digest = expected.content_digest
            if expected_digest is not None:
                if _hash_patch_target(target, current) != expected_digest:
                    raise OSError(f"patch target changed during validation: {relative}")
            elif expected.content is not None:
                if target.read_bytes() != expected.content:
                    raise OSError(f"patch target changed during validation: {relative}")
            else:
                raise OSError(f"patch ownership fingerprint is missing for {relative}")
    created_parents = {
        root.joinpath(*relative.split("/"))
        for file_snapshot in snapshot.files.values()
        for relative in file_snapshot.created_parent_dirs
    }
    for relative, file_snapshot in snapshot.files.items():
        parts = tuple(relative.split("/"))
        target = root
        for part in parts[:-1]:
            target = target / part
            try:
                info = target.lstat()
            except FileNotFoundError:
                target.mkdir()
                created_parents.add(target)
                continue
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise OSError(f"refusing rollback through symlink or non-directory: {target.relative_to(root)}")
        target = target / parts[-1]
        try:
            current = target.lstat()
        except FileNotFoundError:
            current = None
        if current is not None and stat.S_ISDIR(current.st_mode) and not stat.S_ISLNK(current.st_mode):
            raise OSError(f"refusing to remove rollback directory: {relative}")
        if file_snapshot.content is None:
            if current is not None:
                target.unlink()
            continue
        if current is not None and stat.S_ISLNK(current.st_mode):
            target.unlink()
        fd, temp_name = tempfile.mkstemp(prefix=".local-ai-patch-rollback-", dir=str(target.parent))
        try:
            with os.fdopen(fd, "wb", closefd=False) as destination:
                destination.write(file_snapshot.content or b"")
                destination.flush()
                os.fsync(destination.fileno())
            if os.name != "nt" and file_snapshot.owner_uid is not None and file_snapshot.owner_gid is not None:
                os.chown(temp_name, file_snapshot.owner_uid, file_snapshot.owner_gid)
            if file_snapshot.mode is not None:
                os.chmod(temp_name, file_snapshot.mode)
            if file_snapshot.xattrs:
                for attr_name, attr_value in file_snapshot.xattrs.items():
                    os.setxattr(temp_name, attr_name, attr_value)
            if file_snapshot.windows_dacl is not None:
                _set_windows_dacl_path(temp_name, file_snapshot.windows_dacl, fd)
            if file_snapshot.atime_ns is not None and file_snapshot.mtime_ns is not None:
                if os.name == "nt":
                    os.utime(temp_name, ns=(file_snapshot.atime_ns, file_snapshot.mtime_ns))
                else:
                    os.utime(temp_name, ns=(file_snapshot.atime_ns, file_snapshot.mtime_ns), follow_symlinks=False)
            os.close(fd)
            fd = -1
            os.replace(temp_name, target)
        finally:
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
    for parent in sorted(created_parents, key=lambda item: len(item.parts), reverse=True):
        try:
            parent.rmdir()
        except OSError:
            pass




































def _snapshot_rollback_scope(
    cwd: str,
    paths: list[str] | None,
) -> tuple[RollbackSnapshot | None, str | None]:
    if not paths:
        return None, "rollback paths are required"
    if not isinstance(paths, list) or len(paths) > _MAX_ROLLBACK_PATHS:
        return None, "rollback paths must be a list of at most 128 files"
    root_guard: int | None = None
    parent_handles: list[int] = []
    try:
        root = Path(cwd).resolve(strict=True)
        if not root.is_dir():
            return None, "rollback root must be a directory"
        root_guard = _acquire_rollback_root(root)
        root_identity = _rollback_root_identity(root_guard)
        state: dict[str, RollbackFileSnapshot] = {}
        seen_paths: set[str] = set()
        total_bytes = 0
        for raw in paths:
            entry_stat = None
            if not isinstance(raw, str) or not raw or "\x00" in raw:
                raise ValueError("rollback paths must be non-empty relative file paths")
            portable = raw.replace("\\", "/")
            drive, _ = ntpath.splitdrive(raw)
            parts = portable.split("/")
            if drive or ntpath.isabs(raw) or portable.startswith("/") or any(p in {"", ".", ".."} for p in parts):
                raise ValueError(f"invalid rollback path: {raw[:160]}")
            reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10)), "COM¹", "COM²", "COM³", "LPT¹", "LPT²", "LPT³"}
            if any(
                ":" in part
                or part.endswith((".", " "))
                or part.split(".", 1)[0].rstrip(" .").upper() in reserved
                for part in parts
            ):
                raise ValueError(f"invalid platform-specific rollback path: {raw[:160]}")
            key = Path(*parts).as_posix()
            comparison_key = key.casefold() if os.name == "nt" else key
            if comparison_key in seen_paths:
                raise ValueError(f"duplicate rollback path: {raw[:160]}")
            seen_paths.add(comparison_key)
            parent_guard, parent_owned = _open_rollback_parent_handle(root_guard, parts[:-1])
            if parent_owned:
                parent_handles.append(parent_guard)
            leaf = parts[-1]
            snapshot_fd: int | None = None
            if os.name != "nt":
                try:
                    entry_stat = os.stat(leaf, dir_fd=parent_guard, follow_symlinks=False)
                except FileNotFoundError:
                    entry_stat = None
                if entry_stat is not None and stat.S_ISLNK(entry_stat.st_mode):
                    raise ValueError(f"rollback paths cannot be symlinks: {raw[:160]}")
            if os.name == "nt":
                snapshot_fd = _open_rollback_snapshot_file(parent_guard, leaf)
                if snapshot_fd is not None:
                    try:
                        entry_stat = os.fstat(snapshot_fd)
                    except BaseException:
                        fd_to_close = snapshot_fd
                        snapshot_fd = None
                        try:
                            os.close(fd_to_close)
                        except OSError:
                            pass
                        raise
            if entry_stat is not None:
                try:
                    if not stat.S_ISREG(entry_stat.st_mode):
                        raise ValueError(f"rollback path must be a regular file: {raw[:160]}")
                    if entry_stat.st_nlink > 1:
                        raise ValueError(f"rollback does not accept multiply-linked files: {raw[:160]}")
                    size = entry_stat.st_size
                    if size > _MAX_ROLLBACK_FILE_BYTES or total_bytes + size > _MAX_ROLLBACK_TOTAL_BYTES:
                        raise ValueError("rollback snapshot exceeds the 16 MiB per-file or 64 MiB total limit")
                    if os.name != "nt":
                        open_flags = _rollback_snapshot_open_flags()
                        snapshot_fd = os.open(leaf, open_flags, dir_fd=parent_guard)
                    if snapshot_fd is None:
                        raise ValueError(f"rollback target disappeared during snapshot: {raw[:160]}")
                    fd = snapshot_fd
                    opened_stat = os.fstat(fd)
                    if (
                        (os.name != "nt" and (opened_stat.st_dev, opened_stat.st_ino) != (entry_stat.st_dev, entry_stat.st_ino))
                        or opened_stat.st_nlink > 1
                    ):
                        raise ValueError(f"rollback target changed during snapshot: {raw[:160]}")
                    with os.fdopen(fd, "rb", closefd=False) as source:
                        content = source.read(_MAX_ROLLBACK_FILE_BYTES + 1)
                    final_stat = os.fstat(fd)
                    stable_fields = (opened_stat.st_size, opened_stat.st_mtime_ns, opened_stat.st_ctime_ns)
                    final_fields = (final_stat.st_size, final_stat.st_mtime_ns, final_stat.st_ctime_ns)
                    if len(content) > _MAX_ROLLBACK_FILE_BYTES or stable_fields != final_fields or final_stat.st_nlink > 1:
                        raise ValueError(f"rollback target changed during snapshot: {raw[:160]}")
                    if os.name != "nt" and not getattr(os, "O_NOATIME", 0):
                        try:
                            os.utime(fd, ns=(opened_stat.st_atime_ns, opened_stat.st_mtime_ns))
                        except (OSError, TypeError, ValueError) as exc:
                            raise ValueError("cannot preserve file access time during rollback snapshot") from exc
                    elif os.name == "nt":
                        target_path = root.joinpath(*parts)
                        current = target_path.lstat()
                        if (
                            stat.S_ISLNK(current.st_mode)
                            or (current.st_dev, current.st_ino) != (final_stat.st_dev, final_stat.st_ino)
                        ):
                            raise ValueError(f"rollback target changed while restoring access time: {raw[:160]}")
                        os.utime(
                            target_path,
                            ns=(opened_stat.st_atime_ns, opened_stat.st_mtime_ns),
                        )
                    xattrs: dict[str, bytes] = {}
                    metadata_size = 0
                    if os.name != "nt" and hasattr(os, "listxattr"):
                        for attr_name in os.listxattr(fd):
                            attr_value = os.getxattr(fd, attr_name)
                            metadata_size += len(attr_name.encode("utf-8", errors="surrogateescape")) + len(attr_value)
                            if metadata_size > _MAX_ROLLBACK_METADATA_BYTES:
                                raise ValueError("rollback extended metadata exceeds 1 MiB")
                            xattrs[attr_name] = attr_value
                    windows_dacl = _get_windows_dacl(fd) if os.name == "nt" else None
                finally:
                    if snapshot_fd is not None:
                        os.close(snapshot_fd)
                        snapshot_fd = None
                if total_bytes + len(content) > _MAX_ROLLBACK_TOTAL_BYTES:
                    raise ValueError("rollback snapshot exceeds the 64 MiB total limit")
                total_bytes += len(content)
                mode = stat.S_IMODE(entry_stat.st_mode)
                file_snapshot = RollbackFileSnapshot(content, mode, xattrs, windows_dacl, entry_stat.st_atime_ns, entry_stat.st_mtime_ns)
            else:
                file_snapshot = RollbackFileSnapshot(None, None, {}, None, None, None)
            state[key] = file_snapshot
            if parent_owned:
                _close_rollback_root(parent_guard)
                parent_handles.remove(parent_guard)
        return RollbackSnapshot(root, root_identity, state, root_guard), None
    except (OSError, ValueError, TypeError) as exc:
        for parent_handle in parent_handles:
            try:
                _close_rollback_root(parent_handle)
            except OSError:
                pass
        if root_guard is not None:
            try:
                _close_rollback_root(root_guard)
            except OSError:
                pass
        return None, f"cannot snapshot rollback scope: {str(exc)[:256]}"


def _rollback_postimage_at(parent_handle: int, leaf: str) -> RollbackPostimage:
    fd: int | None = None
    try:
        if os.name == "nt":
            fd = _open_rollback_snapshot_file(parent_handle, leaf)
            if fd is None:
                return RollbackPostimage(True, None)
            opened_stat = os.fstat(fd)
        else:
            try:
                entry_stat = os.stat(leaf, dir_fd=parent_handle, follow_symlinks=False)
            except FileNotFoundError:
                return RollbackPostimage(True, None)
            if stat.S_ISLNK(entry_stat.st_mode):
                return RollbackPostimage(False, None, "symlink postimage")
            if not stat.S_ISREG(entry_stat.st_mode):
                return RollbackPostimage(False, None, "non-file postimage")
            if entry_stat.st_nlink != 1:
                return RollbackPostimage(False, None, "external aliases")
            fd = os.open(leaf, _rollback_snapshot_open_flags(), dir_fd=parent_handle)
            opened_stat = os.fstat(fd)
            if (opened_stat.st_dev, opened_stat.st_ino) != (entry_stat.st_dev, entry_stat.st_ino):
                return RollbackPostimage(False, None, "postimage changed while opening")
        if not stat.S_ISREG(opened_stat.st_mode):
            return RollbackPostimage(False, None, "non-file postimage")
        if opened_stat.st_nlink != 1:
            return RollbackPostimage(False, None, "external aliases")
        with os.fdopen(fd, "rb", closefd=False) as source:
            content = source.read(_MAX_ROLLBACK_FILE_BYTES + 1)
        final_stat = os.fstat(fd)
        identity = (opened_stat.st_dev, opened_stat.st_ino)
        stable_before = (
            identity,
            opened_stat.st_size,
            opened_stat.st_mtime_ns,
            opened_stat.st_ctime_ns,
            stat.S_IMODE(opened_stat.st_mode),
            opened_stat.st_nlink,
        )
        stable_after = (
            (final_stat.st_dev, final_stat.st_ino),
            final_stat.st_size,
            final_stat.st_mtime_ns,
            final_stat.st_ctime_ns,
            stat.S_IMODE(final_stat.st_mode),
            final_stat.st_nlink,
        )
        if len(content) > _MAX_ROLLBACK_FILE_BYTES or stable_before != stable_after:
            return RollbackPostimage(False, None, "postimage changed while reading")
        metadata_digest = hashlib.sha256()
        metadata_size = 0
        if os.name != "nt" and hasattr(os, "listxattr"):
            for attr_name in sorted(os.listxattr(fd)):
                name_bytes = attr_name.encode("utf-8", errors="surrogateescape")
                attr_value = os.getxattr(fd, attr_name)
                metadata_size += len(name_bytes) + len(attr_value)
                if metadata_size > _MAX_ROLLBACK_METADATA_BYTES:
                    return RollbackPostimage(False, None, "postimage metadata exceeds limit")
                metadata_digest.update(len(name_bytes).to_bytes(4, "big"))
                metadata_digest.update(name_bytes)
                metadata_digest.update(len(attr_value).to_bytes(4, "big"))
                metadata_digest.update(attr_value)
        elif os.name == "nt":
            dacl = _get_windows_dacl(fd)
            if dacl is not None:
                metadata_digest.update(dacl)
        final_stat = os.fstat(fd)
        stable_after = (
            (final_stat.st_dev, final_stat.st_ino),
            final_stat.st_size,
            final_stat.st_mtime_ns,
            final_stat.st_ctime_ns,
            stat.S_IMODE(final_stat.st_mode),
            final_stat.st_nlink,
        )
        if stable_before != stable_after:
            return RollbackPostimage(False, None, "postimage changed while reading")
        return RollbackPostimage(
            True,
            (*identity, final_stat.st_size, final_stat.st_mtime_ns, final_stat.st_ctime_ns,
             stat.S_IMODE(final_stat.st_mode), hashlib.sha256(content).hexdigest(),
             metadata_digest.hexdigest()),
        )
    except (OSError, ValueError) as exc:
        reason = "external aliases" if "reparse" in str(exc).lower() else f"unverifiable postimage: {exc}"
        return RollbackPostimage(False, None, reason[:160])
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


class _RollbackPostimageChanged(OSError):
    def __init__(self, message: str, *, preserve_temporary: bool = False) -> None:
        super().__init__(message)
        self.preserve_temporary = preserve_temporary


def _rename_exchange_at(parent_handle: int, left: str, right: str) -> None:
    """Atomically exchange two directory entries, failing closed if unsupported."""

    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        exchange = getattr(libc, "renameatx_np", None)
        flags = 0x00000002  # RENAME_SWAP
    else:
        exchange = getattr(libc, "renameat2", None)
        flags = 0x00000002  # RENAME_EXCHANGE
    if exchange is None:
        unsupported = getattr(errno, "ENOTSUP", errno.EOPNOTSUPP)
        raise OSError(unsupported, "atomic rollback exchange is unavailable", left)
    exchange.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    exchange.restype = ctypes.c_int
    result = exchange(
        parent_handle, os.fsencode(left), parent_handle, os.fsencode(right), flags
    )
    if result != 0:
        error_code = ctypes.get_errno()
        raise OSError(error_code, os.strerror(error_code), f"{left} <-> {right}")


def _rename_noreplace_at(parent_handle: int, source: str, destination: str) -> None:
    """Atomically move one entry without replacing a concurrent destination."""

    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        rename_entry = getattr(libc, "renameatx_np", None)
        flags = 0x00000004  # RENAME_EXCL
    else:
        rename_entry = getattr(libc, "renameat2", None)
        flags = 0x00000001  # RENAME_NOREPLACE
    if rename_entry is None:
        unsupported = getattr(errno, "ENOTSUP", errno.EOPNOTSUPP)
        raise OSError(unsupported, "atomic rollback quarantine is unavailable", source)
    rename_entry.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename_entry.restype = ctypes.c_int
    result = rename_entry(
        parent_handle,
        os.fsencode(source),
        parent_handle,
        os.fsencode(destination),
        flags,
    )
    if result != 0:
        error_code = ctypes.get_errno()
        raise OSError(error_code, os.strerror(error_code), f"{source} -> {destination}")


def _same_rollback_postimage_after_owned_rename(
    observed: RollbackPostimage,
    expected: RollbackPostimage,
) -> bool:
    """Account for rename's ctime update without relaxing other postimage fields."""
    if not observed.safe or not expected.safe:
        return False
    actual = observed.fingerprint
    original = expected.fingerprint
    if actual is None or original is None:
        return False
    # POSIX exchange updates both inodes' ctime. Full ctime equality remains
    # mandatory before the exchange and while each postimage is being read.
    # After our rename retain inode, size, mtime, mode, content and metadata
    # equality, and reject a ctime that moved backwards.
    return (
        actual[:4] == original[:4]
        and actual[5:] == original[5:]
        and actual[4] >= original[4]
    )


def _restore_existing_rollback_leaf(
    parent_handle: int,
    temporary_name: str,
    leaf: str,
    expected_postimage: RollbackPostimage,
) -> None:
    """Replace an existing leaf by exchange, then verify displaced postimage."""
    staged_postimage = _rollback_postimage_at(parent_handle, temporary_name)
    current_postimage = _rollback_postimage_at(parent_handle, leaf)
    if (
        not expected_postimage.safe
        or expected_postimage.fingerprint is None
        or not staged_postimage.safe
        or staged_postimage.fingerprint is None
        or not current_postimage.safe
        or current_postimage.fingerprint != expected_postimage.fingerprint
    ):
        raise _RollbackPostimageChanged("rollback postimage changed before atomic exchange")

    _rename_exchange_at(parent_handle, temporary_name, leaf)
    displaced_postimage = _rollback_postimage_at(parent_handle, temporary_name)
    if _same_rollback_postimage_after_owned_rename(displaced_postimage, expected_postimage):
        os.unlink(temporary_name, dir_fd=parent_handle)
        return

    replacement_at_leaf = _rollback_postimage_at(parent_handle, leaf)
    if _same_rollback_postimage_after_owned_rename(replacement_at_leaf, staged_postimage):
        _rename_exchange_at(parent_handle, temporary_name, leaf)
        returned_stage = _rollback_postimage_at(parent_handle, temporary_name)
        if _same_rollback_postimage_after_owned_rename(returned_stage, staged_postimage):
            raise _RollbackPostimageChanged(
                "rollback postimage changed during atomic exchange"
            )

    raise _RollbackPostimageChanged(
        f"rollback postimage changed during atomic exchange; preserved entry at {temporary_name}",
        preserve_temporary=True,
    )


def _capture_rollback_postimages(snapshot: RollbackSnapshot) -> None:
    """Record stable after-images only for the caller-declared rollback paths."""
    for relative in snapshot.files:
        parts = relative.split("/")
        try:
            parent_handle, parent_owned = _open_rollback_parent_handle(
                snapshot.root_guard,
                parts[:-1],
            )
        except (OSError, ValueError) as exc:
            snapshot.postimages[relative] = RollbackPostimage(
                False, None, f"unverifiable postimage parent: {exc}"[:160]
            )
            continue
        try:
            snapshot.postimages[relative] = _rollback_postimage_at(parent_handle, parts[-1])
        finally:
            if parent_owned:
                _close_rollback_root(parent_handle)


def _restore_rollback_scope(
    cwd: str,
    snapshot: RollbackSnapshot,
) -> None:
    root = Path(cwd).resolve(strict=True)
    # POSIX cannot atomically bind this path check to later dirfd writes. After
    # the check, every mutation stays relative to the snapshot's pinned root.
    current_root_handle = _acquire_rollback_root(root)
    try:
        current_root_identity = _rollback_root_identity(current_root_handle)
    finally:
        _close_rollback_root(current_root_handle)
    root_identity = _rollback_root_identity(snapshot.root_guard)
    if (
        root_identity != snapshot.root_identity
        or current_root_identity != snapshot.root_identity
        or root != snapshot.root
    ):
        raise OSError("rollback root changed since snapshot")
    if set(snapshot.postimages) != set(snapshot.files):
        raise OSError("rollback postimages were not captured for the complete write set")
    incomplete: list[str] = []
    for relative, file_snapshot in snapshot.files.items():
        content, mode = file_snapshot.content, file_snapshot.mode
        parts = relative.split("/")
        parent_handle, parent_owned = _open_rollback_parent_handle(
            snapshot.root_guard,
            parts[:-1],
            mutation=True,
        )
        leaf = parts[-1]
        try:
            expected_postimage = snapshot.postimages.get(relative)
            current_postimage = _rollback_postimage_at(parent_handle, leaf)
            if (
                expected_postimage is None
                or not expected_postimage.safe
                or not current_postimage.safe
                or expected_postimage.fingerprint != current_postimage.fingerprint
            ):
                incomplete.append(relative)
                continue

            def postimage_still_matches() -> bool:
                latest = _rollback_postimage_at(parent_handle, leaf)
                return (
                    expected_postimage.safe
                    and latest.safe
                    and expected_postimage.fingerprint == latest.fingerprint
                )

            if os.name != "nt":
                try:
                    current_stat = os.stat(leaf, dir_fd=parent_handle, follow_symlinks=False)
                except FileNotFoundError:
                    current_stat = None
                if current_stat is not None and stat.S_ISDIR(current_stat.st_mode):
                    raise OSError(f"refusing to replace rollback directory: {relative}")
                if current_stat is not None and (stat.S_ISLNK(current_stat.st_mode) or current_stat.st_nlink > 1):
                    incomplete.append(relative)
                    continue
                if content is None:
                    if current_stat is not None:
                        if not postimage_still_matches():
                            incomplete.append(relative)
                            continue
                        quarantine_name = f".local-ai-rollback-postimage-{uuid.uuid4().hex}"
                        _rename_noreplace_at(parent_handle, leaf, quarantine_name)
                        quarantined = _rollback_postimage_at(parent_handle, quarantine_name)
                        if _same_rollback_postimage_after_owned_rename(
                            quarantined, expected_postimage
                        ):
                            os.unlink(quarantine_name, dir_fd=parent_handle)
                            try:
                                os.stat(leaf, dir_fd=parent_handle, follow_symlinks=False)
                            except FileNotFoundError:
                                pass
                            else:
                                incomplete.append(relative)
                        else:
                            try:
                                _rename_noreplace_at(parent_handle, quarantine_name, leaf)
                            except OSError as exc:
                                raise _RollbackPostimageChanged(
                                    f"changed rollback postimage preserved at {quarantine_name}: {exc}",
                                    preserve_temporary=True,
                                ) from exc
                            incomplete.append(relative)
                    continue
                temp_name = f".local-ai-rollback-{uuid.uuid4().hex}"
                fd = os.open(
                    temp_name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
                    0o600,
                    dir_fd=parent_handle,
                )
                preserve_temp = False
                try:
                    with os.fdopen(fd, "wb", closefd=False) as temp_file:
                        temp_file.write(content)
                        temp_file.flush()
                        os.fsync(temp_file.fileno())
                    if mode is not None:
                        os.fchmod(fd, mode)
                    for attr_name, attr_value in file_snapshot.xattrs.items():
                        os.setxattr(fd, attr_name, attr_value)
                    if file_snapshot.atime_ns is not None and file_snapshot.mtime_ns is not None:
                        os.utime(fd, ns=(file_snapshot.atime_ns, file_snapshot.mtime_ns))
                    if not postimage_still_matches():
                        incomplete.append(relative)
                        continue
                    if expected_postimage.fingerprint is None:
                        # linkat-style creation is atomic and fails if a foreign
                        # writer creates the previously absent leaf after our check.
                        os.link(
                            temp_name,
                            leaf,
                            src_dir_fd=parent_handle,
                            dst_dir_fd=parent_handle,
                            follow_symlinks=False,
                        )
                        os.unlink(temp_name, dir_fd=parent_handle)
                    else:
                        try:
                            _restore_existing_rollback_leaf(
                                parent_handle, temp_name, leaf, expected_postimage
                            )
                        except _RollbackPostimageChanged as exc:
                            preserve_temp = exc.preserve_temporary
                            raise
                finally:
                    os.close(fd)
                    if not preserve_temp:
                        try:
                            os.unlink(temp_name, dir_fd=parent_handle)
                        except FileNotFoundError:
                            pass
                continue

            import msvcrt

            if content is None and not postimage_still_matches():
                incomplete.append(relative)
                continue
            target_handle = _open_rollback_relative_handle(
                parent_handle,
                leaf,
                directory=False,
                mutation=True,
            )
            target_fd: int | None = None
            if target_handle is not None:
                try:
                    target_fd = msvcrt.open_osfhandle(target_handle, os.O_RDONLY | os.O_BINARY)
                except BaseException:
                    _close_rollback_root(target_handle)
                    raise
                try:
                    current_stat = os.fstat(target_fd)
                except BaseException:
                    os.close(target_fd)
                    raise
                if content is None and expected_postimage.fingerprint is not None:
                    expected_fields = expected_postimage.fingerprint[:6]
                    observed_fields = (
                        current_stat.st_dev,
                        current_stat.st_ino,
                        current_stat.st_size,
                        current_stat.st_mtime_ns,
                        current_stat.st_ctime_ns,
                        stat.S_IMODE(current_stat.st_mode),
                    )
                    if expected_fields != observed_fields:
                        incomplete.append(relative)
                        os.close(target_fd)
                        target_fd = None
                        continue
                if current_stat.st_nlink > 1:
                    incomplete.append(relative)
                    if target_fd is not None:
                        os.close(target_fd)
                        target_fd = None
                    continue
            else:
                current_stat = None
            if content is None:
                if target_fd is not None:
                    if current_stat is not None and current_stat.st_nlink > 1:
                        os.close(target_fd)
                        continue
                    try:
                        _delete_windows_handle(msvcrt.get_osfhandle(target_fd))
                    finally:
                        os.close(target_fd)
                continue
            if target_fd is not None:
                os.close(target_fd)

            temp_name = f".local-ai-rollback-{uuid.uuid4().hex}"
            temp_handle = _open_rollback_relative_handle(
                parent_handle,
                temp_name,
                directory=False,
                mutation=True,
                create=True,
            )
            if temp_handle is None:
                raise OSError("cannot create rollback temporary file")
            try:
                temp_fd = msvcrt.open_osfhandle(temp_handle, os.O_RDWR | os.O_BINARY)
            except BaseException:
                _close_rollback_root(temp_handle)
                raise
            renamed = False
            try:
                with os.fdopen(temp_fd, "wb", closefd=False) as temp_file:
                    temp_file.write(content)
                    temp_file.flush()
                    os.fsync(temp_file.fileno())
                _restore_windows_file_attributes(temp_fd, mode)
                _restore_windows_file_times(temp_fd, file_snapshot.atime_ns, file_snapshot.mtime_ns)
                if file_snapshot.windows_dacl is not None:
                    _set_windows_dacl(temp_fd, file_snapshot.windows_dacl)
                if not postimage_still_matches():
                    incomplete.append(relative)
                    continue
                _rename_windows_handle(
                    msvcrt.get_osfhandle(temp_fd),
                    parent_handle,
                    leaf,
                    replace_if_exists=expected_postimage.fingerprint is not None,
                )
                renamed = True
            finally:
                import sys

                pending_error = sys.exc_info()[1]
                try:
                    if not renamed:
                        temp_os_handle = msvcrt.get_osfhandle(temp_fd)
                        try:
                            _delete_windows_handle(temp_os_handle)
                        except OSError as first_delete_error:
                            try:
                                _delete_windows_handle(temp_os_handle)
                            except OSError as retry_delete_error:
                                detail = (
                                    f"rollback temporary cleanup failed for {relative}: "
                                    f"{retry_delete_error} (first attempt: {first_delete_error})"
                                )
                                if pending_error is not None:
                                    if hasattr(pending_error, "add_note"):
                                        pending_error.add_note(detail)
                                    else:
                                        pending_error.args = (*pending_error.args, detail)
                                else:
                                    raise OSError(detail) from retry_delete_error
                finally:
                    os.close(temp_fd)
        finally:
            if parent_owned:
                _close_rollback_root(parent_handle)
    if incomplete:
        names = ", ".join(incomplete[:8])
        raise OSError(
            "rollback skipped changed postimages or paths with external aliases for: "
            f"{names}"
        )


def _patch_write_paths(root: Path, patch: bytes, timeout: float) -> list[str]:
    """Return patch paths only after rejecting escapes and symlink traversal."""
    result = subprocess.run(
        ["git", "apply", "--numstat", "-z"],
        input=patch,
        cwd=str(root),
        capture_output=True,
        check=False,
        timeout=timeout,
        **hidden_run_kwargs(),
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(detail or "patch write set could not be inspected")

    records = result.stdout.split(b"\0")
    paths: list[str] = []
    index = 0
    while index < len(records) - 1:
        fields = records[index].split(b"\t", 2)
        index += 1
        if len(fields) != 3:
            raise ValueError("patch write set is malformed")
        if fields[2]:
            candidates = [os.fsdecode(fields[2])]
        else:
            if index + 1 >= len(records) - 1:
                raise ValueError("patch rename write set is malformed")
            candidates = [os.fsdecode(records[index]), os.fsdecode(records[index + 1])]
            index += 2
        paths.extend(candidates)

    if not paths or len(paths) > 512:
        raise ValueError("patch write set must contain 1 to 512 paths")
    root = root.resolve(strict=True)
    safe_paths: list[str] = []
    for raw in paths:
        drive, _ = ntpath.splitdrive(raw)
        parts = raw.split("/")
        if (
            not raw
            or drive
            or raw.startswith(("/", "\\"))
            or "\\" in raw
            or ":" in raw
            or any(part in {"", ".", ".."} for part in parts)
            or any(ord(char) < 32 for char in raw)
        ):
            raise ValueError("patch write path is not a safe relative path")
        candidate = root
        for part in parts:
            candidate = candidate / part
            if candidate.is_symlink() or (
                callable(getattr(candidate, "is_junction", None)) and candidate.is_junction()
            ):
                raise ValueError("patch write path cannot traverse a symlink or junction")
            resolved = candidate.resolve(strict=False)
            try:
                resolved.relative_to(root)
            except ValueError as exc:
                raise ValueError("patch write path escapes the worktree") from exc
        safe_paths.append("/".join(parts))
    return list(dict.fromkeys(safe_paths))



def simulate_patch(
    cwd: str | Path,
    patch: str,
    *,
    timeout: float = 15.0,
    allow_whitespace_fallback: bool = True,
) -> dict[str, Any]:
    """In-memory dry-run patch simulation without modifying files on disk."""
    if not isinstance(patch, str) or not patch.strip():
        return {
            "valid": False,
            "files": [],
            "additions": 0,
            "deletions": 0,
            "file_stats": [],
            "error": "patch text is empty",
            "whitespace_fallback_used": False,
        }

    try:
        cwd_path = Path(cwd).resolve(strict=True)
    except Exception as exc:
        return {
            "valid": False,
            "files": [],
            "additions": 0,
            "deletions": 0,
            "file_stats": [],
            "error": f"invalid cwd: {exc}",
            "whitespace_fallback_used": False,
        }

    patch_bytes = patch.encode("utf-8")

    # 1. Parse numstat / affected files
    files: list[str] = []
    file_stats: list[dict[str, Any]] = []
    total_additions = 0
    total_deletions = 0

    numstat_proc = subprocess.run(
        ["git", "apply", "--numstat", "-z"],
        input=patch_bytes,
        cwd=str(cwd_path),
        capture_output=True,
        check=False,
        timeout=timeout,
        **hidden_run_kwargs(),
    )
    if numstat_proc.returncode == 0:
        records = numstat_proc.stdout.split(b"\0")
        idx = 0
        while idx < len(records) - 1:
            fields = records[idx].split(b"\t", 2)
            idx += 1
            if len(fields) == 3:
                try:
                    adds = int(fields[0].decode("ascii", errors="replace")) if fields[0] != b"-" else 0
                except ValueError:
                    adds = 0
                try:
                    dels = int(fields[1].decode("ascii", errors="replace")) if fields[1] != b"-" else 0
                except ValueError:
                    dels = 0
                if fields[2]:
                    p = os.fsdecode(fields[2])
                else:
                    if idx + 1 < len(records) - 1:
                        p = os.fsdecode(records[idx + 1])
                        idx += 2
                    else:
                        p = ""
                if p:
                    files.append(p)
                    file_stats.append({"path": p, "additions": adds, "deletions": dels})
                    total_additions += adds
                    total_deletions += dels
    else:
        for line in patch.splitlines():
            if line.startswith("+++ b/"):
                p = line[6:].strip()
                if p and p not in files:
                    files.append(p)
            elif line.startswith("+") and not line.startswith("+++"):
                total_additions += 1
            elif line.startswith("-") and not line.startswith("---"):
                total_deletions += 1
        for p in files:
            file_stats.append({"path": p, "additions": total_additions, "deletions": total_deletions})

    # 2. Dry-run applicability check (zero disk write)
    check_proc = subprocess.run(
        ["git", "apply", "--check", "--whitespace=nowarn"],
        input=patch_bytes,
        cwd=str(cwd_path),
        capture_output=True,
        check=False,
        timeout=timeout,
        **hidden_run_kwargs(),
    )
    if check_proc.returncode == 0:
        return {
            "valid": True,
            "files": list(dict.fromkeys(files)),
            "additions": total_additions,
            "deletions": total_deletions,
            "file_stats": file_stats,
            "error": None,
            "whitespace_fallback_used": False,
        }

    err_msg = check_proc.stderr.decode("utf-8", errors="replace").strip()
    if allow_whitespace_fallback:
        ws_proc = subprocess.run(
            ["git", "apply", "--check", "--ignore-whitespace", "--ignore-space-change"],
            input=patch_bytes,
            cwd=str(cwd_path),
            capture_output=True,
            check=False,
            timeout=timeout,
            **hidden_run_kwargs(),
        )
        if ws_proc.returncode == 0:
            return {
                "valid": True,
                "files": list(dict.fromkeys(files)),
                "additions": total_additions,
                "deletions": total_deletions,
                "file_stats": file_stats,
                "error": None,
                "whitespace_fallback_used": True,
            }
        err_msg = ws_proc.stderr.decode("utf-8", errors="replace").strip() or err_msg

    return {
        "valid": False,
        "files": list(dict.fromkeys(files)),
        "additions": total_additions,
        "deletions": total_deletions,
        "file_stats": file_stats,
        "error": err_msg or "patch check failed",
        "whitespace_fallback_used": False,
    }


def patch_dry_run(
    cwd: str | Path,
    patch: str,
    *,
    timeout: float = 15.0,
    allow_whitespace_fallback: bool = True,
) -> dict[str, Any]:
    """Alias for simulate_patch."""
    return simulate_patch(
        cwd,
        patch,
        timeout=timeout,
        allow_whitespace_fallback=allow_whitespace_fallback,
    )


def _stable_rollback_status(method: Any) -> Any:
    @wraps(method)
    def wrapped(self: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
        result = method(self, *args, **kwargs)
        rollback_key = "auto_rollback" if method.__name__ == "patch_and_verify" else "rollback_on_failure"
        rollback_default = method.__name__ == "patch_and_verify"
        if kwargs.get(rollback_key, rollback_default) and isinstance(result, dict):
            result.setdefault("rolled_back", False)
        return result
    return wrapped



from .command_rollback_windows import (
    _get_windows_dacl as _get_windows_dacl,
    _set_windows_dacl as _set_windows_dacl,
    _set_windows_dacl_path as _set_windows_dacl_path,
    _restore_windows_file_attributes as _restore_windows_file_attributes,
    _restore_windows_file_times as _restore_windows_file_times,
    _delete_windows_handle as _delete_windows_handle,
    _rename_windows_handle as _rename_windows_handle,
    _windows_dacl_bytes as _windows_dacl_bytes,
    _acquire_rollback_root as _acquire_rollback_root,
    _close_rollback_root as _close_rollback_root,
    _rollback_snapshot_open_flags as _rollback_snapshot_open_flags,
    _rollback_root_identity as _rollback_root_identity,
    _windows_handle_attributes as _windows_handle_attributes,
    _windows_handle_identity as _windows_handle_identity,
    _open_rollback_relative_handle as _open_rollback_relative_handle,
    _open_rollback_parent_handle as _open_rollback_parent_handle,
    _open_rollback_snapshot_file as _open_rollback_snapshot_file,
    _restore_windows_atime as _restore_windows_atime,
)
