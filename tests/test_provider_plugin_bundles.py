from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest
from local_ai_hub.client_adapters.registry import detect_client, get_adapter
ROOT = Path(__file__).resolve().parents[1]
PROVIDERS = ("codex", "antigravity", "claude", "copilot", "cursor", "gemini", "devin")


def test_provider_skill_snapshots_keep_active_laya_and_live_schema_authority():
    for provider in PROVIDERS:
        skill = (
            ROOT / "plugins" / provider / "local-ai-hub" / "skills"
            / "local-ai-orchestrator" / "SKILL.md"
        ).read_text(encoding="utf-8")
        assert "Laya actively advises eligible model-route, context-budget, and retrieval-strategy decisions" in skill
        assert "current `tools/list` schema is authoritative for tool availability" in skill
        assert "Laya does not fetch evidence or grant permissions" in skill


def test_orchestrator_skill_discovery_description_covers_supported_providers():
    paths = [ROOT / "skills" / "local-ai-orchestrator" / "SKILL.md"] + [
        ROOT / "plugins" / provider / "local-ai-hub" / "skills" / "local-ai-orchestrator" / "SKILL.md"
        for provider in PROVIDERS
    ]
    expected = (
        "Codex", "Antigravity", "Gemini CLI", "Claude", "Cursor", "Windsurf",
        "VS Code/Copilot", "Devin Local", "OpenCode", "MCP coding agent",
    )
    for path in paths:
        content = path.read_text(encoding="utf-8")
        match = re.search(r"(?m)^description: (.+)$", content)
        assert match is not None, path
        description = match.group(1)
        assert description.startswith("Use when "), path
        assert all(provider in description for provider in expected), path


def _assert_shared_skills(plugin: Path) -> None:
    for skill in ("local-ai-orchestrator", "plan-led-work", "token-economizer"):
        source_root = ROOT / "skills" / skill
        for source in source_root.rglob("*"):
            if source.is_file():
                packaged = plugin / "skills" / skill / source.relative_to(source_root)
                assert packaged.read_bytes() == source.read_bytes(), packaged


def test_orchestrator_skill_uses_live_mcp_schema_as_capability_authority():
    skill = (ROOT / "skills" / "local-ai-orchestrator" / "SKILL.md").read_text(encoding="utf-8")

    assert "The connected MCP server's current `tools/list` schema is authoritative" in skill
    assert "This bundled action list and `references/tools.md` are snapshots only" in skill


def test_orchestrator_skill_teaches_active_laya_context_source_flow():
    skill = (ROOT / "skills" / "local-ai-orchestrator" / "SKILL.md").read_text(encoding="utf-8")

    assert "Laya actively advises eligible model-route, context-budget, and retrieval-strategy decisions" in skill
    assert "evaluate_context_source" in skill
    assert "task-scoped `source_record_ids`" in skill
    assert "Laya does not fetch evidence or grant permissions" in skill


def test_portable_provider_launchers_stay_identical():
    providers = ("codex", "antigravity", "claude", "copilot", "cursor", "gemini", "devin")
    launcher_paths = [
        ROOT / "plugins" / provider / "local-ai-hub" / "scripts" / "run_hub.py"
        for provider in providers
    ]
    launchers = [path.read_bytes() for path in launcher_paths]

    assert all(launcher == launchers[0] for launcher in launchers[1:])
    assert all(b'provider = "generic_mcp"' in launcher for launcher in launchers)


