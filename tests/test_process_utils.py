import io
import os
import subprocess
import sys
import threading
import time

import pytest

from local_ai_hub import process_utils


@pytest.mark.parametrize("pid", [0, -1, True, "123", 2**32])
def test_process_identity_rejects_invalid_pid(pid):
    assert process_utils.process_identity(pid) is None


def test_process_identity_linux_returns_normalized_path_and_starttime(monkeypatch):
    stat_reads = iter(
        [
            "4321 (worker ) with spaces) S " + " ".join(["0"] * 18 + ["987654"]),
            "4321 (worker ) with spaces) S " + " ".join(["0"] * 18 + ["987654"]),
        ]
    )

    def read_text(_path, *args, **kwargs):
        return next(stat_reads)

    monkeypatch.setattr(process_utils.os, "name", "posix")
    monkeypatch.setattr(process_utils.sys, "platform", "linux")
    monkeypatch.setattr(process_utils.Path, "read_text", read_text)
    monkeypatch.setattr(process_utils.os, "readlink", lambda _path: "/usr/bin/../bin/python")

    assert process_utils.process_identity(4321) == {
        "pid": 4321,
        "executable": "/usr/bin/python",
        "creation_identity": 987654,
        "creation_identity_type": "linux_proc_starttime_ticks",
    }


def test_process_identity_linux_fails_closed_when_pid_changes_during_lookup(monkeypatch):
    stat_reads = iter(
        [
            "4321 (worker) S " + " ".join(["0"] * 18 + ["100"]),
            "4321 (worker) S " + " ".join(["0"] * 18 + ["101"]),
        ]
    )
    monkeypatch.setattr(process_utils.os, "name", "posix")
    monkeypatch.setattr(process_utils.sys, "platform", "linux")
    monkeypatch.setattr(process_utils.Path, "read_text", lambda *_a, **_k: next(stat_reads))
    monkeypatch.setattr(process_utils.os, "readlink", lambda _path: "/usr/bin/python")

    assert process_utils.process_identity(4321) is None


