from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import setup
import uninstall


def test_uninstall_deactivates_owned_skills_across_configured_hosts(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    install = tmp_path / "install"
    install.mkdir()
    setup.write_install_manifest(install)
    profiles = tmp_path / "Multigravity" / "profiles"
    profile_home = profiles / "example" / "home"
    profile_home.mkdir(parents=True)
    codex_override = home / "alternate-codex"
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.delenv("USERNAME", raising=False)
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("APPDATA", str(home / "AppData" / "Roaming"))
    monkeypatch.setenv("MULTIGRAVITY_PROFILES", str(profiles))
    monkeypatch.setenv("CODEX_HOME", str(codex_override))
    monkeypatch.setattr(uninstall, "configured_install_dir", lambda: install)
    monkeypatch.setattr(uninstall, "_owned_hub_pids", lambda _install: [])
    monkeypatch.setattr(sys, "argv", ["uninstall.py", "--keep-install"])

    placements = [
        (home / ".agents" / "skills", "ponytail"),
        (home / ".codex" / "skills", "plan-led-work"),
        (home / ".cursor" / "skills", "ponytail-audit"),
        (home / ".codeium" / "windsurf" / "skills", "ponytail-review"),
        ((home / "AppData" / "Roaming" / "devin" if sys.platform == "win32"
          else home / ".config" / "devin") / "skills", "local-ai-orchestrator"),
        (home / ".copilot" / "skills", "token-economizer"),
        (profile_home / ".gemini" / "config" / "skills", "using-superpowers"),
        (home / ".gemini" / "skills", "former-managed-skill"),
    ]
    edited = (codex_override / "skills", "ponytail")
    unlisted = (tmp_path / "unlisted" / "skills", "plan-led-work")
    for base, name in (*placements, edited, unlisted):
        source = install / "skills" / name
        source.mkdir(parents=True, exist_ok=True)
        (source / "SKILL.md").write_text(f"---\nname: {name}\n---\nmanaged fixture\n", encoding="utf-8")
        setup.install_skill(source, base / name)
        assert (base / name / "SKILL.md").is_file()

    edited_file = edited[0] / edited[1] / "SKILL.md"
    edited_file.write_text("user changes\n", encoding="utf-8")
    unmanaged = home / ".agents" / "skills" / "user-only"
    unmanaged.mkdir()
    (unmanaged / "SKILL.md").write_text("user skill\n", encoding="utf-8")

    assert uninstall.main() == 0

    for base, name in placements:
        assert not (base / name).exists()
        backups = list((base.parent / ".local-ai-hub-skill-quarantine").glob(f"{name}*/SKILL.md"))
        assert len(backups) == 1 and "managed fixture" in backups[0].read_text(encoding="utf-8")
    assert edited_file.read_text(encoding="utf-8") == "user changes\n"
    assert (unlisted[0] / unlisted[1] / "SKILL.md").is_file()
    assert (unmanaged / "SKILL.md").read_text(encoding="utf-8") == "user skill\n"


def test_all_agent_mcp_entries_roundtrip_and_user_edits_survive(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    install = tmp_path / "install"
    home.mkdir()
    install.mkdir()
    # configure_agents generates artifacts from the canonical installed defaults.
    (install / "defaults.toml").write_bytes((ROOT / "defaults.toml").read_bytes())
    (install / "src" / "local_ai_hub").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("APPDATA", str(home / "AppData" / "Roaming"))
    monkeypatch.setattr(setup, "get_user_homes", lambda: [home])
    codex_home = home / ".codex"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    config_roots = {
        ".claude.json": "mcpServers",
        ".gemini/settings.json": "mcpServers",
        ".gemini/config/mcp_config.json": "mcpServers",
        ".cursor/mcp.json": "mcpServers",
        ".codeium/windsurf/mcp_config.json": "mcpServers",
        ("AppData/Roaming/devin/mcp_config.json" if sys.platform == "win32"
         else ".config/devin/mcp_config.json"): "mcpServers",
        ".copilot/mcp-config.json": "mcpServers",
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
            **{name: True for name in ("codex", "claude", "gemini", "antigravity", "cursor", "windsurf", "copilot", "devin")},
            "extra_mcp_json_paths": [str(home / ".local-ai" / "generic-mcp.json")],
            "extra_vscode_mcp_paths": [str(home / ".local-ai" / "vscode-mcp.json")],
        },
    }
    components = {
        f"agent_{agent}_{component}": component == "mcp"
        for agent in ("codex", "claude", "gemini", "antigravity", "cursor", "windsurf", "copilot", "devin")
        for component in ("mcp", "skills", "instructions")
    }
    components["agent_antigravity_hooks"] = True
    # This roundtrip exercises standalone MCP and hooks, not the native
    # Antigravity plugin route (which intentionally avoids duplicate entries).
    components["agent_antigravity_plugin"] = False
    monkeypatch.setattr(setup, "gemini_cli_extension_active", lambda *_args: False)
    monkeypatch.setattr(setup, "ensure_gemini_cli_extension", lambda *_args, **_kwargs: None)

    setup.configure_agents(install, Path(sys.executable), None, cfg, include_companion=False, agent_components=components)
    manifest = uninstall.read_install_manifest(install)
    owned_paths = {
        Path(record["path"]).resolve()
        for record in manifest["external_ownership"]
        if isinstance(record.get("path"), str)
    }
    expected_paths = {((home / relative).resolve()) for relative in config_roots}
    expected_paths.add(codex_path.resolve())
    assert expected_paths <= owned_paths, f"untracked provider configs: {expected_paths - owned_paths}"

    # A user edit to a managed key is a conflict; an edit elsewhere in the same file is retained.
    claude_path = home / ".claude.json"
    claude_data = json.loads(claude_path.read_text(encoding="utf-8"))
    claude_data["user_settings"]["after_install"] = "keep"
    claude_data["mcpServers"]["local-ai"]["user_added"] = True
    claude_path.write_text(json.dumps(claude_data), encoding="utf-8")
    codex_text = codex_path.read_text(encoding="utf-8").replace('default_tools_approval_mode = "prompt"', 'default_tools_approval_mode = "user"')
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