def test_windows_portable_launcher_preserves_mcp_stdio(tmp_path: Path) -> None:
    install = tmp_path / "hub-install"
    package = install / "src" / "local_ai_hub"
    package.mkdir(parents=True)
    (install / "config.toml").write_text(
        "[local_ai_hub]\nconfig_schema_version = 1\n", encoding="utf-8",
    )
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "mcp_server.py").write_text(
        "import sys\n"
        "line = sys.stdin.readline()\n"
        "print('ACK:' + line.strip(), flush=True)\n",
        encoding="utf-8",
    )
    runner = ROOT / "plugins" / "antigravity" / "local-ai-hub" / "scripts" / "run_hub.py"
    env = os.environ.copy()
    env["LOCAL_AI_HUB_DIR"] = str(install)
    env.pop("LOCAL_AI_CONFIG", None)
    env.pop("PYTHONPATH", None)

    result = subprocess.run(
        [sys.executable, str(runner), "mcp_server"],
        cwd=runner.parent.parent,
        env=env,
        input="MCP-STDIO-PROBE\n",
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ACK:MCP-STDIO-PROBE"


@pytest.mark.parametrize("provider", ("codex", "antigravity", "claude", "copilot", "cursor", "gemini", "devin"))
def test_explicit_host_hook_identity_overrides_inherited_provider_env(tmp_path, monkeypatch, provider):
    script = ROOT / "plugins" / provider / "local-ai-hub" / "scripts" / "run_hub.py"
    spec = importlib.util.spec_from_file_location(f"run_hub_{provider}", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    install = tmp_path / "hub-install"
    installed = {}
    monkeypatch.setattr(module, "resolve_hub_install", lambda: install)
    monkeypatch.setenv("LOCAL_AI_AGENT", "antigravity")
    monkeypatch.setenv("LOCAL_AI_AGENT_PROFILE", "antigravity")
    monkeypatch.setattr(
        module.subprocess,
        "call",
        lambda _argv, *, env: (installed.update(env) or 0),
    )

    assert module.main(["host_hooks", "--host", provider]) == 0
    assert installed["LOCAL_AI_AGENT"] == provider
    assert installed["LOCAL_AI_AGENT_PROFILE"] == provider


def test_each_native_mcp_bundle_declares_its_own_provider_identity():
    mcp_paths = {
        "codex": "mcp.json",
        "antigravity": "mcp_config.json",
        "claude": ".mcp.json",
        "copilot": "mcp.json",
        "cursor": "mcp.json",
        "gemini": "gemini-extension.json",
        "devin": "mcp.json",
    }
    identities = {"codex": "codex", "antigravity": "antigravity", "claude": "claude",
                  "copilot": "copilot", "cursor": "cursor", "gemini": "gemini_cli", "devin": "devin"}
    adapter_ids = {"codex": "codex", "antigravity": "antigravity", "claude": "claude",
                   "copilot": "vscode", "cursor": "cursor", "gemini": "gemini_cli", "devin": "devin"}

    for provider, relative_path in mcp_paths.items():
        bundle = ROOT / "plugins" / provider / "local-ai-hub" / relative_path
        config = json.loads(bundle.read_text(encoding="utf-8-sig"))
        identity = config["mcpServers"]["local-ai"]["env"]["LOCAL_AI_AGENT"]
        assert identity == identities[provider]
        assert detect_client(identity) == adapter_ids[provider]
        assert get_adapter(agent_header=identity).client_id == adapter_ids[provider]


def test_codex_plugin_bundles_native_mcp_hooks_and_current_skills():
    plugin = ROOT / "plugins" / "codex" / "local-ai-hub"
    manifest = json.loads((plugin / "plugin.json").read_text(encoding="utf-8"))
    mcp = json.loads((plugin / "mcp.json").read_text(encoding="utf-8"))
    hooks = json.loads((plugin / "hooks" / "hooks.json").read_text(encoding="utf-8"))

    assert manifest["skills"] == "./skills/"
    assert manifest["extensions"]["com.openai"]["hooks"] == "./hooks/hooks.json"
    assert mcp["mcpServers"]["local-ai"]["type"] == "stdio"
    assert mcp["mcpServers"]["local-ai"]["env"]["LOCAL_AI_AGENT"] == "codex"
    assert (plugin / "scripts" / "run_hub.py").is_file()
    assert set(hooks["hooks"]) == {
        "SessionStart", "UserPromptSubmit", "SubagentStart", "PreToolUse",
        "PermissionRequest", "PostToolUse",
    }
    assert hooks["hooks"]["PermissionRequest"][0]["matcher"] == "Bash|apply_patch"
    for event in ("UserPromptSubmit", "SubagentStart"):
        handler = hooks["hooks"][event][0]["hooks"][0]
        assert handler["additionalContextLimit"] == 256
    _assert_shared_skills(plugin)


def test_claude_plugin_bundles_native_mcp_hooks_and_current_skills():
    plugin = ROOT / "plugins" / "claude" / "local-ai-hub"
    manifest = json.loads((plugin / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    mcp = json.loads((plugin / ".mcp.json").read_text(encoding="utf-8"))
    hooks = json.loads((plugin / "hooks" / "hooks.json").read_text(encoding="utf-8"))

    assert manifest["name"] == "local-ai-hub"
    assert mcp["mcpServers"]["local-ai"]["env"]["LOCAL_AI_AGENT"] == "claude"
    assert "UserPromptSubmit" in hooks["hooks"]
    assert "PreToolUse" in hooks["hooks"]
    assert hooks["hooks"]["PreToolUse"][0]["matcher"] == "Bash|PowerShell|Read"
    assert hooks["hooks"]["PermissionRequest"][0]["matcher"] == "Bash|PowerShell|Read"
    assert "SubagentStart" in hooks["hooks"]
    assert (plugin / "scripts" / "run_hub.py").is_file()
    _assert_shared_skills(plugin)


def test_claude_marketplace_exposes_local_plugin_bundle():
    marketplace_path = ROOT / "plugins" / "claude" / ".claude-plugin" / "marketplace.json"

    assert marketplace_path.is_file()
    marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))
    assert marketplace["name"] == "local-ai-hub"
    assert len(marketplace["plugins"]) == 1
    assert marketplace["plugins"][0]["name"] == "local-ai-hub"
    assert marketplace["plugins"][0]["source"] == "./local-ai-hub"
    assert (marketplace_path.parent.parent / "local-ai-hub" / ".claude-plugin" / "plugin.json").is_file()


def test_copilot_plugin_bundles_agent_plugins_mcp_and_current_skills():
    plugin = ROOT / "plugins" / "copilot" / "local-ai-hub"
    manifest = json.loads((plugin / "plugin.json").read_text(encoding="utf-8-sig"))
    mcp = json.loads((plugin / "mcp.json").read_text(encoding="utf-8-sig"))
    hooks = json.loads((plugin / "com.github.copilot" / "hooks" / "hooks.json").read_text(encoding="utf-8-sig"))

    assert manifest["$schema"] == "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
    assert mcp["$schema"] == "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
    assert mcp["mcpServers"]["local-ai"]["args"] == ["${PLUGIN_ROOT}/scripts/run_hub.py", "mcp_server"]
    assert mcp["mcpServers"]["local-ai"]["env"]["LOCAL_AI_AGENT"] == "copilot"
    assert (plugin / "scripts" / "run_hub.py").is_file()
    assert set(hooks["hooks"]) == {"sessionStart"}
    context_hook = hooks["hooks"]["sessionStart"][0]
    assert context_hook["type"] == "command"
    assert "additionalContext" in context_hook["bash"]
    assert "additionalContext" in context_hook["powershell"]
    assert "permissionDecision" not in context_hook["bash"]
    _assert_shared_skills(plugin)


def test_devin_plugin_bundles_agent_plugins_mcp_and_current_skills():
    plugin = ROOT / "plugins" / "devin" / "local-ai-hub"
    manifest = json.loads((plugin / "plugin.json").read_text(encoding="utf-8"))
    mcp = json.loads((plugin / "mcp.json").read_text(encoding="utf-8"))
    hooks = json.loads((plugin / "hooks.json").read_text(encoding="utf-8"))

    assert manifest["$schema"] == "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
    assert manifest["name"] == "local-ai-hub"
    assert manifest["platforms"] == ["local"]
    assert mcp["$schema"] == "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
    assert mcp["mcpServers"]["local-ai"]["args"] == ["${PLUGIN_ROOT}/scripts/run_hub.py", "mcp_server"]
    assert mcp["mcpServers"]["local-ai"]["env"]["LOCAL_AI_AGENT"] == "devin"
    assert (plugin / "scripts" / "run_hub.py").is_file()
    hook = hooks["SessionStart"][0]["hooks"][0]
    assert hook["type"] == "command"
    assert hook["timeout"] == 5
    assert "hookEventName': 'SessionStart'" in hook["command"]
    assert "local-ai MCP" in hook["command"]
    assert "PreToolUse" not in hooks
    _assert_shared_skills(plugin)


def test_cursor_plugin_bundles_mcp_skills_rules_and_permission_hooks():
    plugin = ROOT / "plugins" / "cursor" / "local-ai-hub"
    manifest = json.loads((plugin / ".cursor-plugin" / "plugin.json").read_text(encoding="utf-8-sig"))
    mcp = json.loads((plugin / "mcp.json").read_text(encoding="utf-8-sig"))
    hooks = json.loads((plugin / "hooks" / "hooks.json").read_text(encoding="utf-8-sig"))

    assert manifest["hooks"] == "./hooks/hooks.json"
    assert mcp["mcpServers"]["local-ai"]["args"] == ["${CURSOR_PLUGIN_ROOT}/scripts/run_hub.py", "mcp_server"]
    assert mcp["mcpServers"]["local-ai"]["env"]["LOCAL_AI_AGENT"] == "cursor"
    assert hooks["hooks"]["beforeShellExecution"][0]["failClosed"] is True
    assert "afterFileEdit" in hooks["hooks"]
    assert (plugin / "rules" / "local-ai-hub.mdc").is_file()
    assert (plugin / "scripts" / "run_hub.py").is_file()
    _assert_shared_skills(plugin)


def test_gemini_cli_extension_bundles_mcp_skills_context_and_native_hooks():
    plugin = ROOT / "plugins" / "gemini" / "local-ai-hub"
    manifest = json.loads((plugin / "gemini-extension.json").read_text(encoding="utf-8-sig"))
    hooks = json.loads((plugin / "hooks" / "hooks.json").read_text(encoding="utf-8-sig"))

    assert manifest["name"] == "local-ai-hub"
    assert manifest["mcpServers"]["local-ai"]["args"] == ["${extensionPath}/scripts/run_hub.py", "mcp_server"]
    assert manifest["mcpServers"]["local-ai"]["env"]["LOCAL_AI_AGENT"] == "gemini_cli"
    assert set(hooks["hooks"]) == {"SessionStart", "BeforeAgent", "BeforeTool", "AfterTool"}
    for event in hooks["hooks"].values():
        assert isinstance(event, list)
        assert all(isinstance(group, dict) and isinstance(group.get("hooks"), list) for group in event)
    assert "${extensionPath}" in hooks["hooks"]["BeforeTool"][0]["hooks"][0]["command"]
    assert (plugin / "GEMINI.md").is_file()
    _assert_shared_skills(plugin)


def test_gemini_extension_requires_host_confirmation_for_sensitive_hub_actions():
    import tomllib

    plugin = ROOT / "plugins" / "gemini" / "local-ai-hub"
    policy = tomllib.loads(
        (plugin / "policies" / "local-ai-hub.toml").read_text(encoding="utf-8")
    )

    rules = policy["rule"]
    assert len(rules) == 2
    assert all(rule["mcpName"] == "local-ai" for rule in rules)
    assert all(rule["toolName"] == "local_ai_coord" for rule in rules)
    assert all(rule["decision"] == "ask_user" for rule in rules)
    assert all(rule["priority"] == 900 for rule in rules)
    assert "gpu_reservation_release_authorized" in rules[0]["argsPattern"]
    assert "memory_delete" in rules[0]["argsPattern"]
    assert '"operator_waiver"' in rules[1]["argsPattern"]
    assert re.search(rules[0]["argsPattern"], json.dumps({"action": "memory_delete"}))
    assert re.search(
        rules[1]["argsPattern"],
        json.dumps({"action": "task_complete", "operator_waiver": {"consent": True}}),
    )
    assert not re.search(rules[1]["argsPattern"], json.dumps({"action": "task_complete"}))
