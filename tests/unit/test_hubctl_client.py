from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def run_hubctl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "tools/hubctl.py", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_hubctl_client_overview():
    proc = run_hubctl("client")
    assert proc.returncode == 0
    assert "Client ID" in proc.stdout
    assert "codex" in proc.stdout
    assert "opencode" in proc.stdout
    assert "claude" in proc.stdout
    assert "antigravity" in proc.stdout


def test_hubctl_client_detect_json():
    proc = run_hubctl("client", "detect", "--json")
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data.get("success") is True
    assert "detected_client" in data


def test_hubctl_client_status_specific():
    proc = run_hubctl("client", "status", "--client", "codex", "--json")
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data.get("success") is True
    assert data.get("client_id") == "codex"
    assert data.get("prompt_cache_shield") is True
    assert data.get("has_token_tracking") is True


def test_hubctl_client_config_vscode():
    proc = run_hubctl("client", "config", "--client", "vscode", "--json")
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data.get("success") is True
    assert ".vscode/mcp.json" in data.get("configs", {})
    mcp_config = data["configs"][".vscode/mcp.json"]
    assert "mcpServers" in mcp_config
    assert "local-ai" in mcp_config["mcpServers"]


def test_hubctl_client_config_opencode():
    proc = run_hubctl("client", "config", "--client", "opencode", "--json")
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data.get("success") is True
    assert "opencode_plugin_storage" in data.get("configs", {})


def test_hubctl_client_inject_and_remove_dry_run(tmp_path):
    proc = run_hubctl("client", "inject", "--client", "claude", "--dry-run", "--root", str(tmp_path), "--json")
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data.get("success") is True
    assert data.get("dry_run") is True
    assert data.get("action") == "inject"

    proc2 = run_hubctl("client", "remove", "--client", "claude", "--dry-run", "--root", str(tmp_path), "--json")
    assert proc2.returncode == 0
    data2 = json.loads(proc2.stdout)
    assert data2.get("success") is True
    assert data2.get("action") == "remove"
