import struct
import os
import subprocess
import sys
import time

import pytest

from local_ai_hub.opencode_stop_protocol import ControlError, control_exchange


class Pipe:
    def __init__(self, chunks, identities=None):
        self.chunks = list(chunks)
        self.identities = list(identities or [True] * len(chunks))
        self.writes = []
    def read(self, size, timeout):
        if not self.chunks: return None
        value = self.chunks.pop(0)
        assert len(value) <= size
        return value
    def matches_identity(self): return self.identities.pop(0)
    def write(self, data, timeout): self.writes.append(data)


class Binding:
    def __init__(self, result=True): self.calls, self.result = [], result
    def stop(self, identity):
        self.calls.append(identity)
        return self.result


def request(key=b"x" * 32, pid=12, created=34):
    return b"LAC1" + key + struct.pack(">IQ", pid, created)


def test_authenticated_fragmented_request_requires_ack():
    data = request()
    pipe = Pipe([data[:7], data[7:], b"\x06"])
    identity = {"pid": 12, "creation_identity": 34}
    binding = Binding()
    assert control_exchange(pipe, b"x" * 32, binding, lookup=lambda pid: identity, timeout=1) == "stopped"
    assert binding.calls == [identity] and pipe.writes == [b"\x01"]


@pytest.mark.parametrize("key,identities", [(b"z" * 32, [True]), (b"x" * 32, [False])])
def test_bad_guard_or_wrong_container_never_resolves_pid(key, identities):
    pipe = Pipe([request(key)], identities)
    binding = Binding()
    with pytest.raises(ControlError) as error:
        control_exchange(pipe, b"x" * 32, binding, lookup=lambda pid: pytest.fail("lookup before authorization"), timeout=1)
    assert error.value.outcome_unknown is False and not binding.calls and not pipe.writes


def test_stale_creation_is_denied_without_termination():
    binding = Binding()
    pipe = Pipe([request(), b"\x06"])
    assert control_exchange(pipe, b"x" * 32, binding, lookup=lambda pid: {"pid": 12, "creation_identity": 35}, timeout=1) == "denied"
    assert not binding.calls and pipe.writes == [b"\x00"]


def test_lost_ack_after_stop_reports_unknown_outcome():
    pipe = Pipe([request()])
    binding = Binding()
    with pytest.raises(ControlError) as error:
        control_exchange(pipe, b"x" * 32, binding, lookup=lambda pid: {"pid": 12, "creation_identity": 34}, timeout=1)
    assert error.value.outcome_unknown is True and len(binding.calls) == 1


def test_tree_request_acknowledges_before_cancelling_entire_owned_job():
    events = []
    class WholeJob:
        def permits(self, identity):
            events.append(("permits", identity))
            return True
        def cancel_job(self):
            events.append(("cancel",))
            return True
    class ObservedPipe(Pipe):
        def write(self, data, timeout):
            events.append(("write", data))
            super().write(data, timeout)
        def read(self, size, timeout):
            value = super().read(size, timeout)
            if size == 1:
                events.append(("ack", value))
            return value
    identity = {"pid": 12, "creation_identity": 34}
    pipe = ObservedPipe([b"LAC2" + request()[4:], b"\x06"])
    assert control_exchange(pipe, b"x" * 32, WholeJob(), lookup=lambda _: identity, timeout=1) == "job_cancelled"
    assert events == [("permits", identity), ("write", b"\x03"), ("ack", b"\x06"), ("cancel",)]


def test_tree_request_without_ack_never_cancels_job():
    class WholeJob:
        def permits(self, _identity): return True
        def cancel_job(self): pytest.fail("cancelled without acknowledgement")
    pipe = Pipe([b"LAC2" + request()[4:]])
    with pytest.raises(ControlError) as error:
        control_exchange(pipe, b"x" * 32, WholeJob(), lookup=lambda _: {"pid": 12, "creation_identity": 34}, timeout=1)
    assert error.value.outcome_unknown is False and pipe.writes == [b"\x03"]


