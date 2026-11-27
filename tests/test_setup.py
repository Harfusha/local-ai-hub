from __future__ import annotations

import importlib.util
import json
import sys
import subprocess
import os
import tomllib
import sqlite3
from contextlib import closing
import pytest
from pathlib import Path
from local_ai_hub.config import load_config

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("local_ai_hub_setup", ROOT / "tools" / "setup.py")
assert SPEC and SPEC.loader
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


@pytest.mark.parametrize(
    "config_text,expected",
    [
        ("", True),
        ("[models]\nallow_hf_downloads = false\n", False),
    ],
)
def test_setup_wizard_hf_download_choice_inherits_config(tmp_path, config_text, expected):
    config = tmp_path / "config.toml"
    config.write_text("[local_ai_hub]\nconfig_schema_version = 1\n" + config_text, encoding="utf-8")
    effective = load_config(config, probe_hardware=False)

    choices = setup._setup_wizard_module.defaults_from_config(effective)

    assert choices["download_hf_models"] is expected


def test_setup_wizard_enables_devin_mcp_skills_instructions_and_hooks_by_default():
    effective = load_config(probe_hardware=False)
    choices = setup._setup_wizard_module.defaults_from_config(effective)

    assert choices["agent_devin"] is True
    assert choices["agent_devin_mcp"] is True
    assert choices["agent_devin_skills"] is True
    assert choices["agent_devin_instructions"] is True
    assert choices["agent_devin_hooks"] is True
    assert choices["agent_devin_plugin_route"] is False

    from types import SimpleNamespace
    args = SimpleNamespace(
        profile=None, skip_model_pull=None, skip_tools=None, skip_token_economy=None,
        skip_agent_config=None, skip_service=None, skip_companion_skills=None,
        skip_laya_runtime=None, skip_ast_index=None, skip_performance=None, skip_profiling=None,
    )
    choices["agent_devin_plugin_route"] = True
    setup._setup_wizard_module.apply_choices(args, effective, choices)
    assert effective["agents"]["devin_plugin_route"] is True


def test_provider_plugin_generation_tracks_current_hub_release_version(tmp_path, monkeypatch):
    provider_manifests = {
        "antigravity": "plugin.json",
        "claude": ".claude-plugin/plugin.json",
        "codex": "plugin.json",
        "copilot": "plugin.json",
        "cursor": ".cursor-plugin/plugin.json",
        "devin": "plugin.json",
        "gemini": "gemini-extension.json",
    }
    root = tmp_path / "hub"
    root.mkdir(parents=True)
    (root / "pyproject.toml").write_text('[project]\nversion = "8.1.0"\n', encoding="utf-8")
    for skill in ("local-ai-orchestrator", "plan-led-work", "token-economizer"):
        skill_file = root / "skills" / skill / "SKILL.md"
        skill_file.parent.mkdir(parents=True, exist_ok=True)
        skill_file.write_text(f"---\nname: {skill}\n---\n", encoding="utf-8")
    for provider, relative_manifest in provider_manifests.items():
        manifest = root / "plugins" / provider / "local-ai-hub" / relative_manifest
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            json.dumps({"name": "local-ai-hub", "version": "6.1.0"}),
            encoding="utf-8",
        )

    monkeypatch.setattr(setup, "SOURCE_ROOT", root)
    setup.generate_provider_plugin_skills()

    for provider, relative_manifest in provider_manifests.items():
        manifest = root / "plugins" / provider / "local-ai-hub" / relative_manifest
        assert json.loads(manifest.read_text(encoding="utf-8"))["version"] == "8.1.0"


