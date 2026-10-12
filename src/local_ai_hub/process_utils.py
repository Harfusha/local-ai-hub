from __future__ import annotations

import ctypes
import json
import ntpath
import os
import posixpath
import sys
import threading
from pathlib import Path, PureWindowsPath
import signal
import select
import shutil
import subprocess
import tempfile
import time
import uuid
import weakref
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


_LOW_PRIORITY_VALUES = {"idle", "below_normal", "normal"}
_POST_TERMINATION_DRAIN_SECONDS = 0.5
_WORKTREE_OWNERSHIP_FILE = "local-ai-hub-worktree-ownership.json"
_CANCEL_POLL_SECONDS = 0.1
_CANCEL_GRACE_SECONDS = 1.0


class ProcessCancelledError(subprocess.SubprocessError):
    """Raised after a cancelled child process tree is terminated and drained."""

    def __init__(self, cmd: Sequence[str], output: Any = None, stderr: Any = None):
        super().__init__("process cancelled")
        self.cmd = list(cmd)
        self.output = output
        self.stderr = stderr


class ProcessCleanupUnverifiedError(subprocess.SubprocessError):
    """Raised when cancellation cannot prove child-tree termination."""

    def __init__(
        self,
        cmd: Sequence[str],
        *,
        process: subprocess.Popen[Any],
        tree_termination_confirmed: bool,
        output: Any = None,
        stderr: Any = None,
    ):
        super().__init__("process cleanup could not be verified")
        self.cmd = list(cmd)
        self.process = process
        self.tree_termination_confirmed = bool(tree_termination_confirmed)
        self.output = output
        self.stderr = stderr


@dataclass(frozen=True)
class _CleanupOutcome:
    stdout: Any
    stderr: Any
    cleanup_confirmed: bool
    process: subprocess.Popen[Any]
    process_group: int | None


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", ctypes.c_uint32), ("dwHighDateTime", ctypes.c_uint32)]


class _DARWIN_BSDINFO(ctypes.Structure):
    _fields_ = [
        ("pbi_flags", ctypes.c_uint32),
        ("pbi_status", ctypes.c_uint32),
        ("pbi_xstatus", ctypes.c_uint32),
        ("pbi_pid", ctypes.c_uint32),
        ("pbi_ppid", ctypes.c_uint32),
        ("pbi_uid", ctypes.c_uint32),
        ("pbi_gid", ctypes.c_uint32),
        ("pbi_ruid", ctypes.c_uint32),
        ("pbi_rgid", ctypes.c_uint32),
        ("pbi_svuid", ctypes.c_uint32),
        ("pbi_svgid", ctypes.c_uint32),
        ("rfu_1", ctypes.c_uint32),
        ("pbi_comm", ctypes.c_char * 16),
        ("pbi_name", ctypes.c_char * 32),
        ("pbi_nfiles", ctypes.c_uint32),
        ("pbi_pgid", ctypes.c_uint32),
        ("pbi_pjobc", ctypes.c_uint32),
        ("e_tdev", ctypes.c_uint32),
        ("e_tpgid", ctypes.c_uint32),
        ("pbi_nice", ctypes.c_int32),
        ("pbi_start_tvsec", ctypes.c_uint64),
        ("pbi_start_tvusec", ctypes.c_uint64),
    ]


def _linux_process_starttime(pid: int) -> int:
    stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
    # comm is parenthesized but may itself contain spaces or closing parens.
    end_comm = stat.rfind(")")
    if end_comm < 0 or int(stat[: stat.find(" ")]) != pid:
        raise ValueError("invalid proc stat")
    fields = stat[end_comm + 1 :].split()  # starts at field 3 (state)
    if len(fields) <= 19:
        raise ValueError("incomplete proc stat")
    return int(fields[19])  # field 22: starttime, in clock ticks after boot


def _windows_process_identity_from_handle(pid: int, handle: Any, kernel32: Any) -> dict[str, Any] | None:
    from ctypes import wintypes

    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_FILETIME),
        ctypes.POINTER(_FILETIME),
        ctypes.POINTER(_FILETIME),
        ctypes.POINTER(_FILETIME),
    ]
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    creation = _FILETIME()
    exit_time = _FILETIME()
    kernel = _FILETIME()
    user = _FILETIME()
    if not kernel32.GetProcessTimes(
        handle,
        ctypes.byref(creation),
        ctypes.byref(exit_time),
        ctypes.byref(kernel),
        ctypes.byref(user),
    ):
        return None
    buffer = ctypes.create_unicode_buffer(32768)
    size = wintypes.DWORD(len(buffer))
    if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
        return None
    executable = ntpath.normcase(ntpath.normpath(buffer.value))
    if not executable:
        return None
    creation_identity = (int(creation.dwHighDateTime) << 32) | int(creation.dwLowDateTime)
    return {
        "pid": pid,
        "executable": executable,
        "creation_identity": creation_identity,
        "creation_identity_type": "windows_creation_filetime_100ns",
    }


def _windows_process_identity(pid: int) -> dict[str, Any] | None:
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        return _windows_process_identity_from_handle(pid, handle, kernel32)
    finally:
        kernel32.CloseHandle(handle)


def _darwin_process_identity(pid: int) -> dict[str, Any] | None:
    """Read Darwin start time and executable through bounded libproc calls."""
    try:
        libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        proc_pidinfo = libproc.proc_pidinfo
        proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
        proc_pidinfo.restype = ctypes.c_int
        proc_pidpath = libproc.proc_pidpath
        proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
        proc_pidpath.restype = ctypes.c_int

        def snapshot() -> dict[str, Any] | None:
            info = _DARWIN_BSDINFO()
            size = ctypes.sizeof(info)
            read = proc_pidinfo(pid, 3, 0, ctypes.byref(info), size)  # PROC_PIDTBSDINFO
            if read != size or int(info.pbi_pid) != pid:
                return None
            path_buffer = ctypes.create_string_buffer(4096)  # PROC_PIDPATHINFO_MAXSIZE
            path_length = proc_pidpath(pid, path_buffer, len(path_buffer))
            if path_length <= 0 or path_length >= len(path_buffer):
                return None
            executable = os.fsdecode(path_buffer.value)
            command = bytes(info.pbi_comm).split(b"\0", 1)[0].decode("utf-8", "replace")
            if not executable.startswith("/") or not command:
                return None
            return {
                "pid": pid,
                "executable": posixpath.normpath(executable),
                "command": command,
                "creation_identity": int(info.pbi_start_tvsec) * 1_000_000 + int(info.pbi_start_tvusec),
                "creation_identity_type": "darwin_proc_bsdinfo_start_time_usec",
            }

        before = snapshot()
        after = snapshot()
        return before if before is not None and before == after else None
    except Exception:
        return None


def process_identity(pid: int) -> dict[str, Any] | None:
    """Return metadata-only PID identity, or None when it cannot be proven."""
    if isinstance(pid, bool) or not isinstance(pid, int) or not 0 < pid <= 0xFFFFFFFF:
        return None
    try:
        if os.name == "nt":
            return _windows_process_identity(pid)
        if sys.platform == "darwin":
            return _darwin_process_identity(pid)
        if sys.platform != "linux":
            return None

        starttime_before = _linux_process_starttime(pid)
        executable = os.readlink(f"/proc/{pid}/exe")
        starttime_after = _linux_process_starttime(pid)
        if starttime_before != starttime_after or not executable.startswith("/"):
            return None
        return {
            "pid": pid,
            "executable": posixpath.normpath(executable),
            "creation_identity": starttime_before,
            "creation_identity_type": "linux_proc_starttime_ticks",
        }
    except (OSError, ValueError, TypeError, OverflowError, AttributeError):
        return None


def process_parent_pid(pid: int | None = None) -> int | None:
    """Return the direct parent PID, using the Windows process table on Windows.

    CPython's os.getppid() can report the console ancestor for a hidden
    process launched in a new process group, rather than its direct creator.
    """
    target_pid = os.getpid() if pid is None else pid
    if isinstance(target_pid, bool) or not isinstance(target_pid, int) or target_pid <= 0:
        return None
    if os.name != "nt":
        return os.getppid() if target_pid == os.getpid() else None

    try:
        from ctypes import wintypes

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", wintypes.LONG),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        kernel32.Process32FirstW.restype = wintypes.BOOL
        kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        kernel32.Process32NextW.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
        snapshot_value = snapshot if isinstance(snapshot, int) else snapshot.value
        if not snapshot_value or snapshot_value == ctypes.c_void_p(-1).value:
            return None
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(entry)
            found = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            while found:
                if int(entry.th32ProcessID) == target_pid:
                    parent_pid = int(entry.th32ParentProcessID)
                    return parent_pid if parent_pid > 0 else None
                entry.dwSize = ctypes.sizeof(entry)
                found = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
            return None
        finally:
            kernel32.CloseHandle(snapshot)
    except Exception:
        return None


