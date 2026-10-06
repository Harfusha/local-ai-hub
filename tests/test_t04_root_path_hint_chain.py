from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT_SOURCE = Path(__file__).resolve().parents[1] / "src"


def test_registered_repo_search_forwards_hints_over_real_root_http(tmp_path: Path) -> None:
    assert ROOT_SOURCE.is_dir(), f"root source overlay is missing: {ROOT_SOURCE}"
    script = r'''
import asyncio
import json
import os
import socket
import threading
from pathlib import Path

root_source = Path(os.environ["T04_ROOT_SOURCE"]).resolve()
sys_path = __import__("sys").path
sys_path.insert(0, str(root_source))

import local_ai_hub
assert Path(local_ai_hub.__file__).resolve().is_relative_to(root_source), local_ai_hub.__file__
from local_ai_hub import http_server, mcp_server
from local_ai_hub.app import LocalAIApp
from local_ai_hub.client import HubClient

fixture_root = Path(os.environ["T04_FIXTURE_ROOT"])
repo = fixture_root / "repo"
for relative in ("templates/element", "src", "secret"):
    (repo / relative).mkdir(parents=True, exist_ok=True)
token = "T04_ROOT_PATH_HINT_CHAIN_TOKEN"
(repo / "templates/element/button.py").write_text(f"marker = '{token}'\n", encoding="utf-8")
(repo / "src/button.py").write_text(f"marker = '{token}'\n", encoding="utf-8")
(repo / "secret/blocked.py").write_text(f"marker = '{token}'\n", encoding="utf-8")
(repo / ".local-ai.toml").write_text(
    'entry_points = ["templates/element"]\n'
    'exclude_paths = ["secret/**"]\n'
    '[path_overrides]\n'
    '"templates/element/**" = "include"\n',
    encoding="utf-8",
)
with socket.socket() as probe:
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
state_dir = fixture_root / "state"
config_path = fixture_root / "hub.toml"
config_path.write_text(
    "[server]\n"
    'bind = "127.0.0.1"\n'
    f'port = {port}\nstate_dir = {json.dumps(state_dir.as_posix())}\n'
    "[ollama]\nenabled = false\n"
    "[smart_ollama]\nenabled = false\n"
    '[llama_cpp]\nmode = "off"\n'
    "[code_intelligence]\nenabled = false\nserena_enabled = false\npreprocess_serena = false\n"
    "[preprocessing]\nenabled = false\n",
    encoding="utf-8",
)
os.environ["LOCAL_AI_CONFIG"] = str(config_path)
app = LocalAIApp(str(config_path))
http_server.APP = app
server = http_server.LocalAIHTTPServer(("127.0.0.1", port), http_server.Handler)
server_thread = threading.Thread(target=server.serve_forever, daemon=True)
server_thread.start()
client = HubClient(tenant="t04-root-path-hints", config_path=str(config_path), auto_start=False)
mcp_server.CLIENT = client
wire_payloads = []
service_hints = []
original_open = client._pooled_open
original_search = app.services.repo_search

def capture_open(method, path, body, headers, timeout):
    if path == "/api/search" and body is not None:
        wire_payloads.append(json.loads(body.decode("utf-8")))
    return original_open(method, path, body, headers, timeout)

def capture_search(*args, **kwargs):
    service_hints.append(kwargs.get("path_hints"))
    return original_search(*args, **kwargs)

client._pooled_open = capture_open
app.services.repo_search = capture_search

async def call_tool(arguments):
    result = await mcp_server.mcp.call_tool("local_ai_repo", arguments)
    contents = result[0] if isinstance(result, tuple) else result
    text_content = next(item for item in contents if getattr(item, "type", None) == "text")
    return json.loads(text_content.text)

def assert_safe_results(result):
    assert result.get("success") is True, result
    paths = {item.get("path") for item in result.get("results", [])}
    assert "templates/element/button.py" in paths, paths
    assert "secret/blocked.py" not in paths, paths

try:
    valid_hint = {"path": "templates/element", "purpose": "repository_search", "scope": "repository_search"}
    valid = asyncio.run(call_tool({
        "action": "search", "root": str(repo), "query": token, "path_hints": [valid_hint]
    }))
    assert_safe_results(valid)
    assert wire_payloads[-1]["path_hints"] == [valid_hint], wire_payloads[-1]
    assert service_hints[-1] == [valid_hint], service_hints[-1]

    empty = asyncio.run(call_tool({
        "action": "search", "root": str(repo), "query": token, "path_hints": []
    }))
    assert_safe_results(empty)
    assert "path_hints" not in wire_payloads[-1], wire_payloads[-1]
    assert service_hints[-1] is None, service_hints[-1]

    before_invalid = len(wire_payloads)
    for bad_path in ("", "../outside.py"):
        invalid = asyncio.run(call_tool({
            "action": "search", "root": str(repo), "query": token,
            "path_hints": [{"path": bad_path, "purpose": "repository_search", "scope": "repository_search"}],
        }))
        assert invalid.get("success") is False, invalid
        assert invalid.get("status_code") == 400, invalid
        assert invalid.get("terminal") is True and invalid.get("retryable") is False, invalid
    assert len(wire_payloads) == before_invalid, wire_payloads

    override = asyncio.run(call_tool({
        "action": "search", "root": str(repo), "query": token,
        "path": "templates/element",
        "path_hints": [{"path": "secret", "purpose": "repository_search", "scope": "repository_search"}],
    }))
    assert_safe_results(override)
    assert [hint["path"] for hint in wire_payloads[-1]["path_hints"]] == ["templates/element", "secret"]
    assert service_hints[-1][1]["path"] == "secret"
    assert len(wire_payloads) == 3, wire_payloads
    print("T04_ROOT_PATH_HINT_RESULT=" + json.dumps({
        "import_origin": str(Path(local_ai_hub.__file__).resolve()),
        "wire_request_count": len(wire_payloads),
        "service_hint_calls": len(service_hints),
        "valid_result_paths": sorted(item["path"] for item in valid.get("results", [])),
        "override_result_paths": sorted(item["path"] for item in override.get("results", [])),
    }))
finally:
    client.close()
    server.shutdown()
    server.server_close()
    server_thread.join(timeout=3)
    app.close()
'''
    env = os.environ.copy()
    env["T04_ROOT_SOURCE"] = str(ROOT_SOURCE)
    env["T04_FIXTURE_ROOT"] = str(tmp_path)
    env["PYTHONPATH"] = str(ROOT_SOURCE)
    completed = subprocess.run(
        [sys.executable, "-B", "-c", script],
        cwd=ROOT_SOURCE.parent,
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert completed.returncode == 0, (
        f"root-source path-hint chain failed\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    result_line = next(
        line for line in completed.stdout.splitlines() if line.startswith("T04_ROOT_PATH_HINT_RESULT=")
    )
    result = json.loads(result_line.partition("=")[2])
    assert Path(result["import_origin"]).resolve().is_relative_to(ROOT_SOURCE.resolve())
    assert result["wire_request_count"] == 3
    assert result["service_hint_calls"] == 3
