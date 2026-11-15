"""Host configuration must not be mistaken for a live MCP handshake."""
from __future__ import annotations

import json
from pathlib import Path

from local_ai_hub import dashboard_frontend


def _hosts():
    return {item["host_id"]: item for item in dashboard_frontend.inspect_agent_hosts()["hosts"]}


def test_codex_uses_toml_mcp_registration_without_fake_handshake(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(dashboard_frontend.shutil, "which", lambda name: "/usr/bin/codex" if name == "codex" else None)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    cfg = tmp_path / ".codex" / "config.toml"
    cfg.parent.mkdir()
    cfg.write_text('[mcp_servers.local-ai]\ncommand = "python"\nargs = ["-m", "local_ai_hub.mcp_server"]\n', encoding="utf-8")
    host = _hosts()["codex"]
    assert host["mcp_registered"] is True
    assert host["status"] == "degraded"  # A config file is not a live session.
    assert host["mcp_connection"] == "unverified"
    assert host["handshake_verified"] is False
    assert host["last_handshake"] is None


def test_codex_toml_comment_or_other_server_does_not_register(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(dashboard_frontend.shutil, "which", lambda _name: "/usr/bin/codex")
    monkeypatch.delenv("CODEX_HOME", raising=False)
    cfg = tmp_path / ".codex" / "config.toml"
    cfg.parent.mkdir()
    cfg.write_text('# local-ai is not configured\n[mcp_servers.unrelated]\ncommand = "python"\n', encoding="utf-8")
    assert _hosts()["codex"]["mcp_registered"] is False
    cfg.write_text('[mcp_servers.local-ai]\ncommand = 1\n', encoding="utf-8")
    assert _hosts()["codex"]["mcp_registered"] is False


def test_codex_home_override_and_antigravity_json_parser(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    codex_home = tmp_path / "other-codex"
    codex_home.mkdir()
    (codex_home / "config.toml").write_text('[mcp_servers.local-ai]\ncommand = "python"\n', encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setenv("ANTIGRAVITY_ENV", "present-but-unverified")
    monkeypatch.setattr(dashboard_frontend.shutil, "which", lambda _name: None)
    config = tmp_path / ".gemini" / "config" / "mcp_config.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"mcpServers": {"local-ai": {"command": "python", "args": ["-m", "local_ai_hub"]}}}), encoding="utf-8")
    hosts = _hosts()
    assert hosts["codex"]["mcp_registered"] is True
    ag = hosts["antigravity"]
    assert ag["mcp_registered"] is True
    assert ag["handshake_verified"] is False
    assert ag["last_handshake"] is None
    assert ag["status"] != "ready"


def test_antigravity_json_comment_cannot_fake_registration(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(dashboard_frontend.shutil, "which", lambda _name: None)
    cfg = tmp_path / ".gemini" / "config" / "mcp_config.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"comment": "local-ai", "mcpServers": {"other": {"command": "python"}}}), encoding="utf-8")
    assert _hosts()["antigravity"]["mcp_registered"] is False


def test_codex_symlink_and_oversized_manifest_do_not_validate(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setattr(dashboard_frontend.shutil, "which", lambda n: "/usr/bin/codex" if n == "codex" else None)
    folder = tmp_path / ".codex"
    folder.mkdir()
    manifest = folder / "config.toml"
    elsewhere = tmp_path / "real.toml"
    elsewhere.write_text('[mcp_servers.local-ai]\ncommand = "python"\n', encoding="utf-8")
    try:
        manifest.symlink_to(elsewhere)
    except (OSError, NotImplementedError):
        pass
    else:
        assert _hosts()["codex"]["mcp_registered"] is False
        manifest.unlink()
    manifest.write_bytes(b"x" * (256 * 1024 + 1))
    assert _hosts()["codex"]["mcp_registered"] is False


def test_redaction_requires_real_home_descendant(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    home_file = tmp_path / ".codex" / "config.toml"
    assert dashboard_frontend._redact_path(home_file) == "~/.codex/config.toml"
    adjacent = Path(str(tmp_path) + "-other") / "config.toml"
    assert dashboard_frontend._redact_path(adjacent) == str(adjacent)