def process_owner_record(pid: int, state_dir: str | Path, role: str) -> dict[str, Any] | None:
    """Bind process identity to one Local AI Hub state directory and role."""
    identity = process_identity(pid)
    if not isinstance(identity, dict):
        return None
    try:
        resolved_state = str(Path(state_dir).expanduser().resolve())
        owner_role = str(role).strip().lower()
        executable = str(identity.get("executable", ""))
        command = identity.get("command")
        creation_identity = identity.get("creation_identity")
        identity_type = str(identity.get("creation_identity_type", ""))
        if (
            int(identity.get("pid", 0)) != int(pid)
            or not executable
            or creation_identity is None
            or not identity_type
            or not owner_role
            or (command is not None and not str(command))
        ):
            return None
        record = {
            "pid": int(pid),
            "executable": executable,
            "creation_identity": creation_identity,
            "creation_identity_type": identity_type,
            "state_dir": resolved_state,
            "role": owner_role,
        }
        if command is not None:
            record["command"] = str(command)
        return record
    except (OSError, TypeError, ValueError, OverflowError):
        return None


def process_owner_state(
    owner: Any, state_dir: str | Path, role: str
) -> str:
    """Return owned, stale, or unknown; only owned identity may be terminated."""
    if not isinstance(owner, dict):
        return "unknown"
    try:
        pid = int(owner.get("pid", 0))
        expected_state = os.path.normcase(
            os.path.normpath(str(Path(state_dir).expanduser().resolve()))
        )
        recorded_state = os.path.normcase(
            os.path.normpath(str(owner.get("state_dir", "")))
        )
        if (
            pid <= 0
            or expected_state != recorded_state
            or str(owner.get("role", "")).strip().lower() != str(role).strip().lower()
        ):
            return "unknown"
        current = process_identity(pid)
        if current is None:
            return "stale" if not pid_alive(pid) else "unknown"
        if int(current.get("pid", 0)) != pid:
            return "unknown"
        if str(current.get("creation_identity_type", "")) != str(
            owner.get("creation_identity_type", "")
        ):
            return "unknown"
        if str(current.get("creation_identity")) != str(owner.get("creation_identity")):
            return "stale"
        actual_executable = os.path.normcase(
            os.path.normpath(str(current.get("executable", "")))
        )
        recorded_executable = os.path.normcase(
            os.path.normpath(str(owner.get("executable", "")))
        )
        if not actual_executable or actual_executable != recorded_executable:
            return "unknown"
        if "command" in owner and str(current.get("command", "")) != str(owner["command"]):
            return "unknown"
        return "owned"
    except (OSError, TypeError, ValueError, OverflowError):
        return "unknown"


def open_pidfd(pid: int) -> int | None:
    """Open Linux process handle; return None when kernel support is unavailable."""
    if sys.platform != "linux" or not callable(getattr(os, "pidfd_open", None)):
        return None
    try:
        return os.pidfd_open(int(pid), 0)
    except (OSError, TypeError, ValueError):
        return None


def close_pidfd(pidfd: int | None) -> None:
    if pidfd is None:
        return
    try:
        os.close(pidfd)
    except OSError:
        pass


def _owner_identity_matches(owner: dict[str, Any], identity: dict[str, Any]) -> bool:
    try:
        actual_path = str(identity.get("executable", ""))
        recorded_path = str(owner.get("executable", ""))
        path_module = ntpath if os.name == "nt" else posixpath
        if (
            int(identity.get("pid", 0)) != int(owner.get("pid", 0))
            or str(identity.get("creation_identity_type", "")) != str(owner.get("creation_identity_type", ""))
            or str(identity.get("creation_identity")) != str(owner.get("creation_identity"))
            or path_module.normcase(path_module.normpath(actual_path))
            != path_module.normcase(path_module.normpath(recorded_path))
        ):
            return False
        return "command" not in owner or str(identity.get("command", "")) == str(owner["command"])
    except (TypeError, ValueError, OverflowError):
        return False


def _wait_pidfd(pidfd: int, timeout: float) -> bool:
    try:
        poller = select.poll()
        poller.register(pidfd, select.POLLIN)
        return bool(poller.poll(max(0, int(float(timeout) * 1000))))
    except (OSError, ValueError, TypeError):
        return False


def terminate_process_handle(
    process: subprocess.Popen[Any], pidfd: int | None, *, grace_seconds: float = 5.0
) -> bool:
    """Terminate a child only through its retained platform process handle."""
    if process.poll() is not None:
        return True
    if os.name == "nt":
        try:
            process.terminate()  # Popen uses its retained Windows process HANDLE.
            process.wait(timeout=max(0.1, grace_seconds))
            return True
        except subprocess.TimeoutExpired:
            try:
                process.kill()  # Same retained HANDLE; never resolves PID again.
                process.wait(timeout=1.0)
                return True
            except (OSError, subprocess.TimeoutExpired):
                return False
        except OSError:
            return process.poll() is not None
    if sys.platform == "linux" and pidfd is not None and callable(
        getattr(signal, "pidfd_send_signal", None)
    ):
        try:
            signal.pidfd_send_signal(pidfd, signal.SIGTERM)
        except ProcessLookupError:
            return True
        except OSError:
            return False
        try:
            process.wait(timeout=max(0.1, grace_seconds))
            return True
        except subprocess.TimeoutExpired:
            try:
                signal.pidfd_send_signal(pidfd, signal.SIGKILL)
                process.wait(timeout=1.0)
                return True
            except (OSError, subprocess.TimeoutExpired):
                return process.poll() is not None
    # Darwin has no public pidfd-equivalent signal handle; numeric PID kill is unsafe.
    return False


def terminate_owned_process(
    owner: Any,
    state_dir: str | Path,
    role: str,
    *,
    grace_seconds: float = 5.0,
) -> bool:
    """Terminate verified external owner using a retained OS handle, never a PID signal."""
    if not isinstance(owner, dict):
        return False
    state = process_owner_state(owner, state_dir, role)
    if state == "stale":
        return True
    if state != "owned":
        return False
    pid = int(owner["pid"])

    if os.name == "nt":
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.TerminateProcess.restype = wintypes.BOOL
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        rights = 0x0001 | 0x1000 | 0x00100000  # terminate, query limited, synchronize
        handle = kernel32.OpenProcess(rights, False, pid)
        if not handle:
            return False
        try:
            identity = _windows_process_identity_from_handle(pid, handle, kernel32)
            if not identity or not _owner_identity_matches(owner, identity):
                return False
            if not kernel32.TerminateProcess(handle, 1):
                return False
            wait_ms = max(100, min(30000, int(grace_seconds * 1000)))
            return kernel32.WaitForSingleObject(handle, wait_ms) == 0
        finally:
            kernel32.CloseHandle(handle)

    if sys.platform != "linux" or not callable(getattr(signal, "pidfd_send_signal", None)):
        return False
    pidfd = open_pidfd(pid)
    if pidfd is None:
        return False
    try:
        # Check identity again after opening pidfd. Signals then target this handle,
        # so PID reuse after the check cannot redirect termination.
        current = process_identity(pid)
        if not current or not _owner_identity_matches(owner, current):
            return False
        signal.pidfd_send_signal(pidfd, signal.SIGTERM)
        if _wait_pidfd(pidfd, grace_seconds):
            return True
        signal.pidfd_send_signal(pidfd, signal.SIGKILL)
        return _wait_pidfd(pidfd, 1.0)
    except ProcessLookupError:
        return True
    except OSError:
        return False
    finally:
        close_pidfd(pidfd)


def _normalise_priority(priority: str | None) -> str | None:
    value = str(priority or "").strip().lower().replace("-", "_")
    return value if value in _LOW_PRIORITY_VALUES else None


