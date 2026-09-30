from __future__ import annotations

import ast
import getpass
import hashlib
import json
import os
import re
import ntpath
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .cache import SQLiteCache, TieredCache, stable_hash
from .features import rollout_feature_enabled
from .process_utils import (
    _resume_suspended_process,
    assign_process_to_job,
    canonical_root,
    close_job_object,
    create_job_object_kill_on_close,
    hidden_run_kwargs,
    process_identity,
    terminate_job_object,
    terminate_tree,
)
from .state_paths import configured_state_dir
from .json_utils import dumps as json_dumps

_GLOBAL_WINDOWS_JOB = create_job_object_kill_on_close() if os.name == "nt" else None


class _RecoveredDaemonProcess:
    """Minimal poll/wait/kill facade for a daemon verified after a Hub restart."""

    def __init__(self, pid: int, identity: dict[str, Any]):
        self.pid = pid
        self.identity = identity

    def poll(self) -> int | None:
        return None if process_identity(self.pid) == self.identity else 0

    def wait(self, timeout: float | None = None) -> int:
        deadline = None if timeout is None else time.monotonic() + timeout
        while self.poll() is None:
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(f"pid {self.pid}", timeout)
            time.sleep(0.025)
        return 0

    def kill(self) -> None:
        if self.poll() is None:
            terminate_tree(self.pid, grace_seconds=0.1)

_SECRET_PATTERNS = [
    re.compile(r"(?i)(--?(?:password|token|secret|api[-_]?key)\s*[= ]\s*)([^\s]+)"),
    re.compile(r"(?i)(Bearer\s+)[A-Za-z0-9._~+/-]+"),
    re.compile(r"(?i)(basic\s+)[A-Za-z0-9+/=]{16,}"),
    re.compile(r"sk-[a-zA-Z0-9_\-]{16,}"),
    re.compile(r"ghp_[a-zA-Z0-9]{36}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)(aws_secret_access_key\s*=\s*)([^\s]+)"),
]

_DIAGNOSTIC_PATTERNS = [
    re.compile(r"^(?P<path>[^:\n]+):(?P<line>\d+)(?::(?P<col>\d+))?[:\s]+(?P<msg>.+)$"),
    re.compile(r"^FAILED\s+(?P<path>[^:\s]+)(?:::(?P<msg>.+))?$"),
]

_MAX_INVOCATION_ERROR_CHARS = 256
_MAX_ROLLBACK_PATHS = 128
_MAX_ROLLBACK_FILE_BYTES = 16 * 1024 * 1024
_MAX_ROLLBACK_TOTAL_BYTES = 64 * 1024 * 1024
_MAX_ROLLBACK_METADATA_BYTES = 1024 * 1024


@dataclass(frozen=True)
class RollbackFileSnapshot:
    content: bytes | None
    mode: int | None
    xattrs: dict[str, bytes]
    windows_dacl: bytes | None
    atime_ns: int | None
    mtime_ns: int | None


@dataclass(frozen=True)
class RollbackSnapshot:
    root: Path
    root_identity: tuple[int, int]
    files: dict[str, RollbackFileSnapshot]
    root_guard: int


def _get_windows_dacl(fd: int) -> bytes:
    import ctypes
    import msvcrt
    from ctypes import wintypes

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


def _set_windows_dacl(path: str, descriptor: bytes) -> None:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.CreateFileW(path, 0x00040000, 0x1 | 0x2, None, 3, 0x80, None)
    if handle == wintypes.HANDLE(-1).value:
        raise OSError(ctypes.get_last_error(), "cannot open rollback temp file for DACL restore")
    try:
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        advapi32.SetKernelObjectSecurity.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p]
        advapi32.SetKernelObjectSecurity.restype = wintypes.BOOL
        security_descriptor = ctypes.create_string_buffer(descriptor)
        if not advapi32.SetKernelObjectSecurity(handle, 0x4, security_descriptor):
            raise OSError(ctypes.get_last_error(), "cannot restore rollback target DACL")
    finally:
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.CloseHandle(handle)


def _windows_dacl_bytes(descriptor: bytes) -> bytes:
    import ctypes
    from ctypes import wintypes

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
        handle = kernel32.CreateFileW(str(root), 0x80, 0x1 | 0x2, None, 3, 0x02000000, None)
        if handle == wintypes.HANDLE(-1).value:
            raise OSError(ctypes.get_last_error(), "cannot lock rollback root against rename")
        return int(handle)
    return os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0))


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


def _restore_windows_atime(fd: int, path: Path, atime_ns: int) -> None:
    """Restore access time through a path-pinned handle matching the snapshotted file."""
    import ctypes
    import msvcrt
    from ctypes import wintypes

    class _FileTime(ctypes.Structure):
        _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

    class _FileInfo(ctypes.Structure):
        _fields_ = [
            ("attributes", wintypes.DWORD),
            ("creation", _FileTime),
            ("access", _FileTime),
            ("write", _FileTime),
            ("volume", wintypes.DWORD),
            ("size_high", wintypes.DWORD),
            ("size_low", wintypes.DWORD),
            ("links", wintypes.DWORD),
            ("index_high", wintypes.DWORD),
            ("index_low", wintypes.DWORD),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(_FileInfo)]
    kernel32.GetFileInformationByHandle.restype = wintypes.BOOL
    kernel32.SetFileTime.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(_FileTime), ctypes.POINTER(_FileTime), ctypes.POINTER(_FileTime),
    ]
    kernel32.SetFileTime.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.CreateFileW(
        str(path), 0x80 | 0x100, 0x1 | 0x2, None, 3, 0x00200000, None,
    )
    if handle == wintypes.HANDLE(-1).value:
        raise OSError(ctypes.get_last_error(), "cannot safely open rollback target to preserve access time")
    try:
        original = _FileInfo()
        pinned = _FileInfo()
        original_handle = msvcrt.get_osfhandle(fd)
        if not kernel32.GetFileInformationByHandle(original_handle, ctypes.byref(original)):
            raise OSError(ctypes.get_last_error(), "cannot inspect rollback snapshot handle")
        if not kernel32.GetFileInformationByHandle(handle, ctypes.byref(pinned)):
            raise OSError(ctypes.get_last_error(), "cannot inspect pinned rollback handle")
        original_id = (original.volume, original.index_high, original.index_low)
        pinned_id = (pinned.volume, pinned.index_high, pinned.index_low)
        if original_id != pinned_id:
            raise ValueError("rollback target changed before access time preservation")

        windows_epoch_ns = 11644473600 * 1_000_000_000
        filetime_value = (int(atime_ns) + windows_epoch_ns) // 100
        access_time = _FileTime(filetime_value & 0xFFFFFFFF, filetime_value >> 32)
        if not kernel32.SetFileTime(handle, None, ctypes.byref(access_time), None):
            raise OSError(ctypes.get_last_error(), "cannot restore rollback target access time")
    finally:
        kernel32.CloseHandle(handle)


def _wait_windows_job_empty(job_handle: Any, timeout_ms: int = 2500) -> bool:
    """Wait until Windows signals that a daemon Job Object has no live processes."""
    if os.name != "nt" or not job_handle:
        return False
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    return int(kernel32.WaitForSingleObject(wintypes.HANDLE(job_handle), max(0, int(timeout_ms)))) == 0


def _stop_daemon_tree(info: dict[str, Any]) -> bool:
    """Stop the owned daemon tree without signaling a recycled Windows PID."""
    process = info["process"]
    job_handle = getattr(process, "_local_ai_job_handle", None)
    if os.name == "nt" and isinstance(job_handle, int) and not isinstance(job_handle, bool):
        try:
            terminate_job_object(job_handle)
            if not _wait_windows_job_empty(job_handle):
                return False
            if not close_job_object(job_handle):
                return False
            process._local_ai_job_handle = None
            return True
        except Exception:
            return False
    if os.name == "nt":
        expected = info.get("identity")
        current = process_identity(int(info["pid"]))
        if current is None:
            return True
        if expected and current != expected:
            return False
    try:
        return bool(terminate_tree(int(info["pid"]), grace_seconds=1.5))
    except Exception:
        return False


def _snapshot_rollback_scope(
    cwd: str,
    paths: list[str] | None,
) -> tuple[RollbackSnapshot | None, str | None]:
    if not paths:
        return None, "rollback paths are required"
    if not isinstance(paths, list) or len(paths) > _MAX_ROLLBACK_PATHS:
        return None, "rollback paths must be a list of at most 128 files"
    root_guard: int | None = None
    try:
        root = Path(cwd).resolve(strict=True)
        if not root.is_dir():
            return None, "rollback root must be a directory"
        root_guard = _acquire_rollback_root(root)
        root_stat = os.fstat(root_guard) if os.name != "nt" else root.stat()
        state: dict[str, RollbackFileSnapshot] = {}
        total_bytes = 0
        for raw in paths:
            entry_stat = None
            if not isinstance(raw, str) or not raw or "\x00" in raw:
                raise ValueError("rollback paths must be non-empty relative file paths")
            portable = raw.replace("\\", "/")
            drive, _ = ntpath.splitdrive(raw)
            parts = portable.split("/")
            if drive or ntpath.isabs(raw) or portable.startswith("/") or len(parts) != 1 or any(p in {"", ".", ".."} for p in parts):
                raise ValueError(f"invalid rollback path: {raw[:160]}")
            basename = parts[0].split(".", 1)[0].rstrip(" .").upper()
            reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10)), "COM¹", "COM²", "COM³", "LPT¹", "LPT²", "LPT³"}
            if ":" in raw or raw.endswith((".", " ")) or basename in reserved:
                raise ValueError(f"invalid platform-specific rollback path: {raw[:160]}")
            candidate = root.joinpath(*parts)
            if os.name != "nt":
                try:
                    entry_stat = os.stat(parts[0], dir_fd=root_guard, follow_symlinks=False)
                except FileNotFoundError:
                    entry_stat = None
                if entry_stat is not None and stat.S_ISLNK(entry_stat.st_mode):
                    raise ValueError(f"rollback paths cannot be symlinks: {raw[:160]}")
            else:
                resolved = candidate.resolve(strict=False)
                if not resolved.is_relative_to(root) or resolved == root or os.path.normcase(str(resolved)) != os.path.normcase(str(candidate)):
                    raise ValueError(f"rollback path escapes root: {raw[:160]}")
            key = Path(*parts).as_posix()
            if key in state:
                raise ValueError(f"duplicate rollback path: {raw[:160]}")
            if os.name != "nt":
                pass
            else:
                entry_stat = candidate.stat() if candidate.exists() else None
            if entry_stat is not None:
                if not stat.S_ISREG(entry_stat.st_mode):
                    raise ValueError(f"rollback path must be a regular file: {raw[:160]}")
                if entry_stat.st_nlink > 1:
                    raise ValueError(f"rollback does not accept multiply-linked files: {raw[:160]}")
                size = entry_stat.st_size
                if size > _MAX_ROLLBACK_FILE_BYTES or total_bytes + size > _MAX_ROLLBACK_TOTAL_BYTES:
                    raise ValueError("rollback snapshot exceeds the 16 MiB per-file or 64 MiB total limit")
                open_flags = _rollback_snapshot_open_flags()
                fd = os.open(parts[0] if os.name != "nt" else candidate, open_flags, **({"dir_fd": root_guard} if os.name != "nt" else {}))
                try:
                    opened_stat = os.fstat(fd)
                    if (opened_stat.st_dev, opened_stat.st_ino) != (entry_stat.st_dev, entry_stat.st_ino) or opened_stat.st_nlink > 1:
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
                        _restore_windows_atime(fd, candidate, opened_stat.st_atime_ns)
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
                    os.close(fd)
                if total_bytes + len(content) > _MAX_ROLLBACK_TOTAL_BYTES:
                    raise ValueError("rollback snapshot exceeds the 64 MiB total limit")
                total_bytes += len(content)
                mode = stat.S_IMODE(entry_stat.st_mode)
                file_snapshot = RollbackFileSnapshot(content, mode, xattrs, windows_dacl, entry_stat.st_atime_ns, entry_stat.st_mtime_ns)
            else:
                file_snapshot = RollbackFileSnapshot(None, None, {}, None, None, None)
            state[key] = file_snapshot
        return RollbackSnapshot(root, (root_stat.st_dev, root_stat.st_ino), state, root_guard), None
    except (OSError, ValueError, TypeError) as exc:
        if root_guard is not None:
            try:
                _close_rollback_root(root_guard)
            except OSError:
                pass
        return None, f"cannot snapshot rollback scope: {str(exc)[:256]}"


def _restore_rollback_scope(
    cwd: str,
    snapshot: RollbackSnapshot,
) -> None:
    root = Path(cwd).resolve(strict=True)
    root_stat = os.fstat(snapshot.root_guard) if os.name != "nt" else root.stat()
    if (root_stat.st_dev, root_stat.st_ino) != snapshot.root_identity or root != snapshot.root:
        raise OSError("rollback root changed since snapshot")
    incomplete: list[str] = []
    for relative, file_snapshot in snapshot.files.items():
        content, mode = file_snapshot.content, file_snapshot.mode
        if os.name != "nt":
            try:
                current_stat = os.stat(relative, dir_fd=snapshot.root_guard, follow_symlinks=False)
            except FileNotFoundError:
                current_stat = None
            if current_stat is not None and stat.S_ISDIR(current_stat.st_mode):
                raise OSError(f"refusing to remove rollback directory: {relative}")
            if current_stat is not None and (stat.S_ISLNK(current_stat.st_mode) or current_stat.st_nlink > 1):
                incomplete.append(relative)
            if content is None:
                if current_stat is not None:
                    os.unlink(relative, dir_fd=snapshot.root_guard)
                continue
            temp_name = f".local-ai-rollback-{uuid.uuid4().hex}"
            fd = os.open(temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0), 0o600, dir_fd=snapshot.root_guard)
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
                os.replace(temp_name, relative, src_dir_fd=snapshot.root_guard, dst_dir_fd=snapshot.root_guard)
            finally:
                os.close(fd)
                try:
                    os.unlink(temp_name, dir_fd=snapshot.root_guard)
                except FileNotFoundError:
                    pass
            continue
        candidate = root / relative
        if candidate.is_dir() and not candidate.is_symlink():
            raise OSError(f"refusing to replace rollback directory: {relative}")
        current_stat = candidate.stat() if candidate.exists() else None
        if candidate.is_symlink() or (current_stat is not None and current_stat.st_nlink > 1):
            incomplete.append(relative)
        if content is None:
            if candidate.exists() or candidate.is_symlink():
                candidate.unlink()
            continue
        fd, temp_name = tempfile.mkstemp(prefix=".local-ai-rollback-", dir=str(candidate.parent))
        try:
            with os.fdopen(fd, "wb") as temp_file:
                temp_file.write(content)
                temp_file.flush()
                os.fsync(temp_file.fileno())
            if mode is not None:
                os.chmod(temp_name, mode)
            if file_snapshot.windows_dacl is not None:
                _set_windows_dacl(temp_name, file_snapshot.windows_dacl)
            os.replace(temp_name, candidate)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
    if incomplete:
        names = ", ".join(incomplete[:8])
        raise OSError(f"rollback restored declared paths but cannot verify external aliases for: {names}")


@dataclass(frozen=True)
class CommandInvocation:
    """Validated subprocess input that cannot request shell interpretation."""

    argv: list[str]
    cwd: str | None = None
    shell: bool = False


def _invocation_error(reason: str, error: str) -> dict[str, Any]:
    return {
        "safe": False,
        "reason": reason,
        "error": error[:_MAX_INVOCATION_ERROR_CHARS],
        "terminal": True,
        "retryable": False,
    }


def _invocation_cwd(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, os.PathLike):
        converted = os.fspath(value)
        if isinstance(converted, str):
            return converted
    raise TypeError("cwd must be a string or path-like value")


def validate_invocation(invocation: Any) -> dict[str, Any]:
    """Validate structured argv input; raw command strings are never parsed here."""
    try:
        if isinstance(invocation, str):
            return _invocation_error(
                "unstructured_shell_text",
                "command must be structured argv; raw shell text is not accepted",
            )

        if isinstance(invocation, CommandInvocation):
            argv = invocation.argv
            cwd_value = invocation.cwd
            shell = invocation.shell
        elif isinstance(invocation, Mapping):
            if "argv" not in invocation:
                return _invocation_error("missing_argv", "structured invocation requires argv")
            argv = invocation["argv"]
            cwd_value = invocation.get("cwd")
            shell = invocation.get("shell", False)
        elif isinstance(invocation, (list, tuple)):
            argv = invocation
            cwd_value = None
            shell = False
        else:
            return _invocation_error("invalid_invocation_type", "invocation must be argv list or structured mapping")

        if shell is not False:
            reason = "shell_true_not_allowed" if shell is True else "invalid_shell_flag"
            return _invocation_error(reason, "structured invocation must set shell=False")
        if not isinstance(argv, (list, tuple)):
            return _invocation_error("argv_not_sequence", "argv must be a list or tuple of strings")
        if not argv:
            return _invocation_error("empty_argv", "argv must contain an executable")

        for index, value in enumerate(argv):
            if not isinstance(value, str):
                return _invocation_error(
                    "argv_argument_not_string",
                    f"argv argument at index {index} must be a string",
                )
            if "\x00" in value:
                return _invocation_error("nul_in_argv", f"argv argument at index {index} contains NUL")
        if not argv[0].strip():
            return _invocation_error("empty_executable", "argv executable must not be empty")

        cwd = _invocation_cwd(cwd_value)
        return {
            "safe": True,
            "reason": "ok",
            "argv": list(argv),
            "cwd": cwd,
            "shell": False,
            "terminal": False,
            "retryable": False,
        }
    except Exception as exc:
        return _invocation_error(
            "invocation_serialization_error",
            f"invocation serialization failed: {type(exc).__name__}"[:_MAX_INVOCATION_ERROR_CHARS],
        )


def build_invocation(
    executable: str,
    args: Sequence[str] = (),
    *,
    cwd: str | os.PathLike[str] | None = None,
) -> CommandInvocation:
    """Build validated argv input for subprocess APIs; never construct shell text."""
    if isinstance(args, (str, bytes)) or not isinstance(args, (list, tuple)):
        raise ValueError("args must be a list or tuple of strings")
    result = validate_invocation({"argv": [executable, *args], "cwd": cwd, "shell": False})
    if not result["safe"]:
        raise ValueError(result["error"])
    return CommandInvocation(argv=result["argv"], cwd=result["cwd"], shell=False)


def _redact_secrets(text: str) -> str:
    if not text:
        return ""
    res = text
    for pat in _SECRET_PATTERNS:
        if pat.groups == 2:
            res = pat.sub(r"\1***", res)
        elif pat.groups == 1:
            res = pat.sub(r"\1***", res)
        else:
            res = pat.sub("***REDACTED_SECRET***", res)
    return res


