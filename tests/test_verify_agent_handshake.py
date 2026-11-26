from __future__ import annotations

import json
import sys
from pathlib import Path

from tools import verify_agent_handshake


def test_configuration_check_does_not_probe_hub_or_claim_handshake(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(sys, "argv", ["verify_agent_handshake.py"])

    def unexpected_probe(*args, **kwargs):
        raise AssertionError("Hub readiness must be opt-in")

    monkeypatch.setattr("urllib.request.urlopen", unexpected_probe)

    assert verify_agent_handshake.main() == 0
    output = capsys.readouterr().out
    assert "Configuration" in output
    assert "configuration is not a live handshake" in output.lower()
    assert "CONFIGURED" in output or "MISSING" in output
    assert "probe skipped" in output.lower()


def test_hub_readiness_probe_requires_explicit_flag(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(sys, "argv", ["verify_agent_handshake.py", "--probe-hub"])
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"ready": true}'

    def probe(request, timeout):
        calls.append((request.full_url, timeout))
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", probe)

    assert verify_agent_handshake.main() == 0
    output = capsys.readouterr().out
    assert calls == [("http://127.0.0.1:11435/ready", 3)]
    assert "Hub readiness" in output


def test_mcp_probe_performs_stdio_initialize_and_lists_tools(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["verify_agent_handshake.py", "--probe-mcp"])

    assert verify_agent_handshake.main() == 0
    output = capsys.readouterr().out
    assert "MCP stdio handshake" in output
    assert "local_ai_status" in output
    assert "local_ai_artifact" in output


def test_opencode_configuration_check_uses_jsonc_and_explicit_home(tmp_path, monkeypatch, capsys):
    opencode_home = tmp_path / "custom-opencode"
    opencode_home.mkdir()
    (opencode_home / "opencode.jsonc").write_text(
        '''{
          // JSONC is an official OpenCode config format.
          "mcp": {"servers": {"local-ai": {"type": "local",},},},
        }''',
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENCODE_HOME", str(opencode_home))
    monkeypatch.setenv("APPDATA", str(tmp_path / "legacy-appdata"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(sys, "argv", ["verify_agent_handshake.py"])

    assert verify_agent_handshake.main() == 0
    output = capsys.readouterr().out
    assert "OpenCode" in output
    assert "Hub MCP route configured" in output
    assert "legacy-appdata" not in output


def test_json_mcp_check_distinguishes_valid_config_from_hub_route(tmp_path):
    config = tmp_path / "mcp.json"
    config.write_text('{"mcpServers":{"browser":{"command":"browser"}}}', encoding="utf-8")

    status, _detail = verify_agent_handshake.check_mcp_json_file(config)
    assert status == "CONFIG_PRESENT_NO_HUB_ROUTE"

    config.write_text('{"mcpServers":{"local-ai":{"command":"python"}}}', encoding="utf-8")
    status, detail = verify_agent_handshake.check_mcp_json_file(config)
    assert status == "HUB_ROUTE_CONFIGURED"
    assert "mcpServers.local-ai" in detail


def test_codex_and_claude_plugin_config_are_reported_separately_from_mcp(tmp_path):
    codex = tmp_path / "config.toml"
    codex.write_text(
        '[plugins."local-ai-hub@local-ai-hub"]\nenabled = true\n', encoding="utf-8"
    )
    status, detail = verify_agent_handshake.check_codex_config(codex)
    assert status == "PLUGIN_ENABLED_CONFIGURED"
    assert "plugins.local-ai-hub@local-ai-hub" in detail

    claude = tmp_path / "settings.json"
    claude.write_text(
        '{"enabledPlugins":{"local-ai-hub@local-ai-hub":true}}', encoding="utf-8"
    )
    status, detail = verify_agent_handshake.check_claude_settings(claude)
    assert status == "PLUGIN_ENABLED_CONFIGURED"
    assert "enabledPlugins.local-ai-hub@local-ai-hub" in detail


def test_codex_plugin_cache_reports_version_drift_from_source(tmp_path):
    codex_home = tmp_path / ".codex"
    cached = codex_home / "plugins" / "cache" / "local-ai-hub" / "local-ai-hub" / "6.1.0" / "plugin.json"
    cached.parent.mkdir(parents=True)
    cached.write_text('{"name":"local-ai-hub","version":"6.1.0"}', encoding="utf-8")

    status, detail = verify_agent_handshake.check_codex_plugin_cache(codex_home, "8.1.0")

    assert status == "STALE_PLUGIN_CACHE"
    assert "6.1.0" in detail
    assert "8.1.0" in detail


def test_codex_plugin_cache_accepts_newer_provider_snapshot(tmp_path):
    codex_home = tmp_path / ".codex"
    cached = codex_home / "plugins" / "cache" / "local-ai-hub" / "local-ai-hub" / "8.2.1" / "plugin.json"
    cached.parent.mkdir(parents=True)
    cached.write_text('{"name":"local-ai-hub","version":"8.2.1"}', encoding="utf-8")

    status, detail = verify_agent_handshake.check_codex_plugin_cache(codex_home, "8.2.0")

    assert status == "PLUGIN_CACHE_CURRENT"
    assert "newer" in detail.lower()
    assert "8.2.1" in detail


def test_claude_plugin_cache_detects_stale_active_user_install(tmp_path):
    claude_home = tmp_path / ".claude"
    install = claude_home / "plugins" / "cache" / "local-ai-hub" / "local-ai-hub" / "8.1.0"
    manifest = install / ".claude-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"name":"local-ai-hub","version":"8.1.0"}', encoding="utf-8")
    installed = claude_home / "plugins" / "installed_plugins.json"
    installed.write_text(json.dumps({"plugins": {"local-ai-hub@local-ai-hub": [{
        "scope": "user", "installPath": str(install), "version": "8.1.0",
    }]}}), encoding="utf-8")

    status, detail = verify_agent_handshake.check_claude_plugin_cache(claude_home, "8.2.0")

    assert status == "STALE_PLUGIN_CACHE"
    assert "8.1.0" in detail
    assert "8.2.0" in detail


def test_claude_plugin_cache_accepts_newer_active_user_install(tmp_path):
    claude_home = tmp_path / ".claude"
    install = claude_home / "plugins" / "cache" / "local-ai-hub" / "local-ai-hub" / "8.2.1"
    manifest = install / ".claude-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"name":"local-ai-hub","version":"8.2.1"}', encoding="utf-8")
    installed = claude_home / "plugins" / "installed_plugins.json"
    installed.write_text(json.dumps({"plugins": {"local-ai-hub@local-ai-hub": [{
        "scope": "user", "installPath": str(install), "version": "8.2.1",
    }]}}), encoding="utf-8")

    status, detail = verify_agent_handshake.check_claude_plugin_cache(claude_home, "8.2.0")

    assert status == "PLUGIN_CACHE_CURRENT"
    assert "8.2.1" in detail


def test_codex_runtime_reports_stale_live_plugin_process(tmp_path):
    codex_home = tmp_path / ".codex"
    stale_command = (
        f'"{codex_home}\\plugins\\cache\\local-ai-hub\\local-ai-hub\\6.1.0/'
        'scripts/run_hub.py mcp_server'
    )

    status, detail = verify_agent_handshake.check_codex_active_mcp_processes(
        codex_home, "8.1.0", process_commands=[stale_command],
    )

    assert status == "STALE_ACTIVE_MCP_PROCESS"
    assert "6.1.0" in detail
    assert "8.1.0" in detail


def test_codex_runtime_classifies_versions_returned_by_host_process_query(tmp_path):
    status, detail = verify_agent_handshake.check_codex_active_mcp_processes(
        tmp_path / ".codex", "8.1.0", process_commands=["6.1.0", "6.1.0"],
    )

    assert status == "STALE_ACTIVE_MCP_PROCESS"
    assert "6.1.0" in detail


def test_codex_runtime_distinguishes_current_process_from_no_observed_process(tmp_path):
    codex_home = tmp_path / ".codex"
    current_command = (
        f'"{codex_home}\\plugins\\cache\\local-ai-hub\\local-ai-hub\\8.1.0/'
        'scripts/run_hub.py mcp_server'
    )

    assert verify_agent_handshake.check_codex_active_mcp_processes(
        codex_home, "8.1.0", process_commands=[current_command],
    )[0] == "ACTIVE_MCP_PROCESS_CURRENT"
    assert verify_agent_handshake.check_codex_active_mcp_processes(
        codex_home, "8.1.0", process_commands=[],
    )[0] == "RUNTIME_NOT_OBSERVED"


def test_antigravity_native_plugin_manifest_is_reported_without_claiming_runtime(tmp_path):
    plugin_dir = tmp_path / "plugins" / "local-ai-hub"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps({
            "name": "local-ai-hub",
            "version": verify_agent_handshake.source_hub_version(),
        }), encoding="utf-8"
    )

    status, detail = verify_agent_handshake.check_antigravity_plugin(plugin_dir)
    assert status == "PLUGIN_MANIFEST_PRESENT"
    assert "manifest present" in detail.lower()


def test_antigravity_plugin_bundle_check_requires_generated_runtime_files(tmp_path):
    gemini = tmp_path / ".gemini"
    plugin = gemini / "config" / "plugins" / "local-ai-hub"
    (plugin / "scripts").mkdir(parents=True)
    (plugin / "skills" / "local-ai-orchestrator").mkdir(parents=True)
    (plugin / "plugin.json").write_text(json.dumps({
        "name": "local-ai-hub",
        "version": verify_agent_handshake.source_hub_version(),
    }), encoding="utf-8")
    (plugin / "mcp_config.json").write_text(
        '{"mcpServers":{"local-ai":{"command":"python"}}}', encoding="utf-8"
    )
    (plugin / "hooks.json").write_text(json.dumps({"local-ai-hub": {
        "SessionStart": [{"command": "python"}],
        "PreToolUse": [{"matcher": "read_file", "hooks": [{"command": "python"}]}],
        "PostToolUse": [{"matcher": "write_file", "hooks": [{"command": "python"}]}],
    }}), encoding="utf-8")
    (plugin / "scripts" / "run_hub.py").write_text("# runner\n", encoding="utf-8")
    (plugin / "skills" / "local-ai-orchestrator" / "SKILL.md").write_text("# skill\n", encoding="utf-8")

    status, detail = verify_agent_handshake.check_antigravity_plugin_bundle(gemini)

    assert status == "PLUGIN_MANIFEST_PRESENT"
    assert "MCP route" in detail
    (plugin / "mcp_config.json").write_text('{"mcpServers":{}}', encoding="utf-8")
    status, detail = verify_agent_handshake.check_antigravity_plugin_bundle(gemini)
    assert status == "INVALID_CONFIG"
    assert "MCP route is invalid" in detail


def test_configuration_check_reports_each_multigravity_profile(tmp_path, monkeypatch, capsys):
    profiles = tmp_path / "profiles"
    gemini = profiles / "Adam" / "home" / ".gemini"
    plugin = gemini / "config" / "plugins" / "local-ai-hub"
    (plugin / "scripts").mkdir(parents=True)
    (plugin / "skills" / "local-ai-orchestrator").mkdir(parents=True)
    (plugin / "plugin.json").write_text(json.dumps({
        "name": "local-ai-hub",
        "version": verify_agent_handshake.source_hub_version(),
    }), encoding="utf-8")
    (plugin / "mcp_config.json").write_text(
        '{"mcpServers":{"local-ai":{"command":"python"}}}', encoding="utf-8"
    )
    (plugin / "hooks.json").write_text(json.dumps({"local-ai-hub": {
        "SessionStart": [{"command": "python"}],
        "PreToolUse": [{"matcher": "read_file", "hooks": [{"command": "python"}]}],
        "PostToolUse": [{"matcher": "write_file", "hooks": [{"command": "python"}]}],
    }}), encoding="utf-8")
    (plugin / "scripts" / "run_hub.py").write_text("# runner\n", encoding="utf-8")
    (plugin / "skills" / "local-ai-orchestrator" / "SKILL.md").write_text("# skill\n", encoding="utf-8")
    monkeypatch.setenv("MULTIGRAVITY_PROFILES", str(profiles))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "empty-home")
    monkeypatch.setattr(sys, "argv", ["verify_agent_handshake.py"])

    assert verify_agent_handshake.main() == 0
    output = capsys.readouterr().out
    assert "Antigravity (MultiGravity: Adam)" in output
    assert "Native plugin bundle present" in output


def test_gemini_cli_extension_manifest_is_reported_without_claiming_runtime(tmp_path, monkeypatch, capsys):
    extension = tmp_path / ".gemini" / "extensions" / "local-ai-hub"
    extension.mkdir(parents=True)
    (extension / "gemini-extension.json").write_text(
        '{"name":"local-ai-hub","version":"6.1.0"}', encoding="utf-8"
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(sys, "argv", ["verify_agent_handshake.py"])

    assert verify_agent_handshake.main() == 0
    output = capsys.readouterr().out
    assert "Gemini CLI extension" in output
    assert "EXTENSION_MANIFEST_PRESENT" in output
    assert "configuration is not a live handshake" in output.lower()
    assert "Hub readiness probe skipped" in output


def test_gemini_extension_route_is_not_reported_missing_from_settings(tmp_path, monkeypatch, capsys):
    gemini = tmp_path / ".gemini"
    (gemini / "extensions" / "local-ai-hub").mkdir(parents=True)
    (gemini / "settings.json").write_text(
        '{"mcpServers":{"browser-mcp":{"command":"browser"}}}', encoding="utf-8"
    )
    (gemini / "extensions" / "local-ai-hub" / "gemini-extension.json").write_text(
        '{"name":"local-ai-hub","version":"8.2.0",'
        '"mcpServers":{"local-ai":{"command":"python"}}}', encoding="utf-8"
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(sys, "argv", ["verify_agent_handshake.py"])

    assert verify_agent_handshake.main() == 0
    output = capsys.readouterr().out
    settings_line = next(line for line in output.splitlines() if "Gemini CLI (settings.json)" in line)
    assert "EXTENSION_ROUTE_CONFIGURED" in settings_line
    assert "standalone mcpservers.local-ai route is not required" in settings_line.casefold()


def test_cursor_native_plugin_manifest_is_not_misreported_as_missing_mcp(tmp_path):
    manifest = tmp_path / ".cursor-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({
        "name": "local-ai-hub",
        "version": verify_agent_handshake.source_hub_version(),
    }), encoding="utf-8")

    status, detail = verify_agent_handshake.check_plugin_manifest(manifest, "local-ai-hub")
    assert status == "PLUGIN_MANIFEST_PRESENT"
    assert str(manifest) in detail


def test_cursor_native_plugin_stale_version_is_reported(tmp_path):
    manifest = tmp_path / ".cursor-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        '{"name":"local-ai-hub","version":"6.1.0"}', encoding="utf-8"
    )

    status, detail = verify_agent_handshake.check_plugin_manifest(manifest, "local-ai-hub")

    assert status == "STALE_PLUGIN_VERSION"
    assert "6.1.0" in detail
    assert verify_agent_handshake.source_hub_version() in detail


def test_cursor_native_plugin_newer_version_is_not_stale(tmp_path):
    manifest = tmp_path / ".cursor-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        '{"name":"local-ai-hub","version":"8.2.1"}', encoding="utf-8"
    )

    status, detail = verify_agent_handshake.check_plugin_manifest(manifest, "local-ai-hub")

    assert status == "PLUGIN_MANIFEST_PRESENT"
    assert "newer" in detail.lower()


def test_codex_runtime_accepts_newer_live_plugin_process(tmp_path):
    codex_home = tmp_path / ".codex"
    newer_command = (
        f'"{codex_home}\\plugins\\cache\\local-ai-hub\\local-ai-hub\\8.2.1/'
        'scripts/run_hub.py mcp_server'
    )

    status, detail = verify_agent_handshake.check_codex_active_mcp_processes(
        codex_home, "8.2.0", process_commands=[newer_command]
    )

    assert status == "ACTIVE_MCP_PROCESS_CURRENT"
    assert "newer" in detail.lower()
