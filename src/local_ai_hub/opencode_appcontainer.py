"""Fail-closed Windows AppContainer primitives for managed OpenCode sessions.

These primitives intentionally do not create a workspace snapshot or expose a
Hub endpoint. Callers must provide a disposable staged directory and an owned
kill-on-close Job Object before launching a child.
"""
from __future__ import annotations

import ctypes
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .process_utils import (
    close_job_object,
    create_job_object_kill_on_close,
    terminate_job_object,
    wait_job_object_empty,
)
from .opencode_workspace import (
    WorkspaceSnapshot,
    WorkspaceTransferResult,
    apply_workspace_changes,
    create_workspace_snapshot,
)


_ENVIRONMENT_KEYS = frozenset({
    "SYSTEMROOT", "WINDIR", "LOCALAPPDATA", "APPDATA", "TEMP", "TMP",
    "HOME", "USERPROFILE", "PATH", "PATHEXT", "COMSPEC",
    "OPENCODE_CONFIG", "OPENCODE_DISABLE_AUTOUPDATE", "OPENCODE_DISABLE_TELEMETRY",
    "OPENCODE_DISABLE_PROJECT_CONFIG", "OPENCODE_DISABLE_MODELS_FETCH",
    "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME", "TMPDIR",
})
_BRIDGE_ENVIRONMENT_KEYS = frozenset({
    "LOCAL_AI_PIPE_NAME", "LOCAL_AI_PIPE_SECRET", "LOCAL_AI_PIPE_PORT_FILE",
})
_PROFILE_NAME = re.compile(r"LAH-OC-[A-F0-9]{32}\Z")


def file_info_identity(info: Sequence[Any]) -> tuple[int, int, int]:
    """Return volume serial and file-index fields from Win32 file information."""
    if len(info) < 10:
        raise ValueError("Win32 file information tuple is incomplete")
    return int(info[4]), int(info[8]), int(info[9])


class AppContainerCleanupError(RuntimeError):
    """A native process or profile resource could not be safely released."""


def build_environment_block(
    environment: Mapping[str, str], *, bridge_client: bool = False
) -> tuple[ctypes.Array, ctypes.c_void_p]:
    """Build a sorted Unicode environment containing only explicitly allowed keys."""
    if not isinstance(environment, Mapping) or not environment:
        raise ValueError("an explicit non-empty environment is required")
    entries: list[tuple[str, str]] = []
    seen_keys: set[str] = set()
    for key, value in environment.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError("environment keys and values must be strings")
        allowed = _ENVIRONMENT_KEYS | (_BRIDGE_ENVIRONMENT_KEYS if bridge_client else frozenset())
        if key.upper() not in allowed:
            raise ValueError(f"environment key is not allowed: {key}")
        if key.upper() in seen_keys:
            raise ValueError(f"duplicate environment key: {key}")
        seen_keys.add(key.upper())
        if not key or "=" in key or "\x00" in key or "\x00" in value:
            raise ValueError("invalid process environment entry")
        entries.append((key, value))
    values = {key.upper(): value for key, value in entries}
    if bridge_client and (
        not re.fullmatch(r"\\\\\.\\pipe\\lah-opencode-[a-f0-9]{32}", values.get("LOCAL_AI_PIPE_NAME", ""))
        or not re.fullmatch(r"[a-f0-9]{64}", values.get("LOCAL_AI_PIPE_SECRET", ""))
        or not os.path.isabs(values.get("LOCAL_AI_PIPE_PORT_FILE", ""))
    ):
        raise ValueError("bridge process requires a session pipe, 256-bit secret, and absolute port-file path")
    text = "\0".join(f"{key}={value}" for key, value in sorted(entries, key=lambda row: row[0].casefold())) + "\0\0"
    buffer = ctypes.create_unicode_buffer(text, len(text))
    return buffer, ctypes.cast(buffer, ctypes.c_void_p)