def test_cursor_setup_refreshes_recognized_plugin_bundle_and_backs_up_old_files(tmp_path, monkeypatch):
    source_root = tmp_path / "hub-source"
    source = source_root / "plugins" / "cursor" / "local-ai-hub"
    (source / ".cursor-plugin").mkdir(parents=True)
    (source / ".cursor-plugin" / "plugin.json").write_text(
        '{"name":"local-ai-hub","version":"8.1.0"}\n', encoding="utf-8",
    )
    (source / "mcp.json").write_text('{"mcpServers":{"local-ai":{"command":"python"}}}\n', encoding="utf-8")
    (source / "rules").mkdir()
    (source / "rules" / "hub.mdc").write_text("current Hub rule\n", encoding="utf-8")
    monkeypatch.setattr(setup, "SOURCE_ROOT", source_root)

    cursor_dir = tmp_path / ".cursor"
    target = cursor_dir / "plugins" / "local" / "local-ai-hub"
    (target / ".cursor-plugin").mkdir(parents=True)
    (target / ".cursor-plugin" / "plugin.json").write_text(
        '{"name":"local-ai-hub","version":"6.1.0"}\n', encoding="utf-8",
    )
    (target / "mcp.json").write_text('{"mcpServers":{}}\n', encoding="utf-8")
    (target / "user-owned.txt").write_text("keep\n", encoding="utf-8")

    assert setup.sync_cursor_plugin_bundle(cursor_dir, backup_enabled=True) is True

    manifest = json.loads((target / ".cursor-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "8.1.0"
    assert json.loads((target / "mcp.json").read_text(encoding="utf-8"))["mcpServers"]["local-ai"]
    assert (target / "rules" / "hub.mdc").read_text(encoding="utf-8") == "current Hub rule\n"
    assert (target / "user-owned.txt").read_text(encoding="utf-8") == "keep\n"
    backups = list(target.rglob("*.local-ai-hub-backup-*"))
    assert len(backups) == 2
    assert any(path.read_text(encoding="utf-8") == '{"name":"local-ai-hub","version":"6.1.0"}\n' for path in backups)

    assert setup.sync_cursor_plugin_bundle(cursor_dir, backup_enabled=True) is True
    assert len(list(target.rglob("*.local-ai-hub-backup-*"))) == 2


def test_cursor_setup_refreshes_bundle_when_local_plugin_route_is_installed(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(setup, "cursor_hub_plugin_installed", lambda _cursor_dir: True)
    monkeypatch.setattr(
        setup, "sync_cursor_plugin_bundle",
        lambda cursor_dir, backup_enabled: calls.append((cursor_dir, backup_enabled)) or True,
        raising=False,
    )

    setup.configure_cursor_global_routes(
        tmp_path / ".cursor", tmp_path / "install", Path("python"), None,
        {}, False, None, [],
    )

    assert calls == [(tmp_path / ".cursor", False)]


def test_setup_generation_refreshes_managed_policy_blocks_in_install_prompts(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    docs.mkdir()
    prompts = ("INSTALL_PROMPT.md", "UPDATE_PROMPT.md")
    for name in prompts:
        (docs / name).write_text(
            "before\n<!-- BEGIN LOCAL AI HUB TOOL POLICY -->\nstale\n"
            "<!-- END LOCAL AI HUB TOOL POLICY -->\nmiddle\n"
            "<!-- BEGIN TOKEN ECONOMY POLICY -->\nstale\n"
            "<!-- END TOKEN ECONOMY POLICY -->\nafter\n",
            encoding="utf-8",
        )
    monkeypatch.setattr(setup, "SOURCE_ROOT", tmp_path)

    setup.sync_generated_prompt_policies()

    for name in prompts:
        text = (docs / name).read_text(encoding="utf-8")
        assert setup.generate_global_policy({}) in text
        assert setup.generate_token_economy_policy({}) in text
        assert "\nstale\n" not in text


def test_setup_wizard_exposes_opencode_and_plugin_route_independently():
    wizard = setup._setup_wizard_module
    cfg = load_config(probe_hardware=False)
    choices = wizard.defaults_from_config(cfg)

    assert choices["agent_opencode"] is True
    assert choices["agent_opencode_plugin"] is True

    from types import SimpleNamespace
    args = SimpleNamespace(
        profile=None, skip_model_pull=None, skip_tools=None, skip_token_economy=None,
        skip_agent_config=None, skip_service=None, skip_companion_skills=None,
        skip_laya_runtime=None, skip_ast_index=None, skip_performance=None, skip_profiling=None,
    )
    choices["agent_opencode_plugin"] = False
    wizard.apply_choices(args, cfg, choices)

    assert cfg["agents"]["opencode"] is True
    assert cfg["agents"]["opencode_plugin_route"] is False


def test_opencode_setup_installs_skills_in_native_global_discovery_root(tmp_path, monkeypatch):
    install = tmp_path / "install"
    source = install / "skills" / "local-ai-orchestrator"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("---\nname: local-ai-orchestrator\ndescription: Use when testing.\n---\n", encoding="utf-8")
    config_root = tmp_path / ".config" / "opencode"
    monkeypatch.setattr(setup, "write_all_generated", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup, "write_generated_agent_manifests", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup, "opencode_config_dirs", lambda: [config_root])
    agents = {name: False for name in (
        "codex", "claude", "gemini", "antigravity", "cursor", "windsurf", "copilot", "devin",
    )}
    agents.update({"opencode": True, "opencode_plugin_route": False})
    agent_components = {
        "agent_opencode_skills": True,
        "agent_opencode_instructions": False,
        "agent_opencode_mcp": False,
        "agent_opencode_plugin": False,
    }

    setup._configure_agents_impl(
        install, Path("python"), None,
        {"agents": agents, "setup": {"backup_existing_configs": False},
         "tool_policy": {"install_global_instructions": False}},
        include_companion=False,
        agent_components=agent_components,
    )

    installed = config_root / "skills" / "local-ai-orchestrator" / "SKILL.md"
    assert installed.read_text(encoding="utf-8") == (source / "SKILL.md").read_text(encoding="utf-8")


def test_opencode_config_can_select_standalone_mcp_without_wizard_state(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(setup, "write_all_generated", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup, "write_generated_agent_manifests", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup, "opencode_config_dirs", lambda: [tmp_path])
    monkeypatch.setattr(setup, "install_agent_skills", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup, "opencode_mcp_merge", lambda path, *_args: calls.append(path))
    monkeypatch.setattr(
        setup, "sync_opencode_plugin_config",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("plugin route selected")),
    )
    agents = {name: False for name in (
        "codex", "claude", "gemini", "antigravity", "cursor", "windsurf", "copilot", "devin",
    )}
    agents.update({"opencode": True, "opencode_plugin_route": False})

    setup._configure_agents_impl(
        tmp_path / "install", Path("python"), None,
        {"agents": agents, "setup": {"backup_existing_configs": False},
         "tool_policy": {"install_global_instructions": False}},
    )

    assert calls == [tmp_path / "opencode.json"]


def test_devin_plugin_route_skips_duplicate_global_mcp_and_reports_existing_route(tmp_path, monkeypatch):
    install = tmp_path / "install"
    install.mkdir()
    devin_dir = tmp_path / "devin"
    mcp_path = devin_dir / "mcp_config.json"
    mcp_attempts = []
    skill_attempts = []
    monkeypatch.setattr(setup, "write_all_generated", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup, "write_generated_agent_manifests", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup, "devin_config_dir", lambda: devin_dir)
    monkeypatch.setattr(setup, "devin_mcp_config_path", lambda: mcp_path)
    monkeypatch.setattr(setup, "global_hub_mcp_configured", lambda path: True)
    monkeypatch.setattr(setup, "json_mcp_merge", lambda *args, **kwargs: mcp_attempts.append(args[0]))
    monkeypatch.setattr(setup, "install_agent_skills", lambda *args, **kwargs: skill_attempts.append(args[1]))
    monkeypatch.setattr(setup, "sync_devin_pre_tool_hook", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(setup, "merge_global_policy", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup, "merge_token_economy_policy", lambda *_args, **_kwargs: None)
    agents = {name: False for name in ("codex", "claude", "gemini", "antigravity", "cursor", "windsurf", "copilot", "opencode")}
    agents.update({"devin": True, "devin_plugin_route": True})

    actions = setup._configure_agents_impl(
        install,
        tmp_path / "python.exe",
        None,
        {"agents": agents, "setup": {"backup_existing_configs": False},
         "tool_policy": {"install_global_instructions": False}},
        include_companion=False,
        agent_components={
            "agent_devin_mcp": True,
            "agent_devin_skills": True,
            "agent_devin_hooks": True,
        },
    )

    assert mcp_attempts == []
    assert all(path != devin_dir / "skills" for path in skill_attempts)
    assert any("plugin route is selected" in action.lower() for action in actions)
    assert any("standalone Hub MCP remains" in action for action in actions)


def test_opencode_plugin_setup_detects_duplicate_standalone_hub_mcp(tmp_path):
    config = tmp_path / "opencode.json"
    config.write_text(
        json.dumps({"plugins": [{"package": "local-ai-hub"}], "mcp": {"servers": {
            "local-ai": {"type": "local", "command": ["python", "-m", "local_ai_hub.mcp_server"]},
            "other": {"type": "local", "command": ["other-server"]},
        }}}),
        encoding="utf-8",
    )

    assert setup.opencode_direct_hub_mcp_configured(config) is True

    data = json.loads(config.read_text(encoding="utf-8"))
    assert set(data["mcp"]["servers"]) == {"local-ai", "other"}


def test_opencode_plugin_setup_detects_native_hub_server_name(tmp_path):
    config = tmp_path / "opencode.json"
    config.write_text(json.dumps({"mcp": {"servers": {
        "local-ai-hub": {"type": "local", "command": ["python", "-m", "local_ai_hub.mcp_server"]},
    }}}), encoding="utf-8")

    assert setup.opencode_direct_hub_mcp_configured(config) is True


def test_opencode_plugin_setup_allows_plugin_without_duplicate_mcp(tmp_path):
    config = tmp_path / "opencode.json"
    config.write_text(json.dumps({"plugins": [{"package": "local-ai-hub"}]}), encoding="utf-8")

    assert setup.opencode_direct_hub_mcp_configured(config) is False


def test_opencode_plugin_setup_detects_jsonc_mcp_without_rewriting_it(tmp_path):
    config = tmp_path / "opencode.jsonc"
    config.write_text(
        '''{
          // Existing standalone Hub route must remain user-owned.
          "mcp": {"servers": {
            "local-ai": {"type": "local", "command": ["python", "-m", "local_ai_hub.mcp_server"],},
            "other": {"type": "local", "command": ["https://example.test/a//b"],},
          },},
        }''',
        encoding="utf-8",
    )

    assert setup.opencode_direct_hub_mcp_configured(config) is True
    assert "//b" in config.read_text(encoding="utf-8")


def test_opencode_plugin_route_does_not_add_duplicate_when_jsonc_has_standalone_hub_mcp(tmp_path, monkeypatch):
    config = tmp_path / "opencode.jsonc"
    config.write_text(
        json.dumps({"mcp": {"servers": {"local-ai": {
            "type": "local", "command": ["python", "-m", "local_ai_hub.mcp_server"],
        }}}}),
        encoding="utf-8",
    )
    plugin_attempts = []
    monkeypatch.setattr(setup, "write_all_generated", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup, "write_generated_agent_manifests", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup, "opencode_config_dirs", lambda: [tmp_path])
    monkeypatch.setattr(setup, "install_agent_skills", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup, "sync_opencode_plugin_config", lambda *args, **kwargs: plugin_attempts.append(args[0]) or True)
    agents = {name: False for name in (
        "codex", "claude", "gemini", "antigravity", "cursor", "windsurf", "copilot", "devin",
    )}
    agents.update({"opencode": True, "opencode_plugin_route": True})

    actions = setup._configure_agents_impl(
        tmp_path / "install", Path("python"), None,
        {"agents": agents, "setup": {"backup_existing_configs": False},
         "tool_policy": {"install_global_instructions": False}},
    )

    assert plugin_attempts == []
    assert not (tmp_path / "opencode.json").exists()
    assert any("opencode.jsonc" in action and "duplicate" in action.lower() for action in actions)


def test_opencode_standalone_route_preserves_existing_jsonc_hub_mcp(tmp_path, monkeypatch):
    config = tmp_path / "opencode.jsonc"
    original = json.dumps({"mcp": {"servers": {"local-ai": {"type": "local"}}}})
    config.write_text(original, encoding="utf-8")
    mcp_attempts = []
    monkeypatch.setattr(setup, "write_all_generated", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup, "write_generated_agent_manifests", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup, "opencode_config_dirs", lambda: [tmp_path])
    monkeypatch.setattr(setup, "install_agent_skills", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup, "opencode_mcp_merge", lambda path, *_args, **_kwargs: mcp_attempts.append(path))
    agents = {name: False for name in (
        "codex", "claude", "gemini", "antigravity", "cursor", "windsurf", "copilot", "devin",
    )}
    agents.update({"opencode": True, "opencode_plugin_route": False})

    actions = setup._configure_agents_impl(
        tmp_path / "install", Path("python"), None,
        {"agents": agents, "setup": {"backup_existing_configs": False},
         "tool_policy": {"install_global_instructions": False}},
    )

    assert mcp_attempts == []
    assert config.read_text(encoding="utf-8") == original
    assert any("opencode.jsonc" in action and "preserved" in action.lower() for action in actions)


def test_opencode_plugin_route_preserves_existing_jsonc_plugin(tmp_path, monkeypatch):
    config = tmp_path / "opencode.jsonc"
    config.write_text(json.dumps({"plugins": [{"package": str(tmp_path / "local-ai-hub")}]}), encoding="utf-8")
    plugin_attempts = []
    monkeypatch.setattr(setup, "write_all_generated", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup, "write_generated_agent_manifests", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup, "opencode_config_dirs", lambda: [tmp_path])
    monkeypatch.setattr(setup, "install_agent_skills", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup, "sync_opencode_plugin_config", lambda *args, **kwargs: plugin_attempts.append(args[0]) or True)
    agents = {name: False for name in (
        "codex", "claude", "gemini", "antigravity", "cursor", "windsurf", "copilot", "devin",
    )}
    agents.update({"opencode": True, "opencode_plugin_route": True})

    setup._configure_agents_impl(
        tmp_path / "install", Path("python"), None,
        {"agents": agents, "setup": {"backup_existing_configs": False},
         "tool_policy": {"install_global_instructions": False}},
    )

    assert plugin_attempts == []
    assert not (tmp_path / "opencode.json").exists()


def test_opencode_plugin_route_refreshes_existing_json_plugin(tmp_path, monkeypatch):
    install = tmp_path / "install"
    mcp_plugin = install / "plugins" / "opencode" / "local-ai-hub"
    goal_plugin = install / "tools" / "opencode_goal"
    mcp_plugin.mkdir(parents=True)
    goal_plugin.mkdir(parents=True)
    (goal_plugin / "index.js").write_text("export default {}\n", encoding="utf-8")
    removed_root = tmp_path / "removed-worktree" / ".local-ai-hub"
    stale_mcp_plugin = removed_root / "plugins" / "opencode" / "local-ai-hub"
    stale_goal_plugin = removed_root / "tools" / "opencode_goal"
    config = tmp_path / "opencode.json"
    config.write_text(json.dumps({
        "plugins": [
            {"package": str(mcp_plugin.resolve()), "options": {
                "server": {"command": ["old-python"], "nativeMcp": False},
            }},
            {"package": str(stale_mcp_plugin), "options": {}},
            {"package": str(stale_goal_plugin), "options": {}},
            "user-plugin",
        ],
        "providers": {"user-provider": {"name": "preserve me"}},
        "mcp": {"servers": {"user-server": {"type": "local", "command": ["keep"]}}},
    }), encoding="utf-8")
    monkeypatch.setattr(setup, "write_all_generated", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup, "write_generated_agent_manifests", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup, "build_codex_mcp_entries", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(setup, "opencode_config_dirs", lambda: [tmp_path])
    monkeypatch.setattr(setup, "install_agent_skills", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup, "build_mcp_entries", lambda *_args, **_kwargs: {
        "local-ai": {"command": "C:/Python/python.exe", "args": ["-m", "local_ai_hub.mcp_server"],
                     "cwd": str(install), "env": {"LOCAL_AI_AGENT": "opencode"}},
    })
    agents = {name: False for name in (
        "codex", "claude", "gemini", "antigravity", "cursor", "windsurf", "copilot", "devin",
    )}
    agents.update({"opencode": True, "opencode_plugin_route": True})
    cfg = {
        "agents": agents,
        "models": {"general": "gemma4:12b-128k"},
        "server": {"bind": "127.0.0.1", "port": 11435},
        "setup": {"backup_existing_configs": False},
        "tool_policy": {"install_global_instructions": False},
    }

    setup._configure_agents_impl(install, Path("C:/Python/python.exe"), None, cfg)

    configured = json.loads(config.read_text(encoding="utf-8"))
    plugins = configured["plugins"]
    managed_plugins = [entry for entry in plugins if isinstance(entry, dict)]
    by_package = {entry["package"]: entry for entry in managed_plugins}
    assert plugins.count("user-plugin") == 1
    assert set(by_package) == {str(mcp_plugin.resolve()), str(goal_plugin.resolve())}
    assert by_package[str(mcp_plugin.resolve())]["options"]["server"]["nativeMcp"] is True
    assert configured["mcp"]["servers"]["local-ai-hub"]["codemode"] is True
    assert configured["providers"]["user-provider"] == {"name": "preserve me"}
    assert configured["mcp"]["servers"]["user-server"] == {"type": "local", "command": ["keep"]}

    by_package[str(mcp_plugin.resolve())]["options"]["server"]["nativeMcp"] = False
    configured["plugins"] = [
        entry for entry in plugins
        if not isinstance(entry, dict) or entry.get("package") != str(goal_plugin.resolve())
    ]
    configured["providers"].pop("local-ai-hub")
    config.write_text(json.dumps(configured), encoding="utf-8")
    setup._configure_agents_impl(install, Path("C:/Python/python.exe"), None, cfg)

    refreshed = json.loads(config.read_text(encoding="utf-8"))
    refreshed_by_package = {
        entry["package"]: entry for entry in refreshed["plugins"] if isinstance(entry, dict)
    }
    assert refreshed_by_package[str(mcp_plugin.resolve())]["options"]["server"]["nativeMcp"] is True
    assert str(goal_plugin.resolve()) in refreshed_by_package
    assert "local-ai-hub" in refreshed["providers"]


def test_opencode_plugin_sync_preserves_existing_valid_hub_copy(tmp_path, monkeypatch):
    install = tmp_path / "install"
    mcp_plugin = install / "plugins" / "opencode" / "local-ai-hub"
    goal_plugin = install / "tools" / "opencode_goal"
    mcp_plugin.mkdir(parents=True)
    goal_plugin.mkdir(parents=True)
    (goal_plugin / "index.js").write_text("export default {}\n", encoding="utf-8")
    retained_mcp_plugin = tmp_path / "other-install" / "plugins" / "opencode" / "local-ai-hub"
    retained_mcp_plugin.mkdir(parents=True)
    retained = {"package": str(retained_mcp_plugin.resolve()), "options": {"user": "preserve"}}
    config = tmp_path / "opencode.json"
    config.write_text(json.dumps({"plugins": [retained]}), encoding="utf-8")
    monkeypatch.setattr(setup, "build_mcp_entries", lambda *_args, **_kwargs: {
        "local-ai": {"command": "C:/Python/python.exe", "args": ["-m", "local_ai_hub.mcp_server"],
                     "cwd": str(install), "env": {"LOCAL_AI_AGENT": "opencode"}},
    })
    cfg = {
        "models": {"general": "gemma4:12b-128k"},
        "server": {"bind": "127.0.0.1", "port": 11435},
    }

    assert setup.sync_opencode_plugin_config(config, install, Path("C:/Python/python.exe"), cfg, False)

    configured = json.loads(config.read_text(encoding="utf-8"))
    packages = {
        entry["package"]: entry for entry in configured["plugins"] if isinstance(entry, dict)
    }
    assert packages[str(retained_mcp_plugin.resolve())] == retained
    assert str(mcp_plugin.resolve()) in packages
    assert str(goal_plugin.resolve()) in packages


def test_opencode_plugin_route_installs_goal_lifecycle_plugin_and_preserves_others(tmp_path, monkeypatch):
    install = tmp_path / "install"
    mcp_plugin = install / "plugins" / "opencode" / "local-ai-hub"
    goal_plugin = install / "tools" / "opencode_goal"
    mcp_plugin.mkdir(parents=True)
    goal_plugin.mkdir(parents=True)
    (goal_plugin / "index.js").write_text("export default {}\n", encoding="utf-8")
    config = tmp_path / "opencode.json"
    config.write_text(json.dumps({
        "plugins": ["existing-plugin"],
        "agents": {"reviewer": {"mode": "subagent", "system": "preserve me"}},
        "mcp": {"servers": {"existing-server": {"type": "local", "command": ["keep"]}}},
    }), encoding="utf-8")
    monkeypatch.setattr(setup, "build_mcp_entries", lambda *_args, **_kwargs: {
        "local-ai": {"command": "C:/Python/python.exe", "args": ["-m", "local_ai_hub.mcp_server"],
                     "cwd": str(install), "env": {"LOCAL_AI_AGENT": "opencode"}},
    })

    hub_config = {"server": {"bind": "127.0.0.1", "port": 11435},
                  "models": {"general": "gemma4:12b-128k"}}
    assert setup.sync_opencode_plugin_config(config, install, Path("C:/Python/python.exe"), hub_config, False)

    written = config.read_bytes()
    plugins = json.loads(written)["plugins"]
    assert "-opencode.provider.ollama" in plugins
    assert plugins[0] == "existing-plugin"
    by_package = {entry["package"]: entry for entry in plugins if isinstance(entry, dict)}
    assert by_package[str(mcp_plugin.resolve())]["options"]["server"]["environment"]["OPENCODE_SESSION"] == "1"
    assert by_package[str(goal_plugin.resolve())]["options"] == {
        "hubURL": "http://127.0.0.1:11435", "actor": "opencode-local",
    }
    assert json.loads(written)["providers"]["local-ai-hub"] == {
        "name": "Local AI Hub",
        "package": "@opencode/ai/providers/openai-compatible",
        "settings": {"baseURL": "http://127.0.0.1:11435/api"},
        "headers": {"X-LocalAI-Agent": "opencode"},
        "models": {"gemma4:12b-128k": {
            "name": "Local AI Hub / gemma4:12b-128k", "modelID": "gemma4:12b-128k",
            "capabilities": {"tools": True, "input": ["text"], "output": ["text"]},
            "limit": {"context": 16384, "output": 2048},
        }},
    }
    assert json.loads(written)["model"] == "local-ai-hub/gemma4:12b-128k"
    configured = json.loads(written)
    assert configured["default_agent"] == "local-ai-hub"
    assert configured["agents"]["reviewer"] == {"mode": "subagent", "system": "preserve me"}
    hub_agent = configured["agents"]["local-ai-hub"]
    assert hub_agent["mode"] == "primary"
    assert hub_agent["steps"] == 8
    assert hub_agent["permissions"] == [
        {"action": "edit", "resource": "*", "effect": "ask"},
        {"action": "shell", "resource": "*", "effect": "ask"},
        {"action": "external_directory", "resource": "*", "effect": "ask"},
        {"action": "webfetch", "resource": "*", "effect": "ask"},
        {"action": "websearch", "resource": "*", "effect": "ask"},
    ]
    assert "top-level `search`" in hub_agent["system"]
    assert "structuredContent" in hub_agent["system"]
    assert "OpenCode permissions" in hub_agent["system"]
    managed_mcp = json.loads(written)["mcp"]["servers"]
    assert managed_mcp["existing-server"] == {"type": "local", "command": ["keep"]}
    assert managed_mcp["local-ai-hub"] == {
        "type": "local",
        "command": [str(Path("C:/Python/python.exe").resolve()), "-m", "local_ai_hub.mcp_server"],
        "cwd": str(install.resolve()),
        "environment": {
            "LOCAL_AI_AGENT": "opencode", "OPENCODE_SESSION": "1",
            "LOCAL_AI_HUB_DIR": str(install.resolve()),
        },
        "codemode": True,
        "timeout": {"startup": 60000, "catalog": 60000},
    }
    assert setup.sync_opencode_plugin_config(config, install, Path("C:/Python/python.exe"), hub_config, False)
    assert config.read_bytes() == written


def test_opencode_plugin_route_preserves_explicit_default_agent(tmp_path, monkeypatch):
    install = tmp_path / "install"
    (install / "plugins" / "opencode" / "local-ai-hub").mkdir(parents=True)
    goal_plugin = install / "tools" / "opencode_goal"
    goal_plugin.mkdir(parents=True)
    (goal_plugin / "index.js").write_text("export default {}\n", encoding="utf-8")
    config = tmp_path / "opencode.json"
    config.write_text(json.dumps({"default_agent": "reviewer", "agents": {
        "reviewer": {"mode": "primary", "system": "keep selected agent"},
    }}), encoding="utf-8")
    monkeypatch.setattr(setup, "build_mcp_entries", lambda *_args, **_kwargs: {
        "local-ai": {"command": "C:/Python/python.exe", "args": ["-m", "local_ai_hub.mcp_server"],
                     "cwd": str(install), "env": {"LOCAL_AI_AGENT": "opencode"}},
    })
    hub_config = {"server": {"bind": "127.0.0.1", "port": 11435},
                  "models": {"general": "gemma4:12b-128k"}}

    assert setup.sync_opencode_plugin_config(config, install, Path("C:/Python/python.exe"), hub_config, False)

    configured = json.loads(config.read_text(encoding="utf-8"))
    assert configured["default_agent"] == "reviewer"
    assert configured["agents"]["reviewer"] == {"mode": "primary", "system": "keep selected agent"}
    assert configured["agents"]["local-ai-hub"]["steps"] == 8
    assert all(rule["effect"] == "ask" for rule in configured["agents"]["local-ai-hub"]["permissions"])


def test_opencode_plugin_route_adopts_and_exactly_rolls_back_existing_config(tmp_path, monkeypatch):
    install = tmp_path / "install"
    (install / "plugins" / "opencode" / "local-ai-hub").mkdir(parents=True)
    goal_plugin = install / "tools" / "opencode_goal"
    goal_plugin.mkdir(parents=True)
    (goal_plugin / "index.js").write_text("export default {}\n", encoding="utf-8")
    setup.write_install_manifest(install)
    config = tmp_path / "opencode.json"
    original = {
        "plugins": ["existing-plugin"],
        "default_agent": "reviewer",
        "agents": {"reviewer": {"mode": "subagent", "system": "preserve me"}},
        "providers": {"existing-provider": {"name": "preserve me"}},
        "mcp": {"servers": {"existing-server": {"type": "local", "command": ["keep"]}}},
    }
    config.write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.setattr(setup, "_ACTIVE_INSTALL_ROOT", install)
    monkeypatch.setattr(setup, "build_mcp_entries", lambda *_args, **_kwargs: {
        "local-ai": {"command": "C:/Python/python.exe", "args": ["-m", "local_ai_hub.mcp_server"],
                     "cwd": str(install), "env": {"LOCAL_AI_AGENT": "opencode"}},
    })
    hub_config = {"server": {"bind": "127.0.0.1", "port": 11435},
                  "models": {"general": "gemma4:12b-128k"}}

    assert setup.sync_opencode_plugin_config(config, install, Path("C:/Python/python.exe"), hub_config, False)
    installed = json.loads(config.read_text(encoding="utf-8"))
    assert installed["plugins"][0] == "existing-plugin"
    assert installed["default_agent"] == "reviewer"
    assert installed["providers"]["existing-provider"] == original["providers"]["existing-provider"]
    assert installed["mcp"]["servers"]["existing-server"] == original["mcp"]["servers"]["existing-server"]

    uninstall_spec = importlib.util.spec_from_file_location("test_opencode_uninstall", ROOT / "tools" / "uninstall.py")
    assert uninstall_spec and uninstall_spec.loader
    uninstall = importlib.util.module_from_spec(uninstall_spec)
    sys.modules[uninstall_spec.name] = uninstall
    uninstall_spec.loader.exec_module(uninstall)
    ownership = setup._install_ownership_module.read_install_manifest(install)["external_ownership"]
    uninstall.clean_external_configurations(ownership, install)
    assert json.loads(config.read_text(encoding="utf-8")) == original

    minimal_config = tmp_path / "opencode-minimal.json"
    minimal_original = {"plugins": ["existing-plugin"]}
    minimal_config.write_text(json.dumps(minimal_original), encoding="utf-8")
    assert setup.sync_opencode_plugin_config(
        minimal_config, install, Path("C:/Python/python.exe"), hub_config, False,
    )
    ownership = setup._install_ownership_module.read_install_manifest(install)["external_ownership"]
    uninstall.clean_external_configurations(ownership, install)
    assert json.loads(minimal_config.read_text(encoding="utf-8")) == minimal_original


def test_opencode_plugin_route_removes_new_config_on_rollback(tmp_path, monkeypatch):
    install = tmp_path / "install"
    (install / "plugins" / "opencode" / "local-ai-hub").mkdir(parents=True)
    goal_plugin = install / "tools" / "opencode_goal"
    goal_plugin.mkdir(parents=True)
    (goal_plugin / "index.js").write_text("export default {}\n", encoding="utf-8")
    setup.write_install_manifest(install)
    config = tmp_path / "opencode.json"
    monkeypatch.setattr(setup, "_ACTIVE_INSTALL_ROOT", install)
    monkeypatch.setattr(setup, "build_mcp_entries", lambda *_args, **_kwargs: {
        "local-ai": {"command": "C:/Python/python.exe", "args": ["-m", "local_ai_hub.mcp_server"],
                     "cwd": str(install), "env": {"LOCAL_AI_AGENT": "opencode"}},
    })
    hub_config = {"server": {"bind": "127.0.0.1", "port": 11435},
                  "models": {"general": "gemma4:12b-128k"}}

    assert setup.sync_opencode_plugin_config(config, install, Path("C:/Python/python.exe"), hub_config, False)
    assert config.exists()
    uninstall_spec = importlib.util.spec_from_file_location("test_opencode_uninstall_new_file", ROOT / "tools" / "uninstall.py")
    assert uninstall_spec and uninstall_spec.loader
    uninstall = importlib.util.module_from_spec(uninstall_spec)
    sys.modules[uninstall_spec.name] = uninstall
    uninstall_spec.loader.exec_module(uninstall)
    ownership = setup._install_ownership_module.read_install_manifest(install)["external_ownership"]

    uninstall.clean_external_configurations(ownership, install)

    assert not config.exists()


def test_opencode_goal_plugin_refuses_non_loopback_hub_endpoint(tmp_path, monkeypatch):
    install = tmp_path / "install"
    (install / "plugins" / "opencode" / "local-ai-hub").mkdir(parents=True)
    goal_plugin = install / "tools" / "opencode_goal"
    goal_plugin.mkdir(parents=True)
    (goal_plugin / "index.js").write_text("export default {}\n", encoding="utf-8")
    config = tmp_path / "opencode.json"
    config.write_text("{}", encoding="utf-8")
    original = config.read_bytes()
    monkeypatch.setattr(setup, "build_mcp_entries", lambda *_args, **_kwargs: {
        "local-ai": {"command": "C:/Python/python.exe", "args": ["-m", "local_ai_hub.mcp_server"],
                     "cwd": str(install), "env": {}},
    })

    assert not setup.sync_opencode_plugin_config(
        config, install, Path("C:/Python/python.exe"),
        {"server": {"bind": "0.0.0.0", "port": 11435}}, False,
    )
    assert config.read_bytes() == original


def test_opencode_provider_uses_reasoning_model_when_general_role_is_implicit(tmp_path, monkeypatch):
    install = tmp_path / "install"
    (install / "plugins" / "opencode" / "local-ai-hub").mkdir(parents=True)
    goal = install / "tools" / "opencode_goal"
    goal.mkdir(parents=True)
    (goal / "index.js").write_text("export default {}\n", encoding="utf-8")
    monkeypatch.setattr(setup, "build_mcp_entries", lambda *_args, **_kwargs: {
        "local-ai": {"command": "C:/Python/python.exe", "args": ["-m", "local_ai_hub.mcp_server"],
                     "cwd": str(install), "env": {}},
    })
    config = tmp_path / "opencode.json"

    assert setup.sync_opencode_plugin_config(
        config, install, Path("C:/Python/python.exe"),
        {"server": {"bind": "127.0.0.1", "port": 11435},
         "models": {"reasoning": "qwen3.5:9b-nvfp4"}}, False,
    )
    written = json.loads(config.read_text(encoding="utf-8"))
    assert written["model"] == "local-ai-hub/qwen3.5:9b-nvfp4"


def test_opencode_provider_prefers_explicit_opencode_model_without_changing_other_roles(tmp_path, monkeypatch):
    install = tmp_path / "install"
    (install / "plugins" / "opencode" / "local-ai-hub").mkdir(parents=True)
    goal = install / "tools" / "opencode_goal"
    goal.mkdir(parents=True)
    (goal / "index.js").write_text("export default {}\n", encoding="utf-8")
    monkeypatch.setattr(setup, "build_mcp_entries", lambda *_args, **_kwargs: {
        "local-ai": {"command": "C:/Python/python.exe", "args": ["-m", "local_ai_hub.mcp_server"],
                     "cwd": str(install), "env": {}},
    })
    config = tmp_path / "opencode.json"
    hub_config = {
        "server": {"bind": "127.0.0.1", "port": 11435},
        "models": {"general": "qwen3.5:9b-nvfp4", "opencode": "gemma4:12b-128k"},
        "model_execution": {"opencode": {
            "context_tokens": 16384, "large_context_tokens": 32768,
            "max_context_tokens": 131072,
        }},
    }

    assert setup.sync_opencode_plugin_config(config, install, Path("C:/Python/python.exe"), hub_config, False)
    written = json.loads(config.read_text(encoding="utf-8"))

    assert written["model"] == "local-ai-hub/gemma4:12b-128k"
    assert set(written["providers"]["local-ai-hub"]["models"]) == {
        "qwen3.5:9b-nvfp4", "gemma4:12b-128k",
    }
    assert written["providers"]["local-ai-hub"]["models"]["gemma4:12b-128k"]["limit"]["context"] == 131072
    assert written["providers"]["local-ai-hub"]["models"]["qwen3.5:9b-nvfp4"]["limit"]["context"] == 16384


def test_opencode_standalone_route_keeps_existing_jsonc_plugin(tmp_path, monkeypatch):
    config = tmp_path / "opencode.jsonc"
    original = json.dumps({"plugins": [str(tmp_path / "local-ai-hub")]})
    config.write_text(original, encoding="utf-8")
    mcp_attempts = []
    monkeypatch.setattr(setup, "write_all_generated", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup, "write_generated_agent_manifests", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup, "opencode_config_dirs", lambda: [tmp_path])
    monkeypatch.setattr(setup, "install_agent_skills", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup, "opencode_mcp_merge", lambda path, *_args, **_kwargs: mcp_attempts.append(path))
    agents = {name: False for name in (
        "codex", "claude", "gemini", "antigravity", "cursor", "windsurf", "copilot", "devin",
    )}
    agents.update({"opencode": True, "opencode_plugin_route": False})

    actions = setup._configure_agents_impl(
        tmp_path / "install", Path("python"), None,
        {"agents": agents, "setup": {"backup_existing_configs": False},
         "tool_policy": {"install_global_instructions": False}},
    )

    assert mcp_attempts == []
    assert config.read_text(encoding="utf-8") == original
    assert any("plugin" in action.lower() and "opencode.jsonc" in action for action in actions)


def test_opencode_setup_uses_canonical_or_explicit_config_root_only(tmp_path, monkeypatch):
    monkeypatch.setattr(setup.Path, "home", lambda: tmp_path)
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    monkeypatch.delenv("OPENCODE_HOME", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    assert setup.opencode_config_dirs() == [tmp_path / ".config" / "opencode"]

    explicit = tmp_path / "custom-opencode"
    monkeypatch.setenv("OPENCODE_HOME", str(explicit))
    assert setup.opencode_config_dirs() == [explicit]


def test_opencode_setup_uses_xdg_config_home_for_isolated_profile(tmp_path, monkeypatch):
    xdg_config_home = tmp_path / "isolated-xdg-config"
    monkeypatch.setenv("OPENCODE_HOME", str(tmp_path / "inherited-opencode-home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_config_home))

    assert setup.opencode_config_dirs() == [xdg_config_home / "opencode"]


def test_claude_plugin_route_detects_global_mcp_and_hooks(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({
        "enabledPlugins": {"local-ai-hub@local-ai-hub": True},
        "hooks": {"SessionStart": [{"hooks": [{
            "type": "command",
            "command": "python host_hooks.py --host claude",
        }]}]},
    }), encoding="utf-8")
    mcp = tmp_path / ".claude.json"
    mcp.write_text(json.dumps({"mcpServers": {"local-ai": {"command": "python"}}}), encoding="utf-8")

    assert setup.claude_hub_plugin_enabled(settings) is True
    assert setup.claude_global_hub_hooks_configured(settings) is True
    assert setup.claude_global_hub_mcp_configured(mcp) is True


def test_claude_plugin_route_detection_keeps_unrelated_settings(tmp_path):
    settings = tmp_path / "settings.json"
    original = json.dumps({
        "enabledPlugins": {"other@marketplace": True},
        "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"command": "user-hook"}]}]},
    })
    settings.write_text(original, encoding="utf-8")

    assert setup.claude_hub_plugin_enabled(settings) is False
    assert setup.claude_global_hub_hooks_configured(settings) is False
    assert settings.read_text(encoding="utf-8") == original


def test_claude_subagent_start_hook_installs_idempotently_without_replacing_settings(tmp_path, monkeypatch):
    install = tmp_path / "install"
    hook_source = install / "src" / "local_ai_hub" / "repo_plan" / "host_hooks.py"
    hook_source.parent.mkdir(parents=True)
    hook_source.write_text("# managed source\n", encoding="utf-8")
    python = tmp_path / "python.exe"
    python.write_text("", encoding="utf-8")
    settings = tmp_path / "home" / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"theme": "dark", "hooks": {"SessionStart": []}}), encoding="utf-8")
    monkeypatch.setattr(setup, "_ACTIVE_INSTALL_ROOT", None)

    assert setup.sync_claude_subagent_start_hook(settings, install, python, False)
    config = json.loads(settings.read_text(encoding="utf-8"))
    assert config["theme"] == "dark"
    assert config["hooks"]["SessionStart"] == []
    assert config["hooks"]["SubagentStart"][0]["hooks"][0]["command"].endswith("--host claude")
    assert setup.sync_claude_subagent_start_hook(settings, install, python, False)
    assert len(json.loads(settings.read_text(encoding="utf-8"))["hooks"]["SubagentStart"]) == 1


def test_gemini_extension_and_antigravity_plugin_paths_are_detected(tmp_path):
    gemini = tmp_path / ".gemini"
    extension = gemini / "extensions" / "local-ai-hub" / "gemini-extension.json"
    plugin = gemini / "config" / "plugins" / "local-ai-hub" / "plugin.json"
    extension.parent.mkdir(parents=True)
    plugin.parent.mkdir(parents=True)
    extension.write_text(json.dumps({"name": "local-ai-hub"}), encoding="utf-8")
    plugin.write_text(json.dumps({"name": "local-ai-hub"}), encoding="utf-8")

    assert setup.gemini_cli_extension_installed(gemini) is True
    assert setup.antigravity_plugin_installed(gemini) is True
    assert setup.gemini_cli_extension_active(gemini) is True


def test_gemini_cli_extension_install_uses_scoped_source_directory(tmp_path, monkeypatch):
    install = tmp_path / "hub"
    source = install / "plugins" / "gemini" / "local-ai-hub"
    source.mkdir(parents=True)
    (source / "gemini-extension.json").write_text(
        json.dumps({"name": "local-ai-hub", "version": "8.1.0"}), encoding="utf-8",
    )
    gemini = tmp_path / "home" / ".gemini"
    calls = []
    actions = []
    monkeypatch.setattr(setup, "SOURCE_ROOT", install)
    monkeypatch.setattr(setup.shutil, "which", lambda name: "gemini.cmd" if name == "gemini.cmd" else None)

    def fake_run(args, *, cwd, check, **kwargs):
        calls.append((args, Path(cwd), check))
        target = gemini / "extensions" / "local-ai-hub"
        target.parent.mkdir(parents=True, exist_ok=True)
        setup.shutil.copytree(source, target)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(setup.subprocess, "run", fake_run)

    assert setup.ensure_gemini_cli_extension(
        gemini, install, interactive=True, manual_actions=actions,
    ) is True
    assert calls == [(["gemini.cmd", "extensions", "install", str(source)], source, False)]
    assert actions == []


def test_gemini_cli_extension_noninteractive_reports_trust_command(tmp_path, monkeypatch):
    install = tmp_path / "hub"
    source = install / "plugins" / "gemini" / "local-ai-hub"
    source.mkdir(parents=True)
    (source / "gemini-extension.json").write_text(
        json.dumps({"name": "local-ai-hub", "version": "8.1.0"}), encoding="utf-8",
    )
    actions = []
    monkeypatch.setattr(setup, "SOURCE_ROOT", install)
    monkeypatch.setattr(setup.shutil, "which", lambda _name: "gemini.cmd")
    monkeypatch.setattr(setup.subprocess, "run", lambda *_a, **_k: pytest.fail("noninteractive setup must not prompt"))

    assert setup.ensure_gemini_cli_extension(
        tmp_path / "home" / ".gemini", install, interactive=False, manual_actions=actions,
    ) is False
    assert len(actions) == 1
    assert "gemini extensions install" in actions[0]
    assert str(source) in actions[0]


def test_gemini_cli_extension_updates_stale_local_install(tmp_path, monkeypatch):
    install = tmp_path / "hub"
    source = install / "plugins" / "gemini" / "local-ai-hub"
    source.mkdir(parents=True)
    current_manifest = {"name": "local-ai-hub", "version": "8.1.0"}
    (source / "gemini-extension.json").write_text(json.dumps(current_manifest), encoding="utf-8")
    gemini = tmp_path / "home" / ".gemini"
    installed = gemini / "extensions" / "local-ai-hub"
    installed.mkdir(parents=True)
    (installed / "gemini-extension.json").write_text(
        json.dumps({"name": "local-ai-hub", "version": "8.0.0"}), encoding="utf-8",
    )
    actions = []
    calls = []
    monkeypatch.setattr(setup, "SOURCE_ROOT", install)
    monkeypatch.setattr(setup.shutil, "which", lambda name: "gemini.cmd" if name == "gemini.cmd" else None)

    def fake_run(args, *, cwd, check, **kwargs):
        calls.append((args, Path(cwd), check))
        if args[1:3] == ["extensions", "list"]:
            return subprocess.CompletedProcess(args, 0, stdout="", stderr=f"Source: {source} (Type: local)")
        (installed / "gemini-extension.json").write_text(json.dumps(current_manifest), encoding="utf-8")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(setup.subprocess, "run", fake_run)

    assert setup.ensure_gemini_cli_extension(
        gemini, install, interactive=True, manual_actions=actions,
    ) is True
    assert calls == [
        (["gemini.cmd", "extensions", "list"], source, False),
        (["gemini.cmd", "extensions", "update", "local-ai-hub"], source, False),
    ]
    assert actions == []


def test_gemini_cli_extension_does_not_accept_same_version_with_stale_files(tmp_path, monkeypatch):
    install = tmp_path / "hub"
    source = install / "plugins" / "gemini" / "local-ai-hub"
    source.mkdir(parents=True)
    (source / "gemini-extension.json").write_text(
        json.dumps({"name": "local-ai-hub", "version": "8.2.1"}), encoding="utf-8",
    )
    (source / "GEMINI.md").write_text("current instructions\n", encoding="utf-8")
    gemini = tmp_path / "home" / ".gemini"
    installed = gemini / "extensions" / "local-ai-hub"
    installed.mkdir(parents=True)
    (installed / "gemini-extension.json").write_text(
        json.dumps({"name": "local-ai-hub", "version": "8.2.1"}), encoding="utf-8",
    )
    (installed / ".gemini-extension-install.json").write_text(
        json.dumps({"source": str(source), "type": "local"}), encoding="utf-8",
    )
    (installed / "GEMINI.md").write_text("stale instructions\n", encoding="utf-8")
    actions = []
    monkeypatch.setattr(setup, "SOURCE_ROOT", install)
    monkeypatch.setattr(setup.shutil, "which", lambda _name: pytest.fail("must not run a CLI update at equal version"))

    assert setup.ensure_gemini_cli_extension(
        gemini, install, interactive=True, manual_actions=actions,
    ) is False
    assert len(actions) == 1
    assert "same version" in actions[0]
    assert "increase the source version" in actions[0]


def test_gemini_mcp_route_omits_blocked_pythonpath(tmp_path):
    entries = setup.build_mcp_entries(tmp_path / "hub", tmp_path / "python.exe", None, "gemini", {})
    assert "PYTHONPATH" not in entries["local-ai"]["env"]
    assert entries["local-ai"]["env"]["LOCAL_AI_AGENT"] == "gemini"


def test_gemini_extension_removes_only_owned_duplicate_routes_and_hooks(tmp_path):
    install = tmp_path / "hub"
    install.mkdir()
    setup.write_install_manifest(install)
    settings = tmp_path / ".gemini" / "settings.json"
    settings.parent.mkdir()
    mcp_entry = {"command": "hub-python", "args": ["-m", "local_ai_hub.mcp_server"]}
    session = {"hooks": [{"name": "local-ai-hub-session-start", "type": "command",
                          "command": 'python host_hooks.py --host gemini_cli'}]}
    before = {"matcher": "read_file|run_shell_command", "hooks": [
        {"name": "local-ai-hub-before-tool", "type": "command",
         "command": 'python host_hooks.py --host gemini_cli'},
        {"name": "user-hook", "type": "command", "command": "user-hook"},
    ]}
    after = {"matcher": "write_file|replace", "hooks": [
        {"name": "local-ai-hub-after-tool", "type": "command",
         "command": 'python host_hooks.py --host gemini_cli'},
    ]}
    data = {"mcpServers": {"local-ai": mcp_entry, "browser": {"command": "browser"}},
            "hooks": {"SessionStart": [session], "BeforeTool": [before], "AfterTool": [after]}}
    settings.write_text(json.dumps(data), encoding="utf-8")
    setup.record_external_json_key(install, settings, container="mcpServers", key="local-ai",
                                   preimage=None, postimage=mcp_entry)
    for event, value in data["hooks"].items():
        setup.record_external_json_key(install, settings, container="hooks", key=event,
                                       preimage=None, postimage=value)

    assert setup.remove_managed_gemini_mcp_route(settings, install, False) is True
    assert setup.remove_managed_gemini_hooks(settings, install, False) is True
    actual = json.loads(settings.read_text(encoding="utf-8"))
    assert actual["mcpServers"] == {"browser": {"command": "browser"}}
    assert "SessionStart" not in actual["hooks"]
    assert "AfterTool" not in actual["hooks"]
    assert actual["hooks"]["BeforeTool"][0]["hooks"] == [
        {"name": "user-hook", "type": "command", "command": "user-hook"},
    ]


def test_gemini_extension_preserves_unowned_duplicate_mcp(tmp_path):
    install = tmp_path / "hub"
    install.mkdir()
    setup.write_install_manifest(install)
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"mcpServers": {"local-ai": {"command": "user"}}}), encoding="utf-8")
    before = settings.read_bytes()

    assert setup.remove_managed_gemini_mcp_route(settings, install, False) is False
    assert settings.read_bytes() == before


def test_cursor_local_plugin_path_detects_hub_plugin(tmp_path):
    cursor = tmp_path / ".cursor"
    manifest = cursor / "plugins" / "local" / "local-ai-hub" / ".cursor-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"name": "local-ai-hub"}), encoding="utf-8")

    assert setup.cursor_hub_plugin_installed(cursor) is True
    assert setup.cursor_hub_plugin_installed(tmp_path / "other-cursor") is False


def test_cursor_plugin_route_preserves_global_duplicates_and_reports_them(tmp_path):
    cursor = tmp_path / ".cursor"
    manifest = cursor / "plugins" / "local" / "local-ai-hub" / ".cursor-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"name": "local-ai-hub"}), encoding="utf-8")
    mcp = cursor / "mcp.json"
    hooks = cursor / "hooks.json"
    mcp.write_text(json.dumps({"mcpServers": {"local-ai": {"command": "python", "args": ["hub"]}}}), encoding="utf-8")
    hooks.write_text(json.dumps({"version": 1, "hooks": {"beforeShellExecution": [
        {"command": "python host_hooks --host cursor --event beforeShellExecution"}
    ]}}), encoding="utf-8")
    before_mcp, before_hooks = mcp.read_bytes(), hooks.read_bytes()
    actions = []

    setup.configure_cursor_global_routes(
        cursor, tmp_path / "install", tmp_path / "python.exe", None, {}, False,
        {"agent_cursor_mcp": True, "agent_cursor_hooks": True}, actions,
    )

    assert mcp.read_bytes() == before_mcp
    assert hooks.read_bytes() == before_hooks
    assert any("standalone Hub MCP" in action for action in actions)
    assert any("global Hub hooks" in action for action in actions)


def test_cursor_without_plugin_keeps_global_mcp_setup(tmp_path):
    cursor = tmp_path / ".cursor"
    actions = []
    setup.configure_cursor_global_routes(
        cursor, tmp_path / "install", tmp_path / "python.exe", None, {}, False,
        {"agent_cursor_mcp": True, "agent_cursor_hooks": False}, actions,
    )
    mcp = json.loads((cursor / "mcp.json").read_text(encoding="utf-8"))
    assert mcp["mcpServers"]["local-ai"]["env"]["LOCAL_AI_AGENT"] == "cursor"


def test_copilot_plugin_route_detects_enabled_user_and_repository_settings(tmp_path):
    copilot = tmp_path / ".copilot"
    copilot.mkdir()
    spec = "local-ai-hub@local-marketplace"
    (copilot / "settings.json").write_text(json.dumps({
        "enabledPlugins": {spec: True}
    }), encoding="utf-8")
    assert setup.copilot_hub_plugin_enabled(copilot, tmp_path / "repo") is True

    (copilot / "settings.json").write_text(json.dumps({"enabledPlugins": {}}), encoding="utf-8")
    repo_settings = tmp_path / "repo" / ".github" / "copilot" / "settings.json"
    repo_settings.parent.mkdir(parents=True)
    repo_settings.write_text(json.dumps({"enabledPlugins": {"local-ai-hub@another-marketplace": True}}), encoding="utf-8")
    assert setup.copilot_hub_plugin_enabled(copilot, tmp_path / "repo") is True

    repo_settings.write_text(json.dumps({"enabledPlugins": {}}), encoding="utf-8")
    (copilot / "settings.json").write_text(json.dumps({"enabledPlugins": {spec: True}}), encoding="utf-8")
    local_settings = repo_settings.with_name("settings.local.json")
    local_settings.write_text(json.dumps({"enabledPlugins": {spec: False}}), encoding="utf-8")
    assert setup.copilot_hub_plugin_enabled(copilot, tmp_path / "repo") is False


def test_copilot_plugin_route_preserves_global_duplicates_and_reports_them(tmp_path):
    copilot = tmp_path / ".copilot"
    copilot.mkdir()
    (copilot / "settings.json").write_text(json.dumps({
        "enabledPlugins": {"local-ai-hub@local-marketplace": True}
    }), encoding="utf-8")
    mcp = copilot / "mcp-config.json"
    hooks = copilot / "hooks" / "local-ai-hub.json"
    hooks.parent.mkdir()
    mcp.write_text(json.dumps({"mcpServers": {"local-ai": {"type": "local"}}}), encoding="utf-8")
    hooks.write_text(json.dumps({"hooks": {"preToolUse": [{
        "command": "python host_hooks.py --host copilot --event preToolUse"
    }]}}), encoding="utf-8")
    before_mcp, before_hooks = mcp.read_bytes(), hooks.read_bytes()
    actions = []

    setup.configure_copilot_global_routes(
        copilot, tmp_path / "repo", tmp_path / "install", tmp_path / "python.exe", None, {}, False,
        {"agent_copilot_mcp": True, "agent_copilot_hooks": True}, actions,
    )

    assert mcp.read_bytes() == before_mcp
    assert hooks.read_bytes() == before_hooks
    assert any("standalone Hub MCP" in action for action in actions)
    assert any("Copilot tool hooks not installed" in action for action in actions)


def test_copilot_plugin_route_still_installs_distinct_tool_hooks(tmp_path):
    copilot = tmp_path / ".copilot"
    copilot.mkdir()
    (copilot / "settings.json").write_text(json.dumps({
        "enabledPlugins": {"local-ai-hub@local-marketplace": True}
    }), encoding="utf-8")
    install = tmp_path / "install"
    hook_source = install / "src" / "local_ai_hub" / "repo_plan" / "host_hooks.py"
    hook_source.parent.mkdir(parents=True)
    hook_source.write_text("# temporary fixture\n", encoding="utf-8")
    actions = []

    setup.configure_copilot_global_routes(
        copilot, tmp_path / "repo", install, tmp_path / "python.exe", None, {}, False,
        {"agent_copilot_mcp": False, "agent_copilot_hooks": True}, actions,
    )

    hooks = json.loads((copilot / "hooks" / "local-ai-hub.json").read_text(encoding="utf-8"))
    assert set(hooks["hooks"]) == {"preToolUse", "postToolUse"}
    assert actions == []


def test_copilot_plugin_route_reports_only_same_event_global_hook(tmp_path):
    copilot = tmp_path / ".copilot"
    copilot.mkdir()
    (copilot / "settings.json").write_text(json.dumps({
        "enabledPlugins": {"local-ai-hub@local-marketplace": True}
    }), encoding="utf-8")
    hooks = copilot / "hooks" / "local-ai-hub.json"
    hooks.parent.mkdir()
    original = {"version": 1, "hooks": {"sessionStart": [{
        "type": "command", "command": "python host_hooks.py --host copilot"
    }]}}
    hooks.write_text(json.dumps(original), encoding="utf-8")
    actions = []

    setup.configure_copilot_global_routes(
        copilot, tmp_path / "repo", tmp_path / "install", tmp_path / "python.exe", None, {}, False,
        {"agent_copilot_mcp": False, "agent_copilot_hooks": True}, actions,
    )

    assert json.loads(hooks.read_text(encoding="utf-8")) == original
    assert any("SessionStart" in action for action in actions)


@pytest.mark.parametrize("scope", ["user_settings", "repo_settings", "repo_claude", "repo_hooks", "user_hook_file"])
def test_copilot_plugin_route_installs_only_missing_tool_hook_events(tmp_path, scope):
    copilot = tmp_path / ".copilot"
    copilot.mkdir()
    user_settings = {"enabledPlugins": {"local-ai-hub@local-marketplace": True}}
    if scope == "user_settings":
        user_settings["hooks"] = {"preToolUse": [{
            "type": "command", "command": "python -m local_ai_hub.repo_plan.host_hooks --host copilot"
        }]}
    (copilot / "settings.json").write_text(json.dumps(user_settings), encoding="utf-8")

    repo = tmp_path / "repo"
    hook_config = {"hooks": {"PreToolUse": [{
        "type": "command", "command": "python -m local_ai_hub.repo_plan.host_hooks --host copilot"
    }]}}
    if scope == "repo_settings":
        target = repo / ".github" / "copilot" / "settings.json"
    elif scope == "repo_claude":
        target = repo / ".claude" / "settings.local.json"
    elif scope == "repo_hooks":
        target = repo / ".github" / "hooks" / "hub.json"
    elif scope == "user_hook_file":
        target = copilot / "hooks" / "other.json"
    else:
        target = None
    if target is not None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(hook_config), encoding="utf-8")

    install = tmp_path / "install"
    hook_source = install / "src" / "local_ai_hub" / "repo_plan" / "host_hooks.py"
    hook_source.parent.mkdir(parents=True)
    hook_source.write_text("# temporary fixture\n", encoding="utf-8")
    actions = []
    setup.configure_copilot_global_routes(
        copilot, repo, install, tmp_path / "python.exe", None, {}, False,
        {"agent_copilot_mcp": False, "agent_copilot_hooks": True}, actions,
    )

    managed = json.loads((copilot / "hooks" / "local-ai-hub.json").read_text(encoding="utf-8"))
    assert set(managed["hooks"]) == {"postToolUse"}
    assert any("pretooluse" in action.casefold() for action in actions)


def test_copilot_without_plugin_keeps_global_mcp_setup(tmp_path):
    copilot = tmp_path / ".copilot"
    actions = []
    setup.configure_copilot_global_routes(
        copilot, tmp_path / "repo", tmp_path / "install", tmp_path / "python.exe", None, {}, False,
        {"agent_copilot_mcp": True, "agent_copilot_hooks": False}, actions,
    )
    mcp = json.loads((copilot / "mcp-config.json").read_text(encoding="utf-8"))
    assert mcp["mcpServers"]["local-ai"]["env"]["LOCAL_AI_AGENT"] == "copilot"


def test_gemini_cli_extension_disabled_setting_selects_global_route(tmp_path):
    gemini = tmp_path / ".gemini"
    extension = gemini / "extensions" / "local-ai-hub" / "gemini-extension.json"
    extension.parent.mkdir(parents=True)
    extension.write_text(json.dumps({"name": "local-ai-hub"}), encoding="utf-8")
    settings = gemini / "settings.json"
    settings.write_text(json.dumps({"extensions": {"disabled": ["local-ai-hub"]}}), encoding="utf-8")

    assert setup.gemini_cli_extension_active(gemini) is False

    project = tmp_path / "repo"
    (project / ".gemini").mkdir(parents=True)
    (project / ".gemini" / "settings.json").write_text(
        json.dumps({"extensions": {"disabled": []}}), encoding="utf-8",
    )
    assert setup.gemini_cli_extension_active(gemini, project) is True


def test_gemini_setup_preserves_plugin_and_global_routes_without_duplication(tmp_path, monkeypatch):
    gemini = tmp_path / ".gemini"
    install = tmp_path / "install"
    extension = gemini / "extensions" / "local-ai-hub" / "gemini-extension.json"
    plugin = gemini / "config" / "plugins" / "local-ai-hub" / "plugin.json"
    extension.parent.mkdir(parents=True)
    plugin.parent.mkdir(parents=True)
    extension.write_text(json.dumps({"name": "local-ai-hub"}), encoding="utf-8")
    plugin.write_text(json.dumps({"name": "local-ai-hub"}), encoding="utf-8")
    gemini_settings = gemini / "settings.json"
    antigravity_mcp = gemini / "config" / "mcp_config.json"
    gemini_settings.parent.mkdir(parents=True, exist_ok=True)
    gemini_settings.write_text(json.dumps({"mcpServers": {"local-ai": {"command": "keep"}}}), encoding="utf-8")
    antigravity_mcp.write_text(json.dumps({"mcpServers": {"local-ai": {"command": "keep"}}}), encoding="utf-8")
    before_gemini = gemini_settings.read_bytes()
    before_antigravity = antigravity_mcp.read_bytes()
    monkeypatch.setattr(setup, "sync_antigravity_mcp_config", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("duplicate route")))
    actions = []

    setup._configure_gemini_instance_impl(
        gemini, install, tmp_path / "python.exe", None, {}, False, False,
        agent_components={"agent_gemini_mcp": True, "agent_gemini_hooks": False,
                          "agent_gemini_skills": False, "agent_gemini_instructions": False,
                          "agent_antigravity_mcp": True},
        manual_actions=actions,
    )

    assert gemini_settings.read_bytes() == before_gemini
    assert antigravity_mcp.read_bytes() == before_antigravity
    assert any("Gemini CLI extension" in action for action in actions)
    assert any("Antigravity plugin" in action for action in actions)


@pytest.mark.parametrize("known_backup", [True, False])
def test_migration_recovery_report_lists_verified_backups(tmp_path, known_backup):
    install = tmp_path / "install"
    install.mkdir()
    state = tmp_path / "state"
    migrations = setup._state_migrations_module
    migrations.write_state_version(state, version=1)
    (state / "records.txt").write_text("original records", encoding="utf-8")

    def fail_migration(staged):
        (staged / "records.txt").write_text("partial changes", encoding="utf-8")
        raise RuntimeError("verification fixture failed")

    steps = (migrations.StateMigration(1, 2, fail_migration, lambda _root: False),) if known_backup else ()
    with pytest.raises(RuntimeError) as error:
        setup.run_state_migrations(state, migrations=steps, target_version=2)
    setup.write_migration_failure_report(
        install, state, stage="apply" if known_backup else "preflight", error=error.value,
    )

    report = json.loads((install / "setup-report.json").read_text(encoding="utf-8"))
    retained = list(tmp_path.glob("state.backup-v1-*"))
    assert len(retained) == int(known_backup)
    assert report["migration"]["backups"] == [str(path) for path in retained]
    assert (state / "records.txt").read_text(encoding="utf-8") == "original records"
    if known_backup:
        assert (retained[0] / "records.txt").read_text(encoding="utf-8") == "original records"


@pytest.mark.skipif(os.name != 'nt', reason='Windows batch executable lookup')
def test_run_resolves_windows_batch_executables(tmp_path, monkeypatch):
    script = tmp_path / 'hub-test-command.cmd'
    script.write_text('@echo off\necho batch-ok\n')
    monkeypatch.setenv('PATH', str(tmp_path) + os.pathsep + os.environ['PATH'])
    result = setup.run(['hub-test-command'], capture=True)
    assert result.stdout.strip() == 'batch-ok'


def test_copilot_hook_installs_reversibly_and_preserves_unowned_file(tmp_path, capsys):
    install = tmp_path / "install"
    hook_source = install / "src" / "local_ai_hub" / "repo_plan" / "host_hooks.py"
    hook_source.parent.mkdir(parents=True)
    hook_source.write_text("# managed source\n", encoding="utf-8")
    python = tmp_path / "python.exe"
    python.write_text("", encoding="utf-8")
    target = tmp_path / "home" / ".copilot" / "hooks" / "local-ai-hub.json"

    assert setup.sync_copilot_tool_hooks(target, install, python, False)
    configured = json.loads(target.read_text(encoding="utf-8"))
    assert configured["version"] == 1
    hook = configured["hooks"]["preToolUse"][0]
    assert hook["command"].endswith("--host copilot --event preToolUse")
    assert hook["timeoutSec"] == 5
    assert "timeout" not in hook
    post_hook = configured["hooks"]["postToolUse"][0]
    assert post_hook["command"].endswith("--host copilot --event postToolUse")
    assert post_hook["matcher"] == "^(create|edit)$"
    assert post_hook["timeoutSec"] == 5

    target.write_text('{"version":1,"hooks":{"custom":[]}}\n', encoding="utf-8")
    assert not setup.sync_copilot_tool_hooks(target, install, python, False)
    assert json.loads(target.read_text(encoding="utf-8"))["hooks"] == {"custom": []}


def test_windsurf_hooks_install_bounded_command_read_mcp_and_edit_checks(tmp_path, monkeypatch):
    install = tmp_path / "install"
    hook_source = install / "src" / "local_ai_hub" / "windsurf_hook.py"
    hook_source.parent.mkdir(parents=True)
    hook_source.write_text("# managed source\n", encoding="utf-8")
    python = tmp_path / "python.exe"
    python.write_text("", encoding="utf-8")
    target = tmp_path / "home" / ".codeium" / "windsurf" / "hooks.json"
    monkeypatch.setattr(setup, "_ACTIVE_INSTALL_ROOT", None)

    assert setup.sync_windsurf_policy_hooks(target, install, python, False)
    configured = json.loads(target.read_text(encoding="utf-8"))
    assert set(configured["hooks"]) == {"pre_run_command", "pre_read_code", "pre_mcp_tool_use", "post_write_code"}
    for event in configured["hooks"].values():
        assert event[0]["command"].endswith('windsurf_hook.py"')
        assert event[0]["show_output"] is True
    assert setup.sync_windsurf_policy_hooks(target, install, python, False)
    assert len(json.loads(target.read_text(encoding="utf-8"))["hooks"]["pre_run_command"]) == 1


def test_copilot_home_respects_environment_override(tmp_path, monkeypatch):
    monkeypatch.setenv("COPILOT_HOME", str(tmp_path / "copilot-config"))
    assert setup.copilot_home() == tmp_path / "copilot-config"
    assert setup.copilot_hook_path() == tmp_path / "copilot-config" / "hooks" / "local-ai-hub.json"


def test_devin_setup_uses_native_windows_config_and_pre_tool_hook(tmp_path, monkeypatch):
    install = tmp_path / "install"
    hook_source = install / "src" / "local_ai_hub" / "repo_plan" / "host_hooks.py"
    hook_source.parent.mkdir(parents=True)
    hook_source.write_text("# managed source\n", encoding="utf-8")
    python = tmp_path / "python.exe"
    python.write_text("", encoding="utf-8")
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))

    assert setup.devin_config_dir() == tmp_path / "AppData" / "Roaming" / "devin"
    target = setup.devin_config_dir() / "config.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({"theme": "dark", "hooks": {"SessionStart": []}}), encoding="utf-8")

    assert setup.sync_devin_pre_tool_hook(target, install, python, False)
    configured = json.loads(target.read_text(encoding="utf-8"))
    assert configured["theme"] == "dark"
    group = configured["hooks"]["PreToolUse"][0]
    assert group["matcher"] == "exec"
    hook = group["hooks"][0]
    assert hook["command"].endswith("--host devin --event PreToolUse")
    assert hook["timeout"] == 5
    assert setup.sync_devin_pre_tool_hook(target, install, python, False)
    assert len(json.loads(target.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]) == 1


