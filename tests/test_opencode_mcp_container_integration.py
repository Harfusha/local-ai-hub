"""Offline staging probe; not installer or live Hub acceptance."""
import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from local_ai_hub.opencode_sandbox_session import SandboxSession
from tools.opencode_install import VERSION, WINDOWS_X64_EXECUTABLE_SHA256

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows AppContainer")
ROOT = Path(__file__).resolve().parents[1]


def _copy_local_runtime(destination):
    from local_ai_hub.opencode_runtime_stage import stage_runtime
    return stage_runtime(destination)


def test_existing_mcp_adapter_imports_in_appcontainer_without_live_hub(tmp_path):
    python = _copy_local_runtime(tmp_path)
    config = tmp_path / "client.toml"
    env = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA", "PATH") if key in os.environ}
    site = python.parent / "Lib" / "site-packages"
    env.update({"TEMP": str(tmp_path), "TMP": str(tmp_path),
                "PYTHONPATH": os.pathsep.join(str(path) for path in (tmp_path / "src", site / "win32", site / "win32" / "lib", site / "pythonwin")),
                "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1", "LOCAL_AI_AGENT": "opencode-local",
                "LOCAL_AI_AGENT_PROFILE": "opencode-local", "LOCAL_AI_CONFIG": str(config)})
    with SandboxSession(1, 1) as session:
        profile = session.profile
        runtime, client_toml = session.build_runtime_config({"server": {"port": 1}}, install_dir=tmp_path,
                                                            hub_python=python, client_config=config, model="model-a")
        config.write_text(client_toml, encoding="utf-8")
        assert runtime["plugins"][1]["options"]["server"]["environment"]["LOCAL_AI_CONFIG"] == str(config)
        for options in (["/grant", f"*{profile.sid}:(OI)(CI)(F)"], ["/setintegritylevel", "(OI)(CI)L"]):
            result = subprocess.run(["icacls", str(tmp_path), *options, "/T", "/C"], capture_output=True, timeout=30, check=False)
            assert result.returncode == 0
        stdout, stderr, input_file = tmp_path / "stdout.txt", tmp_path / "stderr.txt", tmp_path / "input.txt"
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "offline-test", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        ]
        input_file.write_text("".join(json.dumps(message) + "\n" for message in messages), encoding="utf-8")
        with input_file.open("rb") as stdin, stdout.open("wb") as output, stderr.open("wb") as error:
            code = session.run([str(python), "-c", "import mcp.server.fastmcp; import jwt; from cryptography.hazmat.primitives.asymmetric import rsa; import local_ai_hub.mcp_server as m; assert m.FastMCP is not None and m.mcp is not None; m.main()"],
                               cwd=tmp_path, env=env, timeout=20, stdio=(stdin.fileno(), output.fileno(), error.fileno()))
        assert code == 0, stderr.read_text(encoding="utf-8", errors="replace")[-2000:]
        responses = [json.loads(line) for line in stdout.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
        assert any(response.get("id") == 1 and "result" in response for response in responses)
        assert any(response.get("id") == 2 and any(tool.get("name") == "local_ai_status" for tool in response.get("result", {}).get("tools", [])) for response in responses)


def test_mcp_search_and_status_cross_authenticated_sandbox_bridge(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable")
    python = _copy_local_runtime(tmp_path)
    node_copy = tmp_path / "node.exe"
    shutil.copyfile(node, node_copy)
    bootstrap = tmp_path / "bootstrap.cjs"
    bridge = tmp_path / "bridge.cjs"
    shutil.copyfile(ROOT / "tools" / "opencode_sandbox_bootstrap.cjs", bootstrap)
    shutil.copyfile(ROOT / "tools" / "opencode_pipe_client.cjs", bridge)
    received = []

    class FakeHub(BaseHTTPRequestHandler):
        def do_GET(self):
            received.append(self.path)
            ok = self.path == "/api/live/status?light=1"
            body = json.dumps({"hub_online": ok, "version": "fake-status-bridge-test", "scheduler": {}}).encode()
            self.send_response(200 if ok else 403)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            received.append(self.path)
            ok = self.path == "/api/search"
            body = json.dumps({"success": ok, "results": [{"path": "fake-hub-bridge-test"}]}).encode()
            self.send_response(200 if ok else 403)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeHub)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        config = tmp_path / "client.toml"
        site = python.parent / "Lib" / "site-packages"
        env = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA", "PATH") if key in os.environ}
        env.update({"TEMP": str(tmp_path), "TMP": str(tmp_path),
                    "PYTHONPATH": os.pathsep.join(str(path) for path in (tmp_path / "src", site / "win32", site / "win32" / "lib", site / "pythonwin")),
                    "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1", "LOCAL_AI_AGENT": "opencode-local",
                    "LOCAL_AI_AGENT_PROFILE": "opencode-local", "LOCAL_AI_CONFIG": str(config),
                    "LOCAL_AI_BOOTSTRAP_CLIENT": str(bridge), "LOCAL_AI_BOOTSTRAP_EXECUTABLE": str(python),
                    "LOCAL_AI_BOOTSTRAP_PROJECT": str(tmp_path), "LOCAL_AI_BOOTSTRAP_ARGS": json.dumps(["-m", "local_ai_hub.mcp_server"])})
        with SandboxSession(server.server_port, server.server_port) as session:
            _, client_toml = session.build_runtime_config({"server": {"port": server.server_port}}, install_dir=tmp_path,
                                                          hub_python=python, client_config=config, model="model-a")
            config.write_text(client_toml, encoding="utf-8")
            for options in (["/grant", f"*{session.profile.sid}:(OI)(CI)(F)"], ["/setintegritylevel", "(OI)(CI)L"]):
                result = subprocess.run(["icacls", str(tmp_path), *options, "/T", "/C"], capture_output=True, timeout=30, check=False)
                assert result.returncode == 0
            messages = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "bridge-test", "version": "1"}}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "local_ai_repo", "arguments": {"action": "search", "root": str(tmp_path), "query": "bridge-test"}}},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "local_ai_status", "arguments": {}}},
            ]
            read_fd, write_fd = os.pipe()
            response_read, response_write = os.pipe()
            response_received = threading.Event()
            responses = []
            def read_responses():
                with os.fdopen(response_read, "rb") as stream:
                    for line in stream:
                        response = json.loads(line)
                        responses.append(response)
                        if {2, 3}.issubset({item.get("id") for item in responses}):
                            response_received.set()
            def send_messages():
                with os.fdopen(write_fd, "wb") as stream:
                    stream.write("".join(json.dumps(message) + "\n" for message in messages).encode())
                    stream.flush()
                    response_received.wait(18)
            reader = threading.Thread(target=read_responses, daemon=True)
            reader.start()
            writer = threading.Thread(target=send_messages, daemon=True)
            writer.start()
            stderr = tmp_path / "stderr.txt"
            loader = "const fs=require('node:fs'),M=require('node:module');const m=new M('bootstrap');m._compile(fs.readFileSync(process.argv[1],'utf8'),'bootstrap.cjs');m.exports.main()"
            try:
                with stderr.open("wb") as error:
                    code = session.run([str(node_copy), "-e", loader, str(bootstrap)], cwd=tmp_path, env=env, timeout=25,
                                       stdio=(read_fd, response_write, error.fileno()))
            finally:
                os.close(read_fd)
                os.close(response_write)
                writer.join(timeout=20)
                reader.join(timeout=5)
            assert code == 0, stderr.read_text(encoding="utf-8", errors="replace")[-2000:]
            assert response_received.is_set()
            assert sorted(received) == sorted(["/api/search", "/api/live/status?light=1"])
            assert any(response.get("id") == 2 and "fake-hub-bridge-test" in json.dumps(response.get("result")) for response in responses)
            assert any(response.get("id") == 3 and "fake-status-bridge-test" in json.dumps(response.get("result")) for response in responses)
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)