def test_process_identity_linux_fails_closed_on_inaccessible_proc(monkeypatch):
    def inaccessible(*_args, **_kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(process_utils.os, "name", "posix")
    monkeypatch.setattr(process_utils.sys, "platform", "linux")
    monkeypatch.setattr(process_utils.Path, "read_text", inaccessible)

    assert process_utils.process_identity(4321) is None


def test_process_identity_linux_returns_none_for_dead_pid(monkeypatch):
    def missing(*_args, **_kwargs):
        raise FileNotFoundError("no such process")

    monkeypatch.setattr(process_utils.os, "name", "posix")
    monkeypatch.setattr(process_utils.sys, "platform", "linux")
    monkeypatch.setattr(process_utils.Path, "read_text", missing)

    assert process_utils.process_identity(4321) is None


def test_process_identity_windows_uses_creation_filetime_and_executable(monkeypatch):
    class ApiFunction:
        def __init__(self, callback):
            self.callback = callback

        def __call__(self, *args):
            return self.callback(*args)

    class Kernel32:
        def __init__(self):
            self.closed = []
            self.OpenProcess = ApiFunction(lambda _access, _inherit, pid: 0x1234 if pid == 4321 else 0)
            self.QueryFullProcessImageNameW = ApiFunction(self.query_image)
            self.GetProcessTimes = ApiFunction(self.get_times)
            self.CloseHandle = ApiFunction(lambda handle: self.closed.append(handle) or 1)

        @staticmethod
        def query_image(_handle, _flags, buffer, size):
            buffer.value = r"C:\Windows\System32\python.exe"
            process_utils.ctypes.cast(size, process_utils.ctypes.POINTER(process_utils.ctypes.c_uint32))[0] = len(buffer.value)
            return 1

        @staticmethod
        def get_times(_handle, creation, exit_time, kernel, user):
            filetime = process_utils.ctypes.cast(
                creation, process_utils.ctypes.POINTER(process_utils._FILETIME)
            ).contents
            filetime.dwLowDateTime = 0x89ABCDEF
            filetime.dwHighDateTime = 0x01234567
            for pointer in (exit_time, kernel, user):
                value = process_utils.ctypes.cast(
                    pointer, process_utils.ctypes.POINTER(process_utils._FILETIME)
                ).contents
                value.dwLowDateTime = 0
                value.dwHighDateTime = 0
            return 1

    kernel32 = Kernel32()
    monkeypatch.setattr(process_utils.os, "name", "nt")
    monkeypatch.setattr(process_utils.ctypes, "WinDLL", lambda *_a, **_k: kernel32, raising=False)

    assert process_utils.process_identity(4321) == {
        "pid": 4321,
        "executable": r"c:\windows\system32\python.exe",
        "creation_identity": 0x0123456789ABCDEF,
        "creation_identity_type": "windows_creation_filetime_100ns",
    }
    assert kernel32.closed == [0x1234]


@pytest.mark.skipif(
    not (sys.platform == "linux" or os.name == "nt"),
    reason="live process identity supported on Linux and Windows",
)
def test_process_identity_returns_current_process_identity():
    identity = process_utils.process_identity(os.getpid())

    assert identity is not None
    assert identity["pid"] == os.getpid()
    assert os.path.isabs(identity["executable"])
    assert identity["creation_identity"] > 0


class _FakeProcess:
    pid = 4321
    returncode = 0

    def __init__(self, communicate_results):
        self.args = ["tool"]
        self.communicate_results = iter(communicate_results)
        self.stdout = io.BytesIO()
        self.stderr = io.BytesIO()
        self.wait_timeouts = []

    def communicate(self, input=None, timeout=None):
        result = next(self.communicate_results)
        if isinstance(result, BaseException):
            raise result
        return result

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def kill(self):
        self.returncode = -9

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.wait_timeouts.append(timeout)
        return self.returncode


def test_run_hidden_timeout_terminates_tree_before_reporting_timeout(monkeypatch):
    process = _FakeProcess(
        [
            subprocess.TimeoutExpired(["tool"], 0.01, output=b"partial", stderr=b"err"),
            (b"partial", b"err"),
        ]
    )
    calls = []
    monkeypatch.setattr(process_utils.os, "name", "posix")
    monkeypatch.setattr(process_utils.subprocess, "Popen", lambda *a, **k: process)
    monkeypatch.setattr(
        process_utils,
        "terminate_tree",
        lambda pid, *, process_group=None: calls.append((pid, process_group)) or True,
    )

    with pytest.raises(subprocess.TimeoutExpired) as raised:
        process_utils.run_hidden(["tool"], capture_output=True, timeout=0.01)

    assert calls == [(4321, 4321)]
    assert raised.value.output == b"partial"
    assert raised.value.stderr == b"err"


def test_run_hidden_cancellation_terminates_tree_and_drains_output(monkeypatch):
    cancel_event = threading.Event()
    process = _FakeProcess(
        [
            subprocess.TimeoutExpired(["tool"], 0.1, output=b"partial", stderr=b"err"),
            (b"partial", b"err"),
        ]
    )
    process.returncode = None
    original_communicate = process.communicate
    first_call = True

    def communicate(input=None, timeout=None):
        nonlocal first_call
        if first_call:
            first_call = False
            cancel_event.set()
        return original_communicate(input=input, timeout=timeout)

    process.communicate = communicate
    calls = []
    monkeypatch.setattr(process_utils.os, "name", "posix")
    monkeypatch.setattr(process_utils.subprocess, "Popen", lambda *a, **k: process)
    monkeypatch.setattr(
        process_utils,
        "terminate_tree",
        lambda pid, *, process_group=None, grace_seconds=5.0: calls.append(
            (pid, process_group, grace_seconds)
        )
        or True,
    )

    with pytest.raises(process_utils.ProcessCancelledError) as raised:
        process_utils.run_hidden(
            ["tool"], capture_output=True, timeout=60, cancel_event=cancel_event
        )

    assert calls == [(4321, 4321, 1.0)]
    assert process.returncode == -9
    assert raised.value.output == b"partial"
    assert raised.value.stderr == b"err"


def test_run_hidden_timeout_terminates_explicit_posix_process_group(monkeypatch):
    process = _FakeProcess([subprocess.TimeoutExpired(["tool"], 0.01)])
    calls = []
    monkeypatch.setattr(process_utils.os, "name", "posix")
    monkeypatch.setattr(process_utils.subprocess, "Popen", lambda *a, **k: process)
    monkeypatch.setattr(
        process_utils,
        "terminate_tree",
        lambda pid, *, process_group=None: calls.append((pid, process_group)) or True,
    )

    with pytest.raises(subprocess.TimeoutExpired):
        process_utils.run_hidden(["tool"], process_group=7777, timeout=0.01)

    assert calls == [(4321, 7777)]


def test_run_hidden_timeout_keeps_explicit_no_session_descendants_owned(monkeypatch):
    process = _FakeProcess([subprocess.TimeoutExpired(["tool"], 0.01)])
    spawned = {}
    terminated = []

    def popen(*args, **kwargs):
        spawned.update(kwargs)
        return process

    monkeypatch.setattr(process_utils.os, "name", "posix")
    monkeypatch.setattr(process_utils.subprocess, "Popen", popen)
    monkeypatch.setattr(
        process_utils,
        "terminate_tree",
        lambda pid, *, process_group=None: terminated.append((pid, process_group)) or True,
    )

    with pytest.raises(subprocess.TimeoutExpired):
        process_utils.run_hidden(["tool"], start_new_session=False, timeout=0.01)

    assert spawned["start_new_session"] is False
    assert spawned["process_group"] == 0
    assert terminated == [(process.pid, process.pid)]


def test_terminate_tree_escalates_explicit_group_when_leader_exits(monkeypatch):
    calls = []
    ticks = iter([0.0, 0.0, 1.0])

    def killpg(group_id, sig):
        calls.append((group_id, sig))
        if sig == 0 and calls.count((7777, 0)) > 1:
            raise ProcessLookupError

    monkeypatch.setattr(process_utils.os, "name", "posix")
    monkeypatch.setattr(process_utils.os, "killpg", killpg, raising=False)
    monkeypatch.setattr(process_utils.signal, "SIGKILL", 9, raising=False)
    monkeypatch.setattr(process_utils, "pid_alive", lambda pid: False)
    monkeypatch.setattr(process_utils.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(process_utils.time, "sleep", lambda seconds: None)

    assert process_utils.terminate_tree(4321, process_group=7777, grace_seconds=0.1)
    assert calls == [
        (7777, process_utils.signal.SIGTERM),
        (7777, 0),
        (7777, process_utils.signal.SIGKILL),
        (7777, 0),
    ]


def test_run_hidden_bounds_drain_when_descendant_keeps_pipes_open(monkeypatch):
    process = _FakeProcess(
        [
            subprocess.TimeoutExpired(["tool"], 0.01, output=b"out", stderr=b"err"),
            subprocess.TimeoutExpired(["tool"], 0.5, output=b"out", stderr=b"err"),
        ]
    )
    monkeypatch.setattr(process_utils.os, "name", "posix")
    monkeypatch.setattr(process_utils.subprocess, "Popen", lambda *a, **k: process)
    monkeypatch.setattr(process_utils, "terminate_tree", lambda pid: True)

    with pytest.raises(subprocess.TimeoutExpired):
        process_utils.run_hidden(["tool"], capture_output=True, timeout=0.01)

    assert process.stdout.closed
    assert process.stderr.closed
    assert process.wait_timeouts and process.wait_timeouts[-1] <= 1.0


def test_run_hidden_cancellation_terminates_process_tree(monkeypatch):
    process = _FakeProcess([KeyboardInterrupt()])
    calls = []
    monkeypatch.setattr(process_utils.os, "name", "posix")
    monkeypatch.setattr(process_utils.subprocess, "Popen", lambda *a, **k: process)
    monkeypatch.setattr(process_utils, "terminate_tree", lambda pid: calls.append(pid) or True)

    with pytest.raises(KeyboardInterrupt):
        process_utils.run_hidden(["tool"], capture_output=True)

    assert calls == [4321]
    assert process.wait_timeouts


def test_run_hidden_uses_hidden_windows_process_group(monkeypatch):
    class StartupInfo:
        dwFlags = 0
        wShowWindow = 1

    process = _FakeProcess([(b"ok", None)])
    process._handle = 1234
    process._thread = 5678
    spawned = {}
    monkeypatch.setattr(process_utils.os, "name", "nt")
    monkeypatch.setattr(process_utils.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(process_utils.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200, raising=False)
    monkeypatch.setattr(process_utils.subprocess, "STARTF_USESHOWWINDOW", 1, raising=False)
    monkeypatch.setattr(process_utils.subprocess, "STARTUPINFO", StartupInfo, raising=False)
    monkeypatch.setattr(process_utils, "create_job_object_kill_on_close", lambda: 77)
    monkeypatch.setattr(process_utils, "assign_process_to_job", lambda job, handle: True)
    monkeypatch.setattr(process_utils, "_resume_suspended_process", lambda child: True)
    monkeypatch.setattr(process_utils, "close_job_object", lambda job: True)

    def popen(*args, **kwargs):
        spawned.update(kwargs)
        return process

    monkeypatch.setattr(process_utils.subprocess, "Popen", popen)
    result = process_utils.run_hidden(["tool"], capture_output=True)

    assert spawned["creationflags"] == 0x08000204
    assert spawned["startupinfo"].wShowWindow == 0
    assert result.stdout == b"ok"
    assert result.returncode == 0


def test_run_hidden_preserves_explicit_posix_start_new_session(monkeypatch):
    process = _FakeProcess([(None, None)])
    spawned = {}

    def popen(*args, **kwargs):
        spawned.update(kwargs)
        return process

    monkeypatch.setattr(process_utils.os, "name", "posix")
    monkeypatch.setattr(process_utils.subprocess, "Popen", popen)
    process_utils.run_hidden(["tool"], start_new_session=False)

    assert spawned["start_new_session"] is False


def test_run_hidden_preserves_explicit_posix_process_group(monkeypatch):
    process = _FakeProcess([(None, None)])
    spawned = {}

    def popen(*args, **kwargs):
        spawned.update(kwargs)
        return process

    monkeypatch.setattr(process_utils.os, "name", "posix")
    monkeypatch.setattr(process_utils.subprocess, "Popen", popen)
    process_utils.run_hidden(["tool"], process_group=0)

    assert spawned["process_group"] == 0
    assert "start_new_session" not in spawned


def test_run_hidden_assigns_suspended_windows_process_to_job_before_resume(monkeypatch):
    process = _FakeProcess([(None, None)])
    process._handle = 1234
    process._thread = 5678
    events = []

    def popen(*args, **kwargs):
        events.append(("popen", kwargs))
        return process

    monkeypatch.setattr(process_utils.os, "name", "nt")
    monkeypatch.setattr(process_utils.subprocess, "Popen", popen)
    monkeypatch.setattr(
        process_utils, "create_job_object_kill_on_close",
        lambda: events.append(("create_job",)) or 77,
    )
    monkeypatch.setattr(
        process_utils, "assign_process_to_job",
        lambda job, handle: events.append(("assign", job, handle)) or True,
    )
    monkeypatch.setattr(
        process_utils, "_resume_suspended_process",
        lambda child: events.append(("resume", child._thread)) or True,
        raising=False,
    )
    monkeypatch.setattr(
        process_utils, "close_job_object",
        lambda job: events.append(("close_job", job)) or True,
    )

    result = process_utils.run_hidden(["tool"])

    assert result.returncode == 0
    kinds = [event[0] for event in events]
    assert kinds.index("create_job") < kinds.index("popen") < kinds.index("assign")
    assert kinds.index("assign") < kinds.index("resume") < kinds.index("close_job")
    assert ("assign", 77, process.pid) in events
    popen_kwargs = next(event[1] for event in events if event[0] == "popen")
    assert popen_kwargs["creationflags"] & 0x00000004  # CREATE_SUSPENDED


def test_run_hidden_retries_job_cleanup_after_transient_close_failures(monkeypatch):
    process = _FakeProcess([(None, None), (None, None)])
    process._handle = 1234
    process._thread = 5678
    process.poll = lambda: 0
    close_results = iter([False, False, True])
    close_calls = []

    monkeypatch.setattr(process_utils.os, "name", "nt")
    monkeypatch.setattr(process_utils, "hidden_run_kwargs", lambda **kwargs: {})
    monkeypatch.setattr(process_utils, "windows_creationflags", lambda **kwargs: 0)
    monkeypatch.setattr(process_utils.subprocess, "Popen", lambda *a, **k: process)
    monkeypatch.setattr(process_utils, "create_job_object_kill_on_close", lambda: 77)
    monkeypatch.setattr(process_utils, "assign_process_to_job", lambda job, handle: True)
    monkeypatch.setattr(process_utils, "_resume_suspended_process", lambda child: True)
    monkeypatch.setattr(process_utils, "terminate_tree", lambda pid, **kwargs: True)
    monkeypatch.setattr(
        process_utils,
        "close_job_object",
        lambda job: close_calls.append(job) or next(close_results),
    )
    monkeypatch.setattr(process_utils, "terminate_job_object", lambda job: False)

    result = process_utils.run_hidden(["tool"])

    assert result.returncode == 0
    assert close_calls == [77, 77, 77]


def _windows_pid_running(pid):
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if not handle:
        return False
    try:
        return kernel32.WaitForSingleObject(handle, 0) == 0x00000102  # WAIT_TIMEOUT
    finally:
        kernel32.CloseHandle(handle)


def _wait_windows_pid_exit(pid, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _windows_pid_running(pid):
            return True
        time.sleep(0.05)
    return not _windows_pid_running(pid)


def _kill_windows_pid(pid):
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateProcess.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(0x0001 | 0x00100000, False, pid)  # TERMINATE | SYNCHRONIZE
    if not handle:
        return
    try:
        kernel32.TerminateProcess(handle, 1)
        kernel32.WaitForSingleObject(handle, 2000)
    finally:
        kernel32.CloseHandle(handle)


@pytest.mark.skipif(os.name != "nt", reason="requires Windows Job Objects")
def test_run_hidden_timeout_kills_real_windows_descendant_after_root_exit(tmp_path):
    pid_file = tmp_path / "grandchild.pid"
    grandchild = (
        "import os,signal,sys,time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "if hasattr(signal, 'SIGBREAK'): signal.signal(signal.SIGBREAK, signal.SIG_IGN)\n"
        "open(sys.argv[1], 'w').write(str(os.getpid()))\n"
        "time.sleep(12)\n"
    )
    parent = "\n".join(
        [
            "import os,subprocess,sys,time",
            "subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]])",
            "deadline=time.monotonic()+5",
            "while not os.path.exists(sys.argv[2]) and time.monotonic()<deadline:",
            "    time.sleep(.02)",
        ]
    )
    grandchild_pid = None
    try:
        started = time.monotonic()
        with pytest.raises(subprocess.TimeoutExpired):
            process_utils.run_hidden(
                [sys.executable, "-c", parent, grandchild, str(pid_file)],
                capture_output=True,
                timeout=2.0,
            )
        elapsed = time.monotonic() - started
        assert elapsed < 8.0, f"timeout cleanup exceeded bound: {elapsed:.2f}s"
        assert pid_file.exists(), "grandchild did not start"
        grandchild_pid = int(pid_file.read_text())
        assert _wait_windows_pid_exit(grandchild_pid, timeout=1.0), "grandchild survived cleanup"
    finally:
        if pid_file.exists():
            grandchild_pid = int(pid_file.read_text())
        if grandchild_pid is not None:
            _kill_windows_pid(grandchild_pid)
