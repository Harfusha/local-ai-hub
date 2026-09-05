from __future__ import annotations

import sys
import time
from pathlib import Path
import pytest

from local_ai_hub.commands import CommandBroker


def test_command_runner_invokes_streaming_callback(tmp_path: Path) -> None:
    runner = CommandBroker({"commands": {"enabled": True}})

    chunks: list[str] = []

    def on_log(stream: str, text: str) -> None:
        chunks.append(text)

    # Command that prints two separate lines
    cmd = f'"{sys.executable}" -c "import sys; print(\'alpha\'); print(\'beta\')"'
    res = runner.run(
        command=cmd,
        cwd=str(tmp_path),
        log_callback=on_log,
    )

    assert res["success"] is True
    combined = "".join(chunks)
    assert "alpha" in combined
    assert "beta" in combined
    assert "alpha" in res["stdout"]
    assert "beta" in res["stdout"]


def test_command_runner_buffers_live_output(tmp_path: Path) -> None:
    runner = CommandBroker({"commands": {"enabled": True}})
    cmd = f'"{sys.executable}" -c "import sys; print(\'streaming_data_test\')"'

    res = runner.run(command=cmd, cwd=str(tmp_path))
    assert res["success"] is True
    assert "streaming_data_test" in res["stdout"]
