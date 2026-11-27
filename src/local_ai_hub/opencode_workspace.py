"""Bounded snapshots and conflict-aware result transfer for OpenCode workspaces.

This module never grants a process access to the source checkout. Callers must
keep the managed launch disabled until the Windows handle and AppContainer
boundary have been verified end to end.
"""
from __future__ import annotations

import ctypes
import hashlib
from ctypes import wintypes
import os
import stat
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping


class UnsafeWorkspacePathError(RuntimeError):
    """A snapshot contains a symlink, reparse point, or unsupported file type."""


class WorkspaceTransferError(RuntimeError):
    """A copyback failed; exposes paths whose rollback could not be confirmed."""

    def __init__(self, message: str, *, recovery_paths: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.recovery_paths = recovery_paths


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


@dataclass
class _PreparedChange:
    relative: str
    destination: Path
    content_temp: Path | None
    backup: Path | None
    expected: FileFingerprint | None


def _windows_set_delete_disposition(file_handle, delete: bool) -> None:
    class _Disposition(ctypes.Structure):
        _fields_ = [("DeleteFile", wintypes.BOOLEAN)]

    class _IoStatusBlock(ctypes.Structure):
        _fields_ = [("Status", ctypes.c_void_p), ("Information", ctypes.c_size_t)]

    ntdll = ctypes.WinDLL("ntdll")
    set_info = ntdll.NtSetInformationFile
    set_info.argtypes = (
        wintypes.HANDLE, ctypes.POINTER(_IoStatusBlock), ctypes.c_void_p,
        wintypes.DWORD, ctypes.c_int,
    )
    set_info.restype = ctypes.c_long
    status_to_error = ntdll.RtlNtStatusToDosError
    status_to_error.argtypes = (ctypes.c_long,)
    status_to_error.restype = wintypes.ULONG
    info = _Disposition(bool(delete))
    io_status = _IoStatusBlock()
    handle = getattr(file_handle, "handle", file_handle)
    status = set_info(handle, ctypes.byref(io_status), ctypes.byref(info), ctypes.sizeof(info), 13)
    if status < 0:
        raise ctypes.WinError(status_to_error(status))


def _windows_fingerprint_handle(file_handle) -> FileFingerprint:
    import win32con
    import win32file

    win32file.SetFilePointer(file_handle, 0, win32con.FILE_BEGIN)
    digest = hashlib.sha256()
    size = 0
    while True:
        data = win32file.ReadFile(file_handle, 1024 * 1024)[1]
        if not data:
            break
        digest.update(data)
        size += len(data)
    return FileFingerprint(size, digest.hexdigest())


def _windows_open_regular_file(path: Path):
    import win32api
    import win32con
    import win32file

    try:
        observed = path.lstat()
    except FileNotFoundError:
        observed = None
    if observed is not None and (_is_reparse(path, observed) or not stat.S_ISREG(observed.st_mode)):
        raise UnsafeWorkspacePathError(f"workspace file changed type during copyback: {path}")
    try:
        handle = win32file.CreateFile(
            str(path), 0x80000000 | 0x00010000,  # GENERIC_READ | DELETE
            win32con.FILE_SHARE_READ, None, win32con.OPEN_EXISTING,
            0x00200000, None,  # OPEN_REPARSE_POINT
        )
    except Exception as exc:
        error_code = getattr(exc, "winerror", None)
        if error_code is None and exc.args:
            error_code = exc.args[0]
        if error_code in {2, 3}:
            return None
        raise
    try:
        native = win32file.GetFileInformationByHandle(handle)
        attrs = int(native[0])
        index = (int(native[8]) << 32) | int(native[9])
        if (attrs & _REPARSE_POINT or attrs & 0x10
                or observed is None or index != int(observed.st_ino)):
            raise UnsafeWorkspacePathError(f"workspace file changed while opening for copyback: {path}")
        return handle
    except Exception:
        win32api.CloseHandle(handle)
        raise


def _windows_open_parent_directory(path: Path):
    import win32api
    import win32con
    import win32file

    observed = path.lstat()
    handle = win32file.CreateFile(
        str(path), 0x80 | 0x2,  # FILE_READ_ATTRIBUTES | FILE_ADD_FILE
        win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE | win32con.FILE_SHARE_DELETE,
        None, win32con.OPEN_EXISTING, 0x02000000 | 0x00200000, None,
    )
    try:
        native = win32file.GetFileInformationByHandle(handle)
        attrs = int(native[0])
        index = (int(native[8]) << 32) | int(native[9])
        if (_is_reparse(path, observed) or not stat.S_ISDIR(observed.st_mode)
                or attrs & _REPARSE_POINT or not attrs & 0x10
                or index != int(observed.st_ino)):
            raise UnsafeWorkspacePathError(f"workspace parent changed while opening for copyback: {path}")
        return handle
    except Exception:
        win32api.CloseHandle(handle)
        raise


def _apply_windows_prepared_changes(
    prepared: list[_PreparedChange],
    staged_hashes: Mapping[str, FileFingerprint],
    preserve_recovery: set[Path],
) -> WorkspaceTransferResult:
    """Commit copyback with pinned file handles and no-replace renames."""
    import win32api

    states: dict[int, dict[str, object]] = {}
    changed_paths: list[str] = []
    committed: list[_PreparedChange] = []

    def close_state_handle(state: dict[str, object], key: str) -> None:
        handle = state.get(key)
        if handle is not None:
            win32api.CloseHandle(handle)
            state[key] = None

    try:
        for change in prepared:
            state: dict[str, object] = {
                "parent": None, "source": None, "content": None,
                "source_moved": False, "content_moved": False,
                "displaced": None, "delete_marked": False,
            }
            states[id(change)] = state
            state["parent"] = _windows_open_parent_directory(change.destination.parent)
            state["source"] = _windows_open_regular_file(change.destination)
            if (state["source"] is None) != (change.expected is None):
                return WorkspaceTransferResult((), (change.relative,))
            if state["source"] is not None:
                if _windows_fingerprint_handle(state["source"]) != change.expected:
                    return WorkspaceTransferResult((), (change.relative,))
            if change.content_temp is not None:
                state["content"] = _windows_open_regular_file(change.content_temp)
                if (state["content"] is None
                        or _windows_fingerprint_handle(state["content"]) != staged_hashes[change.relative]):
                    raise UnsafeWorkspacePathError(f"staged file changed during transfer: {change.relative}")

        try:
            for change in prepared:
                state = states[id(change)]
                parent = state["parent"]
                source_handle = state["source"]
                content_handle = state["content"]
                if source_handle is not None:
                    displaced = change.destination.parent / f".lah-displaced-{uuid.uuid4().hex}.tmp"
                    state["displaced"] = displaced
                    _rename_handle_relative(source_handle, parent, displaced.name)
                    state["source_moved"] = True
                    committed.append(change)
                if content_handle is not None:
                    _rename_handle_relative(content_handle, parent, change.destination.name)
                    state["content_moved"] = True
                    if change not in committed:
                        committed.append(change)

            for change in prepared:
                state = states[id(change)]
                if state["source_moved"]:
                    _windows_set_delete_disposition(state["source"], True)
                    state["delete_marked"] = True
        except Exception as exc:
            recovery_paths: list[str] = []
            for state in states.values():
                if state["delete_marked"]:
                    try:
                        _windows_set_delete_disposition(state["source"], False)
                        state["delete_marked"] = False
                    except Exception:
                        change = next(item for item in prepared if states[id(item)] is state)
                        recovery_paths.extend(
                            str(path) for path in (state["displaced"], change.backup) if path is not None
                        )
            for change in reversed(committed):
                state = states[id(change)]
                try:
                    if state["content_moved"]:
                        _windows_set_delete_disposition(state["content"], True)
                        close_state_handle(state, "content")
                        state["content_moved"] = False
                    if state["source_moved"]:
                        _rename_handle_relative(state["source"], state["parent"], change.destination.name)
                        state["source_moved"] = False
                except Exception:
                    recovery_paths.extend(
                        str(path) for path in (state["displaced"] or change.destination, change.backup)
                        if path is not None
                    )
            if recovery_paths:
                preserve_recovery.update(Path(path) for path in recovery_paths if path)
                raise WorkspaceTransferError(
                    "workspace transfer failed and rollback could not be confirmed",
                    recovery_paths=tuple(dict.fromkeys(recovery_paths)),
                ) from exc
            raise WorkspaceTransferError("workspace transfer failed; committed files were rolled back") from exc

        for change in prepared:
            state = states[id(change)]
            if state["source_moved"]:
                close_state_handle(state, "source")
            changed_paths.append(change.relative)
        return WorkspaceTransferResult(tuple(sorted(changed_paths, key=str.casefold)), ())
    finally:
        for state in states.values():
            for key in ("content", "source", "parent"):
                try:
                    close_state_handle(state, key)
                except Exception:
                    pass


_REPARSE_POINT = 0x400
_DEFAULT_MAX_FILES = 100_000
_DEFAULT_MAX_BYTES = 4 * 1024 * 1024 * 1024


def _rename_handle_relative(file_handle, parent_handle, name: str) -> None:
    """Rename an open file under an open directory without replacing a name.

    The source handle pins the file object and RootDirectory pins the target
    directory.  FILE_RENAME_INFO's ReplaceIfExists flag is deliberately false.
    """
    if os.name != "nt":
        raise OSError("handle-relative rename is available only on Windows")
    if (not name or name in {".", ".."} or "\\" in name or "/" in name
            or ":" in name or "\x00" in name):
        raise ValueError("rename target must be a single relative file name")

    class _RenameInfo(ctypes.Structure):
        _fields_ = [
            ("ReplaceIfExists", wintypes.BOOL),
            ("RootDirectory", wintypes.HANDLE),
            ("FileNameLength", wintypes.DWORD),
            ("FileName", wintypes.WCHAR * 1),
        ]

    encoded = name.encode("utf-16-le")
    size = _RenameInfo.FileName.offset + len(encoded)
    storage = ctypes.create_string_buffer(size)
    info = ctypes.cast(storage, ctypes.POINTER(_RenameInfo)).contents
    info.ReplaceIfExists = False
    info.RootDirectory = getattr(parent_handle, "handle", parent_handle)
    info.FileNameLength = len(encoded)
    ctypes.memmove(ctypes.addressof(storage) + _RenameInfo.FileName.offset, encoded, len(encoded))

    class _IoStatusBlock(ctypes.Structure):
        _fields_ = [("Status", ctypes.c_void_p), ("Information", ctypes.c_size_t)]

    ntdll = ctypes.WinDLL("ntdll")
    set_info = ntdll.NtSetInformationFile
    set_info.argtypes = (
        wintypes.HANDLE, ctypes.POINTER(_IoStatusBlock), ctypes.c_void_p,
        wintypes.DWORD, ctypes.c_int,
    )
    set_info.restype = ctypes.c_long
    status_to_error = ntdll.RtlNtStatusToDosError
    status_to_error.argtypes = (ctypes.c_long,)
    status_to_error.restype = wintypes.ULONG
    raw_handle = getattr(file_handle, "handle", file_handle)
    io_status = _IoStatusBlock()
    status = set_info(raw_handle, ctypes.byref(io_status), ctypes.byref(storage), size, 10)
    if status < 0:
        raise ctypes.WinError(status_to_error(status))


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


def _windows_file_identity(info) -> tuple[int, int, int]:
    """Return the Win32 volume serial and 64-bit file-index fields."""
    if len(info) < 10:
        raise ValueError("Win32 file information tuple is incomplete")
    return int(info[4]), int(info[8]), int(info[9])


@contextmanager
def _lock_workspace_tree(root: Path, *, root_handle: int | None = None):
    """Hold each Windows ancestor/directory without delete sharing while walking."""
    root = Path(os.path.abspath(os.fspath(root)))
    if os.name != "nt":
        yield lambda _path: None
        return
    if not root.drive or root.anchor.startswith("\\\\"):
        raise UnsafeWorkspacePathError("Windows workspace must be on a local drive")

    import win32api
    import win32con
    import win32file

    handles = []
    locked_paths: set[str] = set()

    def open_directory(path: Path, expected: os.stat_result | None = None, *, lock: bool = True) -> None:
        path = Path(os.path.abspath(os.fspath(path)))
        key = os.path.normcase(os.fspath(path))
        if key in locked_paths:
            return
        info = path.lstat() if expected is None else expected
        if _is_reparse(path, info) or not stat.S_ISDIR(info.st_mode):
            raise UnsafeWorkspacePathError(f"workspace directory is a reparse point or changed type: {path}")
        handle = win32file.CreateFile(
            str(path), 0x80 | (0x00010000 if lock else 0),  # FILE_READ_ATTRIBUTES | DELETE
            win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
            None, win32con.OPEN_EXISTING,
            0x02000000 | 0x00200000,  # BACKUP_SEMANTICS | OPEN_REPARSE_POINT
            None,
        )
        try:
            native = win32file.GetFileInformationByHandle(handle)
            attributes = int(native[0])
            file_index = (int(native[8]) << 32) | int(native[9])
            if attributes & _REPARSE_POINT or not attributes & 0x10:
                raise UnsafeWorkspacePathError(f"workspace directory opened as a reparse point: {path}")
            if file_index != int(info.st_ino):
                raise UnsafeWorkspacePathError(f"workspace directory changed while opening: {path}")
            handles.append(handle)
            locked_paths.add(key)
        except Exception:
            win32api.CloseHandle(handle)
            raise

    try:
        current = Path(root.anchor)
        open_directory(current, lock=False)
        for part in root.parts[1:]:
            current = current / part
            if current == root and root_handle is not None:
                info = current.lstat()
                expected = win32file.GetFileInformationByHandle(root_handle)
                path_handle = win32file.CreateFile(
                    str(current), 0x80,
                    win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE | win32con.FILE_SHARE_DELETE,
                    None, win32con.OPEN_EXISTING,
                    0x02000000 | 0x00200000, None,
                )
                try:
                    observed = win32file.GetFileInformationByHandle(path_handle)
                    if (_is_reparse(current, info) or not stat.S_ISDIR(info.st_mode)
                            or int(observed[0]) & _REPARSE_POINT or not int(observed[0]) & 0x10
                            or _windows_file_identity(observed) != _windows_file_identity(expected)
                            or ((int(observed[8]) << 32) | int(observed[9])) != int(info.st_ino)):
                        raise UnsafeWorkspacePathError("managed stage handle does not identify the workspace root")
                finally:
                    win32api.CloseHandle(path_handle)
                locked_paths.add(os.path.normcase(os.fspath(Path(os.path.abspath(os.fspath(current))))))
            else:
                open_directory(current, lock=current == root)

        stack = [root]
        while stack:
            directory = stack.pop()
            try:
                entries = list(os.scandir(directory))
            except OSError as exc:
                raise UnsafeWorkspacePathError(f"cannot safely enumerate workspace path: {directory}") from exc
            for entry in entries:
                path = Path(entry.path)
                try:
                    info = path.lstat()
                except OSError as exc:
                    raise UnsafeWorkspacePathError(f"cannot inspect workspace entry: {path}") from exc
                if _is_reparse(path, info):
                    raise UnsafeWorkspacePathError(f"workspace contains a symbolic link or reparse point: {path}")
                if stat.S_ISDIR(info.st_mode):
                    open_directory(path, info)
                    stack.append(path)
        yield open_directory
    finally:
        for handle in reversed(handles):
            try:
                win32api.CloseHandle(handle)
            except Exception:
                pass


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


def _read_workspace_file(path: Path, output_path: Path | None = None) -> FileFingerprint:
    before = path.lstat()
    if _is_reparse(path, before) or not stat.S_ISREG(before.st_mode):
        raise UnsafeWorkspacePathError(f"workspace file changed type during inspection: {path}")
    output = output_path.open("wb") if output_path is not None else None
    if os.name == "nt":
        import win32api
        import win32con
        import win32file

        try:
            handle = win32file.CreateFile(
                str(path), win32con.GENERIC_READ | 0x00010000,  # GENERIC_READ | DELETE
                win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
                None, win32con.OPEN_EXISTING, 0x00200000 | 0x08000000, None,
            )
        except Exception as exc:
            if output is not None:
                output.close()
            raise UnsafeWorkspacePathError(f"cannot open workspace file without following reparse points: {path}") from exc
        try:
            opened = win32file.GetFileInformationByHandle(handle)
            attributes = int(opened[0])
            file_index = (int(opened[8]) << 32) | int(opened[9])
            size_on_handle = (int(opened[5]) << 32) | int(opened[6])
            if attributes & (_REPARSE_POINT | 0x10 | 0x40) or file_index != int(before.st_ino):
                raise UnsafeWorkspacePathError(f"workspace file changed or resolved to a reparse point: {path}")
            if size_on_handle != int(before.st_size):
                raise UnsafeWorkspacePathError(f"workspace file changed while being opened: {path}")
            digest = hashlib.sha256()
            size = 0
            while True:
                _, chunk = win32file.ReadFile(handle, 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
                if output is not None:
                    output.write(chunk)
            after = win32file.GetFileInformationByHandle(handle)
            stable_fields = (1, 3, 4, 5, 6, 8, 9)
            if tuple(opened[index] for index in stable_fields) != tuple(after[index] for index in stable_fields):
                raise UnsafeWorkspacePathError(f"workspace file changed while being read: {path}")
            if size != size_on_handle:
                raise UnsafeWorkspacePathError(f"workspace file length changed while being read: {path}")
            return FileFingerprint(size, digest.hexdigest())
        finally:
            win32api.CloseHandle(handle)
            if output is not None:
                output.close()

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        if output is not None:
            output.close()
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
                if output is not None:
                    output.write(chunk)
    finally:
        os.close(descriptor)
        if output is not None:
            output.close()
    after = path.lstat()
    if _is_reparse(path, after) or (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != (
        before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns
    ):
        raise UnsafeWorkspacePathError(f"workspace file changed while being read: {path}")
    return FileFingerprint(size, digest.hexdigest())


def _fingerprint(path: Path) -> FileFingerprint:
    return _read_workspace_file(path)


def _relative_confined(root: Path, relative: str) -> Path:
    parts = relative.split("/")
    if not relative or any(part in {"", ".", ".."} or "\x00" in part for part in parts):
        raise UnsafeWorkspacePathError(f"invalid workspace relative path: {relative!r}")
    path = root.joinpath(*parts)
    if not path.resolve(strict=False).is_relative_to(root):
        raise UnsafeWorkspacePathError(f"workspace path escapes its root: {relative}")
    return path


def _create_workspace_snapshot_unlocked(
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
            copied = _read_workspace_file(path, temporary)
            if copied != baseline[relative]:
                raise UnsafeWorkspacePathError(f"snapshot copy verification failed: {relative}")
            os.replace(temporary, target)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    return WorkspaceSnapshot(source, stage, _identity(source), _identity(stage), MappingProxyType(baseline))


def create_workspace_snapshot(
    project_root: str | os.PathLike[str],
    staging_root: str | os.PathLike[str],
    *,
    max_files: int = _DEFAULT_MAX_FILES,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    staging_handle: int | None = None,
) -> WorkspaceSnapshot:
    source = _root(project_root)
    stage = _root(staging_root)
    with _lock_workspace_tree(source):
        with _lock_workspace_tree(stage, root_handle=staging_handle):
            return _create_workspace_snapshot_unlocked(
                source, stage, max_files=max_files, max_bytes=max_bytes
            )


def _validate_tree(root: Path, *, max_files: int, max_bytes: int) -> tuple[dict[str, Path], dict[str, Path]]:
    if _root(root) != root:
        raise UnsafeWorkspacePathError("workspace root identity changed")
    return _scan(root, max_files=max_files, max_bytes=max_bytes)


def _ensure_parent_chain(root: Path, destination: Path) -> tuple[Path, ...]:
    relative_parent = destination.parent.relative_to(root)
    current = root
    created: list[Path] = []
    for part in relative_parent.parts:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            current.mkdir()
            created.append(current)
            info = current.lstat()
        if _is_reparse(current, info) or not stat.S_ISDIR(info.st_mode):
            raise UnsafeWorkspacePathError(f"destination parent is not a real directory: {current}")
    return tuple(created)


def _apply_workspace_changes_unlocked(
    snapshot: WorkspaceSnapshot,
    *,
    max_files: int = _DEFAULT_MAX_FILES,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    lock_source_directory=None,
    created_directories: list[Path] | None = None,
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

    # This path-based pass rejects ordinary conflicts before preparing writes.
    # The Windows commit path repeats the check under pinned file handles and
    # uses handle-relative no-replace renames. The launcher remains gated until
    # the separate AppContainer, pipe, and token-cleanup path passes E2E.
    for relative in changed:
        current_path = _relative_confined(source, relative)
        staged_path = _relative_confined(stage, relative)
        expected = snapshot.baseline.get(relative)
        if expected is not None:
            if not current_path.exists() or _fingerprint(current_path) != expected:
                return WorkspaceTransferResult((), (relative,))
        if relative in staged_files and _fingerprint(staged_path) != staged_hashes[relative]:
            raise UnsafeWorkspacePathError(f"staged file changed during transfer: {relative}")

    prepared: list[_PreparedChange] = []
    created_directories = created_directories if created_directories is not None else []
    committed: list[_PreparedChange] = []
    preserve_recovery: set[Path] = set()
    try:
        for relative in changed:
            destination = _relative_confined(source, relative)
            staged_path = _relative_confined(stage, relative)
            new_directories = _ensure_parent_chain(source, destination)
            created_directories.extend(new_directories)
            if lock_source_directory is not None:
                for directory in new_directories:
                    lock_source_directory(directory)
            expected = snapshot.baseline.get(relative)
            try:
                info = destination.lstat()
            except FileNotFoundError:
                info = None
            if info is not None and (_is_reparse(destination, info) or not stat.S_ISREG(info.st_mode)):
                return WorkspaceTransferResult((), (relative,))
            current = _fingerprint(destination) if info is not None else None
            if current != expected:
                return WorkspaceTransferResult((), (relative,))

            content_temp = None
            if relative in staged_files:
                descriptor, temp_name = tempfile.mkstemp(prefix=".lah-transfer-", suffix=".tmp", dir=destination.parent)
                os.close(descriptor)
                content_temp = Path(temp_name)
                if _read_workspace_file(staged_path, content_temp) != staged_hashes[relative]:
                    raise UnsafeWorkspacePathError(f"staged file changed during transfer: {relative}")

            backup = None
            if current is not None:
                descriptor, backup_name = tempfile.mkstemp(prefix=".lah-backup-", suffix=".tmp", dir=destination.parent)
                os.close(descriptor)
                backup = Path(backup_name)
                if _read_workspace_file(destination, backup) != current:
                    raise UnsafeWorkspacePathError(f"source file changed while preparing transfer: {relative}")
            prepared.append(_PreparedChange(relative, destination, content_temp, backup, expected))

        # Recheck the full write set after preparing temporary files and before
        # committing the first destination mutation.
        for change in prepared:
            try:
                info = change.destination.lstat()
            except FileNotFoundError:
                info = None
            if info is not None and (_is_reparse(change.destination, info) or not stat.S_ISREG(info.st_mode)):
                return WorkspaceTransferResult((), (change.relative,))
            current = _fingerprint(change.destination) if info is not None else None
            if current != change.expected:
                return WorkspaceTransferResult((), (change.relative,))

        if os.name == "nt":
            return _apply_windows_prepared_changes(prepared, staged_hashes, preserve_recovery)

        try:
            for change in prepared:
                if change.content_temp is not None:
                    os.replace(change.content_temp, change.destination)
                    change.content_temp = None
                else:
                    change.destination.unlink()
                committed.append(change)
        except Exception as exc:
            recovery_paths: list[str] = []
            for change in reversed(committed):
                try:
                    if change.backup is not None:
                        os.replace(change.backup, change.destination)
                        change.backup = None
                    else:
                        change.destination.unlink(missing_ok=True)
                except Exception:
                    recovery_paths.append(str(change.backup or change.destination))
            if recovery_paths:
                preserve_recovery.update(Path(path) for path in recovery_paths)
                raise WorkspaceTransferError(
                    "workspace transfer failed and rollback could not be confirmed",
                    recovery_paths=tuple(recovery_paths),
                ) from exc
            raise WorkspaceTransferError("workspace transfer failed; committed files were rolled back") from exc

        return WorkspaceTransferResult(tuple(sorted(changed, key=str.casefold)), ())
    finally:
        for change in prepared:
            for temporary in (change.content_temp, change.backup):
                if temporary is not None and temporary not in preserve_recovery:
                    try:
                        temporary.unlink(missing_ok=True)
                    except OSError:
                        pass


def apply_workspace_changes(
    snapshot: WorkspaceSnapshot,
    *,
    max_files: int = _DEFAULT_MAX_FILES,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    staging_handle: int | None = None,
) -> WorkspaceTransferResult:
    source = _root(snapshot.source_root)
    stage = _root(snapshot.staging_root)
    created_directories: list[Path] = []
    try:
        with _lock_workspace_tree(source) as lock_source_directory:
            with _lock_workspace_tree(stage, root_handle=staging_handle):
                result = _apply_workspace_changes_unlocked(
                    snapshot, max_files=max_files, max_bytes=max_bytes,
                    lock_source_directory=lock_source_directory,
                    created_directories=created_directories,
                )
    except Exception:
        for directory in reversed(created_directories):
            try:
                directory.rmdir()
            except OSError:
                pass
        raise
    if result.conflicts:
        for directory in reversed(created_directories):
            try:
                directory.rmdir()
            except OSError:
                pass
    return result
