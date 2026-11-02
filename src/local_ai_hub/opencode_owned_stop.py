"""Experimental exact-process and whole-job control for a host-owned job."""
from __future__ import annotations

import ntpath
import os
import threading

from .process_utils import (_windows_process_identity_from_handle, terminate_job_object,
                            wait_job_object_empty, windows_job_contains_process)


def is_direct_owned_child(job: int, parent: dict, child: dict) -> bool:
    """Observe live job membership and parentage; this does not authorize a stop.

    Windows parent IDs can be spoofed and parentage is momentary. Callers must
    not use this result to authorize termination or any other mutation.
    """
    if os.name != "nt" or type(job) is not int or job <= 0:
        return False
    fields = {"pid", "executable", "creation_identity", "creation_identity_type"}
    for identity in (parent, child):
        if (not isinstance(identity, dict) or set(identity) != fields
                or type(identity["pid"]) is not int or not 1 <= identity["pid"] <= 0xFFFFFFFF
                or not isinstance(identity["executable"], str) or not ntpath.isabs(identity["executable"])
                or type(identity["creation_identity"]) is not int or identity["creation_identity"] <= 0
                or identity["creation_identity_type"] != "windows_creation_filetime_100ns"):
            return False
    if parent["pid"] == child["pid"] or parent["creation_identity"] > child["creation_identity"]:
        return False

    import ctypes
    from ctypes import wintypes

    class ProcessBasicInformation(ctypes.Structure):
        _fields_ = [("exit_status", ctypes.c_long), ("peb", ctypes.c_void_p),
                    ("affinity", ctypes.c_size_t), ("priority", ctypes.c_long),
                    ("pid", ctypes.c_size_t), ("parent_pid", ctypes.c_size_t)]

    try:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        ntdll = ctypes.WinDLL("ntdll")
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
        kernel.IsProcessInJob.restype = wintypes.BOOL
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        query = ntdll.NtQueryInformationProcess
        query.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG)]
        query.restype = ctypes.c_long
        handles = []
        try:
            for identity in (parent, child):
                handle = kernel.OpenProcess(0x1000 | 0x00100000, False, identity["pid"])
                if not handle:
                    return False
                handles.append(handle)
                member = wintypes.BOOL()
                if (_windows_process_identity_from_handle(identity["pid"], handle, kernel) != identity
                        or not kernel.IsProcessInJob(handle, job, ctypes.byref(member)) or not member.value
                        or kernel.WaitForSingleObject(handle, 0) != 0x102):
                    return False
            info, returned = ProcessBasicInformation(), wintypes.ULONG()
            if query(handles[1], 0, ctypes.byref(info), ctypes.sizeof(info), ctypes.byref(returned)) != 0:
                return False
            return (returned.value == ctypes.sizeof(info) and info.pid == child["pid"]
                    and info.parent_pid == parent["pid"]
                    and all(kernel.WaitForSingleObject(handle, 0) == 0x102 for handle in handles))
        finally:
            for handle in handles:
                kernel.CloseHandle(handle)
    except (AttributeError, OSError, ValueError):
        return False


class OwnedJobBinding:
    """Host-only, single-use binding to one suspended process and its job."""

    def __init__(self):
        self._lock = threading.Lock()
        self._state = "new"
        self._job = None
        self._root_pid = None

    def _bind(self, job: int, root_pid: int):
        if type(job) is not int or job <= 0 or type(root_pid) is not int or root_pid <= 0:
            raise ValueError("valid job and root process are required")
        with self._lock:
            if self._state != "new":
                raise RuntimeError("job binding cannot be reused")
            self._job, self._root_pid, self._state = job, root_pid, "bound"

    def _unbind(self):
        with self._lock:
            self._state = "closed"
            self._job = self._root_pid = None

    def stop(self, identity: dict) -> bool | None:
        """Stop an exact job member other than the launcher root; not a tree."""
        with self._lock:
            if self._state != "bound":
                raise RuntimeError("job binding is not active")
            if not isinstance(identity, dict) or identity.get("pid") == self._root_pid:
                return False
            return stop_owned_process(self._job, identity)

    def permits(self, identity: dict) -> bool:
        """Check a non-root target against this job without terminating it."""
        with self._lock:
            if self._state != "bound":
                raise RuntimeError("job binding is not active")
            if not isinstance(identity, dict) or type(identity.get("pid")) is not int or identity["pid"] == self._root_pid:
                return False
            return windows_job_contains_process(self._job, identity["pid"], identity)

    def cancel_job(self) -> bool:
        """Terminate the entire owned session; never describes a subtree stop."""
        with self._lock:
            if self._state != "bound":
                raise RuntimeError("job binding is not active")
            return bool(terminate_job_object(self._job)) and bool(wait_job_object_empty(self._job))


def stop_owned_process(job: int, identity: dict) -> bool | None:
    """Stop one exactly identified job member, retaining one process handle.

    False means no termination was attempted. None means termination was
    attempted but its outcome was not confirmed; callers must not retry blindly.
    True confirms only this process exited, not its descendants or the job.
    """
    if os.name != "nt" or type(job) is not int or job <= 0 or not isinstance(identity, dict):
        return False
    if set(identity) != {"pid", "executable", "creation_identity", "creation_identity_type"}:
        return False
    pid, path, created = identity["pid"], identity["executable"], identity["creation_identity"]
    if (type(pid) is not int or not 1 <= pid <= 0xFFFFFFFF or not isinstance(path, str)
            or not ntpath.isabs(path) or type(created) is not int or created <= 0
            or identity["creation_identity_type"] != "windows_creation_filetime_100ns"):
        return False

    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
    kernel.IsProcessInJob.restype = wintypes.BOOL
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.TerminateProcess.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000 | 0x0001 | 0x00100000, False, pid)
    if not handle:
        return False
    try:
        actual = _windows_process_identity_from_handle(pid, handle, kernel)
        if actual != identity:
            return False
        member = wintypes.BOOL()
        if not kernel.IsProcessInJob(handle, job, ctypes.byref(member)) or not member.value:
            return False
        if not kernel.TerminateProcess(handle, 1):
            return None
        return True if kernel.WaitForSingleObject(handle, 3000) == 0 else None
    finally:
        kernel.CloseHandle(handle)
