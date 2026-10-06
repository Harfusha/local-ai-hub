from __future__ import annotations

import subprocess

import pytest

import local_ai_hub.process_utils as process_utils_module


def test_timeout_drain_escalates_group_before_rejoining_pipe_readers(monkeypatch) -> None:
    events: list[tuple[str, object]] = []

    class Pipe:
        def close(self) -> None:
            events.append(("close", self))

    class StuckProcess:
        pid = 24569

        def __init__(self) -> None:
            self.stdout = Pipe()
            self.stderr = Pipe()
            self.communicate_calls = 0

        def poll(self) -> int | None:
            return None

        def kill(self) -> None:
            events.append(("kill_leader", self.pid))

        def wait(self, timeout: float) -> int:
            events.append(("wait", timeout))
            return 0

        def communicate(self, timeout: float) -> tuple[bytes, bytes]:
            self.communicate_calls += 1
            events.append((f"communicate_{self.communicate_calls}", timeout))
            if self.communicate_calls == 1:
                raise subprocess.TimeoutExpired(
                    "fake command", timeout, output=b"partial", stderr=b"partial-error"
                )
            return b"drained", b"drained-error"

    process = StuckProcess()
    cleanup_calls = 0

    def terminate_tree(pid: int, **kwargs) -> bool:
        nonlocal cleanup_calls
        cleanup_calls += 1
        events.append((f"terminate_group_{cleanup_calls}", (pid, kwargs)))
        return cleanup_calls > 1

    monkeypatch.setattr(process_utils_module, "terminate_tree", terminate_tree)

    output = process_utils_module._terminate_and_drain(process, process_group=process.pid)

    assert (output.stdout, output.stderr) == (b"drained", b"drained-error")
    assert output.cleanup_confirmed is True
    event_names = [name for name, _value in events]
    assert event_names.index("terminate_group_2") < event_names.index("communicate_2")
    assert "close" not in event_names

def test_posix_numeric_process_group_cleanup_fails_closed_without_signals(monkeypatch) -> None:
    calls: list[tuple[object, ...]] = []

    class PosixOsProxy:
        name = "posix"

        @staticmethod
        def killpg(group_id, _sig):
            calls.append(("killpg", group_id))
            raise ProcessLookupError

        @staticmethod
        def kill(pid, _sig):
            calls.append(("kill", pid))
            raise ProcessLookupError

    monkeypatch.setattr(process_utils_module, "os", PosixOsProxy())

    result = process_utils_module.terminate_tree(24569, process_group=24569, grace_seconds=0.1)

    assert result is False
    assert calls == []

def test_run_hidden_timeout_preserves_unconfirmed_posix_process_without_pid_kill(monkeypatch) -> None:
    class PosixOsProxy:
        name = "posix"

    class TimedOutProcess:
        pid = 24569

        class Pipe:
            def __init__(self) -> None:
                self.closed = False

            def close(self) -> None:
                self.closed = True

        def __init__(self) -> None:
            self.stdout = self.Pipe()
            self.stderr = self.Pipe()
            self.kill_calls = 0
            self.wait_calls = 0
            self.communicate_calls = 0

        def communicate(self, input=None, timeout=None):
            self.communicate_calls += 1
            raise subprocess.TimeoutExpired(
                ["fake"], timeout, output=b"partial", stderr=b"partial-error"
            )

        def poll(self):
            return None

        def kill(self):
            self.kill_calls += 1

        def wait(self, timeout=None):
            self.wait_calls += 1
            raise subprocess.TimeoutExpired(["fake"], timeout)

    process = TimedOutProcess()
    termination_calls: list[tuple[int, dict[str, object]]] = []

    def refuse_numeric_group(pid: int, **kwargs) -> bool:
        termination_calls.append((pid, kwargs))
        return False

    monkeypatch.setattr(process_utils_module, "os", PosixOsProxy())
    monkeypatch.setattr(
        process_utils_module.subprocess, "Popen", lambda *_args, **_kwargs: process
    )
    monkeypatch.setattr(process_utils_module, "terminate_tree", refuse_numeric_group)

    with pytest.raises(subprocess.TimeoutExpired) as raised:
        process_utils_module.run_hidden(["fake"], timeout=0.01, capture_output=True)

    error = raised.value
    assert process.kill_calls == 0
    assert process.wait_calls == 0
    assert process.stdout.closed is False
    assert process.stderr.closed is False
    assert len(termination_calls) == 2
    assert error.cleanup_unconfirmed is True
    assert error.cleanup_process is process
    assert error.cleanup_process_group == process.pid

def test_posix_terminate_tree_refuses_unowned_numeric_pid_and_group(monkeypatch) -> None:
    calls: list[tuple[object, ...]] = []

    class PosixOsProxy:
        name = "posix"

        @staticmethod
        def killpg(group_id, sig):
            calls.append(("killpg", group_id, sig))

        @staticmethod
        def kill(pid, sig):
            calls.append(("kill", pid, sig))

    monkeypatch.setattr(process_utils_module, "os", PosixOsProxy())
    monkeypatch.setattr(process_utils_module.signal, "SIGKILL", 9, raising=False)

    assert process_utils_module.terminate_tree(24569, grace_seconds=0.1) is False
    assert process_utils_module.terminate_tree(
        24569, process_group=24569, grace_seconds=0.1
    ) is False
    assert calls == []

def test_explicit_process_group_reports_unknown_liveness_without_pid_fallback(monkeypatch) -> None:
    calls: list[tuple[object, ...]] = []

    class PosixOsProxy:
        name = "posix"

        @staticmethod
        def killpg(group_id, sig):
            calls.append(("killpg", group_id, sig))
            raise OSError(22, "group state unavailable")

        @staticmethod
        def kill(pid, _sig):
            calls.append(("kill", pid))
            raise ProcessLookupError

    monkeypatch.setattr(process_utils_module, "os", PosixOsProxy())
    monkeypatch.setattr(process_utils_module.signal, "SIGKILL", 9, raising=False)

    result = process_utils_module.terminate_tree(24569, process_group=24569, grace_seconds=0.1)

    assert result is False
    assert calls == []

def test_posix_cleanup_does_not_report_success_when_signals_are_denied(monkeypatch) -> None:
    calls: list[tuple[object, ...]] = []

    class PosixOsProxy:
        name = "posix"

        @staticmethod
        def killpg(group_id, sig):
            calls.append(("killpg", group_id, sig))
            raise PermissionError("group signal denied")

        @staticmethod
        def kill(pid, sig):
            calls.append(("kill", pid, sig))
            raise PermissionError("leader signal denied")

    monkeypatch.setattr(process_utils_module, "os", PosixOsProxy())
    monkeypatch.setattr(process_utils_module.signal, "SIGKILL", 9, raising=False)
    monkeypatch.setattr(process_utils_module, "pid_alive", lambda _pid: True)

    result = process_utils_module.terminate_tree(
        24569, process_group=24569, grace_seconds=0.1
    )

    assert result is False
    assert calls == []