def set_current_thread_priority(priority: str | None) -> bool:
    """Best-effort priority for background worker thread, never raises."""
    value = _normalise_priority(priority)
    if value in {None, "normal"}:
        return True
    try:
        if os.name == "nt":
            import ctypes
            thread = ctypes.windll.kernel32.OpenThread(0x0020 | 0x0040, False, threading.get_native_id())
            if not thread:
                return False
            try:
                level = -15 if value == "idle" else -2
                return bool(ctypes.windll.kernel32.SetThreadPriority(thread, level))
            finally:
                ctypes.windll.kernel32.CloseHandle(thread)
        nice = 19 if value == "idle" else 10
        # On Linux (NPTL), PRIO_PROCESS with a thread ID sets per-thread priority.
        # On other POSIX systems this may silently affect the whole process instead.
        # The broad except below handles any failure gracefully.
        os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), nice)
        return True
    except (AttributeError, OSError, TypeError, ValueError):
        return False


def set_process_priority(pid: int, priority: str | None) -> bool:
    """Best-effort priority for a background child process, never raises."""
    value = _normalise_priority(priority)
    if value in {None, "normal"}:
        return True
    try:
        if os.name == "nt":
            import ctypes
            handle = ctypes.windll.kernel32.OpenProcess(0x0200, False, int(pid))
            if not handle:
                return False
            try:
                process_class = 0x40 if value == "idle" else 0x4000
                return bool(ctypes.windll.kernel32.SetPriorityClass(handle, process_class))
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        nice = 19 if value == "idle" else 10
        os.setpriority(os.PRIO_PROCESS, int(pid), nice)
        return True
    except (AttributeError, OSError, TypeError, ValueError):
        return False


def windows_creationflags(*, detached: bool = False, new_group: bool = False) -> int:
    if os.name != "nt":
        return 0
    # Always enforce CREATE_NO_WINDOW on Windows.
    # Note: On Windows 10/11 with Windows Terminal default handler, DETACHED_PROCESS
    # (0x00000008) causes Windows Terminal to spawn a visible window/tab.
    # We use CREATE_NEW_PROCESS_GROUP (0x00000200) instead, which provides clean process
    # isolation and signal detachment without triggering console window creation.
    flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
    if detached or new_group:
        flags |= int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200))
    return flags


def hidden_run_kwargs(*, text: bool = False, detached: bool = False, new_group: bool = False) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if os.name == "nt":
        kwargs["creationflags"] = windows_creationflags(detached=detached, new_group=new_group)
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0  # SW_HIDE
        kwargs["startupinfo"] = startupinfo
    if text:
        # Never inherit the Windows ANSI code page for captured tool output. A single
        # invalid byte used to crash subprocess reader threads and strand callers.
        kwargs.update({"text": True, "encoding": "utf-8", "errors": "replace"})
    return kwargs


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes
            # SYNCHRONIZE is sufficient for a non-blocking wait on the process object.
            # Merely opening a handle is not enough: exited processes can remain
            # handleable until their final handle is closed.
            synchronize = 0x00100000
            wait_timeout = 0x00000102
            handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, int(pid))
            if not handle:
                return False
            try:
                return int(ctypes.windll.kernel32.WaitForSingleObject(handle, 0)) == wait_timeout
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:
            return False

    # On Linux, kill(pid, 0) succeeds for zombies even though they can no longer
    # execute work. Treat Z/X states as dead so shutdown loops do not burn their
    # entire grace interval waiting for a process that only needs to be reaped.
    if sys_platform_linux():
        try:
            stat_text = Path(f"/proc/{int(pid)}/stat").read_text(encoding="utf-8", errors="replace")
            close_paren = stat_text.rfind(")")
            if close_paren >= 0:
                rest = stat_text[close_paren + 1 :].strip().split()
                if rest and rest[0] in {"Z", "X"}:
                    return False
        except OSError:
            pass
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        # EPERM means the process exists but belongs to another user/session.
        return True
    except OSError:
        return False


def sys_platform_linux() -> bool:
    # Kept tiny and dependency-free so process liveness remains safe during
    # interpreter shutdown and in minimal bootstrap environments.
    import sys
    return sys.platform.startswith("linux")


def process_executable(pid: int) -> str | None:
    if pid <= 0:
        return None
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
            if not handle:
                return None
            try:
                size = wintypes.DWORD(32768)
                buf = ctypes.create_unicode_buffer(size.value)
                if ctypes.windll.kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                    return buf.value
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:
            return None
        return None
    try:
        return os.readlink(f"/proc/{int(pid)}/exe")
    except OSError:
        return None


def _terminate_tree_unlocked(
    pid: int,
    *,
    process_group: int | None = None,
    expected_identity: Mapping[str, Any] | None = None,
    grace_seconds: float = 5.0,
    process_handle: subprocess.Popen[Any] | None = None,
) -> bool:
    if pid <= 0:
        return True
    if os.name == "nt":
        if process_handle is None or getattr(process_handle, "pid", None) != pid:
            return False
        job_handle = getattr(process_handle, "_local_ai_job_handle", None)
        if job_handle:
            return _release_process_job(process_handle)
        # A Popen handle safely targets its owned process, but does not prove
        # ownership of descendants. Never replace it with CTRL_BREAK/taskkill
        # against a numeric PID that may already have been recycled.
        try:
            if process_handle.poll() is None:
                process_handle.kill()
                process_handle.wait(timeout=max(0.1, min(grace_seconds, 5.0)))
        except (OSError, subprocess.TimeoutExpired):
            return False
        except Exception:
            return False
        return False
    # A process group is the caller's explicit tree-ownership capability. Never
    # fall back to the leader PID: it may have exited and been reused while the
    # group still contains descendants.
    if process_group is None or isinstance(process_group, bool):
        return False
    try:
        group_id = int(process_group)
    except (TypeError, ValueError, OverflowError):
        return False
    if group_id <= 0:
        return False

    if (
        not isinstance(expected_identity, Mapping)
        or isinstance(expected_identity.get("pid"), bool)
        or expected_identity.get("pid") != pid
        or expected_identity.get("creation_identity") is None
    ):
        return False

    def leader_still_owned() -> bool:
        try:
            return (
                process_identity(pid) == expected_identity
                and os.getpgid(pid) == group_id
            )
        except (AttributeError, OSError, TypeError, ValueError):
            return False

    if not leader_still_owned():
        return False

    try:
        os.killpg(group_id, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except OSError:
        return False

    deadline = time.monotonic() + max(0.5, min(grace_seconds, 5.0))
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(0.05, remaining))

    # Presence alone does not prove this is still the original group: a PGID
    # can be reused while waiting. Escalate only while its original leader
    # still has the identity captured immediately after spawn.
    if not leader_still_owned():
        return False
    try:
        os.killpg(group_id, 0)
    except ProcessLookupError:
        return True
    except OSError:
        return False

    try:
        os.killpg(group_id, signal.SIGKILL)
    except ProcessLookupError:
        return True
    except OSError:
        return False

    try:
        os.killpg(group_id, 0)
    except ProcessLookupError:
        return True
    except OSError:
        return False
    return False


def terminate_tree(
    pid: int,
    *,
    process_group: int | None = None,
    expected_identity: Mapping[str, Any] | None = None,
    grace_seconds: float = 5.0,
    process_handle: subprocess.Popen[Any] | None = None,
) -> bool:
    if process_handle is not None:
        if expected_identity is None:
            expected_identity = getattr(process_handle, "_local_ai_process_identity", None)
        if process_group is None:
            process_group = getattr(process_handle, "_local_ai_process_group", None)
    if os.name == "nt" or process_group is None or pid <= 0:
        return _terminate_tree_unlocked(
            pid,
            process_group=process_group,
            expected_identity=expected_identity,
            grace_seconds=grace_seconds,
            process_handle=process_handle,
        )

    # Keep the Popen child unreaped while killpg uses its numeric PGID. If a
    # concurrent poll/wait reaps the leader, the PGID can be recycled between
    # the identity check and the group signal. Missing guard means fail closed.
    if process_handle is None or getattr(process_handle, "pid", None) != pid:
        return False
    wait_lock = getattr(process_handle, "_waitpid_lock", None)
    if wait_lock is None:
        return False
    with wait_lock:
        if getattr(process_handle, "returncode", None) is not None:
            return False
        return _terminate_tree_unlocked(
            pid,
            process_group=process_group,
            expected_identity=expected_identity,
            grace_seconds=grace_seconds,
        )


_default_terminate_tree = terminate_tree


