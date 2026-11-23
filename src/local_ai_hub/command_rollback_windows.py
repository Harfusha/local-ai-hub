from __future__ import annotations

import ctypes
import os
import stat
from ctypes import wintypes
from pathlib import Path

from .command_rollback import _MAX_ROLLBACK_METADATA_BYTES


def _get_windows_dacl(fd: int) -> bytes:
    import msvcrt

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    get_security_info = advapi32.GetSecurityInfo
    get_security_info.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)]
    get_security_info.restype = wintypes.DWORD
    descriptor = ctypes.c_void_p()
    status = get_security_info(msvcrt.get_osfhandle(fd), 1, 0x4, None, None, None, None, ctypes.byref(descriptor))
    if status:
        raise OSError(status, "cannot snapshot rollback target DACL")
    try:
        advapi32.GetSecurityDescriptorLength.argtypes = [ctypes.c_void_p]
        advapi32.GetSecurityDescriptorLength.restype = wintypes.DWORD
        length = int(advapi32.GetSecurityDescriptorLength(descriptor))
        if length <= 0 or length > _MAX_ROLLBACK_METADATA_BYTES:
            raise OSError("rollback target DACL exceeds metadata limit")
        return ctypes.string_at(descriptor, length)
    finally:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        kernel32.LocalFree(descriptor)


def _set_windows_dacl(fd: int, descriptor: bytes) -> None:
    import msvcrt

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi32.SetKernelObjectSecurity.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p]
    advapi32.SetKernelObjectSecurity.restype = wintypes.BOOL
    security_descriptor = ctypes.create_string_buffer(descriptor)
    if not advapi32.SetKernelObjectSecurity(msvcrt.get_osfhandle(fd), 0x4, security_descriptor):
        raise OSError(ctypes.get_last_error(), "cannot restore rollback target DACL")


def _set_windows_dacl_path(path: str | Path, descriptor: bytes, expected_fd: int) -> None:
    """Restore a DACL on a verified temp file using a handle with WRITE_DAC."""
    import msvcrt

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    handle = create_file(
        str(path), 0x00040000 | 0x00000080, 0x1 | 0x2, None, 3,
        0x00200000 | 0x08000000, None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle == invalid_handle:
        raise OSError(ctypes.get_last_error(), "cannot open rollback temp file for DACL restore")
    raw_handle = int(handle)
    try:
        attributes, _reparse_tag = _windows_handle_attributes(raw_handle)
        if attributes & 0x400 or _windows_handle_identity(raw_handle) != _windows_handle_identity(
            msvcrt.get_osfhandle(expected_fd)
        ):
            raise OSError("rollback temp file identity changed before DACL restore")
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        set_security = advapi32.SetKernelObjectSecurity
        set_security.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p]
        set_security.restype = wintypes.BOOL
        security_descriptor = ctypes.create_string_buffer(descriptor)
        if not set_security(wintypes.HANDLE(raw_handle), 0x4, security_descriptor):
            raise OSError(ctypes.get_last_error(), "cannot restore rollback target DACL")
    finally:
        _close_rollback_root(raw_handle)


def _restore_windows_file_attributes(fd: int, mode: int | None) -> None:
    import msvcrt

    class FileBasicInfo(ctypes.Structure):
        _fields_ = [
            ("creation_time", ctypes.c_int64),
            ("last_access_time", ctypes.c_int64),
            ("last_write_time", ctypes.c_int64),
            ("change_time", ctypes.c_int64),
            ("file_attributes", wintypes.DWORD),
        ]

    set_information = ctypes.WinDLL("kernel32", use_last_error=True).SetFileInformationByHandle
    set_information.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    set_information.restype = wintypes.BOOL
    attributes = 0x00000001 if mode is not None and not mode & stat.S_IWRITE else 0x00000080
    basic_info = FileBasicInfo(0, 0, 0, 0, attributes)
    handle = wintypes.HANDLE(msvcrt.get_osfhandle(fd))
    if not set_information(handle, 0, ctypes.byref(basic_info), ctypes.sizeof(basic_info)):
        raise OSError(ctypes.get_last_error(), "cannot restore rollback target attributes")