def test_devin_post_tool_hook_installs_idempotently_and_preserves_unowned_list(tmp_path, monkeypatch):
    install = tmp_path / "install"
    hook_source = install / "src" / "local_ai_hub" / "repo_plan" / "host_hooks.py"
    hook_source.parent.mkdir(parents=True)
    hook_source.write_text("# managed source\n", encoding="utf-8")
    python = tmp_path / "python.exe"
    python.write_text("", encoding="utf-8")
    target = tmp_path / "config.json"
    target.write_text('{"theme":"dark","hooks":{"SessionStart":[]}}')
    monkeypatch.setattr(setup, "_ACTIVE_INSTALL_ROOT", None)

    assert setup.sync_devin_post_tool_hook(target, install, python, False)
    config = json.loads(target.read_text(encoding="utf-8"))
    group = config["hooks"]["PostToolUse"][0]
    assert group["matcher"] == "^(edit|write|apply_patch)$"
    hook = group["hooks"][0]
    assert hook["command"].endswith("--host devin --event PostToolUse")
    assert hook["timeout"] == 5
    assert config["theme"] == "dark"
    assert setup.sync_devin_post_tool_hook(target, install, python, False)
    assert len(json.loads(target.read_text(encoding="utf-8"))["hooks"]["PostToolUse"]) == 1

    unowned = tmp_path / "unowned-config.json"
    user_hook = {"matcher": "*", "hooks": [{"type": "command", "command": "user-hook"}]}
    unowned.write_text(json.dumps({"hooks": {"PostToolUse": [user_hook]}}), encoding="utf-8")
    monkeypatch.setattr(setup, "_ACTIVE_INSTALL_ROOT", install)
    assert not setup.sync_devin_post_tool_hook(unowned, install, python, False)
    assert json.loads(unowned.read_text(encoding="utf-8"))["hooks"]["PostToolUse"] == [user_hook]


