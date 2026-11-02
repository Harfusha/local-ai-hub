import os
import queue
import subprocess
import sys
import threading

import pytest

from local_ai_hub.opencode_owned_stop import OwnedJobBinding, stop_owned_process, is_direct_owned_child
from local_ai_hub.process_utils import (
    _resume_suspended_process, _windows_process_identity, assign_process_to_job,
    close_job_object, create_job_object_kill_on_close, terminate_job_object,
)

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows job object")


def test_process_lineage_requires_exact_live_membership():
    job = create_job_object_kill_on_close()
    assert job
    parent = foreign = None
    try:
        script = ("import subprocess,sys,time; "
                  "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],creationflags=0x08000000); "
                  "print(p.pid,flush=True); time.sleep(30)")
        parent = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE,
                                  creationflags=0x08000004, text=True)
        assert assign_process_to_job(job, parent.pid)
        assert _resume_suspended_process(parent)
        output = queue.Queue()
        threading.Thread(target=lambda: output.put(parent.stdout.readline()), daemon=True).start()
        child_pid = int(output.get(timeout=5))
        foreign = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"], creationflags=0x08000000)
        parent_id = _windows_process_identity(parent.pid)
        child_id = _windows_process_identity(child_pid)
        foreign_id = _windows_process_identity(foreign.pid)
        assert parent_id and child_id and foreign_id
        assert is_direct_owned_child(job, parent_id, child_id) is True
        assert is_direct_owned_child(job, parent_id, foreign_id) is False
        assert is_direct_owned_child(job, child_id, parent_id) is False
        assert is_direct_owned_child(job, parent_id, {**child_id, "creation_identity": child_id["creation_identity"] + 1}) is False
        parent.kill()
        parent.wait(timeout=3)
        assert is_direct_owned_child(job, parent_id, child_id) is False
    finally:
        terminate_job_object(job)
        close_job_object(job)
        for process in (parent, foreign):
            if process is not None and process.poll() is None:
                process.kill()
                process.wait(timeout=3)
        if parent is not None and parent.stdout is not None:
            parent.stdout.close()


def test_only_exact_identity_in_owned_job_can_be_stopped():
    job = create_job_object_kill_on_close()
    assert job
    owned = foreign = None
    try:
        owned = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"], creationflags=0x08000004)
        assert assign_process_to_job(job, owned.pid)
        assert _resume_suspended_process(owned)
        foreign = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"], creationflags=0x08000000)
        owner = _windows_process_identity(owned.pid)
        other = _windows_process_identity(foreign.pid)
        assert owner and other
        stale = {**owner, "creation_identity": owner["creation_identity"] + 1}
        assert stop_owned_process(job, stale) is False
        assert stop_owned_process(job, other) is False
        assert owned.poll() is None and foreign.poll() is None
        binding = OwnedJobBinding()
        binding._bind(job, foreign.pid)
        assert binding.stop(other) is False
        assert binding.stop(owner) is True
        binding._unbind()
        owned.wait(timeout=3)
        assert foreign.poll() is None
    finally:
        terminate_job_object(job)
        close_job_object(job)
        for process in (owned, foreign):
            if process is not None and process.poll() is None:
                process.kill()
                process.wait(timeout=3)


def test_malformed_identity_fails_closed():
    for identity in (None, {}, {"pid": True}, {"pid": 0, "executable": "x", "creation_identity": 1,
                                                 "creation_identity_type": "windows_creation_filetime_100ns"}):
        assert stop_owned_process(1, identity) is False


def test_job_binding_cannot_stop_root_or_be_reused(monkeypatch):
    calls = []
    monkeypatch.setattr("local_ai_hub.opencode_owned_stop.stop_owned_process", lambda job, identity: calls.append((job, identity)) or True)
    binding = OwnedJobBinding()
    with pytest.raises(RuntimeError):
        binding.stop({"pid": 2})
    binding._bind(42, 1)
    assert binding.stop({"pid": 1}) is False
    identity = {"pid": 2}
    assert binding.stop(identity) is True
    assert calls == [(42, identity)]
    binding._unbind()
    with pytest.raises(RuntimeError):
        binding.stop(identity)
    with pytest.raises(RuntimeError):
        binding._bind(43, 3)
