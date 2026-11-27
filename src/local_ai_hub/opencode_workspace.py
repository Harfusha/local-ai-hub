"""Bounded snapshots and conflict-aware result transfer for OpenCode workspaces.

This module never grants a process access to the source checkout. Callers must
keep the managed launch disabled until the Windows handle and AppContainer
boundary have been verified end to end.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping


class UnsafeWorkspacePathError(RuntimeError):
    """A snapshot contains a symlink, reparse point, or unsupported file type."""


@dataclass(frozen=True)
class FileFingerprint:
    size: int
    sha256: str


@dataclass(frozen=True)
class WorkspaceSnapshot:
    source_root: Path
    staging_root: Path
    source_identity: tuple[int, int]
    staging_identity: tuple[int, int]
    baseline: Mapping[str, FileFingerprint]


@dataclass(frozen=True)
class WorkspaceTransferResult:
    applied: tuple[str, ...]
    conflicts: tuple[str, ...]


_REPARSE_POINT = 0x400
_DEFAULT_MAX_FILES = 100_000
_DEFAULT_MAX_BYTES = 4 * 1024 * 1024 * 1024


def _is_reparse(path: Path, info: os.stat_result | None = None) -> bool:
    info = info or path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & _REPARSE_POINT)


def _root(path: str | os.PathLike[str]) -> Path:
    candidate = Path(os.path.abspath(os.fspath(path)))
    info = candidate.lstat()
    if not stat.S_ISDIR(info.st_mode) or _is_reparse(candidate, info):
        raise UnsafeWorkspacePathError(f"workspace root is not a real directory: {candidate}")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_dir():
        raise UnsafeWorkspacePathError(f"workspace root is not a directory: {resolved}")
    return resolved


def _identity(path: Path) -> tuple[int, int]:
    info = path.stat()
    return int(info.st_dev), int(info.st_ino)


def _scan(root: Path, *, max_files: int, max_bytes: int) -> tuple[dict[str, Path], dict[str, Path]]:
    files: dict[str, Path] = {}
    directories: dict[str, Path] = {"": root}
    stack = [("", root)]
    total_bytes = 0
    while stack:
        relative_parent, directory = stack.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name.casefold())
        except OSError as exc:
            raise UnsafeWorkspacePathError(f"cannot safely enumerate workspace path: {relative_parent or '.'}") from exc
        with_entries = entries
        for entry in with_entries:
            relative = f"{relative_parent}/{entry.name}" if relative_parent else entry.name
            if not entry.name or entry.name in {".", ".."} or "\x00" in entry.name:
                raise UnsafeWorkspacePathError("workspace contains an invalid path component")
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise UnsafeWorkspacePathError(f"cannot inspect workspace entry: {relative}") from exc
            if _is_reparse(Path(entry.path), info):
                raise UnsafeWorkspacePathError(f"workspace contains a symbolic link or reparse point: {relative}")
            if stat.S_ISDIR(info.st_mode):
                directories[relative] = Path(entry.path)
                stack.append((relative, Path(entry.path)))
            elif stat.S_ISREG(info.st_mode):
                files[relative] = Path(entry.path)
                total_bytes += int(info.st_size)
                if len(files) > max_files or total_bytes > max_bytes:
                    raise UnsafeWorkspacePathError("workspace exceeds the configured snapshot size limit")
            else:
                raise UnsafeWorkspacePathError(f"workspace contains an unsupported file type: {relative}")
    return files, directories


def _fingerprint(path: Path) -> FileFingerprint:
    before = path.lstat()
    if _is_reparse(path, before) or not stat.S_ISREG(before.st_mode):
        raise UnsafeWorkspacePathError(f"workspace file changed type during inspection: {path}")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise UnsafeWorkspacePathError(f"cannot open workspace file safely: {path}") from exc
    digest = hashlib.sha256()
    size = 0
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise UnsafeWorkspacePathError(f"workspace file changed during open: {path}")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
    finally:
        os.close(descriptor)
    after = path.lstat()
    if _is_reparse(path, after) or (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != (
        before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns
    ):
        raise UnsafeWorkspacePathError(f"workspace file changed while being read: {path}")
    return FileFingerprint(size, digest.hexdigest())


def _relative_confined(root: Path, relative: str) -> Path:
    parts = relative.split("/")
    if not relative or any(part in {"", ".", ".."} or "\x00" in part for part in parts):
        raise UnsafeWorkspacePathError(f"invalid workspace relative path: {relative!r}")
    path = root.joinpath(*parts)
    if not path.resolve(strict=False).is_relative_to(root):
        raise UnsafeWorkspacePathError(f"workspace path escapes its root: {relative}")
    return path


def create_workspace_snapshot(
    project_root: str | os.PathLike[str],
    staging_root: str | os.PathLike[str],
    *,
    max_files: int = _DEFAULT_MAX_FILES,
    max_bytes: int = _DEFAULT_MAX_BYTES,
) -> WorkspaceSnapshot:
    """Copy a real workspace into an empty private stage and record its baseline."""
    if isinstance(max_files, bool) or not isinstance(max_files, int) or max_files < 1:
        raise ValueError("max_files must be a positive integer")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
        raise ValueError("max_bytes must be a positive integer")
    source = _root(project_root)
    stage = _root(staging_root)
    if source == stage or source in stage.parents or stage in source.parents:
        raise UnsafeWorkspacePathError("source and staging workspace roots must be disjoint")
    if any(stage.iterdir()):
        raise UnsafeWorkspacePathError("staging workspace must be empty")

    files, directories = _scan(source, max_files=max_files, max_bytes=max_bytes)
    baseline = {relative: _fingerprint(path) for relative, path in files.items()}
    for relative in sorted(directories, key=lambda value: (value.count("/"), value.casefold())):
        if relative:
            _relative_confined(stage, relative).mkdir(exist_ok=True)
    for relative, path in files.items():
        target = _relative_confined(stage, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".lah-snapshot-{uuid.uuid4().hex}.tmp")
        try:
            shutil.copyfile(path, temporary, follow_symlinks=False)
            if _fingerprint(path) != baseline[relative]:
                raise UnsafeWorkspacePathError(f"workspace file changed during snapshot: {relative}")
            if _fingerprint(temporary) != baseline[relative]:
                raise UnsafeWorkspacePathError(f"snapshot copy verification failed: {relative}")
            os.replace(temporary, target)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    return WorkspaceSnapshot(source, stage, _identity(source), _identity(stage), MappingProxyType(baseline))


def _validate_tree(root: Path, *, max_files: int, max_bytes: int) -> tuple[dict[str, Path], dict[str, Path]]:
    if _root(root) != root:
        raise UnsafeWorkspacePathError("workspace root identity changed")
    return _scan(root, max_files=max_files, max_bytes=max_bytes)


def _ensure_parent_chain(root: Path, destination: Path) -> None:
    relative_parent = destination.parent.relative_to(root)
    current = root
    for part in relative_parent.parts:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            current.mkdir()
            info = current.lstat()
        if _is_reparse(current, info) or not stat.S_ISDIR(info.st_mode):
            raise UnsafeWorkspacePathError(f"destination parent is not a real directory: {current}")


def apply_workspace_changes(
    snapshot: WorkspaceSnapshot,
    *,
    max_files: int = _DEFAULT_MAX_FILES,
    max_bytes: int = _DEFAULT_MAX_BYTES,
) -> WorkspaceTransferResult:
    """Apply staged changes only when every corresponding source file is unchanged.

    All file conflicts are detected before the first write. Git metadata is
    included in the private snapshot for repository-aware tools, but never
    copied back into the live checkout.
    """
    source = _root(snapshot.source_root)
    stage = _root(snapshot.staging_root)
    if (source != snapshot.source_root or stage != snapshot.staging_root
            or _identity(source) != snapshot.source_identity
            or _identity(stage) != snapshot.staging_identity):
        raise UnsafeWorkspacePathError("workspace root identity changed since snapshot creation")
    source_files, source_dirs = _validate_tree(source, max_files=max_files, max_bytes=max_bytes)
    staged_files, staged_dirs = _validate_tree(stage, max_files=max_files, max_bytes=max_bytes)
    source_hashes = {name: _fingerprint(path) for name, path in source_files.items()}
    staged_hashes = {name: _fingerprint(path) for name, path in staged_files.items()}

    changed: list[str] = []
    conflicts: list[str] = []
    paths = set(snapshot.baseline) | set(staged_files)
    for relative in sorted(paths, key=str.casefold):
        if any(part.casefold() == ".git" for part in relative.split("/")):
            continue
        baseline = snapshot.baseline.get(relative)
        current = source_hashes.get(relative)
        staged = staged_hashes.get(relative)
        if baseline is None:
            if staged is not None:
                if current is not None or relative in source_dirs:
                    if current != staged:
                        conflicts.append(relative)
                    # Identical content already exists in the source.
                else:
                    changed.append(relative)
            continue
        if relative in source_dirs or relative in staged_dirs:
            if staged != baseline or current != baseline:
                conflicts.append(relative)
            continue
        if staged is None and current is None:
            continue
        if staged == baseline:
            continue
        if current == baseline:
            changed.append(relative)
        elif current == staged:
            continue
        else:
            conflicts.append(relative)
    if conflicts:
        return WorkspaceTransferResult((), tuple(conflicts))

    # Recheck all affected source paths immediately before mutation. This does
    # not certify a production-grade Windows path-race boundary; the caller
    # must retain the AppContainer launch gate until handle-relative access is
    # verified on the target OS.
    for relative in changed:
        current_path = _relative_confined(source, relative)
        staged_path = _relative_confined(stage, relative)
        expected = snapshot.baseline.get(relative)
        if expected is not None:
            if not current_path.exists() or _fingerprint(current_path) != expected:
                return WorkspaceTransferResult((), (relative,))
        if relative in staged_files and _fingerprint(staged_path) != staged_hashes[relative]:
            raise UnsafeWorkspacePathError(f"staged file changed during transfer: {relative}")

    applied: list[str] = []
    for relative in changed:
        destination = _relative_confined(source, relative)
        staged_path = _relative_confined(stage, relative)
        _ensure_parent_chain(source, destination)
        if relative in staged_files:
            temporary = destination.with_name(f".lah-transfer-{uuid.uuid4().hex}.tmp")
            try:
                shutil.copyfile(staged_path, temporary, follow_symlinks=False)
                if _fingerprint(staged_path) != staged_hashes[relative]:
                    raise UnsafeWorkspacePathError(f"staged file changed during transfer: {relative}")
                os.replace(temporary, destination)
            finally:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
        else:
            try:
                info = destination.lstat()
            except FileNotFoundError:
                info = None
            if info is not None:
                if _is_reparse(destination, info) or not stat.S_ISREG(info.st_mode):
                    raise UnsafeWorkspacePathError(f"delete target changed type during transfer: {relative}")
                if _fingerprint(destination) != snapshot.baseline[relative]:
                    return WorkspaceTransferResult((), (relative,))
                destination.unlink()
        applied.append(relative)
    return WorkspaceTransferResult(tuple(sorted(applied, key=str.casefold)), ())
