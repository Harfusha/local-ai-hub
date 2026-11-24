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
    assert "servers" in mcp_config
    assert "local-ai" in mcp_config["servers"]
    assert mcp_config["servers"]["local-ai"]["type"] == "stdio"


def test_hubctl_client_apply_vscode_requires_explicit_root(tmp_path):
    proc = run_hubctl("client", "config", "--client", "vscode", "--apply", "--json")
    assert proc.returncode != 0
    assert "--root" in proc.stderr


def test_hubctl_client_apply_vscode_merges_workspace_config(tmp_path, monkeypatch, capsys):
    from tools import hubctl

    config_path = tmp_path / ".vscode" / "mcp.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps({"servers": {"other": {"type": "stdio", "command": "keep"}}}))
    install = tmp_path / "hub-install"
    install.mkdir()
    monkeypatch.setattr(hubctl, "ROOT", install)
    monkeypatch.setattr(sys, "argv", [
        "hubctl", "client", "config", "--client", "vscode", "--apply",
        "--root", str(tmp_path), "--json",
    ])
    assert hubctl.main() == 0
    data = json.loads(config_path.read_text())
    assert data["servers"]["other"]["command"] == "keep"
    assert data["servers"]["local-ai"]["type"] == "stdio"
    result = json.loads(capsys.readouterr().out)
    assert result["applied"] is True
    assert result["rollback_tracking"] == "backup_only"


def test_hubctl_client_apply_vscode_records_owned_workspace_change_for_rollback(tmp_path, monkeypatch, capsys):
    from tools import hubctl
    from tools.install_ownership import read_install_manifest, write_install_manifest
    from tools import uninstall

    install = tmp_path / "install"
    install.mkdir()
    write_install_manifest(install)
    workspace = tmp_path / "workspace"
    config_path = workspace / ".vscode" / "mcp.json"
    config_path.parent.mkdir(parents=True)
    original = {"servers": {"browser-mcp": {"type": "stdio", "command": "keep"}}}
    config_path.write_text(json.dumps(original), encoding="utf-8")

    monkeypatch.setattr(hubctl, "ROOT", install)
    monkeypatch.setattr(sys, "argv", [
        "hubctl", "client", "config", "--client", "vscode", "--apply",
        "--root", str(workspace), "--json",
    ])
    assert hubctl.main() == 0
    assert json.loads(capsys.readouterr().out)["rollback_tracking"] == "install_manifest"

    ownership = read_install_manifest(install)["external_ownership"]
    assert len(ownership) == 1
    assert ownership[0]["path"] == str(config_path.resolve())
    uninstall.clean_external_configurations(ownership, install)
    assert json.loads(config_path.read_text(encoding="utf-8")) == original


def test_hubctl_client_apply_vscode_preserves_unowned_conflicting_server(tmp_path, monkeypatch, capsys):
    from tools import hubctl
    from tools.install_ownership import write_install_manifest

    install = tmp_path / "install"
    install.mkdir()
    write_install_manifest(install)
    workspace = tmp_path / "workspace"
    config_path = workspace / ".vscode" / "mcp.json"
    config_path.parent.mkdir(parents=True)
    original = {"servers": {"local-ai": {"type": "stdio", "command": "user-server"}}}
    config_path.write_text(json.dumps(original), encoding="utf-8")

    monkeypatch.setattr(hubctl, "ROOT", install)
    monkeypatch.setattr(sys, "argv", [
        "hubctl", "client", "config", "--client", "vscode", "--apply",
        "--root", str(workspace), "--json",
    ])
    assert hubctl.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["success"] is False
    assert result["applied"] is False
    assert "not Hub-owned" in result["error"]
    assert json.loads(config_path.read_text(encoding="utf-8")) == original


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
