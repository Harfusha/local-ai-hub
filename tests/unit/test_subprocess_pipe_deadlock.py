import sys
import subprocess
import threading
import time
from local_ai_hub.commands import CommandBroker, _BoundedStreamBuffer
from local_ai_hub.process_utils import ProcessCancelledError, run_hidden

def test_commands_pipe_drain_avoids_deadlock(tmp_path):
    config = {
        "commands": {
            "enabled": True,
            "timeout_seconds": 15,
        },
        "server": {
            "state_dir": str(tmp_path / "state"),
        },
    }
    broker = CommandBroker(config)
    # Output 250 KB to stdout and 250 KB to stderr simultaneously
    code = (
        "import sys\n"
        "sys.stdout.write('A' * 250000)\n"
        "sys.stdout.flush()\n"
        "sys.stderr.write('B' * 250000)\n"
        "sys.stderr.flush()\n"
    )
    cmd = f'"{sys.executable}" -c "{code}"'
    res = broker.run(cmd, cwd=str(tmp_path), timeout=10)
    assert res.get("success") is True
    assert res.get("timed_out") is False
    assert len(res.get("stdout", "")) > 0
    assert len(res.get("stderr", "")) > 0


def test_commands_keep_both_streams_byte_bounded_while_draining(tmp_path):
    broker = CommandBroker({
        "commands": {"enabled": True, "timeout_seconds": 15, "max_output_chars": 100_000, "max_output_bytes": 4096},
        "server": {"state_dir": str(tmp_path / "state")},
    })
    code = (
        "import sys, threading\n"
        "def write(stream, text):\n"
        "    for _ in range(100):\n"
        "        stream.write(text * 4096); stream.flush()\n"
        "a=threading.Thread(target=write,args=(sys.stdout,'A'))\n"
        "b=threading.Thread(target=write,args=(sys.stderr,'B'))\n"
        "a.start(); b.start(); a.join(); b.join()\n"
    )
    res = broker.run(f'"{sys.executable}" -c "{code}"', cwd=str(tmp_path), timeout=10)
    assert res.get("success") is True
    assert res.get("timed_out") is False
    assert len(res["stdout"].encode("utf-8")) <= 4096
    assert len(res["stderr"].encode("utf-8")) <= 4096
    assert res.get("discarded_output_chars", 0) > 0


def test_run_hidden_large_dual_stream_output_preserves_text_and_bytes():
    code = (
        "import sys, threading\n"
        "def write(stream, char):\n"
        "    for _ in range(40):\n"
        "        stream.write(char * 8192); stream.flush()\n"
        "a=threading.Thread(target=write,args=(sys.stdout,'A'))\n"
        "b=threading.Thread(target=write,args=(sys.stderr,'B'))\n"
        "a.start(); b.start(); a.join(); b.join()\n"
    )
    text_result = run_hidden([sys.executable, "-c", code], capture_output=True, text=True, timeout=10)
    bytes_result = run_hidden([sys.executable, "-c", code], capture_output=True, text=False, timeout=10)
    assert text_result.returncode == bytes_result.returncode == 0
    assert len(text_result.stdout) == len(text_result.stderr) == 327680
    assert len(bytes_result.stdout) == len(bytes_result.stderr) == 327680


def test_run_hidden_text_capture_byte_cap_preserves_check_error_output():
    code = "import sys; sys.stdout.buffer.write(('é' * 5000).encode('utf-8')); sys.exit(7)"
    try:
        run_hidden(
            [sys.executable, "-c", code], capture_output=True, text=True,
            encoding="utf-8", errors="strict", check=True, max_output_bytes=1024,
        )
    except subprocess.CalledProcessError as error:
        assert error.returncode == 7
        assert isinstance(error.stdout, str)
        assert len(error.stdout.encode("utf-8")) <= 1024
        assert error.stdout_truncated is True
        assert error.discarded_output_bytes > 0
    else:
        raise AssertionError("check=True must preserve nonzero exit behavior")


def test_run_hidden_bounds_capture_and_writes_large_input_concurrently():
    code = (
        "import sys\n"
        "sys.stdout.write('P' * 250000); sys.stdout.flush()\n"
        "data=sys.stdin.buffer.read()\n"
        "sys.stderr.write(str(len(data))); sys.stderr.flush()\n"
    )
    result = run_hidden(
        [sys.executable, "-c", code], input=b"I" * 250000,
        capture_output=True, timeout=10, max_output_bytes=4096,
    )
    assert result.returncode == 0
    assert len(result.stdout) <= 4096
    assert result.stderr == b"250000"
    assert result.stdout_truncated is True
    assert result.stderr_truncated is False
    assert result.discarded_output_bytes > 0


