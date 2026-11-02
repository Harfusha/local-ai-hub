import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from local_ai_hub.opencode_sandbox import SandboxError, build_policy, run_sandbox


def test_policy_denies_network_and_bounds_files(tmp_path):
    project = tmp_path / "project"
    state = tmp_path / "state"
    source = tmp_path / "source"
    for path in (project, state, source):
        path.mkdir()
    executable = source / "opencode.exe"
    executable.touch()
    policy = build_policy([str(executable), "run", "hello world"], cwd=project, readwrite=[project, state],
                          readonly=[source], environment={"SYSTEMROOT": "C:\\Windows", "LOCALAPPDATA": str(state)},
                          proxy_port=12345, timeout_seconds=20)
    assert policy["containment"] == "processcontainer"
    assert policy["network"] == {"egress": {"default": "deny"}, "ingress": {"default": "allow", "hostLoopback": "allow"}}
    assert policy["runtimeConfig"]["networkProxy"] == "http://127.0.0.1:12345"
    assert set(policy["filesystem"]["readwritePaths"]) == {str(project.resolve()), str(state.resolve())}
    assert policy["process"]["timeout"] == 20000 and policy["process"]["inheritDefaultEnv"] is False
    assert '"hello world"' in policy["process"]["commandLine"]


@pytest.mark.parametrize("port,timeout", [(0, 10), (65536, 10), (True, 10), (123, 0), (123, float("nan"))])
def test_policy_rejects_invalid_limits(tmp_path, port, timeout):
    with pytest.raises(ValueError):
        build_policy([str(tmp_path / "exe")], cwd=tmp_path, readwrite=[tmp_path], readonly=[],
                     environment={"SYSTEMROOT": "C:\\Windows", "LOCALAPPDATA": str(tmp_path)},
                     proxy_port=port, timeout_seconds=timeout)


def test_runner_cleans_sensitive_policy_even_on_failure(tmp_path, monkeypatch):
    from local_ai_hub import opencode_sandbox

    executor = tmp_path / "wxc-exec.exe"
    executor.write_bytes(b"executor")
    monkeypatch.setattr(opencode_sandbox, "_EXECUTOR_SHA256", __import__("hashlib").sha256(b"executor").hexdigest())
    observed = []
    policy = build_policy([str(executor)], cwd=tmp_path, readwrite=[tmp_path], readonly=[],
                          environment={"SYSTEMROOT": "C:\\Windows", "LOCALAPPDATA": str(tmp_path), "SCOPED": "secret"},
                          proxy_port=12345, timeout_seconds=10)
    def run(argv, *, cwd, env, timeout):
        policy_path = Path(argv[1])
        assert policy_path.is_file()
        observed.append(policy_path)
        raise RuntimeError("child failed")
    with pytest.raises(RuntimeError, match="child failed"):
        run_sandbox(executor, policy, cwd=tmp_path, environment={}, timeout_seconds=10, run_child=run)
    assert observed and not observed[0].exists()


def test_runner_refuses_unverified_executor(tmp_path):
    executor = tmp_path / "wxc-exec.exe"
    executor.write_bytes(b"foreign")
    with pytest.raises(SandboxError, match="verify"):
        run_sandbox(executor, {}, cwd=tmp_path, environment={}, timeout_seconds=10,
                    run_child=lambda *_a, **_kw: pytest.fail("unexpected launch"))


def test_runner_refuses_weakened_policy(tmp_path, monkeypatch):
    import hashlib
    from local_ai_hub import opencode_sandbox

    executor = tmp_path / "wxc-exec.exe"
    executor.write_bytes(b"executor")
    monkeypatch.setattr(opencode_sandbox, "_EXECUTOR_SHA256", hashlib.sha256(b"executor").hexdigest())
    policy = build_policy([str(executor)], cwd=tmp_path, readwrite=[tmp_path], readonly=[],
                          environment={"SYSTEMROOT": "C:\\Windows", "LOCALAPPDATA": str(tmp_path)},
                          proxy_port=12345, timeout_seconds=10)
    policy["filesystem"]["readwritePaths"] = [str(Path(tmp_path.anchor))]
    with pytest.raises(SandboxError, match="policy"):
        run_sandbox(executor, policy, cwd=tmp_path, environment={}, timeout_seconds=10,
                    run_child=lambda *_a, **_kw: pytest.fail("unexpected launch"))


@pytest.mark.skipif(os.name != "nt", reason="Windows delete-on-close semantics")
def test_policy_file_is_removed_after_launcher_is_terminated(tmp_path):
    executor = tmp_path / "wxc-exec.exe"
    executor.write_bytes(b"executor")
    script = r'''
import hashlib,sys,time
from pathlib import Path
from local_ai_hub import opencode_sandbox as s
p=Path(sys.argv[1]); exe=p/"wxc-exec.exe"
s._EXECUTOR_SHA256=hashlib.sha256(b"executor").hexdigest()
policy=s.build_policy([str(exe)],cwd=p,readwrite=[p],readonly=[],environment={"SYSTEMROOT":"C:/Windows","LOCALAPPDATA":str(p),"SCOPED":"secret"},proxy_port=12345,timeout_seconds=10)
def run(argv,**_kwargs):
 print(argv[1],flush=True)
 time.sleep(30)
s.run_sandbox(exe,policy,cwd=p,environment={},timeout_seconds=10,run_child=run)
'''
    proc = subprocess.Popen([sys.executable, "-c", script, str(tmp_path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        line = []
        reader = threading.Thread(target=lambda: line.append(proc.stdout.readline().strip()), daemon=True)
        reader.start()
        reader.join(timeout=10)
        assert line and line[0], "launcher did not produce a policy path"
        policy_path = Path(line[0])
        assert policy_path.is_file()
        proc.terminate()
        proc.wait(timeout=10)
        assert not policy_path.exists()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)
        proc.stdout.close()
        proc.stderr.close()