@dataclass
class AppContainerProfile:
    """Disposable AppContainer profile whose deletion is explicit and checked."""

    name: str
    sid: int
    _closed: bool = False

    @classmethod
    def create(cls) -> "AppContainerProfile":
        if os.name != "nt" or not sys.platform.startswith("win"):
            raise OSError("AppContainer profiles are Windows-only")
        name = "LAH-OC-" + __import__("uuid").uuid4().hex.upper()
        userenv = ctypes.WinDLL("userenv", use_last_error=True)
        userenv.CreateAppContainerProfile.argtypes = [
            wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p,
            wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p),
        ]
        userenv.CreateAppContainerProfile.restype = ctypes.c_long
        sid = ctypes.c_void_p()
        hr = userenv.CreateAppContainerProfile(name, name, "Local AI Hub OpenCode session", None, 0, ctypes.byref(sid))
        if hr < 0 or not sid:
            raise OSError(f"CreateAppContainerProfile failed: HRESULT 0x{hr & 0xFFFFFFFF:08x}")
        return cls(name, int(sid.value))

    def close(self) -> None:
        if self._closed:
            return
        if not _PROFILE_NAME.fullmatch(self.name):
            raise AppContainerCleanupError("refusing to delete a non-managed AppContainer profile")
        userenv = ctypes.WinDLL("userenv", use_last_error=True)
        userenv.DeleteAppContainerProfile.argtypes = [wintypes.LPCWSTR]
        userenv.DeleteAppContainerProfile.restype = ctypes.c_long
        hr = 0
        for attempt in range(3):
            hr = userenv.DeleteAppContainerProfile(self.name)
            if hr >= 0:
                break
            if attempt < 2:
                # Windows documents the profile state as undetermined after failure
                # and directs callers to invoke DeleteAppContainerProfile again.
                time.sleep(0.05 * (attempt + 1))
        else:
            raise AppContainerCleanupError(f"DeleteAppContainerProfile failed: HRESULT 0x{hr & 0xFFFFFFFF:08x}")
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        advapi32.FreeSid.argtypes = [ctypes.c_void_p]
        advapi32.FreeSid.restype = ctypes.c_void_p
        advapi32.FreeSid(ctypes.c_void_p(self.sid))
        self._closed = True


def grant_staged_workspace_access(stage: Path, package_sid_string: str, *, retain_handle: bool = False):
    """Give only SYSTEM, the current owner, and package SID access to a staged tree.

    When ``retain_handle`` is set, return the reparse-checked directory handle
    so the session can detect replacement of the stage path before launch.
    """
    if os.name != "nt" or not sys.platform.startswith("win"):
        raise OSError("AppContainer ACLs are Windows-only")
    requested = Path(os.path.abspath(os.fspath(stage)))
    if requested == Path(requested.anchor):
        raise ValueError("stage must be an existing non-root directory")
    if not re.fullmatch(r"S-1-[0-9-]{5,}", package_sid_string, re.ASCII):
        raise ValueError("invalid package SID")
    import win32api
    import win32con
    import win32file
    import win32security

    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32security.TOKEN_QUERY)
    try:
        owner_sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    finally:
        win32api.CloseHandle(token)
    system_sid = win32security.CreateWellKnownSid(win32security.WinLocalSystemSid, None)
    package_sid = win32security.ConvertStringSidToSid(package_sid_string)
    acl = win32security.ACL()
    inheritance = win32security.OBJECT_INHERIT_ACE | win32security.CONTAINER_INHERIT_ACE
    for sid in (system_sid, owner_sid, package_sid):
        acl.AddAccessAllowedAceEx(win32security.ACL_REVISION_DS, inheritance, 0x1F01FF, sid)
    # Resolve ancestors, but open the final component itself with
    # OPEN_REPARSE_POINT. Path.resolve() here would silently follow a staged
    # junction and could grant the package SID access to its target.
    root = requested.parent.resolve(strict=True) / requested.name
    handle = win32file.CreateFile(
        str(root), win32con.WRITE_DAC | 0x80,  # FILE_READ_ATTRIBUTES
        win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
        None, win32con.OPEN_EXISTING,
        win32con.FILE_FLAG_BACKUP_SEMANTICS | 0x00200000,  # FILE_FLAG_OPEN_REPARSE_POINT
        None,
    )
    retained = False
    try:
        info = win32file.GetFileInformationByHandle(handle)
        attributes = int(info[0])
        if not attributes & 0x10 or attributes & 0x400:  # DIRECTORY, not REPARSE_POINT
            raise ValueError("stage must be a real directory, not a reparse point")
        win32security.SetNamedSecurityInfo(
            str(root), win32security.SE_FILE_OBJECT,
            win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
            None, None, acl, None,
        )
        if retain_handle:
            retained = True
            return root, handle
    finally:
        if not retained:
            win32api.CloseHandle(handle)


