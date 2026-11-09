from pathlib import Path
import os
import socket
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_invalid_bootstrap_never_retains_transport_secret():
    script = r'''
const assert=require('node:assert/strict'),crypto=require('node:crypto'),path=require('node:path');
const {main}=require('./tools/opencode_sandbox_bootstrap.cjs');
const pipeSecretName=['LOCAL_AI_PIPE','SECRET'].join('_');
const valid={[pipeSecretName]:crypto.randomBytes(32).toString('hex'),LOCAL_AI_PIPE_NAME:'bad',LOCAL_AI_CLIENT_PORT:'49152',
 LOCAL_AI_BOOTSTRAP_CLIENT:path.resolve('tools/opencode_pipe_client.cjs'),LOCAL_AI_BOOTSTRAP_EXECUTABLE:path.resolve('fake.exe'),
 LOCAL_AI_BOOTSTRAP_PROJECT:process.cwd(),LOCAL_AI_BOOTSTRAP_ARGS:'[42]'};
for(const change of [{LOCAL_AI_PIPE_SECRET:'invalid'}, {LOCAL_AI_CLIENT_PORT:'65536'}, {LOCAL_AI_CLIENT_PORT:'1023'}, {LOCAL_AI_CLIENT_PORT:'01024'}, {LOCAL_AI_BOOTSTRAP_ARGS:'[42]'}]){
 Object.assign(process.env,valid,change);assert.throws(main);assert.equal(process.env[pipeSecretName],undefined);
 assert.equal(process.env.LOCAL_AI_BOOTSTRAP_ARGS,undefined);
}
if(process.platform==='win32'){
 Object.assign(process.env,valid,{LOCAL_AI_BOOTSTRAP_CLIENT:'\\\\.\\pipe\\arbitrary',LOCAL_AI_BOOTSTRAP_ARGS:'[]'});
 assert.throws(main,/invalid sandbox bootstrap configuration/);assert.equal(process.env[pipeSecretName],undefined);
}'''
    result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr


def test_bridge_source_read_is_bounded_even_if_file_grows(tmp_path):
    oversized = tmp_path / "oversized.cjs"
    oversized.write_bytes(b"x" * (1024 * 1024))
    script = r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {main}=require('./tools/opencode_sandbox_bootstrap.cjs');const file=process.argv[1];
const valid={LOCAL_AI_PIPE_SECRET:'ab'.repeat(32),LOCAL_AI_PIPE_NAME:'\\\\.\\pipe\\lah-opencode-'+ 'a'.repeat(32),LOCAL_AI_CLIENT_PORT:'49152',
 LOCAL_AI_BOOTSTRAP_CLIENT:file,LOCAL_AI_BOOTSTRAP_EXECUTABLE:path.resolve('fake.exe'),
 LOCAL_AI_BOOTSTRAP_PROJECT:process.cwd(),LOCAL_AI_BOOTSTRAP_ARGS:'[]'};
const originalRead=fs.readSync, originalStat=fs.fstatSync;let bytes=0;
fs.readFileSync=()=>{throw Error('unbounded read')};
fs.readSync=(...a)=>{const n=originalRead(...a);bytes+=n;return n};
Object.assign(process.env,valid);assert.throws(main,/too large/);assert.equal(bytes,0);
fs.fstatSync=()=>({isFile:()=>true,size:0});Object.assign(process.env,valid);assert.throws(main,/too large/);
assert.ok(bytes<=262145);fs.fstatSync=originalStat;fs.readSync=originalRead;
'''
    result = subprocess.run(["node", "-e", script, str(oversized)], cwd=ROOT, capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr


def test_missing_child_reports_bounded_error_without_secret(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    if port < 1024:
        import pytest
        pytest.skip("ephemeral port is outside bootstrap range")
    secret = "ab" * 32
    env = {**os.environ, "LOCAL_AI_PIPE_SECRET": secret,
           "LOCAL_AI_PIPE_NAME": r"\\.\pipe\lah-opencode-" + "a" * 32,
           "LOCAL_AI_CLIENT_PORT": str(port),
           "LOCAL_AI_BOOTSTRAP_CLIENT": str(ROOT / "tools" / "opencode_pipe_client.cjs"),
           "LOCAL_AI_BOOTSTRAP_EXECUTABLE": str(tmp_path / "missing.exe"),
           "LOCAL_AI_BOOTSTRAP_PROJECT": str(tmp_path), "LOCAL_AI_BOOTSTRAP_ARGS": "[]"}
    result = subprocess.run(["node", str(ROOT / "tools" / "opencode_sandbox_bootstrap.cjs")],
                            env=env, cwd=tmp_path, capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode != 0 and "sandbox bootstrap: child process failed" in result.stderr
    assert secret not in result.stdout + result.stderr


def test_windows_reserved_port_probe_identifies_transport_failure(tmp_path):
    import shutil
    import pytest
    if os.name != "nt":
        pytest.skip("Windows excluded TCP range")
    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable")
    reserved = 49700
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", reserved))
        except OSError as error:
            if getattr(error, "winerror", None) != 10013:
                pytest.skip("known excluded port is unavailable for another reason")
        else:
            pytest.skip("this system does not exclude the probe port")
    from local_ai_hub.opencode_private_stage import PrivateStage
    from local_ai_hub.opencode_sandbox_session import SandboxSession
    with PrivateStage(tmp_path) as stage:
        exe = stage.path / "node.exe"
        client = stage.path / "client.cjs"
        bootstrap = stage.path / "bootstrap.cjs"
        shutil.copyfile(node, exe)
        shutil.copyfile(ROOT / "tools" / "opencode_pipe_client.cjs", client)
        shutil.copyfile(ROOT / "tools" / "opencode_sandbox_bootstrap.cjs", bootstrap)
        env = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA", "PATH") if key in os.environ}
        env.update({"TEMP": str(stage.path), "TMP": str(stage.path),
                    "LOCAL_AI_BOOTSTRAP_CLIENT": str(client), "LOCAL_AI_BOOTSTRAP_EXECUTABLE": str(exe),
                    "LOCAL_AI_BOOTSTRAP_PROJECT": str(stage.path), "LOCAL_AI_BOOTSTRAP_ARGS": '["-e", ""]'})
        with SandboxSession(1, 1) as session:
            session.client_port = reserved
            stage.grant(session)
            error_path = stage.path / "error.log"
            loader = "const fs=require('node:fs'),M=require('node:module');const m=new M('bootstrap');m._compile(fs.readFileSync(process.argv[1],'utf8'),'bootstrap.cjs');m.exports.main()"
            with open(os.devnull, "rb") as stdin, open(os.devnull, "wb") as stdout, error_path.open("wb") as stderr:
                code = session.run([str(exe), "-e", loader, str(bootstrap)], cwd=stage.path, env=env, timeout=10,
                                   stdio=(stdin.fileno(), stdout.fileno(), stderr.fileno()))
            assert code != 0
            assert "local transport failed (EACCES)" in error_path.read_text(encoding="utf-8", errors="replace")