def _resume_suspended_process(process: subprocess.Popen[Any]) -> bool:
    """Resume suspended Windows process thread after Job Object assignment."""
    if os.name != "nt":
        return True
    try:
        import ctypes
        from ctypes import wintypes

        class THREADENTRY32(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ThreadID", wintypes.DWORD),
                ("th32OwnerProcessID", wintypes.DWORD),
                ("tpBasePri", wintypes.LONG),
                ("tpDeltaPri", wintypes.LONG),
                ("dwFlags", wintypes.DWORD),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(THREADENTRY32)]
        kernel32.Thread32First.restype = wintypes.BOOL
        kernel32.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(THREADENTRY32)]
        kernel32.Thread32Next.restype = wintypes.BOOL
        kernel32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenThread.restype = wintypes.HANDLE
        kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
        kernel32.ResumeThread.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        snapshot = kernel32.CreateToolhelp32Snapshot(0x00000004, 0)
        snapshot_value = snapshot if isinstance(snapshot, int) else snapshot.value
        if not snapshot_value or snapshot_value == ctypes.c_void_p(-1).value:
            return False
        try:
            entry = THREADENTRY32()
            entry.dwSize = ctypes.sizeof(entry)
            found = kernel32.Thread32First(snapshot, ctypes.byref(entry))
            while found:
                if int(entry.th32OwnerProcessID) == int(process.pid):
                    thread_handle = kernel32.OpenThread(
                        0x0002, False, int(entry.th32ThreadID)
                    )  # THREAD_SUSPEND_RESUME
                    if not thread_handle:
                        return False
                    try:
                        return int(kernel32.ResumeThread(thread_handle)) == 1
                    finally:
                        kernel32.CloseHandle(thread_handle)
                entry.dwSize = ctypes.sizeof(entry)
                found = kernel32.Thread32Next(snapshot, ctypes.byref(entry))
            return False
        finally:
            kernel32.CloseHandle(snapshot)
    except Exception:
        return False


def _release_process_job(process: subprocess.Popen[Any]) -> bool:
    """Close the owned kill-on-close Job Object, killing any remaining children."""
    job_handle = getattr(process, "_local_ai_job_handle", None)
    if not job_handle:
        return True
    for _ in range(2):
        if close_job_object(job_handle):
            process._local_ai_job_handle = None
            finalizer = getattr(process, "_local_ai_job_finalizer", None)
            if finalizer is not None and finalizer.alive:
                finalizer.detach()
            return True
        terminate_job_object(job_handle)
        if close_job_object(job_handle):
            process._local_ai_job_handle = None
            finalizer = getattr(process, "_local_ai_job_finalizer", None)
            if finalizer is not None and finalizer.alive:
                finalizer.detach()
            return True
    return False


def popen_managed(argv: Sequence[str], *, job_name: str | None = None, **kwargs: Any) -> subprocess.Popen[Any]:
    """Start a hidden child with owned process-tree cleanup on Windows."""
    opts = dict(kwargs)
    text = bool(opts.get("text", False))
    for key, value in hidden_run_kwargs(text=text, new_group=True).items():
        opts.setdefault(key, value)

    job_handle = None
    if os.name == "nt":
        required_flags = windows_creationflags(new_group=True)
        job_handle = (
            create_sandboxed_job_object(job_name=job_name)
            if job_name else create_job_object_kill_on_close()
        )
        if not job_handle:
            raise OSError("Unable to create a kill-on-close Windows Job Object")
        # Keep the child suspended until Job Object ownership is established.
        opts["creationflags"] = int(opts.get("creationflags", 0)) | required_flags | 0x00000004
    else:
        if "start_new_session" not in opts and "process_group" not in opts:
            opts["start_new_session"] = True
        elif opts.get("start_new_session") is False and "process_group" not in opts:
            opts["process_group"] = 0

    process: subprocess.Popen[Any] | None = None
    try:
        process = subprocess.Popen([str(value) for value in argv], **opts)
        if os.name == "nt":
            process._local_ai_job_handle = job_handle
            process._local_ai_job_finalizer = weakref.finalize(
                process, close_job_object, job_handle
            )
            if not assign_process_to_job(job_handle, process.pid):
                raise OSError("Unable to assign suspended process to Windows Job Object")
            if not _resume_suspended_process(process):
                raise OSError("Unable to resume suspended Windows process")
        else:
            process._local_ai_process_identity = process_identity(process.pid)
            requested_group = opts.get("process_group")
            if requested_group is not None:
                process._local_ai_process_group = (
                    process.pid if int(requested_group) == 0 else int(requested_group)
                )
            elif opts.get("start_new_session"):
                process._local_ai_process_group = process.pid
        return process
    except BaseException:
        if process is not None:
            try:
                process.kill()
            except OSError:
                pass
            try:
                process.wait(timeout=_POST_TERMINATION_DRAIN_SECONDS)
            except (OSError, subprocess.TimeoutExpired):
                pass
            _release_process_job(process)
        elif job_handle:
            close_job_object(job_handle)
        raise


