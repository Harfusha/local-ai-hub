import os
import json
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from local_ai_hub.opencode_owned_stop import OwnedJobBinding
from local_ai_hub.opencode_stop_protocol import ControlError
from local_ai_hub.opencode_stop_service import StopService

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows named pipe")


def test_service_stops_after_uncertain_dispatch(monkeypatch):
    import local_ai_hub.opencode_stop_service as service
    finished = threading.Event()

    class Pipe:
        def close(self): pass
    class Listener:
        name = "test"
        def __init__(self, sid): pass
        def __enter__(self): return self
        def __exit__(self, *_args): finished.set()
        def accept(self, *, timeout, stop): return Pipe()
    def uncertain(*args, **kwargs):
        raise ControlError("response lost", outcome_unknown=True)

    monkeypatch.setattr(service, "WindowsPipeListener", Listener)
    monkeypatch.setattr(service, "control_exchange", uncertain)
    instance = StopService("sid", b"x" * 32, OwnedJobBinding()).__enter__()
    assert finished.wait(2)
    with pytest.raises(RuntimeError, match="control service failed"):
        instance.check_health()
    with pytest.raises(RuntimeError, match="control service failed"):
        instance.close()


def test_invalid_control_service_secret_rejected():
    with pytest.raises(ValueError):
        StopService("sid", b"short", OwnedJobBinding())


def test_stop_client_rejects_invalid_pid():
    script = Path(__file__).resolve().parents[1] / "tools" / "opencode_stop_client.ps1"
    powershell = Path(os.environ["SYSTEMROOT"]) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    env = dict(os.environ)
    env.update({"LOCAL_AI_STOP_PIPE": r"\\.\pipe\lah-opencode-" + "a" * 32, "LOCAL_AI_STOP_SECRET": "78" * 32})
    result = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script), "not-a-pid"],
                            env=env, capture_output=True, timeout=10, check=False)
    assert result.returncode == 4