def test_copilot_cli_mcp_uses_native_mcp_servers_format(tmp_path):
    path = tmp_path / "mcp-config.json"
    entries = {"local-ai": {"command": "python", "args": ["-m", "local_ai_hub.mcp_server"]}}
    setup.json_mcp_merge(path, entries, False)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["mcpServers"]["local-ai"]["command"] == "python"
    assert "servers" not in manifest


def test_claude_tool_policy_hook_preserves_host_approvals_and_user_hooks(tmp_path, monkeypatch):
    install = tmp_path / "install"
    hook_source = install / "src" / "local_ai_hub" / "repo_plan" / "host_hooks.py"
    hook_source.parent.mkdir(parents=True)
    hook_source.write_text("# managed source\n", encoding="utf-8")
    python = tmp_path / "python.exe"
    python.write_text("", encoding="utf-8")
    target = tmp_path / "settings.json"
    target.write_text('{"permissions":{"defaultMode":"default"}}\n', encoding="utf-8")
    monkeypatch.setattr(setup, "_ACTIVE_INSTALL_ROOT", None)

    assert setup.sync_claude_pre_tool_hook(target, install, python, False)
    settings = json.loads(target.read_text(encoding="utf-8"))
    hook = settings["hooks"]["PreToolUse"][0]
    assert hook["matcher"] == "Bash|PowerShell|Read"
    assert settings["permissions"]["defaultMode"] == "default"
    assert setup.sync_claude_pre_tool_hook(target, install, python, False)
    assert len(json.loads(target.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]) == 1

    user_target = tmp_path / "user-settings.json"
    user_target.write_text('{"hooks":{"PreToolUse":[{"matcher":"Write","hooks":[]}]}}\n', encoding="utf-8")
    monkeypatch.setattr(setup, "_ACTIVE_INSTALL_ROOT", install)
    assert not setup.sync_claude_pre_tool_hook(user_target, install, python, False)
    assert json.loads(user_target.read_text(encoding="utf-8"))["hooks"]["PreToolUse"] == [{"matcher": "Write", "hooks": []}]