def test_tree_request_fails_closed_on_authorization_or_dispatch_failure():
    class Denied:
        def permits(self, _identity): return False
        def cancel_job(self): pytest.fail("unauthorized cancellation")
    identity = {"pid": 12, "creation_identity": 34}
    pipe = Pipe([b"LAC2" + request()[4:], b"\x06"])
    assert control_exchange(pipe, b"x" * 32, Denied(), lookup=lambda _: identity, timeout=1) == "denied"
    assert pipe.writes == [b"\x00"]
    class Unconfirmed(Denied):
        def permits(self, _identity): return True
        def cancel_job(self): return False
    with pytest.raises(ControlError) as error:
        control_exchange(Pipe([b"LAC2" + request()[4:], b"\x06"]), b"x" * 32, Unconfirmed(), lookup=lambda _: identity, timeout=1)
    assert error.value.outcome_unknown is True


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object")
def test_real_tree_request_cancels_owned_job_and_not_foreign_process(tmp_path):
    import win32api
    import win32con
    import win32event
    from local_ai_hub.opencode_owned_stop import OwnedJobBinding
    from local_ai_hub.process_utils import (_resume_suspended_process, _windows_process_identity,
                                             assign_process_to_job, close_job_object,
                                             create_job_object_kill_on_close, terminate_job_object)
    job = create_job_object_kill_on_close()
    assert job
    owned = foreign = child_handle = None
    binding = OwnedJobBinding()
    try:
        marker = tmp_path / "child.pid"
        code = ("import pathlib,subprocess,sys,time; "
                "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],creationflags=0x08000000); "
                f"pathlib.Path({str(marker)!r}).write_text(str(p.pid)); time.sleep(30)")
        owned = subprocess.Popen([sys.executable, "-c", code], creationflags=0x08000004)
        assert assign_process_to_job(job, owned.pid) and _resume_suspended_process(owned)
        foreign = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"], creationflags=0x08000000)
        deadline = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert marker.exists()
        child_handle = win32api.OpenProcess(win32con.SYNCHRONIZE, False, int(marker.read_text()))
        identity, other = _windows_process_identity(owned.pid), _windows_process_identity(foreign.pid)
        assert identity and other
        binding._bind(job, os.getpid())
        def tree_request(item):
            return b"LAC2" + b"x" * 32 + struct.pack(">IQ", item["pid"], item["creation_identity"])
        denied = Pipe([tree_request(other), b"\x06"])
        assert control_exchange(denied, b"x" * 32, binding, lookup=lambda _: other, timeout=5) == "denied"
        assert owned.poll() is None and foreign.poll() is None
        accepted = Pipe([tree_request(identity), b"\x06"])
        assert control_exchange(accepted, b"x" * 32, binding, lookup=lambda _: identity, timeout=5) == "job_cancelled"
        assert accepted.writes == [b"\x03"]
        assert owned.wait(timeout=5) is not None
        assert win32event.WaitForSingleObject(child_handle, 5000) == win32event.WAIT_OBJECT_0
        assert foreign.poll() is None
    finally:
        binding._unbind()
        if child_handle is not None:
            child_handle.Close()
        terminate_job_object(job)
        close_job_object(job)
        for proc in (owned, foreign):
            if proc is not None and proc.poll() is None:
                proc.terminate()
            if proc is not None:
                proc.wait(timeout=5)


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object")
def test_protocol_stops_only_exact_job_member():
    from local_ai_hub.opencode_owned_stop import OwnedJobBinding
    from local_ai_hub.process_utils import (_resume_suspended_process, _windows_process_identity,
                                             assign_process_to_job, close_job_object,
                                             create_job_object_kill_on_close, terminate_job_object)
    job = create_job_object_kill_on_close()
    assert job
    owned = foreign = None
    binding = OwnedJobBinding()
    try:
        owned = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"], creationflags=0x08000004)
        assert assign_process_to_job(job, owned.pid) and _resume_suspended_process(owned)
        foreign = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"], creationflags=0x08000000)
        one, other = _windows_process_identity(owned.pid), _windows_process_identity(foreign.pid)
        assert one and other
        binding._bind(job, os.getpid())
        outsider = Pipe([request(pid=foreign.pid, created=other["creation_identity"]), b"\x06"])
        assert control_exchange(outsider, b"x" * 32, binding, timeout=1) == "denied"
        member = Pipe([request(pid=owned.pid, created=one["creation_identity"]), b"\x06"])
        assert control_exchange(member, b"x" * 32, binding, timeout=5) == "stopped"
        owned.wait(timeout=3)
        assert foreign.poll() is None
    finally:
        binding._unbind()
        terminate_job_object(job)
        close_job_object(job)
        for process in (owned, foreign):
            if process is not None and process.poll() is None:
                process.kill()
                process.wait(timeout=3)
