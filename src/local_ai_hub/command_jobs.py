"""Windows Job Object management, process tracking, and process liveness helpers."""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Any

from .process_utils import (
    assign_process_to_job,
    close_job_object,
    create_job_object_kill_on_close,
    terminate_job_object,
)

__all__ = [
    "assign_process_to_job",
    "close_job_object",
    "create_job_object_kill_on_close",
    "create_named_daemon_job",
    "daemon_job_name",
    "duplicate_job_handle_into_process",
    "is_windows_process_alive",
    "open_named_daemon_job",
    "set_windows_job_kill_on_close",
    "stop_windows_job_process",
    "terminate_and_confirm_windows_job_empty",
    "terminate_job_object",
    "wait_windows_job_empty",
    "windows_job_contains_process",
    "windows_job_has_processes",
]


def is_windows_process_alive(pid: int) -> bool:
    """Return whether a Windows process with the specified PID is currently alive."""
    if (
        os.name != "nt"
        or not sys.platform.startswith("win")
        or isinstance(pid, bool)
        or not isinstance(pid, int)
        or pid <= 0
    ):
        return False
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD

        # SYNCHRONIZE (0x00100000) allows non-blocking wait.
        # An active process remains unsignaled (WAIT_TIMEOUT = 0x102).
        # A terminated process becomes signaled (WAIT_OBJECT_0 = 0).
        synchronize = 0x00100000
        query_limited_info = 0x1000
        wait_timeout = 0x00000102

        ctypes.set_last_error(0)
        handle = kernel32.OpenProcess(synchronize | query_limited_info, False, pid)
        if not handle:
            # ERROR_ACCESS_DENIED (5) indicates the process exists and is active.
            return ctypes.get_last_error() == 5
        try:
            return int(kernel32.WaitForSingleObject(handle, 0)) == wait_timeout
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return False


def daemon_job_name(daemon_id: str) -> str:
    """Format canonical named Windows Job Object path for a daemon."""
    return f"Local\\LocalAIHubDaemon-{daemon_id.removeprefix('dmn_')}"


def set_windows_job_kill_on_close(job_handle: int) -> bool:
    """Configure a Windows Job Object to terminate all member processes on handle close."""
    if os.name != "nt" or not job_handle:
        return False
    import ctypes
    from ctypes import wintypes

    class _IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
        )]

    class _BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimitInformation), ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryLimit", ctypes.c_size_t), ("PeakJobMemoryLimit", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
    ]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    info = _ExtendedLimitInformation()
    info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    return bool(kernel32.SetInformationJobObject(
        wintypes.HANDLE(job_handle), 9, ctypes.byref(info), ctypes.sizeof(info)
    ))


def create_named_daemon_job(daemon_id: str) -> int:
    """Create a persistent named Job Object, rejecting pre-existing names."""
    if os.name != "nt":
        raise OSError("named daemon Job Objects are Windows-only")
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_job = kernel32.CreateJobObjectW
    create_job.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    create_job.restype = wintypes.HANDLE
    ctypes.set_last_error(0)
    handle = create_job(None, daemon_job_name(daemon_id))
    if not handle:
        raise OSError(ctypes.get_last_error(), "unable to create named daemon Job Object")
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        close_job_object(int(handle))
        raise OSError("named daemon Job Object already exists")
    if not set_windows_job_kill_on_close(int(handle)):
        error = ctypes.get_last_error()
        close_job_object(int(handle))
        raise OSError(error, "unable to enable kill-on-close for named daemon Job Object")
    return int(handle)