@pytest.fixture
def private_stage(tmp_path):
    from local_ai_hub.opencode_private_stage import PrivateStage
    with PrivateStage(tmp_path) as stage:
        yield stage


def test_opencode_invokes_mcp_search_inside_sandbox(private_stage):
    import win32security
    import ntsecuritycon
    tmp_path = private_stage.path
    project = tmp_path.parent / "disposable-project"
    project.mkdir()
    marker = project / "existing.py"
    marker.write_text("original\n", encoding="utf-8")
    def descriptor(path):
        return win32security.GetFileSecurity(str(path), win32security.DACL_SECURITY_INFORMATION)
    def dacl_string(path):
        return win32security.ConvertSecurityDescriptorToStringSecurityDescriptor(descriptor(path), win32security.SDDL_REVISION_1, win32security.DACL_SECURITY_INFORMATION)
    baseline = {str(path): dacl_string(path) for path in (project, marker)}
    principal = None
    session = None
    installed = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "OpenCode-LocalAIHub" / VERSION / "opencode.exe"
    node = shutil.which("node")
    if not node or not installed.is_file():
        pytest.skip("pinned OpenCode or Node unavailable")
    from local_ai_hub.opencode_runtime_stage import stage_session_bundle, _OPENCODE_SHA256
    assert _OPENCODE_SHA256 == WINDOWS_X64_EXECUTABLE_SHA256
    staged = stage_session_bundle(tmp_path, ROOT, installed, Path(node))
    python = staged["python"]
    # The shim is limited to this offline test and is not production isolation.
    (tmp_path / "taskkill.cmd").write_text('@powershell.exe -NoProfile -Command "Stop-Process -Id %2 -Force -ErrorAction Stop"\r\n', encoding="ascii")
    calls = []
    traffic = []
    invoked = threading.Event()
    edited = threading.Event()

    class FakeServices(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            traffic.append(self.path)
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path == "/api/search":
                calls.append(self.path)
                body = json.dumps({"success": True, "results": [{"path": "mcp-bridge-result"}]}).encode()
                content_type = "application/json"
            else:
                names = [t.get("function", {}).get("name", "") for t in request.get("tools", [])]
                matches = [name for name in names if name.endswith("local_ai_repo")]
                common = {"id": "test", "object": "chat.completion.chunk", "created": 1, "model": "model-a"}
                if "shell" in names and not edited.is_set():
                    edited.set()
                    output_path = str(project / "created.py").replace("'", "''")
                    shell_command = f"Set-Content -LiteralPath '{output_path}' -Value 'answer = 42'; Get-Content -LiteralPath '{output_path}'"
                    call = {"index": 0, "id": "edit_call", "type": "function", "function": {"name": "shell", "arguments": json.dumps({"command": shell_command, "timeout": 5000})}}
                    choices = [{"index": 0, "delta": {"role": "assistant", "tool_calls": [call]}, "finish_reason": None},
                               {"index": 0, "delta": {}, "finish_reason": "tool_calls"}]
                elif matches and not invoked.is_set():
                    invoked.set()
                    call = {"index": 0, "id": "mcp_call", "type": "function", "function": {"name": matches[0], "arguments": json.dumps({"action": "search", "root": str(project), "query": "bridge-test"})}}
                    choices = [{"index": 0, "delta": {"role": "assistant", "tool_calls": [call]}, "finish_reason": None},
                               {"index": 0, "delta": {}, "finish_reason": "tool_calls"}]
                else:
                    choices = [{"index": 0, "delta": {"role": "assistant", "content": "MCP_TEST_FINISHED"}, "finish_reason": None},
                               {"index": 0, "delta": {}, "finish_reason": "stop"}]
                body = ("".join("data: " + json.dumps({**common, "choices": [choice]}) + "\n\n" for choice in choices) + "data: [DONE]\n\n").encode()
                content_type = "text/event-stream"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeServices)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        with SandboxSession(server.server_port, server.server_port) as session:
            principal = win32security.ConvertStringSidToSid(session.profile.sid)
            mask = ntsecuritycon.FILE_GENERIC_READ | ntsecuritycon.FILE_GENERIC_WRITE | ntsecuritycon.FILE_GENERIC_EXECUTE | ntsecuritycon.DELETE
            for item in (project, marker):
                sd = descriptor(item)
                acl = sd.GetSecurityDescriptorDacl()
                acl.AddAccessAllowedAceEx(win32security.ACL_REVISION, 0, mask, principal)
                if item == project:
                    flags = win32security.OBJECT_INHERIT_ACE | win32security.CONTAINER_INHERIT_ACE | win32security.INHERIT_ONLY_ACE
                    acl.AddAccessAllowedAceEx(win32security.ACL_REVISION, flags, mask, principal)
                sd.SetSecurityDescriptorDacl(1, acl, 0)
                win32security.SetFileSecurity(str(item), win32security.DACL_SECURITY_INFORMATION, sd)
            client_config = tmp_path / "client.toml"
            config, client_toml = session.build_runtime_config({"server": {"port": server.server_port}}, install_dir=tmp_path,
                                                               hub_python=python, client_config=client_config, model="model-a")
            client_config.write_text(client_toml, encoding="utf-8")
            home_dir = tmp_path / "home"
            home_dir.mkdir()
            env = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "PATH", "COMSPEC", "PATHEXT") if key in os.environ}
            env.update({"PATH": str(tmp_path) + ";" + env.get("PATH", ""),
                        **{key: str(tmp_path) for key in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME", "TEMP", "TMP")},
                        "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
                        "LOCAL_AI_BOOTSTRAP_CLIENT": str(staged["client"]), "LOCAL_AI_BOOTSTRAP_EXECUTABLE": str(staged["opencode"]),
                        "LOCAL_AI_BOOTSTRAP_PROJECT": str(project),
                        "LOCAL_AI_BOOTSTRAP_ARGS": json.dumps(["run", "--auto", "--format", "json", "--standalone", "--print-logs", "--log-level", "debug", "--model", "local-hub/model-a", "Search"]),
                        "LOCAL_AI_OPENCODE_PROVIDER_TOKEN": "fake", "OPENCODE_CONFIG_CONTENT": json.dumps(config)})
            env["HOME"] = env["USERPROFILE"] = str(home_dir)
            private_stage.grant(session)
            loader = "const fs=require('node:fs'),M=require('node:module');const m=new M('bootstrap');m._compile(fs.readFileSync(process.argv[1],'utf8'),'bootstrap.cjs');m.exports.main()"
            output, errors = tmp_path / "events.log", tmp_path / "errors.log"
            try:
                with open(os.devnull, "rb") as stdin, output.open("wb") as stdout, errors.open("wb") as stderr:
                    code = session.run([str(staged["node"]), "-e", loader, str(staged["bootstrap"])], cwd=tmp_path, env=env, timeout=45,
                                       stdio=(stdin.fileno(), stdout.fileno(), stderr.fileno()))
            except TimeoutError:
                tail = errors.read_text(encoding="utf-8", errors="replace")[-5000:]
                pytest.fail(f"sandbox timed out; fake service paths={traffic!r}; stderr tail={tail}")
            events = output.read_text(encoding="utf-8", errors="replace")
            assert code == 0, f"traffic={traffic!r}; events={events[-2000:]}; errors={errors.read_text(encoding='utf-8', errors='replace')[-3000:]}"
            assert edited.is_set() and (project / "created.py").read_text(encoding="utf-8").strip() == "answer = 42"
            assert invoked.is_set(), events[-2000:]
            assert calls == ["/api/search"]
            assert "mcp-bridge-result" in events and "MCP_TEST_FINISHED" in events
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)
        if principal is not None and session is not None and session.cleanup_confirmed:
            for directory, names, files in os.walk(project, topdown=False, followlinks=False):
                for item in [*(Path(directory) / name for name in files), *(Path(directory) / name for name in names), Path(directory)]:
                    if item.is_symlink() or getattr(item.lstat(), "st_file_attributes", 0) & 0x400:
                        raise RuntimeError("unexpected reparse point in disposable project")
                    sd = descriptor(item)
                    acl = sd.GetSecurityDescriptorDacl()
                    for index in reversed(range(acl.GetAceCount())):
                        if acl.GetAce(index)[-1] == principal:
                            acl.DeleteAce(index)
                    sd.SetSecurityDescriptorDacl(1, acl, 0)
                    win32security.SetFileSecurity(str(item), win32security.DACL_SECURITY_INFORMATION, sd)
            assert {str(path): dacl_string(path) for path in (project, marker)} == baseline
            if (project / "created.py").exists():
                assert win32security.ConvertSidToStringSid(principal) not in dacl_string(project / "created.py")
