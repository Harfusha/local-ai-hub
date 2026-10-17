"""Safe ownership tracking for installed agent skill directories.

This module deliberately uses only the standard library so setup and uninstall
can use it before the Local AI Hub runtime is available.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import TypeGuard

MANIFEST_NAME = ".local-ai-hub-skill-ownership.json"
MANIFEST_VERSION = 1
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


_LOCK_TIMEOUT_SECONDS = 30.0
_PATH_LOCKS: dict[str, threading.RLock] = {}
_PATH_LOCKS_GUARD = threading.Lock()


class _PinnedQuarantine:
    def __init__(
        self,
        path: Path,
        root_path: Path,
        *,
        parent_fd: int | None = None,
        directory_fd: int | None = None,
        parent_handle: int | None = None,
        directory_handle: int | None = None,
    ) -> None:
        self.path = path
        self.root_path = root_path
        self.key = os.path.normcase(os.path.abspath(str(path)))
        self.parent_fd = parent_fd
        self.directory_fd = directory_fd
        self.parent_handle = parent_handle
        self.directory_handle = directory_handle
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if os.name == "nt":
            close_handle = _windows_close_handle()
            try:
                if self.directory_handle is not None:
                    close_handle(self.directory_handle)
            finally:
                if self.parent_handle is not None:
                    close_handle(self.parent_handle)
            return
        try:
            if self.directory_fd is not None:
                os.close(self.directory_fd)
        finally:
            if self.parent_fd is not None:
                os.close(self.parent_fd)

    def __enter__(self) -> _PinnedQuarantine:
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()

    def is_current(self) -> bool:
        if os.name == "nt":
            if self.directory_handle is None or self.parent_handle is None:
                return False
            parent = directory = None
            try:
                parent = _open_windows_directory(self.root_path.parent, 0, 0x1 | 0x2)
                directory = _open_windows_directory(self.root_path, 0, 0x1 | 0x2)
                return (
                    _windows_handle_identity(parent)[:2]
                    == _windows_handle_identity(self.parent_handle)[:2]
                    and _windows_handle_identity(directory)[:2]
                    == _windows_handle_identity(self.directory_handle)[:2]
                )
            except OSError:
                return False
            finally:
                close_handle = _windows_close_handle()
                try:
                    if directory is not None:
                        close_handle(directory)
                finally:
                    if parent is not None:
                        close_handle(parent)
        if self.directory_fd is None or self.parent_fd is None:
            return False
        try:
            named = os.stat(self.root_path.name, dir_fd=self.parent_fd, follow_symlinks=False)
        except OSError:
            return False
        pinned = os.fstat(self.directory_fd)
        return named.st_dev == pinned.st_dev and named.st_ino == pinned.st_ino

    def entry_presence(self, leaf: str) -> bool | None:
        if os.name == "nt":
            # Path-based lstat can follow a substituted ancestor even when a
            # prior is_current check succeeded. Do not claim presence without
            # a genuine handle-relative child lookup.
            return None
        if self.directory_fd is None:
            try:
                (self.path / leaf).lstat()
                return True
            except FileNotFoundError:
                return False
            except OSError:
                return None
        try:
            os.stat(leaf, dir_fd=self.directory_fd, follow_symlinks=False)
            return True
        except FileNotFoundError:
            return False
        except OSError:
            return None


class _PinnedSource:
    """Keep the source parent and directory identity stable across hashing and rename."""

    def __init__(
        self,
        path: Path,
        *,
        parent_fd: int | None = None,
        source_fd: int | None = None,
        identity: tuple[int, int] | None = None,
        parent_handle: int | None = None,
        directory_handle: int | None = None,
        parent_identity: tuple[int, int] | None = None,
    ) -> None:
        self.path = path
        self.parent_fd = parent_fd
        self.source_fd = source_fd
        self.identity = identity
        self.parent_handle = parent_handle
        self.directory_handle = directory_handle
        self.parent_identity = parent_identity
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if os.name == "nt":
            close_handle = _windows_close_handle()
            try:
                if self.directory_handle is not None:
                    close_handle(self.directory_handle)
            finally:
                if self.parent_handle is not None:
                    close_handle(self.parent_handle)
            return
        try:
            if self.source_fd is not None:
                os.close(self.source_fd)
        finally:
            if self.parent_fd is not None:
                os.close(self.parent_fd)


class _AmbiguousMoveError(OSError):
    """The source leaf raced identity validation and its final location is uncertain."""


def _windows_close_handle():
    import ctypes
    from ctypes import wintypes

    close_handle = ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    return close_handle


def _windows_handle_identity(handle: int) -> tuple[int, int, int]:
    import ctypes
    from ctypes import wintypes

    class _FileInformation(ctypes.Structure):
        _fields_ = [
            ("attributes", wintypes.DWORD), ("creation_time", wintypes.FILETIME),
            ("last_access_time", wintypes.FILETIME), ("last_write_time", wintypes.FILETIME),
            ("volume_serial_number", wintypes.DWORD), ("file_size_high", wintypes.DWORD),
            ("file_size_low", wintypes.DWORD), ("number_of_links", wintypes.DWORD),
            ("file_index_high", wintypes.DWORD), ("file_index_low", wintypes.DWORD),
        ]

    function = ctypes.WinDLL("kernel32", use_last_error=True).GetFileInformationByHandle
    function.argtypes = [wintypes.HANDLE, ctypes.POINTER(_FileInformation)]
    function.restype = wintypes.BOOL
    info = _FileInformation()
    if not function(handle, ctypes.byref(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    file_index = (int(info.file_index_high) << 32) | int(info.file_index_low)
    return int(info.volume_serial_number), file_index, int(info.attributes)


def _pin_source(path: Path) -> _PinnedSource:
    if os.name == "nt":
        parent = _open_windows_directory(path.parent, 0, 0x1 | 0x2)
        directory = None
        try:
            # DELETE access is needed for FileRenameInfo; omitting FILE_SHARE_DELETE
            # pins the source entry while its hash is measured and moved.
            directory = _open_windows_directory(path, 0x00010000, 0x1 | 0x2)
            parent_identity = _windows_handle_identity(parent)[:2]
            identity = _windows_handle_identity(directory)[:2]
            return _PinnedSource(
                path,
                identity=identity,
                parent_handle=parent,
                directory_handle=directory,
                parent_identity=parent_identity,
            )
        except BaseException:
            try:
                if directory is not None:
                    _windows_close_handle()(directory)
            finally:
                _windows_close_handle()(parent)
            raise

    parent_fd = _open_posix_directory_chain(path.parent)
    source_fd = None
    try:
        source_fd = os.open(path.name, _posix_directory_flags(), dir_fd=parent_fd)
        info = os.fstat(source_fd)
        if not stat.S_ISDIR(info.st_mode):
            raise OSError(f"skill source is not a regular directory: {path}")
        return _PinnedSource(
            path,
            parent_fd=parent_fd,
            source_fd=source_fd,
            identity=(info.st_dev, info.st_ino),
        )
    except BaseException:
        try:
            if source_fd is not None:
                os.close(source_fd)
        finally:
            os.close(parent_fd)
        raise


def _source_is_current(source: _PinnedSource) -> bool:
    if os.name == "nt":
        parent = directory = None
        try:
            parent = _open_windows_directory(source.path.parent, 0, 0x1 | 0x2)
            directory = _open_windows_directory(source.path, 0, 0x1 | 0x2)
        except OSError:
            close_handle = _windows_close_handle()
            try:
                if directory is not None:
                    close_handle(directory)
            finally:
                if parent is not None:
                    close_handle(parent)
            return False
        close_handle = _windows_close_handle()
        try:
            return (
                _windows_handle_identity(parent)[:2] == source.parent_identity
                and _windows_handle_identity(directory)[:2] == source.identity
            )
        finally:
            try:
                close_handle(directory)
            finally:
                close_handle(parent)
    if source.parent_fd is None or source.source_fd is None or source.identity is None:
        return False
    try:
        current_parent = _open_posix_directory_chain(source.path.parent)
    except OSError:
        return False
    try:
        pinned_parent = os.fstat(source.parent_fd)
        observed_parent = os.fstat(current_parent)
        observed = os.stat(source.path.name, dir_fd=source.parent_fd, follow_symlinks=False)
        pinned_source = os.fstat(source.source_fd)
        return (
            (pinned_parent.st_dev, pinned_parent.st_ino) == (observed_parent.st_dev, observed_parent.st_ino)
            and stat.S_ISDIR(observed.st_mode)
            and (observed.st_dev, observed.st_ino) == source.identity
            and (pinned_source.st_dev, pinned_source.st_ino) == source.identity
        )
    except OSError:
        return False
    finally:
        os.close(current_parent)


def _posix_directory_flags() -> int:
    import errno

    required = ("O_DIRECTORY", "O_NOFOLLOW", "O_CLOEXEC")
    values = [getattr(os, name, 0) for name in required]
    if any(type(value) is not int or value == 0 for value in values):
        raise OSError(
            errno.ENOTSUP,
            "secure directory-relative operations require O_DIRECTORY, O_NOFOLLOW, and O_CLOEXEC",
        )
    supports_dir_fd = getattr(os, "supports_dir_fd", set())
    if os.open not in supports_dir_fd or os.mkdir not in supports_dir_fd:
        raise OSError(errno.ENOTSUP, "secure directory-relative operations are unavailable")
    return os.O_RDONLY | values[0] | values[1] | values[2]


def _open_posix_directory_chain(path: Path) -> int:
    flags = _posix_directory_flags()
    if not path.is_absolute() or path.anchor != "/" or any(part in (".", "..") for part in path.parts[1:]):
        raise OSError("secure directory path must be normalized and absolute")
    current_fd = os.open("/", flags)
    try:
        for part in path.parts[1:]:
            next_fd = os.open(part, flags, dir_fd=current_fd)
            previous_fd = current_fd
            current_fd = next_fd
            os.close(previous_fd)
        if not stat.S_ISDIR(os.fstat(current_fd).st_mode):
            raise OSError(f"directory path is not a directory: {path}")
        return current_fd
    except BaseException:
        os.close(current_fd)
        raise


def _open_windows_directory(path: Path, access: int, share: int) -> int:
    import ctypes
    from ctypes import wintypes

    class _FileAttributeTagInfo(ctypes.Structure):
        _fields_ = [("attributes", wintypes.DWORD), ("reparse_tag", wintypes.DWORD)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    get_info = kernel32.GetFileInformationByHandleEx
    get_info.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    get_info.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    handle = create_file(
        str(path),
        access | 0x80,  # FILE_READ_ATTRIBUTES
        share,
        None,
        3,  # OPEN_EXISTING
        0x02000000 | 0x00200000,  # BACKUP_SEMANTICS | OPEN_REPARSE_POINT
        None,
    )
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    info = _FileAttributeTagInfo()
    if not get_info(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):  # FileAttributeTagInfo
        error = ctypes.get_last_error()
        close_handle(handle)
        raise ctypes.WinError(error)
    if info.attributes & (_REPARSE_POINT | 0x10) != 0x10:
        close_handle(handle)
        raise OSError(f"skill quarantine parent is not a regular directory: {path}")
    return handle


def _open_ownership_lock_file(lock_path: Path) -> int:
    if os.name != "nt":
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        if type(nofollow) is not int or nofollow == 0:
            raise OSError("skill ownership lock requires POSIX O_NOFOLLOW support")
        flags = os.O_CREAT | os.O_RDWR
        flags |= nofollow
        return os.open(lock_path, flags, 0o600)

    import ctypes
    import msvcrt
    from ctypes import wintypes

    class _FileInformation(ctypes.Structure):
        _fields_ = [
            ("attributes", wintypes.DWORD),
            ("creation_time", wintypes.FILETIME),
            ("last_access_time", wintypes.FILETIME),
            ("last_write_time", wintypes.FILETIME),
            ("volume_serial_number", wintypes.DWORD),
            ("file_size_high", wintypes.DWORD),
            ("file_size_low", wintypes.DWORD),
            ("number_of_links", wintypes.DWORD),
            ("file_index_high", wintypes.DWORD),
            ("file_index_low", wintypes.DWORD),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    get_file_information = kernel32.GetFileInformationByHandle
    get_file_information.argtypes = [wintypes.HANDLE, ctypes.POINTER(_FileInformation)]
    get_file_information.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    handle = create_file(str(lock_path), 0x80000000 | 0x40000000, 0x1 | 0x2, None, 4, 0x00200000, None)
    invalid_handle = ctypes.c_void_p(-1).value
    if handle == invalid_handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        information = _FileInformation()
        if not get_file_information(handle, ctypes.byref(information)):
            raise ctypes.WinError(ctypes.get_last_error())
        if information.attributes & (_REPARSE_POINT | 0x10):
            raise OSError(f"skill ownership lock is not a regular file: {lock_path}")
        if information.number_of_links != 1:
            raise OSError(f"skill ownership lock has unexpected hard links: {lock_path}")
        return msvcrt.open_osfhandle(handle, os.O_RDWR)
    except BaseException:
        close_handle(handle)
        raise


def _rename_noreplace(
    source: Path,
    destination: Path,
    *,
    quarantine_directory: _PinnedQuarantine | None = None,
    source_pin: _PinnedSource | None = None,
) -> None:
    """Move one path without replacing an existing destination, or fail closed."""
    if os.name == "nt":
        _rename_noreplace_windows(source, destination, quarantine_directory, source_pin)
        return
    if sys.platform.startswith("linux"):
        import ctypes
        owns_source_pin = source_pin is None
        if source_pin is None:
            source_pin = _pin_source(source)
        source_fd = destination_fd = None
        close_destination_fd = quarantine_directory is None
        try:
            if (
                source_pin is None
                or source_pin.parent_fd is None
                or source_pin.source_fd is None
                or not _source_is_current(source_pin)
            ):
                raise OSError("skill source identity changed before quarantine move")
            source_fd = source_pin.parent_fd
            pinned_source = os.fstat(source_pin.source_fd)
            pinned_source_identity = (pinned_source.st_dev, pinned_source.st_ino)
            if quarantine_directory is None:
                destination_fd = _open_posix_directory_chain(destination.parent.resolve(strict=True))
            else:
                destination_fd = quarantine_directory.directory_fd
                if destination_fd is None:
                    raise OSError("pinned quarantine directory has no POSIX directory handle")
            if not stat.S_ISDIR(os.fstat(source_fd).st_mode):
                raise OSError("source parent is not a directory")
            if not stat.S_ISDIR(os.fstat(destination_fd).st_mode):
                raise OSError("destination parent is not a directory")

            libc = ctypes.CDLL(None, use_errno=True)
            renameat2 = getattr(libc, "renameat2", None)
            if renameat2 is None:
                import errno

                raise OSError(errno.ENOTSUP, "renameat2(RENAME_NOREPLACE) is unavailable")
            renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
            renameat2.restype = ctypes.c_int
            result = renameat2(
                source_fd,
                os.fsencode(source.name),
                destination_fd,
                os.fsencode(destination.name),
                1,
            )
            if result != 0:
                error = ctypes.get_errno()
                raise OSError(error, os.strerror(error), str(destination))
            moved = os.stat(destination.name, dir_fd=destination_fd, follow_symlinks=False)
            if (moved.st_dev, moved.st_ino) != pinned_source_identity:
                moved_identity = (moved.st_dev, moved.st_ino)
                restored = False
                restore_error: OSError | None = None
                restore_result = renameat2(
                    destination_fd,
                    os.fsencode(destination.name),
                    source_fd,
                    os.fsencode(source.name),
                    1,
                )
                if restore_result == 0:
                    try:
                        at_source = os.stat(source.name, dir_fd=source_fd, follow_symlinks=False)
                        restored = (at_source.st_dev, at_source.st_ino) == moved_identity
                    except OSError as exc:
                        restore_error = exc
                else:
                    error = ctypes.get_errno()
                    restore_error = OSError(error, os.strerror(error), str(source))
                if restored:
                    raise _AmbiguousMoveError(
                        "source leaf identity changed; moved replacement restored without overwrite; "
                        "original source location is unknown"
                    )
                raise _AmbiguousMoveError(
                    "source leaf identity changed and replacement restoration could not be proven; "
                    f"location is unknown ({restore_error or 'identity mismatch after restore'})"
                )
        finally:
            try:
                if close_destination_fd and destination_fd is not None:
                    os.close(destination_fd)
            finally:
                # Caller-owned pins survive through manifest reconciliation.
                if owns_source_pin:
                    source_pin.close()
        return
    raise OSError(f"no-replace directory moves are unsupported on {sys.platform}")


def _rename_noreplace_windows(
    source: Path,
    destination: Path,
    quarantine_directory: _PinnedQuarantine | None = None,
    source_pin: _PinnedSource | None = None,
) -> None:
    """Rename by pinned directory handles; path-based moves can follow a swapped junction."""
    import ctypes
    from ctypes import wintypes

    class _FileAttributeTagInfo(ctypes.Structure):
        _fields_ = [("attributes", wintypes.DWORD), ("reparse_tag", wintypes.DWORD)]

    class _FileRenameInfo(ctypes.Structure):
        _fields_ = [
            ("replace_if_exists", wintypes.BOOLEAN),
            ("root_directory", wintypes.HANDLE),
            ("file_name_length", wintypes.DWORD),
            ("file_name", wintypes.WCHAR * 1),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    get_info = kernel32.GetFileInformationByHandleEx
    get_info.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    get_info.restype = wintypes.BOOL
    ntdll = ctypes.WinDLL("ntdll", use_last_error=True)

    class _IoStatusBlock(ctypes.Structure):
        _fields_ = [("status", ctypes.c_void_p), ("information", ctypes.c_size_t)]

    set_info = ntdll.NtSetInformationFile
    set_info.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_IoStatusBlock),
        wintypes.LPVOID,
        wintypes.ULONG,
        ctypes.c_int,
    ]
    set_info.restype = ctypes.c_long
    status_to_error = ntdll.RtlNtStatusToDosError
    status_to_error.argtypes = [ctypes.c_long]
    status_to_error.restype = wintypes.ULONG
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    invalid_handle = ctypes.c_void_p(-1).value
    owns_source_pin = source_pin is None
    if source_pin is None:
        source_pin = _pin_source(source)
    source_handle = destination_handle = None
    close_destination_handle = quarantine_directory is None

    def open_directory(path: Path, access: int):
        handle = create_file(
            str(path),
            access | 0x80,  # FILE_READ_ATTRIBUTES
            0x1 | 0x2 | 0x4,  # share read, write, and delete
            None,
            3,  # OPEN_EXISTING
            0x02000000 | 0x00200000,  # BACKUP_SEMANTICS | OPEN_REPARSE_POINT
            None,
        )
        if handle == invalid_handle:
            raise ctypes.WinError(ctypes.get_last_error())
        info = _FileAttributeTagInfo()
        if not get_info(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):  # FileAttributeTagInfo
            error = ctypes.get_last_error()
            close_handle(handle)
            raise ctypes.WinError(error)
        if info.attributes & (_REPARSE_POINT | 0x10) != 0x10:
            close_handle(handle)
            raise OSError(f"skill move parent is not a regular directory: {path}")
        return handle

    try:
        if source_pin is None or source_pin.directory_handle is None or not _source_is_current(source_pin):
            raise OSError("skill source identity changed before quarantine move")
        source_handle = source_pin.directory_handle
        if _windows_handle_identity(source_handle)[:2] != source_pin.identity:
            raise OSError("pinned skill source identity changed before quarantine move")
        if quarantine_directory is None:
            destination_handle = open_directory(destination.parent, 0x4)  # FILE_ADD_SUBDIRECTORY
        else:
            destination_handle = quarantine_directory.directory_handle
            if destination_handle is None:
                raise OSError("pinned quarantine directory has no Windows directory handle")
        name = destination.name
        if not name or name in (".", "..") or "\\" in name or "/" in name:
            raise OSError(f"invalid skill quarantine leaf name: {name!r}")
        encoded_name = name.encode("utf-16-le")
        info_size = _FileRenameInfo.file_name.offset + len(encoded_name)
        rename_info = ctypes.create_string_buffer(max(ctypes.sizeof(_FileRenameInfo), info_size))
        rename = _FileRenameInfo.from_buffer(rename_info)
        rename.replace_if_exists = 0
        rename.root_directory = destination_handle
        rename.file_name_length = len(encoded_name)
        ctypes.memmove(
            ctypes.addressof(rename_info) + _FileRenameInfo.file_name.offset,
            encoded_name,
            len(encoded_name),
        )
        io_status = _IoStatusBlock()
        status = int(set_info(source_handle, ctypes.byref(io_status), ctypes.byref(rename), info_size, 10))
        if status < 0:  # NT_SUCCESS accepts success and informational statuses.
            ctypes.set_last_error(int(status_to_error(status)))
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        try:
            if close_destination_handle and destination_handle is not None:
                close_handle(destination_handle)
        finally:
            # source_handle belongs to source_pin and must remain pinned until
            # the manifest commit/reconciliation completes.
            if owns_source_pin:
                source_pin.close()


def _skill_quarantine_path(skills_root: Path, skill_name: str) -> _PinnedQuarantine:
    resolved_root = skills_root.resolve(strict=True)
    quarantine_root = resolved_root.parent / ".local-ai-hub-skill-quarantine"
    if quarantine_root.parent != resolved_root.parent:
        raise OSError(f"skill quarantine root escaped install directory: {quarantine_root}")
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        parent_handle = _open_windows_directory(resolved_root.parent, 0, 0x1 | 0x2)
        directory_handle = None
        try:
            create_directory = ctypes.WinDLL("kernel32", use_last_error=True).CreateDirectoryW
            create_directory.argtypes = [wintypes.LPCWSTR, wintypes.LPVOID]
            create_directory.restype = wintypes.BOOL
            if not create_directory(str(quarantine_root), None):
                error = ctypes.get_last_error()
                if error not in (80, 183):  # ERROR_FILE_EXISTS / ERROR_ALREADY_EXISTS
                    raise ctypes.WinError(error)
            # FILE_SHARE_DELETE deliberately omitted: the path cannot be swapped
            # while this directory is used as FileRenameInfo.RootDirectory.
            directory_handle = _open_windows_directory(quarantine_root, 0x4, 0x1 | 0x2)
            return _PinnedQuarantine(
                quarantine_root / f"{skill_name}-{uuid.uuid4().hex}",
                quarantine_root,
                parent_handle=parent_handle,
                directory_handle=directory_handle,
            )
        except BaseException:
            try:
                if directory_handle is not None:
                    _windows_close_handle()(directory_handle)
            finally:
                _windows_close_handle()(parent_handle)
            raise

    parent_fd = _open_posix_directory_chain(resolved_root.parent)
    directory_fd = None
    try:
        root_name = quarantine_root.name
        try:
            os.mkdir(root_name, mode=0o700, dir_fd=parent_fd)
        except FileExistsError:
            pass
        directory_fd = os.open(root_name, _posix_directory_flags(), dir_fd=parent_fd)
        if not stat.S_ISDIR(os.fstat(directory_fd).st_mode):
            raise OSError(f"skill quarantine root is not a regular directory: {quarantine_root}")
        return _PinnedQuarantine(
            quarantine_root / f"{skill_name}-{uuid.uuid4().hex}",
            quarantine_root,
            parent_fd=parent_fd,
            directory_fd=directory_fd,
        )
    except BaseException:
        try:
            if directory_fd is not None:
                os.close(directory_fd)
        finally:
            os.close(parent_fd)
        raise


@contextmanager
def _ownership_lock(manifest: Path):
    """Serialize ownership-manifest and skill-tree mutations across threads/processes."""
    lock_path = manifest.with_name(manifest.name + ".lock")
    key = _canonical(lock_path)
    with _PATH_LOCKS_GUARD:
        thread_lock = _PATH_LOCKS.setdefault(key, threading.RLock())
    with thread_lock:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = _open_ownership_lock_file(lock_path)
        acquired = False
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & _REPARSE_POINT:
                raise OSError(f"skill ownership lock is not a regular file: {lock_path}")
            if info.st_nlink != 1:
                raise OSError(f"skill ownership lock has unexpected hard links: {lock_path}")
            if info.st_size == 0:
                os.write(fd, b"\\0")
            deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
            if os.name == "nt":
                import msvcrt

                while True:
                    try:
                        os.lseek(fd, 0, os.SEEK_SET)
                        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                        acquired = True
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            raise TimeoutError(f"timed out locking skill ownership manifest: {manifest}")
                        time.sleep(0.05)
            else:
                import fcntl

                while True:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        acquired = True
                        break
                    except BlockingIOError:
                        if time.monotonic() >= deadline:
                            raise TimeoutError(f"timed out locking skill ownership manifest: {manifest}")
                        time.sleep(0.05)
            yield
        finally:
            try:
                if acquired:
                    if os.name == "nt":
                        import msvcrt

                        os.lseek(fd, 0, os.SEEK_SET)
                        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)


def _is_link(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & _REPARSE_POINT)


def _safe_tree_hash(root: Path) -> str:
    if _is_link(root) or not root.is_dir():
        raise ValueError(f"skill tree is not a safe directory: {root}")
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        if _is_link(path):
            raise ValueError(f"skill tree contains a link: {path}")
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            digest.update(b"D\0" + relative.encode("utf-8") + b"\0")
        elif stat.S_ISREG(info.st_mode):
            digest.update(b"F\0" + relative.encode("utf-8") + b"\0")
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            digest.update(b"\0")
        else:
            raise ValueError(f"skill tree contains an unsupported file: {path}")
    return digest.hexdigest()


def _canonical(path: Path) -> str:
    return os.path.normcase(str(path.resolve(strict=False)))


def _validate_manifest(manifest: Path) -> None:
    if manifest.name != MANIFEST_NAME:
        raise ValueError(f"unexpected skill ownership manifest path: {manifest}")
    cursor = manifest.parent
    while cursor != cursor.parent:
        if _is_link(cursor):
            raise ValueError(f"ownership manifest path contains a link: {cursor}")
        cursor = cursor.parent


def _validate_source(source: Path, skill_name: str) -> Path:
    if source.name != skill_name or source.parent.name != "skills":
        raise ValueError(f"skill source must be a direct child of an install skills directory: {source}")
    cursor = source
    while cursor != cursor.parent:
        if _is_link(cursor):
            raise ValueError(f"skill source path contains a link: {cursor}")
        cursor = cursor.parent
    return source.resolve(strict=True)


def _manifest_read(manifest: Path) -> dict[str, dict[str, object]]:
    if _is_link(manifest):
        return {}
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        if payload.get("version") != MANIFEST_VERSION or not isinstance(payload.get("skills"), dict):
            return {}
        return {key: value for key, value in payload["skills"].items() if isinstance(value, dict)}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def _manifest_write(manifest: Path, entries: dict[str, dict[str, object]]) -> None:
    manifest.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=manifest.name + ".", dir=manifest.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump({"version": MANIFEST_VERSION, "skills": entries}, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temp_name, manifest)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def _valid_quarantine_record(record: dict[str, object]) -> TypeGuard[dict[str, str]]:
    if any(not isinstance(value, str) for value in record.values()):
        return False
    required = ("quarantine_path", "status", "recorded_sha256", "original_target")
    if any(not isinstance(record.get(field), str) or not record[field].strip() for field in required):
        return False
    if "\x00" in record["quarantine_path"]:
        return False
    return record["status"] in {"pending", "unverified", "quarantined", "conflict", "ambiguous"}


def _expected_quarantine_root(skills_root: Path) -> Path:
    return skills_root.resolve(strict=False).parent / ".local-ai-hub-skill-quarantine"


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdefABCDEF" for char in value)


def _inspect_quarantine_record(
    record: dict[str, object], expected_root: Path
) -> tuple[dict[str, object], str]:
    """Return safely classified metadata and path presence without dropping evidence."""
    if not _valid_quarantine_record(record):
        return dict(record), "unknown"
    if record["status"] == "ambiguous" or record.get("location_state") == "unknown":
        return dict(record), "unknown"
    path = Path(record["quarantine_path"])
    if not path.is_absolute() or ".." in path.parts:
        return dict(record), "unknown"
    expected_parent = os.path.normcase(os.path.abspath(expected_root))
    actual_parent = os.path.normcase(os.path.abspath(path.parent))
    if actual_parent != expected_parent:
        return dict(record), "unknown"
    try:
        root_info = expected_root.lstat()
    except (OSError, ValueError):
        return dict(record), "unknown"
    if (
        _is_link(expected_root)
        or not stat.S_ISDIR(root_info.st_mode)
        or bool(getattr(root_info, "st_file_attributes", 0) & _REPARSE_POINT)
    ):
        return dict(record), "unknown"
    try:
        path.lstat()
    except FileNotFoundError:
        return dict(record), "absent"
    except (OSError, ValueError):
        return dict(record), "unknown"

    # Quarantine paths are persisted metadata and may race replacement. Inspect
    # presence only; never recursively hash a path that can change between lstat
    # and traversal. The stored SHA-256 remains the pre-move baseline only.
    updated = dict(record)
    if updated["status"] == "conflict":
        updated["observed_sha256"] = "unverified"
    elif not _is_sha256(updated["recorded_sha256"]):
        updated["status"] = "pending" if updated["status"] == "pending" else "conflict"
        updated["observed_sha256"] = (
            "unavailable" if updated["recorded_sha256"] == "unavailable" else "unverified"
        )
    return updated, "present"


def _validate_target(target: Path, skills_root: Path, skill_name: str) -> Path:
    if target.name != skill_name or target.parent != skills_root:
        raise ValueError(f"skill target must be a direct child of {skills_root}: {target}")
    if _is_link(skills_root):
        raise ValueError(f"skills directory is a link: {skills_root}")
    if _is_link(target):
        raise ValueError(f"skill target is a link: {target}")
    # Resolve existing ancestors and ensure resolution did not redirect the target.
    resolved_root = skills_root.resolve(strict=False)
    resolved_target = target.resolve(strict=False)
    if resolved_target.parent != resolved_root:
        raise ValueError(f"skill target resolves outside its skills directory: {target}")
    cursor = skills_root
    while cursor != cursor.parent:
        if _is_link(cursor):
            raise ValueError(f"skill path contains a link: {cursor}")
        cursor = cursor.parent
    return resolved_root / target.name


def _retain_previous_install(
    backup: Path,
    *,
    target: Path,
    skills_root: Path,
    manifest: Path,
    skill_name: str,
    original_hash: str,
    entries: dict[str, dict[str, object]],
) -> str:
    source_pin: _PinnedSource | None = None
    quarantine_directory: _PinnedQuarantine | None = None
    quarantine_key = ""
    pending_entries = dict(entries)

    def mark_ambiguous(reason: str) -> str:
        ambiguous_key = f"ambiguous:{_canonical(target)}:{uuid.uuid4().hex}"
        ambiguous_record = {
            "name": skill_name,
            "recorded_sha256": original_hash,
            "status": "ambiguous",
            "hash_state": "unverified",
            "location_state": "unknown",
            "original_target": _canonical(target),
            "quarantine_path": "unknown",
        }
        ambiguous_entries = dict(entries)
        ambiguous_entries.pop(quarantine_key, None)
        ambiguous_entries[ambiguous_key] = ambiguous_record
        try:
            _manifest_write(manifest, ambiguous_entries)
        except (OSError, ValueError) as exc:
            return f"installed Hub-owned skill: {target}; previous version location ambiguous: {reason}; manifest update failed: {exc}"
        return f"installed Hub-owned skill: {target}; previous version location ambiguous: {reason}"

    try:
        source_pin = _pin_source(backup)
        if not _source_is_current(source_pin) or _safe_tree_hash(backup) != original_hash or not _source_is_current(source_pin):
            return f"installed Hub-owned skill: {target}; previous version retained at {backup}; backup identity changed"
        quarantine_directory = _skill_quarantine_path(skills_root, skill_name)
        quarantine_key = quarantine_directory.key
        pending_record = {
            "name": skill_name,
            "recorded_sha256": original_hash,
            "status": "pending",
            "hash_state": "unverified",
            "original_target": _canonical(target),
            "quarantine_path": str(quarantine_directory.path),
        }
        pending_entries[quarantine_key] = pending_record
        _manifest_write(manifest, pending_entries)
        try:
            _rename_noreplace(
                backup,
                quarantine_directory.path,
                quarantine_directory=quarantine_directory,
                source_pin=source_pin,
            )
        except (OSError, ValueError) as exc:
            if not _source_is_current(source_pin):
                return mark_ambiguous(str(exc))
            try:
                _manifest_write(manifest, entries)
            except (OSError, ValueError) as restore_exc:
                return (
                    f"installed Hub-owned skill: {target}; previous version retained at {backup}; "
                    f"quarantine record cleanup failed: {restore_exc}"
                )
            return f"installed Hub-owned skill: {target}; previous version retained at {backup}: {exc}"

        if not quarantine_directory.is_current():
            return mark_ambiguous("quarantine root changed after move")
        source_identity = source_pin.identity
        source_pin.close()
        try:
            moved_pin = _pin_source(quarantine_directory.path)
        except OSError as exc:
            return mark_ambiguous(f"moved tree identity unavailable: {exc}")
        try:
            if moved_pin.identity != source_identity:
                return mark_ambiguous("moved tree identity changed")
        finally:
            moved_pin.close()
        if not quarantine_directory.is_current():
            return mark_ambiguous("quarantine root changed during identity verification")

        retained_record = {**pending_record, "status": "unverified"}
        retained_entries = dict(pending_entries)
        retained_entries[quarantine_key] = retained_record
        try:
            _manifest_write(manifest, retained_entries)
        except (OSError, ValueError) as exc:
            return (
                f"installed Hub-owned skill: {target}; previous version retained at {quarantine_directory.path}; "
                f"pending recovery record remains: {exc}"
            )
        # The backup is now outside the staging tree. Remove only the empty
        # parent; rmdir cannot recursively follow or delete a substituted tree.
        try:
            backup.parent.rmdir()
        except OSError:
            pass
        return f"installed Hub-owned skill: {target}; previous version retained at {quarantine_directory.path}"
    except (OSError, ValueError) as exc:
        return f"installed Hub-owned skill: {target}; previous version retained at {backup}: {exc}"
    finally:
        if source_pin is not None:
            source_pin.close()
        if quarantine_directory is not None:
            quarantine_directory.close()
def _install_skill_unlocked(source: Path, target: Path, skills_root: Path, manifest: Path, skill_name: str) -> str:
    """Install only into an absent or unchanged Hub-owned skill tree."""
    _validate_manifest(manifest)
    source = _validate_source(source, skill_name)
    if _canonical(source.parent.parent) != _canonical(manifest.parent):
        raise ValueError(f"skill source and ownership manifest have different install roots: {source}")
    source_hash = _safe_tree_hash(source)
    target = _validate_target(target, skills_root, skill_name)
    entries = _manifest_read(manifest)
    key = _canonical(target)
    previous = entries.get(key)
    if target.exists():
        try:
            current_hash = _safe_tree_hash(target)
        except ValueError:
            return f"preserved conflicting skill tree: {target}"
        if not previous or previous.get("name") != skill_name or previous.get("sha256") != current_hash:
            return f"preserved unmanaged or modified skill tree: {target}"
        if _is_link(target):
            return f"preserved conflicting skill tree: {target}"
        if current_hash == source_hash:
            return f"installed Hub-owned skill: {target}"
    target.parent.mkdir(parents=True, exist_ok=True)
    stage_root = Path(tempfile.mkdtemp(prefix=f".{skill_name}.lah-stage-", dir=target.parent))
    staged = stage_root / "replacement"
    backup = stage_root / "previous"
    had_target = target.exists()
    moved_old = False
    installed_new = False
    try:
        shutil.copytree(source, staged, symlinks=False)
        if _safe_tree_hash(staged) != source_hash:
            raise OSError("staged skill content differs from source")
        if had_target:
            if _safe_tree_hash(target) != current_hash or _is_link(target):
                return f"preserved changed skill tree during replacement: {target}"
            os.replace(target, backup)
            moved_old = True
            try:
                moved_hash = _safe_tree_hash(backup)
            except ValueError:
                moved_hash = None
            if _is_link(backup) or moved_hash != current_hash:
                if not target.exists():
                    os.replace(backup, target)
                    moved_old = False
                if backup.exists():
                    return f"preserved changed skill tree during replacement; recoverable at {backup}"
                return f"preserved changed skill tree during replacement: {target}"
        elif target.exists() or _is_link(target):
            return f"preserved conflicting skill tree created during install: {target}"
        os.replace(staged, target)
        installed_new = True
        entries[key] = {"name": skill_name, "sha256": source_hash}
        _manifest_write(manifest, entries)
    except (OSError, ValueError) as exc:
        rollback_error: Exception | None = None
        try:
            if installed_new and target.exists() and _safe_tree_hash(target) == source_hash:
                shutil.rmtree(target)
            if moved_old and backup.exists() and not target.exists():
                os.replace(backup, target)
        except (OSError, ValueError) as rollback_exc:
            rollback_error = rollback_exc
        if backup.exists():
            recovery = f"; previous skill recoverable at {backup}"
        else:
            recovery = "; previous skill restored" if had_target and target.exists() else "; target unchanged"
        if rollback_error:
            recovery += f"; rollback failed: {rollback_error}"
        return f"skill replacement failed for {target}: {exc}{recovery}"
    finally:
        if not backup.exists():
            shutil.rmtree(stage_root, ignore_errors=True)
    if backup.exists():
        return _retain_previous_install(
            backup,
            target=target,
            skills_root=skills_root,
            manifest=manifest,
            skill_name=skill_name,
            original_hash=current_hash,
            entries=entries,
        )
    try:
        shutil.rmtree(stage_root)
    except OSError:
        pass
    return f"installed Hub-owned skill: {target}"


def install_skill(source: Path, target: Path, skills_root: Path, manifest: Path, skill_name: str) -> str:
    _validate_manifest(manifest)
    with _ownership_lock(manifest):
        return _install_skill_unlocked(source, target, skills_root, manifest, skill_name)


def _remove_skill_quarantined(
    target: Path,
    skill_name: str,
    manifest: Path,
    entries: dict[str, dict[str, object]],
    key: str,
    current_hash: str,
    expected_quarantine_root: Path,
    quarantine_directory: _PinnedQuarantine,
    source_pin: _PinnedSource,
) -> str:
    quarantine = quarantine_directory.path
    quarantine_key = quarantine_directory.key
    if quarantine_key in entries:
        return f"skill removal failed for {target}: quarantine record already exists at {quarantine}"
    quarantine_record: dict[str, str] = {
        "name": skill_name,
        "recorded_sha256": current_hash,
        "status": "pending",
        "original_target": key,
        "quarantine_path": str(quarantine),
    }
    pending_entries = dict(entries)
    pending_entries[quarantine_key] = quarantine_record

    def mark_unknown_location(reason: str) -> str:
        ambiguous_key = f"ambiguous:{key}:{uuid.uuid4().hex}"
        ambiguous_record = {
            **quarantine_record,
            "quarantine_path": "unknown",
            "status": "ambiguous",
            "hash_state": "unverified",
            "location_state": "unknown",
        }
        ambiguous_entries = dict(entries)
        ambiguous_entries.pop(key, None)
        ambiguous_entries.pop(quarantine_key, None)
        ambiguous_entries[ambiguous_key] = ambiguous_record
        try:
            _manifest_write(manifest, ambiguous_entries)
            return f"skill move outcome ambiguous: {reason}; recovery location is unknown"
        except (OSError, ValueError) as write_exc:
            return (
                f"skill move outcome ambiguous: {reason}; recovery location is unknown; "
                f"manifest reconciliation failed: {write_exc}"
            )

    try:
        _manifest_write(manifest, pending_entries)
    except (OSError, ValueError) as exc:
        try:
            _manifest_write(manifest, entries)
        except (OSError, ValueError) as restore_exc:
            return (
                f"skill removal failed for {target}: pending quarantine record write failed: {exc}; "
                f"active tree remains at {target}; manifest cleanup failed: {restore_exc}"
            )
        return f"skill removal failed for {target}: pending quarantine record write failed: {exc}; active tree remains at {target}"

    try:
        _rename_noreplace(
            target, quarantine, quarantine_directory=quarantine_directory, source_pin=source_pin
        )
    except _AmbiguousMoveError as exc:
        return mark_unknown_location(str(exc))
    except OSError as exc:
        if not quarantine_directory.is_current():
            return mark_unknown_location(
                f"pinned quarantine root path changed after move error ({exc})"
            )
        try:
            target.lstat()
            target_present = True
        except FileNotFoundError:
            target_present = False
        except OSError:
            target_present = None
        quarantine_present = quarantine_directory.entry_presence(quarantine.name)
        if os.name == "nt" and not quarantine_directory.is_current():
            return mark_unknown_location(
                f"pinned quarantine root path changed during error reconciliation ({exc})"
            )
        if quarantine_present is None:
            return mark_unknown_location(
                f"quarantine presence could not be established after move error ({exc})"
            )

        if target_present is False and quarantine_present is True:
            tracked_record, _presence = _inspect_quarantine_record(quarantine_record, expected_quarantine_root)
            tracked_record["hash_state"] = "unverified"
            tracked_record["observed_sha256"] = "unverified"
            tracked_entries = dict(entries)
            tracked_entries.pop(key, None)
            tracked_entries[quarantine_key] = tracked_record
            try:
                _manifest_write(manifest, tracked_entries)
                return (
                    f"skill move outcome ambiguous after {exc}; tracked recovery path {quarantine}; "
                    f"recorded_sha256={tracked_record.get('recorded_sha256')}, hash_state=unverified"
                )
            except (OSError, ValueError) as write_exc:
                return (
                    f"skill move outcome ambiguous after {exc}; quarantine path {quarantine}; "
                    f"manifest reconciliation failed: {write_exc}"
                )
        if target_present is True and quarantine_present is False:
            try:
                _manifest_write(manifest, entries)
                return f"skill removal failed for {target}: {exc}; target observed in place; pending record removed"
            except (OSError, ValueError) as restore_exc:
                return (
                    f"skill removal failed for {target}: {exc}; target observed at {target}; "
                    f"pending record remains at {quarantine}: {restore_exc}"
                )
        # Both/neither path, or an inspection error: retain the pending intent
        # rather than claiming where the tree is or dropping its recovery path.
        if target_present is True and quarantine_present is True:
            ambiguous_record = {
                **quarantine_record,
                "status": "conflict",
                "observed_sha256": "unverified",
            }
            pending_entries[quarantine_key] = ambiguous_record
            try:
                _manifest_write(manifest, pending_entries)
                classification_state = "; recovery path marked conflict"
            except (OSError, ValueError) as write_exc:
                classification_state = f"; conflict update failed, prior pending record retained: {write_exc}"
        else:
            classification_state = "; pending recovery record retained"
        return (
            f"skill move outcome uncertain after {exc}; inspect target {target} and quarantine {quarantine}; "
            f"recovery path remains recorded{classification_state}"
        )
    if not quarantine_directory.is_current():
        # The directory handle proves where renameat2/FileRenameInfo placed the
        # tree, but its former pathname no longer identifies that directory.
        # Do not leave a manifest entry that advertises the now-stale path.
        ambiguous_key = f"ambiguous:{key}:{uuid.uuid4().hex}"
        ambiguous_record = {
            **quarantine_record,
            "quarantine_path": "unknown",
            "status": "ambiguous",
            "hash_state": "unverified",
            "location_state": "unknown",
        }
        ambiguous_entries = dict(entries)
        ambiguous_entries.pop(key, None)
        ambiguous_entries.pop(quarantine_key, None)
        ambiguous_entries[ambiguous_key] = ambiguous_record
        try:
            _manifest_write(manifest, ambiguous_entries)
            return (
                "skill deactivated; quarantine root changed during uninstall; "
                "recovery location is unknown (manifest status=ambiguous)"
            )
        except (OSError, ValueError) as write_exc:
            return (
                "skill move outcome uncertain; quarantine root changed during uninstall; "
                f"could not replace pending recovery path with unknown location: {write_exc}"
            )

    # The source digest is a pre-move baseline only. Persisted quarantine paths
    # are never recursively hashed because lstat-to-traversal races cannot be
    # closed here; no quarantine path is ever deleted.
    final_record = {**quarantine_record, "status": "unverified", "hash_state": "unverified"}
    final_entries = dict(entries)
    final_entries.pop(key, None)
    # Reconcile older intents for this target without discarding any recorded
    # recovery path. Quarantine contents remain unverified; inspect presence only.
    for old_key, old_record in list(final_entries.items()):
        original_target = old_record.get("original_target")
        if old_key == quarantine_key or not isinstance(original_target, str) or original_target != key:
            continue
        classified_record, _presence = _inspect_quarantine_record(old_record, expected_quarantine_root)
        final_entries[old_key] = classified_record
    final_entries[quarantine_key] = final_record
    try:
        _manifest_write(manifest, final_entries)
    except (OSError, ValueError) as exc:
        observed = _manifest_read(manifest)
        if observed.get(quarantine_key) == final_record and key not in observed:
            if not quarantine_directory.is_current():
                ambiguous_key = f"ambiguous:{key}:{uuid.uuid4().hex}"
                ambiguous_record = {
                    **quarantine_record,
                    "quarantine_path": "unknown",
                    "status": "ambiguous",
                    "hash_state": "unverified",
                    "location_state": "unknown",
                }
                ambiguous_entries = dict(observed)
                ambiguous_entries.pop(quarantine_key, None)
                ambiguous_entries[ambiguous_key] = ambiguous_record
                try:
                    _manifest_write(manifest, ambiguous_entries)
                    return (
                        "skill deactivated; quarantine root changed during manifest commit; "
                        "recovery location is unknown (manifest status=ambiguous)"
                    )
                except (OSError, ValueError) as write_exc:
                    return (
                        "skill move outcome uncertain; quarantine root changed during manifest commit; "
                        f"could not replace stale recovery path with unknown location: {write_exc}"
                    )
            return (
                f"uninstalled skill; quarantine recorded at {quarantine} "
                f"(recorded_sha256={current_hash}, hash_state=unverified)"
            )
        if not quarantine_directory.is_current():
            ambiguous_key = f"ambiguous:{key}:{uuid.uuid4().hex}"
            ambiguous_record = {
                **quarantine_record,
                "quarantine_path": "unknown",
                "status": "ambiguous",
                "hash_state": "unverified",
                "location_state": "unknown",
            }
            ambiguous_entries = dict(entries)
            ambiguous_entries.pop(key, None)
            ambiguous_entries.pop(quarantine_key, None)
            ambiguous_entries[ambiguous_key] = ambiguous_record
            try:
                _manifest_write(manifest, ambiguous_entries)
                return (
                    "skill deactivated; quarantine root changed during manifest commit; "
                    "recovery location is unknown (manifest status=ambiguous)"
                )
            except (OSError, ValueError) as write_exc:
                return (
                    "skill move outcome uncertain; quarantine root changed during manifest commit; "
                    f"could not replace stale recovery path with unknown location: {write_exc}"
                )
        # The pre-move pending record already stores the path/baseline. Keep the
        # moved tree there and never overwrite a target that appeared meanwhile.
        try:
            _manifest_write(manifest, pending_entries)
            tracking = "; pending quarantine path/baseline record persisted"
        except (OSError, ValueError) as reconcile_exc:
            tracking = f"; manifest reconciliation failed: {reconcile_exc}"
        return (
            f"skill deactivated; data recoverable at {quarantine} "
            f"(recorded_sha256={current_hash}, hash_state=unverified); "
            f"final manifest update failed: {exc}{tracking}"
        )

    if not quarantine_directory.is_current():
        ambiguous_key = f"ambiguous:{key}:{uuid.uuid4().hex}"
        ambiguous_record = {
            **quarantine_record,
            "quarantine_path": "unknown",
            "status": "ambiguous",
            "hash_state": "unverified",
            "location_state": "unknown",
        }
        ambiguous_entries = dict(final_entries)
        ambiguous_entries.pop(quarantine_key, None)
        ambiguous_entries[ambiguous_key] = ambiguous_record
        try:
            _manifest_write(manifest, ambiguous_entries)
            return (
                "skill deactivated; quarantine root changed during manifest commit; "
                "recovery location is unknown (manifest status=ambiguous)"
            )
        except (OSError, ValueError) as write_exc:
            return (
                "skill move outcome uncertain; quarantine root changed during manifest commit; "
                f"could not replace stale recovery path with unknown location: {write_exc}"
            )

    return (
        f"uninstalled Hub-owned skill; data preserved at {quarantine} "
        f"(recorded_sha256={current_hash}, hash_state=unverified)"
    )


def _remove_skill_unlocked(target: Path, skills_root: Path, manifest: Path, skill_name: str) -> str:
    """Deactivate an owned tree by moving it outside skills_root, without deleting it."""
    _validate_manifest(manifest)
    target = _validate_target(target, skills_root, skill_name)
    expected_quarantine_root = _expected_quarantine_root(skills_root)
    entries = _manifest_read(manifest)
    key = _canonical(target)
    if not target.exists():
        tracked: list[tuple[dict[str, object], str]] = []
        for record in entries.values():
            original_target = record.get("original_target")
            if isinstance(original_target, str) and original_target == key:
                classified, presence = _inspect_quarantine_record(record, expected_quarantine_root)
                tracked.append((classified, presence))
        if tracked:
            tracked.sort(
                key=lambda item: (
                    {"present": 2, "unknown": 1, "absent": 0}[item[1]],
                    item[0].get("status") in ("quarantined", "unverified"),
                ),
                reverse=True,
            )
            locations = "; ".join(
                f"{record.get('quarantine_path', '<missing path>')} "
                f"(status={record.get('status', 'unknown')}, recorded_sha256={record.get('recorded_sha256', 'unknown')}, "
                f"observed_sha256={record.get('observed_sha256', 'unverified')}, "
                f"hash_state=unverified, presence={presence})"
                for record, presence in tracked
            )
            path_label = "tracked recovery path" if len(tracked) == 1 else "tracked recovery paths"
            return f"skill inactive; {path_label}: {locations}"
        return f"skill already absent: {target}"
    previous = entries.get(key)
    if not previous or previous.get("name") != skill_name:
        return f"preserved unmanaged skill tree: {target}"
    try:
        source_pin = _pin_source(target)
    except OSError as exc:
        return f"preserved conflicting skill tree: cannot pin source identity: {exc}"
    try:
        try:
            current_hash = _safe_tree_hash(target)
        except ValueError:
            return f"preserved conflicting skill tree: {target}"
        if not _source_is_current(source_pin):
            return f"preserved conflicting skill tree: source identity changed while hashing: {target}"
        if not _is_sha256(current_hash):
            return f"preserved skill tree because its SHA-256 could not be verified: {target}"
        if previous.get("sha256") != current_hash:
            return f"preserved modified Hub-owned skill tree: {target}"
        if _is_link(target):
            return f"preserved conflicting skill tree: {target}"

        try:
            quarantine_directory = _skill_quarantine_path(skills_root, skill_name)
        except OSError as exc:
            return f"skill removal failed for {target}: cannot prepare external quarantine: {exc}"

        try:
            return _remove_skill_quarantined(
                target,
                skill_name,
                manifest,
                entries,
                key,
                current_hash,
                expected_quarantine_root,
                quarantine_directory,
                source_pin,
            )
        finally:
            quarantine_directory.close()
    finally:
        source_pin.close()


def remove_skill(target: Path, skills_root: Path, manifest: Path, skill_name: str) -> str:
    """Deactivate a managed skill and retain its bytes in tracked quarantine."""
    _validate_manifest(manifest)
    with _ownership_lock(manifest):
        return _remove_skill_unlocked(target, skills_root, manifest, skill_name)
