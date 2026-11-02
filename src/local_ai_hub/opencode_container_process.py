"""Experimental no-console AppContainer process runner, without inherited handles."""
from __future__ import annotations

import os
import math
import subprocess
import time
from pathlib import Path

from .opencode_appcontainer import AppContainerProfile
from .opencode_owned_stop import OwnedJobBinding
from .opencode_pipe_service import PipeService
from .opencode_stop_service import StopService
from .process_utils import (assign_process_to_job, close_job_object, create_job_object_kill_on_close,
                            terminate_job_object, wait_job_object_empty)


def _wait_process(kernel, handle, timeout: int, services=()):
    """Keep long waits interruptible without relaxing the total deadline."""
    import ctypes

    deadline = time.monotonic() + timeout
    while True:
        for service in services:
            service.check_health()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("AppContainer process timed out")
        status = kernel.WaitForSingleObject(handle, min(250, max(1, math.ceil(remaining * 1000))))
        if status == 0:
            for service in services:
                service.check_health()
            return
        if status != 258:
            raise OSError(ctypes.get_last_error(), "AppContainer process wait failed")


def run_in_appcontainer(profile: AppContainerProfile, argv: list[str], *, cwd: Path,
                        env: dict[str, str], timeout: int, stdio: tuple[int, int, int] | None = None,
                        binding: OwnedJobBinding | None = None,
                        services: tuple[PipeService | StopService, ...] = ()) -> int:
    """Run one process without network capabilities, inside a retained owned job.

    Optional standard streams use an explicit inherited-handle allowlist. This
    low-level runner does not grant filesystem access or provide a console.
    It does not establish complete sandbox or launcher acceptance.
    """
    if os.name != "nt" or not isinstance(profile, AppContainerProfile):
        raise ValueError("an active Windows AppContainer profile is required")
    sid = profile.sid_pointer
    if (not isinstance(argv, list) or not argv or any(not isinstance(x, str) or "\0" in x for x in argv)
            or not Path(argv[0]).is_absolute() or not Path(argv[0]).is_file()):
        raise ValueError("an absolute executable and valid arguments are required")
    cwd = Path(cwd)
    if not cwd.is_absolute() or not cwd.is_dir():
        raise ValueError("an absolute existing working directory is required")
    if not isinstance(env, dict) or any(not isinstance(k, str) or not k or "=" in k or "\0" in k
                                        or not isinstance(v, str) or "\0" in v for k, v in env.items()):
        raise ValueError("invalid environment")
    if len({key.upper() for key in env}) != len(env):
        raise ValueError("duplicate environment names")
    if type(timeout) is not int or not 1 <= timeout <= 43_200:
        raise ValueError("invalid process timeout")
    if stdio is not None and (not isinstance(stdio, tuple) or len(stdio) != 3
                              or any(type(fd) is not int or fd < 0 for fd in stdio)):
        raise ValueError("stdio must contain three file descriptors")
    if binding is not None and type(binding) is not OwnedJobBinding:
        raise ValueError("invalid owned job binding")
    if not isinstance(services, tuple) or any(type(service) not in (PipeService, StopService) for service in services):
        raise ValueError("invalid sandbox service list")
    for service in services:
        service.check_health()

    import ctypes
    from ctypes import wintypes

    class StartupInfo(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("reserved", wintypes.LPWSTR), ("desktop", wintypes.LPWSTR),
                    ("title", wintypes.LPWSTR), ("x", wintypes.DWORD), ("y", wintypes.DWORD),
                    ("x_size", wintypes.DWORD), ("y_size", wintypes.DWORD), ("x_count", wintypes.DWORD),
                    ("y_count", wintypes.DWORD), ("fill", wintypes.DWORD), ("flags", wintypes.DWORD),
                    ("show", wintypes.WORD), ("reserved_size", wintypes.WORD), ("reserved2", wintypes.LPVOID),
                    ("stdin", wintypes.HANDLE), ("stdout", wintypes.HANDLE), ("stderr", wintypes.HANDLE)]

    class StartupInfoEx(ctypes.Structure):
        _fields_ = [("startup", StartupInfo), ("attributes", wintypes.LPVOID)]

    class ProcessInfo(ctypes.Structure):
        _fields_ = [("process", wintypes.HANDLE), ("thread", wintypes.HANDLE),
                    ("pid", wintypes.DWORD), ("tid", wintypes.DWORD)]

    class SecurityCapabilities(ctypes.Structure):
        _fields_ = [("sid", wintypes.LPVOID), ("capabilities", wintypes.LPVOID),
                    ("count", wintypes.DWORD), ("reserved", wintypes.DWORD)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.InitializeProcThreadAttributeList.argtypes = [wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_size_t)]
    kernel.InitializeProcThreadAttributeList.restype = wintypes.BOOL
    kernel.UpdateProcThreadAttribute.argtypes = [wintypes.LPVOID, wintypes.DWORD, ctypes.c_size_t, wintypes.LPVOID,
                                                 ctypes.c_size_t, wintypes.LPVOID, wintypes.LPVOID]
    kernel.UpdateProcThreadAttribute.restype = wintypes.BOOL
    kernel.DeleteProcThreadAttributeList.argtypes = [wintypes.LPVOID]
    kernel.CreateProcessW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.LPVOID, wintypes.LPVOID,
                                      wintypes.BOOL, wintypes.DWORD, wintypes.LPVOID, wintypes.LPCWSTR,
                                      ctypes.POINTER(StartupInfo), ctypes.POINTER(ProcessInfo)]
    kernel.CreateProcessW.restype = wintypes.BOOL
    kernel.ResumeThread.argtypes = [wintypes.HANDLE]
    kernel.ResumeThread.restype = wintypes.DWORD
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.TerminateProcess.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.DuplicateHandle.argtypes = [wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE,
                                       ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.DuplicateHandle.restype = wintypes.BOOL

    job = create_job_object_kill_on_close()
    if not job:
        raise OSError("cannot create owned process job")
    info = ProcessInfo()
    attributes_ready = False
    assigned = False
    bound = False
    duplicated = []
    try:
        if stdio is not None:
            import msvcrt
            for fd in stdio:
                try:
                    source = msvcrt.get_osfhandle(fd)
                except (OSError, ValueError) as exc:
                    raise ValueError("invalid stdio file descriptor") from exc
                target = wintypes.HANDLE()
                current = kernel.GetCurrentProcess()
                if not kernel.DuplicateHandle(current, source, current, ctypes.byref(target), 0, True, 2):
                    raise OSError(ctypes.get_last_error(), "cannot duplicate stdio handle")
                duplicated.append(target)
        size = ctypes.c_size_t()
        attribute_count = 2 if stdio is not None else 1
        kernel.InitializeProcThreadAttributeList(None, attribute_count, 0, ctypes.byref(size))
        if not size.value:
            raise OSError(ctypes.get_last_error(), "cannot size process attributes")
        attributes = ctypes.create_string_buffer(size.value)
        if not kernel.InitializeProcThreadAttributeList(attributes, attribute_count, 0, ctypes.byref(size)):
            raise OSError(ctypes.get_last_error(), "cannot initialize process attributes")
        attributes_ready = True
        capabilities = SecurityCapabilities(sid, None, 0, 0)
        if not kernel.UpdateProcThreadAttribute(attributes, 0, 0x20009, ctypes.byref(capabilities), ctypes.sizeof(capabilities), None, None):
            raise OSError(ctypes.get_last_error(), "cannot set AppContainer identity")
        if stdio is not None:
            handle_list = (wintypes.HANDLE * 3)(*(handle.value for handle in duplicated))
            if not kernel.UpdateProcThreadAttribute(attributes, 0, 0x20002, ctypes.byref(handle_list), ctypes.sizeof(handle_list), None, None):
                raise OSError(ctypes.get_last_error(), "cannot restrict inherited handles")
        startup = StartupInfoEx()
        startup.startup.cb = ctypes.sizeof(startup)
        startup.attributes = ctypes.cast(attributes, wintypes.LPVOID)
        if stdio is not None:
            startup.startup.flags = 0x100
            startup.startup.stdin, startup.startup.stdout, startup.startup.stderr = duplicated
        command = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
        environment = ctypes.create_unicode_buffer("\0".join(f"{k}={v}" for k, v in sorted(env.items(), key=lambda item: item[0].upper())) + "\0\0")
        flags = 0x00000004 | 0x00080000 | 0x00000400 | 0x08000000
        if not kernel.CreateProcessW(argv[0], command, None, None, stdio is not None, flags, environment, str(cwd),
                                     ctypes.byref(startup.startup), ctypes.byref(info)):
            raise OSError(ctypes.get_last_error(), "cannot create AppContainer process")
        duplicated = [handle for handle in duplicated if not kernel.CloseHandle(handle)]
        if duplicated:
            raise OSError("cannot close inherited stdio duplicates")
        assigned = assign_process_to_job(job, info.pid)
        if not assigned:
            raise OSError("cannot establish owned process execution")
        if binding is not None:
            binding._bind(job, info.pid)
            bound = True
        if kernel.ResumeThread(info.thread) == 0xFFFFFFFF:
            raise OSError("cannot establish owned process execution")
        _wait_process(kernel, info.process, timeout, services)
        code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(info.process, ctypes.byref(code)):
            raise OSError(ctypes.get_last_error(), "cannot read AppContainer process exit code")
        return code.value
    finally:
        clean = True
        if bound:
            binding._unbind()
        if info.process:
            if assigned:
                stopped = bool(terminate_job_object(job))
                empty = bool(wait_job_object_empty(job))
                clean = stopped and empty
            else:
                clean = bool(kernel.TerminateProcess(info.process, 1))
            clean = (kernel.WaitForSingleObject(info.process, 5000) == 0) and clean
            thread_closed = bool(kernel.CloseHandle(info.thread))
            process_closed = bool(kernel.CloseHandle(info.process))
            clean = clean and thread_closed and process_closed
        if attributes_ready:
            kernel.DeleteProcThreadAttributeList(attributes)
        for handle in duplicated:
            clean = bool(kernel.CloseHandle(handle)) and clean
        clean = bool(close_job_object(job)) and clean
        if not clean:
            raise RuntimeError("AppContainer process cleanup was not confirmed")
