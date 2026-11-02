import json
import os
import shutil
import socket
import subprocess
import tempfile
from pathlib import Path

import pytest

from local_ai_hub.opencode_appcontainer import AppContainerProfile
from local_ai_hub.opencode_container_process import run_in_appcontainer
from local_ai_hub.opencode_owned_stop import OwnedJobBinding

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows AppContainer")


def test_real_container_has_internal_loopback_but_not_host_loopback(tmp_path, monkeypatch):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable")
    executable = tmp_path / "node.exe"
    shutil.copyfile(node, executable)
    shutil.copyfile(Path(__file__).resolve().parents[1] / "tools" / "opencode_pipe_client.cjs", tmp_path / "client.cjs")
    host = socket.socket()
    host.bind(("127.0.0.1", 0))
    host.listen()
    host.settimeout(0.2)
    try:
        with AppContainerProfile() as profile:
            grant = subprocess.run(["icacls", str(tmp_path), "/grant", f"*{profile.sid}:(OI)(CI)(F)", "/T", "/C"],
                                   capture_output=True, timeout=15, check=False)
            assert grant.returncode == 0
            label = subprocess.run(["icacls", str(tmp_path), "/setintegritylevel", "(OI)(CI)L", "/T", "/C"],
                                   capture_output=True, timeout=15, check=False)
            assert label.returncode == 0
            script = """const net=require('net'),fs=require('fs');let result={};
const s=net.createServer(c=>c.end());s.listen(0,'127.0.0.1',()=>{
const c=net.connect(s.address().port,'127.0.0.1');c.on('connect',()=>{result.internal=true;c.destroy();s.close();
const h=net.connect(HOSTPORT,'127.0.0.1');h.setTimeout(500);h.on('connect',()=>{result.host=true;h.destroy();done()});
h.on('error',()=>{result.host=false;done()});h.on('timeout',()=>{result.host=false;h.destroy();done()});});
c.on('error',()=>{result.internal=false;s.close();done()});});
let wrote=false;function done(){if(wrote)return;wrote=true;fs.writeFileSync('evidence.json',JSON.stringify(result))}""".replace("HOSTPORT", str(host.getsockname()[1]))
            env = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "USERPROFILE",
                                                      "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA", "PATH") if key in os.environ}
            env.update({"TEMP": str(tmp_path), "TMP": str(tmp_path)})
            assert run_in_appcontainer(profile, [str(executable), "-e", script], cwd=tmp_path, env=env, timeout=10) == 0
            assert json.loads((tmp_path / "evidence.json").read_text()) == {"internal": True, "host": False}
            module_env = {**env, "NODE_OPTIONS": "--preserve-symlinks --preserve-symlinks-main"}
            module_script = "const fs=require('fs'),path=require('path');try{const m=require(path.join(process.cwd(),'client.cjs'));fs.writeFileSync('module.json',JSON.stringify({loaded:typeof m.createBridge==='function'}))}catch(e){fs.writeFileSync('module.json',JSON.stringify({error:e.code||String(e)}));process.exit(1)}"
            default_exit = run_in_appcontainer(profile, [str(executable), "-e", module_script], cwd=tmp_path, env=env, timeout=5)
            default_result = json.loads((tmp_path / "module.json").read_text())
            assert (default_exit == 0 and default_result == {"loaded": True}) or (default_exit == 1 and default_result.get("error") in {"EPERM", "EACCES"})
            module_exit = run_in_appcontainer(profile, [str(executable), "-e", module_script], cwd=tmp_path, env=module_env, timeout=5)
            assert module_exit == 0, (tmp_path / "module.json").read_text()
            assert json.loads((tmp_path / "module.json").read_text()) == {"loaded": True}
            with pytest.raises(TimeoutError):
                host.accept()
            output = tmp_path / "stdout.txt"
            observed = []
            original_bind = OwnedJobBinding._bind
            def record_binding(self, job, pid):
                if not observed:
                    assert not (tmp_path / "resumed").exists()
                original_bind(self, job, pid)
                observed.append(pid)
            monkeypatch.setattr(OwnedJobBinding, "_bind", record_binding)
            binding = OwnedJobBinding()
            with open(os.devnull, "rb") as stdin, output.open("wb") as stdout, open(os.devnull, "wb") as stderr:
                assert run_in_appcontainer(profile, [str(executable), "-e", "require('fs').writeFileSync('resumed','yes');process.stdout.write('STDIO_OK')"],
                                           cwd=tmp_path, env=env, timeout=28_800,
                                           stdio=(stdin.fileno(), stdout.fileno(), stderr.fileno()), binding=binding) == 0
            assert observed and (tmp_path / "resumed").read_text() == "yes"
            with pytest.raises(RuntimeError):
                binding.stop({"pid": 1})
            with pytest.raises(RuntimeError, match="cannot be reused"):
                run_in_appcontainer(profile, [str(executable), "-e", "require('fs').writeFileSync('must-not-run','bad')"],
                                    cwd=tmp_path, env=env, timeout=5, binding=binding)
            assert not (tmp_path / "must-not-run").exists()
            assert output.read_text() == "STDIO_OK"
            from local_ai_hub import opencode_container_process as runner
            captured = []
            original_assign = runner.assign_process_to_job
            def capture_job(job, pid):
                captured.append(pid)
                return original_assign(job, pid)
            def interrupt(*_args):
                raise KeyboardInterrupt()
            with monkeypatch.context() as patch:
                patch.setattr(runner, "assign_process_to_job", capture_job)
                patch.setattr(runner, "_wait_process", interrupt)
                with pytest.raises(KeyboardInterrupt):
                    run_in_appcontainer(profile, [str(executable), "-e", "setTimeout(()=>{},30000)"],
                                        cwd=tmp_path, env=env, timeout=28_800)
            assert captured
            from local_ai_hub.process_utils import _windows_process_identity
            assert _windows_process_identity(captured[0]) is None
            from local_ai_hub.opencode_pipe_service import PipeService
            with PipeService(profile.sid, b"x" * 32, 1234) as service:
                checks = []
                def fail_health():
                    checks.append(True)
                    if len(checks) >= 2:
                        raise RuntimeError("relay unhealthy")
                captured.clear()
                with monkeypatch.context() as patch:
                    patch.setattr(runner, "assign_process_to_job", capture_job)
                    patch.setattr(service, "check_health", fail_health)
                    with pytest.raises(RuntimeError, match="relay unhealthy"):
                        run_in_appcontainer(profile, [str(executable), "-e", "setTimeout(()=>{},30000)"],
                                            cwd=tmp_path, env=env, timeout=28_800, services=(service,))
                assert len(checks) >= 2 and captured and _windows_process_identity(captured[0]) is None
            udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            udp.bind(("127.0.0.1", 0))
            udp.settimeout(0.5)
            try:
                with tempfile.TemporaryDirectory(prefix="lah-host-boundary-") as outside, tempfile.TemporaryDirectory(prefix="lah-private-boundary-") as private:
                    outside_file = Path(outside) / "private.txt"
                    outside_file.write_text("host-only test marker")
                    junction = tmp_path / "outside-junction"
                    made = subprocess.run([os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", "mklink", "/J", str(junction), outside],
                                          capture_output=True, timeout=10, check=False)
                    assert made.returncode == 0
                    junction_probe = "const fs=require('fs');let read=false;try{read=fs.readFileSync('outside-junction/private.txt','utf8')==='host-only test marker'}catch(e){};fs.writeFileSync('junction.json',JSON.stringify({read}))"
                    assert run_in_appcontainer(profile, [str(executable), "-e", junction_probe], cwd=tmp_path, env=module_env, timeout=5) == 0
                    assert json.loads((tmp_path / "junction.json").read_text()) == {"read": False}
                    grant_outside = subprocess.run(["icacls", outside, "/grant", f"*{profile.sid}:(OI)(CI)(RX)", "/T", "/C"],
                                                   capture_output=True, timeout=15, check=False)
                    assert grant_outside.returncode == 0
                    assert run_in_appcontainer(profile, [str(executable), "-e", junction_probe], cwd=tmp_path, env=module_env, timeout=5) == 0
                    assert json.loads((tmp_path / "junction.json").read_text()) == {"read": True}
                    # Resetting access would change unrelated ACLs in a real project;
                    # the following denial probe uses a separate untouched file.
                    outside_file = Path(private) / "private.txt"
                    outside_file.write_text("host-only test marker")
                    probe = """const fs=require('fs'),dgram=require('dgram');let read=false;
try{fs.readFileSync(OUTSIDE);read=true}catch(e){}
const s=dgram.createSocket('udp4');let done=false;
function finish(){if(done)return;done=true;try{s.close()}catch(e){};fs.writeFileSync('boundary.json',JSON.stringify({outsideRead:read}))}
s.on('error',finish);s.send(Buffer.from('test'),HOSTPORT,'127.0.0.1',finish);setTimeout(finish,500);"""
                    probe = probe.replace("OUTSIDE", json.dumps(str(outside_file))).replace("HOSTPORT", str(udp.getsockname()[1]))
                    assert run_in_appcontainer(profile, [str(executable), "-e", probe], cwd=tmp_path, env=env, timeout=5) == 0
                    assert json.loads((tmp_path / "boundary.json").read_text()) == {"outsideRead": False}
                    with pytest.raises(TimeoutError):
                        udp.recvfrom(1024)
                    powershell = Path(os.environ["SYSTEMROOT"]) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
                    if powershell.is_file():
                        escaped = str(outside_file).replace("'", "''")
                        command = (f"$r=$false;try{{$null=[IO.File]::ReadAllText('{escaped}');$r=$true}}catch{{}};"
                                   "$h=$false;try{$c=[Net.Sockets.TcpClient]::new();"
                                   f"$a=$c.BeginConnect('127.0.0.1',{host.getsockname()[1]},$null,$null);"
                                   "if($a.AsyncWaitHandle.WaitOne(500)){$c.EndConnect($a);$h=$true};$c.Close()"
                                   "}catch{};[IO.File]::WriteAllText('child-boundary.json',('{\"outsideRead\":'+$r.ToString().ToLower()+',\"hostConnect\":'+$h.ToString().ToLower()+'}'))")
                        nested = ("const c=require('child_process').spawn(" + json.dumps(str(powershell))
                                  + ",['-NoProfile','-NonInteractive','-Command'," + json.dumps(command)
                                  + "],{stdio:'inherit'});c.on('exit',code=>process.exit(code));c.on('error',()=>process.exit(9))")
                        with open(os.devnull, "rb") as stdin, (tmp_path / "nested.log").open("wb") as stdout, (tmp_path / "nested-error.log").open("wb") as stderr:
                            assert run_in_appcontainer(profile, [str(executable), "-e", nested], cwd=tmp_path, env=env, timeout=15,
                                                       stdio=(stdin.fileno(), stdout.fileno(), stderr.fileno())) == 0
                        child = json.loads((tmp_path / "child-boundary.json").read_text(encoding="utf-8-sig"))
                        assert child == {"outsideRead": False, "hostConnect": False}
                        with pytest.raises(TimeoutError):
                            host.accept()
            finally:
                udp.close()
            with pytest.raises(TimeoutError, match="process timed out"):
                run_in_appcontainer(profile, [str(executable), "-e", "require('fs').writeFileSync('pid',String(process.pid));setTimeout(()=>{},30000)"],
                                    cwd=tmp_path, env=env, timeout=1)
            import ctypes
            from ctypes import wintypes
            pid = int((tmp_path / "pid").read_text())
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel.WaitForSingleObject.restype = wintypes.DWORD
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel.OpenProcess(0x00100000, False, pid)
            if handle:
                try:
                    assert kernel.WaitForSingleObject(handle, 3000) == 0
                finally:
                    kernel.CloseHandle(handle)
    finally:
        host.close()


def test_rejects_malformed_environment_before_launch(tmp_path):
    with AppContainerProfile() as profile:
        command = [str(Path(os.environ["SYSTEMROOT"]) / "System32" / "cmd.exe")]
        with pytest.raises(ValueError):
            run_in_appcontainer(profile, command, cwd=tmp_path, env={"A=B": "bad"}, timeout=2)
        for stdio in ((0, 1), (0, True, 2), (0, 1, -1), (0, 1, 999999)):
            with pytest.raises(ValueError):
                run_in_appcontainer(profile, command, cwd=tmp_path, env={}, timeout=2, stdio=stdio)
        with pytest.raises(ValueError):
            run_in_appcontainer(profile, command, cwd=tmp_path, env={}, timeout=43_201)


def test_process_wait_yields_regularly_for_interrupts():
    from local_ai_hub.opencode_container_process import _wait_process

    class Kernel:
        def __init__(self): self.waits = []
        def WaitForSingleObject(self, handle, millis):
            self.waits.append(millis)
            return 0 if len(self.waits) == 3 else 258
    kernel = Kernel()
    _wait_process(kernel, 42, 28_800)
    assert len(kernel.waits) == 3 and all(1 <= delay <= 250 for delay in kernel.waits)


def test_unlisted_inheritable_handle_is_not_exposed(tmp_path):
    import ctypes
    import msvcrt
    from ctypes import wintypes

    compiler = Path(os.environ["SYSTEMROOT"]) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
    if not compiler.is_file():
        pytest.skip("Windows .NET Framework compiler unavailable")
    source, executable = tmp_path / "probe.cs", tmp_path / "probe.exe"
    source.write_text(r'''using System;using System.Text;using System.Runtime.InteropServices;
class Probe {[DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern uint GetFinalPathNameByHandle(IntPtr h,StringBuilder b,uint n,uint f);
[DllImport("kernel32.dll")] static extern IntPtr GetStdHandle(int n);
static int Main(string[] a){var b=new StringBuilder(32768);var h=a[0]=="stdout"?GetStdHandle(-11):new IntPtr(long.Parse(a[0]));uint n=GetFinalPathNameByHandle(h,b,(uint)b.Capacity,0);string p=b.ToString();if(p.StartsWith(@"\\?\"))p=p.Substring(4);bool found=n>0&&n<b.Capacity&&String.Equals(p,a[1],StringComparison.OrdinalIgnoreCase);Console.Error.Write(found?"FOUND":"BLOCKED");return 0;}}''')
    compiled = subprocess.run([str(compiler), "/nologo", "/out:" + str(executable), str(source)], capture_output=True, timeout=20, check=False)
    assert compiled.returncode == 0, compiled.stderr.decode(errors="replace")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.SetHandleInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
    kernel.SetHandleInformation.restype = wintypes.BOOL
    env = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA", "PATH") if key in os.environ}
    env.update({"TEMP": str(tmp_path), "TMP": str(tmp_path)})
    with AppContainerProfile() as profile:
        for options in (["/grant", f"*{profile.sid}:(OI)(CI)(F)"], ["/setintegritylevel", "(OI)(CI)L"]):
            grant = subprocess.run(["icacls", str(tmp_path), *options, "/T", "/C"], capture_output=True, timeout=15, check=False)
            assert grant.returncode == 0
        sentinel = tmp_path / "host-only-handle.bin"
        output, positive, negative = tmp_path / "output.txt", tmp_path / "positive.txt", tmp_path / "negative.txt"
        with sentinel.open("wb") as hidden, open(os.devnull, "rb") as stdin, output.open("wb") as stdout, positive.open("wb") as yes, negative.open("wb") as no:
            raw = msvcrt.get_osfhandle(hidden.fileno())
            assert kernel.SetHandleInformation(raw, 1, 1)
            try:
                assert run_in_appcontainer(profile, [str(executable), "stdout", str(sentinel)], cwd=tmp_path, env=env, timeout=15,
                                           stdio=(stdin.fileno(), hidden.fileno(), yes.fileno())) == 0
                negative_code = run_in_appcontainer(profile, [str(executable), str(raw), str(sentinel)], cwd=tmp_path, env=env, timeout=15,
                                                    stdio=(stdin.fileno(), stdout.fileno(), no.fileno()))
            finally:
                assert kernel.SetHandleInformation(raw, 1, 0)
        assert positive.read_text() == "FOUND"
        assert (negative_code == 0 and negative.read_text() == "BLOCKED") or negative_code == 0xC0000008
        assert sentinel.read_bytes() == b""