class _BoundedStreamBuffer:
    """Bounded rolling buffer that retains the most recent output characters without OOM."""

    def __init__(self, max_chars: int, redact: bool = True):
        self.max_chars = max(1024, int(max_chars))
        self.chunks: deque[str] = deque()
        self.total_chars = 0
        self.total_lines = 0
        self.lock = threading.Lock()
        self.redact = redact

    def append(self, chunk: str) -> None:
        if not chunk:
            return
        cleaned = _redact_secrets(chunk) if self.redact else chunk
        if len(cleaned) > self.max_chars:
            cleaned = cleaned[-self.max_chars:]
        with self.lock:
            self.chunks.append(cleaned)
            self.total_chars += len(cleaned)
            self.total_lines += 1
            while self.chunks and (self.total_chars - len(self.chunks[0])) >= self.max_chars:
                discarded = self.chunks.popleft()
                self.total_chars -= len(discarded)

    def getvalue(self) -> str:
        with self.lock:
            return "".join(self.chunks)[-self.max_chars:]

    def write(self, chunk: str) -> None:
        self.append(chunk)

    def peek(self, chars: int = 500) -> str:
        if chars <= 0:
            return ""
        with self.lock:
            if not self.chunks:
                return ""
            collected: list[str] = []
            collected_len = 0
            for chunk in reversed(self.chunks):
                collected.append(chunk)
                collected_len += len(chunk)
                if collected_len >= chars:
                    break
            joined = "".join(reversed(collected))
            return joined[-chars:]


_INTERACTIVE_PATTERNS = [
    re.compile(r"\[[yY]/[nN]\]"),
    re.compile(r"\(yes/no\)", re.IGNORECASE),
    re.compile(r"password(\s+for\s+.*)?:", re.IGNORECASE),
    re.compile(r"press\s+any\s+key", re.IGNORECASE),
    re.compile(r"do\s+you\s+want\s+to\s+continue", re.IGNORECASE),
]


def _is_interactive_prompt(text: str) -> bool:
    """Check if output tail looks like an interactive user prompt."""
    if not text:
        return False
    tail = text[-300:] if len(text) > 300 else text
    return any(p.search(tail) for p in _INTERACTIVE_PATTERNS)