def run_hidden(argv: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
    opts = dict(kwargs)
    timeout = opts.pop("timeout", 60.0)
    cancel_event = opts.pop("cancel_event", None)
    cancel_grace_seconds = float(opts.pop("cancel_grace_seconds", _CANCEL_GRACE_SECONDS))
    check = bool(opts.pop("check", False))
    input_data = opts.pop("input", None)
    capture_output = bool(opts.pop("capture_output", False))
    if input_data is not None:
        if opts.get("stdin") is not None:
            raise ValueError("stdin and input arguments may not both be used.")
        opts["stdin"] = subprocess.PIPE
    if capture_output:
        if opts.get("stdout") is not None or opts.get("stderr") is not None:
            raise ValueError("stdout and stderr arguments may not be used with capture_output.")
        opts["stdout"] = subprocess.PIPE
        opts["stderr"] = subprocess.PIPE

    if os.name != "nt":
        # Keep group ownership visible to timeout/cancellation cleanup below.
        if "start_new_session" not in opts and "process_group" not in opts:
            opts["start_new_session"] = True
        elif opts.get("start_new_session") is False and "process_group" not in opts:
            opts["process_group"] = 0

    command = [str(x) for x in argv]
    if cancel_event is not None and cancel_event.is_set():
        raise ProcessCancelledError(command)
    process = popen_managed(command, **opts)
    try:
        if cancel_event is None:
            stdout, stderr = process.communicate(input=input_data, timeout=timeout)
        else:
            deadline = None if timeout is None else time.monotonic() + float(timeout)
            first_communicate = True
            while True:
                if cancel_event.is_set():
                    process_group = None
                    if os.name != "nt":
                        requested_group = opts.get("process_group")
                        if requested_group is not None:
                            process_group = process.pid if int(requested_group) == 0 else int(requested_group)
                        elif opts.get("start_new_session"):
                            process_group = process.pid
                    cleanup = _terminate_and_drain(
                        process,
                        process_group=process_group,
                        grace_seconds=cancel_grace_seconds,
                        require_tree_termination=True,
                    )
                    error = ProcessCancelledError(command, cleanup.stdout, cleanup.stderr)
                    _attach_cleanup_outcome(error, cleanup)
                    raise error
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise subprocess.TimeoutExpired(command, timeout)
                wait_for = _CANCEL_POLL_SECONDS if remaining is None else min(_CANCEL_POLL_SECONDS, remaining)
                try:
                    stdout, stderr = process.communicate(
                        input=input_data if first_communicate else None,
                        timeout=wait_for,
                    )
                    break
                except subprocess.TimeoutExpired:
                    first_communicate = False
                    continue
    except ProcessCancelledError:
        raise
    except ProcessCleanupUnverifiedError:
        raise
    except subprocess.TimeoutExpired as timeout_error:
        process_group = None
        if os.name != "nt":
            requested_group = opts.get("process_group")
            if requested_group is not None:
                process_group = process.pid if int(requested_group) == 0 else int(requested_group)
            elif opts.get("start_new_session"):
                process_group = process.pid
        cleanup = _terminate_and_drain(process, process_group=process_group)
        error = subprocess.TimeoutExpired(
            command,
            timeout,
            output=cleanup.stdout if cleanup.stdout is not None else timeout_error.output,
            stderr=cleanup.stderr if cleanup.stderr is not None else timeout_error.stderr,
        )
        _attach_cleanup_outcome(error, cleanup)
        raise error from None
    except BaseException as error:
        cleanup = _terminate_and_drain(process)
        _attach_cleanup_outcome(error, cleanup)
        raise

    returncode = process.wait()
    if getattr(process, "_local_ai_job_handle", None) and not _release_process_job(process):
        cleanup = _terminate_and_drain(process)
        if getattr(process, "_local_ai_job_handle", None):
            error = OSError("Unable to close Windows Job Object after process completion")
            _attach_cleanup_outcome(error, cleanup)
            raise error
    completed = subprocess.CompletedProcess(command, returncode, stdout, stderr)
    if check and returncode:
        raise subprocess.CalledProcessError(returncode, command, stdout, stderr)
    return completed


def _terminate_and_drain(
    process: subprocess.Popen[Any], *, process_group: int | None = None,
    grace_seconds: float | None = None,
    require_tree_termination: bool = False,
) -> _CleanupOutcome:
    def outcome(stdout: Any, stderr: Any) -> _CleanupOutcome:
        result = _CleanupOutcome(stdout, stderr, cleanup_confirmed, process, process_group)
        if require_tree_termination:
            try:
                leader_exited = process.poll() is not None
            except Exception:
                leader_exited = False
            if not cleanup_confirmed or not leader_exited:
                error = ProcessCleanupUnverifiedError(
                    getattr(process, "args", ()),
                    process=process,
                    tree_termination_confirmed=cleanup_confirmed,
                    output=stdout,
                    stderr=stderr,
                )
                _attach_cleanup_outcome(error, result)
                raise error
        return result

    cleanup_kwargs = {"process_group": process_group} if process_group is not None else {}
    expected_identity = getattr(process, "_local_ai_process_identity", None)
    if process_group is not None and expected_identity is not None:
        cleanup_kwargs["expected_identity"] = expected_identity
    if grace_seconds is not None:
        cleanup_kwargs["grace_seconds"] = grace_seconds
    job_handle = getattr(process, "_local_ai_job_handle", None)
    cleanup_confirmed = False
    if job_handle:
        cleanup_confirmed = _release_process_job(process)
        if not cleanup_confirmed:
            cleanup_confirmed = _request_tree_cleanup(process, cleanup_kwargs)
    else:
        cleanup_confirmed = _request_tree_cleanup(process, cleanup_kwargs)

    # Popen.kill uses a stable process HANDLE on Windows. On POSIX it signals the
    # numeric PID after a liveness check, so never use it when tree ownership was
    # not continuously held by a safe signal target.
    if os.name == "nt" and not cleanup_confirmed:
        try:
            if process.poll() is None:
                process.kill()
        except OSError:
            pass

    try:
        stdout, stderr = process.communicate(timeout=_POST_TERMINATION_DRAIN_SECONDS)
        return outcome(stdout, stderr)
    except subprocess.TimeoutExpired as drain_error:
        retry_confirmed = _request_tree_cleanup(process, cleanup_kwargs)
        cleanup_confirmed = cleanup_confirmed or retry_confirmed
        final_output = drain_error.output
        final_stderr = drain_error.stderr
        try:
            stdout, stderr = process.communicate(timeout=_POST_TERMINATION_DRAIN_SECONDS)
            return outcome(stdout, stderr)
        except subprocess.TimeoutExpired as final_drain_error:
            if final_drain_error.output is not None:
                final_output = final_drain_error.output
            if final_drain_error.stderr is not None:
                final_stderr = final_drain_error.stderr
        except Exception:
            pass
        if cleanup_confirmed:
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass
            if os.name == "nt":
                try:
                    process.kill()
                except OSError:
                    pass
            try:
                process.wait(timeout=_POST_TERMINATION_DRAIN_SECONDS)
            except (OSError, subprocess.TimeoutExpired):
                pass
        return outcome(final_output, final_stderr)
    except ProcessCleanupUnverifiedError:
        raise
    except Exception:
        if cleanup_confirmed:
            if os.name == "nt":
                try:
                    process.kill()
                except OSError:
                    pass
            try:
                process.wait(timeout=_POST_TERMINATION_DRAIN_SECONDS)
            except (OSError, subprocess.TimeoutExpired):
                pass
        return outcome(None, None)


def _request_tree_cleanup(
    process: subprocess.Popen[Any], cleanup_kwargs: dict[str, Any]
) -> bool:
    if os.name == "nt":
        # Keep cleanup on the continuously owned Job Object. Closing it never
        # authorizes a later taskkill against a potentially recycled numeric PID.
        if getattr(process, "_local_ai_job_handle", None):
            return _release_process_job(process)
        if cleanup_kwargs.get("process_group") is None and terminate_tree is _default_terminate_tree:
            return False
    try:
        return bool(terminate_tree(process.pid, process_handle=process, **cleanup_kwargs))
    except Exception:
        return False


def _attach_cleanup_outcome(error: BaseException, outcome: _CleanupOutcome) -> None:
    error.cleanup_confirmed = outcome.cleanup_confirmed
    error.cleanup_unconfirmed = not outcome.cleanup_confirmed
    if not outcome.cleanup_confirmed:
        error.cleanup_process = outcome.process
        error.cleanup_process_group = outcome.process_group


def _find_listening_pid_win32(port: int) -> int | None:
    if port <= 0:
        return None
    try:
        import ctypes
        import socket
        from ctypes import wintypes

        class MIB_TCPROW_OWNER_PID(ctypes.Structure):
            _fields_ = [
                ("dwState", wintypes.DWORD),
                ("dwLocalAddr", wintypes.DWORD),
                ("dwLocalPort", wintypes.DWORD),
                ("dwRemoteAddr", wintypes.DWORD),
                ("dwRemotePort", wintypes.DWORD),
                ("dwOwningPid", wintypes.DWORD),
            ]

        iphlpapi = ctypes.windll.iphlpapi
        # IPv4 (AF_INET = 2, TCP_TABLE_OWNER_PID_LISTENER = 3)
        size = wintypes.DWORD(0)
        iphlpapi.GetExtendedTcpTable(None, ctypes.byref(size), False, 2, 3, 0)
        if size.value > 0:
            buf = ctypes.create_string_buffer(size.value)
            if iphlpapi.GetExtendedTcpTable(buf, ctypes.byref(size), False, 2, 3, 0) == 0:
                num_entries = wintypes.DWORD.from_buffer_copy(buf[:4]).value
                row_size = ctypes.sizeof(MIB_TCPROW_OWNER_PID)
                offset = 4
                for _ in range(num_entries):
                    row = MIB_TCPROW_OWNER_PID.from_buffer_copy(buf[offset : offset + row_size])
                    offset += row_size
                    if socket.ntohs(row.dwLocalPort & 0xFFFF) == port:
                        return int(row.dwOwningPid)

        # IPv6 (AF_INET6 = 23, TCP_TABLE_OWNER_PID_LISTENER = 3)
        class MIB_TCP6ROW_OWNER_PID(ctypes.Structure):
            _fields_ = [
                ("ucLocalAddr", wintypes.BYTE * 16),
                ("dwLocalScopeId", wintypes.DWORD),
                ("dwLocalPort", wintypes.DWORD),
                ("ucRemoteAddr", wintypes.BYTE * 16),
                ("dwRemoteScopeId", wintypes.DWORD),
                ("dwRemotePort", wintypes.DWORD),
                ("dwState", wintypes.DWORD),
                ("dwOwningPid", wintypes.DWORD),
            ]

        size6 = wintypes.DWORD(0)
        iphlpapi.GetExtendedTcpTable(None, ctypes.byref(size6), False, 23, 3, 0)
        if size6.value > 0:
            buf6 = ctypes.create_string_buffer(size6.value)
            if iphlpapi.GetExtendedTcpTable(buf6, ctypes.byref(size6), False, 23, 3, 0) == 0:
                num_entries = wintypes.DWORD.from_buffer_copy(buf6[:4]).value
                row_size = ctypes.sizeof(MIB_TCP6ROW_OWNER_PID)
                offset = 4
                for _ in range(num_entries):
                    row = MIB_TCP6ROW_OWNER_PID.from_buffer_copy(buf6[offset : offset + row_size])
                    offset += row_size
                    if socket.ntohs(row.dwLocalPort & 0xFFFF) == port:
                        return int(row.dwOwningPid)
    except Exception:
        pass
    return None


def find_listening_pid(port: int) -> int | None:
    if port <= 0:
        return None
    if os.name == "nt":
        pid = _find_listening_pid_win32(port)
        if pid is not None:
            return pid
        try:
            cp = subprocess.run(
                ["netstat", "-ano", "-p", "tcp"],
                stdin=subprocess.DEVNULL,
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3.0, check=False,
                **hidden_run_kwargs(),
            )
            for line in (cp.stdout or "").splitlines():
                parts = line.strip().split()
                if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[3].upper() == "LISTENING":
                    local_addr = parts[1]
                    port_str = local_addr.rsplit(":", 1)[-1]
                    if port_str.isdigit() and int(port_str) == int(port):
                        try:
                            return int(parts[4])
                        except ValueError:
                            pass
        except Exception:
            return None
        return None
    else:
        # Prefer lsof because its terse PID output is stable on macOS and common
        # Linux distributions. Fall back to ss on Linux. Both probes are optional,
        # bounded, and failure simply means the caller cannot adopt/clean an orphan.
        lsof = shutil.which("lsof")
        if lsof:
            try:
                cp = subprocess.run(
                    [lsof, "-nP", f"-iTCP:{int(port)}", "-sTCP:LISTEN", "-t"],
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    text=True, encoding="utf-8", errors="replace", timeout=2.0, check=False,
                )
                for line in (cp.stdout or "").splitlines():
                    value = line.strip()
                    if value.isdigit():
                        return int(value)
            except Exception:
                pass
        ss = shutil.which("ss")
        if ss:
            try:
                cp = subprocess.run(
                    [ss, "-ltnp", f"sport = :{int(port)}"],
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    text=True, encoding="utf-8", errors="replace", timeout=2.0, check=False,
                )
                import re
                match = re.search(r"pid=(\d+)", cp.stdout or "")
                if match:
                    return int(match.group(1))
            except Exception:
                pass
    return None


def canonical_root(path: str | Path) -> str:
    """Return a fully resolved, canonical repository root path string.

    Resolves symlinks, relative segments, and user home directory.
    On Windows, Path.resolve() normalizes drive letter casing to the disk filesystem.
    """
    try:
        resolved = Path(path).expanduser().resolve()
    except Exception:
        resolved = Path(path).expanduser().absolute()
    return str(resolved)


def is_rooted_path(path: str | Path) -> bool:
    """Recognize absolute/rooted paths independent of the host platform.

    ``pathlib.Path`` intentionally follows host semantics, which means a Windows
    drive path looks relative on Linux/macOS. Protocol-facing validation needs to
    recognize both forms so cross-platform client payloads are never joined onto
    the current workspace by accident.
    """
    raw = str(path or "").strip()
    if not raw:
        return False
    if raw.startswith(("/", "\\")):
        return True
    if Path(raw).is_absolute():
        return True
    win = PureWindowsPath(raw)
    return bool(win.drive) or win.is_absolute()


def _job_kernel32() -> Any:
    """Use pointer-sized handles for the Windows Job Object APIs."""
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.windll.kernel32
    for name, args, result in (
        ("CreateJobObjectW", [ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
        ("SetInformationJobObject", [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
        ("OpenProcess", [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
        ("AssignProcessToJobObject", [wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
        ("TerminateJobObject", [wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
        ("ResumeThread", [wintypes.HANDLE], wintypes.DWORD),
        ("CloseHandle", [wintypes.HANDLE], wintypes.BOOL),
    ):
        fn = getattr(kernel32, name)
        fn.argtypes = args
        fn.restype = result
    return kernel32


def create_sandboxed_job_object(
    memory_limit_mb: int | None = None,
    kill_on_close: bool = True,
    cpu_rate_percent: int | None = None,
    *,
    job_name: str | None = None,
) -> Any | None:
    """Create a Windows Job Object with kill-on-close and optional memory limits.

    Returns the Job Object handle (or None if not Windows / unsupported).
    """
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = _job_kernel32()
        if job_name:
            kernel32.SetLastError(0)
        job = kernel32.CreateJobObjectW(None, job_name)
        if not job:
            return None
        if job_name and kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            kernel32.CloseHandle(job)
            return None

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_uint64),
                ("WriteOperationCount", ctypes.c_uint64),
                ("OtherOperationCount", ctypes.c_uint64),
                ("ReadTransferCount", ctypes.c_uint64),
                ("WriteTransferCount", ctypes.c_uint64),
                ("OtherTransferCount", ctypes.c_uint64),
            ]

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryLimit", ctypes.c_size_t),
                ("PeakJobMemoryLimit", ctypes.c_size_t),
            ]

        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        limit_flags = 0
        if kill_on_close:
            limit_flags |= 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        limit_flags |= 0x0400      # JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION

        if memory_limit_mb and memory_limit_mb > 0:
            limit_flags |= 0x0200  # JOB_OBJECT_LIMIT_JOB_MEMORY
            info.JobMemoryLimit = ctypes.c_size_t(int(memory_limit_mb) * 1024 * 1024)

        info.BasicLimitInformation.LimitFlags = limit_flags
        success = kernel32.SetInformationJobObject(
            job,
            9,  # JobObjectExtendedLimitInformation
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not success:
            kernel32.CloseHandle(job)
            return None
        if cpu_rate_percent is not None:
            class CPU_RATE_INFORMATION(ctypes.Structure):
                _fields_ = [("ControlFlags", wintypes.DWORD), ("CpuRate", wintypes.DWORD)]
            rate = CPU_RATE_INFORMATION(0x1 | 0x4, max(1, min(100, int(cpu_rate_percent))) * 100)
            if not kernel32.SetInformationJobObject(job, 15, ctypes.byref(rate), ctypes.sizeof(rate)):
                kernel32.CloseHandle(job)
                return None
        return job
    except Exception:
        return None






def _git_worktree_admin_dir(repo: Path, target: Path) -> Path | None:
    common_proc = run_hidden(
        ["git", "-C", str(repo), "rev-parse", "--git-common-dir"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
        **hidden_run_kwargs(),
    )
    admin_proc = run_hidden(
        ["git", "-C", str(target), "rev-parse", "--git-dir"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
        **hidden_run_kwargs(),
    )
    if common_proc.returncode != 0 or admin_proc.returncode != 0:
        return None
    common = Path(common_proc.stdout.strip())
    admin = Path(admin_proc.stdout.strip())
    if not common.is_absolute():
        common = repo / common
    if not admin.is_absolute():
        admin = target / admin
    common = common.resolve(strict=False)
    admin = admin.resolve(strict=False)
    try:
        admin.relative_to(common / "worktrees")
    except ValueError:
        return None
    return admin


def get_git_worktree_ownership(repo_root: str | Path, worktree_path: str | Path) -> dict[str, Any] | None:
    """Read ownership metadata stored outside a linked worktree's working files."""
    repo = Path(repo_root).expanduser().resolve(strict=False)
    target = Path(worktree_path).expanduser().resolve(strict=False)
    admin = _git_worktree_admin_dir(repo, target)
    if admin is None:
        return None
    marker = admin / _WORKTREE_OWNERSHIP_FILE
    if not marker.exists():
        fallback = admin / "local_ai_hub_worktree.json"
        if fallback.exists():
            marker = fallback
    try:
        import json

        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def create_git_worktree(
    repo_root: str | Path,
    branch_name: str | None = None,
    worktree_path: str | Path | None = None,
    base_commit: str = "HEAD",
    *,
    task_id: str = "",
    owner: str = "",
    created_at: float | None = None,
    ttl_seconds: float = 86400.0,
    expires_at: float | None = None,
) -> dict[str, Any]:
    """Create an isolated temporary Git worktree for safe agent modifications."""
    repo = Path(repo_root).expanduser().resolve(strict=False)
    if not (repo / ".git").exists():
        return {"success": False, "error": f"not a git repository: {repo}"}
    if not shutil.which("git"):
        return {"success": False, "error": "git executable not found in PATH"}

    import math
    import tempfile
    import uuid
    try:
        created_at_value = float(created_at) if created_at is not None else time.time()
        ttl_value = float(ttl_seconds)
        expires_at_value = float(expires_at) if expires_at is not None else None
        task_id_value = str(task_id)
        owner_value = str(owner)
    except Exception as exc:
        return {"success": False, "error": f"invalid worktree metadata: {exc}"}
    if (
        not math.isfinite(created_at_value)
        or not math.isfinite(ttl_value)
        or (expires_at_value is not None and not math.isfinite(expires_at_value))
    ):
        return {"success": False, "error": "invalid worktree metadata: values must be finite"}
    ttl_value = max(60.0, min(ttl_value, 30 * 24 * 60 * 60.0))
    lease_id = f"lease_{uuid.uuid4().hex[:12]}"
    worktree_id = f"worktree_{uuid.uuid4().hex[:12]}"
    branch = branch_name or f"lease/{lease_id}"
    temp_root = Path(tempfile.gettempdir()).resolve(strict=False)
    if not worktree_path:
        target_dir = temp_root / f"lah_wt_{worktree_id}"
    else:
        raw_target = Path(worktree_path).expanduser()
        if ".." in raw_target.parts:
            return {"success": False, "error": "worktree path traversal is not allowed"}
        target_dir = raw_target.resolve(strict=False)
    try:
        target_dir.relative_to(temp_root)
    except ValueError:
        return {"success": False, "error": "worktree path escapes the temporary root"}

    cmd = ["git", "-C", str(repo), "worktree", "add", "-b", branch, str(target_dir), base_commit]
    created_checkout = False
    try:
        completed = run_hidden(cmd, capture_output=True, text=True, check=False, timeout=30, **hidden_run_kwargs())
        if completed.returncode != 0:
            return {
                "success": False,
                "error": completed.stderr.strip() or "failed to create git worktree",
                "exit_code": completed.returncode,
            }
        created_checkout = True
        metadata_path = _worktree_ownership_path(target_dir)
        if metadata_path is None:
            raise RuntimeError("could not locate worktree administrative directory")
        metadata = {
            "schema_version": 1,
            "worktree_id": worktree_id,
            "task_id": task_id_value,
            "owner": owner_value,
            "repo_root": str(repo),
            "worktree_path": str(target_dir),
            "branch": branch,
            "created_at": created_at_value,
            "ttl_seconds": ttl_value,
            "expires_at": expires_at_value,
        }
        metadata_tmp = metadata_path.with_name(f".{metadata_path.name}.{uuid.uuid4().hex}.tmp")
        metadata_tmp.write_text(json.dumps(metadata, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        os.replace(metadata_tmp, metadata_path)
        return {
            "success": True,
            "lease_id": lease_id,
            "worktree_id": worktree_id,
            "worktree_path": str(target_dir),
            "branch": branch,
            "base_commit": base_commit,
            "repo_root": str(repo),
            "task_id": task_id_value,
            "owner": owner_value,
            "created_at": created_at_value,
            "ttl_seconds": ttl_value,
            "expires_at": expires_at_value,
        }
    except Exception as exc:
        if created_checkout:
            run_hidden(
                ["git", "-C", str(repo), "worktree", "remove", str(target_dir)],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
                **hidden_run_kwargs(),
            )
        return {"success": False, "error": str(exc)}


def _git_value(root: Path, *arguments: str, timeout: float = 15.0) -> str:
    try:
        result = run_hidden(
            ["git", "-C", str(root), *arguments],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            **hidden_run_kwargs(),
        )
    except Exception:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _worktree_ownership_path(worktree_path: str | Path) -> Path | None:
    git_dir = _git_value(Path(worktree_path), "rev-parse", "--absolute-git-dir")
    if not git_dir:
        return None
    return Path(git_dir).expanduser().resolve(strict=False) / _WORKTREE_OWNERSHIP_FILE


def remove_git_worktree(
    repo_root: str | Path,
    worktree_path: str | Path,
    delete_branch: bool = True,
    branch_name: str | None = None,
    *,
    worktree_id: str = "",
    expected_task_id: str = "",
    expected_owner: str = "",
    expected_created_at: float | None = None,
    expected_ttl_seconds: float | None = None,
    expected_expires_at: float | None = None,
) -> dict[str, Any]:
    """Remove only clean worktree whose persisted owner metadata matches caller."""
    repo = Path(repo_root).expanduser().resolve(strict=False)
    raw_target = Path(worktree_path).expanduser()
    if raw_target.is_symlink():
        return {"success": False, "error": "worktree path must not be a symlink"}
    target = raw_target.resolve(strict=False)
    if not shutil.which("git"):
        return {"success": False, "error": "git executable not found"}
    if not worktree_id.strip():
        return {"success": False, "error": "worktree ownership identifier is required"}
    try:
        temp_root = Path(tempfile.gettempdir()).resolve(strict=False)
        try:
            target.relative_to(temp_root)
        except ValueError:
            return {"success": False, "error": "worktree path escapes the temporary root"}
        if not target.is_dir() or not (repo / ".git").exists():
            return {"success": False, "error": "repository or worktree path is unavailable"}

        repo_common_raw = _git_value(repo, "rev-parse", "--git-common-dir")
        target_common_raw = _git_value(target, "rev-parse", "--git-common-dir")
        if not repo_common_raw or not target_common_raw:
            return {"success": False, "error": "repository worktree identity is unavailable"}
        repo_common = Path(repo_common_raw)
        target_common = Path(target_common_raw)
        if not repo_common.is_absolute():
            repo_common = repo / repo_common
        if not target_common.is_absolute():
            target_common = target / target_common
        if repo_common.resolve(strict=False) != target_common.resolve(strict=False):
            return {"success": False, "error": "worktree belongs to another repository"}

        top_level = _git_value(target, "rev-parse", "--show-toplevel")
        if not top_level or Path(top_level).resolve(strict=False) != target:
            return {"success": False, "error": "worktree path does not match checkout root"}
        listed = _git_value(repo, "worktree", "list", "--porcelain", timeout=20)
        listed_paths = {
            Path(line.removeprefix("worktree ")).resolve(strict=False)
            for line in listed.splitlines()
            if line.startswith("worktree ")
        }
        if target not in listed_paths:
            return {"success": False, "error": "checkout is not registered to this repository"}

        metadata_path = _worktree_ownership_path(target)
        if metadata_path is None or not metadata_path.is_file():
            return {"success": False, "error": "worktree ownership metadata is unavailable"}
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if not isinstance(metadata, dict):
            return {"success": False, "error": "worktree ownership metadata is invalid"}
        recorded_branch = str(metadata.get("branch", ""))
        current_branch = _git_value(target, "symbolic-ref", "--short", "HEAD")
        if (
            metadata.get("schema_version") != 1
            or str(metadata.get("worktree_id", "")) != worktree_id
            or Path(str(metadata.get("repo_root", ""))).resolve(strict=False) != repo
            or Path(str(metadata.get("worktree_path", ""))).resolve(strict=False) != target
            or not recorded_branch
            or recorded_branch != (branch_name or recorded_branch)
            or current_branch != recorded_branch
        ):
            return {"success": False, "error": "worktree ownership or branch metadata does not match"}
        if expected_task_id and str(metadata.get("task_id", "")) != expected_task_id:
            return {"success": False, "error": "worktree task ownership does not match"}
        if expected_owner and str(metadata.get("owner", "")) != expected_owner:
            return {"success": False, "error": "worktree owner metadata does not match"}

        try:
            created_at = float(metadata.get("created_at"))
            ttl_seconds = float(metadata.get("ttl_seconds"))
            expires_at_raw = metadata.get("expires_at")
            expires_at = float(expires_at_raw) if expires_at_raw is not None else None
        except (TypeError, ValueError):
            return {"success": False, "error": "worktree time metadata is invalid"}
        import math
        if (
            not math.isfinite(created_at)
            or not math.isfinite(ttl_seconds)
            or ttl_seconds < 60
            or ttl_seconds > 30 * 24 * 60 * 60
            or (expires_at is not None and (not math.isfinite(expires_at) or abs(expires_at - (created_at + ttl_seconds)) > max(1e-6, ttl_seconds * 1e-9)))
        ):
            return {"success": False, "error": "worktree time metadata is inconsistent"}
        for expected, actual in (
            (expected_created_at, created_at),
            (expected_ttl_seconds, ttl_seconds),
            (expected_expires_at, expires_at),
        ):
            if expected is not None and (actual is None or abs(float(expected) - float(actual)) > max(1e-6, ttl_seconds * 1e-9)):
                return {"success": False, "error": "worktree time metadata does not match task ownership"}

        status = run_hidden(
            ["git", "-C", str(target), "status", "--porcelain", "--untracked-files=all", "--ignored"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
            **hidden_run_kwargs(),
        )
        if status.returncode != 0 or status.stdout.strip():
            return {"success": False, "error": "worktree contains uncommitted or ignored changes"}

        removed = run_hidden(
            ["git", "-C", str(repo), "worktree", "remove", str(target)],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
            **hidden_run_kwargs(),
        )
        if removed.returncode != 0:
            return {"success": False, "error": removed.stderr.strip() or "Git refused to remove worktree"}
        branch_deleted = False
        if delete_branch:
            cmd_branch = ["git", "-C", str(repo), "branch", "-d", recorded_branch]
            proc_b = run_hidden(cmd_branch, capture_output=True, text=True, check=False, timeout=10, **hidden_run_kwargs())
            branch_deleted = (proc_b.returncode == 0)
        return {
            "success": True,
            "worktree_removed": not target.exists(),
            "branch_deleted": branch_deleted,
            "repo_root": str(repo),
            "worktree_path": str(target),
            "worktree_id": worktree_id,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}

def list_git_worktrees(repo_root: str | Path) -> dict[str, Any]:
    """Enumerate active Git worktrees and metadata."""
    repo = Path(repo_root).expanduser().resolve(strict=False)
    if not shutil.which("git"):
        return {"success": False, "error": "git executable not found"}
    try:
        proc = run_hidden(
            ["git", "-C", str(repo), "worktree", "list", "--porcelain"],
            capture_output=True, text=True, check=False, timeout=15, **hidden_run_kwargs()
        )
        if proc.returncode != 0:
            err_msg = proc.stderr.strip()
            if "not a git repository" in err_msg.lower():
                return {"success": True, "repo_root": str(repo), "worktrees": [], "count": 0, "is_git": False}
            return {"success": False, "error": err_msg or "git worktree list failed"}
        worktrees: list[dict[str, Any]] = []
        current: dict[str, Any] = {}
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line:
                if current.get("worktree"):
                    worktrees.append(current)
                current = {}
                continue
            if line.startswith("worktree "):
                current["worktree"] = line[len("worktree "):].strip()
            elif line.startswith("HEAD "):
                current["head"] = line[len("HEAD "):].strip()
            elif line.startswith("branch "):
                current["branch"] = line[len("branch "):].strip().replace("refs/heads/", "")
            elif line.startswith("bare"):
                current["bare"] = True
            elif line.startswith("locked"):
                current["locked"] = True
            elif line.startswith("prunable"):
                current["prunable"] = True
        if current.get("worktree"):
            worktrees.append(current)
        return {"success": True, "repo_root": str(repo), "worktrees": worktrees, "count": len(worktrees)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def prune_git_worktrees(repo_root: str | Path) -> dict[str, Any]:
    """Prune stale Git worktrees."""
    repo = Path(repo_root).expanduser().resolve(strict=False)
    if not shutil.which("git"):
        return {"success": False, "error": "git executable not found"}
    try:
        proc = run_hidden(
            ["git", "-C", str(repo), "worktree", "prune", "-v"],
            capture_output=True, text=True, check=False, timeout=15, **hidden_run_kwargs()
        )
        if proc.returncode != 0:
            err_msg = proc.stderr.strip()
            if "not a git repository" in err_msg.lower():
                return {"success": True, "repo_root": str(repo), "is_git": False, "output": "not a git repository"}
            return {"success": False, "repo_root": str(repo), "error": err_msg or "git worktree prune failed"}
        return {
            "success": True,
            "repo_root": str(repo),
            "output": proc.stdout.strip() or proc.stderr.strip() or "pruned successfully",
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}



def simulate_git_merge(
    repo_root: str | Path,
    source_branch: str,
    target_branch: str = "HEAD",
) -> dict[str, Any]:
    """Simulate a 3-way merge without touching the working tree or index via git merge-tree."""
    repo = Path(repo_root).expanduser().resolve(strict=False)
    if not shutil.which("git"):
        return {"success": False, "error": "git executable not found"}

    try:
        cmd = ["git", "-C", str(repo), "merge-tree", "--write-tree", target_branch, source_branch]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=30, **hidden_run_kwargs())

        clean = (proc.returncode == 0)
        output = proc.stdout.strip()
        conflicts: list[str] = []
        for line in output.splitlines():
            line_str = line.strip()
            if "conflict" in line_str.lower() or "auto-merging" in line_str.lower():
                conflicts.append(line_str)
        if proc.stderr:
            for line in proc.stderr.splitlines():
                if line.strip():
                    conflicts.append(line.strip())

        return {
            "success": True,
            "mergeable": clean,
            "exit_code": proc.returncode,
            "source_branch": source_branch,
            "target_branch": target_branch,
            "conflicts": conflicts,
            "conflict_count": len(conflicts) if not clean else 0,
            "output_preview": output[:500],
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def atomic_write_file(
    target_path: Path | str,
    content: str | bytes,
    encoding: str = "utf-8",
) -> Path:
    """Atomically write content to target_path using a sibling temporary file and os.replace."""
    target = Path(target_path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_name = f".tmp_{uuid.uuid4().hex[:10]}_{target.name}"
    temp_path = target.parent / temp_name
    try:
        if isinstance(content, bytes):
            with open(temp_path, "wb") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
        else:
            with open(temp_path, "w", encoding=encoding, errors="replace") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
        os.replace(temp_path, target)
        return target
    except Exception:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise


@contextmanager
def managed_process_lock(path: Path):
    """Try one kernel lock; never steal a lock based on a timestamp or PID."""
    handle = path.open("a+b")
    acquired = False
    try:
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except OSError as exc:
            import errno

            if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                raise
        yield acquired
    finally:
        handle.close()


def open_named_job_object(name: str) -> Any | None:
    """Open an existing job; distinguish absence from denied/unknown ownership."""
    if os.name != "nt":
        raise OSError("Named Windows jobs are unavailable")
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenJobObjectW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.OpenJobObjectW.restype = wintypes.HANDLE
    handle = kernel32.OpenJobObjectW(0x0008 | 0x0004 | 0x00100000, False, name)
    if handle:
        return int(handle)
    error = ctypes.get_last_error()
    if error == 2:  # ERROR_FILE_NOT_FOUND
        return None
    raise OSError(error, "Cannot establish named Job Object ownership")


def windows_job_contains_process(job_handle: Any, pid: int, owner: dict[str, Any]) -> bool:
    """Verify image, creation identity and job membership on one retained handle."""
    if os.name != "nt" or not job_handle:
        return False
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
    kernel32.IsProcessInJob.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(0x1000 | 0x00100000, False, pid)
    if not handle:
        return False
    try:
        identity = _windows_process_identity_from_handle(pid, handle, kernel32)
        if not isinstance(identity, dict) or not _owner_identity_matches(owner, identity):
            return False
        in_job = wintypes.BOOL()
        return bool(kernel32.IsProcessInJob(handle, job_handle, ctypes.byref(in_job)) and in_job.value)
    finally:
        kernel32.CloseHandle(handle)


def wait_job_object_empty(job_handle: Any, timeout_ms: int = 2500) -> bool:
    """Boundedly verify zero active processes, including runner descendants."""
    if os.name != "nt" or not job_handle:
        return False
    from ctypes import wintypes

    class Accounting(ctypes.Structure):
        _fields_ = [
            ("total_user", ctypes.c_int64), ("total_kernel", ctypes.c_int64),
            ("period_user", ctypes.c_int64), ("period_kernel", ctypes.c_int64),
            ("page_faults", wintypes.DWORD), ("total", wintypes.DWORD),
            ("active", wintypes.DWORD), ("terminated", wintypes.DWORD),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.QueryInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p,
    ]
    kernel32.QueryInformationJobObject.restype = wintypes.BOOL
    deadline = time.monotonic() + max(0, int(timeout_ms)) / 1000
    while True:
        accounting = Accounting()
        if not kernel32.QueryInformationJobObject(job_handle, 1, ctypes.byref(accounting), ctypes.sizeof(accounting), None):
            return False
        if accounting.active == 0:
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.05, remaining))


def create_job_object_kill_on_close() -> Any:
    """Create a Windows Job Object that terminates children on close."""
    return create_sandboxed_job_object(kill_on_close=True)


def assign_process_to_job(job_handle: Any, process_handle_or_pid: Any) -> bool:
    """Assign a Windows process to a Job Object. Accepts either process handle or PID."""
    if os.name != "nt" or not job_handle:
        return False
    try:
        kernel32 = _job_kernel32()
        if isinstance(process_handle_or_pid, int):
            h_proc = kernel32.OpenProcess(0x0100 | 0x0001, False, process_handle_or_pid)
            if not h_proc:
                return False
            try:
                return bool(kernel32.AssignProcessToJobObject(job_handle, h_proc))
            finally:
                kernel32.CloseHandle(h_proc)
        else:
            return bool(kernel32.AssignProcessToJobObject(job_handle, int(process_handle_or_pid)))
    except Exception:
        return False


def close_job_object(job_handle: Any) -> bool:
    """Close a Windows Job Object handle."""
    if os.name != "nt" or not job_handle:
        return False
    try:
        return bool(_job_kernel32().CloseHandle(job_handle))
    except Exception:
        return False


def terminate_job_object(job_handle: Any) -> bool:
    """Force-terminate all processes currently owned by a Windows Job Object."""
    if os.name != "nt" or not job_handle:
        return False
    try:
        return bool(_job_kernel32().TerminateJobObject(job_handle, 1))
    except Exception:
        return False
