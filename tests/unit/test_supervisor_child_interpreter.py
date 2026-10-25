from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from local_ai_hub import supervisor


def _isolate_windows_interpreter(monkeypatch, executable: Path) -> None:
    monkeypatch.setattr(supervisor, "sys", SimpleNamespace(**{
        **vars(supervisor.sys), "platform": "win32", "executable": str(executable),
    }))
    monkeypatch.setattr(supervisor, "ctypes", SimpleNamespace(**vars(supervisor.ctypes)))
    monkeypatch.setattr(supervisor, "subprocess", SimpleNamespace(**vars(supervisor.subprocess)))


def test_windows_supervisor_uses_console_python_for_hub_child(tmp_path: Path, monkeypatch) -> None:
    pythonw = tmp_path / "pythonw.exe"
    console_python = tmp_path / "python.exe"
    console_python.touch()
    _isolate_windows_interpreter(monkeypatch, pythonw)
    kernel32 = SimpleNamespace(SetErrorMode=Mock(return_value=0))
    monkeypatch.setattr(supervisor.ctypes, "WinDLL", lambda *args, **kwargs: kernel32, raising=False)
    popen = Mock(return_value=object())
    monkeypatch.setattr(supervisor.subprocess, "Popen", popen)
    instance = supervisor.Supervisor.__new__(supervisor.Supervisor)
    instance.config_path = str(tmp_path / "config.toml")
    instance.state_dir = tmp_path / "state"

    instance.spawn_hub()

    assert popen.call_args.args[0][0] == str(console_python)
    assert popen.call_args.kwargs["stderr"] == supervisor.subprocess.PIPE
    assert [call.args[0] for call in kernel32.SetErrorMode.call_args_list] == [0x0001 | 0x0002, 0]


def test_windows_supervisor_suppresses_child_crash_dialog_and_restores_mode(
    tmp_path: Path, monkeypatch
) -> None:
    pythonw = tmp_path / "pythonw.exe"
    console_python = tmp_path / "python.exe"
    console_python.touch()
    _isolate_windows_interpreter(monkeypatch, pythonw)
    mode_calls: list[int] = []

    class Kernel32:
        def __init__(self):
            class _SetErrorMode:
                argtypes = None
                restype = None

                def __call__(self, mode: int) -> int:
                    mode_calls.append(mode)
                    return 0x10

            self.SetErrorMode = _SetErrorMode()

    monkeypatch.setattr(
        supervisor.ctypes,
        "WinDLL",
        lambda *_args, **_kwargs: Kernel32(),
        raising=False,
    )
    popen = Mock(return_value=object())
    monkeypatch.setattr(supervisor.subprocess, "Popen", popen)
    instance = supervisor.Supervisor.__new__(supervisor.Supervisor)
    instance.config_path = str(tmp_path / "config.toml")
    instance.state_dir = tmp_path / "state"

    instance.spawn_hub()

    assert mode_calls == [0x0001 | 0x0002, 0x10]
    assert popen.call_args.args[0][0] == str(console_python)