class CommandBroker:
    """Safe shared command runner with repo-state-aware cache and single-flight."""

    READ_ONLY = {
        "git", "rg", "ripgrep", "grep", "findstr", "where", "which",
        "fd", "fdfind", "find", "cat", "type", "head", "tail", "wc",
        "diff", "cmp", "sort", "uniq", "cut", "tr", "file", "stat",
        "echo", "pwd", "tree", "jq", "yq", "ls", "dir",
        "tasklist", "whoami", "hostname", "systeminfo", "ver", "ipconfig", "netstat",
        "fc", "comp", "attrib", "set", "env", "printenv",
    }
    READ_FILTERS = {
        "grep", "ripgrep", "rg", "findstr", "select-string", "find", "head", "tail", "wc", "sort", "uniq", "cut", "tr", "jq", "yq",
        "cat", "type", "format-table", "select-object", "convertto-json", "convertfrom-json", "out-string", "out-null", "tee", "more", "less",
    }
    VALIDATORS = {
        "pytest", "phpunit", "phpstan", "ruff", "mypy", "eslint", "tsc", "cargo",
        "dotnet", "go", "npm", "pnpm", "yarn", "bun", "composer", "make", "cmake",
        "ctest", "mvn", "mvnw", "gradle", "gradlew", "gradlew.bat", "flake8", "pylint",
        "black", "isort", "bandit", "shellcheck", "yamllint",
    }
    PURE_VALIDATORS = {
        "pytest", "phpunit", "phpstan", "pest", "ruff", "mypy", "eslint", "tsc",
        "pyflakes", "flake8", "pylint", "bandit", "radon", "yamllint", "shellcheck",
        "markdownlint", "biome", "oxlint", "clippy", "coverage", "vitest", "jest",
        "mocha", "ava", "playwright", "cypress", "tox", "nox", "pre-commit",
    }
    MUTATING_WORDS = {
        "commit", "push", "pull", "merge", "rebase", "reset", "clean", "checkout", "switch", "restore", "add", "stash", "apply",
        "install", "update", "upgrade", "publish", "deploy", "migrate", "migration", "seed", "format", "fix", "write", "delete", "remove",
    }
    DANGEROUS_EXES = {"rm", "del", "erase", "rmdir", "shutdown", "reboot", "poweroff", "mkfs", "diskpart", "format"}

    def __init__(self, config: dict[str, Any], artifacts: Any = None, repo_state: Any = None):
        self.config = config
        self.artifacts = artifacts
        if repo_state is None:
            from .repo_state import RepoStateTracker
            repo_state = RepoStateTracker(config)
        self.repo_state = repo_state
        cfg = config.get("commands", {})
        self.enabled = bool(cfg.get("enabled", True))
        self.policy_blocking = bool(cfg.get("policy_blocking", False))
        self.timeout = int(cfg.get("timeout_seconds", 1800))
        self.max_output_chars = int(cfg.get("max_output_chars", 2_000_000))
        self.inline_chars = int(cfg.get("inline_output_chars", 5000))
        self.daemon_log_max_bytes = min(2 * 1024 * 1024, max(1024, int(cfg.get("daemon_log_max_bytes", 512 * 1024))))
        self.daemon_ttl_seconds = min(7 * 24 * 60 * 60, max(1, int(cfg.get("daemon_ttl_seconds", 24 * 60 * 60))))
        self.max_daemons = min(32, max(1, int(cfg.get("daemon_max_count", 16))))
        self._daemon_owner_id = self._get_daemon_owner_id()
        self.coalesce_wait_seconds = max(1.0, float(cfg.get("coalesced_wait_seconds", 90.0)))
        self.terminate_grace_seconds = max(0.1, float(cfg.get("terminate_grace_seconds", 2.0)))
        self.post_kill_drain_seconds = max(0.1, float(cfg.get("post_kill_drain_seconds", 2.0)))
        workspace_cache = config.get("workspace_cache", {})
        self.git_snapshot_timeout = max(0.5, float(workspace_cache.get("git_status_timeout_seconds", 2.5)))
        state_dir = configured_state_dir(config)
        self._daemon_state_dir = state_dir / "daemons"
        self._daemon_registry_path = self._daemon_state_dir / "registry.json"
        l1_entries = int(cfg.get("l1_entries", 128))
        self.success_cache = TieredCache(SQLiteCache(state_dir / "cache.sqlite3", "command:success", int(cfg.get("success_ttl_seconds", 43200)), int(cfg.get("max_entries", 5000))), l1_entries, int(cfg.get("l1_ttl_seconds", 900)))
        self.failure_cache = TieredCache(SQLiteCache(state_dir / "cache.sqlite3", "command:failure", int(cfg.get("failure_ttl_seconds", 180)), int(cfg.get("max_failure_entries", 1000))), max(32, l1_entries // 2), min(300, int(cfg.get("l1_ttl_seconds", 900))))
        self.suppression_cache = TieredCache(SQLiteCache(state_dir / "cache.sqlite3", "command:suppression", int(cfg.get("suppression_ttl_seconds", 900)), int(cfg.get("max_suppression_entries", 2000))), max(32, l1_entries // 2), min(300, int(cfg.get("l1_ttl_seconds", 900))))
        self._lock = threading.Lock()
        self._inflight: dict[str, threading.Event] = {}
        self._last: dict[str, dict[str, Any]] = {}
        self.hits = 0
        self.misses = 0
        self.coalesced = 0
        self.coalesced_timeouts = 0
        self.executed = 0
        self.blocked = 0
        self.suppressed = 0
        self.cancelled = 0
        self._blocked_by_reason: dict[str, int] = {}
        self._active_commands: dict[str, dict[str, Any]] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._active_cancel_keys: dict[str, tuple[str, str]] = {}
        self._daemons: dict[str, dict[str, Any]] = {}
        self._daemons_lock = threading.Lock()
        self._daemon_slots = threading.BoundedSemaphore(self.max_daemons)
        self._load_daemon_registry()
        self.incident_store: Any = None
        self.verification_store: Any = None
        self.policy_engine: Any = None
        self.error_distiller: Any = None

    def set_policy_engine(self, policy_engine: Any) -> None:
        self.policy_engine = policy_engine

    def set_incident_store(self, incident_store: Any) -> None:
        self.incident_store = incident_store

    def set_verification_store(self, verification_store: Any) -> None:
        self.verification_store = verification_store

    def _record_command_verification(
        self,
        result: dict[str, Any],
        *,
        tenant: str,
        task_id: str,
        criterion: str,
        command_id: str,
        command_digest: str,
        repository_revision: str,
        duration_ms: float,
        cached: bool = False,
    ) -> None:
        if not result.get("success") or not task_id or self.verification_store is None:
            return
        try:
            if self.artifacts is None:
                raise RuntimeError("artifact store unavailable")
            from .agent_verification import VerificationReceipt

            proof = {
                "kind": "command_verification",
                "task_id": task_id,
                "criterion": criterion,
                "command_id": command_id,
                "command_sha256": command_digest,
                "exit_code": int(result.get("exit_code", 0)),
                "repository_revision": repository_revision,
                "duration_ms": max(0.0, float(duration_ms or 0)),
                "cached": cached,
            }
            if hasattr(self.artifacts, "put_json"):
                evidence_id = self.artifacts.put_json(proof, tenant, "command_verification")
            elif hasattr(self.artifacts, "put"):
                evidence_id = self.artifacts.put(json_dumps(proof), tenant, "command_verification", "application/json")
            else:
                evidence_id = ""
            if not evidence_id:
                raise RuntimeError("verification evidence was not persisted")
            receipt = VerificationReceipt.create(
                task_id=task_id,
                criterion=criterion,
                passed=True,
                command_id=command_id,
                evidence_id=str(evidence_id),
                repository_revision=repository_revision,
                details={
                    "exit_code": proof["exit_code"],
                    "duration_ms": proof["duration_ms"],
                    "cached": cached,
                },
            )
            self.verification_store.record(receipt)
            result["verification_receipt"] = receipt.to_dict()
            result["verification_evidence_id"] = str(evidence_id)
        except Exception:
            result["verification_receipt_warning"] = (
                "command succeeded but durable verification evidence was unavailable"
            )

    def set_error_distiller(self, error_distiller: Any) -> None:
        """Set the optional local-model fallback for unstructured command failures."""
        self.error_distiller = error_distiller

    @staticmethod
    def _daemon_environment(extra: dict[str, str] | None = None) -> dict[str, str]:
        """Inherit a minimal OS runtime environment; add only explicit, bounded overrides."""
        key_pattern = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
        inherited_allowlist = {
            "PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT",
            "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
            "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "VIRTUAL_ENV", "LANG", "LANGUAGE", "TZ",
        }
        result = {
            key: value
            for key, value in os.environ.items()
            if key_pattern.fullmatch(key)
            and (key.upper() in inherited_allowlist or key.upper().startswith("LC_"))
            and isinstance(value, str)
            and "\x00" not in value
        }
        if extra is None:
            return result
        if not isinstance(extra, dict) or len(extra) > 128:
            raise ValueError("daemon environment must be a mapping with at most 128 entries")
        total_bytes = 0
        for key, value in extra.items():
            if not isinstance(key, str) or not key_pattern.fullmatch(key):
                raise ValueError("daemon environment contains an invalid variable name")
            if not isinstance(value, str) or "\x00" in value:
                raise ValueError(f"daemon environment value for {key} must be a NUL-free string")
            total_bytes += len(key.encode("utf-8")) + len(value.encode("utf-8"))
            if len(key) > 255 or len(value) > 32_767 or total_bytes > 64 * 1024:
                raise ValueError("daemon environment exceeds the supported size limit")
            if os.name == "nt":
                for existing in list(result):
                    if existing.casefold() == key.casefold():
                        del result[existing]
            result[key] = value
        return result

    @staticmethod
    def _get_daemon_owner_id() -> str:
        try:
            owner = getpass.getuser()
        except Exception:
            owner = f"uid:{os.getuid()}" if hasattr(os, "getuid") else "local-ai-hub"
        return hashlib.sha256(f"local-ai-daemon-owner:{owner}".encode("utf-8")).hexdigest()[:32]

    @classmethod
    def _daemon_argv(cls, command: str | Sequence[str]) -> tuple[list[str] | None, str, str | None]:
        if isinstance(command, str):
            if not command.strip() or len(command) > 8192:
                return None, "", "daemon command must be a non-empty string of at most 8192 characters"
            argv = cls._tokens(command)
            executable = ""
            if argv:
                executable = (ntpath.basename(argv[0]) if os.name == "nt" else Path(argv[0]).name).casefold()
            explicit_shells = {"sh", "bash", "dash", "zsh", "fish", "cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe"}
            if cls._needs_shell(command) and executable not in explicit_shells:
                return None, "", "daemon command contains shell syntax; implicit shell execution is not allowed"
            label = cls._safe_label(command)
        elif isinstance(command, Sequence) and not isinstance(command, (bytes, bytearray)):
            if not command or len(command) > 128:
                return None, "", "daemon argv must contain 1 to 128 arguments"
            if any(not isinstance(arg, str) or "\x00" in arg or len(arg) > 8192 for arg in command):
                return None, "", "daemon argv entries must be NUL-free strings of at most 8192 characters"
            argv = list(command)
            if not argv[0]:
                return None, "", "daemon argv[0] must name an executable"
            if sum(len(arg.encode("utf-8")) for arg in argv) > 32 * 1024:
                return None, "", "daemon argv exceeds the 32 KiB size limit"
            label = cls._safe_label(shlex.join(argv))
        else:
            return None, "", "daemon command must be a string or structured argv list"
        if not argv:
            return None, "", "daemon command could not be parsed"
        return argv, label, None

    def _schedule_daemon_expiry(self, info: dict[str, Any]) -> None:
        previous = info.get("ttl_timer")
        if previous is not None:
            previous.cancel()
        delay = max(0.0, float(info["expires_at"]) - time.time())
        timer = threading.Timer(delay, self._expire_daemon, args=(info["daemon_id"],))
        timer.daemon = True
        info["ttl_timer"] = timer
        timer.start()

    def _release_daemon_slot(self, info: dict[str, Any]) -> None:
        if not info.get("_slot_acquired") or info.get("_slot_released"):
            return
        info["_slot_released"] = True
        try:
            self._daemon_slots.release()
        except ValueError:
            pass

    def _refresh_daemon_capacity(self) -> None:
        now = time.time()
        changed = False
        with self._daemons_lock:
            for info in self._daemons.values():
                if info["process"].poll() is None:
                    continue
                reader = info.get("reader_thread")
                if reader is not None:
                    reader.join(timeout=0.1)
                self._close_daemon_log(info)
                info.setdefault("stopped_at", now)
                self._release_daemon_slot(info)
                changed = True
            if changed:
                self._persist_daemon_registry()

    def _expire_daemon(self, daemon_id: str) -> None:
        for attempt in range(3):
            result = self.stop_daemon(daemon_id)
            if result.get("process_tree_stopped") is True or result.get("status") == "not_found":
                return
            if attempt < 2:
                time.sleep(0.25)
        with self._daemons_lock:
            info = self._daemons.get(daemon_id)
            if info is not None:
                info["ttl_stop_failed"] = True

    def _watch_daemon_exit(self, daemon_id: str, process: subprocess.Popen[Any]) -> None:
        """Reap descendants promptly when a daemon leader exits on its own."""
        while True:
            try:
                process.wait(timeout=1.0)
                break
            except subprocess.TimeoutExpired:
                continue
            except (OSError, ValueError):
                return
        status = self.daemon_status(daemon_id)
        if status.get("process_tree_stopped") is not True:
            self._expire_daemon(daemon_id)

    def _load_daemon_registry(self) -> None:
        """Reattach only live PIDs whose executable and creation identity still match."""
        registry = self._daemon_registry_path
        try:
            if registry.is_symlink() or registry.stat().st_size > 256 * 1024:
                return
            with registry.open("r", encoding="utf-8") as stream:
                payload = json.load(stream)
        except (OSError, ValueError, TypeError):
            return
        if not isinstance(payload, dict) or payload.get("version") != 2:
            return
        rows = payload.get("daemons")
        if not isinstance(rows, list):
            return
        expected_dir = self._daemon_state_dir.resolve(strict=False)
        for row in rows[:50]:
            if not isinstance(row, dict):
                continue
            daemon_id = row.get("daemon_id")
            pid = row.get("pid")
            identity = row.get("identity")
            if (
                not isinstance(daemon_id, str)
                or not re.fullmatch(r"dmn_[0-9a-f]{32}", daemon_id)
                or isinstance(pid, bool)
                or not isinstance(pid, int)
                or not isinstance(identity, dict)
                or identity.get("pid") != pid
                or row.get("owner_id") != self._daemon_owner_id
                or process_identity(pid) != identity
            ):
                continue
            if not self._daemon_slots.acquire(blocking=False):
                try:
                    terminate_tree(pid, grace_seconds=self.terminate_grace_seconds)
                except Exception:
                    pass
                continue
            log_path = self._daemon_state_dir / f"{daemon_id}.log"
            try:
                if log_path.is_symlink() or log_path.resolve(strict=False).parent != expected_dir:
                    self._daemon_slots.release()
                    continue
                log_fh = log_path.open("r+b")
                log_fh.seek(0, os.SEEK_END)
                size = log_fh.tell()
                log_fh.seek(max(0, size - self.daemon_log_max_bytes), os.SEEK_SET)
                log_buffer = bytearray(log_fh.read(self.daemon_log_max_bytes))
            except OSError:
                self._daemon_slots.release()
                continue
            try:
                started_at = float(row.get("started_at"))
                expires_at = float(row.get("expires_at"))
            except (TypeError, ValueError, OverflowError):
                log_fh.close()
                self._daemon_slots.release()
                continue
            if not (0 < started_at < float("inf") and started_at <= expires_at < float("inf")):
                log_fh.close()
                self._daemon_slots.release()
                continue
            name = row.get("name")
            command = row.get("command")
            info = {
                "daemon_id": daemon_id,
                "process": _RecoveredDaemonProcess(pid, identity),
                "pid": pid,
                "identity": identity,
                "owner_id": self._daemon_owner_id,
                "name": self._safe_label(name) if isinstance(name, str) else daemon_id,
                "command": self._safe_label(command) if isinstance(command, str) else "",
                "cwd": "",
                "log_path": str(log_path),
                "log_fh": log_fh,
                "log_buffer": log_buffer,
                "log_lock": threading.Lock(),
                "reader_thread": None,
                "_log_closed": False,
                "started_at": started_at,
                "expires_at": expires_at,
                "_slot_acquired": True,
                "_slot_released": False,
            }
            self._daemons[daemon_id] = info
        for info in self._daemons.values():
            try:
                self._schedule_daemon_expiry(info)
            except RuntimeError:
                info["ttl_timer"] = None

    def _persist_daemon_registry(self) -> bool:
        """Atomically persist bounded, secret-redacted daemon identity metadata."""
        try:
            self._daemon_state_dir.mkdir(parents=True, exist_ok=True)
            registry = self._daemon_registry_path
            if registry.is_symlink():
                return False
            rows: list[dict[str, Any]] = []
            for daemon_id, info in self._daemons.items():
                process = info["process"]
                if process.poll() is not None:
                    continue
                identity = info.get("identity")
                if not isinstance(identity, dict) or identity.get("pid") != int(info["pid"]):
                    continue
                rows.append(
                    {
                        "daemon_id": daemon_id,
                        "pid": int(info["pid"]),
                        "identity": identity,
                        "owner_id": info["owner_id"],
                        "name": self._safe_label(str(info.get("name", daemon_id)))[:128],
                        "command": self._safe_label(str(info.get("command", ""))),
                        "started_at": float(info["started_at"]),
                        "expires_at": float(info["expires_at"]),
                    }
                )
                if len(rows) >= 50:
                    break
            payload = json.dumps({"version": 2, "daemons": rows}, ensure_ascii=True, separators=(",", ":"))
            temp_path = registry.with_name(f"registry.{os.getpid()}.{uuid.uuid4().hex}.tmp")
            fd = os.open(temp_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp_path, registry)
            except Exception:
                try:
                    temp_path.unlink()
                except OSError:
                    pass
                raise
            return True
        except (OSError, TypeError, ValueError, OverflowError):
            return False

    @staticmethod
    def _flush_daemon_log(info: dict[str, Any]) -> None:
        log_fh = info.get("log_fh")
        log_buffer = info.get("log_buffer")
        if log_fh is None or not isinstance(log_buffer, bytearray) or info.get("_log_closed"):
            return
        log_lock = info.get("log_lock")
        try:
            if log_lock is None:
                log_fh.seek(0)
                log_fh.truncate()
                log_fh.write(bytes(log_buffer))
                log_fh.flush()
            else:
                with log_lock:
                    log_fh.seek(0)
                    log_fh.truncate()
                    log_fh.write(bytes(log_buffer))
                    log_fh.flush()
        except (OSError, ValueError):
            pass

    @classmethod
    def _capture_daemon_output(cls, read_fh: Any, info: dict[str, Any], max_bytes: int) -> None:
        try:
            while True:
                chunk = read_fh.read(64 * 1024)
                if not chunk:
                    break
                with info["log_lock"]:
                    buffer = info["log_buffer"]
                    buffer.extend(chunk)
                    if len(buffer) > max_bytes:
                        del buffer[: len(buffer) - max_bytes]
        except (OSError, ValueError):
            pass
        finally:
            try:
                read_fh.close()
            except Exception:
                pass
            cls._flush_daemon_log(info)

    @classmethod
    def _close_daemon_log(cls, info: dict[str, Any]) -> None:
        """Close a daemon log handle exactly once, including natural exits."""
        if info.get("_log_closed"):
            return
        cls._flush_daemon_log(info)
        try:
            info["log_fh"].close()
        except Exception:
            pass
        info["_log_closed"] = True

    @staticmethod
    def _tokens(command: str) -> list[str]:
        try:
            tokens = shlex.split(command, posix=(os.name != "nt"))
            if os.name == "nt":
                return [t[1:-1] if (len(t) >= 2 and ((t.startswith('"') and t.endswith('"')) or (t.startswith("'") and t.endswith("'")))) else t for t in tokens]
            return tokens
        except ValueError:
            return []

    @staticmethod
    def _strip_null_redirections(cmd: str) -> str:
        c = re.sub(r"\s*(?:2>&1|2>\s*(?:/dev/null|nul|\$null)|>\s*(?:/dev/null|nul|\$null)|\|\s*Out-Null)\s*$", "", cmd, flags=re.IGNORECASE)
        return c.strip()

    @staticmethod
    def _split_outside_quotes(s: str, delimiters: tuple[str, ...]) -> list[tuple[str, str]]:
        parts = []
        current = []
        in_quote = False
        quote_char = ''
        i = 0
        n = len(s)
        last_delim = ''
        while i < n:
            c = s[i]
            if in_quote:
                current.append(c)
                if c == quote_char:
                    in_quote = False
                i += 1
                continue
            if c in ('"', "'"):
                in_quote = True
                quote_char = c
                current.append(c)
                i += 1
                continue
            matched_delim = None
            for d in delimiters:
                if s[i:i+len(d)] == d:
                    matched_delim = d
                    break
            if matched_delim:
                parts.append((last_delim, "".join(current).strip()))
                current = []
                last_delim = matched_delim
                i += len(matched_delim)
            else:
                current.append(c)
                i += 1
        if current or last_delim:
            parts.append((last_delim, "".join(current).strip()))
        return [(d, p) for d, p in parts if p]

    @staticmethod
    def _is_powershell_command(cmd: str) -> bool:
        trimmed = cmd.strip()
        if trimmed.startswith(("$", "&")):
            return True
        ps_prefixes = (
            "get-", "set-", "test-", "invoke-", "start-", "stop-", "select-", "format-",
            "where-", "out-", "new-", "remove-", "clear-", "write-", "read-", "measure-",
            "compare-", "convertfrom-", "convertto-", "add-type",
        )
        first = trimmed.split()[0].lower() if trimmed.split() else ""
        return any(first.startswith(p) for p in ps_prefixes)

    def classify(self, command: str) -> dict[str, Any]:
        cfg = self.config.get("commands", {})
        trimmed = self._strip_null_redirections(command.strip())
        if not trimmed:
            return {"class": "unknown", "cacheable": False, "allowed": False, "reason": "empty or unparsable command"}

        # Direct PowerShell syntax or explicit pwsh/powershell invocation
        if self._is_powershell_command(trimmed) or trimmed.lower().startswith(("pwsh", "powershell")):
            return self._classify_single(trimmed)

        # Compound sequences (; or &&) outside quotes
        seq_parts = self._split_outside_quotes(trimmed, (";", "&&"))
        if len(seq_parts) > 1:
            classes = []
            replay_safe = True
            for _, subcmd in seq_parts:
                sub_res = self.classify(subcmd)
                if not sub_res.get("allowed"):
                    return sub_res
                classes.append(sub_res.get("class", "unknown"))
                replay_safe = replay_safe and bool(
                    sub_res.get("replay_safe", sub_res.get("class") == "read")
                )
            order = ["dangerous", "unknown", "mutating", "build", "validation", "read"]
            for o in order:
                if o in classes:
                    return {"class": o, "cacheable": False, "allowed": bool(cfg.get(f"allow_{o}", o in {"read", "validation", "build"})), "replay_safe": replay_safe, "reason": f"compound sequence ({o})"}
            return {"class": "read", "cacheable": False, "allowed": True, "reason": "compound sequence"}

        # Pipelines (|) outside quotes
        pipe_parts = self._split_outside_quotes(trimmed, ("|",))
        if len(pipe_parts) > 1:
            first_delim, first_cmd = pipe_parts[0]
            first_res = self.classify(first_cmd)
            if not first_res.get("allowed"):
                return first_res
            for _, stage in pipe_parts[1:]:
                stok = self._tokens(stage)
                if not stok:
                    continue
                sexe = ntpath.basename(stok[0].strip('"').replace("/", "\\")).lower()
                sexe_base = re.sub(r"\.(exe|cmd|bat|ps1|sh)$", "", sexe)
                if sexe_base not in self.READ_FILTERS and sexe_base not in self.READ_ONLY:
                    return {"class": "unknown", "cacheable": False, "allowed": False, "reason": f"pipeline filter {sexe_base} not allowed"}
            replay_safe = bool(first_res.get("replay_safe", first_res.get("class") == "read"))
            return {"class": first_res.get("class", "read"), "cacheable": False, "allowed": True, "replay_safe": replay_safe, "reason": "pipeline with safe filters"}

        return self._classify_single(trimmed)

    def _classify_single(self, command: str) -> dict[str, Any]:
        tokens = self._tokens(command)
        if not tokens:
            return {"class": "unknown", "cacheable": False, "allowed": False, "reason": "empty or unparsable command"}
        raw_exe = tokens[0].strip('"').replace("/", "\\")
        exe = ntpath.basename(raw_exe).lower() or Path(tokens[0].strip('"')).name.lower()
        exe_base = re.sub(r"\.(exe|cmd|bat|ps1|sh)$", "", exe)
        lower = [t.lower() for t in tokens[1:]]
        cfg = self.config.get("commands", {})

        if exe_base in self.DANGEROUS_EXES:
            return {"class": "dangerous", "cacheable": False, "allowed": False, "reason": "dangerous executable"}

        extra_allowed = set(str(x).strip().lower() for x in cfg.get("extra_allowed_tools", []))
        if exe_base in extra_allowed:
            # A user whitelist permits execution; it does not prove replay safety.
            return {"class": "validation", "cacheable": False, "allowed": True, "replay_safe": False, "reason": f"user-whitelisted tool has unknown side effects: {exe_base}"}

        # PowerShell commands or script blocks
        if self._is_powershell_command(command) or exe_base in {"pwsh", "powershell"}:
            cmd_lower = command.lower()
            ps_dangerous = (
                "remove-item", "format-volume", "stop-computer", "restart-computer",
                "stop-process", "invoke-webrequest", "invoke-restmethod", "start-bitstransfer",
                "set-executionpolicy", "new-service", "stop-service", "rmdir /s", "del /s",
                "-encodedcommand", " -e ", " -enc ",
            )
            if any(d in cmd_lower for d in ps_dangerous):
                return {"class": "dangerous", "cacheable": False, "allowed": False, "reason": "dangerous or network powershell command"}

            ps_mutating = (
                "set-content", "add-content", "out-file", "new-item", "copy-item",
                "move-item", "rename-item", "clear-content", "git push", "git commit",
                "git merge", "git reset", "git rebase", "git checkout -b", "git branch -d",
            )
            if any(m in cmd_lower for m in ps_mutating):
                return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": "mutating powershell command"}

            validation_keywords = {"test", "validate", "check", "audit", "-runtests", "pester"} | extra_allowed
            if any(w in cmd_lower for w in validation_keywords):
                replay_safe = not any(w and w in cmd_lower for w in extra_allowed)
                reason = (
                    "powershell validation command"
                    if replay_safe
                    else "powershell command includes user-whitelisted tool with unknown side effects"
                )
                return {"class": "validation", "cacheable": False, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": replay_safe, "reason": reason}

            ps_read_prefixes = ("get-", "select-", "measure-", "format-", "test-path", "where-", "out-string", "compare-", "convertfrom-", "convertto-")
            first_word = command.strip().split()[0].lower() if command.strip() else ""
            if any(first_word.startswith(p) or f" {p}" in cmd_lower for p in ps_read_prefixes):
                return {"class": "read", "cacheable": False, "allowed": bool(cfg.get("allow_read", True)), "reason": "powershell read command"}

            return {"class": "unknown", "cacheable": False, "allowed": False, "reason": "unrecognized powershell command"}

        # Reject dangerous shell subshells in raw non-powershell commands
        unquoted = re.sub(r'("[^"]*"|\'[^\']*\')', '', command)
        if any(op in unquoted for op in ("`", "$(")):
            return {"class": "unknown", "cacheable": False, "allowed": False, "reason": "shell subshells are not accepted"}

        if exe_base == "git":
            unsafe_git_flags = {"--paginate", "--exec-path", "--config-env"}
            if any(flag in unsafe_git_flags or flag.startswith(("--exec-path=", "--config-env=", "--upload-pack=", "--receive-pack=")) for flag in lower):
                return {"class": "unknown", "cacheable": False, "allowed": False, "reason": "git flags may execute a pager or external program"}
            for idx, arg in enumerate(tokens[1:], 1):
                if arg == "-c" and idx < len(tokens) - 1:
                    config_pair = tokens[idx + 1].lower()
                    if any(config_pair.startswith(bad) for bad in ("core.pager", "pager.", "alias.", "core.fsmonitor", "core.sshcommand")):
                        return {"class": "unknown", "cacheable": False, "allowed": False, "reason": "git -c config may execute arbitrary commands"}

            skip_next = False
            sub = ""
            sub_idx = 0
            for idx, token in enumerate(tokens[1:], 1):
                if skip_next:
                    skip_next = False
                    continue
                if token in {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--no-optional-locks", "--no-pager"}:
                    if token in {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}:
                        skip_next = True
                    continue
                if token.startswith("-"):
                    continue
                sub = token.lower()
                sub_idx = idx
                break

            if not sub:
                return {"class": "read", "cacheable": True, "allowed": bool(cfg.get("allow_read", True)), "reason": "read-only git"}

            git_read_subs = {
                "status", "diff", "show", "log", "grep", "ls-files", "rev-parse",
                "branch", "tag", "describe", "blame", "remote", "cat-file", "check-ignore",
                "check-attr", "merge-base", "shortlog", "ls-tree", "var", "reflog",
                "version", "whatchanged", "for-each-ref", "show-ref", "rev-list", "diff-tree",
                "hash-object", "check-ref-format", "name-rev", "count-objects", "ls-remote",
                "verify-pack", "verify-commit", "verify-tag",
            }
            if sub in git_read_subs:
                return {"class": "read", "cacheable": True, "allowed": bool(cfg.get("allow_read", True)), "reason": f"read-only git {sub}"}

            if sub == "stash":
                stash_args = [t.lower() for t in tokens[sub_idx + 1:] if not t.startswith("-")]
                stash_sub = stash_args[0] if stash_args else "list"
                if stash_sub in {"list", "show"}:
                    return {"class": "read", "cacheable": True, "allowed": bool(cfg.get("allow_read", True)), "reason": f"read-only git stash {stash_sub}"}

            if sub == "worktree":
                wt_args = [t.lower() for t in tokens[sub_idx + 1:] if not t.startswith("-")]
                wt_sub = wt_args[0] if wt_args else "list"
                if wt_sub in {"list"}:
                    return {"class": "read", "cacheable": True, "allowed": bool(cfg.get("allow_read", True)), "reason": f"read-only git worktree {wt_sub}"}

            if sub == "config":
                config_args = [t.lower() for t in tokens[sub_idx + 1:]]
                read_flags = {"--get", "--get-all", "--get-regexp", "-l", "--list", "--show-origin", "--show-scope"}
                if any(rf in config_args for rf in read_flags):
                    return {"class": "read", "cacheable": True, "allowed": bool(cfg.get("allow_read", True)), "reason": "read-only git config"}

            return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": f"git {sub} may mutate"}

        if exe_base in self.READ_ONLY and exe_base != "git":
            if exe_base in {"rg", "ripgrep"} and any(flag == "--pre" or flag.startswith("--pre=") for flag in lower):
                return {"class": "unknown", "cacheable": False, "allowed": False, "reason": "ripgrep preprocessor may execute arbitrary programs"}
            if exe_base == "find" and any(flag in {"-exec", "-execdir", "-ok", "-okdir", "-delete"} for flag in lower):
                return {"class": "unknown", "cacheable": False, "allowed": False, "reason": "find execution flags are not allowed"}
            return {"class": "read", "cacheable": True, "allowed": bool(cfg.get("allow_read", True)), "reason": f"{exe_base} read command"}

        if exe_base in {"python", "python3", "py"}:
            dash_m = None
            for idx, arg in enumerate(tokens[1:], 1):
                if arg == "-m" and idx < len(tokens) - 1:
                    dash_m = tokens[idx + 1].lower()
                    break
            if dash_m is not None:
                validation_modules = {
                    "pytest", "ruff", "mypy", "unittest", "flake8", "compileall", "pyflakes",
                    "pylint", "bandit", "coverage", "tox", "nox", "pre_commit", "pre-commit",
                }
                if dash_m in validation_modules:
                    return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": f"python -m {dash_m} validation"}
                if dash_m in {"build", "wheel", "setuptools", "flit"}:
                    return {"class": "build", "cacheable": True, "allowed": bool(cfg.get("allow_build", True)), "reason": f"python -m {dash_m} packaging"}
                if dash_m in {"local_ai_hub", "local_ai_hub.generator"}:
                    return {"class": "build", "cacheable": True, "allowed": bool(cfg.get("allow_build", True)), "reason": f"python -m {dash_m} dynamic artifacts generator"}
                if dash_m == "pip":
                    pip_sub = [t.lower() for t in tokens[2:] if not t.startswith("-")]
                    pip_action = pip_sub[0] if pip_sub else ""
                    if pip_action in {"list", "show", "check"} or any(flag in lower for flag in {"--version", "-v"}):
                        return {"class": "read", "cacheable": True, "allowed": bool(cfg.get("allow_read", True)), "reason": f"python -m pip {pip_action or 'info'}"}
                    if pip_action in {"install", "uninstall", "download"}:
                        return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": f"python -m pip {pip_action} changes environment"}
                if dash_m in {"json.tool", "platform", "sysconfig", "site", "venv", "pydoc"}:
                    return {"class": "read", "cacheable": True, "allowed": bool(cfg.get("allow_read", True)), "reason": f"python -m {dash_m} inspection"}
                if dash_m in {"black", "isort"}:
                    if any(f in lower for f in {"--check", "--diff"}):
                        return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": f"python -m {dash_m} validation"}
                    return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": f"python -m {dash_m} format without --check"}

            dash_c = None
            for idx, arg in enumerate(tokens[1:], 1):
                if arg == "-c" and idx < len(tokens) - 1:
                    dash_c = tokens[idx + 1]
                    break
            if dash_c is not None:
                _DANGEROUS_INLINE = (
                    "os.system(", "os.popen(", "subprocess.", "exec(", "eval(", "__import__(",
                    "importlib.", "ctypes.", "shutil.rmtree", "shutil.move", "os.remove(",
                    "os.unlink(", "os.rmdir(", "socket.", "pty.",
                )
                dash_c_lower = dash_c.lower()
                if any(pat in dash_c_lower for pat in _DANGEROUS_INLINE):
                    return {"class": "unknown", "cacheable": False, "allowed": bool(cfg.get("allow_unknown", False)), "reason": "python -c inline code contains potentially dangerous call"}

                is_validation = False
                try:
                    tree = ast.parse(dash_c)
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Call):
                            func_name = ""
                            if isinstance(node.func, ast.Name):
                                func_name = node.func.id
                            elif isinstance(node.func, ast.Attribute):
                                func_name = node.func.attr
                            if func_name in {"exec", "eval", "compile"}:
                                return {"class": "unknown", "cacheable": False, "allowed": bool(cfg.get("allow_unknown", False)), "reason": f"python -c inline code contains dangerous call: {func_name}"}
                        elif isinstance(node, ast.Assert):
                            is_validation = True
                except SyntaxError:
                    return {"class": "unknown", "cacheable": False, "allowed": bool(cfg.get("allow_unknown", False)), "reason": "python -c inline code contains invalid syntax"}

                if not is_validation:
                    tokens_in_code = set(re.findall(r"\b\w+\b", dash_c_lower))
                    validation_keywords = {"test", "validate", "check", "audit", "doctor", "selftest", "report", "assert"}
                    if validation_keywords & tokens_in_code:
                        is_validation = True

                if is_validation:
                    return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": "python inline validation"}
                return {"class": "read", "cacheable": True, "allowed": bool(cfg.get("allow_read", True)), "reason": "python inline read"}

            non_flag_args = [t for t in tokens[1:] if not t.startswith("-")]
            if non_flag_args:
                script_name = Path(non_flag_args[0].replace("\\", "/")).name.lower()
                sub_args = [t.lower() for t in non_flag_args[1:]]
                if script_name in {"hubctl.py", "hubctl"}:
                    sub = sub_args[0] if sub_args else ""
                    if sub == "tasks":
                        is_mutating = any(t in lower for t in {"--complete", "--fail"})
                        if is_mutating:
                            return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": "hubctl tasks status mutation"}
                        return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": "hubctl tasks status check"}
                    if sub in {"status", "service-status", "agent-state", "dashboard", "watch", "memory", "doctor", "logs"}:
                        return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": f"hubctl {sub} status check"}
                    if sub == "generate":
                        return {"class": "build", "cacheable": True, "allowed": bool(cfg.get("allow_build", True)), "reason": "hubctl generate dynamic artifacts"}
                    if sub in {"start", "stop", "restart", "cleanup"}:
                        return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": f"hubctl {sub} service lifecycle mutation"}
                if script_name in {"setup.py", "setup"}:
                    if any(t in lower for t in {"--generate-only", "--help", "-h"}):
                        return {"class": "build", "cacheable": True, "allowed": bool(cfg.get("allow_build", True)), "reason": "setup.py generate dynamic artifacts"}
                if any(f in arg.lower() for arg in non_flag_args for f in ("test", "validate", "check", "flow", "status", "audit", "doctor", "selftest", "report", "bench", "benchmark", "inspect", "diagnose", "eval", "summary")):
                    return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": "python validation script"}
                if any(f in script_name for f in ("generate", "build", "compile", "bundle")):
                    return {"class": "build", "cacheable": True, "allowed": bool(cfg.get("allow_build", True)), "reason": "python build/generate script"}
                if not any(token.lower() in self.MUTATING_WORDS for token in non_flag_args[1:]):
                    return {"class": "read", "cacheable": False, "allowed": bool(cfg.get("allow_read", True)), "reason": "python read script"}

        if exe_base == "hubctl":
            sub = lower[0] if lower else ""
            if sub == "tasks":
                is_mutating = any(t in lower for t in {"--complete", "--fail"})
                if is_mutating:
                    return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": "hubctl tasks status mutation"}
                return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": "hubctl tasks status check"}
            if sub in {"status", "service-status", "agent-state", "dashboard", "watch", "memory", "doctor", "logs"}:
                return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": f"hubctl {sub} status check"}
            if sub == "generate":
                return {"class": "build", "cacheable": True, "allowed": bool(cfg.get("allow_build", True)), "reason": "hubctl generate dynamic artifacts"}
            if sub in {"start", "stop", "restart", "cleanup"}:
                return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": f"hubctl {sub} service lifecycle mutation"}

        if exe_base == "php" and lower:
            php_target = ntpath.basename(lower[0].replace("/", "\\"))
            if any(name in php_target for name in ("phpunit", "phpstan", "pest")):
                return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": "PHP validation tool"}

        if exe_base in {"black", "isort"}:
            if any(f in lower for f in {"--check", "--diff"}):
                return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": f"{exe_base} check"}
            return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": f"{exe_base} format without --check"}

        if exe_base in self.PURE_VALIDATORS or any(name in exe_base for name in ("phpunit", "phpstan", "pytest", "pest", "flake8", "pylint", "shellcheck", "yamllint")):
            return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": f"{exe_base} validation tool"}

        positional_verbs = [t.lower() for t in tokens[1:] if not t.startswith(("-", "/"))]
        primary_verb = positional_verbs[0] if positional_verbs else ""

        if exe_base == "dotnet":
            flag_info = {"--info", "--version", "--list-sdks", "--list-runtimes", "--help", "-h", "-v"}
            if any(f in lower for f in flag_info) and not any(v in lower for v in ("build", "test", "run", "clean", "publish")):
                return {"class": "read", "cacheable": True, "allowed": bool(cfg.get("allow_read", True)), "reason": "read-only dotnet inspection"}
            if primary_verb in {"test", "vstest"}:
                return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": "dotnet test"}
            if primary_verb in {"build", "compile", "pack", "restore", "clean", "run", "msbuild"}:
                return {"class": "build", "cacheable": True, "allowed": bool(cfg.get("allow_build", True)), "reason": f"dotnet {primary_verb}"}
            if primary_verb == "format":
                if any(f in lower for f in {"--verify-no-changes", "--check"}):
                    return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": "dotnet format check"}
                return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": "dotnet format changes source without --verify-no-changes"}

        package_tools = {"npm", "pnpm", "yarn", "bun"}
        if exe_base in package_tools:
            mutating = {"install", "i", "add", "remove", "rm", "uninstall", "update", "upgrade", "publish", "link", "unlink", "pack", "version"}
            if primary_verb in mutating:
                return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": f"{exe_base} {primary_verb} changes dependencies or publishes artifacts"}
            script = ""
            if primary_verb in {"run", "run-script"} and len(positional_verbs) > 1:
                script = positional_verbs[1]
            elif primary_verb:
                script = primary_verb
            safe_validation = {"test", "lint", "check", "typecheck", "type-check", "analyse", "analyze", "audit"}
            safe_build = {"build", "compile"}
            if script in safe_validation:
                return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": f"{exe_base} safe validation script"}
            if script in safe_build:
                return {"class": "build", "cacheable": True, "allowed": bool(cfg.get("allow_build", True)), "reason": f"{exe_base} safe build script"}
            return {"class": "unknown", "cacheable": False, "allowed": bool(cfg.get("allow_unknown", False)), "reason": f"{exe_base} script is not in the safe validation/build allowlist"}

        if exe_base == "composer":
            if primary_verb in {"install", "update", "upgrade", "remove", "require", "create-project", "dump-autoload", "global"}:
                return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": f"composer {primary_verb} may change dependencies or generated files"}
            if primary_verb in {"validate", "audit", "test", "phpunit", "phpstan", "analyse", "analyze", "check"}:
                return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": "composer validation command"}
            return {"class": "unknown", "cacheable": False, "allowed": bool(cfg.get("allow_unknown", False)), "reason": "composer command is not in the safe validation allowlist"}

        if exe_base == "make":
            if any(v in {"clean", "install", "uninstall", "deploy", "publish", "release"} for v in positional_verbs):
                return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": "make target may mutate or deploy"}
            safe_validation = {"test", "tests", "check", "lint", "validate", "verify", "typecheck"}
            safe_build = {"build", "compile", "all"}
            if positional_verbs and all(v in safe_validation for v in positional_verbs):
                return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": "make validation target"}
            if positional_verbs and all(v in safe_build for v in positional_verbs):
                return {"class": "build", "cacheable": True, "allowed": bool(cfg.get("allow_build", True)), "reason": "make build target"}
            return {"class": "unknown", "cacheable": False, "allowed": bool(cfg.get("allow_unknown", False)), "reason": "make target is not in the safe validation/build allowlist"}

        if exe_base == "cargo":
            if primary_verb in {"fmt"} and "--check" not in lower:
                return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": "cargo fmt changes source without --check"}
            if primary_verb in {"test", "check", "clippy", "bench"} or (primary_verb == "fmt" and "--check" in lower):
                return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": "cargo validation command"}
            if primary_verb == "build":
                return {"class": "build", "cacheable": True, "allowed": bool(cfg.get("allow_build", True)), "reason": "cargo build"}
            return {"class": "unknown", "cacheable": False, "allowed": bool(cfg.get("allow_unknown", False)), "reason": "cargo command is not in the safe validation/build allowlist"}

        if exe_base in {"go", "mvn", "mvnw", "gradle", "gradlew", "gradlew.bat", "cmake", "ctest"}:
            if any(v in self.MUTATING_WORDS or v in {"tidy", "publish", "deploy", "release"} for v in positional_verbs):
                return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": f"{exe_base} command may mutate project or publish artifacts"}
            validation_words = {"test", "tests", "check", "verify", "lint", "vet", "clippy", "ctest"}
            build_words = {"build", "compile", "package", "assemble"}
            if exe_base == "ctest" or any(v in validation_words for v in positional_verbs):
                return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": f"{exe_base} validation command"}
            if exe_base == "cmake" or any(v in build_words for v in positional_verbs):
                return {"class": "build", "cacheable": True, "allowed": bool(cfg.get("allow_build", True)), "reason": f"{exe_base} build command"}
            return {"class": "unknown", "cacheable": False, "allowed": bool(cfg.get("allow_unknown", False)), "reason": f"{exe_base} command is not in the safe validation/build allowlist"}

        if exe_base in self.VALIDATORS:
            if primary_verb in self.MUTATING_WORDS:
                return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": f"mutating verb {primary_verb}"}
            if any(x in positional_verbs for x in ("build", "compile")):
                return {"class": "build", "cacheable": True, "allowed": bool(cfg.get("allow_build", True)), "reason": "build command"}
            return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": "validation/test command"}

        return {"class": "unknown", "cacheable": False, "allowed": bool(cfg.get("allow_unknown", False)), "reason": "command not in safe broker allowlist"}

    @staticmethod
    def _safe_label(command: str) -> str:
        # Local dashboard metadata only; redact common credential-bearing options.
        text = re.sub(r"(?i)(--?(?:password|token|secret|api[-_]?key)\s*[= ]\s*)([^\s]+)", r"\1***", command.strip())
        text = re.sub(r"(?i)(Bearer\s+)[A-Za-z0-9._~+/-]+", r"\1***", text)
        return text[:240]

    @classmethod
    def _needs_shell(cls, command: str) -> bool:
        trimmed = command.strip()
        if cls._is_powershell_command(trimmed):
            return True
        seq = cls._split_outside_quotes(trimmed, (";", "&&", "||", "|", ">", "<"))
        if len(seq) > 1:
            return True
        if any(op in trimmed for op in ("2>&1", "| Out-Null", "| out-null", ">nul", "> nul")):
            return True
        return False

    def _tool_identity(self, command: str, cwd: str) -> dict[str, Any]:
        if self._needs_shell(command):
            raw = (shutil.which("pwsh") or shutil.which("powershell") or "powershell") if os.name == "nt" else (shutil.which("sh") or "/bin/sh")
            candidate = Path(raw)
            try:
                stat = candidate.stat()
                return {"path": str(candidate.resolve()), "mtime_ns": int(stat.st_mtime_ns), "size": int(stat.st_size)}
            except Exception:
                return {"path": str(candidate)}
        tokens = self._tokens(command)
        if not tokens:
            return {}
        raw = tokens[0].strip('"')
        candidate = Path(raw)
        if not candidate.is_absolute():
            local = (Path(cwd) / candidate).resolve(strict=False)
            resolved = local if local.exists() else Path(shutil.which(raw) or raw)
        else:
            resolved = candidate
        try:
            stat = resolved.stat()
            return {"path": str(resolved.resolve()), "mtime_ns": int(stat.st_mtime_ns), "size": int(stat.st_size)}
        except Exception:
            return {"path": str(resolved)}

    def _key(self, command: str, cwd: str, classification: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        state = self.repo_state.fingerprint(cwd)
        env_keys = self.config.get("commands", {}).get("environment_keys", ["CI", "NODE_ENV", "APP_ENV", "PYTHONPATH"])
        env = {str(k): os.environ.get(str(k), "") for k in env_keys}
        key = stable_hash({
            "command": command.strip(), "cwd": str(Path(cwd).resolve()), "class": classification.get("class"),
            "repo": state.get("fingerprint"), "env": env, "python": sys.version_info[:3], "tool": self._tool_identity(command, cwd),
        })
        return key, state

    def _attempt_key(self, command: str, cwd: str) -> str:
        tokens = self._tokens(command)
        cmd_str = " ".join(tokens) if tokens else command.strip()
        return stable_hash({
            "command": cmd_str,
            "cwd": str(Path(cwd).resolve()),
            "tool": self._tool_identity(command, cwd),
        })

    def _unavailable_executable(self, command: str, cwd: str) -> str | None:
        if self._needs_shell(command):
            if os.name == "nt":
                return None if (shutil.which("pwsh") or shutil.which("powershell")) else "powershell"
            return None if (shutil.which("sh") or Path("/bin/sh").exists()) else "sh"
        tokens = self._tokens(command)
        if not tokens:
            return None
        raw = tokens[0].strip('"')
        if os.name == "nt" and raw.lower() in {"ver", "set"}:
            return None if shutil.which("cmd") else "cmd"
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = Path(cwd) / candidate
        has_path = any(marker in raw for marker in ("/", "\\"))
        if has_path:
            return None if candidate.exists() else raw
        return None if shutil.which(raw) else raw

    @staticmethod
    def _non_retryable_failure(result: dict[str, Any]) -> bool:
        if result.get("success") or result.get("timed_out"):
            return False
        text = (str(result.get("error", "")) + "\n" + str(result.get("stderr", ""))).lower()
        return int(result.get("exit_code", 0) or 0) == 127 or any(marker in text for marker in (
            "failed to spawn process", "command not found", "is not recognized as an internal", "no such file or directory",
        ))

    _INTERACTIVE_PATTERNS = [
        re.compile(r"\[y/n\]", re.I),
        re.compile(r"\(y/n\)", re.I),
        re.compile(r"password\s*:", re.I),
        re.compile(r"enter\s+(?:passphrase|password|pin|key|choice)", re.I),
        re.compile(r"press\s+(?:any\s+key|enter)\s+to\s+continue", re.I),
        re.compile(r"do\s+you\s+want\s+to\s+continue\s*\?", re.I),
        re.compile(r"are\s+you\s+sure\s*\?", re.I),
    ]

    @classmethod
    def _is_interactive_prompt(cls, text: str) -> bool:
        if not text:
            return False
        return any(p.search(text) for p in cls._INTERACTIVE_PATTERNS)

    def _execute(
        self,
        command: str,
        cwd: str,
        timeout: int,
        cancel_event: threading.Event | None = None,
        log_callback: Any | None = None,
    ) -> dict[str, Any]:
        tokens = self._tokens(command)
        started = time.perf_counter()
        if self._needs_shell(command):
            if os.name == "nt":
                shell_bin = shutil.which("pwsh") or shutil.which("powershell") or "powershell.exe"
                argv = [shell_bin, "-NoProfile", "-NonInteractive", "-Command", command]
            else:
                if self._is_powershell_command(command) and shutil.which("pwsh"):
                    argv = [shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-Command", command]
                else:
                    argv = ["/bin/sh", "-c", command]
        elif os.name == "nt":
            raw0 = tokens[0].strip('"') if tokens else ""
            if raw0.lower() in {"ver", "set"}:
                comspec = os.environ.get("COMSPEC", "cmd.exe")
                argv = [comspec, "/d", "/c", command]
            else:
                suffix = Path(raw0).suffix.lower()
                resolved = shutil.which(raw0) or shutil.which(raw0, path=cwd)
                if (resolved and Path(resolved).suffix.lower() in {".bat", ".cmd"}) or suffix in {".bat", ".cmd"}:
                    comspec = os.environ.get("COMSPEC", "cmd.exe")
                    argv = [comspec, "/d", "/c"] + tokens
                else:
                    argv = tokens
        else:
            argv = tokens
        proc_env = os.environ.copy()
        proc_env["PYTHONDONTWRITEBYTECODE"] = "1"
        proc_env["PYTHONIOENCODING"] = "utf-8"
        kwargs: dict[str, Any] = {
            "cwd": str(Path(cwd).resolve()), "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE, "stderr": subprocess.PIPE,
            "text": True, "encoding": "utf-8", "errors": "replace",
            "env": proc_env,
        }
        if os.name == "nt":
            kwargs.update(hidden_run_kwargs(new_group=True))
        else:
            kwargs["start_new_session"] = True
        try:
            process = subprocess.Popen(argv, **kwargs)
            if os.name == "nt" and _GLOBAL_WINDOWS_JOB is not None:
                try:
                    assign_process_to_job(_GLOBAL_WINDOWS_JOB, process.pid)
                except Exception:
                    pass
        except OSError as exc:
            return {
                "success": False, "exit_code": 127, "timed_out": False,
                "stdout": "", "stderr": str(exc), "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                "error": f"failed to spawn process: {exc}",
            }

        out_buf = _BoundedStreamBuffer(self.max_output_chars)
        err_buf = _BoundedStreamBuffer(self.max_output_chars)

        def _reader(stream: Any, buf: _BoundedStreamBuffer, stream_name: str) -> None:
            last_callback_time = 0.0
            callback_min_interval = 0.005  # Max ~200 callbacks/sec to prevent downstream lock/choking
            pending_batch: list[str] = []
            try:
                for line in iter(lambda: stream.readline(65536), ""):
                    if not line:
                        break
                    buf.append(line)
                    if log_callback:
                        now = time.monotonic()
                        if now - last_callback_time >= callback_min_interval:
                            if pending_batch:
                                text = "".join(pending_batch) + line
                                pending_batch.clear()
                            else:
                                text = line
                            last_callback_time = now
                            try:
                                log_callback(stream_name, text)
                            except Exception:
                                pass
                        else:
                            pending_batch.append(line)
                            if len(pending_batch) >= 50:
                                text = "".join(pending_batch)
                                pending_batch.clear()
                                last_callback_time = now
                                try:
                                    log_callback(stream_name, text)
                                except Exception:
                                    pass
                if log_callback and pending_batch:
                    try:
                        log_callback(stream_name, "".join(pending_batch))
                    except Exception:
                        pass
            except Exception:
                pass
            finally:
                try:
                    stream.close()
                except Exception:
                    pass

        t_out = threading.Thread(target=_reader, args=(process.stdout, out_buf, "stdout"), daemon=True)
        t_err = threading.Thread(target=_reader, args=(process.stderr, err_buf, "stderr"), daemon=True)
        t_out.start()
        t_err.start()

        timed_out = False
        cancelled = False
        aborted_interactive = False
        deadline = time.monotonic() + max(1, timeout)
        while process.poll() is None:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                break
            if time.monotonic() > deadline:
                timed_out = True
                break
            peek_out = out_buf.peek(500)
            peek_err = err_buf.peek(500)
            if self._is_interactive_prompt(peek_out) or self._is_interactive_prompt(peek_err):
                aborted_interactive = True
                break
            time.sleep(0.02)

        if timed_out or cancelled or aborted_interactive:
            try:
                terminate_tree(process.pid, grace_seconds=self.terminate_grace_seconds)
            except Exception:
                pass
            try:
                process.kill()
            except Exception:
                pass
            try:
                process.wait(timeout=max(2.0, self.terminate_grace_seconds))
            except Exception:
                pass
            if process.poll() is None:
                try:
                    process.kill()
                    process.wait(timeout=1.0)
                except Exception:
                    pass

        # A successful child can exit before the reader/callback threads finish
        # publishing their last SSE/event chunks.  Keep the drain bounded, but
        # give callback delivery a small scheduler-load margin so callers never
        # observe a successful command before its final stream evidence exists.
        drain_seconds = max(self.post_kill_drain_seconds, 5.0)
        drain_deadline = time.monotonic() + drain_seconds
        t_out.join(timeout=max(0.0, drain_deadline - time.monotonic()))
        t_err.join(timeout=max(0.0, drain_deadline - time.monotonic()))
        try:
            if process.stdout and not process.stdout.closed:
                process.stdout.close()
        except Exception:
            pass
        try:
            if process.stderr and not process.stderr.closed:
                process.stderr.close()
        except Exception:
            pass
        try:
            process.wait(timeout=1.0)
        except Exception:
            pass

        stdout = out_buf.getvalue()
        stderr = err_buf.getvalue()
        self.executed += 1
        return {
            "success": (not timed_out) and (not cancelled) and (not aborted_interactive) and process.returncode == 0,
            "exit_code": -9 if (timed_out or cancelled or aborted_interactive) else int(process.returncode or 0),
            "timed_out": timed_out, "cancelled": cancelled, "aborted_interactive": aborted_interactive,
            "stdout": stdout, "stderr": stderr,
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            **({"error": "interactive_prompt_detected: command aborted because it requested interactive input"} if aborted_interactive else {"error": "command cancelled"} if cancelled else {"error": f"command timed out after {timeout}s"} if timed_out else {}),
        }

    @staticmethod
    def _cancel_key(command: str, cwd: str) -> str:
        return stable_hash({"command": command.strip(), "cwd": str(Path(cwd).resolve())})

    @staticmethod
    def _tenant_identity(tenant: str) -> str:
        """Return collision-resistant tenant identity without retaining its raw value."""
        return stable_hash({"tenant": str(tenant)})

    @staticmethod
    def _public_active(active: dict[str, Any]) -> dict[str, Any]:
        """Expose bounded active-command metadata without tenant identity or raw tenant."""
        return {key: value for key, value in active.items() if key not in {"tenant", "tenant_identity"}}

    def cancel(self, command: str, cwd: str, tenant: str, *, execution_id: str = "") -> dict[str, Any]:
        """Request bounded cancellation of one currently running broker command."""
        lookup = self._cancel_key(command, cwd)
        tenant_key = self._tenant_identity(tenant)
        with self._lock:
            if execution_id:
                matches = [
                    item for item, active in self._active_commands.items()
                    if active.get("execution_id") == execution_id and active.get("tenant_identity") == tenant_key
                ]
            else:
                matches = [item for item, value in self._active_cancel_keys.items() if value == (lookup, tenant_key)]
            if len(matches) > 1:
                return {
                    "success": False, "terminal": True, "retryable": False,
                    "error": "multiple matching active commands; provide execution_id",
                    "execution_ids": [str(self._active_commands[item].get("execution_id", "")) for item in matches],
                }
            key = matches[0] if matches else ""
            event = self._cancel_events.get(key) if key else None
            active = self._public_active(dict(self._active_commands.get(key, {}))) if key else {}
            if event is None:
                return {"success": False, "terminal": True, "retryable": False, "error": "no matching active command"}
            event.set()
            self.cancelled += 1
        return {"success": True, "cancellation_requested": True, "execution_id": active.get("execution_id", ""), "active": active}

    @staticmethod
    def _extract_diagnostics(result: dict[str, Any], limit: int = 30) -> list[dict[str, Any]]:
        # stdout/stderr are captured independently, so their true interleaving is
        # unavailable. Preserve each stream's order while preferring explicit
        # failures over informational diagnostics and warnings from a failed run.
        # This keeps an early stdout warning from masking the useful stderr error.
        streams = (str(result.get("stdout", "")), str(result.get("stderr", "")))
        failures: list[dict[str, Any]] = []
        others: list[dict[str, Any]] = []
        patterns = _DIAGNOSTIC_PATTERNS
        failure_terms = ("error", "fatal", "exception", "traceback", "assertionerror", "panic", "failed", "failure")
        for text in streams:
            for raw in text.splitlines():
                line = raw.strip()
                if not line:
                    continue
                matched = None
                matched_failure = False
                for pattern_index, pattern in enumerate(patterns):
                    m = pattern.match(line)
                    if m:
                        matched = m
                        # The dedicated pytest `FAILED path::test` pattern keeps
                        # the path but strips the word FAILED from its message.
                        # Preserve its failure semantics from the original line.
                        matched_failure = pattern_index == 1
                        break
                message = ""
                diagnostic: dict[str, Any] | None = None
                if matched:
                    data = matched.groupdict()
                    message = str(data.get("msg") or line)[:500]
                    diagnostic = {
                        "path": data.get("path", ""),
                        "line": int(data.get("line") or 0),
                        "column": int(data.get("col") or 0),
                        "message": message,
                    }
                elif any(term in line.lower() for term in failure_terms):
                    message = line[:500]
                    diagnostic = {"path": "", "line": 0, "column": 0, "message": message}
                if diagnostic is None:
                    continue
                target = failures if (
                    matched_failure
                    or any(term in line.lower() for term in failure_terms)
                ) else others
                if len(target) < limit:
                    target.append(diagnostic)
        return (failures + others)[:limit]

    @classmethod
    def _first_failure_summary(cls, result: dict[str, Any]) -> dict[str, Any]:
        """Return first deterministic failure location without replaying verbose logs."""
        diagnostics = list(result.get("diagnostics") or cls._extract_diagnostics(result, limit=1))
        if diagnostics:
            first = diagnostics[0]
            return {
                "path": str(first.get("path") or ""),
                "line": int(first.get("line") or 0),
                "message": str(first.get("message") or "").strip()[:500],
            }
        return {
            "path": "",
            "line": 0,
            "message": cls._distill_error(result)[:500],
        }

    @staticmethod
    def _failure_preview(summary: dict[str, Any]) -> str:
        """Expose only the narrow first-failure slice in command results."""
        path = str(summary.get("path") or "")
        line = int(summary.get("line") or 0)
        message = str(summary.get("message") or "").strip()
        if path and line:
            return f"{path}:{line}: {message}"[:800]
        if path:
            return f"{path}: {message}"[:800]
        return message[:800]

    @staticmethod
    def _deterministic_summary(result: dict[str, Any], limit: int = 60) -> str:
        text = (str(result.get("stdout", "")) + "\n" + str(result.get("stderr", ""))).strip()
        lines = text.splitlines()
        if len(lines) <= limit:
            return text
        needles = ("error", "fail", "fatal", "warning", "assert", "exception", "traceback", "passed", "failed", "success", "tests", "errors")
        selected = [line for line in lines if any(n in line.lower() for n in needles)]
        # Keep final framework summary because pytest/phpunit/cargo/go normally report counts there.
        tail = lines[-min(12, len(lines)):]
        for line in tail:
            if line not in selected:
                selected.append(line)
        if len(selected) < limit // 2:
            selected = lines[: max(8, limit // 5)] + selected
        return "\n".join(selected[:limit])

    @staticmethod
    def _distill_error(result: dict[str, Any]) -> str:
        """Extract a high-density, concise 1-3 line failure cause from command output."""
        if result.get("success"):
            return ""
        diagnostics = result.get("diagnostics", [])
        if diagnostics:
            parts = []
            for d in diagnostics[:2]:
                path = d.get("path")
                line = d.get("line")
                msg = str(d.get("message") or "").strip()
                if path and line:
                    parts.append(f"{path}:{line}: {msg}")
                elif msg:
                    parts.append(msg)
            if parts:
                return "\n".join(parts)[:300]
        text = (str(result.get("stderr", "")) + "\n" + str(result.get("stdout", ""))).strip()
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if lines:
            for ln in reversed(lines):
                if any(k in ln.lower() for k in ("error", "failed", "exception", "fatal", "traceback")):
                    return ln[:240]
            return lines[-1][:240]
        return f"Command failed with exit code {result.get('exit_code', 1)}"

    @staticmethod
    def _needs_model_error_distillation(result: dict[str, Any]) -> bool:
        if result.get("diagnostics"):
            return False
        text = (str(result.get("stderr", "")) + "\n" + str(result.get("stdout", ""))).strip()
        return bool(text)

    def _distill_error_with_model(self, result: dict[str, Any]) -> str:
        if not callable(self.error_distiller):
            return ""
        payload = {
            "exit_code": int(result.get("exit_code", 1) or 1),
            "summary": str(result.get("summary", ""))[:4000],
            "diagnostics": list(result.get("diagnostics", []))[:2],
        }
        try:
            distilled = self.error_distiller(payload)
        except Exception:
            return ""
        if isinstance(distilled, dict):
            distilled = distilled.get("text", distilled.get("summary", ""))
        return str(distilled or "").strip()[:300]

    def run(
        self,
        command: str,
        cwd: str,
        tenant: str = "agent",
        *,
        timeout: int | None = None,
        force: bool = False,
        task_id: str = "",
        criterion: str = "",
        auto_fix: bool = False,
        fix_generator: Any | None = None,
        max_repair_attempts: int = 3,
        log_callback: Any | None = None,
        snapshot: bool = False,
        rollback_on_failure: bool = False,
        sandbox: str = "local",
        docker_image: str = "python:3.11-slim",
        bypass_cache: bool = False,
        rollback_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {"success": False, "error": "command broker disabled"}
        if rollback_on_failure and auto_fix:
            return {"success": False, "error": "rollback_on_failure is supported only for direct run actions", "rollback_unsupported_action": True, "terminal": True, "retryable": False}
        rollback_state: RollbackSnapshot | None = None
        if rollback_on_failure:
            rollback_state, scope_error = _snapshot_rollback_scope(cwd, rollback_paths)
            if scope_error:
                key = "rollback_scope_required" if scope_error == "rollback paths are required" else "rollback_scope_invalid"
                return {
                    "success": False,
                    "error": scope_error,
                    key: True,
                    "terminal": True,
                    "retryable": False,
                }
        original_command = command
        classification = self.classify(original_command)
        is_mutating = classification.get("class") == "mutating"
        if sandbox == "docker":
            if not shutil.which("docker"):
                return {
                    "success": False,
                    "error": "docker executable not found for sandbox mode",
                    "terminal": True,
                    "retryable": False,
                }
            abs_cwd = str(Path(cwd).resolve())
            command = f'docker run --rm -v "{abs_cwd}:/workspace" -w /workspace {docker_image} {command}'
        if task_id and self.policy_engine:
            budget = self.policy_engine.get_budget(task_id)
            if budget.is_exhausted():
                return {
                    "success": False,
                    "error": f"task budget exhausted ({task_id}): max_tokens={budget.max_tokens}, max_compute_seconds={budget.max_compute_seconds}",
                    "terminal": True,
                    "retryable": False,
                    "budget_exhausted": True,
                }
        attempt_key = self._attempt_key(command, cwd)
        if not force and not bypass_cache and not is_mutating:
            suppressed = self.suppression_cache.get(attempt_key)
            if isinstance(suppressed, dict):
                self.suppressed += 1
                result = dict(suppressed)
                result.update({"suppression_cache_hit": True, "classification": classification})
                return self._compact(result, tenant, command)
        is_dangerous = classification.get("class") == "dangerous"
        if is_dangerous or (not classification["allowed"] and self.policy_blocking):
            with self._lock:
                self.blocked += 1
                reason = str(classification.get("reason", "policy"))[:120]
                self._blocked_by_reason[reason] = self._blocked_by_reason.get(reason, 0) + 1
            result = {
                "success": False, "error": f"command blocked: {classification['reason']}",
                "classification": classification, "policy_blocked": True, "terminal": True, "retryable": False,
            }
            if not force and not is_mutating:
                self.suppression_cache.set(attempt_key, result)
            return result
        cwd_path = Path(cwd).expanduser().resolve(strict=False)
        if not cwd_path.is_dir():
            result = {
                "success": False,
                "error": f"working directory does not exist: {cwd_path}",
                "preflight": True,
                "terminal": True,
                "retryable": False,
            }
            if not force and not is_mutating:
                self.suppression_cache.set(attempt_key, result)
            return result
        unavailable = self._unavailable_executable(command, cwd)
        if unavailable:
            result = {
                "success": False, "error": f"command executable is unavailable: {unavailable}",
                "exit_code": 127, "classification": classification, "preflight": True, "terminal": True, "retryable": False,
            }
            if not force and not is_mutating:
                self.suppression_cache.set(attempt_key, result)
            return self._compact(result, tenant, command)
        if not Path(cwd).is_dir():
            result = {
                "success": False, "error": f"working directory does not exist: {cwd}",
                "exit_code": 1, "classification": classification, "preflight": True, "terminal": True, "retryable": False,
            }
            if not force and not is_mutating:
                self.suppression_cache.set(attempt_key, result)
            return self._compact(result, tenant, command)
        try:
            key, state = self._key(command, cwd, classification)
        except ValueError as exc:
            result = {
                "success": False,
                "error": str(exc),
                "classification": classification,
                "preflight": True,
                "terminal": True,
                "retryable": False,
            }
            if not force and not is_mutating:
                self.suppression_cache.set(attempt_key, result)
            return self._compact(result, tenant, command)
        cacheable = bool(classification["cacheable"]) and not is_mutating
        if cacheable and not force:
            cached = self.success_cache.get(key) or self.failure_cache.get(key)
            if isinstance(cached, dict):
                self.hits += 1
                result = dict(cached)
                result.update({"cache_hit": True, "coalesced": False, "classification": classification, "repo_state": state, "repository_revision": str(state.get("fingerprint", ""))})
                self._record_command_verification(
                    result,
                    tenant=tenant,
                    task_id=task_id,
                    criterion=criterion or f"command:{self._safe_label(command)}",
                    command_id=f"cache_{uuid.uuid4().hex}",
                    command_digest=hashlib.sha256(command.encode("utf-8")).hexdigest(),
                    repository_revision=str(state.get("fingerprint", "")),
                    duration_ms=float(result.get("duration_ms", 0) or 0),
                    cached=True,
                )
                return self._compact(result, tenant, command)

        singleflight = not is_mutating and not bypass_cache
        event: threading.Event | None = None
        if singleflight:
            with self._lock:
                event = self._inflight.get(key)
                if event is None:
                    event = threading.Event(); self._inflight[key] = event; owner = True
                else:
                    owner = False; self.coalesced += 1
        if singleflight and not owner:
            # A second agent should benefit from single-flight without being trapped
            # behind a very long build/test command. The owner keeps running and will
            # populate the cache; the waiter gets a bounded in-progress response.
            wait_budget = min(max(1.0, float(timeout or self.timeout) + 5.0), self.coalesce_wait_seconds)
            if not event.wait(wait_budget):
                with self._lock:
                    self.coalesced_timeouts += 1
                    active = self._public_active(dict(self._active_commands.get(key, {})))
                return {
                    "success": False, "in_progress": True, "retryable": True,
                    "error": "identical command is still running in another agent; do not start a duplicate",
                    "classification": classification, "repo_state": state, "active": active,
                }
            with self._lock:
                result = dict(self._last.get(key, {"success": False, "error": "coalesced command failed"}))
            result.update({"cache_hit": True, "coalesced": True, "classification": classification, "repo_state": state, "repository_revision": str(state.get("fingerprint", ""))})
            return self._compact(result, tenant, command)

        self.misses += 1
        started_wall = time.time()
        cancel_event = threading.Event()
        execution_id = uuid.uuid4().hex
        execution_key = key if singleflight else f"mutation:{execution_id}"
        tenant_identity = self._tenant_identity(tenant)
        with self._lock:
            self._active_commands[execution_key] = {
                "command": self._safe_label(command), "cwd": Path(cwd).name or str(Path(cwd)),
                "class": str(classification.get("class", "")),
                "tenant_identity": tenant_identity, "started_at": started_wall,
                "timeout_seconds": int(timeout or self.timeout), "execution_id": execution_id,
            }
            self._cancel_events[execution_key] = cancel_event
            self._active_cancel_keys[execution_key] = (self._cancel_key(command, cwd), tenant_identity)
        git_snapshot = None
        if snapshot:
            try:
                cp_rev = subprocess.run(
                    ["git", "rev-parse", "--is-inside-work-tree"],
                    cwd=cwd, capture_output=True, text=True, check=False,
                    timeout=self.git_snapshot_timeout, **hidden_run_kwargs()
                )
                if cp_rev.returncode == 0:
                    cp_untracked = subprocess.run(
                        ["git", "ls-files", "--others", "--exclude-standard"],
                        cwd=cwd, capture_output=True, text=True, check=False,
                        timeout=self.git_snapshot_timeout, **hidden_run_kwargs()
                    )
                    git_snapshot = {
                        "cwd": cwd,
                        "untracked": set(cp_untracked.stdout.splitlines()),
                    }
            except Exception:
                pass
        try:
            result = self._execute(command, cwd, int(timeout or self.timeout), cancel_event, log_callback=log_callback)
            # CPython compileall reports missing targets as a diagnostic while
            # still exiting 0. A green exit code must not hide that no target
            # was compiled.
            combined_output = f"{result.get('stdout', '')}\n{result.get('stderr', '')}"
            if result.get("success") and "compileall" in command.lower() and re.search(r"can't\s+list\s+['\"]?[^\r\n]+", combined_output, re.I):
                result.update({
                    "success": False,
                    "exit_code": 1,
                    "error": "compileall reported an unavailable target",
                    "terminal": True,
                    "retryable": False,
                    "target_missing": True,
                })
            if rollback_state is not None and rollback_on_failure and not result.get("success"):
                try:
                    _restore_rollback_scope(cwd, rollback_state)
                    result["rolled_back"] = True
                except Exception as rb_exc:
                    result["rollback_error"] = str(rb_exc)[:512]
                    result["rolled_back"] = False
            elif snapshot and git_snapshot:
                result["snapshot_taken"] = True
            result["diagnostics"] = self._extract_diagnostics(result)
            if not result.get("success") and not result.get("cancelled"):
                result["error_distillation"] = self._distill_error(result)
                result["error_distillation_source"] = "deterministic"
                if self._needs_model_error_distillation(result):
                    model_distillation = self._distill_error_with_model(result)
                    if model_distillation:
                        result["error_distillation"] = model_distillation
                        result["error_distillation_source"] = "local_model"
            diag_paths = [d["path"] for d in result.get("diagnostics", []) if d.get("path")]
            if not result.get("success") and not result.get("cancelled") and self.incident_store is not None:
                try:
                    from .agent_incidents import ToolOutcome
                    inc = self.incident_store.capture(ToolOutcome(
                        tool_name="command",
                        command=command,
                        error=str(result.get("error") or result.get("stderr") or ("exit code " + str(result.get("exit_code", 1)))),
                        exit_code=int(result.get("exit_code", 1)),
                        state_revision=str(state.get("fingerprint", "")),
                        timed_out=bool(result.get("timed_out")),
                        cancelled=bool(result.get("cancelled")),
                        affected_paths=tuple(set(diag_paths)),
                    ))
                    if inc and (inc.root_cause or inc.verified_fix):
                        result["remediation"] = {
                            "incident_id": inc.incident_id,
                            "root_cause": inc.root_cause,
                            "verified_fix": inc.verified_fix,
                            "confidence": inc.confidence,
                            "attempts": inc.attempts,
                        }
                except Exception:
                    pass

            if self.incident_store is not None:
                try:
                    target_paths = set(diag_paths)
                    for cp in state.get("changed_paths", []):
                        target_paths.add(str(cp))
                    # Historical incidents are actionable only when the current
                    # command failed; successful runs must not emit stale alarms.
                    if target_paths and not result.get("success") and not result.get("cancelled"):
                        regs = self.incident_store.find_regressions(
                            list(target_paths),
                            state_revision=str(state.get("fingerprint") or ""),
                        )
                        if regs:
                            result["regression_warnings"] = regs
                    search_query = command
                    if not result.get("success") and result.get("error_distillation"):
                        search_query = f"{command} {result['error_distillation']}"
                    pitfalls = self.incident_store.find_negative_knowledge(query=search_query, limit=3)
                    if pitfalls:
                        result["known_pitfalls"] = [
                            {"incident_id": p.get("incident_id"), "root_cause": p.get("root_cause"), "verified_fix": p.get("verified_fix")}
                            for p in pitfalls if p.get("root_cause") or p.get("verified_fix")
                        ]
                except Exception:
                    pass

            raw = dict(result)
            if cacheable and not result.get("cancelled") and not result.get("timed_out"):
                (self.success_cache if result.get("success") else self.failure_cache).set(key, raw)
            self._record_command_verification(
                result,
                tenant=tenant,
                task_id=task_id,
                criterion=criterion or f"command:{self._safe_label(command)}",
                command_id=execution_id,
                command_digest=hashlib.sha256(command.encode("utf-8")).hexdigest(),
                repository_revision=str(state.get("fingerprint", "")),
                duration_ms=float(result.get("duration_ms", 0) or 0),
            )
            if not force and not is_mutating and self._non_retryable_failure(raw):
                raw.update({"terminal": True, "retryable": False})
                self.suppression_cache.set(attempt_key, raw)
            if singleflight:
                with self._lock:
                    if len(self._last) > 128:
                        old_keys = list(self._last.keys())[:64]
                        for k in old_keys:
                            self._last.pop(k, None)
                    self._last[key] = raw
            result.update({"cache_hit": False, "coalesced": False, "classification": classification, "repo_state": state, "repository_revision": str(state.get("fingerprint", ""))})
        except subprocess.TimeoutExpired:
            timeout_result = {"success": False, "error": "command timed out", "timed_out": True, "classification": classification, "cache_hit": False}
            if rollback_state is not None:
                try:
                    _restore_rollback_scope(cwd, rollback_state)
                    timeout_result["rolled_back"] = True
                except Exception as rb_exc:
                    timeout_result["rollback_error"] = str(rb_exc)[:512]
                    timeout_result["rolled_back"] = False
            return timeout_result
        finally:
            if rollback_state is not None:
                try:
                    _close_rollback_root(rollback_state.root_guard)
                except OSError:
                    pass
            with self._lock:
                if singleflight:
                    self._inflight.pop(key, None)
                self._active_commands.pop(execution_key, None)
                self._cancel_events.pop(execution_key, None)
                self._active_cancel_keys.pop(execution_key, None)
                if event is not None:
                    event.set()

        if task_id and self.policy_engine:
            try:
                from .agent_policy import BudgetCost
                elapsed_s = float(result.get("duration_ms", 0) or 0) / 1000.0
                self.policy_engine.consume(task_id, BudgetCost(compute_seconds=elapsed_s, external_calls=1))
            except Exception:
                pass

        compacted = self._compact(result, tenant, command)
        compacted["execution_id"] = execution_id
        if auto_fix and not compacted.get("success") and not compacted.get("cancelled"):
            repaired = self.repair_loop(
                command, cwd, tenant,
                max_attempts=max_repair_attempts,
                task_id=task_id, criterion=criterion,
                timeout=timeout,
                fix_generator=fix_generator,
                initial_result=compacted,
            )
            repaired["execution_id"] = execution_id
            return repaired
        return compacted

    def patch_and_verify(
        self,
        patch: str,
        cwd: str | Path,
        tenant: str,
        *,
        command: str = "",
        criterion: str = "",
        task_id: str = "",
        timeout: int | None = None,
        auto_rollback: bool = True,
        log_callback: Any | None = None,
    ) -> dict[str, Any]:
        """Apply a unified diff, run verification tests, and auto-rollback on failure."""
        cwd_path = Path(canonical_root(cwd))
        if not patch or not patch.strip():
            return {"success": False, "error": "patch text is empty", "terminal": True, "retryable": False}

        # 1. Check if patch applies cleanly
        check_proc = subprocess.run(
            ["git", "apply", "--check", "--whitespace=nowarn"],
            input=patch.encode("utf-8"),
            cwd=str(cwd_path), capture_output=True, check=False,
            timeout=self.git_snapshot_timeout, **hidden_run_kwargs()
        )
        if check_proc.returncode != 0:
            err_msg = check_proc.stderr.decode("utf-8", errors="replace")
            return {
                "success": False,
                "applied": False,
                "rolled_back": False,
                "error": f"Patch check failed: {err_msg.strip()}",
                "terminal": True,
                "retryable": False,
            }

        # 2. Apply patch
        apply_proc = subprocess.run(
            ["git", "apply", "--whitespace=nowarn"],
            input=patch.encode("utf-8"),
            cwd=str(cwd_path), capture_output=True, check=False,
            timeout=self.git_snapshot_timeout, **hidden_run_kwargs()
        )
        if apply_proc.returncode != 0:
            err_msg = apply_proc.stderr.decode("utf-8", errors="replace")
            return {
                "success": False,
                "applied": False,
                "rolled_back": False,
                "error": f"Patch apply failed: {err_msg.strip()}",
                "terminal": True,
                "retryable": False,
            }

        # 3. Roll back only the exact patch; preserve all other working-tree state.
        def _do_rollback() -> dict[str, Any]:
            try:
                rollback_proc = subprocess.run(
                    ["git", "apply", "--reverse", "--whitespace=nowarn"],
                    input=patch.encode("utf-8"),
                    cwd=str(cwd_path), capture_output=True, check=False,
                    timeout=self.git_snapshot_timeout, **hidden_run_kwargs()
                )
                if rollback_proc.returncode != 0:
                    detail = rollback_proc.stderr.decode("utf-8", errors="replace").strip()
                    return {
                        "rolled_back": False,
                        "rollback_error": f"Patch rollback failed: {detail or 'reverse patch did not apply'}",
                    }
                return {"rolled_back": True}
            except Exception as rollback_exc:
                return {"rolled_back": False, "rollback_error": f"Patch rollback failed: {rollback_exc}"}

        # 5. Syntax pre-flight check on modified Python files
        diff_lines = patch.splitlines()
        modified_py_files: list[Path] = []
        for line in diff_lines:
            if line.startswith("+++ b/"):
                rel_p = line[6:].strip()
                if rel_p.endswith(".py"):
                    modified_py_files.append(cwd_path / rel_p)

        import py_compile
        for py_file in modified_py_files:
            if py_file.is_file():
                try:
                    py_compile.compile(str(py_file), doraise=True)
                except py_compile.PyCompileError as syn_err:
                    rollback_result = _do_rollback() if auto_rollback else {"rolled_back": False}
                    return {
                        "success": False,
                        "applied": not rollback_result["rolled_back"],
                        **rollback_result,
                        "error": f"Syntax error in modified file {py_file.name}: {syn_err.msg}",
                        "diagnostics": [{"path": str(py_file.relative_to(cwd_path)), "message": syn_err.msg}],
                    }

        # 6. Determine test command
        test_cmd = command.strip() or criterion.strip()
        auto_detected_tests: list[str] = []
        if test_cmd.lower() == "auto":
            all_modified: list[str] = []
            for line in diff_lines:
                if line.startswith("+++ b/"):
                    all_modified.append(line[6:].strip())

            try:
                from .repo_tools import RepositoryTools
                from .deterministic import DeterministicEngine
                rt = RepositoryTools(self.config)
                det = DeterministicEngine(self.config, rt)
                aff = det.affected_tests(str(cwd_path), changed_paths=all_modified)
                auto_detected_tests = aff.get("test_files", []) if isinstance(aff, dict) else []
            except Exception:
                auto_detected_tests = []

            if auto_detected_tests:
                if any(tf.endswith(".py") for tf in auto_detected_tests):
                    test_cmd = f"python -m pytest {' '.join(auto_detected_tests[:5])} -q"
                elif any(tf.endswith((".ts", ".js")) for tf in auto_detected_tests):
                    test_cmd = f"npm test -- {' '.join(auto_detected_tests[:5])}"
                elif any(tf.endswith(".cs") for tf in auto_detected_tests):
                    test_cmd = "dotnet test"
                else:
                    test_cmd = f"python -m pytest {' '.join(auto_detected_tests[:5])} -q"
            else:
                test_cmd = ""

        if not test_cmd:
            return {
                "success": True,
                "applied": True,
                "tests_passed": True,
                "affected_tests_run": [],
                "message": "Patch applied cleanly and passed syntax verification (no tests required or specified)",
            }

        # 7. Run validation command
        run_res = self.run(
            test_cmd, str(cwd_path), tenant,
            timeout=timeout, force=True, task_id=task_id, criterion=criterion,
            log_callback=log_callback,
        )

        if run_res.get("success"):
            rcpt_data = run_res.get("verification_receipt")
            if not rcpt_data and task_id and self.verification_store is not None:
                try:
                    import uuid
                    from .agent_verification import VerificationReceipt
                    rcpt = VerificationReceipt.create(
                        task_id=task_id,
                        criterion=criterion or f"patch:{self._safe_label(test_cmd)}",
                        passed=True,
                        command_id=test_cmd,
                        evidence_id=str(run_res.get("artifact_id") or ""),
                        repository_revision=str(run_res.get("repository_revision") or ""),
                        details={"exit_code": 0, "duration_ms": run_res.get("duration_ms", 0)},
                    )
                    self.verification_store.record(rcpt)
                    rcpt_data = rcpt.to_dict()
                except Exception:
                    pass

            return {
                "success": True,
                "applied": True,
                "tests_passed": True,
                "command": test_cmd,
                "affected_tests_run": auto_detected_tests,
                "duration_ms": run_res.get("duration_ms"),
                "verification_receipt": rcpt_data,
                "message": "Patch applied and verified successfully",
            }
        else:
            rollback_result = _do_rollback() if auto_rollback else {"rolled_back": False}
            return {
                "success": False,
                "applied": not rollback_result["rolled_back"],
                **rollback_result,
                "error": "Validation command failed after applying patch",
                "command": test_cmd,
                "affected_tests_run": auto_detected_tests,
                "exit_code": run_res.get("exit_code"),
                "stdout": run_res.get("stdout"),
                "stderr": run_res.get("stderr"),
                "diagnostics": run_res.get("diagnostics", []),
                "remediation": run_res.get("remediation"),
            }

    def preflight(
        self,
        cwd: str | Path,
        tenant: str = "default",
        *,
        paths: list[str] | None = None,
        timeout: int = 10,
    ) -> dict[str, Any]:
        """Perform fast syntax and typecheck pre-flight on modified or specified files."""
        cwd_path = Path(canonical_root(cwd))
        if not cwd_path.is_dir():
            return {"success": False, "error": "Working directory does not exist"}

        target_files = [p.replace("\\", "/").strip() for p in (paths or []) if p]
        if not target_files:
            cp = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(cwd_path), capture_output=True, text=True, check=False,
                timeout=5, **hidden_run_kwargs()
            )
            if cp.returncode == 0:
                for line in cp.stdout.splitlines():
                    parts = line.strip().split(None, 1)
                    if len(parts) == 2:
                        target_files.append(parts[1].replace("\\", "/").strip())

        if not target_files:
            return {
                "success": True,
                "clean": True,
                "checker": "none",
                "message": "No modified files detected for pre-flight check",
                "errors": [],
            }

        py_files = [f for f in target_files if f.endswith(".py") and (cwd_path / f).is_file()]
        ts_files = [f for f in target_files if f.endswith((".ts", ".tsx", ".js", ".jsx")) and (cwd_path / f).is_file()]

        errors: list[dict[str, Any]] = []
        checker = "none"

        if py_files:
            checker = "py_compile"
            import py_compile
            for pf in py_files:
                p_path = cwd_path / pf
                try:
                    py_compile.compile(str(p_path), doraise=True)
                except py_compile.PyCompileError as err:
                    errors.append({
                        "file": pf,
                        "line": getattr(err, "lineno", 1) or 1,
                        "message": str(err.msg),
                        "level": "syntax_error",
                    })

        if ts_files and not errors and (cwd_path / "tsconfig.json").is_file():
            checker = "tsc"
            try:
                cp_tsc = subprocess.run(
                    ["npx", "tsc", "--noEmit", "--pretty", "false"],
                    cwd=str(cwd_path), capture_output=True, text=True, check=False,
                    timeout=timeout, **hidden_run_kwargs()
                )
                if cp_tsc.returncode != 0:
                    for line in cp_tsc.stdout.splitlines():
                        if ": error TS" in line:
                            parts = line.split(":", 3)
                            if len(parts) >= 4:
                                errors.append({
                                    "file": parts[0].strip(),
                                    "line": int(parts[1].strip() or 1),
                                    "col": int(parts[2].strip() or 1),
                                    "message": parts[3].strip(),
                                    "level": "type_error",
                                })
            except Exception:
                pass

        return {
            "success": True,
            "clean": len(errors) == 0,
            "checker": checker,
            "target_files": target_files[:10],
            "errors_count": len(errors),
            "errors": errors[:5],
            "message": "Pre-flight clean" if not errors else f"Found {len(errors)} pre-flight issue(s)",
        }

    def repair_loop(
        self,
        command: str,
        cwd: str | Path,
        tenant: str,
        *,
        max_attempts: int = 3,
        task_id: str = "",
        criterion: str = "",
        timeout: int | None = None,
        fix_generator: Any | None = None,
        initial_result: dict[str, Any] | None = None,
        log_callback: Any | None = None,
    ) -> dict[str, Any]:
        """Execute autonomous self-healing test loop on command failure.

        Synthesizes candidate diffs/patches, applies them with in-memory file backups,
        re-tests, and if successful, mints a VerificationReceipt and keeps the fix.
        If all attempts fail, cleanly rolls back all modified files to pristine state.
        """
        cwd_path = Path(canonical_root(cwd))
        initial = initial_result or self.run(
            command, str(cwd_path), tenant, timeout=timeout, force=True,
            task_id=task_id, criterion=criterion, auto_fix=False, log_callback=log_callback,
        )
        if initial.get("success"):
            return {
                "success": True,
                "repaired": False,
                "attempts": 0,
                "result": initial,
                "message": "command passed without repair",
            }

        classification = self.classify(command)
        command_class = str(classification.get("class", "unknown"))
        replay_safe = bool(classification.get("replay_safe", command_class == "read"))
        outcome_unknown = bool(
            initial.get("outcome_unknown")
            or initial.get("timed_out")
            or initial.get("cancelled")
            or not replay_safe
        )
        if outcome_unknown:
            uncertain = dict(initial)
            uncertain["outcome_unknown"] = True
            return {
                "success": False,
                "repaired": False,
                "repair_skipped": True,
                "outcome_unknown": True,
                "attempts": 0,
                "result": uncertain,
                "message": "repair skipped because command outcome or side effects are not safe to replay",
            }

        original_files: dict[Path, str | None] = {}
        attempt_history: list[dict[str, Any]] = []
        last_result = initial
        generated_patches: dict[str, str] | None = None
        generator_invoked = False

        try:
            for attempt in range(1, max(1, max_attempts) + 1):
                patches: dict[str, str] = {}
                if callable(fix_generator):
                    # A repair loop may retry applying the same bounded candidate,
                    # but it must never amplify one failed command into repeated
                    # local-model inference calls or send subsequent raw outputs.
                    if not generator_invoked:
                        generator_invoked = True
                        try:
                            gen_res = fix_generator(command, str(cwd_path), last_result)
                            if isinstance(gen_res, dict):
                                generated_patches = {str(k): str(v) for k, v in gen_res.items()}
                        except Exception as exc:
                            attempt_history.append({"attempt": attempt, "error": f"fix generator error: {exc}"})
                            continue
                    patches = dict(generated_patches or {})
                elif self.incident_store is not None:
                    rem = last_result.get("remediation") or {}
                    fix = rem.get("verified_fix")
                    if isinstance(fix, dict):
                        patches = {str(k): str(v) for k, v in fix.items()}

                if not patches:
                    attempt_history.append({"attempt": attempt, "error": "no candidate patches synthesized"})
                    continue

                applied_paths: list[Path] = []
                for rel_path, new_content in patches.items():
                    target = (cwd_path / rel_path).resolve()
                    try:
                        target.relative_to(cwd_path)
                    except ValueError:
                        try:
                            target_canon = Path(canonical_root(target))
                            target_canon.relative_to(cwd_path)
                            target = target_canon
                        except ValueError:
                            continue
                    if target not in original_files:
                        original_files[target] = target.read_text(encoding="utf-8", errors="replace") if target.is_file() else None
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(new_content, encoding="utf-8")
                    if target.suffix.lower() in {".py", ".pyw"}:
                        pycache = target.parent / "__pycache__"
                        if pycache.is_dir():
                            for pyc in pycache.glob(f"{target.stem}*.pyc"):
                                try:
                                    pyc.unlink(missing_ok=True)
                                except Exception:
                                    pass
                    applied_paths.append(target)

                re_result = self.run(command, str(cwd_path), tenant, timeout=timeout, force=True, auto_fix=False, log_callback=log_callback)
                last_result = re_result
                attempt_history.append({
                    "attempt": attempt,
                    "applied_files": [str(p.relative_to(cwd_path)) for p in applied_paths],
                    "success": bool(re_result.get("success")),
                    "re_stderr": re_result.get("stderr"),
                    "re_exit_code": re_result.get("exit_code"),
                })

                if re_result.get("success"):
                    rcpt_dict = None
                    if task_id and self.verification_store is not None:
                        try:
                            from .agent_verification import VerificationReceipt
                            criterion_text = criterion or f"repair:{self._safe_label(command)}"
                            evidence_id = str(re_result.get("artifact_id") or "")
                            if not evidence_id:
                                evidence_id = self.artifacts.put_json(
                                    {
                                        "schema": "local-ai-command-validation/v1",
                                        "task_id": task_id,
                                        "criterion": criterion_text,
                                        "command_label": self._safe_label(command),
                                        "exit_code": int(re_result.get("exit_code", 0) or 0),
                                        "duration_ms": re_result.get("duration_ms"),
                                        "repository_revision": str(
                                            re_result.get("repository_revision")
                                            or re_result.get("repo_state", {}).get("fingerprint", "")
                                        ),
                                        "attempt": attempt,
                                        "repaired_paths": [
                                            str(p.relative_to(cwd_path)) for p in applied_paths
                                        ],
                                    },
                                    tenant,
                                    "command_validation",
                                )
                                re_result["artifact_id"] = evidence_id
                            rcpt = VerificationReceipt.create(
                                task_id=task_id,
                                criterion=criterion_text,
                                passed=True,
                                command_id=command,
                                evidence_id=evidence_id,
                                repository_revision=str(re_result.get("repository_revision") or re_result.get("repo_state", {}).get("fingerprint", "")),
                                details={
                                    "exit_code": 0,
                                    "attempts": attempt,
                                    "repaired_paths": [str(p.relative_to(cwd_path)) for p in applied_paths],
                                },
                            )
                            self.verification_store.record(rcpt)
                            rcpt_dict = rcpt.to_dict()
                        except Exception:
                            pass

                    if self.incident_store is not None:
                        try:
                            rem = initial.get("remediation") or {}
                            inc_id = rem.get("incident_id")
                            if inc_id:
                                self.incident_store.record_decision(
                                    inc_id,
                                    action="apply_verified_fix",
                                    verified_fix=json_dumps([str(p.relative_to(cwd_path)) for p in applied_paths]),
                                    confidence=1.0,
                                )
                        except Exception:
                            pass

                    original_files.clear()
                    return {
                        "success": True,
                        "repaired": True,
                        "attempts": attempt,
                        "patches_applied": [str(p.relative_to(cwd_path)) for p in applied_paths],
                        "verification_receipt": rcpt_dict,
                        "result": re_result,
                    }
                else:
                    for target, orig_content in list(original_files.items()):
                        if orig_content is None:
                            target.unlink(missing_ok=True)
                        else:
                            target.write_text(orig_content, encoding="utf-8")
                        if target.suffix.lower() in {".py", ".pyw"}:
                            pycache = target.parent / "__pycache__"
                            if pycache.is_dir():
                                for pyc in pycache.glob(f"{target.stem}*.pyc"):
                                    try:
                                        pyc.unlink(missing_ok=True)
                                    except Exception:
                                        pass
                    original_files.clear()

        finally:
            for target, orig_content in original_files.items():
                try:
                    if orig_content is None:
                        target.unlink(missing_ok=True)
                    else:
                        target.write_text(orig_content, encoding="utf-8")
                except Exception:
                    pass

        return {
            "success": False,
            "repaired": False,
            "attempts": len(attempt_history),
            "history": attempt_history,
            "original_result": initial,
            "error": "Self-healing repair loop exhausted without passing command.",
        }

    def format(
        self,
        root: str,
        paths: list[str] | None = None,
        tenant: str = "agent",
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """Automatically detect local code formatters and format paths or repository."""
        resolved_root = Path(canonical_root(root))
        if not resolved_root.is_dir():
            return {"success": False, "error": f"Directory not found: {root}"}

        target_str = " ".join(f'"{p}"' for p in paths) if paths else "."
        cmd = None
        formatter_name = None

        if (resolved_root / "pyproject.toml").exists() or any((resolved_root / f).is_file() for f in ("setup.py", "requirements.txt")):
            if shutil.which("ruff"):
                cmd = f"ruff format {target_str}"
                formatter_name = "ruff"
            elif shutil.which("black"):
                cmd = f"black {target_str}"
                formatter_name = "black"
        elif (resolved_root / "package.json").exists():
            if shutil.which("prettier"):
                cmd = f"prettier --write {target_str}"
                formatter_name = "prettier"
        elif (resolved_root / "Cargo.toml").exists():
            if shutil.which("cargo"):
                cmd = "cargo fmt"
                formatter_name = "cargo fmt"
        elif (resolved_root / "go.mod").exists():
            if shutil.which("gofmt"):
                cmd = f"gofmt -w {target_str}"
                formatter_name = "gofmt"
        elif any((resolved_root / f).is_file() for f in os.listdir(str(resolved_root)) if f.endswith((".sln", ".csproj"))):
            if shutil.which("dotnet"):
                cmd = "dotnet format"
                formatter_name = "dotnet format"

        if not cmd:
            if shutil.which("ruff"):
                cmd = f"ruff format {target_str}"
                formatter_name = "ruff"
            elif shutil.which("black"):
                cmd = f"black {target_str}"
                formatter_name = "black"

        if not cmd:
            return {"success": False, "error": "No supported code formatter found in PATH (tried ruff, black, prettier, cargo, gofmt, dotnet)"}

        res = self.run(cmd, str(resolved_root), tenant=tenant, timeout=timeout or 60, force=True)
        res["formatter"] = formatter_name
        return res

    def lint_fix(
        self,
        root: str,
        command: str | None = None,
        paths: list[str] | None = None,
        tenant: str = "agent",
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """Automatically run project linters in auto-fix mode to resolve style/lint issues."""
        resolved_root = Path(root).expanduser().resolve(strict=False)
        if not resolved_root.is_dir():
            return {"success": False, "error": f"root directory does not exist: {root}"}

        target_str = " ".join(f'"{p}"' for p in paths) if paths else "."
        cmd = command
        linter_name = "custom"

        if not cmd:
            if (resolved_root / "pyproject.toml").exists() or any((resolved_root / f).is_file() for f in ("setup.py", "requirements.txt")):
                if shutil.which("ruff"):
                    cmd = f"ruff check --fix {target_str}"
                    linter_name = "ruff"
                elif shutil.which("autopep8"):
                    cmd = f"autopep8 --in-place --aggressive {target_str}"
                    linter_name = "autopep8"
            elif (resolved_root / "package.json").exists():
                if shutil.which("eslint"):
                    cmd = f"eslint --fix {target_str}"
                    linter_name = "eslint"
                elif shutil.which("npm"):
                    cmd = "npm run lint -- --fix"
                    linter_name = "npm lint"
            elif (resolved_root / "Cargo.toml").exists():
                if shutil.which("cargo"):
                    cmd = "cargo fix --allow-no-vcs"
                    linter_name = "cargo fix"
            elif (resolved_root / "go.mod").exists():
                if shutil.which("golangci-lint"):
                    cmd = f"golangci-lint run --fix {target_str}"
                    linter_name = "golangci-lint"
                elif shutil.which("gofmt"):
                    cmd = f"gofmt -w {target_str}"
                    linter_name = "gofmt"

        if not cmd:
            if shutil.which("ruff"):
                cmd = f"ruff check --fix {target_str}"
                linter_name = "ruff"

        if not cmd:
            return {"success": False, "error": "No supported linter with auto-fix found in PATH (tried ruff, eslint, cargo, golangci-lint)"}

        res = self.run(cmd, str(resolved_root), tenant=tenant, timeout=timeout or 120, force=True)
        res["linter"] = linter_name
        return res

    def spawn_daemon(
        self,
        command: str | Sequence[str],
        cwd: str,
        name: str = "",
        env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Spawn a detached background daemon process with bounded logging and lifecycle tracking."""
        argv, command_label, command_error = self._daemon_argv(command)
        if command_error:
            return {"success": False, "error": command_error}
        if not isinstance(name, str) or len(name) > 128 or any(ord(ch) < 32 for ch in name):
            return {"success": False, "error": "daemon name must be a control-free string of at most 128 characters"}
        resolved_cwd = Path(cwd).expanduser().resolve(strict=False)
        if not resolved_cwd.is_dir():
            return {"success": False, "error": f"working directory does not exist: {cwd}"}
        try:
            proc_env = self._daemon_environment(env)
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

        self._refresh_daemon_capacity()
        if not self._daemon_slots.acquire(blocking=False):
            return {"success": False, "error": "maximum active daemon count reached", "retryable": False}

        import uuid
        daemon_id = f"dmn_{uuid.uuid4().hex}"
        state_dir = configured_state_dir(self.config)
        log_dir = state_dir / "daemons"
        log_path = log_dir / f"{daemon_id}.log"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            log_fh = log_path.open("w+b")
        except OSError as exc:
            self._daemon_slots.release()
            return {"success": False, "error": f"could not prepare daemon log: {exc}"}
        read_fh = None
        write_fh = None

        kwargs: dict[str, Any] = {
            "cwd": str(resolved_cwd),
            "stdout": None,
            "stderr": subprocess.STDOUT,
            "env": proc_env,
        }
        if os.name == "nt":
            kwargs.update(hidden_run_kwargs(new_group=True))
            kwargs["creationflags"] = int(kwargs.get("creationflags", 0)) | getattr(subprocess, "CREATE_SUSPENDED", 0x00000004)
        else:
            kwargs["start_new_session"] = True

        job_handle = None
        process = None
        try:
            if os.name == "nt":
                job_handle = create_job_object_kill_on_close()
                if not job_handle:
                    raise OSError("unable to create a kill-on-close daemon Job Object")
            read_fd, write_fd = os.pipe()
            read_fh = os.fdopen(read_fd, "rb", buffering=0)
            write_fh = os.fdopen(write_fd, "wb", buffering=0)
            kwargs["stdout"] = write_fh
            process = subprocess.Popen(argv, **kwargs)
            if job_handle:
                process._local_ai_job_handle = job_handle
                if not assign_process_to_job(job_handle, process.pid):
                    raise OSError("unable to assign suspended daemon to its Job Object")
                if not _resume_suspended_process(process):
                    raise OSError("unable to resume suspended daemon process")
            write_fh.close()
            write_fh = None
        except (OSError, ValueError) as exc:
            if process is not None:
                try:
                    process.kill()
                except OSError:
                    pass
                try:
                    process.wait(timeout=2.0)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            if job_handle:
                close_job_object(job_handle)
            for handle in (read_fh, write_fh):
                if handle is not None:
                    try:
                        handle.close()
                    except OSError:
                        pass
            log_fh.close()
            self._daemon_slots.release()
            return {"success": False, "error": f"failed to spawn daemon: {exc}"}

        started_at = time.time()
        info = {
            "daemon_id": daemon_id,
            "process": process,
            "pid": process.pid,
            "identity": process_identity(process.pid),
            "owner_id": self._daemon_owner_id,
            "name": name or daemon_id,
            "command": command_label,
            "cwd": str(resolved_cwd),
            "log_path": str(log_path),
            "log_fh": log_fh,
            "log_buffer": bytearray(),
            "log_lock": threading.Lock(),
            "_log_closed": False,
            "started_at": started_at,
            "expires_at": started_at + self.daemon_ttl_seconds,
            "_slot_acquired": True,
            "_slot_released": False,
        }
        reader = threading.Thread(
            target=self._capture_daemon_output,
            args=(read_fh, info, self.daemon_log_max_bytes),
            name=f"local-ai-daemon-log-{daemon_id}",
            daemon=True,
        )
        info["reader_thread"] = reader
        with self._daemons_lock:
            if len(self._daemons) > 50:
                dead = [d for d, inf in self._daemons.items() if inf["process"].poll() is not None]
                if len(dead) > 20:
                    dead.sort(key=lambda d: float(self._daemons[d].get("stopped_at", self._daemons[d].get("started_at", 0))))
                    for old_d in dead[:len(dead) - 20]:
                        self._close_daemon_log(self._daemons[old_d])
                        self._daemons.pop(old_d, None)
            self._daemons[daemon_id] = info
        try:
            reader.start()
        except RuntimeError as exc:
            try:
                _stop_daemon_tree(info)
                process.wait(timeout=2.0)
            except Exception:
                pass
            try:
                read_fh.close()
            except OSError:
                pass
            self._close_daemon_log(info)
            with self._daemons_lock:
                self._daemons.pop(daemon_id, None)
            self._release_daemon_slot(info)
            return {"success": False, "error": f"failed to start daemon log reader: {exc}"}
        try:
            self._schedule_daemon_expiry(info)
        except RuntimeError as exc:
            stopped = self.stop_daemon(daemon_id)
            return {
                "success": False,
                "error": f"failed to schedule daemon TTL cleanup: {exc}",
                "daemon_id": daemon_id if not stopped.get("success") else None,
                "cleanup_success": bool(stopped.get("success")),
            }
        watcher = threading.Thread(
            target=self._watch_daemon_exit,
            args=(daemon_id, process),
            name=f"local-ai-daemon-watch-{daemon_id}",
            daemon=True,
        )
        info["watcher_thread"] = watcher
        try:
            watcher.start()
        except RuntimeError as exc:
            stopped = self.stop_daemon(daemon_id)
            return {
                "success": False,
                "error": f"failed to start daemon lifecycle watcher: {exc}",
                "cleanup_success": bool(stopped.get("success")),
            }
        with self._daemons_lock:
            registry_saved = self._persist_daemon_registry()
        if not registry_saved:
            stopped = self.stop_daemon(daemon_id)
            return {
                "success": False,
                "error": "daemon registry could not be written; newly started process was stopped",
                "cleanup_success": bool(stopped.get("success")),
            }

        return {
            "success": True,
            "daemon_id": daemon_id,
            "pid": process.pid,
            "name": name or daemon_id,
            "command": command_label,
            "status": "running",
            "log_path": str(log_path),
            "owner_id": self._daemon_owner_id,
            "ttl_seconds": self.daemon_ttl_seconds,
        }

    def daemon_status(self, daemon_id: str | None = None) -> dict[str, Any]:
        """Check status of one or all background daemons."""
        now = time.time()
        with self._daemons_lock:
            if daemon_id:
                info = self._daemons.get(daemon_id)
                if not info:
                    return {"success": False, "error": f"daemon not found: {daemon_id}"}
                proc = info["process"]
                alive = proc.poll() is None
                newly_stopped = not alive and "stopped_at" not in info
                if not alive:
                    tree_stopped = info.get("process_tree_stopped") is True
                    if not tree_stopped:
                        tree_stopped = _stop_daemon_tree(info)
                        info["process_tree_stopped"] = tree_stopped
                    reader = info.get("reader_thread")
                    if reader is not None:
                        reader.join(timeout=0.2)
                    if reader is None or not reader.is_alive():
                        self._close_daemon_log(info)
                    if tree_stopped:
                        timer = info.get("ttl_timer")
                        if timer is not None:
                            timer.cancel()
                        self._release_daemon_slot(info)
                        info.setdefault("stopped_at", now)
                        if newly_stopped:
                            self._persist_daemon_registry()
                self._flush_daemon_log(info)
                with info.get("log_lock", threading.Lock()):
                    log_tail = bytes(info.get("log_buffer", b""))[-8192:].decode("utf-8", errors="replace")
                log_tail = "\n".join(log_tail.splitlines()[-30:])
                return {
                    "success": True,
                    "daemon_id": daemon_id,
                    "alive": alive,
                    "running": alive,
                    "pid": info["pid"],
                    "status": "running" if alive else ("stopped" if info.get("process_tree_stopped") is True else "cleanup_unconfirmed"),
                    "process_tree_stopped": info.get("process_tree_stopped") is True,
                    "exit_code": proc.poll(),
                    "uptime_seconds": round(now - float(info["started_at"]), 1),
                    "owner_id": info.get("owner_id", ""),
                    "ttl_remaining_seconds": max(0.0, round(float(info.get("expires_at", now)) - now, 1)),
                    "name": info["name"],
                    "command": self._safe_label(info["command"]),
                    "log_tail": log_tail,
                }
            items = []
            registry_changed = False
            for d_id, info in self._daemons.items():
                proc = info["process"]
                alive = proc.poll() is None
                if not alive:
                    tree_stopped = info.get("process_tree_stopped") is True
                    if not tree_stopped:
                        tree_stopped = _stop_daemon_tree(info)
                        info["process_tree_stopped"] = tree_stopped
                    reader = info.get("reader_thread")
                    if reader is not None:
                        reader.join(timeout=0.2)
                    if reader is None or not reader.is_alive():
                        self._close_daemon_log(info)
                    if tree_stopped:
                        registry_changed = registry_changed or "stopped_at" not in info
                        timer = info.get("ttl_timer")
                        if timer is not None:
                            timer.cancel()
                        self._release_daemon_slot(info)
                        info.setdefault("stopped_at", now)
                items.append({
                    "daemon_id": d_id,
                    "alive": alive,
                    "running": alive,
                    "pid": info["pid"],
                    "status": "running" if alive else ("stopped" if info.get("process_tree_stopped") is True else "cleanup_unconfirmed"),
                    "process_tree_stopped": info.get("process_tree_stopped") is True,
                    "exit_code": proc.poll(),
                    "uptime_seconds": round(now - float(info["started_at"]), 1),
                    "owner_id": info.get("owner_id", ""),
                    "ttl_remaining_seconds": max(0.0, round(float(info.get("expires_at", now)) - now, 1)),
                    "name": info["name"],
                    "command": self._safe_label(info["command"]),
                })
            if registry_changed:
                self._persist_daemon_registry()
            return {"success": True, "daemons": items, "count": len(items)}

    def stop_daemon(self, daemon_id: str) -> dict[str, Any]:
        """Terminate a background daemon process tree cleanly."""
        with self._daemons_lock:
            info = self._daemons.get(daemon_id)
            if not info:
                return {"success": False, "error": f"daemon not found: {daemon_id}"}
            proc = info["process"]
            tree_stopped = info.get("process_tree_stopped") is True
            if not tree_stopped:
                try:
                    # The leader may have exited while descendants remain in its
                    # process group/tree; stop the owned tree even after leader exit.
                    tree_stopped = _stop_daemon_tree(info)
                except Exception:
                    tree_stopped = False
            if proc.poll() is None:
                try:
                    proc.wait(timeout=2.0)
                except Exception:
                    try:
                        proc.kill()
                        proc.wait(timeout=1.0)
                    except Exception:
                        pass
            if not tree_stopped:
                try:
                    tree_stopped = _stop_daemon_tree(info)
                except Exception:
                    tree_stopped = False
            if proc.poll() is None:
                return {
                    "success": False,
                    "daemon_id": daemon_id,
                    "status": "running",
                    "running": True,
                    "alive": True,
                    "process_tree_stopped": False,
                    "pid": info["pid"],
                    "error": "daemon did not stop within the bounded termination window",
                }
            if not tree_stopped:
                return {
                    "success": False,
                    "daemon_id": daemon_id,
                    "status": "cleanup_unconfirmed",
                    "running": False,
                    "alive": False,
                    "process_tree_stopped": False,
                    "pid": info["pid"],
                    "error": "daemon leader stopped but process-tree cleanup could not be confirmed",
                }
            info["process_tree_stopped"] = True
            timer = info.get("ttl_timer")
            if timer is not None:
                timer.cancel()
            reader = info.get("reader_thread")
            if reader is not None:
                reader.join(timeout=2.5)
            self._close_daemon_log(info)
            self._release_daemon_slot(info)
            info["stopped_at"] = time.time()
            if len(self._daemons) > 50:
                dead = [d for d, inf in self._daemons.items() if inf["process"].poll() is not None]
                if len(dead) > 20:
                    dead.sort(key=lambda d: float(self._daemons[d].get("stopped_at", self._daemons[d].get("started_at", 0))))
                    for old_d in dead[:len(dead) - 20]:
                        self._close_daemon_log(self._daemons[old_d])
                        self._daemons.pop(old_d, None)
            self._persist_daemon_registry()
            return {
                "success": True,
                "daemon_id": daemon_id,
                "status": "stopped",
                "running": False,
                "alive": False,
                "process_tree_stopped": True,
                "exit_code": proc.poll(),
            }

    def http_probe(
        self,
        url: str,
        expected_status: int = 200,
        json_path: str | None = None,
        timeout: float = 5.0,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Execute a fast, bounded headless HTTP/API endpoint probe."""
        import urllib.request
        import urllib.error
        import json
        clean_url = url.strip()
        if not (clean_url.startswith("http://") or clean_url.startswith("https://")):
            return {"success": False, "error": f"invalid HTTP URL: {url}"}

        req = urllib.request.Request(clean_url, headers=headers or {"User-Agent": "LocalAIHub-Probe/1.0"})
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=max(0.1, float(timeout))) as resp:
                elapsed = time.perf_counter() - t0
                status_code = int(resp.status)
                body_bytes = resp.read(65536)
                body_text = body_bytes.decode("utf-8", errors="replace")
                resp_headers = dict(resp.headers)
        except urllib.error.HTTPError as exc:
            elapsed = time.perf_counter() - t0
            status_code = int(exc.code)
            body_bytes = exc.read(65536) if hasattr(exc, "read") else b""
            body_text = body_bytes.decode("utf-8", errors="replace")
            resp_headers = dict(exc.headers) if hasattr(exc, "headers") else {}
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            return {
                "success": False,
                "status_code": 0,
                "error": f"request failed: {exc}",
                "latency_ms": round(elapsed * 1000, 1),
            }

        matches_status = (status_code == expected_status)
        json_match = None
        if json_path:
            try:
                parsed = json.loads(body_text)
                if isinstance(parsed, dict):
                    json_match = bool(parsed.get(json_path) is not None)
                elif isinstance(parsed, list):
                    json_match = (len(parsed) > 0)
                else:
                    json_match = True
            except Exception:
                json_match = False

        success = matches_status and (json_match is not False)
        return {
            "success": success,
            "status_code": status_code,
            "expected_status": expected_status,
            "latency_ms": round(elapsed * 1000, 1),
            "body_preview": body_text[:500],
            "body_length": len(body_text),
            "json_matched": json_match,
            "headers": {k.lower(): v for k, v in list(resp_headers.items())[:12]},
        }

    def stash_save(self, cwd: str, message: str = "local_ai_hub_stash") -> dict[str, Any]:
        """Save dirty working tree state to Git stash."""
        resolved = str(Path(cwd).resolve())
        cmd = f'git stash push -u -m "{message}"'
        res = self._execute(cmd, resolved, timeout=30)
        return {
            "success": res.get("success", False),
            "stdout": res.get("stdout", "").strip(),
            "stashed": "Saved working directory" in res.get("stdout", "") or "No local changes" in res.get("stdout", ""),
        }

    def stash_restore(self, cwd: str) -> dict[str, Any]:
        """Restore most recent Git stash."""
        resolved = str(Path(cwd).resolve())
        cmd = "git stash pop"
        res = self._execute(cmd, resolved, timeout=30)
        return {
            "success": res.get("success", False),
            "stdout": res.get("stdout", "").strip(),
            "stderr": res.get("stderr", "").strip(),
        }

    def record_mock(self, url: str, cassette_name: str, state_dir: str | None = None) -> dict[str, Any]:
        """Record an HTTP request/response as an offline mock cassette."""
        probe = self.http_probe(url, timeout=10.0)
        if not probe.get("success"):
            return {"success": False, "error": f"failed to fetch URL: {probe.get('error')}"}
        s_dir = Path(state_dir or self.config.get("server", {}).get("state_dir", ".local-ai-hub")) / "cassettes"
        s_dir.mkdir(parents=True, exist_ok=True)
        cassette_file = s_dir / f"{cassette_name}.json"
        data = {
            "url": url,
            "recorded_at": time.time(),
            "status_code": probe["status_code"],
            "headers": probe.get("headers", {}),
            "body": probe.get("body_preview", ""),
            "body_length": probe.get("body_length", 0),
        }
        cassette_file.write_text(json_dumps(data, indent=2), encoding="utf-8")
        return {"success": True, "cassette": str(cassette_file), "url": url, "status_code": probe["status_code"]}

    def replay_mock(self, cassette_name: str, state_dir: str | None = None) -> dict[str, Any]:
        """Replay an offline mock cassette."""
        s_dir = Path(state_dir or self.config.get("server", {}).get("state_dir", ".local-ai-hub")) / "cassettes"
        cassette_file = s_dir / f"{cassette_name}.json"
        if not cassette_file.is_file():
            return {"success": False, "error": f"cassette not found: {cassette_name}"}
        try:
            data = json.loads(cassette_file.read_text(encoding="utf-8"))
            return {"success": True, "replayed": True, **data}
        except Exception as exc:
            return {"success": False, "error": f"failed to read cassette: {exc}"}

    def diff_hunk_stage(self, cwd: str, patch: str) -> dict[str, Any]:
        """Apply and stage a diff hunk directly to the git index using git apply --cached."""
        resolved = str(Path(cwd).resolve())
        if not patch or not patch.strip():
            return {"success": False, "error": "patch content must not be empty"}
        if not shutil.which("git"):
            return {"success": False, "error": "git executable not found"}
        try:
            proc = subprocess.run(
                ["git", "apply", "--cached", "--whitespace=nowarn", "-"],
                input=patch,
                text=True,
                capture_output=True,
                cwd=resolved,
                check=False,
                timeout=30,
                **hidden_run_kwargs(),
            )
            clean = (proc.returncode == 0)
            return {
                "success": clean,
                "exit_code": proc.returncode,
                "stdout": proc.stdout.strip(),
                "stderr": proc.stderr.strip() if not clean else "",
                "staged": clean,
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def test_flaky_detect(
        self,
        cwd: str,
        command: str,
        runs: int = 5,
        timeout_per_run: int = 30,
    ) -> dict[str, Any]:
        """Run a test command N times to detect flaky or intermittent failures."""
        resolved = str(Path(cwd).resolve())
        bounded_runs = max(2, min(int(runs), 20))
        results: list[dict[str, Any]] = []
        passed_count = 0
        failed_count = 0
        for i in range(1, bounded_runs + 1):
            res = self._execute(command, resolved, timeout=timeout_per_run)
            is_ok = bool(res.get("success") and res.get("exit_code") == 0)
            if is_ok:
                passed_count += 1
            else:
                failed_count += 1
            results.append({
                "run": i,
                "success": is_ok,
                "exit_code": res.get("exit_code", -1),
                "duration_ms": res.get("duration_ms", 0),
                "stdout_preview": (res.get("stdout") or "")[:200],
                "stderr_preview": (res.get("stderr") or "")[:200],
            })
        is_flaky = (passed_count > 0 and failed_count > 0)
        return {
            "success": True,
            "command": command,
            "total_runs": bounded_runs,
            "passed": passed_count,
            "failed": failed_count,
            "pass_rate": round(passed_count / bounded_runs, 2),
            "flaky": is_flaky,
            "status": "flaky" if is_flaky else "stable_pass" if passed_count == bounded_runs else "stable_fail",
            "runs": results,
        }

    def webhook_replay(
        self,
        url: str,
        payload: dict[str, Any] | str,
        secret: str = "",
        signature_header: str = "X-Hub-Signature-256",
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        """Deliver a mock webhook payload with HMAC-SHA256 signature to a target endpoint."""
        import hmac
        import hashlib
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError, URLError

        body_str = json_dumps(payload) if isinstance(payload, dict) else str(payload)
        body_bytes = body_str.encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "LocalAIHub-WebhookReplay/3.0",
        }
        if secret:
            sig = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
            headers[signature_header] = f"sha256={sig}"

        req = Request(url, data=body_bytes, headers=headers, method="POST")
        started = time.perf_counter()
        try:
            with urlopen(req, timeout=max(0.1, float(timeout))) as resp:
                resp_body = resp.read(65_536).decode("utf-8", errors="replace")
                dur = round((time.perf_counter() - started) * 1000, 1)
                return {
                    "success": True,
                    "status_code": resp.status,
                    "duration_ms": dur,
                    "body_preview": resp_body[:500],
                    "headers": {k.lower(): v for k, v in list(resp.headers.items())[:10]},
                }
        except HTTPError as exc:
            resp_body = exc.read(65_536).decode("utf-8", errors="replace")
            return {
                "success": False,
                "status_code": exc.code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                "error": f"HTTP {exc.code}",
                "body_preview": resp_body[:500],
            }
        except URLError as exc:
            return {"success": False, "error": str(exc.reason)}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def mock_server_start(
        self,
        root: str = ".",
        spec_path: str | None = None,
        port: int = 11440,
    ) -> dict[str, Any]:
        """Start an in-process mock HTTP server delivering simulated OpenAPI endpoints."""
        import http.server
        import socketserver

        target_port = int(port or 11440)
        with self._lock:
            if not hasattr(self, "_mock_servers"):
                self._mock_servers: dict[int, dict[str, Any]] = {}

            if target_port in self._mock_servers:
                srv_info = self._mock_servers[target_port]
                if srv_info.get("alive"):
                    return {"success": True, "running": True, "port": target_port, "routes": srv_info.get("routes", [])}

        endpoints = []
        resolved_root = str(Path(root).resolve())
        if spec_path:
            p_spec = Path(spec_path)
            if not p_spec.is_absolute():
                p_spec = Path(resolved_root) / p_spec
            if p_spec.is_file():
                try:
                    spec_data = json.loads(p_spec.read_text(encoding="utf-8"))
                    paths = spec_data.get("paths", {})
                    for p_url, methods in paths.items():
                        for m, defn in methods.items():
                            endpoints.append({
                                "method": m.upper(),
                                "path": p_url,
                                "summary": defn.get("summary", ""),
                                "responses": defn.get("responses", {}),
                            })
                except Exception:
                    pass

        if not endpoints:
            from .deterministic import DeterministicEngine
            det = DeterministicEngine(self.config)
            spec = det.extract_api_spec(resolved_root)
            endpoints = spec.get("endpoints", [])

        if not endpoints:
            endpoints = [{"method": "GET", "path": "/api/health", "summary": "Health check"}]

        class MockHandler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def do_GET(self):
                self._handle("GET")

            def do_POST(self):
                self._handle("POST")

            def do_PUT(self):
                self._handle("PUT")

            def do_DELETE(self):
                self._handle("DELETE")

            def _handle(self, method: str):
                path_only = self.path.split("?", 1)[0]
                matched = None
                for ep in endpoints:
                    if ep.get("method") == method:
                        ep_path = ep.get("path", "")
                        regex_p = "^" + re.sub(r"\{[a-zA-Z0-9_]+\}", "[^/]+", ep_path) + "$"
                        if ep_path == path_only or re.match(regex_p, path_only):
                            matched = ep
                            break

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                resp = {
                    "mock": True,
                    "status": 200,
                    "method": method,
                    "path": path_only,
                    "endpoint": matched or {"path": path_only, "synthetic": True},
                    "data": {"id": 1, "name": "mock_resource", "timestamp": time.time()},
                }
                self.wfile.write(json_dumps(resp).encode("utf-8"))

        class ReusableTCPServer(socketserver.TCPServer):
            allow_reuse_address = True

        try:
            httpd = ReusableTCPServer(("127.0.0.1", target_port), MockHandler)
            thread = threading.Thread(target=httpd.serve_forever, daemon=True, name=f"mock-srv-{target_port}")
            thread.start()
            with self._lock:
                self._mock_servers[target_port] = {
                    "server": httpd,
                    "thread": thread,
                    "port": target_port,
                    "routes": [f"{ep.get('method')} {ep.get('path')}" for ep in endpoints[:20]],
                    "alive": True,
                    "started_at": time.time(),
                }
            return {
                "success": True,
                "port": target_port,
                "routes_count": len(endpoints),
                "sample_routes": [f"{ep.get('method')} {ep.get('path')}" for ep in endpoints[:10]],
                "status": "listening",
            }
        except Exception as exc:
            return {"success": False, "error": str(exc), "port": target_port}

    def mock_server_stop(self, port: int = 11440) -> dict[str, Any]:
        """Stop a running mock HTTP server."""
        target_port = int(port or 11440)
        with self._lock:
            srv_info = getattr(self, "_mock_servers", {}).get(target_port)
            if not srv_info or not srv_info.get("alive"):
                return {"success": False, "error": f"no active mock server on port {target_port}"}
            try:
                srv_info["server"].shutdown()
                srv_info["server"].server_close()
                srv_info["alive"] = False
                if len(self._mock_servers) > 32:
                    dead = [p for p, info in self._mock_servers.items() if not info.get("alive")]
                    for p in dead:
                        self._mock_servers.pop(p, None)
                return {"success": True, "stopped": True, "port": target_port}
            except Exception as exc:
                return {"success": False, "error": str(exc), "port": target_port}

    def mock_server_status(self, port: int = 11440) -> dict[str, Any]:
        """Check status of mock HTTP server."""
        target_port = int(port or 11440)
        with self._lock:
            srv_info = getattr(self, "_mock_servers", {}).get(target_port)
            if not srv_info:
                return {"success": True, "running": False, "port": target_port}
            return {
                "success": True,
                "running": bool(srv_info.get("alive")),
                "port": target_port,
                "uptime_seconds": round(time.time() - srv_info.get("started_at", time.time()), 1),
                "routes": srv_info.get("routes", []),
            }


    def _compact(self, result: dict[str, Any], tenant: str, command: str) -> dict[str, Any]:
        stdout = str(result.get("stdout", "")); stderr = str(result.get("stderr", ""))
        combined_chars = len(stdout) + len(stderr)
        diagnostic_artifacts_enabled = rollout_feature_enabled(self.config, "diagnostic_artifacts")
        local_diagnostic_dispatch_enabled = rollout_feature_enabled(self.config, "local_diagnostic_dispatch")
        diagnostic_artifacts_unavailable = {
            "available": False,
            "unsupported": True,
            "feature": "diagnostic_artifacts",
            "error": "diagnostic artifacts are disabled (features.diagnostic_artifacts=false)",
        }
        result["summary"] = self._deterministic_summary(result)
        classification = result.get("classification") if isinstance(result.get("classification"), dict) else {}
        if classification:
            # Keep the policy decision visible even in compact responses.
            result["allowed"] = bool(classification.get("allowed", False))
            result["class"] = str(classification.get("class", "unknown"))
            result["reason"] = str(classification.get("reason", ""))[:240]
        diagnostics = list(result.get("diagnostics") or self._extract_diagnostics(result))
        failure_summary = self._first_failure_summary({**result, "diagnostics": diagnostics})
        if result.get("remediation"):
            rem = result["remediation"]
            fix_msg = rem.get("verified_fix") or rem.get("root_cause")
            if fix_msg:
                diagnostics.insert(0, {
                    "path": "",
                    "line": 0,
                    "column": 0,
                    "message": f"Remediation guidance: {fix_msg}",
                })
        result["diagnostics"] = diagnostics
        if not result.get("success") and not result.get("cancelled"):
            result["failure_summary"] = failure_summary
            result["preview"] = self._failure_preview(failure_summary)
            # Low-confidence short failures do not get the full-log artifact below.
            # Retain only the already-bounded diagnostic so the repair gate receives
            # a safe reference without persisting the raw command output.
            if combined_chars <= self.inline_chars and not result.get("artifact_id") and not failure_summary.get("path"):
                if local_diagnostic_dispatch_enabled and self.artifacts is not None:
                    diagnostic = str(result["preview"])[:800]
                    result["artifact_id"] = self.artifacts.put(diagnostic, tenant, "local_diagnostic_context")
                elif not diagnostic_artifacts_enabled:
                    result["diagnostic_artifacts"] = diagnostic_artifacts_unavailable
                elif self.artifacts is not None:
                    diagnostic = str(result["preview"])[:800]
                    result["artifact_id"] = self.artifacts.put(diagnostic, tenant, "command_diagnostic")
        if combined_chars > self.inline_chars:
            full = f"$ {command}\n\nSTDOUT:\n{stdout}\n\nSTDERR:\n{stderr}"
            if local_diagnostic_dispatch_enabled and not diagnostic_artifacts_enabled and self.artifacts is not None:
                diagnostic = str(result.get("preview", ""))[:800]
                result["artifact_id"] = self.artifacts.put(diagnostic, tenant, "local_diagnostic_context")
            elif not diagnostic_artifacts_enabled:
                result["diagnostic_artifacts"] = diagnostic_artifacts_unavailable
            elif self.artifacts is not None:
                result["artifact_id"] = self.artifacts.put(full, tenant, "command")
            result["stdout"] = stdout[: self.inline_chars // 2]
            result["stderr"] = stderr[-self.inline_chars // 2:]
            result["output_truncated"] = True
        else:
            result["output_truncated"] = False
        return result

    def stats(self) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            active = [
                self._public_active(dict(v, age_ms=max(0, int((now - float(v.get("started_at", now))) * 1000))))
                for v in self._active_commands.values()
            ]
            blocked_by_reason = dict(sorted(self._blocked_by_reason.items(), key=lambda kv: (-kv[1], kv[0]))[:12])
        return {
            "enabled": self.enabled, "hits": self.hits, "misses": self.misses, "cancelled": self.cancelled,
            "coalesced_waiters": self.coalesced, "coalesced_wait_timeouts": self.coalesced_timeouts, "executed": self.executed,
            "blocked": self.blocked, "blocked_by_reason": blocked_by_reason,
            "suppressed": self.suppressed, "suppression_cache": self.suppression_cache.stats(),
            "active_count": len(active), "active": active[:24],
            "success_cache": self.success_cache.stats(), "failure_cache": self.failure_cache.stats(),
        }