def _restore_windows_file_times(fd: int, atime_ns: int | None, mtime_ns: int | None) -> None:
    import msvcrt

    class FileTime(ctypes.Structure):
        _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

    def to_filetime(value: int | None) -> FileTime | None:
        if value is None:
            return None
        ticks = (int(value) + 11644473600 * 1_000_000_000) // 100
        return FileTime(ticks & 0xFFFFFFFF, ticks >> 32)

    access_time, write_time = to_filetime(atime_ns), to_filetime(mtime_ns)
    set_file_time = ctypes.WinDLL("kernel32", use_last_error=True).SetFileTime
    set_file_time.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
    ]
    set_file_time.restype = wintypes.BOOL
    if not set_file_time(
        msvcrt.get_osfhandle(fd), None,
        ctypes.byref(access_time) if access_time is not None else None,
        ctypes.byref(write_time) if write_time is not None else None,
    ):
        raise OSError(ctypes.get_last_error(), "cannot restore rollback target file times")


def _delete_windows_handle(handle: int) -> None:

    set_information = ctypes.WinDLL("kernel32", use_last_error=True).SetFileInformationByHandle
    set_information.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    set_information.restype = wintypes.BOOL
    delete = ctypes.c_ubyte(1)
    if not set_information(wintypes.HANDLE(handle), 4, ctypes.byref(delete), ctypes.sizeof(delete)):
        raise OSError(ctypes.get_last_error(), "cannot remove rollback target by handle")


def _rename_windows_handle(
    handle: int, parent_handle: int, name: str, *, replace_if_exists: bool = True
) -> None:

    class RenameFlags(ctypes.Union):
        _fields_ = [("replace_if_exists", wintypes.BOOLEAN), ("flags", wintypes.DWORD)]

    class FileRenameInfo(ctypes.Structure):
        _fields_ = [
            ("rename_flags", RenameFlags),
            ("replace_if_exists_legacy", wintypes.BOOLEAN),
            ("root_directory", wintypes.HANDLE),
            ("file_name_length", wintypes.DWORD),
            ("file_name", wintypes.WCHAR * 1),
        ]

    encoded_name = name.encode("utf-16-le")
    info_size = ctypes.sizeof(FileRenameInfo) + len(encoded_name)
    info_buffer = ctypes.create_string_buffer(info_size)
    info = ctypes.cast(info_buffer, ctypes.POINTER(FileRenameInfo)).contents
    replace_flag = 1 if replace_if_exists else 0
    info.rename_flags.replace_if_exists = replace_flag
    info.replace_if_exists_legacy = replace_flag
    info.root_directory = wintypes.HANDLE(parent_handle)
    info.file_name_length = len(encoded_name)
    ctypes.memmove(ctypes.addressof(info_buffer) + FileRenameInfo.file_name.offset, encoded_name, len(encoded_name))

    class IoStatusBlock(ctypes.Structure):
        _fields_ = [("status", ctypes.c_void_p), ("information", ctypes.c_size_t)]

    ntdll = ctypes.WinDLL("ntdll")
    set_information = ntdll.NtSetInformationFile
    set_information.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(IoStatusBlock),
        ctypes.c_void_p,
        wintypes.ULONG,
        wintypes.ULONG,
    ]
    set_information.restype = wintypes.LONG
    io_status = IoStatusBlock()
    status = int(set_information(wintypes.HANDLE(handle), ctypes.byref(io_status), info_buffer, info_size, 10))
    if status < 0:
        status_to_error = ntdll.RtlNtStatusToDosError
        status_to_error.argtypes = [wintypes.LONG]
        status_to_error.restype = wintypes.ULONG
        raise OSError(int(status_to_error(status)), "cannot install rollback target by handle")


