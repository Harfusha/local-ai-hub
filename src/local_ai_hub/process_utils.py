from __future__ import annotations

import ctypes
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
import time
import uuid
from typing import Any, Sequence


_LOW_PRIORITY_VALUES = {"idle", "below_normal", "normal"}
_POST_TERMINATION_DRAIN_SECONDS = 0.5


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


def terminate_tree(
    pid: int, *, process_group: int | None = None, grace_seconds: float = 5.0
) -> bool:
    if pid <= 0:
        return True
    if os.name == "nt":
        try:
            # Send CTRL_BREAK_EVENT first so process groups can run cleanup handlers.
            # Only send to a process group (positive pid); fall through on any error.
            try:
                os.kill(pid, signal.CTRL_BREAK_EVENT)
                deadline = time.monotonic() + max(0.5, min(grace_seconds, 5.0))
                while time.monotonic() < deadline:
                    if not pid_alive(pid):
                        return True
                    time.sleep(0.05)
            except (OSError, NotImplementedError):
                pass
            # Fall back to force-kill the whole process tree.
            cp = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=max(2.0, grace_seconds), check=False,
                **hidden_run_kwargs(),
            )
            return cp.returncode in {0, 128}
        except Exception:
            return not pid_alive(pid)
    group_id = pid if process_group in (None, 0) else int(process_group)

    def group_alive() -> bool:
        try:
            os.killpg(group_id, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return pid_alive(pid)

    try:
        # Runtime children are started in their own sessions. Prefer the group, then
        # fall back to the process itself for older/recovered installations.
        try:
            os.killpg(group_id, signal.SIGTERM)
        except OSError:
            os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + max(0.1, grace_seconds)
        while time.monotonic() < deadline:
            if not group_alive():
                return True
            time.sleep(0.05)
        try:
            os.killpg(group_id, signal.SIGKILL)
        except OSError:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        return not group_alive()
    except OSError:
        return True


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
            return True
        terminate_job_object(job_handle)
        if close_job_object(job_handle):
            process._local_ai_job_handle = None
            return True
    return False


def run_hidden(argv: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
    opts = dict(kwargs)
    text = bool(opts.get("text", False))
    for key, value in hidden_run_kwargs(text=text, new_group=True).items():
        opts.setdefault(key, value)
    timeout = opts.pop("timeout", 60.0)
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

    job_handle = None
    if os.name == "nt":
        required_flags = windows_creationflags(new_group=True)
        job_handle = create_job_object_kill_on_close()
        if not job_handle:
            raise OSError("Unable to create a kill-on-close Windows Job Object")
        opts["creationflags"] = (
            int(opts.get("creationflags", 0)) | required_flags | 0x00000004
        )  # CREATE_SUSPENDED prevents child creation before job assignment.
    else:
        # Keep explicit session ownership, but isolate the group unless the caller
        # selected one so timeout cleanup can still terminate this child's descendants.
        if "start_new_session" not in opts and "process_group" not in opts:
            opts["start_new_session"] = True
        elif opts.get("start_new_session") is False and "process_group" not in opts:
            opts["process_group"] = 0

    command = [str(x) for x in argv]
    process: subprocess.Popen[Any] | None = None
    try:
        process = subprocess.Popen(command, **opts)
        if job_handle:
            process._local_ai_job_handle = job_handle
            if not assign_process_to_job(job_handle, process.pid):
                raise OSError("Unable to assign suspended process to Windows Job Object")
            if not _resume_suspended_process(process):
                raise OSError("Unable to resume suspended Windows process")
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
    try:
        stdout, stderr = process.communicate(input=input_data, timeout=timeout)
    except subprocess.TimeoutExpired as timeout_error:
        process_group = None
        if os.name != "nt":
            requested_group = opts.get("process_group")
            if requested_group is not None:
                process_group = process.pid if int(requested_group) == 0 else int(requested_group)
            elif opts.get("start_new_session"):
                process_group = process.pid
        stdout, stderr = _terminate_and_drain(process, process_group=process_group)
        raise subprocess.TimeoutExpired(
            command,
            timeout,
            output=stdout if stdout is not None else timeout_error.output,
            stderr=stderr if stderr is not None else timeout_error.stderr,
        ) from None
    except BaseException:
        _terminate_and_drain(process)
        raise

    returncode = process.wait()
    if job_handle and not _release_process_job(process):
        _terminate_and_drain(process)
        if getattr(process, "_local_ai_job_handle", None):
            raise OSError("Unable to close Windows Job Object after process completion")
    completed = subprocess.CompletedProcess(command, returncode, stdout, stderr)
    if check and returncode:
        raise subprocess.CalledProcessError(returncode, command, stdout, stderr)
    return completed


def _terminate_and_drain(
    process: subprocess.Popen[Any], *, process_group: int | None = None
) -> tuple[Any, Any]:
    cleanup_kwargs = {"process_group": process_group} if process_group is not None else {}
    job_handle = getattr(process, "_local_ai_job_handle", None)
    if job_handle:
        if not _release_process_job(process):
            try:
                terminate_tree(process.pid, **cleanup_kwargs)
            except Exception:
                pass
    else:
        try:
            terminate_tree(process.pid, **cleanup_kwargs)
        except Exception:
            pass
    try:
        if process.poll() is None:
            process.kill()
    except OSError:
        pass

    try:
        return process.communicate(timeout=_POST_TERMINATION_DRAIN_SECONDS)
    except subprocess.TimeoutExpired as drain_error:
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
        try:
            process.kill()
        except OSError:
            pass
        try:
            process.wait(timeout=_POST_TERMINATION_DRAIN_SECONDS)
        except (OSError, subprocess.TimeoutExpired):
            pass
        return drain_error.output, drain_error.stderr
    except Exception:
        try:
            process.kill()
        except OSError:
            pass
        try:
            process.wait(timeout=_POST_TERMINATION_DRAIN_SECONDS)
        except (OSError, subprocess.TimeoutExpired):
            pass
        return None, None


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
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
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






def create_git_worktree(
    repo_root: str | Path,
    branch_name: str | None = None,
    worktree_path: str | Path | None = None,
    base_commit: str = "HEAD",
) -> dict[str, Any]:
    """Create an isolated temporary Git worktree for safe agent modifications."""
    repo = Path(repo_root).expanduser().resolve(strict=False)
    if not (repo / ".git").exists():
        return {"success": False, "error": f"not a git repository: {repo}"}
    if not shutil.which("git"):
        return {"success": False, "error": "git executable not found in PATH"}

    import uuid
    lease_id = f"wt_{uuid.uuid4().hex[:8]}"
    branch = branch_name or f"lease/{lease_id}"
    if not worktree_path:
        import tempfile
        target_dir = Path(tempfile.gettempdir()) / f"lah_wt_{lease_id}"
    else:
        target_dir = Path(worktree_path).resolve(strict=False)

    cmd = ["git", "-C", str(repo), "worktree", "add", "-b", branch, str(target_dir), base_commit]
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=30, **hidden_run_kwargs())
        if completed.returncode != 0:
            return {
                "success": False,
                "error": completed.stderr.strip() or "failed to create git worktree",
                "exit_code": completed.returncode,
            }
        return {
            "success": True,
            "lease_id": lease_id,
            "worktree_path": str(target_dir),
            "branch": branch,
            "base_commit": base_commit,
            "repo_root": str(repo),
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def remove_git_worktree(
    repo_root: str | Path,
    worktree_path: str | Path,
    delete_branch: bool = True,
    branch_name: str | None = None,
) -> dict[str, Any]:
    """Remove a previously leased Git worktree and optionally prune its branch."""
    repo = Path(repo_root).expanduser().resolve(strict=False)
    target = Path(worktree_path).resolve(strict=False)
    if not shutil.which("git"):
        return {"success": False, "error": "git executable not found"}

    try:
        cmd_rm = ["git", "-C", str(repo), "worktree", "remove", "--force", str(target)]
        subprocess.run(cmd_rm, capture_output=True, text=True, check=False, timeout=30, **hidden_run_kwargs())

        cmd_prune = ["git", "-C", str(repo), "worktree", "prune"]
        subprocess.run(cmd_prune, capture_output=True, text=True, check=False, timeout=10, **hidden_run_kwargs())

        if target.exists():
            try:
                shutil.rmtree(target, ignore_errors=True)
            except Exception:
                pass

        branch_deleted = False
        if delete_branch and branch_name:
            cmd_branch = ["git", "-C", str(repo), "branch", "-D", branch_name]
            proc_b = subprocess.run(cmd_branch, capture_output=True, text=True, check=False, timeout=10, **hidden_run_kwargs())
            branch_deleted = (proc_b.returncode == 0)

        return {
            "success": True,
            "worktree_removed": True,
            "branch_deleted": branch_deleted,
            "repo_root": str(repo),
            "worktree_path": str(target),
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def list_git_worktrees(repo_root: str | Path) -> dict[str, Any]:
    """Enumerate active Git worktrees and metadata."""
    repo = Path(repo_root).expanduser().resolve(strict=False)
    if not shutil.which("git"):
        return {"success": False, "error": "git executable not found"}
    try:
        proc = subprocess.run(
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
        proc = subprocess.run(
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
