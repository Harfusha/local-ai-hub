from __future__ import annotations

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


def test_antigravity_native_plugin_manifest_is_reported_without_claiming_runtime(tmp_path):
    plugin_dir = tmp_path / "plugins" / "local-ai-hub"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(
        '{"name":"local-ai-hub","version":"6.1.0"}', encoding="utf-8"
    )

    status, detail = verify_agent_handshake.check_antigravity_plugin(plugin_dir)
    assert status == "PLUGIN_MANIFEST_PRESENT"
    assert "manifest present" in detail.lower()


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


def test_cursor_native_plugin_manifest_is_not_misreported_as_missing_mcp(tmp_path):
    manifest = tmp_path / ".cursor-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"name":"local-ai-hub"}', encoding="utf-8")

    status, detail = verify_agent_handshake.check_plugin_manifest(manifest, "local-ai-hub")
    assert status == "PLUGIN_MANIFEST_PRESENT"
    assert str(manifest) in detail