class _StartupInfo(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR), ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR), ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD), ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD), ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.c_ubyte)), ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE)]


class _StartupInfoEx(ctypes.Structure):
    _fields_ = [("StartupInfo", _StartupInfo), ("lpAttributeList", ctypes.c_void_p)]


class _SecurityCapabilities(ctypes.Structure):
    _fields_ = [("AppContainerSid", ctypes.c_void_p), ("Capabilities", ctypes.c_void_p),
        ("CapabilityCount", wintypes.DWORD), ("Reserved", wintypes.DWORD)]


class _ProcessInformation(ctypes.Structure):
    _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]


@dataclass
class SuspendedAppContainerProcess:
    """AppContainer child assigned to a kill-on-close job, not yet resumed."""

    process_handle: int
    thread_handle: int
    pid: int
    job_handle: int
    owns_job: bool = True
    _resumed: bool = False

    def resume(self) -> None:
        if self._resumed:
            raise RuntimeError("process already resumed")
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
        kernel32.ResumeThread.restype = wintypes.DWORD
        if kernel32.ResumeThread(wintypes.HANDLE(self.thread_handle)) == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())
        self._resumed = True

    def wait(self, timeout_ms: int = 20_000) -> int:
        if not self._resumed:
            raise RuntimeError("cannot wait for a process that has not been resumed")
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        result = kernel32.WaitForSingleObject(wintypes.HANDLE(self.process_handle), max(0, int(timeout_ms)))
        if result == 0x102:
            self.terminate()
            raise TimeoutError("AppContainer process exceeded its wait deadline")
        if result != 0:
            raise ctypes.WinError(ctypes.get_last_error())
        code = wintypes.DWORD()
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        if not kernel32.GetExitCodeProcess(wintypes.HANDLE(self.process_handle), ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(code.value)

    def terminate(self, exit_code: int = 125) -> None:
        _ = exit_code
        if not terminate_job_object(self.job_handle) or not wait_job_object_empty(self.job_handle, timeout_ms=5000):
            raise AppContainerCleanupError("could not confirm AppContainer job is empty")

    def close(self, *, require_empty: bool = True) -> None:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        if require_empty:
            if self.owns_job:
                empty = wait_job_object_empty(self.job_handle, timeout_ms=5000)
            else:
                empty = kernel32.WaitForSingleObject(wintypes.HANDLE(self.process_handle), 5000) == 0
            if not empty:
                raise AppContainerCleanupError("refusing to close live process or non-empty owned job")
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        errors = []
        for handle in (self.thread_handle, self.process_handle):
            if handle and not kernel32.CloseHandle(wintypes.HANDLE(handle)):
                errors.append(ctypes.get_last_error())
        if self.owns_job and self.job_handle and not close_job_object(self.job_handle):
            errors.append(ctypes.get_last_error())
        if errors:
            raise AppContainerCleanupError(f"native handle cleanup failed: {errors}")


def launch_suspended_appcontainer(
    application: str, arguments: Sequence[str], appcontainer_sid: int,
    environment: Mapping[str, str], *, cwd: str | None = None, bridge_client: bool = False,
    job_handle: int | None = None,
) -> SuspendedAppContainerProcess:
    """Create a no-capability AppContainer child suspended inside a kill-on-close job."""
    if os.name != "nt" or not sys.platform.startswith("win"):
        raise OSError("AppContainer process creation is Windows-only")
    if not os.path.isabs(application) or not os.path.isfile(application) or not appcontainer_sid:
        raise ValueError("verified absolute executable and AppContainer SID are required")
    environment_buffer, environment_pointer = build_environment_block(environment, bridge_client=bridge_client)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    attribute_list = None
    process = _ProcessInformation()
    owns_job = job_handle is None
    job = create_job_object_kill_on_close() if owns_job else job_handle
    if not job:
        raise OSError("could not create kill-on-close Job Object")
    try:
        required = ctypes.c_size_t(0)
        kernel32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(required))
        if ctypes.get_last_error() != 122:
            raise ctypes.WinError(ctypes.get_last_error())
        attribute_list = ctypes.create_string_buffer(required.value)
        if not kernel32.InitializeProcThreadAttributeList(attribute_list, 1, 0, ctypes.byref(required)):
            raise ctypes.WinError(ctypes.get_last_error())
        capabilities = _SecurityCapabilities(ctypes.c_void_p(appcontainer_sid), None, 0, 0)
        if not kernel32.UpdateProcThreadAttribute(attribute_list, 0, 0x00020009, ctypes.byref(capabilities),
                ctypes.sizeof(capabilities), None, None):
            raise ctypes.WinError(ctypes.get_last_error())
        startup = _StartupInfoEx()
        startup.StartupInfo.cb = ctypes.sizeof(startup)
        startup.StartupInfo.lpDesktop = r"WinSta0\Default"
        startup.lpAttributeList = ctypes.cast(attribute_list, ctypes.c_void_p)
        command_line = ctypes.create_unicode_buffer(subprocess.list2cmdline([application, *arguments]))
        kernel32.CreateProcessW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p,
            ctypes.c_void_p, wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
            ctypes.c_void_p, ctypes.POINTER(_ProcessInformation)]
        kernel32.CreateProcessW.restype = wintypes.BOOL
        flags = 0x00080000 | 0x00000400 | 0x00000004  # extended startup, Unicode env, suspended
        if not kernel32.CreateProcessW(application, command_line, None, None, False, flags,
                environment_pointer, cwd or os.path.dirname(application), ctypes.byref(startup), ctypes.byref(process)):
            raise ctypes.WinError(ctypes.get_last_error())
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        if not kernel32.AssignProcessToJobObject(wintypes.HANDLE(job), process.hProcess):
            raise ctypes.WinError(ctypes.get_last_error(), "could not assign suspended AppContainer process to kill-on-close job")
        result = SuspendedAppContainerProcess(int(process.hProcess), int(process.hThread),
            int(process.dwProcessId), int(job), owns_job)
        process.hProcess = None
        process.hThread = None
        job = 0
        return result
    except Exception:
        if process.hProcess:
            kernel32.TerminateProcess(process.hProcess, 125)
            kernel32.WaitForSingleObject(process.hProcess, 5000)
            kernel32.CloseHandle(process.hProcess)
        if process.hThread:
            kernel32.CloseHandle(process.hThread)
        if job and owns_job:
            close_job_object(job)
        raise
    finally:
        # Keep both buffers alive through CreateProcessW; all failures are fail-closed.
        _ = environment_buffer
        if attribute_list:
            kernel32.DeleteProcThreadAttributeList(attribute_list)


