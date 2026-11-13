from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import setup
import uninstall


def test_all_agent_mcp_entries_roundtrip_and_user_edits_survive(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    install = tmp_path / "install"
    home.mkdir()
    install.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(setup, "get_user_homes", lambda: [home])
    codex_home = home / ".codex"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    config_roots = {
        ".claude.json": "mcpServers",
        ".gemini/settings.json": "mcpServers",
        ".gemini/config/mcp_config.json": "mcpServers",
        ".cursor/mcp.json": "mcpServers",
        ".codeium/windsurf/mcp_config.json": "mcpServers",
        ".copilot/mcp-config.json": "servers",
        ".local-ai/generic-mcp.json": "mcpServers",
        ".local-ai/vscode-mcp.json": "servers",
    }
    for relative, container_name in config_roots.items():
        path = home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"user_settings": {"preserve": True}, container_name: {
            "foreign": {"command": "keep-me"},
        }}), encoding="utf-8")

    codex_path = codex_home / "config.toml"
    codex_path.parent.mkdir(parents=True, exist_ok=True)
    codex_path.write_text('[model]\nprovider = "user"\n', encoding="utf-8")
    antigravity_config = home / ".gemini" / "config" / "config.json"
    antigravity_config.parent.mkdir(parents=True, exist_ok=True)
    antigravity_config.write_text(json.dumps({"userSettings": {
        "autoExecutionPolicy": "USER_VALUE",
        "globalPermissionGrants": {
            "allow": ["user-grant"],
            "block": ["mcp(local-ai/local_ai_repo)"],
        },
    }, "foreign": {"keep": True}}), encoding="utf-8")
    cfg = {
        "setup": {"backup_existing_configs": False},
        "tool_policy": {"install_global_instructions": False},
        "code_intelligence": {"direct_agent_mcp": False, "serena_enabled": False},
        "agents": {
            **{name: True for name in ("codex", "claude", "gemini", "cursor", "windsurf", "copilot")},
            "extra_mcp_json_paths": [str(home / ".local-ai" / "generic-mcp.json")],
            "extra_vscode_mcp_paths": [str(home / ".local-ai" / "vscode-mcp.json")],
        },
    }
    components = {
        f"agent_{agent}_{component}": component == "mcp"
        for agent in ("codex", "claude", "gemini", "cursor", "windsurf", "copilot")
        for component in ("mcp", "skills", "instructions")
    }

    setup.configure_agents(install, Path(sys.executable), None, cfg, include_companion=False, agent_components=components)
    manifest = uninstall.read_install_manifest(install)
    assert len(manifest["external_ownership"]) >= len(config_roots) + 1

    # A user edit to a managed key is a conflict; an edit elsewhere in the same file is retained.
    claude_path = home / ".claude.json"
    claude_data = json.loads(claude_path.read_text(encoding="utf-8"))
    claude_data["user_settings"]["after_install"] = "keep"
    claude_data["mcpServers"]["local-ai"]["user_added"] = True
    claude_path.write_text(json.dumps(claude_data), encoding="utf-8")
    codex_text = codex_path.read_text(encoding="utf-8").replace('default_tools_approval_mode = "auto"', 'default_tools_approval_mode = "user"')
    codex_path.write_text(codex_text, encoding="utf-8")

    monkeypatch.setattr(uninstall, "configured_install_dir", lambda: install)
    monkeypatch.setattr(uninstall, "stop_hub", lambda _install: uninstall.StopResult("already_stopped"))
    monkeypatch.setattr(sys, "argv", ["uninstall.py"])
    assert uninstall.main() == 0
    assert not install.exists()

    cleaned_claude = json.loads(claude_path.read_text(encoding="utf-8"))
    assert cleaned_claude["user_settings"] == {"preserve": True, "after_install": "keep"}
    assert cleaned_claude["mcpServers"]["local-ai"]["user_added"] is True
    assert cleaned_claude["mcpServers"]["foreign"] == {"command": "keep-me"}
    for relative, container_name in list(config_roots.items())[1:]:
        payload = json.loads((home / relative).read_text(encoding="utf-8"))
        assert payload[container_name] == {"foreign": {"command": "keep-me"}}
    cleaned_codex = tomllib.loads(codex_path.read_text(encoding="utf-8"))
    assert cleaned_codex["model"]["provider"] == "user"
    assert cleaned_codex["mcp_servers"]["local-ai"]["default_tools_approval_mode"] == "user"

    antigravity_settings = json.loads(antigravity_config.read_text(encoding="utf-8"))
    assert antigravity_settings["userSettings"]["autoExecutionPolicy"] == "USER_VALUE"
    assert antigravity_settings["userSettings"]["globalPermissionGrants"]["allow"] == ["user-grant"]
    assert antigravity_settings["userSettings"]["globalPermissionGrants"]["block"] == ["mcp(local-ai/local_ai_repo)"]
    assert antigravity_settings["foreign"] == {"keep": True}
    hooks_path = home / ".gemini" / "config" / "hooks.json"
    assert "local-ai-hub" not in json.loads(hooks_path.read_text(encoding="utf-8"))
    assert not (hooks_path.parent / ("local-ai-hook.cmd" if sys.platform == "win32" else "local-ai-hook.sh")).exists()