def test_claude_permission_request_hook_installs_idempotently_and_preserves_unowned_list(tmp_path, monkeypatch):
    install = tmp_path / "install"
    hook_source = install / "src" / "local_ai_hub" / "repo_plan" / "host_hooks.py"
    hook_source.parent.mkdir(parents=True)
    hook_source.write_text("# managed source\n", encoding="utf-8")
    python = tmp_path / "python.exe"
    python.write_text("", encoding="utf-8")
    target = tmp_path / "settings.json"
    target.write_text('{"permissions":{"defaultMode":"default"}}\n', encoding="utf-8")
    monkeypatch.setattr(setup, "_ACTIVE_INSTALL_ROOT", None)

    assert setup.sync_claude_permission_request_hook(target, install, python, False)
    settings = json.loads(target.read_text(encoding="utf-8"))
    hook = settings["hooks"]["PermissionRequest"][0]
    assert hook["matcher"] == "Bash|PowerShell|Read"
    assert settings["permissions"]["defaultMode"] == "default"
    assert setup.sync_claude_permission_request_hook(target, install, python, False)
    assert len(json.loads(target.read_text(encoding="utf-8"))["hooks"]["PermissionRequest"]) == 1

    user_target = tmp_path / "user-settings.json"
    user_hook = {"matcher": "Write", "hooks": []}
    user_target.write_text(json.dumps({"hooks": {"PermissionRequest": [user_hook]}}), encoding="utf-8")
    monkeypatch.setattr(setup, "_ACTIVE_INSTALL_ROOT", install)
    assert not setup.sync_claude_permission_request_hook(user_target, install, python, False)
    assert json.loads(user_target.read_text(encoding="utf-8"))["hooks"]["PermissionRequest"] == [user_hook]


def test_claude_post_tool_hook_installs_idempotently_and_preserves_unowned_list(tmp_path, monkeypatch):
    install = tmp_path / "install"
    hook_source = install / "src" / "local_ai_hub" / "repo_plan" / "host_hooks.py"
    hook_source.parent.mkdir(parents=True)
    hook_source.write_text("# managed source\n", encoding="utf-8")
    python = tmp_path / "python.exe"
    python.write_text("", encoding="utf-8")
    target = tmp_path / "settings.json"
    target.write_text('{"permissions":{"defaultMode":"default"}}\n', encoding="utf-8")
    monkeypatch.setattr(setup, "_ACTIVE_INSTALL_ROOT", None)

    assert setup.sync_claude_post_tool_hook(target, install, python, False)
    settings = json.loads(target.read_text(encoding="utf-8"))
    hook = settings["hooks"]["PostToolUse"][0]
    assert hook["matcher"] == "Edit|Write"
    assert hook["hooks"][0]["timeout"] == 5
    assert settings["permissions"]["defaultMode"] == "default"
    assert setup.sync_claude_post_tool_hook(target, install, python, False)
    assert len(json.loads(target.read_text(encoding="utf-8"))["hooks"]["PostToolUse"]) == 1

    unowned = tmp_path / "unowned.json"
    user_hook = {"matcher": "*", "hooks": [{"type": "command", "command": "user-hook"}]}
    unowned.write_text(json.dumps({"hooks": {"PostToolUse": [user_hook]}}), encoding="utf-8")
    monkeypatch.setattr(setup, "_ACTIVE_INSTALL_ROOT", install)
    assert not setup.sync_claude_post_tool_hook(unowned, install, python, False)
    assert json.loads(unowned.read_text(encoding="utf-8"))["hooks"]["PostToolUse"] == [user_hook]


def test_cursor_shell_hook_installs_fail_closed_without_granting_execution(tmp_path, monkeypatch):
    install = tmp_path / "install"
    hook_source = install / "src" / "local_ai_hub" / "repo_plan" / "host_hooks.py"
    hook_source.parent.mkdir(parents=True)
    hook_source.write_text("# managed source\n", encoding="utf-8")
    python = tmp_path / "python.exe"
    python.write_text("", encoding="utf-8")
    target = tmp_path / "hooks.json"
    target.write_text(json.dumps({"version": 1, "hooks": {"sessionStart": [{"command": "user-hook"}]}}))
    monkeypatch.setattr(setup, "_ACTIVE_INSTALL_ROOT", None)

    assert setup.sync_cursor_before_shell_hook(target, install, python, False)
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["hooks"]["sessionStart"] == [{"command": "user-hook"}]
    entry = data["hooks"]["beforeShellExecution"][0]
    assert entry["failClosed"] is True
    assert entry["command"].endswith("--host cursor --event beforeShellExecution")
    assert setup.sync_cursor_before_shell_hook(target, install, python, False)
    assert len(json.loads(target.read_text(encoding="utf-8"))["hooks"]["beforeShellExecution"]) == 1

    target.write_text(json.dumps({"version": 1, "hooks": {"beforeShellExecution": [{"command": "user-hook"}]}}))
    monkeypatch.setattr(setup, "_ACTIVE_INSTALL_ROOT", install)
    assert not setup.sync_cursor_before_shell_hook(target, install, python, False)
    assert json.loads(target.read_text(encoding="utf-8"))["hooks"]["beforeShellExecution"] == [{"command": "user-hook"}]


def test_cursor_after_file_edit_hook_installs_idempotently_and_preserves_unowned_list(tmp_path, monkeypatch):
    install = tmp_path / "install"
    hook_source = install / "src" / "local_ai_hub" / "repo_plan" / "host_hooks.py"
    hook_source.parent.mkdir(parents=True)
    hook_source.write_text("# managed source\n", encoding="utf-8")
    python = tmp_path / "python.exe"
    python.write_text("", encoding="utf-8")
    target = tmp_path / "hooks.json"
    target.write_text(json.dumps({"version": 1, "hooks": {"sessionStart": [{"command": "user-hook"}]}}))
    monkeypatch.setattr(setup, "_ACTIVE_INSTALL_ROOT", None)

    assert setup.sync_cursor_after_file_edit_hook(target, install, python, False)
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["hooks"]["sessionStart"] == [{"command": "user-hook"}]
    hook = data["hooks"]["afterFileEdit"][0]
    assert hook["command"].endswith("--host cursor --event afterFileEdit")
    assert setup.sync_cursor_after_file_edit_hook(target, install, python, False)
    assert len(json.loads(target.read_text(encoding="utf-8"))["hooks"]["afterFileEdit"]) == 1

    target.write_text(json.dumps({"version": 1, "hooks": {"afterFileEdit": [{"command": "user-hook"}]}}))
    monkeypatch.setattr(setup, "_ACTIVE_INSTALL_ROOT", install)
    assert not setup.sync_cursor_after_file_edit_hook(target, install, python, False)
    assert json.loads(target.read_text(encoding="utf-8"))["hooks"]["afterFileEdit"] == [{"command": "user-hook"}]


def test_provider_report_does_not_confuse_setup_with_runtime_or_trust():
    report = setup.provider_integration_status(
        ("claude", "windsurf"),
        {"claude": True, "windsurf": False},
        {"claude": {"mcp": "configured"}, "windsurf": {"mcp": "not_selected"}},
        {"claude": "configured", "windsurf": "not_supported_by_hub_setup"},
        {"claude": "not_supported_by_hub_setup", "windsurf": "not_supported_by_hub_setup"},
    )
    assert report["claude"]["selected_for_setup"] is True
    assert report["claude"]["connection"] == "not_probed_by_setup"
    assert report["claude"]["trust"] == "host_controlled_not_observed"
    assert report["claude"]["runtime_verification"] == "not_run"
    assert report["windsurf"]["hooks"] == "not_supported_by_hub_setup"


def test_provider_report_distinguishes_configured_host_install_and_enabled_states():
    report = setup.provider_integration_status(
        ("claude", "windsurf"),
        {"claude": True, "windsurf": False},
        {"claude": {"mcp": "configured", "skills": "configured"},
         "windsurf": {"mcp": "not_selected"}},
        {"claude": "configured", "windsurf": "not_selected"},
        {"claude": "bundled_external_installation_and_trust_not_probed",
         "windsurf": "not_supported_by_hub_setup"},
    )

    assert report["claude"]["configured"] == "configured_by_setup"
    assert report["claude"]["installed"] == "not_observed_by_setup"
    assert report["claude"]["enabled"] == "not_observed_by_setup"
    assert report["claude"]["trust"] == "host_controlled_not_observed"
    assert report["claude"]["connection"] == "not_probed_by_setup"
    assert report["claude"]["runtime_verification"] == "not_run"
    assert report["windsurf"]["configured"] == "not_selected"
    assert json.loads(json.dumps(report)) == report


def test_provider_manual_actions_are_not_broadcast_to_other_providers():
    actions = [
        "OpenCode standalone Hub MCP already exists; existing route was preserved",
        "Gemini and Antigravity shared instructions were preserved",
        "A path with no provider identity needs review",
    ]

    attributed = setup.provider_manual_actions(actions)

    assert attributed["opencode"] == [actions[0]]
    assert attributed["gemini"] == [actions[1]]
    assert attributed["antigravity"] == [actions[1]]
    assert attributed["claude"] == []
    assert attributed["unattributed"] == [actions[2]]

    assert setup.provider_setup_component_state(
        True, manual_actions=attributed["opencode"],
    ) == "configured_with_manual_steps"
    assert setup.provider_setup_component_state(
        True, manual_actions=attributed["claude"],
    ) == "configured"
    assert setup.provider_setup_component_state(
        True, batch_error="write failed",
    ) == "outcome_unknown_after_batch_error"


