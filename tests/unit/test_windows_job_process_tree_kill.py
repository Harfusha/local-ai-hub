import os
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from local_ai_hub import process_utils


pytestmark = pytest.mark.skipif(os.name != "nt", reason="requires Windows Job Object semantics")


_ROOT_SCRIPT = r"""
import os, subprocess, sys, time
from pathlib import Path
child_script, grandchild_script, parent_pid_file, child_pid_file, grandchild_pid_file = sys.argv[1:]
Path(parent_pid_file).write_text(str(os.getpid()), encoding="ascii")
subprocess.Popen([
    sys.executable, child_script, "child", grandchild_script,
    child_pid_file, grandchild_pid_file,
])
time.sleep(600)
"""

_DESCENDANT_SCRIPT = r"""
import os, subprocess, sys, time
from pathlib import Path
mode = sys.argv[1]
if mode == "child":
    grandchild_script, child_pid_file, grandchild_pid_file = sys.argv[2:]
    subprocess.Popen([sys.executable, grandchild_script, "leaf", grandchild_pid_file])
    Path(child_pid_file).write_text(str(os.getpid()), encoding="ascii")
elif mode == "leaf":
    Path(sys.argv[2]).write_text(str(os.getpid()), encoding="ascii")
time.sleep(600)
"""


def _wait_for_pid_file(path: Path, timeout: float = 10.0) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = int(path.read_text(encoding="ascii").strip())
            if value > 0:
                return value
        except (OSError, ValueError):
            pass
        time.sleep(0.05)
    raise AssertionError(f"child process did not publish its PID: {path.name}")


def _same_live_identity(pid: int, expected: dict[str, object]) -> bool:
    current = process_utils.process_identity(pid)
    return (
        current is not None
        and current.get("creation_identity") == expected.get("creation_identity")
        and process_utils.pid_alive(pid)
    )


@pytest.mark.parametrize("termination", ["terminate_tree", "release_owned_job"])
def test_owned_windows_job_termination_kills_parent_child_and_grandchild(tmp_path, termination):
    root_script = tmp_path / "root.py"
    descendant_script = tmp_path / "descendant.py"
    parent_pid_file = tmp_path / "parent.pid"
    child_pid_file = tmp_path / "child.pid"
    grandchild_pid_file = tmp_path / "grandchild.pid"
    root_script.write_text(_ROOT_SCRIPT, encoding="utf-8")
    descendant_script.write_text(_DESCENDANT_SCRIPT, encoding="utf-8")

    parent = process_utils.popen_managed(
        [
            sys.executable, str(root_script), str(descendant_script), str(descendant_script),
            str(parent_pid_file), str(child_pid_file), str(grandchild_pid_file),
        ],
        cwd=tmp_path,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        assert _wait_for_pid_file(parent_pid_file) == parent.pid
        child_pid = _wait_for_pid_file(child_pid_file)
        grandchild_pid = _wait_for_pid_file(grandchild_pid_file)
        parent_identity = process_utils.process_identity(parent.pid)
        child_identity = process_utils.process_identity(child_pid)
        grandchild_identity = process_utils.process_identity(grandchild_pid)
        assert parent_identity is not None
        assert child_identity is not None
        assert grandchild_identity is not None
        assert process_utils.process_parent_pid(child_pid) == parent.pid
        assert process_utils.process_parent_pid(grandchild_pid) == child_pid
        assert process_utils.pid_alive(parent.pid)
        assert process_utils.pid_alive(child_pid)
        assert process_utils.pid_alive(grandchild_pid)

        if termination == "terminate_tree":
            assert process_utils.terminate_tree(
                parent.pid, process_handle=parent, grace_seconds=1.0,
            )
        else:
            assert process_utils._release_process_job(parent)

        parent.wait(timeout=8.0)
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline and any((
            _same_live_identity(parent.pid, parent_identity),
            _same_live_identity(child_pid, child_identity),
            _same_live_identity(grandchild_pid, grandchild_identity),
        )):
            time.sleep(0.05)
        assert not _same_live_identity(parent.pid, parent_identity)
        assert not _same_live_identity(child_pid, child_identity)
        assert not _same_live_identity(grandchild_pid, grandchild_identity)
    finally:
        if parent.poll() is None:
            process_utils.terminate_tree(parent.pid, process_handle=parent, grace_seconds=1.0)
            try:
                parent.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                pass
        if getattr(parent, "_local_ai_job_handle", None):
            process_utils._release_process_job(parent)
