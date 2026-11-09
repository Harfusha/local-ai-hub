"""Isolated HTTP/process smoke test; no model service or real user project is touched."""
from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import closing
from pathlib import Path

import pytest

from local_ai_hub.process_utils import popen_managed, process_identity, terminate_tree


def _request(base: str, path: str, payload=None):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        base + path, data=body, headers={"Content-Type": "application/json"},
        method="GET" if body is None else "POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_isolated_http_mode_and_registered_projects(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    state = tmp_path / "state"
    config = tmp_path / "config.toml"
    config.write_text(f'''[server]
bind="127.0.0.1"
port={port}
state_dir="{state.as_posix()}"
auto_start_ollama=false
[hardware]
profile="cpu"
auto_tune=true
[prewarm]
enabled=false
[preprocessing]
enabled=true
reject_temp_projects=false
fs_watcher_enabled=false
startup_delay_seconds=0
poll_seconds=0.2
idle_diagnostics_enabled=false
[preprocessing.exclusive]
max_projects=2
cpu_workers=2
model_parallel=1
[background_gpu]
enabled=false
cpu_fallback_enabled=false
[resilience]
watchdog_enabled=false
[code_intelligence]
enabled=false
''', encoding="utf-8")
    projects = []
    for index in range(2):
        project = tmp_path / f"project-{index}"
        project.mkdir()
        (project / "main.py").write_text("def example():\n    return 42\n", encoding="utf-8")
        projects.append(project)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    env["LOCAL_AI_CONFIG"] = str(config)
    proc = popen_managed([sys.executable, "-m", "local_ai_hub.supervisor"], cwd=str(root), env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    identity = process_identity(proc.pid)
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline and proc.poll() is None:
            try:
                if _request(base, "/health")[1].get("success") is True:
                    break
            except (OSError, ValueError):
                time.sleep(0.2)
        else:
            raise AssertionError("isolated Hub did not start")
        for project in projects:
            status, result = _request(base, "/api/preprocess", {"action": "register", "root": str(project)})
            assert status == 200 and result.get("success") is True and not result.get("ignored"), result
        status, result = _request(base, "/api/admin/mode", {"mode": "preprocessing"})
        assert status == 200 and result.get("preprocessing_start", {}).get("success") is True, result
        status, mode = _request(base, "/api/mode")
        assert status == 200 and mode.get("preprocessing_ready") is True, mode
        status, blocked = _request(base, "/api/search", {"root": str(projects[0]), "query": "example"})
        assert status == 423 and blocked.get("mode") == "preprocessing", blocked
        # One bounded observation window; this is a real isolated server, with
        # model inference disabled, not evidence of model quality or throughput.
        time.sleep(3)
        for project in projects:
            status, prep = _request(base, "/api/preprocess/status?" + urllib.parse.urlencode({"root": str(project)}))
            assert status == 200 and len(prep.get("projects", [])) == 1, prep
            assert prep["projects"][0].get("files", 0) >= 1, prep
        status, mode = _request(base, "/api/admin/mode", {"mode": "active"})
        assert status == 200 and mode.get("mode") == "active", mode
    finally:
        terminate_tree(proc.pid, expected_identity=identity, grace_seconds=5.0, process_handle=proc)
        try:
            proc.wait(timeout=6)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
@pytest.mark.skipif(os.environ.get("LOCAL_AI_TEST_PREPROCESS_CPU") != "1", reason="explicit isolated CPU model test required")
def test_isolated_http_mode_enriches_two_projects_with_real_model(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    def free_port():
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    port, model_port, unused_port = free_port(), free_port(), free_port()
    assert len({port, model_port, unused_port}) == 3
    state = tmp_path / "state"
    config = tmp_path / "config.toml"
    config.write_text(f'''[server]
bind="127.0.0.1"
port={port}
state_dir="{state.as_posix()}"
ollama_url="http://127.0.0.1:{unused_port}"
auto_start_ollama=false
[hardware]
profile="cpu"
auto_tune=true
[ollama]
enabled=true
[llama_cpp]
mode="off"
[headless]
autostart_ollama=true
manage_ollama=false
[prewarm]
enabled=false
[preprocessing]
enabled=true
model="qwen2.5-coder:3b"
prefer_deterministic_cards=false
disable_llm_card_synthesis=false
reject_temp_projects=false
fs_watcher_enabled=false
startup_delay_seconds=0
poll_seconds=0.2
idle_diagnostics_enabled=false
[preprocessing.exclusive]
max_projects=2
cpu_workers=2
model_parallel=1
[background_gpu]
enabled=false
cpu_fallback_enabled=true
cpu_ollama_url="http://127.0.0.1:{model_port}"
cpu_context_tokens=4096
request_timeout_seconds=150
file_batch_size=1
[resilience]
watchdog_enabled=false
[code_intelligence]
enabled=false
''', encoding="utf-8")
    from local_ai_hub.config import load_config
    effective = load_config(str(config), probe_hardware=False)
    assert effective["headless"]["autostart_ollama"] is True
    assert effective["llama_cpp"]["mode"] == "off"
    projects = []
    for index in range(2):
        project = tmp_path / f"project-{index}"
        project.mkdir()
        (project / "inventory.md").write_text(f"Inventory {index} tracks products and quantities.\n", encoding="utf-8")
        projects.append(project)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    env["LOCAL_AI_CONFIG"] = str(config)
    proc = popen_managed([sys.executable, "-m", "local_ai_hub.supervisor"], cwd=str(root), env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    identity = process_identity(proc.pid)
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline and proc.poll() is None:
            try:
                if _request(base, "/health")[1].get("success") is True:
                    break
            except (OSError, ValueError):
                time.sleep(0.2)
        else:
            raise AssertionError("isolated Hub did not start")
        for project in projects:
            status, result = _request(base, "/api/preprocess", {"action": "register", "root": str(project)})
            assert status == 200 and result.get("success") is True and not result.get("ignored"), result
        status, result = _request(base, "/api/admin/mode", {"mode": "preprocessing"})
        assert status == 200 and result.get("preprocessing_start", {}).get("success") is True, result
        status, blocked = _request(base, "/api/search", {"root": str(projects[0]), "query": "inventory"})
        assert status == 423 and blocked.get("mode") == "preprocessing", blocked
        # A single bounded observation window; no asynchronous status polling.
        time.sleep(55)
        time.sleep(55)
        time.sleep(55)
        with closing(sqlite3.connect(state / "preprocess.sqlite3")) as con:
            rows = con.execute("SELECT f.root,c.model,c.card_json FROM file_refs f JOIN content_cards c ON c.card_key=f.card_key WHERE f.path='inventory.md'").fetchall()
            project_rows = con.execute("SELECT root,status,phase,last_error FROM projects").fetchall()
        diagnostics = [_request(base, "/api/preprocess/status?" + urllib.parse.urlencode({"root": str(project)}))[1]["projects"][0] for project in projects]
        gpu = _request(base, "/api/live/status")[1].get("background_gpu", {})
        diagnostics = [{key: item.get(key) for key in ("phase", "status", "last_error", "waiting_reason")} for item in diagnostics]
        diagnostics.append({key: gpu.get(key) for key in ("model", "ready", "last_error", "stats", "cpu_fallback")})
        if {row[0] for row in rows} != {str(project) for project in projects}:
            raise AssertionError(json.dumps({"rows": rows, "diagnostics": diagnostics}))
        assert all(row[1] == "qwen2.5-coder:3b" for row in rows), rows
        assert all(any(term in row[2].lower() for term in ("invent", "product", "quantit", "stock")) for row in rows), rows
        if {row[0] for row in project_rows if row[1] == "complete" and row[2] == "complete"} != {str(project) for project in projects}:
            raise AssertionError(json.dumps({"projects": project_rows, "diagnostics": diagnostics}))
        status, mode = _request(base, "/api/admin/mode", {"mode": "active"})
        assert status == 200 and mode.get("mode") == "active", mode
    finally:
        terminate_tree(proc.pid, expected_identity=identity, grace_seconds=5.0, process_handle=proc)
        try:
            proc.wait(timeout=6)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
    with socket.socket() as sock:
        sock.settimeout(1)
        assert sock.connect_ex(("127.0.0.1", model_port)) != 0, "isolated CPU model server survived Hub shutdown"
