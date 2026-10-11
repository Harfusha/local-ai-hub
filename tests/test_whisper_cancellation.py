from __future__ import annotations

import io
import subprocess
import threading
from pathlib import Path

import pytest

from local_ai_hub import process_utils
from local_ai_hub.services import LocalAIServices


class _FakeProcess:
    pid = 4321
    returncode = None

    def __init__(self, cancel_event: threading.Event) -> None:
        self.stdout = io.BytesIO()
        self.stderr = io.BytesIO()
        self.cancel_event = cancel_event
        self.first = True

    def communicate(self, input=None, timeout=None):
        if self.first:
            self.first = False
            self.cancel_event.set()
            raise subprocess.TimeoutExpired(["whisper"], timeout, output=b"partial", stderr=b"err")
        return b"partial", b"err"

    def kill(self) -> None:
        self.returncode = -9

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode


def test_run_hidden_cancellation_terminates_tree_and_drains_output(monkeypatch):
    cancel_event = threading.Event()
    process = _FakeProcess(cancel_event)
    calls = []
    identity = {
        "pid": 4321,
        "executable": "/usr/bin/python",
        "creation_identity": 1234,
        "creation_identity_type": "linux_proc_starttime_ticks",
    }
    monkeypatch.setattr(process_utils.os, "name", "posix")
    monkeypatch.setattr(process_utils.subprocess, "Popen", lambda *a, **k: process)
    monkeypatch.setattr(process_utils, "process_identity", lambda _pid: identity)

    def terminate_tree(
        pid, *, process_group=None, expected_identity=None, grace_seconds=5.0, process_handle=None
    ):
        calls.append((pid, process_group, expected_identity, grace_seconds, process_handle))
        process.returncode = -9
        return True

    monkeypatch.setattr(process_utils, "terminate_tree", terminate_tree)

    with pytest.raises(process_utils.ProcessCancelledError) as raised:
        process_utils.run_hidden(
            ["whisper"], capture_output=True, timeout=60, cancel_event=cancel_event
        )

    assert calls == [(4321, 4321, identity, 1.0, process)]
    assert process.returncode == -9
    assert raised.value.output == b"partial"
    assert raised.value.stderr == b"err"


def test_transcribe_reports_cancellation_after_owned_output_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"test audio")
    output_directories: list[Path] = []
    cancel_event = threading.Event()
    cancel_event.set()

    def cancelled_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        output_dir = Path(args[args.index("--output_dir") + 1])
        output_directories.append(output_dir)
        assert output_dir.is_dir()
        partial_output = output_dir / "sample.json"
        partial_output.write_text('{"text": "partial"}', encoding="utf-8")
        assert kwargs["cancel_event"] is cancel_event
        raise process_utils.ProcessCancelledError(args)

    monkeypatch.setattr("local_ai_hub.services.shutil.which", lambda _name: "whisper-cli")
    monkeypatch.setattr(process_utils, "run_hidden", cancelled_run)
    result = object.__new__(LocalAIServices).transcribe(
        {"audio": str(audio)}, "task-17", cancel_event=cancel_event
    )

    assert result["success"] is False
    assert result["reason"] == "cancelled"
    assert result["cancelled"] is True
    assert output_directories
    assert not output_directories[0].exists()
