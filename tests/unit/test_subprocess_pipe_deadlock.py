import sys
from local_ai_hub.commands import CommandBroker
from local_ai_hub.process_utils import run_hidden

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