def _windows_dacl_bytes(descriptor: bytes) -> bytes:

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    get_dacl = advapi32.GetSecurityDescriptorDacl
    get_dacl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL)]
    get_dacl.restype = wintypes.BOOL
    buffer = ctypes.create_string_buffer(descriptor)
    present, dacl, defaulted = wintypes.BOOL(), ctypes.c_void_p(), wintypes.BOOL()
    if not get_dacl(buffer, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)):
        raise OSError(ctypes.get_last_error(), "cannot inspect rollback DACL")
    if not present.value:
        return b"absent"
    if not dacl.value:
        return b"null"
    header = ctypes.string_at(dacl, 4)
    return ctypes.string_at(dacl, int.from_bytes(header[2:4], "little"))


def _acquire_rollback_root(root: Path) -> int:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel32.CreateFileW.restype = wintypes.HANDLE
        root_access = 0x0001 | 0x0080 | 0x00100000
        if len(root.parts) == 1:
            root_access |= 0x0002 | 0x0040
        handle = kernel32.CreateFileW(
            str(root.anchor),
            root_access,
            0x1 | 0x2,  # share read/write; omit delete sharing to pin the root
            None,
            3,
            0x02000000 | 0x00200000,
            None,
        )
        if handle == wintypes.HANDLE(-1).value:
            raise OSError(ctypes.get_last_error(), "cannot pin rollback volume root")
        current = int(handle)
        try:
            attributes, _reparse_tag = _windows_handle_attributes(current)
            if attributes & 0x400:
                raise ValueError("rollback volume root cannot be a reparse point")
            if not attributes & 0x10:
                raise ValueError("rollback volume root is not a directory")
            components = root.parts[1:]
            for index, component in enumerate(components):
                child = _open_rollback_relative_handle(
                    current,
                    component,
                    directory=True,
                    mutation=index == len(components) - 1,
                )
                if child is None:
                    raise FileNotFoundError(f"rollback root component is missing: {component}")
                try:
                    _close_rollback_root(current)
                except BaseException:
                    _close_rollback_root(child)
                    raise
                current = child
            return current
        except BaseException:
            try:
                _close_rollback_root(current)
            except OSError:
                pass
            raise
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise OSError("safe rollback-root acquisition requires O_NOFOLLOW support")
    anchor_fd = os.open(
        root.anchor,
        os.O_RDONLY | nofollow | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        root_handle, _owned = _open_rollback_parent_handle(anchor_fd, list(root.parts[1:]))
        return root_handle
    finally:
        os.close(anchor_fd)


def _close_rollback_root(handle: int) -> None:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        close_handle = ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL
        if not close_handle(handle):
            raise OSError(ctypes.get_last_error(), "cannot close rollback root handle")
    else:
        os.close(handle)


def _rollback_snapshot_open_flags() -> int:
    flags = os.O_RDONLY | (getattr(os, "O_NOFOLLOW", 0) if os.name != "nt" else getattr(os, "O_BINARY", 0))
    if os.name != "nt":
        flags |= getattr(os, "O_NOATIME", 0)
    return flags


def _rollback_root_identity(handle: int) -> tuple[int, int]:
    if os.name == "nt":
        return _windows_handle_identity(handle)
    root_stat = os.fstat(handle)
    return root_stat.st_dev, root_stat.st_ino


def _windows_handle_attributes(handle: int) -> tuple[int, int]:

    class FileAttributeTagInfo(ctypes.Structure):
        _fields_ = [("FileAttributes", wintypes.DWORD), ("ReparseTag", wintypes.DWORD)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_info = kernel32.GetFileInformationByHandleEx
    get_info.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    get_info.restype = wintypes.BOOL
    tag_info = FileAttributeTagInfo()
    if not get_info(handle, 9, ctypes.byref(tag_info), ctypes.sizeof(tag_info)):
        raise OSError(ctypes.get_last_error(), "cannot inspect rollback handle attributes")
    return int(tag_info.FileAttributes), int(tag_info.ReparseTag)


def _windows_handle_identity(handle: int) -> tuple[int, int]:

    class FileInfo(ctypes.Structure):
        _fields_ = [
            ("attributes", wintypes.DWORD),
            ("creation_low", wintypes.DWORD), ("creation_high", wintypes.DWORD),
            ("access_low", wintypes.DWORD), ("access_high", wintypes.DWORD),
            ("write_low", wintypes.DWORD), ("write_high", wintypes.DWORD),
            ("volume", wintypes.DWORD),
            ("size_high", wintypes.DWORD), ("size_low", wintypes.DWORD),
            ("links", wintypes.DWORD),
            ("index_high", wintypes.DWORD), ("index_low", wintypes.DWORD),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_info = kernel32.GetFileInformationByHandle
    get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(FileInfo)]
    get_info.restype = wintypes.BOOL
    info = FileInfo()
    if not get_info(handle, ctypes.byref(info)):
        raise OSError(ctypes.get_last_error(), "cannot verify pinned rollback root identity")
    index = (int(info.index_high) << 32) | int(info.index_low)
    return int(info.volume), index


def _open_rollback_relative_handle(
    root_handle: int,
    name: str,
    *,
    directory: bool,
    mutation: bool = False,
    create: bool = False,
) -> int | None:
    """Open one root-relative child without following reparse points."""

    class UnicodeString(ctypes.Structure):
        _fields_ = [
            ("Length", wintypes.USHORT),
            ("MaximumLength", wintypes.USHORT),
            ("Buffer", wintypes.LPWSTR),
        ]

    class ObjectAttributes(ctypes.Structure):
        _fields_ = [
            ("Length", wintypes.ULONG),
            ("RootDirectory", wintypes.HANDLE),
            ("ObjectName", ctypes.POINTER(UnicodeString)),
            ("Attributes", wintypes.ULONG),
            ("SecurityDescriptor", wintypes.LPVOID),
            ("SecurityQualityOfService", wintypes.LPVOID),
        ]

    class IoStatusBlock(ctypes.Structure):
        _fields_ = [("Status", ctypes.c_void_p), ("Information", ctypes.c_size_t)]

    name_buffer = ctypes.create_unicode_buffer(name)
    name_bytes = len(name.encode("utf-16-le"))
    unicode_name = UnicodeString(name_bytes, name_bytes + 2, ctypes.cast(name_buffer, wintypes.LPWSTR))
    object_attributes = ObjectAttributes(
        ctypes.sizeof(ObjectAttributes),
        wintypes.HANDLE(root_handle),
        ctypes.pointer(unicode_name),
        0x40,  # OBJ_CASE_INSENSITIVE
        None,
        None,
    )
    io_status = IoStatusBlock()
    handle = wintypes.HANDLE()
    ntdll = ctypes.WinDLL("ntdll")
    nt_create_file = ntdll.NtCreateFile
    nt_create_file.argtypes = [
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.ULONG,
        ctypes.POINTER(ObjectAttributes),
        ctypes.POINTER(IoStatusBlock),
        ctypes.c_void_p,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.ULONG,
        ctypes.c_void_p,
        wintypes.ULONG,
    ]
    nt_create_file.restype = wintypes.LONG
    desired_access = (
        0x0001 | 0x0020 | 0x0080 | 0x00100000
        if directory
        else 0x0001 | 0x0080 | 0x0100 | 0x00020000 | 0x00100000
    )
    if mutation:
        desired_access |= (0x0002 | 0x0040) if directory else (0x00010000 | 0x00040000)
    if create and not directory:
        desired_access |= 0x0002
    create_options = 0x20 | 0x00200000 | (0x1 if directory else 0)
    status = int(
        nt_create_file(
            ctypes.byref(handle), desired_access, ctypes.byref(object_attributes),
            ctypes.byref(io_status), None, 0, 0x1 | 0x2, 2 if create else 1, create_options, None, 0,
        )
    )
    status_code = status & 0xFFFFFFFF
    if status_code in {0xC0000034, 0xC000003A}:
        return None
    if create and status_code == 0xC0000035:
        raise FileExistsError(f"rollback temporary path already exists: {name[:160]}")
    if status < 0:
        status_to_error = ntdll.RtlNtStatusToDosError
        status_to_error.argtypes = [wintypes.LONG]
        status_to_error.restype = wintypes.ULONG
        raise OSError(int(status_to_error(status)), "cannot open rollback path relative to pinned root")

    raw_handle = int(handle.value)
    try:
        attributes, _reparse_tag = _windows_handle_attributes(raw_handle)
        if attributes & 0x400:
            raise ValueError("rollback paths cannot be reparse points")
        if directory and not attributes & 0x10:
            raise ValueError("rollback root path component is not a directory")
        if not directory and attributes & 0x10:
            raise ValueError("rollback target is a directory")
        return raw_handle
    except BaseException:
        _close_rollback_root(raw_handle)
        raise


def _open_rollback_parent_handle(
    root_handle: int,
    components: list[str],
    *,
    mutation: bool = False,
) -> tuple[int, bool]:
    """Open parent directory by walking each component from a pinned root."""
    if os.name == "nt":
        current = root_handle
        owned = False
        try:
            for index, component in enumerate(components):
                child = _open_rollback_relative_handle(
                    current,
                    component,
                    directory=True,
                    mutation=mutation and index == len(components) - 1,
                )
                if child is None:
                    raise FileNotFoundError(f"rollback parent component is missing: {component}")
                if owned:
                    try:
                        _close_rollback_root(current)
                    except BaseException:
                        _close_rollback_root(child)
                        raise
                current = child
                owned = True
            return current, owned
        except BaseException:
            if owned:
                try:
                    _close_rollback_root(current)
                except OSError:
                    pass
            raise

    current = os.dup(root_handle)
    try:
        for component in components:
            nofollow = getattr(os, "O_NOFOLLOW", None)
            if nofollow is None:
                raise OSError("safe nested rollback paths require O_NOFOLLOW support")
            flags = os.O_RDONLY | nofollow | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
            child = os.open(component, flags, dir_fd=current)
            try:
                child_stat = os.fstat(child)
            except BaseException:
                os.close(child)
                raise
            if not stat.S_ISDIR(child_stat.st_mode):
                os.close(child)
                raise ValueError("rollback parent component is not a directory")
            os.close(current)
            current = child
        return current, True
    except BaseException:
        try:
            os.close(current)
        except OSError:
            pass
        raise


def _open_rollback_snapshot_file(root_handle: int, name: str) -> int | None:
    import msvcrt

    raw_handle = _open_rollback_relative_handle(root_handle, name, directory=False)
    if raw_handle is None:
        return None
    try:
        return msvcrt.open_osfhandle(raw_handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        _close_rollback_root(raw_handle)
        raise


def _restore_windows_atime(fd: int, atime_ns: int) -> None:
    """Restore access time through the already pinned snapshot handle."""
    import msvcrt

    class _FileTime(ctypes.Structure):
        _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.SetFileTime.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(_FileTime), ctypes.POINTER(_FileTime), ctypes.POINTER(_FileTime),
    ]
    kernel32.SetFileTime.restype = wintypes.BOOL
    windows_epoch_ns = 11644473600 * 1_000_000_000
    filetime_value = (int(atime_ns) + windows_epoch_ns) // 100
    access_time = _FileTime(filetime_value & 0xFFFFFFFF, filetime_value >> 32)
    if not kernel32.SetFileTime(msvcrt.get_osfhandle(fd), None, ctypes.byref(access_time), None):
        raise OSError(ctypes.get_last_error(), "cannot restore rollback target access time")


