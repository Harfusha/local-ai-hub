from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT_SOURCE = Path(__file__).resolve().parents[1] / "src"


def test_registered_search_honors_worktree_hint_and_path_policy(tmp_path: Path) -> None:
    assert ROOT_SOURCE.is_dir(), f"root source overlay is missing: {ROOT_SOURCE}"
    script = r'''
import asyncio
import json
import os
import socket
import subprocess
import sys
import threading
from pathlib import Path

root_source = Path(os.environ["T21_ROOT_SOURCE"]).resolve()
sys.path.insert(0, str(root_source))
import local_ai_hub
assert Path(local_ai_hub.__file__).resolve().is_relative_to(root_source), local_ai_hub.__file__
from local_ai_hub import http_server, mcp_server, project_config
from local_ai_hub.app import LocalAIApp
from local_ai_hub.client import HubClient
from local_ai_hub.project_config import resolve_project_config

fixture_root = Path(os.environ["T21_FIXTURE_ROOT"])
primary = fixture_root / "primary"
primary.mkdir()

def git(*args):
    completed = subprocess.run(
        ["git", "-C", str(primary), *args], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, (args, completed.stdout, completed.stderr)
    return completed.stdout.strip()

git("init", "-q")
(primary / ".gitignore").write_text(
    "templates/element/ignored.py\n"
    "templates/element/primary-only.py\n"
    "**/.local-ai-hub/**\n",
    encoding="utf-8",
)
(primary / ".local-ai.toml").write_text(
    'exclude_paths = ["templates/element/primary-hidden.py"]\n'
    'force_include_paths = ["templates/element/primary-only.py"]\n',
    encoding="utf-8",
)
element = primary / "templates/element"
element.mkdir(parents=True)
token = "T21_ROOT_WORKTREE_HINT_TOKEN"
for name in ("button.py", "primary-hidden.py"):
    (element / name).write_text(f"marker = '{token}'\n", encoding="utf-8")
git("add", ".")
git("-c", "user.name=T21 Test", "-c", "user.email=t21@example.invalid", "commit", "-qm", "fixture")

worktree = fixture_root / "worktree"
git("worktree", "add", "--detach", str(worktree), "HEAD")
(worktree / ".local-ai.worktree.toml").write_text(
    'force_include_paths = ["templates/element/ignored.py", '
    '"templates/element/.local-ai-hub/hard.py"]\n',
    encoding="utf-8",
)
element = worktree / "templates/element"
(element / "ignored.py").write_text(f"marker = '{token}'\n", encoding="utf-8")
(element / "primary-only.py").write_text(f"marker = '{token}'\n", encoding="utf-8")
hard_dir = element / ".local-ai-hub"
hard_dir.mkdir()
(hard_dir / "hard.py").write_text(f"marker = '{token}'\n", encoding="utf-8")

resolution = resolve_project_config(worktree)
assert "primary_project" in resolution.active_sources, resolution.active_sources
assert "worktree" in resolution.active_sources, resolution.active_sources
assert resolution.settings.exclude_paths == ("templates/element/primary-hidden.py",)
assert resolution.settings.force_include_paths == (
    "templates/element/ignored.py", "templates/element/.local-ai-hub/hard.py"
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
client = HubClient(tenant="t21-root-worktree-path-hints", config_path=str(config_path), auto_start=False)
mcp_server.CLIENT = client
wire_payloads = []
service_hints = []
accepted_hints = []
original_open = client._pooled_open
original_search = app.services.repo_search
original_validate_hint = project_config.validate_path_hint

def capture_open(method, path, body, headers, timeout, *, cancel_event=None):
    if path == "/api/search" and body is not None:
        wire_payloads.append(json.loads(body.decode("utf-8")))
    return original_open(method, path, body, headers, timeout, cancel_event=cancel_event)

def capture_search(*args, **kwargs):
    service_hints.append(kwargs.get("path_hints"))
    return original_search(*args, **kwargs)

def capture_validate_hint(root, hint, **kwargs):
    resolved = original_validate_hint(root, hint, **kwargs)
    if resolved is not None:
        accepted_hints.append((hint.path, hint.scope))
    return resolved

client._pooled_open = capture_open
app.services.repo_search = capture_search
project_config.validate_path_hint = capture_validate_hint

async def call_tool(arguments):
    result = await mcp_server.mcp.call_tool("local_ai_repo", arguments)
    contents = result[0] if isinstance(result, tuple) else result
    text_content = next(item for item in contents if getattr(item, "type", None) == "text")
    return json.loads(text_content.text)

try:
    hint = {"path": "templates/element", "purpose": "repository_search", "scope": "repo_search"}
    result = asyncio.run(call_tool({
        "action": "search", "root": str(worktree), "query": token, "path_hints": [hint]
    }))
    assert result.get("success") is True, result
    paths = {item.get("path") for item in result.get("results", [])}
    assert "templates/element/button.py" in paths, paths
    assert "templates/element/ignored.py" in paths, paths
    assert "templates/element/primary-hidden.py" not in paths, paths
    assert "templates/element/primary-only.py" not in paths, paths
    assert "templates/element/.local-ai-hub/hard.py" not in paths, paths
    assert wire_payloads[-1]["path_hints"] == [hint], wire_payloads[-1]
    assert service_hints[-1] == [hint], service_hints[-1]
    assert ("templates/element", "repo_search") in accepted_hints, accepted_hints

    requests_before_invalid = len(wire_payloads)
    invalid = asyncio.run(call_tool({
        "action": "search", "root": str(worktree), "query": token,
        "path_hints": [{"path": "../outside.py", "purpose": "repository_search", "scope": "repo_search"}],
    }))
    assert invalid.get("success") is False, invalid
    assert invalid.get("status_code") == 400, invalid
    assert invalid.get("terminal") is True and invalid.get("retryable") is False, invalid
    assert len(wire_payloads) == requests_before_invalid, wire_payloads
    print("T21_ROOT_WORKTREE_HINT_RESULT=" + json.dumps({
        "import_origin": str(Path(local_ai_hub.__file__).resolve()),
        "active_sources": list(resolution.active_sources),
        "valid_paths": sorted(paths),
        "accepted_hints": accepted_hints,
        "wire_requests": len(wire_payloads),
        "service_hint_calls": len(service_hints),
    }))
finally:
    client.close()
    server.shutdown()
    server.server_close()
    server_thread.join(timeout=3)
    app.close()
'''
    env = os.environ.copy()
    env["T21_ROOT_SOURCE"] = str(ROOT_SOURCE)
    env["T21_FIXTURE_ROOT"] = str(tmp_path)
    env["PYTHONPATH"] = str(ROOT_SOURCE)
    completed = subprocess.run(
        [sys.executable, "-B", "-c", script],
        cwd=ROOT_SOURCE.parent,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, (
        f"root-source worktree path-hint chain failed\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    result_line = next(
        line
        for line in completed.stdout.splitlines()
        if line.startswith("T21_ROOT_WORKTREE_HINT_RESULT=")
    )
    result = __import__("json").loads(result_line.partition("=")[2])
    assert Path(result["import_origin"]).resolve().is_relative_to(ROOT_SOURCE.resolve())
    assert "primary_project" in result["active_sources"]
    assert "worktree" in result["active_sources"]
    assert result["wire_requests"] == 1
    assert result["service_hint_calls"] == 1