def open_named_daemon_job(name: str) -> int | None:
    """Open an existing named Job Object with terminate, query, and synchronize rights."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    open_job = kernel32.OpenJobObjectW
    open_job.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    open_job.restype = wintypes.HANDLE
    handle = open_job(0x0008 | 0x0004 | 0x00100000, False, name)  # terminate, query, synchronize
    return int(handle) if handle else None


def duplicate_job_handle_into_process(job_handle: int, process: subprocess.Popen[Any] | Any) -> bool:
    """Keep a named Job Object open in its suspended daemon until that process exits."""
    pid = getattr(process, "pid", None)
    if os.name != "nt" or not job_handle or not isinstance(pid, int) or isinstance(pid, bool):
        return False
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.DuplicateHandle.argtypes = [
        wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.HANDLE),
        wintypes.DWORD, wintypes.BOOL, wintypes.DWORD,
    ]
    kernel32.DuplicateHandle.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    target = kernel32.OpenProcess(0x0040, False, pid)  # PROCESS_DUP_HANDLE
    if not target:
        return False
    try:
        remote_handle = wintypes.HANDLE()
        return bool(kernel32.DuplicateHandle(
            kernel32.GetCurrentProcess(), wintypes.HANDLE(job_handle), target,
            ctypes.byref(remote_handle), 0x00100000, False, 0,  # SYNCHRONIZE only; non-inheritable keeper
        ))
    finally:
        kernel32.CloseHandle(target)


def windows_job_contains_process(job_handle: int, pid: int, identity: dict[str, Any]) -> bool:
    """Bind PID identity and Job membership to one retained process handle."""
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes

    class _FileTime(ctypes.Structure):
        _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(_FileTime), ctypes.POINTER(_FileTime),
        ctypes.POINTER(_FileTime), ctypes.POINTER(_FileTime),
    ]
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
    kernel32.IsProcessInJob.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    process = kernel32.OpenProcess(0x1000 | 0x00100000, False, pid)
    if not process:
        return False
    try:
        creation, exited, kernel, user = (_FileTime() for _ in range(4))
        if not kernel32.GetProcessTimes(
            process, ctypes.byref(creation), ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user)
        ):
            return False
        creation_id = (int(creation.high) << 32) | int(creation.low)
        if identity.get("creation_identity") != creation_id or identity.get("pid") != pid:
            return False
        in_job = wintypes.BOOL()
        return bool(kernel32.IsProcessInJob(process, wintypes.HANDLE(job_handle), ctypes.byref(in_job)) and in_job.value)
    finally:
        kernel32.CloseHandle(process)


def windows_job_has_processes(job_handle: int) -> bool | None:
    """Check whether a Windows Job Object currently contains active processes."""
    if os.name != "nt" or not job_handle:
        return None
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    result = int(kernel32.WaitForSingleObject(wintypes.HANDLE(job_handle), 0))
    if result == 0x102:  # WAIT_TIMEOUT
        return True
    if result == 0:  # WAIT_OBJECT_0
        return False
    return None


def wait_windows_job_empty(job_handle: Any, timeout_ms: int = 2500) -> bool:
    """Wait until Windows signals that a daemon Job Object has no live processes."""
    if os.name != "nt" or not job_handle:
        return False
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    return int(kernel32.WaitForSingleObject(wintypes.HANDLE(job_handle), max(0, int(timeout_ms)))) == 0


def terminate_and_confirm_windows_job_empty(job_handle: Any, timeout_ms: int = 2500) -> bool:
    """Terminate a command job and confirm its process tree exited before success."""
    if not job_handle:
        return False
    try:
        terminate_job_object(job_handle)
    except Exception:
        pass
    try:
        return wait_windows_job_empty(job_handle, timeout_ms)
    except Exception:
        return False


def stop_windows_job_process(process: Any, job_handle: Any = None, timeout_ms: int = 2500) -> bool:
    """Terminate a Windows Job object, confirm processes exited, and close handle."""
    if job_handle is None and hasattr(process, "_local_ai_job_handle"):
        job_handle = getattr(process, "_local_ai_job_handle", None)
    if os.name != "nt" or not job_handle or isinstance(job_handle, bool):
        return False
    try:
        if not terminate_job_object(job_handle):
            return False
        if not wait_windows_job_empty(job_handle, timeout_ms=timeout_ms):
            return False
        if not close_job_object(job_handle):
            return False
        if hasattr(process, "_local_ai_job_handle"):
            process._local_ai_job_handle = None
        return True
    except Exception:
        return False