def test_run_hidden_cancel_drains_and_joins_owned_readers(tmp_path):
    marker = tmp_path / "child-started"
    code = (
        "import sys,time\n"
        "sys.stdout.write('Z' * 250000); sys.stdout.flush()\n"
        f"open({str(marker)!r}, 'w').close()\n"
        "time.sleep(5)\n"
    )
    cancel_event = threading.Event()
    errors: list[BaseException] = []

    def invoke() -> None:
        try:
            run_hidden(
                [sys.executable, "-c", code], capture_output=True, timeout=10,
                cancel_event=cancel_event, max_output_bytes=4096,
            )
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=invoke)
    worker.start()
    deadline = time.monotonic() + 5
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert marker.exists()
    cancel_event.set()
    worker.join(timeout=8)
    assert not worker.is_alive()
    assert len(errors) == 1
    error = errors[0]
    assert isinstance(error, ProcessCancelledError)
    assert len(error.output) <= 4096
    assert error.stdout_truncated is True
    assert error.discarded_output_bytes > 0
    assert getattr(error, "cleanup_confirmed", False) is True


def test_bounded_stream_buffer_obeys_utf8_byte_limit():
    buffer = _BoundedStreamBuffer(max_chars=10_000, max_bytes=1024, redact=False)
    buffer.append("é" * 2000)
    retained = buffer.getvalue()
    assert len(retained.encode("utf-8")) <= 1024
    assert retained == "é" * 512
    assert buffer.discarded_chars == 1488


def test_commands_timeout_keeps_bounded_output_and_finishes_capture(tmp_path):
    broker = CommandBroker({
        "commands": {"enabled": True, "timeout_seconds": 15, "max_output_chars": 100_000, "max_output_bytes": 4096},
        "server": {"state_dir": str(tmp_path / "state")},
    })
    code = (
        "import sys, threading, time\n"
        "def write(stream, char):\n"
        "    for _ in range(100): stream.write(char * 4096); stream.flush()\n"
        "a=threading.Thread(target=write,args=(sys.stdout,'A'))\n"
        "b=threading.Thread(target=write,args=(sys.stderr,'B'))\n"
        "a.start(); b.start(); a.join(); b.join(); time.sleep(5)\n"
    )
    res = broker.run(f'"{sys.executable}" -c "{code}"', cwd=str(tmp_path), timeout=1)
    assert res.get("timed_out") is True
    assert len(res["stdout"].encode("utf-8")) <= 4096
    assert len(res["stderr"].encode("utf-8")) <= 4096
    assert res.get("output_capture_unconfirmed") is False


def test_commands_cancel_keeps_bounded_output_and_finishes_capture(tmp_path):
    broker = CommandBroker({
        "commands": {"enabled": True, "timeout_seconds": 15, "max_output_chars": 100_000, "max_output_bytes": 4096},
        "server": {"state_dir": str(tmp_path / "state")},
    })
    cancel_event = threading.Event()
    stream_started = threading.Event()
    code = (
        "import sys, threading, time\n"
        "def write(stream, char):\n"
        "    for _ in range(100): stream.write(char * 4096); stream.flush()\n"
        "a=threading.Thread(target=write,args=(sys.stdout,'A'))\n"
        "b=threading.Thread(target=write,args=(sys.stderr,'B'))\n"
        "a.start(); b.start(); a.join(); b.join(); time.sleep(5)\n"
    )
    result: dict[str, object] = {}
    worker = threading.Thread(target=lambda: result.update(
        broker.run(
            f'"{sys.executable}" -c "{code}"', cwd=str(tmp_path), timeout=10,
            request_cancel_event=cancel_event, log_callback=lambda *_: stream_started.set(),
        )
    ))
    worker.start()
    assert stream_started.wait(5)
    cancel_event.set()
    worker.join(timeout=8)
    assert not worker.is_alive()
    assert result.get("cancelled") is True
    assert len(str(result["stdout"]).encode("utf-8")) <= 4096
    assert len(str(result["stderr"]).encode("utf-8")) <= 4096
    assert result.get("output_capture_unconfirmed") is False


def test_run_hidden_pipe_drain_avoids_deadlock():
    code = (
        "import sys\n"
        "sys.stdout.write('A' * 250000)\n"
        "sys.stdout.flush()\n"
        "sys.stderr.write('B' * 250000)\n"
        "sys.stderr.flush()\n"
    )
    cmd = [sys.executable, "-c", code]
    res = run_hidden(cmd, capture_output=True, timeout=10)
    assert res.returncode == 0
    assert len(res.stdout) >= 250000
    assert len(res.stderr) >= 250000