def test_powershell_client_stops_owned_appcontainer_child(tmp_path):
    from local_ai_hub.opencode_appcontainer import AppContainerProfile
    from local_ai_hub.opencode_container_process import run_in_appcontainer
    from local_ai_hub.process_utils import _windows_process_identity

    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable")
    executable = tmp_path / "node.exe"
    shutil.copyfile(node, executable)
    client = tmp_path / "stop.ps1"
    shutil.copyfile(Path(__file__).resolve().parents[1] / "tools" / "opencode_stop_client.ps1", client)
    powershell = Path(os.environ["SYSTEMROOT"]) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    env = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA", "PATH") if key in os.environ}
    env.update({"TEMP": str(tmp_path), "TMP": str(tmp_path)})
    marker = tmp_path / "target.pid"
    result = []
    binding = OwnedJobBinding()
    with AppContainerProfile() as profile:
        for options in (["/grant", f"*{profile.sid}:(OI)(CI)(F)"], ["/setintegritylevel", "(OI)(CI)L"]):
            grant = subprocess.run(["icacls", str(tmp_path), *options, "/T", "/C"], capture_output=True, timeout=15, check=False)
            assert grant.returncode == 0
        with StopService(profile.sid, b"x" * 32, binding) as service:
            script = "const fs=require('fs'),cp=require('child_process');const p=cp.spawn(process.execPath,['-e','setTimeout(()=>{},12000)'],{stdio:'inherit'});fs.writeFileSync('target.pid',String(p.pid));p.on('exit',()=>process.exit(0));"
            def launch():
                try:
                    with open(os.devnull, "rb") as stdin, (tmp_path / "parent.log").open("wb") as stdout, open(os.devnull, "wb") as stderr:
                        result.append(run_in_appcontainer(profile, [str(executable), "-e", script], cwd=tmp_path, env=env, timeout=18,
                                                          stdio=(stdin.fileno(), stdout.fileno(), stderr.fileno()), binding=binding,
                                                          services=(service,)))
                except BaseException as exc:
                    result.append(exc)
            worker = threading.Thread(target=launch)
            worker.start()
            target_pid = None
            try:
                deadline = time.monotonic() + 8
                while not marker.exists() and worker.is_alive() and time.monotonic() < deadline:
                    time.sleep(0.02)
                assert marker.exists(), result
                target_pid = int(marker.read_text())
                control_env = {**env, "LOCAL_AI_STOP_PIPE": service.name, "LOCAL_AI_STOP_SECRET": "78" * 32}
                with open(os.devnull, "rb") as stdin, (tmp_path / "client.log").open("wb") as stdout, (tmp_path / "client-error.log").open("wb") as stderr:
                    code = run_in_appcontainer(profile, [str(powershell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(client), str(target_pid)],
                                               cwd=tmp_path, env=control_env, timeout=10,
                                               stdio=(stdin.fileno(), stdout.fileno(), stderr.fileno()))
                assert code == 0
                worker.join(timeout=5)
                assert not worker.is_alive() and result == [0]
                service.check_health()
            finally:
                if worker.is_alive() and target_pid:
                    identity = _windows_process_identity(target_pid)
                    if identity:
                        binding.stop(identity)
                worker.join(timeout=19)
                assert not worker.is_alive()


def test_session_cancel_client_stops_owned_job_and_preserves_foreign_process(tmp_path):
    from local_ai_hub.opencode_appcontainer import AppContainerProfile
    from local_ai_hub.opencode_container_process import run_in_appcontainer

    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable")
    executable = tmp_path / "node.exe"
    shutil.copyfile(node, executable)
    client = tmp_path / "stop.ps1"
    shutil.copyfile(Path(__file__).resolve().parents[1] / "tools" / "opencode_stop_client.ps1", client)
    powershell = Path(os.environ["SYSTEMROOT"]) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    env = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA", "PATH") if key in os.environ}
    env.update({"TEMP": str(tmp_path), "TMP": str(tmp_path)})
    foreign = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"], creationflags=0x08000000)
    binding, outcomes = OwnedJobBinding(), []
    worker = None
    try:
        with AppContainerProfile() as profile:
            for options in (["/grant", f"*{profile.sid}:(OI)(CI)(F)"], ["/setintegritylevel", "(OI)(CI)L"]):
                grant = subprocess.run(["icacls", str(tmp_path), *options, "/T", "/C"], capture_output=True, timeout=15, check=False)
                assert grant.returncode == 0
            with StopService(profile.sid, b"x" * 32, binding) as service:
                script = "const fs=require('fs'),cp=require('child_process');const p=cp.spawn(process.execPath,['-e','setTimeout(()=>{},30000)'],{stdio:'inherit'});fs.writeFileSync('target.pid',String(p.pid));setTimeout(()=>{},30000)"
                def launch():
                    try:
                        with open(os.devnull, "rb") as stdin, (tmp_path / "parent.log").open("wb") as stdout, (tmp_path / "parent-error.log").open("wb") as stderr:
                            outcomes.append(run_in_appcontainer(profile, [str(executable), "-e", script], cwd=tmp_path, env=env, timeout=20,
                                                                stdio=(stdin.fileno(), stdout.fileno(), stderr.fileno()), binding=binding, services=(service,)))
                    except BaseException as exc:
                        outcomes.append(exc)
                worker = threading.Thread(target=launch)
                worker.start()
                target_pid = None
                try:
                    deadline = time.monotonic() + 8
                    marker = tmp_path / "target.pid"
                    while not marker.exists() and worker.is_alive() and time.monotonic() < deadline:
                        time.sleep(0.02)
                    assert marker.exists(), outcomes
                    target_pid = int(marker.read_text())
                    control_env = {**env, "LOCAL_AI_STOP_PIPE": service.name, "LOCAL_AI_STOP_SECRET": "78" * 32}
                    with open(os.devnull, "rb") as stdin, open(os.devnull, "wb") as stdout, (tmp_path / "control-error.log").open("wb") as stderr:
                        code = run_in_appcontainer(profile, [str(powershell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(client), "--cancel-session", str(target_pid)],
                                                   cwd=tmp_path, env=control_env, timeout=10,
                                                   stdio=(stdin.fileno(), stdout.fileno(), stderr.fileno()))
                    assert code == 3, (tmp_path / "control-error.log").read_text(encoding="utf-8", errors="replace")
                    worker.join(timeout=10)
                    assert not worker.is_alive() and len(outcomes) == 1 and isinstance(outcomes[0], int) and outcomes[0] != 0
                    assert foreign.poll() is None
                    service.check_health()
                finally:
                    if worker.is_alive() and target_pid:
                        binding.cancel_job()
                    worker.join(timeout=21)
                    assert not worker.is_alive()
    finally:
        if foreign.poll() is None:
            foreign.terminate()
        foreign.wait(timeout=5)


def test_real_appcontainer_client_and_same_user_rejection(tmp_path):
    import ctypes
    from ctypes import wintypes
    from local_ai_hub.opencode_appcontainer import AppContainerProfile
    from local_ai_hub.opencode_container_process import run_in_appcontainer
    from local_ai_hub.process_utils import (_resume_suspended_process, _windows_process_identity,
                                             assign_process_to_job, close_job_object,
                                             create_job_object_kill_on_close, terminate_job_object)

    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable")
    exe = tmp_path / "node.exe"
    shutil.copyfile(node, exe)
    job = create_job_object_kill_on_close()
    assert job
    target = foreign = None
    binding = OwnedJobBinding()
    try:
        target = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"], creationflags=0x08000004)
        assert assign_process_to_job(job, target.pid) and _resume_suspended_process(target)
        foreign = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"], creationflags=0x08000000)
        target_id, foreign_id = _windows_process_identity(target.pid), _windows_process_identity(foreign.pid)
        assert target_id and foreign_id
        binding._bind(job, os.getpid())
        with AppContainerProfile() as profile:
            for options in (["/grant", f"*{profile.sid}:(OI)(CI)(F)"], ["/setintegritylevel", "(OI)(CI)L"]):
                result = subprocess.run(["icacls", str(tmp_path), *options, "/T", "/C"], capture_output=True, timeout=15, check=False)
                assert result.returncode == 0
            with StopService(profile.sid, b"x" * 32, binding) as service:
                # Same-account host process has the guard but must fail SID authentication.
                rogue = r'''const net=require('net');const s=net.connect(PIPE);const timer=setTimeout(()=>s.destroy(),1500);
s.on('connect',()=>{let b=Buffer.alloc(48);b.write('LAC1');b.fill(120,4,36);b.writeUInt32BE(PID,36);b.writeBigUInt64BE(BigInt('CREATED'),40);s.write(b)});
s.on('error',()=>{});s.on('close',()=>clearTimeout(timer));'''
                rogue = rogue.replace("PIPE", json.dumps(service.name)).replace("PID", str(target.pid)).replace("CREATED", str(target_id["creation_identity"]))
                result = subprocess.run([node, "-e", rogue], capture_output=True, timeout=4, check=False)
                assert result.returncode == 0 and target.poll() is None
                kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
                kernel.WaitNamedPipeW.restype = wintypes.BOOL
                assert kernel.WaitNamedPipeW(service.name, 3000)
                script = r'''const net=require('net'),fs=require('fs');const name=PIPE;
function request(pid,created){return new Promise((resolve,reject)=>{const s=net.connect(name);let status,acked=false;
s.on('connect',()=>{const b=Buffer.alloc(48);b.write('LAC1');b.fill(120,4,36);b.writeUInt32BE(pid,36);b.writeBigUInt64BE(BigInt(created),40);s.write(b)});
s.on('data',b=>{status=b[0];s.write(Buffer.from([6]),err=>{if(err)return reject(err);acked=true;s.end()})});s.on('error',e=>acked?resolve(status):reject(e));s.on('close',()=>acked?resolve(status):reject(Error('no acknowledgement')))})}
request(FOREIGN,'F_CREATED').then(a=>request(TARGET,'T_CREATED').then(b=>fs.writeFileSync('control.json',JSON.stringify([a,b])))).catch(e=>{fs.writeFileSync('control-error.txt',String(e.code||e));process.exit(3)});'''
                script = (script.replace("PIPE", json.dumps(service.name)).replace("FOREIGN", str(foreign.pid))
                          .replace("F_CREATED", str(foreign_id["creation_identity"])).replace("TARGET", str(target.pid))
                          .replace("T_CREATED", str(target_id["creation_identity"])))
                env = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA", "PATH") if key in os.environ}
                env.update({"TEMP": str(tmp_path), "TMP": str(tmp_path)})
                assert run_in_appcontainer(profile, [str(exe), "-e", script], cwd=tmp_path, env=env, timeout=10) == 0
                assert json.loads((tmp_path / "control.json").read_text()) == [0, 1]
                target.wait(timeout=3)
                assert foreign.poll() is None
                service.check_health()
    finally:
        binding._unbind()
        terminate_job_object(job)
        close_job_object(job)
        for process in (target, foreign):
            if process is not None and process.poll() is None:
                process.kill()
                process.wait(timeout=3)