def _current_windows_session_id() -> int:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcessId.restype = wintypes.DWORD
    kernel32.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    kernel32.ProcessIdToSessionId.restype = wintypes.BOOL
    session_id = wintypes.DWORD()
    if not kernel32.ProcessIdToSessionId(kernel32.GetCurrentProcessId(), ctypes.byref(session_id)):
        raise ctypes.WinError(ctypes.get_last_error())
    return int(session_id.value)


class ManagedAppContainerProcessSession:
    """Own one AppContainer profile and its Job-fenced child lifecycle.

    The session creates its stage inside its private AppContainer profile path.
    Optional workspace snapshots copy files into that stage and transfer changes
    back only after successful process exit and a confirmed empty Job Object. It
    grants only that directory and never changes checkout ACLs. Pipe/listener and
    GPU ownership remain separate gates before this can launch OpenCode.
    """

    def __init__(self, profile: AppContainerProfile, stage: Path, package_sid: str,
                 stage_handle: Any, job_handle: int, windows_session_id: int,
                 workspace_snapshot: WorkspaceSnapshot | None = None) -> None:
        self.profile = profile
        self.stage = Path(stage)
        self.package_sid = package_sid
        self.stage_handle = stage_handle
        self.job_handle = job_handle
        self.windows_session_id = windows_session_id
        self.workspace_snapshot = workspace_snapshot
        self.workspace_owner_pid: int | None = None
        self.process_exit_codes: dict[int, int] = {}
        self.workspace_transfer_result: WorkspaceTransferResult | None = None
        self.workspace_finalized = False
        self.session_id = uuid.uuid4().hex
        self.secret = os.urandom(32)
        self.process: SuspendedAppContainerProcess | None = None
        self.processes: list[SuspendedAppContainerProcess] = []
        self.bridge_pid: int | None = None
        self.pipe_listener = None
        self.pipe_thread: threading.Thread | None = None
        self.pipe_error: BaseException | None = None
        self.state = "created"

    @classmethod
    def create(cls, project_root: str | os.PathLike[str] | None = None) -> "ManagedAppContainerProcessSession":
        profile = AppContainerProfile.create()
        sid_text = wintypes.LPWSTR()
        stage_handle = None
        job_handle = None
        workspace_snapshot = None
        try:
            advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
            advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
            advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
            if not advapi32.ConvertSidToStringSidW(ctypes.c_void_p(profile.sid), ctypes.byref(sid_text)):
                raise ctypes.WinError(ctypes.get_last_error())
            package_temp = Path(os.environ["LOCALAPPDATA"]) / "Packages" / profile.name / "AC" / "Temp"
            package_temp.mkdir(parents=True, exist_ok=True)
            stage = package_temp / ("workspace-" + uuid.uuid4().hex)
            stage.mkdir()
            stage_path, stage_handle = grant_staged_workspace_access(stage, sid_text.value, retain_handle=True)
            if project_root is not None:
                workspace_snapshot = create_workspace_snapshot(
                    project_root, stage_path, staging_handle=stage_handle
                )
            job_handle = create_job_object_kill_on_close()
            if not job_handle:
                raise OSError("could not create the session kill-on-close Job Object")
            return cls(
                profile, stage_path, sid_text.value, stage_handle, job_handle,
                _current_windows_session_id(), workspace_snapshot,
            )
        except Exception:
            if job_handle:
                close_job_object(job_handle)
            if stage_handle:
                import win32api
                win32api.CloseHandle(stage_handle)
            profile.close()
            raise
        finally:
            if sid_text:
                ctypes.windll.kernel32.LocalFree(ctypes.cast(sid_text, wintypes.HLOCAL))

    def launch(self, application: str, arguments: Sequence[str], environment: Mapping[str, str]) -> int:
        pid = self._launch(application, arguments, environment, bridge_client=False)
        self.workspace_owner_pid = pid
        return pid

    def launch_bridge(self, application: str, arguments: Sequence[str], environment: Mapping[str, str]) -> int:
        if self.pipe_listener is None:
            raise RuntimeError("pipe listener must be active before launching the bridge")
        if self.bridge_pid is not None:
            raise RuntimeError("session accepts one bridge process")
        if any(key.upper() in _BRIDGE_ENVIRONMENT_KEYS for key in environment):
            raise ValueError("bridge identity variables are supplied by the session")
        bridge_environment = dict(environment)
        bridge_environment["LOCAL_AI_PIPE_NAME"] = self.pipe_listener.pipe_name
        bridge_environment["LOCAL_AI_PIPE_SECRET"] = self.secret.hex()
        self.bridge_port_path = self.stage / ("bridge-" + self.session_id + ".port")
        bridge_environment["LOCAL_AI_PIPE_PORT_FILE"] = str(self.bridge_port_path)
        self.bridge_pid = self._launch(application, arguments, bridge_environment, bridge_client=True)
        return self.bridge_pid

    def wait_bridge_port(self, timeout_seconds: float = 10.0) -> int:
        if self.bridge_pid is None or not hasattr(self, "bridge_port_path"):
            raise RuntimeError("bridge process has not been launched")
        if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
                or not 0 < timeout_seconds <= 30):
            raise ValueError("bridge port timeout must be greater than 0 and at most 30 seconds")
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        deadline = time.monotonic() + float(timeout_seconds)
        child = next((item for item in self.processes if item.pid == self.bridge_pid), None)
        while time.monotonic() < deadline:
            if self.bridge_port_path.exists():
                raw = self.bridge_port_path.read_text(encoding="ascii").strip()
                if not raw.isascii() or not raw.isdecimal():
                    raise RuntimeError("bridge wrote an invalid listening port")
                port = int(raw)
                if not 1 <= port <= 65535:
                    raise RuntimeError("bridge listening port is outside the TCP range")
                return port
            if child is None or kernel32.WaitForSingleObject(wintypes.HANDLE(child.process_handle), 0) == 0:
                raise RuntimeError("bridge exited before publishing its listening port")
            time.sleep(0.05)
        raise TimeoutError("bridge did not publish a listening port before the deadline")

    def _launch(self, application: str, arguments: Sequence[str], environment: Mapping[str, str],
                *, bridge_client: bool) -> int:
        if self.state not in {"created", "running"} or len(self.processes) >= 2:
            raise RuntimeError("session accepts at most two children while live")
        import win32con
        import win32file

        expected = win32file.GetFileInformationByHandle(self.stage_handle)
        path_handle = win32file.CreateFile(
            str(self.stage), 0x80,  # FILE_READ_ATTRIBUTES
            win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE | win32con.FILE_SHARE_DELETE,
            None, win32con.OPEN_EXISTING,
            win32con.FILE_FLAG_BACKUP_SEMANTICS | 0x00200000,
            None,
        )
        try:
            observed = win32file.GetFileInformationByHandle(path_handle)
            if int(observed[0]) & 0x400 or file_info_identity(observed) != file_info_identity(expected):
                raise RuntimeError("staged workspace path changed after ACL setup")
        finally:
            import win32api
            win32api.CloseHandle(path_handle)
        child = launch_suspended_appcontainer(
            application, arguments, self.profile.sid, environment, cwd=str(self.stage),
            bridge_client=bridge_client, job_handle=self.job_handle,
        )
        try:
            child.resume()
        except Exception:
            self.state = "cleanup_failed"
            try:
                if not terminate_job_object(self.job_handle) or not wait_job_object_empty(self.job_handle, timeout_ms=5000):
                    raise AppContainerCleanupError("session job failed to empty after child resume failure")
                for existing in [*self.processes, child]:
                    existing.close()
            except Exception as cleanup_error:
                raise AppContainerCleanupError("failed to clean up child after resume failure") from cleanup_error
            self.processes.clear()
            self.process = None
            self.state = "launch_failed"
            self._stop_pipe_listener()
            raise
        self.processes.append(child)
        self.process = child
        self.state = "running"
        return child.pid

    def attach_pipe_listener(self, listener: Any, *, ready_timeout: float = 5.0) -> None:
        """Start and own a listener bound to this session's exact package SID."""
        if self.state not in {"created", "running"} or self.pipe_thread is not None:
            raise RuntimeError("pipe listener can be attached exactly once to a live session")
        if (getattr(listener, "appcontainer_sid", None) != self.package_sid
                or getattr(listener, "session_id", None) != self.session_id
                or getattr(listener, "windows_session_id", None) != self.windows_session_id
                or getattr(listener, "secret", None) != self.secret or not callable(
            getattr(listener, "serve_forever", None)
        ) or not callable(getattr(listener, "stop", None))):
            raise ValueError("listener identity or lifecycle API does not match this AppContainer session")
        if isinstance(ready_timeout, bool) or not isinstance(ready_timeout, (int, float)) or not 0 < ready_timeout <= 30:
            raise ValueError("pipe readiness timeout must be greater than 0 and at most 30 seconds")

        self.pipe_listener = listener

        def serve() -> None:
            try:
                listener.serve_forever()
            except BaseException as exc:
                self.pipe_error = exc

        self.pipe_thread = threading.Thread(target=serve, name=f"lah-opencode-{uuid.uuid4().hex[:8]}", daemon=True)
        self.pipe_thread.start()
        if not listener.pipe_ready.wait(float(ready_timeout)):
            listener.stop()
            self.pipe_thread.join(float(listener.io_timeout) + 1)
            if self.pipe_thread.is_alive():
                self.state = "cleanup_failed"
                raise AppContainerCleanupError("pipe listener did not stop after readiness timeout")
            raise RuntimeError("pipe listener failed before becoming ready") from self.pipe_error
        if self.pipe_error is not None:
            raise RuntimeError("pipe listener exited during startup") from self.pipe_error

    def start_pipe_listener(self, *, hub_port: int, hub_api_token: str | None = None,
                            repository_root: str | None = None,
                            io_timeout: float = 120.0, ready_timeout: float = 5.0) -> None:
        """Create and attach the listener with session-owned identity and secret."""
        from .opencode_pipe_broker import WindowsOpenCodePipeListener

        listener = WindowsOpenCodePipeListener(
            session_id=self.session_id,
            appcontainer_sid=self.package_sid,
            windows_session_id=self.windows_session_id,
            secret=self.secret,
            hub_port=hub_port,
            hub_api_token=hub_api_token,
            repository_root=repository_root,
            io_timeout=io_timeout,
        )
        self.attach_pipe_listener(listener, ready_timeout=ready_timeout)

    def _stop_pipe_listener(self) -> None:
        if self.pipe_thread is None:
            return
        listener = self.pipe_listener
        listener.stop()
        self.pipe_thread.join(float(self.pipe_listener.io_timeout) + 1)
        if self.pipe_thread.is_alive():
            self.state = "cleanup_failed"
            raise AppContainerCleanupError("pipe listener cleanup could not be confirmed")
        listener.secret = b""
        listener.hub_api_token = None
        self.pipe_listener = None
        self.pipe_thread = None

    def wait_child(self, pid: int, timeout_ms: int = 20_000) -> int:
        child = next((item for item in self.processes if item.pid == pid), None)
        if child is None:
            raise RuntimeError("process is not owned by this session")
        try:
            exit_code = child.wait(timeout_ms)
            child.close()
            self.processes.remove(child)
            self.process_exit_codes[pid] = exit_code
            self.process = self.processes[-1] if self.processes else None
            self.state = "running" if self.processes else "exited"
        except TimeoutError:
            try:
                self.cancel()
            except Exception:
                self.state = "cleanup_failed"
            raise
        except Exception:
            self.state = "cleanup_failed"
            raise
        self._complete_workspace_if_ready()
        return exit_code

    def _complete_workspace_if_ready(self) -> WorkspaceTransferResult | None:
        """Copy back only after the main child and every session child exited cleanly."""
        snapshot = self.workspace_snapshot
        owner_pid = self.workspace_owner_pid
        if self.workspace_finalized:
            return self.workspace_transfer_result
        if snapshot is None or owner_pid is None or self.state != "exited" or self.processes:
            return None
        if owner_pid not in self.process_exit_codes:
            return None
        self.workspace_finalized = True
        if any(code != 0 for code in self.process_exit_codes.values()):
            return None
        if not wait_job_object_empty(self.job_handle, timeout_ms=5000):
            self.state = "cleanup_failed"
            raise AppContainerCleanupError("workspace copyback blocked because session Job is not empty")
        try:
            result = apply_workspace_changes(snapshot, staging_handle=self.stage_handle)
        except Exception:
            self.state = "cleanup_failed"
            raise
        self.workspace_transfer_result = result
        return result

    def wait(self, timeout_ms: int = 20_000) -> int:
        if len(self.processes) != 1:
            raise RuntimeError("wait requires exactly one owned child; use wait_child for multi-process sessions")
        return self.wait_child(self.processes[0].pid, timeout_ms)

    def cancel(self) -> None:
        if not self.processes:
            if self.state in {"cancelled", "exited", "closed"}:
                return
            if self.state == "created":
                self._stop_pipe_listener()
                self.state = "cancelled"
                return
            raise RuntimeError("session has no cancellable child")
        if not terminate_job_object(self.job_handle) or not wait_job_object_empty(self.job_handle, timeout_ms=5000):
            self.state = "cleanup_failed"
            raise AppContainerCleanupError("could not confirm the entire session Job is empty")
        for child in self.processes:
            child.close()
        self.processes.clear()
        self.process = None
        self.state = "cancelled"
        self._stop_pipe_listener()

    def close(self) -> None:
        if self.state == "closed":
            return
        if self.state == "running":
            self.cancel()
        if self.state == "cleanup_failed":
            raise AppContainerCleanupError("session cleanup state is unknown; profile retained")
        self._stop_pipe_listener()
        self.secret = b""
        if self.job_handle:
            if not wait_job_object_empty(self.job_handle, timeout_ms=5000) or not close_job_object(self.job_handle):
                self.state = "cleanup_failed"
                raise AppContainerCleanupError("session Job cleanup could not be confirmed")
            self.job_handle = 0
        if self.stage_handle:
            import win32api
            win32api.CloseHandle(self.stage_handle)
            self.stage_handle = None
        self.profile.close()
        self.state = "closed"