def test_provider_report_does_not_claim_failure_scope_after_batch_error():
    report = setup.provider_integration_status(
        ("claude", "opencode"),
        {"claude": True, "opencode": True},
        {"claude": {"mcp": "configured"}, "opencode": {"plugin": "configured"}},
        {"claude": "configured", "opencode": "not_separate_from_plugin"},
        {"claude": "not_supported_by_hub_setup", "opencode": "configured"},
        batch_error="write failed after partial setup",
    )

    assert report["claude"]["configured"] == "outcome_unknown_after_batch_error"
    assert report["opencode"]["configured"] == "outcome_unknown_after_batch_error"


def test_codex_plugin_packages_skills_and_all_configured_hook_surfaces():
    plugin_root = ROOT / "plugins" / "codex" / "local-ai-hub"
    manifest = json.loads((plugin_root / "plugin.json").read_text(encoding="utf-8"))
    hook_config = json.loads((plugin_root / "hooks" / "hooks.json").read_text(encoding="utf-8"))

    assert manifest["skills"] == "./skills/"
    onboarding = plugin_root / manifest["extensions"]["com.openai"]["onboardingSkill"].removeprefix("./")
    assert onboarding.is_file()
    assert set(hook_config["hooks"]) >= {
        "SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
    }


def test_setup_skip_service_does_not_restart_global_hub_without_registering_service(tmp_path, monkeypatch):
    config_source = tmp_path / "config.toml"
    config_source.write_text("[hardware]\nprofile = \"auto\"\n", encoding="utf-8")
    install_dir = tmp_path / "install"
    config = {
        "setup": {
            "install_agent_configs": False,
            "install_optional_tools": False,
            "install_service": True,
        },
        "hardware": {"profile": "cpu"},
        "_hardware": {"gpus": [], "npus": [], "profile": "cpu", "os": "Windows", "arch": "AMD64"},
        "features": {
            "rag": False,
            "reranker": False,
            "install_local_nlp_dependencies": False,
            "install_openvino_dependencies": False,
            "pull_models_during_setup": False,
        },
        "models": {"embedding_backend": "none", "reranker_backend": "none"},
        "code_intelligence": {"serena_enabled": False},
        "headless": {"enabled": True},
        "ollama": {"enabled": False},
        "llama_cpp": {"mode": "off"},
        "tools": {},
    }
    commands = []
    restart_timeouts = []

    monkeypatch.setattr(setup, "select_config_source", lambda _path: (config_source, config, install_dir))

    def copy_install_tree(destination, _source, *, before_commit=None, after_swap=None):
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "config.toml").write_text("[hardware]\nprofile = \"auto\"\n", encoding="utf-8")
        if after_swap is not None:
            assert after_swap()[0] is True
        return True

    monkeypatch.setattr(setup, "copy_install_tree", copy_install_tree)
    monkeypatch.setattr(setup, "load_hub_config", lambda _path: config)
    monkeypatch.setattr(setup, "ensure_venv", lambda _path: tmp_path / "python.exe")
    monkeypatch.setattr(setup, "install_requirements", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(setup, "write_generated_agent_manifests", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup, "ensure_ollama_for_setup", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup, "pull_ollama_models", lambda *_args, **_kwargs: {"unavailable": []})
    monkeypatch.setattr(setup, "ensure_llama_cpp_for_setup", lambda *_args, **_kwargs: None)
    def capture_run(command, **kwargs):
        commands.append([str(part) for part in command])
        if command[-1:] == ["restart"] and any(Path(part).name == "hubctl.py" for part in command):
            restart_timeouts.append(kwargs.get("timeout"))

    monkeypatch.setattr(setup, "run", capture_run)
    monkeypatch.setattr(sys, "argv", [
        "setup.py", "--config", str(config_source), "--profile", "cpu", "--skip-service",
        "--skip-tools", "--skip-agent-config", "--skip-token-economy", "--skip-model-pull",
        "--skip-local-nlp-preload", "--skip-ollama-install", "--skip-companion-skills",
    ])

    assert setup.main() == 0
    assert restart_timeouts == []
    assert sum(
        command[-1:] == ["restart"] and any(part.endswith("tools/hubctl.py") or part.endswith("tools\\hubctl.py") for part in command)
        for command in commands
    ) == 0
    assert not any(command[-1:] == ["install"] and any(part.endswith("tools/service.py") or part.endswith("tools\\service.py") for part in command) for command in commands)


def test_setup_stop_failure_skips_runtime_setup_and_service_start(tmp_path, monkeypatch):
    config_source = tmp_path / "config.toml"
    config_source.write_text("[hardware]\nprofile = \"auto\"\n", encoding="utf-8")
    install_dir = tmp_path / "install"
    config = {"setup": {}}
    events = []
    stop_attempts = []

    monkeypatch.setattr(setup, "select_config_source", lambda _path: (config_source, config, install_dir))

    def fail_to_stop(*_args, **_kwargs):
        stop_attempts.append(True)
        return False, "stop outcome unknown"

    monkeypatch.setattr(setup, "stop_existing_runtime", fail_to_stop)

    def copy_install_tree(_destination, _source, *, before_commit=None, after_swap=None):
        assert before_commit is not None
        stopped, _detail = before_commit()
        return stopped

    monkeypatch.setattr(setup, "copy_install_tree", copy_install_tree)
    monkeypatch.setattr(setup, "ensure_venv", lambda _path: events.append("venv"))
    monkeypatch.setattr(setup, "run", lambda command, **_kwargs: events.append(command))
    monkeypatch.setattr(sys, "argv", ["setup.py", "--config", str(config_source), "--profile", "cpu"])

    assert setup.main() == 1
    assert stop_attempts == [True]
    assert events == []


def test_token_economy_launchers_and_trim_run_allowlist(tmp_path, monkeypatch):
    scripts = tmp_path / '.venv' / ('Scripts' if setup.os.name == 'nt' else 'bin')
    scripts.mkdir(parents=True)
    registered = []
    monkeypatch.setattr(setup, "persist_token_economy_path", registered.append)
    setup.install_token_economy_suite(tmp_path, Path(sys.executable), allow_external_tools=False)
    assert registered == [scripts]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    for tool in ('tokcount', 'trim-run', 'repo-map'):
        launcher = scripts / (tool + '.cmd' if setup.os.name == 'nt' else tool)
        assert len(launcher.read_text().splitlines()) == 2
        if setup.os.name != 'nt':
            assert launcher.stat().st_mode & 0o111
        if tool == 'trim-run':
            unsafe = subprocess.run(
                [str(launcher), 'python', '-c', 'print(12345)'],
                capture_output=True, text=True, timeout=15, env=env,
            )
            assert unsafe.returncode == 2
            assert "not in the safe" in unsafe.stderr
            args = ['tokcount', '--help']
        else:
            args = ['--help']
        cp = subprocess.run([str(launcher), *args], capture_output=True, text=True, timeout=15, env=env)
        assert cp.returncode == 0, cp.stderr
        assert 'usage:' in cp.stdout.lower()



def test_token_economy_path_is_persisted_idempotently(tmp_path: Path):
    scripts = tmp_path / ".local-ai-hub" / ".venv" / "bin"
    setup.persist_token_economy_path(scripts, home=tmp_path, windows=False, shell="bash")
    setup.persist_token_economy_path(scripts, home=tmp_path, windows=False, shell="bash")

    profile = (tmp_path / ".profile").read_text(encoding="utf-8")
    assert profile.count("# BEGIN LOCAL AI HUB TOKEN TOOLS PATH") == 1
    assert str(scripts) in profile


def test_token_economy_path_merge_preserves_existing_entries(tmp_path: Path):
    scripts = tmp_path / "bin"
    existing = os.pathsep.join(["existing-tool-dir", str(scripts)])
    assert setup._merge_path_entry(existing, scripts, windows=os.name == "nt") == existing


def test_token_economy_path_merge_deduplicates_case_insensitively(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(setup.os, "pathsep", ":")
    scripts = Path(r"C:\Users\Test\TokenTools")
    existing = r"C:\Users\Test\tokentools;D:\Existing"
    assert setup._merge_path_entry(existing, scripts, windows=True) == existing


def test_compact_agent_config_is_default(tmp_path: Path):
    install = tmp_path / "install"
    py = tmp_path / "python"
    serena = tmp_path / "serena"
    cfg = {"code_intelligence": {"direct_agent_mcp": False, "serena_enabled": True}}
    entries = setup.build_mcp_entries(install, py, serena, "codex", cfg)
    assert set(entries) == {"local-ai"}
    assert entries["local-ai"]["env"]["LOCAL_AI_AGENT"] == "codex"
    assert entries["local-ai"]["args"] == ["-m", "local_ai_hub.mcp_server"]
    assert entries["local-ai"]["env"]["PYTHONPATH"] == str(install / "src")
    # Global MCP adapters launch from the Hub install. Repository-scoped
    # operations must still receive the caller's explicit root.
    assert entries["local-ai"]["cwd"] == str(install)


def test_global_policy_has_explicit_read_only_and_fallback_contract() -> None:
    policy = setup.GLOBAL_POLICY

    for phrase in (
        "READ-ONLY AUDIT CONTRACT",
        "git worktree add",
        "terminal=true",
        "retryable=false",
        "sandbox",
        "allow_write",
        "Codex controls each subagent's scope",
        "Native `multi_agent_v1__spawn_agent` is used only for useful independent bounded work",
    ):
        assert phrase in policy


@pytest.mark.parametrize("relative_path", ["docs/INSTALL_PROMPT.md", "docs/UPDATE_PROMPT.md"])
def test_instruction_policy_blocks_match_generated_policy_sources(relative_path: str) -> None:
    text = (ROOT / relative_path).read_text(encoding="utf-8")
    expected_agent = setup.generate_global_policy({})
    expected_token = setup.generate_token_economy_policy({})

    def block(begin: str, end: str) -> str:
        start = text.find(begin)
        assert start >= 0, f"{relative_path} missing {begin}"
        assert text.find(begin, start + len(begin)) < 0, f"{relative_path} repeats {begin}"
        finish = text.find(end, start + len(begin))
        assert finish >= 0, f"{relative_path} missing {end}"
        return text[start:finish + len(end)]

    assert block(setup.GLOBAL_POLICY_BEGIN, setup.GLOBAL_POLICY_END) == expected_agent
    assert block(setup.TOKEN_ECONOMY_POLICY_BEGIN, setup.TOKEN_ECONOMY_POLICY_END) == expected_token


def test_direct_serena_is_explicit_opt_in(tmp_path: Path):
    cfg = {"code_intelligence": {"direct_agent_mcp": True, "serena_enabled": True}}
    entries = setup.build_mcp_entries(tmp_path, tmp_path / "python", tmp_path / "serena", "codex", cfg)
    assert set(entries) == {"local-ai", "serena"}
    assert "--project-from-cwd" in entries["serena"]["args"]


def test_direct_agent_serena_context_matches_gemini(tmp_path: Path):
    cfg = {"code_intelligence": {"direct_agent_mcp": True, "serena_enabled": True}}
    entries = setup.build_mcp_entries(tmp_path, tmp_path / "python", tmp_path / "serena", "gemini", cfg)
    assert entries["serena"]["args"][1:3] == ["--context", "gemini"]


def test_antigravity_mcp_sync_uses_its_provider_identity_and_prunes_stale_backends(tmp_path: Path, monkeypatch):
    path = tmp_path / "mcp_config.json"
    serena = tmp_path / "serena.exe"
    install_dir = tmp_path / "install"
    install_dir.mkdir()
    setup.write_install_manifest(install_dir)
    monkeypatch.setattr(setup, "_ACTIVE_INSTALL_ROOT", install_dir)
    path.write_text(json.dumps({"mcpServers": {
        "user-server": {"command": "keep"},
    }}), encoding="utf-8")
    setup.record_external_json_key(
        install_dir,
        path,
        container="mcpServers",
        key="serena",
        preimage=None,
        postimage={"command": str(serena), "args": ["start-mcp-server"]},
    )

    setup.sync_antigravity_mcp_config(
        path, install_dir, tmp_path / "python", serena,
        {"code_intelligence": {"direct_agent_mcp": True, "serena_enabled": True}}, False,
    )
    setup.sync_antigravity_mcp_config(
        path, install_dir, tmp_path / "python", serena,
        {"code_intelligence": {"direct_agent_mcp": False}}, False,
    )

    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data["mcpServers"]) == {"user-server", "local-ai"}
    local_ai = data["mcpServers"]["local-ai"]
    assert local_ai["cwd"] == str(tmp_path / "install")
    assert local_ai["env"]["LOCAL_AI_AGENT"] == "antigravity"
    assert local_ai["env"]["LOCAL_AI_AGENT_PROFILE"] == "antigravity"


def test_mcp_merge_preserves_existing_isolated_hub_launch(tmp_path: Path):
    import json
    import tomllib

    entry = {"command": "new-python", "args": ["-m", "local_ai_hub.mcp_server"], "cwd": "new-root"}
    isolated = ["-I", "-m", "local_ai_hub.mcp_server"]
    codex = tmp_path / "config.toml"
    codex.write_text(
        setup.MARKER_BEGIN + '\n[mcp_servers.local-ai]\ncommand = "old-python"\n'
        'args = ["-I", "-m", "local_ai_hub.mcp_server"]\n' + setup.MARKER_END + '\n',
        encoding="utf-8",
    )
    gemini = tmp_path / "settings.json"
    gemini.write_text(json.dumps({"mcpServers": {"local-ai": {"args": isolated}, "other": {"command": "keep"}}}), encoding="utf-8")
    for _ in range(2):
        setup.codex_mcp_merge(codex, {"local-ai": entry}, False)
        setup.json_mcp_merge(gemini, {"local-ai": entry}, False)
    codex_server = tomllib.loads(codex.read_text(encoding="utf-8"))["mcp_servers"]["local-ai"]
    gemini_servers = json.loads(gemini.read_text(encoding="utf-8"))["mcpServers"]
    for server in (codex_server, gemini_servers["local-ai"]):
        assert server["args"] == isolated
        assert server["command"] == "new-python"
        assert server["cwd"] == "new-root"
    assert gemini_servers["other"] == {"command": "keep"}
    assert setup.preserve_isolated_hub_args("local-ai", {"args": isolated + ["stale"]}, entry) == entry


def test_codex_mcp_merge_writes_stable_working_directory(tmp_path: Path):
    path = tmp_path / "config.toml"
    setup.codex_mcp_merge(
        path,
        {"local-ai": {"command": "python", "args": ["-m", "hub"], "cwd": str(tmp_path / "hub")}},
        False,
    )
    text = path.read_text(encoding="utf-8")
    assert f"cwd = {setup.toml_quote(str(tmp_path / 'hub'))}" in text


def test_codex_hub_plugin_refreshes_cache_from_its_selected_local_marketplace(tmp_path, monkeypatch):
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    config = codex_home / "config.toml"
    config.write_text('[plugins."local-ai-hub@local-ai-hub"]\nenabled = true\n', encoding="utf-8")
    manifest = tmp_path / "plugins" / "codex" / "local-ai-hub" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"name":"local-ai-hub","version":"8.1.0"}', encoding="utf-8")
    calls = []
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[1:4] == ["plugin", "marketplace", "list"]:
            return subprocess.CompletedProcess(command, 0, json.dumps({"marketplaces": [
                {"name": "local-ai-hub", "root": str(tmp_path)},
            ]}), "")
        if command[1:3] == ["plugin", "list"]:
            raise AssertionError("refresh must not enumerate every installed Codex plugin")
        if command[1:3] == ["plugin", "add"]:
            return subprocess.CompletedProcess(command, 0, json.dumps({"version": "8.1.0"}), "")
        raise AssertionError(command)

    monkeypatch.setattr(setup.shutil, "which", lambda name: "codex.exe" if name == "codex" else None)
    monkeypatch.setattr(setup, "run", fake_run)

    success, detail = setup.refresh_codex_hub_plugin_cache(config, tmp_path)

    assert success is True
    assert "8.1.0" in detail
    assert calls[1][1:] == ["plugin", "add", "local-ai-hub@local-ai-hub", "--json"]


def test_codex_hub_plugin_refresh_does_not_replace_foreign_marketplace_source(tmp_path, monkeypatch):
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    config = codex_home / "config.toml"
    config.write_text('[plugins."local-ai-hub@local-ai-hub"]\nenabled = true\n', encoding="utf-8")
    manifest = tmp_path / "plugins" / "codex" / "local-ai-hub" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"name":"local-ai-hub","version":"8.1.0"}', encoding="utf-8")
    calls = []
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setattr(setup.shutil, "which", lambda name: "codex.exe" if name == "codex" else None)
    monkeypatch.setattr(setup, "run", lambda command, **kwargs: (
        calls.append(command) or subprocess.CompletedProcess(
            command, 0, json.dumps({"marketplaces": [
                {"name": "local-ai-hub", "root": str(tmp_path / "other-source")},
            ]}), "",
        )
    ))

    success, detail = setup.refresh_codex_hub_plugin_cache(config, tmp_path)

    assert success is False
    assert "marketplace" in detail.lower()
    assert len(calls) == 1


