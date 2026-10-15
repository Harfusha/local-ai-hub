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


def _owned_ancestry(pid: int, ancestor_pid: int, max_depth: int = 8) -> list[int] | None:
    chain = [pid]
    while chain[-1] != ancestor_pid and len(chain) <= max_depth:
        parent_pid = process_utils.process_parent_pid(chain[-1])
        if not parent_pid or parent_pid in chain:
            return None
        chain.append(parent_pid)
    return chain if chain[-1] == ancestor_pid else None


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
        parent_handle_identity = process_utils.process_identity(parent.pid)
        assert parent_handle_identity is not None
        script_parent_pid = _wait_for_pid_file(parent_pid_file)
        child_pid = _wait_for_pid_file(child_pid_file)
        grandchild_pid = _wait_for_pid_file(grandchild_pid_file)
        parent_chain = _owned_ancestry(script_parent_pid, parent.pid)
        child_chain = _owned_ancestry(child_pid, script_parent_pid)
        grandchild_chain = _owned_ancestry(grandchild_pid, child_pid)
        assert parent_chain is not None
        assert child_chain is not None
        assert grandchild_chain is not None
        owned_pids = tuple(dict.fromkeys(parent_chain + child_chain + grandchild_chain))
        identities = {parent.pid: parent_handle_identity}
        for pid in owned_pids:
            identity = process_utils.process_identity(pid)
            assert identity is not None
            if pid == parent.pid:
                assert identity.get("creation_identity") == parent_handle_identity.get("creation_identity")
            identities[pid] = identity
            assert process_utils.pid_alive(pid)

        if termination == "terminate_tree":
            assert process_utils.terminate_tree(
                parent.pid, process_handle=parent, grace_seconds=1.0,
            )
        else:
            assert process_utils._release_process_job(parent)

        parent.wait(timeout=8.0)
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline and any(
            _same_live_identity(pid, identity) for pid, identity in identities.items()
        ):
            time.sleep(0.05)
        assert all(not _same_live_identity(pid, identity) for pid, identity in identities.items())
    finally:
        if parent.poll() is None:
            process_utils.terminate_tree(parent.pid, process_handle=parent, grace_seconds=1.0)
            try:
                parent.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                pass
        if getattr(parent, "_local_ai_job_handle", None):
            process_utils._release_process_job(parent)
