"""Real CLI smoke with a fake model; this does not establish production isolation."""
import json
import os
import shutil
import subprocess
import threading
from contextlib import nullcontext
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from local_ai_hub.opencode_sandbox_session import SandboxSession
from tools.opencode_install import VERSION, WINDOWS_X64_EXECUTABLE_SHA256, _file_digest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows AppContainer")
ROOT = Path(__file__).resolve().parents[1]


def test_pinned_opencode_uses_pipe_for_fake_model_and_exits(tmp_path):
    installed = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "OpenCode-LocalAIHub" / VERSION / "opencode.exe"
    node = shutil.which("node")
    if not node or not installed.is_file():
        pytest.skip("pinned OpenCode or Node unavailable")
    assert _file_digest(installed) == WINDOWS_X64_EXECUTABLE_SHA256
    shutil.copyfile(installed, tmp_path / "opencode.exe")
    shutil.copyfile(node, tmp_path / "node.exe")
    shutil.copyfile(ROOT / "tools" / "opencode_pipe_client.cjs", tmp_path / "client.cjs")
    shutil.copyfile(ROOT / "tools" / "opencode_sandbox_bootstrap.cjs", tmp_path / "bootstrap.cjs")
    shutil.copyfile(ROOT / "tools" / "opencode_stop_client.ps1", tmp_path / "stop_client.ps1")
    goal = tmp_path / "tools" / "opencode_goal"
    goal.mkdir(parents=True)
    for name in ("index.js", "core.js", "transport.js", "package.json"):
        shutil.copyfile(ROOT / "tools" / "opencode_goal" / name, goal / name)
    # Test-only shim: LAC1 stops exactly one process, not the requested tree.
    (tmp_path / "taskkill.cmd").write_text(
        '@powershell.exe -NoProfile -NonInteractive -File "%~dp0stop_client.ps1" "%~2"\r\n', encoding="ascii")
    requests = []
    tool_names = set()
    tool_sent = threading.Event()
    goal_sent = threading.Event()
    tool_lock = threading.Lock()

    class FakeModel(BaseHTTPRequestHandler):
        def log_message(self, *_args): pass
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(self.path)
            common = {"id": "test", "object": "chat.completion.chunk", "created": 1, "model": "model-a"}
            with tool_lock:
                tool_names.update(t.get("function", {}).get("name") for t in request.get("tools", []))
                use_tool = not tool_sent.is_set() and any(t.get("function", {}).get("name") == "shell" for t in request.get("tools", []))
                if use_tool:
                    tool_sent.set()
                use_goal = (not use_tool and tool_sent.is_set() and not goal_sent.is_set()
                            and any(t.get("function", {}).get("name") == "goal_verify" for t in request.get("tools", [])))
                if use_goal:
                    goal_sent.set()
            if use_tool:
                call = {"index": 0, "id": "call_shell", "type": "function",
                        "function": {"name": "shell", "arguments": json.dumps({"command": "if ($env:LOCAL_AI_PIPE_SECRET) {exit 37} else {echo ISOLATED_TOOL_OK}", "timeout": 5000})}}
                choices = [{"index": 0, "delta": {"role": "assistant", "tool_calls": [call]}, "finish_reason": None},
                           {"index": 0, "delta": {}, "finish_reason": "tool_calls"}]
            elif use_goal:
                call = {"index": 0, "id": "call_goal", "type": "function",
                        "function": {"name": "goal_verify", "arguments": json.dumps({"alias": "test"})}}
                choices = [{"index": 0, "delta": {"role": "assistant", "tool_calls": [call]}, "finish_reason": None},
                           {"index": 0, "delta": {}, "finish_reason": "tool_calls"}]
            else:
                choices = [{"index": 0, "delta": {"role": "assistant", "content": "ISOLATED_MODEL_OK"}, "finish_reason": None},
                           {"index": 0, "delta": {}, "finish_reason": "stop"}]
            body = ("".join("data: " + json.dumps({**common, "choices": [choice]}) + "\n\n" for choice in choices)
                    + "data: [DONE]\n\n").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    model = ThreadingHTTPServer(("127.0.0.1", 0), FakeModel)
    threading.Thread(target=model.serve_forever, daemon=True).start()
    try:
        with SandboxSession(model.server_port, model.server_port) as session:
            profile, router = session.profile, session.router
            stops = []
            original_stop = session.binding.stop
            def record_stop(identity):
                result = original_stop(identity)
                stops.append((identity, result))
                return result
            session.binding.stop = record_stop
            for command in (["/grant", f"*{profile.sid}:(OI)(CI)(F)"], ["/setintegritylevel", "(OI)(CI)L"]):
                result = subprocess.run(["icacls", str(tmp_path), *command, "/T", "/C"], capture_output=True, timeout=15, check=False)
                assert result.returncode == 0
            with nullcontext(session.relay) as service:
                bootstrap = "const fs=require('node:fs'),M=require('node:module');const m=new M('bootstrap');m._compile(fs.readFileSync('bootstrap.cjs','utf8'),'bootstrap.cjs');m.exports.main()"
                env = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA", "PATH", "COMSPEC", "PATHEXT") if key in os.environ}
                env.update({"PATH": str(tmp_path) + ";" + env.get("PATH", ""),
                            **{key: str(tmp_path) for key in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME", "TEMP", "TMP")},
                            "LOCAL_AI_BOOTSTRAP_CLIENT": str(tmp_path / "client.cjs"),
                            "LOCAL_AI_BOOTSTRAP_EXECUTABLE": str(tmp_path / "opencode.exe"),
                            "LOCAL_AI_BOOTSTRAP_PROJECT": str(tmp_path),
                            "LOCAL_AI_BOOTSTRAP_ARGS": json.dumps(["run", "--auto", "--format", "json", "--standalone", "--model", "local-hub/model-a", "Say OK"]),
                            "LOCAL_AI_HUB_TOKEN": "test-profile-token", "LOCAL_AI_OPENCODE_PROVIDER_TOKEN": "fake"})
                config, _client_toml = session.build_runtime_config({"server": {"port": model.server_port}},
                                                                   install_dir=tmp_path, hub_python=tmp_path / "python.exe",
                                                                   client_config=tmp_path / "client.toml", model="model-a")
                # The MCP runtime is not staged in this smoke; do not imply MCP integration.
                del config["mcp"]
                config["plugins"] = config["plugins"][:1]
                env["OPENCODE_CONFIG_CONTENT"] = json.dumps(config)
                with pytest.raises(ValueError, match="reserved"):
                    session.run([str(tmp_path / "node.exe"), "-e", ""], cwd=tmp_path,
                                env={**env, "local_ai_pipe_secret": "override"}, timeout=2)
                output = tmp_path / "events.log"
                with open(os.devnull, "rb") as stdin, output.open("wb") as stdout, open(os.devnull, "wb") as stderr:
                    exit_code = session.run([str(tmp_path / "node.exe"), "-e", bootstrap], cwd=tmp_path,
                                            env=env, timeout=30, stdio=(stdin.fileno(), stdout.fileno(), stderr.fileno()))
                events = output.read_text(encoding="utf-8", errors="replace")
                assert exit_code == 0
                assert len(stops) == 1 and stops[0][1] is True
                assert Path(stops[0][0]["executable"]).name.lower() == "opencode.exe"
                assert "ISOLATED_MODEL_OK" in events and "step_finish" in events
                records = [json.loads(line) for line in events.splitlines() if line.startswith("{")]
                tool_results = [record.get("part", {}).get("state", {}) for record in records if record.get("type") == "tool_use"]
                assert tool_sent.is_set() and any(state.get("status") == "completed"
                                                   and "ISOLATED_TOOL_OK" in state.get("output", "")
                                                   and state.get("metadata", {}).get("metadata", {}).get("exit") == 0
                                                   for state in tool_results)
                assert goal_sent.is_set()
                goal_results = [record.get("part", {}).get("state", {}) for record in records
                                if record.get("part", {}).get("tool") == "goal_verify"]
                assert any(state.get("status") == "error" and state.get("error") == "goal is not ready for verification"
                           for state in goal_results)
                assert requests and all(path == "/v1/chat/completions" for path in requests)
                assert "goal_verify" in tool_names
                service.check_health()
                with pytest.raises(RuntimeError, match="not available"):
                    session.run([str(tmp_path / "node.exe"), "-e", ""], cwd=tmp_path, env=env, timeout=2)
    finally:
        model.shutdown()
        model.server_close()