def test_codex_hub_plugin_refresh_skips_non_active_codex_home(tmp_path, monkeypatch):
    codex_home = tmp_path / "other-codex-home"
    codex_home.mkdir()
    config = codex_home / "config.toml"
    config.write_text('[plugins."local-ai-hub@local-ai-hub"]\nenabled = true\n', encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "active-codex-home"))
    monkeypatch.setattr(setup.shutil, "which", lambda _name: (_ for _ in ()).throw(AssertionError("CLI must not run")))

    success, detail = setup.refresh_codex_hub_plugin_cache(config, tmp_path)

    assert success is False
    assert "different CODEX_HOME" in detail


def test_codex_hub_plugin_refresh_does_not_reinstall_an_already_current_version(tmp_path, monkeypatch):
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    config = codex_home / "config.toml"
    config.write_text('[plugins."local-ai-hub@local-ai-hub"]\nenabled = true\n', encoding="utf-8")
    manifest = tmp_path / "plugins" / "codex" / "local-ai-hub" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"name":"local-ai-hub","version":"8.1.0"}', encoding="utf-8")
    cached_manifest = codex_home / "plugins" / "cache" / "local-ai-hub" / "local-ai-hub" / "8.1.0" / "plugin.json"
    cached_manifest.parent.mkdir(parents=True)
    cached_manifest.write_text('{"name":"local-ai-hub","version":"8.1.0"}', encoding="utf-8")
    calls = []
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setattr(setup.shutil, "which", lambda name: "codex.exe" if name == "codex" else None)

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[1:4] == ["plugin", "marketplace", "list"]:
            return subprocess.CompletedProcess(command, 0, json.dumps({"marketplaces": [
                {"name": "local-ai-hub", "root": str(tmp_path)},
            ]}), "")
        raise AssertionError(f"unexpected Codex CLI command: {command}")

    monkeypatch.setattr(setup, "run", fake_run)

    success, detail = setup.refresh_codex_hub_plugin_cache(config, tmp_path)

    assert success is True
    assert "already current" in detail.lower()
    assert len(calls) == 1


def test_codex_hub_plugin_refresh_does_not_downgrade_newer_cache(tmp_path, monkeypatch):
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    config = codex_home / "config.toml"
    config.write_text('[plugins."local-ai-hub@local-ai-hub"]\nenabled = true\n', encoding="utf-8")
    manifest = tmp_path / "plugins" / "codex" / "local-ai-hub" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"name":"local-ai-hub","version":"8.2.0"}', encoding="utf-8")
    cached_manifest = codex_home / "plugins" / "cache" / "local-ai-hub" / "local-ai-hub" / "8.2.1" / "plugin.json"
    cached_manifest.parent.mkdir(parents=True)
    cached_manifest.write_text('{"name":"local-ai-hub","version":"8.2.1"}', encoding="utf-8")
    calls = []
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setattr(setup.shutil, "which", lambda name: "codex.exe" if name == "codex" else None)

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[1:4] == ["plugin", "marketplace", "list"]:
            return subprocess.CompletedProcess(command, 0, json.dumps({"marketplaces": [
                {"name": "local-ai-hub", "root": str(tmp_path)},
            ]}), "")
        raise AssertionError(f"newer cache must not be replaced: {command}")

    monkeypatch.setattr(setup, "run", fake_run)

    success, detail = setup.refresh_codex_hub_plugin_cache(config, tmp_path)

    assert success is True
    assert "newer" in detail.lower()
    assert len(calls) == 1


def test_claude_hub_plugin_refresh_updates_only_the_enabled_local_marketplace(tmp_path, monkeypatch):
    claude_home = tmp_path / ".claude"
    settings = claude_home / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"enabledPlugins": {"local-ai-hub@local-ai-hub": True}}), encoding="utf-8")
    source_marketplace = tmp_path / "hub" / "plugins" / "claude"
    source_manifest = source_marketplace / "local-ai-hub" / ".claude-plugin" / "plugin.json"
    source_manifest.parent.mkdir(parents=True)
    source_manifest.write_text('{"name":"local-ai-hub","version":"8.2.0"}', encoding="utf-8")
    known = claude_home / "plugins" / "known_marketplaces.json"
    known.parent.mkdir(parents=True)
    known.write_text(json.dumps({"local-ai-hub": {"source": {
        "source": "directory", "path": str(source_marketplace),
    }}}), encoding="utf-8")
    old_install = claude_home / "plugins" / "cache" / "local-ai-hub" / "local-ai-hub" / "8.1.0"
    old_manifest = old_install / ".claude-plugin" / "plugin.json"
    old_manifest.parent.mkdir(parents=True)
    old_manifest.write_text('{"name":"local-ai-hub","version":"8.1.0"}', encoding="utf-8")
    installed_path = claude_home / "plugins" / "installed_plugins.json"
    installed_path.write_text(json.dumps({"plugins": {"local-ai-hub@local-ai-hub": [{
        "scope": "user", "installPath": str(old_install), "version": "8.1.0",
    }]}}), encoding="utf-8")
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        new_install = claude_home / "plugins" / "cache" / "local-ai-hub" / "local-ai-hub" / "8.2.0"
        new_manifest = new_install / ".claude-plugin" / "plugin.json"
        new_manifest.parent.mkdir(parents=True)
        new_manifest.write_text(source_manifest.read_text(encoding="utf-8"), encoding="utf-8")
        installed_path.write_text(json.dumps({"plugins": {"local-ai-hub@local-ai-hub": [{
            "scope": "user", "installPath": str(new_install), "version": "8.2.0",
        }]}}), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "updated", "")

    monkeypatch.setattr(setup.shutil, "which", lambda name: "claude.exe" if name == "claude" else None)
    monkeypatch.setattr(setup, "run", fake_run)

    success, detail = setup.refresh_claude_hub_plugin_cache(settings, tmp_path / "hub")

    assert success is True
    assert "8.2.0" in detail
    assert calls == [["claude.exe", "plugin", "update", "local-ai-hub@local-ai-hub", "--scope", "user"]]


def test_claude_hub_plugin_refresh_preserves_newer_cache(tmp_path, monkeypatch):
    claude_home = tmp_path / ".claude"
    settings = claude_home / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"enabledPlugins": {"local-ai-hub@local-ai-hub": True}}), encoding="utf-8")
    marketplace = tmp_path / "hub" / "plugins" / "claude"
    source_manifest = marketplace / "local-ai-hub" / ".claude-plugin" / "plugin.json"
    source_manifest.parent.mkdir(parents=True)
    source_manifest.write_text('{"name":"local-ai-hub","version":"8.2.0"}', encoding="utf-8")
    known = claude_home / "plugins" / "known_marketplaces.json"
    known.parent.mkdir(parents=True)
    known.write_text(json.dumps({"local-ai-hub": {"source": {"source": "directory", "path": str(marketplace)}}}), encoding="utf-8")
    new_install = claude_home / "plugins" / "cache" / "local-ai-hub" / "local-ai-hub" / "8.2.1"
    cached_manifest = new_install / ".claude-plugin" / "plugin.json"
    cached_manifest.parent.mkdir(parents=True)
    cached_manifest.write_text('{"name":"local-ai-hub","version":"8.2.1"}', encoding="utf-8")
    installed = claude_home / "plugins" / "installed_plugins.json"
    installed.write_text(json.dumps({"plugins": {"local-ai-hub@local-ai-hub": [{
        "scope": "user", "installPath": str(new_install), "version": "8.2.1",
    }]}}), encoding="utf-8")
    monkeypatch.setattr(setup.shutil, "which", lambda _name: (_ for _ in ()).throw(AssertionError("newer cache must not update")))

    success, detail = setup.refresh_claude_hub_plugin_cache(settings, tmp_path / "hub")

    assert success is True
    assert "newer" in detail.lower()
    assert "8.2.1" in detail


def test_cursor_bundle_sync_preserves_newer_installed_plugin(tmp_path, monkeypatch):
    source_root = tmp_path / "source"
    target_root = tmp_path / "home" / ".cursor"
    source = source_root / "plugins" / "cursor" / "local-ai-hub"
    source_manifest = source / ".cursor-plugin" / "plugin.json"
    source_manifest.parent.mkdir(parents=True)
    source_manifest.write_text('{"name":"local-ai-hub","version":"8.2.0"}', encoding="utf-8")
    (source / "README.md").write_text("source bundle", encoding="utf-8")
    target = target_root / "plugins" / "local" / "local-ai-hub"
    target_manifest = target / ".cursor-plugin" / "plugin.json"
    target_manifest.parent.mkdir(parents=True)
    target_manifest.write_text('{"name":"local-ai-hub","version":"8.2.1"}', encoding="utf-8")
    (target / "README.md").write_text("installed newer bundle", encoding="utf-8")
    monkeypatch.setattr(setup, "SOURCE_ROOT", source_root)

    assert setup.sync_cursor_plugin_bundle(target_root, backup_enabled=False) is True
    assert json.loads(target_manifest.read_text(encoding="utf-8"))["version"] == "8.2.1"
    assert (target / "README.md").read_text(encoding="utf-8") == "installed newer bundle"


def test_antigravity_bundle_sync_preserves_newer_installed_plugin(tmp_path, monkeypatch):
    source_root = tmp_path / "source"
    target_root = tmp_path / "home" / ".gemini"
    source = source_root / "plugins" / "antigravity" / "local-ai-hub"
    source_manifest = source / "plugin.json"
    source.mkdir(parents=True)
    source_manifest.write_text('{"name":"local-ai-hub","version":"8.2.0"}', encoding="utf-8")
    (source / "README.md").write_text("source bundle", encoding="utf-8")
    target = target_root / "config" / "plugins" / "local-ai-hub"
    target.mkdir(parents=True)
    target_manifest = target / "plugin.json"
    target_manifest.write_text('{"name":"local-ai-hub","version":"8.2.1"}', encoding="utf-8")
    (target / "README.md").write_text("installed newer bundle", encoding="utf-8")
    monkeypatch.setattr(setup, "SOURCE_ROOT", source_root)

    assert setup.sync_antigravity_plugin_bundle(target_root, backup_enabled=False) is True
    assert json.loads(target_manifest.read_text(encoding="utf-8"))["version"] == "8.2.1"
    assert (target / "README.md").read_text(encoding="utf-8") == "installed newer bundle"


def test_codex_unowned_files_do_not_block_other_profile_setup(tmp_path: Path, monkeypatch):
    root_home = tmp_path / "root"
    profile_home = tmp_path / "profile"
    install_dir = tmp_path / "install"
    install_dir.mkdir()
    mcp_paths = []
    policy_paths = []

    monkeypatch.setattr(setup, "get_user_homes", lambda: [root_home, profile_home])
    monkeypatch.setattr(setup, "write_all_generated", lambda *args, **kwargs: None)
    monkeypatch.setattr(setup, "write_generated_agent_manifests", lambda *args, **kwargs: None)
    monkeypatch.setattr(setup, "install_agent_skills", lambda *args, **kwargs: None)
    monkeypatch.setattr(setup, "build_codex_mcp_entries", lambda *args, **kwargs: {"local-ai": {"command": "python"}})
    monkeypatch.setattr(setup, "build_mcp_entries", lambda *args, **kwargs: {})

    def merge_global_policy(path, *_args, **_kwargs):
        if path == root_home / ".codex" / "AGENTS.md":
            raise ValueError("external block has no ownership record")
        policy_paths.append(path)

    monkeypatch.setattr(setup, "merge_global_policy", merge_global_policy)
    monkeypatch.setattr(setup, "merge_token_economy_policy", lambda *args, **kwargs: None)
    monkeypatch.setattr(setup, "merge_autosetup_policy", lambda *args, **kwargs: None)
    def merge_codex_mcp(path, *_args, **_kwargs):
        if path == root_home / ".codex" / "config.toml":
            raise ValueError("external block has no ownership record")
        mcp_paths.append(path)

    monkeypatch.setattr(setup, "codex_mcp_merge", merge_codex_mcp)

    manual_actions = setup._configure_agents_impl(
        install_dir,
        Path("python"),
        None,
        {
            "agents": {
                "codex": True,
                "claude": False,
                "gemini": False,
                "cursor": False,
                "windsurf": False,
                "copilot": False,
                "agent_skills_standard": False,
            },
            "tool_policy": {"install_global_instructions": True},
            "setup": {"backup_existing_configs": False},
        },
    )

    assert "external block has no ownership record" in " ".join(manual_actions)
    assert mcp_paths == [profile_home / ".codex" / "config.toml"]
    assert profile_home / ".codex" / "AGENTS.md" in policy_paths


def test_config_mergers_preserve_user_content(tmp_path: Path):
    json_path = tmp_path / "settings.json"
    json_path.write_text(json.dumps({"other": 1, "mcpServers": {"user": {"command": "keep"}}}), encoding="utf-8")
    setup.json_mcp_merge(json_path, {"local-ai": {"command": "python", "args": ["hub.py"]}}, False)
    json_first = json_path.read_text(encoding="utf-8")
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["other"] == 1
    assert data["mcpServers"]["user"]["command"] == "keep"
    assert data["mcpServers"]["local-ai"]["command"] == "python"
    setup.json_mcp_merge(json_path, {"local-ai": {"command": "python", "args": ["hub.py"]}}, False)
    assert json_path.read_text(encoding="utf-8") == json_first

    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        '[model]\nprovider="x"\n\n[mcp_servers.foreign]\ncommand="keep"\n\n'
        '[mcp_servers.local-ai]\ncommand="user-managed"\n',
        encoding="utf-8",
    )
    setup.codex_mcp_merge(toml_path, {"local-ai": {"command": "should-not-overwrite", "args": []}}, False)
    toml_first = toml_path.read_text(encoding="utf-8")
    data = tomllib.loads(toml_first)
    assert data["model"]["provider"] == "x"
    assert data["mcp_servers"]["foreign"]["command"] == "keep"
    assert data["mcp_servers"]["local-ai"]["command"] == "user-managed"
    assert "should-not-overwrite" not in toml_first
    setup.codex_mcp_merge(toml_path, {"local-ai": {"command": "should-not-overwrite", "args": []}}, False)
    assert toml_path.read_text(encoding="utf-8") == toml_first


@pytest.mark.parametrize(
    ("host", "manifest_format", "entry_agent"),
    [
        ("codex", "toml", "codex"),
        ("claude", "json", "claude"),
        ("gemini", "json", "gemini"),
        ("antigravity", "antigravity", "antigravity"),
        ("cursor", "json", "cursor"),
        ("windsurf", "json", "windsurf"),
        ("devin", "json", "devin"),
        ("copilot", "json", "copilot"),
        ("vscode", "vscode", "generic"),
        ("generic", "json", "generic"),
        ("vscode", "vscode", "generic"),
    ],
)
def test_supported_host_mcp_manifests_parse(tmp_path: Path, host: str, manifest_format: str, entry_agent: str):
    path = tmp_path / f"{host}.{'toml' if manifest_format == 'toml' else 'json'}"
    install_dir = tmp_path / "install"
    hub_python = tmp_path / "python"
    cfg = {"code_intelligence": {"direct_agent_mcp": False}}
    entries = setup.build_mcp_entries(install_dir, hub_python, None, entry_agent, cfg)

    if manifest_format == "toml":
        setup.codex_mcp_merge(path, entries, False)
        manifest = tomllib.loads(path.read_text(encoding="utf-8"))["mcp_servers"]
    elif manifest_format == "antigravity":
        setup.sync_antigravity_mcp_config(path, install_dir, hub_python, None, cfg, False)
        manifest = json.loads(path.read_text(encoding="utf-8"))["mcpServers"]
    elif manifest_format == "vscode":
        setup.vscode_mcp_merge(path, entries, False)
        manifest = json.loads(path.read_text(encoding="utf-8"))["servers"]
    else:
        setup.json_mcp_merge(path, entries, False)
        manifest = json.loads(path.read_text(encoding="utf-8"))["mcpServers"]

    assert manifest["local-ai"]["env"]["LOCAL_AI_AGENT"] == entry_agent
    if manifest_format == "vscode":
        assert manifest["local-ai"]["type"] == "stdio"
    assert manifest["local-ai"]["command"] == str(hub_python)


def test_ollama_setup_skips_exclusive_llama_cpp_configuration(monkeypatch, tmp_path: Path, capsys):
    cfg = {
        "ollama": {"enabled": False},
        "server": {"auto_start_ollama": True},
        "llama_cpp": {"mode": "on", "fallback_to_ollama": False},
    }
    monkeypatch.setattr(setup, "find_ollama_executable", lambda: pytest.fail("Ollama lookup must be skipped"))

    assert setup.ollama_setup_required(cfg) is False
    assert setup.ensure_ollama_for_setup(cfg, tmp_path, allow_install=True) is True
    setup.pull_ollama_models(cfg)
    assert "Skipping Ollama setup" in capsys.readouterr().out


@pytest.mark.parametrize(
    "cfg",
    [
        {"server": {"auto_start_ollama": False}, "llama_cpp": {"fallback_to_ollama": True}},
        {"server": {"auto_start_ollama": True}, "llama_cpp": {"fallback_to_ollama": False}},
    ],
)
def test_ollama_setup_requires_auto_start_and_fallback(cfg):
    assert setup.ollama_setup_required(cfg) is False


def test_ollama_setup_remains_enabled_for_fallback_configuration():
    assert setup.ollama_setup_required(
        {"ollama": {"enabled": True}, "server": {"auto_start_ollama": True}, "llama_cpp": {"mode": "auto", "fallback_to_ollama": True}}
    ) is True


def test_managed_llama_setup_runs_only_when_selected(monkeypatch, capsys):
    class ManagedRuntime:
        def __init__(self, config):
            self.config = config

        def ensure_running(self):
            return True

        def status(self):
            return {"url": "http://127.0.0.1:12438", "mode": "none"}

    monkeypatch.setattr(setup, "LlamaCppManagedRuntime", ManagedRuntime)
    assert setup.ensure_llama_cpp_for_setup({"ollama": {"enabled": False}, "llama_cpp": {"mode": "on"}})
    assert "Managed llama.cpp is ready" in capsys.readouterr().out
    assert setup.ensure_llama_cpp_for_setup({"ollama": {"enabled": True}, "llama_cpp": {"mode": "on"}})
    assert "Skipping managed llama.cpp setup" in capsys.readouterr().out


def test_managed_llama_setup_fails_closed_when_server_never_becomes_healthy(monkeypatch):
    class ManagedRuntime:
        def __init__(self, config):
            pass

        def ensure_running(self):
            return False

        def status(self):
            return {"last_error": "llama-server did not become healthy"}

    monkeypatch.setattr(setup, "LlamaCppManagedRuntime", ManagedRuntime)
    with pytest.raises(RuntimeError, match="did not become healthy"):
        setup.ensure_llama_cpp_for_setup({"ollama": {"enabled": False}, "llama_cpp": {"mode": "on"}})


def test_pull_ollama_models_includes_vision_when_enabled(monkeypatch):
    pulled = []
    monkeypatch.setattr(setup, "find_ollama_executable", lambda: "ollama")
    monkeypatch.setattr(setup, "run", lambda args, **kwargs: pulled.append(args))

    setup.pull_ollama_models(
        {
            "ollama": {"enabled": True},
            "features": {"pull_models_during_setup": True, "vision": True},
            "server": {"auto_start_ollama": True},
            "llama_cpp": {"fallback_to_ollama": True},
            "models": {"general": "qwen2.5-coder:7b", "vision": "qwen3-vl:4b"},
            "ollama_subagents": {"enabled": False},
        }
    )

    assert [args[-1] for args in pulled] == ["qwen2.5-coder:7b", "qwen3-vl:4b"]


def test_pull_ollama_models_skips_vision_when_disabled(monkeypatch):
    pulled = []
    monkeypatch.setattr(setup, "find_ollama_executable", lambda: "ollama")
    monkeypatch.setattr(setup, "run", lambda args, **kwargs: pulled.append(args))

    setup.pull_ollama_models(
        {
            "ollama": {"enabled": True},
            "features": {"pull_models_during_setup": True, "vision": False},
            "server": {"auto_start_ollama": True},
            "llama_cpp": {"fallback_to_ollama": True},
            "models": {"general": "qwen2.5-coder:7b", "vision": "qwen3-vl:4b"},
            "ollama_subagents": {"enabled": False},
        }
    )

    assert [args[-1] for args in pulled] == ["qwen2.5-coder:7b"]


def test_setup_rerun_preserves_installed_config_without_explicit_override(tmp_path: Path, monkeypatch):
    source = tmp_path / "source"
    install = tmp_path / "installed"
    source.mkdir(); install.mkdir()
    (source / "config.toml").write_text(f'[setup]\ninstall_dir="{install.as_posix()}"\n[hardware]\nprofile="cpu"\n', encoding="utf-8")
    installed = install / "config.toml"
    installed.write_text(f'[setup]\ninstall_dir="{install.as_posix()}"\n[hardware]\nprofile="high"\n', encoding="utf-8")
    monkeypatch.setattr(setup, "SOURCE_ROOT", source)
    selected, cfg, selected_install = setup.select_config_source(None)
    assert selected == installed.resolve()
    assert selected_install == install.resolve()
    assert cfg["hardware"]["profile"] == "high"


def test_setup_explicit_config_wins_over_installed_config(tmp_path: Path, monkeypatch):
    source = tmp_path / "source"
    install = tmp_path / "installed"
    source.mkdir(); install.mkdir()
    explicit = source / "custom.toml"
    explicit.write_text(f'[setup]\ninstall_dir="{install.as_posix()}"\n[hardware]\nprofile="low"\n', encoding="utf-8")
    (install / "config.toml").write_text(f'[setup]\ninstall_dir="{install.as_posix()}"\n[hardware]\nprofile="high"\n', encoding="utf-8")
    monkeypatch.setattr(setup, "SOURCE_ROOT", source)
    selected, cfg, selected_install = setup.select_config_source(explicit)
    assert selected == explicit.resolve()
    assert selected_install == install.resolve()
    assert cfg["hardware"]["profile"] == "low"


def test_setup_clean_checkout_bootstraps_from_example_config(tmp_path: Path, monkeypatch):
    source = tmp_path / "source"
    install = tmp_path / "installed"
    source.mkdir()
    example = source / "config.toml.example"
    example.write_text(
        f'[local_ai_hub]\nconfig_schema_version = 1\n'
        f'[setup]\ninstall_dir="{install.as_posix()}"\n[hardware]\nprofile="cpu"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(setup, "SOURCE_ROOT", source)

    selected, cfg, selected_install = setup.select_config_source(None)

    assert selected == example.resolve()
    assert selected_install == install.resolve()
    assert cfg["hardware"]["profile"] == "cpu"


def test_v8_setup_migration_clears_active_vectors_without_backup(tmp_path: Path, monkeypatch):
    from tools.embedding_reset import verify_embedding_reset
    source = tmp_path / "source"
    state = tmp_path / "state"
    source.mkdir()
    state.mkdir()
    (source / "pyproject.toml").write_text('[project]\nversion = "8.0.0"\n', encoding="utf-8")
    schema = (
        "CREATE TABLE chunks(embedding TEXT NOT NULL,embedding_space TEXT NOT NULL);"
        "CREATE TABLE rag_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);"
    )
    with closing(sqlite3.connect(state / "rag.sqlite3")) as con:
        con.executescript(schema)
        con.execute("INSERT INTO chunks VALUES('[0.1,0.2]','old-space')")
        con.commit()
    monkeypatch.setattr(setup, "SOURCE_ROOT", source)
    monkeypatch.setattr(setup, "discard_stale_migration_artifacts", lambda _state: [])
    monkeypatch.setattr(setup, "run_state_migrations", lambda _state, **kwargs: {
        "status": "current", "version": 9, "backups": [],
    })

    result = setup.migrate_release_state(state, create_backup=False)

    assert result["embedding_reset"] == "migrated"
    assert result["embedding_reset_backup"] is None
    assert setup.run_state_migrations(state)["status"] == "current"
    assert verify_embedding_reset(state)


def test_v8_setup_migration_clears_active_vectors_with_backup(tmp_path: Path, monkeypatch):
    from tools.embedding_reset import verify_embedding_reset
    source = tmp_path / "source"
    state = tmp_path / "state"
    source.mkdir()
    state.mkdir()
    (source / "pyproject.toml").write_text('[project]\nversion = "8.0.0"\n', encoding="utf-8")
    schema = (
        "CREATE TABLE chunks(embedding TEXT NOT NULL,embedding_space TEXT NOT NULL);"
        "CREATE TABLE rag_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);"
    )
    with closing(sqlite3.connect(state / "rag.sqlite3")) as con:
        con.executescript(schema)
        con.execute("INSERT INTO chunks VALUES('[0.1,0.2]','old-space')")
        con.commit()
    monkeypatch.setattr(setup, "SOURCE_ROOT", source)
    monkeypatch.setattr(setup, "discard_stale_migration_artifacts", lambda _state: [])
    monkeypatch.setattr(setup, "run_state_migrations", lambda _state, **kwargs: {
        "status": "current", "version": 9, "backups": [],
    })

    result = setup.migrate_release_state(state)

    assert result["embedding_reset"] == "migrated"
    assert result["embedding_reset_backup"] is not None
    assert Path(result["embedding_reset_backup"]).is_dir()
    assert setup.run_state_migrations(state)["status"] == "current"
    assert verify_embedding_reset(state)



def test_skip_service_does_not_restart_global_hub_without_managed_service(tmp_path: Path, monkeypatch):
    source = tmp_path / "source"
    install = tmp_path / "installed"
    source.mkdir()
    install.mkdir()
    config_text = (
        f'[setup]\ninstall_dir="{install.as_posix()}"\n'
        "install_agent_configs=false\ninstall_optional_tools=false\n"
        "[server]\nauto_start_ollama=false\n"
        "[features]\ninstall_local_nlp_dependencies=false\n"
        "install_openvino_dependencies=false\npull_models_during_setup=false\n"
    )
    source_config = source / "config.toml"
    source_config.write_text(config_text, encoding="utf-8")
    (install / "config.toml").write_text(config_text, encoding="utf-8")
    monkeypatch.setattr(setup, "SOURCE_ROOT", source)
    monkeypatch.setattr(setup, "copy_install_tree", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(setup, "ensure_venv", lambda _venv: tmp_path / "python.exe")
    monkeypatch.setattr(setup, "install_requirements", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(setup, "ensure_ollama_for_setup", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup, "pull_ollama_models", lambda *_args, **_kwargs: {"unavailable": []})
    monkeypatch.setattr(setup, "ensure_llama_cpp_for_setup", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup, "write_generated_agent_manifests", lambda *_args, **_kwargs: None)
    commands = []
    monkeypatch.setattr(setup, "run", lambda command, **_kwargs: commands.append(command))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "setup.py", "--profile", "cpu", "--skip-service", "--skip-model-pull",
            "--skip-tools", "--skip-agent-config", "--skip-ollama-install",
            "--skip-local-nlp-preload", "--skip-token-economy", "--skip-companion-skills",
        ],
    )

    assert setup.main() == 0
    assert sum(
        len(command) >= 2 and Path(command[-2]).name == "hubctl.py" and command[-1] == "restart"
        for command in commands
    ) == 0
    assert not any(
        len(command) >= 2 and Path(command[-2]).name == "service.py" and command[-1] == "install"
        for command in commands
    )


@pytest.mark.parametrize("service_ok", [True, False])
@pytest.mark.parametrize("restart_ok", [True, False])
def test_setup_starts_hub_before_configuring_http_mcp(tmp_path: Path, monkeypatch, service_ok: bool, restart_ok: bool):
    source = tmp_path / "source"
    install = tmp_path / "installed"
    source.mkdir()
    install.mkdir()
    config_text = (
        f'[setup]\ninstall_dir="{install.as_posix()}"\n'
        "install_agent_configs=true\ninstall_service=true\ninstall_optional_tools=false\n"
        "[agents]\ncodex=true\n"
        "[headless]\nenabled=true\n"
        "[server]\nauto_start_ollama=false\n"
        "[features]\ninstall_local_nlp_dependencies=false\n"
        "install_openvino_dependencies=false\npull_models_during_setup=false\n"
    )
    (source / "config.toml").write_text(config_text, encoding="utf-8")
    (install / "config.toml").write_text(config_text, encoding="utf-8")
    monkeypatch.setattr(setup, "SOURCE_ROOT", source)
    monkeypatch.setattr(setup, "copy_install_tree", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(setup, "ensure_venv", lambda _venv: tmp_path / "python.exe")
    monkeypatch.setattr(setup, "install_requirements", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(setup, "ensure_ollama_for_setup", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup, "pull_ollama_models", lambda *_args, **_kwargs: {"unavailable": []})
    monkeypatch.setattr(setup, "ensure_llama_cpp_for_setup", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup, "write_generated_agent_manifests", lambda *_args, **_kwargs: None)
    events = []

    def install_service(*_args, **_kwargs):
        events.append("service-ready")
        return service_ok

    def configure_agents(*_args, **_kwargs):
        assert events == ["service-ready", "hub-restarted"]
        events.append("agents-configured")
        return []

    def run(command, **_kwargs):
        if command[-1:] == ["restart"] and any(
            part.endswith("tools/hubctl.py") or part.endswith("tools\\hubctl.py") for part in command
        ):
            events.append("hub-restarted")
            if not restart_ok:
                raise RuntimeError("Hub restart failed")

    monkeypatch.setattr(setup, "install_persistent_service", install_service)
    monkeypatch.setattr(setup, "configure_agents", configure_agents)
    monkeypatch.setattr(setup, "run", run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "setup.py", "--skip-model-pull", "--skip-tools", "--skip-token-economy",
            "--skip-companion-skills", "--skip-local-nlp-preload", "--skip-ollama-install",
        ],
    )

    expected_status = 0 if service_ok and restart_ok else 1
    assert setup.main() == expected_status
    if not service_ok:
        assert events == ["service-ready"]
    elif not restart_ok:
        assert events == ["service-ready", "hub-restarted"]
    else:
        assert events == ["service-ready", "hub-restarted", "agents-configured"]


def test_copy_install_tree_copies_only_current_package_roots(tmp_path: Path, monkeypatch):
    source = tmp_path / "source"
    for name in ("src", "skills", "tools", "plugins"):
        (source / name).mkdir(parents=True)
        (source / name / "marker.txt").write_text(name, encoding="utf-8")
    for name in ("requirements-core.txt", "defaults.toml", "pyproject.toml", "README.md"):
        (source / name).write_text("x", encoding="utf-8")
    config = source / "config.toml"
    config.write_text("[hardware]\nprofile='cpu'\n", encoding="utf-8")
    monkeypatch.setattr(setup, "SOURCE_ROOT", source)
    monkeypatch.setattr(setup, "UPDATE_SOURCE_ROOT", source)
    target = tmp_path / "install"

    setup.copy_install_tree(target, config)

    assert (target / "src" / "marker.txt").read_text(encoding="utf-8") == "src"
    assert (target / "skills" / "marker.txt").read_text(encoding="utf-8") == "skills"
    assert (target / "tools" / "marker.txt").read_text(encoding="utf-8") == "tools"
    assert (target / "plugins" / "marker.txt").read_text(encoding="utf-8") == "plugins"
    assert not (target / "mcp").exists()


def test_install_agent_skills_includes_companion_by_default(tmp_path: Path):
    source = tmp_path / "source"
    skills = source / "skills"
    for s in ["local-ai-orchestrator", "token-economizer", "caveman", "tool-orchestration", "ollama-quality-routing"]:
        d = skills / s
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"name: {s}", encoding="utf-8")

    target = tmp_path / "target_skills"
    setup.install_agent_skills(source, target, include_companion=True)

    for s in ["local-ai-orchestrator", "token-economizer", "caveman", "tool-orchestration", "ollama-quality-routing"]:
        assert (target / s / "SKILL.md").exists()
        assert (target / s / "SKILL.md").read_text(encoding="utf-8") == f"name: {s}"


def test_install_agent_skills_skip_companion(tmp_path: Path):
    source = tmp_path / "source"
    skills = source / "skills"
    for s in ["local-ai-orchestrator", "token-economizer", "caveman", "tool-orchestration", "ollama-quality-routing"]:
        d = skills / s
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"name: {s}", encoding="utf-8")

    target = tmp_path / "target_skills"
    setup.install_agent_skills(source, target, include_companion=False)

    assert (target / "local-ai-orchestrator" / "SKILL.md").exists()
    for s in ["token-economizer", "caveman", "tool-orchestration", "ollama-quality-routing"]:
        assert not (target / s).exists()


def test_install_agent_skills_accepts_generated_install_target(tmp_path: Path):
    install = tmp_path / "install"
    target = tmp_path / "target_skills"
    setup.write_all_generated({"models": {"fast_code": "qwen2.5-coder:7b"}}, install)

    setup.install_agent_skills(install, target, include_companion=False)

    assert (target / "local-ai-orchestrator" / "SKILL.md").exists()
