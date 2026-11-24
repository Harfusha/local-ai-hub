#!/usr/bin/env python3
"""Verify agent configurations, MCP manifests, skills, and live Hub handshake."""
from __future__ import annotations

import json
import os
import sys
import argparse
import tomllib
from pathlib import Path
from typing import Any

def check_json_file(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, "File does not exist"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return False, "JSON is not an object"
        return True, f"Valid JSON ({len(data)} keys)"
    except Exception as exc:
        return False, f"JSON error: {exc}"

def check_file_exists(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, "Not found"
    return True, f"Found ({path.stat().st_size} bytes)"

def check_mcp_json_file(path: Path, containers: tuple[str, ...] = ("mcpServers",)) -> tuple[str, str]:
    if not path.is_file():
        return "MISSING", "File does not exist"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return "INVALID_CONFIG", f"JSON error: {exc}"
    if not isinstance(data, dict):
        return "INVALID_CONFIG", "JSON is not an object"
    for key in containers:
        servers = data.get(key)
        if isinstance(servers, dict) and "local-ai" in servers:
            return "HUB_ROUTE_CONFIGURED", f"Hub MCP route configured: {key}.local-ai"
    return "CONFIG_PRESENT_NO_HUB_ROUTE", f"Valid JSON; no local-ai route in {', '.join(containers)}"

def check_codex_mcp_config(path: Path) -> tuple[str, str]:
    if not path.is_file():
        return "MISSING", "File does not exist"
    try:
        with path.open("rb") as source:
            data = tomllib.load(source)
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        return "INVALID_CONFIG", f"TOML error: {exc}"
    servers = data.get("mcp_servers")
    if isinstance(servers, dict) and "local-ai" in servers:
        return "HUB_ROUTE_CONFIGURED", "Hub MCP route configured: mcp_servers.local-ai"
    return "CONFIG_PRESENT_NO_HUB_ROUTE", "Valid TOML; no mcp_servers.local-ai route"

def check_codex_config(path: Path) -> tuple[str, str]:
    if not path.is_file():
        return "MISSING", "File does not exist"
    try:
        with path.open("rb") as source:
            data = tomllib.load(source)
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        return "INVALID_CONFIG", f"TOML error: {exc}"
    routes: list[str] = []
    plugins = data.get("plugins")
    plugin = plugins.get("local-ai-hub@local-ai-hub") if isinstance(plugins, dict) else None
    if isinstance(plugin, dict) and plugin.get("enabled") is True:
        routes.append("plugin enabled in config: plugins.local-ai-hub@local-ai-hub")
    servers = data.get("mcp_servers")
    if isinstance(servers, dict) and "local-ai" in servers:
        routes.append("MCP route configured: mcp_servers.local-ai")
    if routes:
        status = "PLUGIN_ENABLED_CONFIGURED" if any(item.startswith("plugin ") for item in routes) else "HUB_ROUTE_CONFIGURED"
        return status, "; ".join(routes)
    return "CONFIG_PRESENT_NO_HUB_ROUTE", "Valid TOML; no enabled Hub plugin or mcp_servers.local-ai route"

def check_claude_settings(path: Path) -> tuple[str, str]:
    if not path.is_file():
        return "MISSING", "File does not exist"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return "INVALID_CONFIG", f"JSON error: {exc}"
    if not isinstance(data, dict):
        return "INVALID_CONFIG", "JSON is not an object"
    enabled = data.get("enabledPlugins")
    if isinstance(enabled, dict) and enabled.get("local-ai-hub@local-ai-hub") is True:
        return "PLUGIN_ENABLED_CONFIGURED", "Hub plugin enabled in config: enabledPlugins.local-ai-hub@local-ai-hub"
    return "CONFIG_PRESENT_NO_HUB_ROUTE", "Valid Claude settings; Hub plugin is not enabled"

def check_plugin_manifest(manifest_path: Path, expected_name: str) -> tuple[str, str]:
    if not manifest_path.is_file():
        return "MISSING", "Native Hub plugin manifest is not installed"
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return "INVALID_CONFIG", f"Plugin manifest JSON error: {exc}"
    if not isinstance(data, dict) or data.get("name") != expected_name:
        return "INVALID_CONFIG", f"Plugin manifest does not identify {expected_name}"
    return "PLUGIN_MANIFEST_PRESENT", f"Native Hub plugin manifest present: {manifest_path}"

def check_antigravity_plugin(plugin_dir: Path) -> tuple[str, str]:
    return check_plugin_manifest(plugin_dir / "plugin.json", "local-ai-hub")


def check_gemini_cli_extension(extension_dir: Path) -> tuple[str, str]:
    """Report an installed Gemini CLI extension manifest without asserting it is enabled."""
    manifest_path = extension_dir / "gemini-extension.json"
    if not manifest_path.is_file():
        return "MISSING", "Gemini CLI Hub extension manifest is not installed"
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return "INVALID_CONFIG", f"Gemini CLI extension manifest JSON error: {exc}"
    if not isinstance(data, dict) or data.get("name") != "local-ai-hub":
        return "INVALID_CONFIG", "Gemini CLI extension manifest does not identify local-ai-hub"
    return "EXTENSION_MANIFEST_PRESENT", f"Gemini CLI Hub extension manifest present: {manifest_path}"

def opencode_config_dirs() -> list[Path]:
    """Use OpenCode's canonical global root or its explicit override."""
    configured = os.environ.get("OPENCODE_HOME", "").strip()
    if configured:
        return [Path(configured).expanduser()]
    return [Path.home() / ".config" / "opencode"]

def load_opencode_config(path: Path) -> dict[str, Any]:
    """Reuse setup's JSON/JSONC parser without starting a provider or Hub."""
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from tools.setup import _load_opencode_config
    return _load_opencode_config(path)

def check_opencode_config(config_dir: Path) -> tuple[str, str]:
    files = [path for path in (config_dir / "opencode.json", config_dir / "opencode.jsonc") if path.is_file()]
    if not files:
        return "CONFIGURED_WHEN_OPENCODE_INSTALLED", f"No user config found in {config_dir}"
    hub_routes: list[str] = []
    for path in files:
        try:
            data = load_opencode_config(path)
        except (OSError, UnicodeError, ValueError, RuntimeError) as exc:
            return "INVALID_CONFIG", f"{path}: {exc}"
        mcp = data.get("mcp")
        servers = mcp.get("servers") if isinstance(mcp, dict) else None
        if isinstance(servers, dict) and "local-ai" in servers:
            hub_routes.append(f"standalone MCP in {path.name}")
        plugins = data.get("plugins")
        if isinstance(plugins, list) and any("local-ai-hub" in str(plugin).casefold() for plugin in plugins):
            hub_routes.append(f"plugin in {path.name}")
    if hub_routes:
        return "HUB_ROUTE_CONFIGURED", "Hub MCP route configured: " + "; ".join(hub_routes)
    return "CONFIG_PRESENT_NO_HUB_ROUTE", ", ".join(path.name for path in files)

def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect configured agent MCP files and optionally probe Hub readiness.")
    parser.add_argument(
        "--probe-hub",
        action="store_true",
        help="Make an HTTP readiness request to the local Hub at 127.0.0.1:11435.",
    )
    args = parser.parse_args(sys.argv[1:])

    print("=" * 60)
    print("Agent Configuration Check (configuration is not a live handshake)")
    print("=" * 60)

    user_home = Path.home()
    results: list[dict[str, Any]] = []

    # 1. Antigravity / Gemini CLI
    g_dir = user_home / ".gemini"
    antigravity_mcp = g_dir / "config" / "mcp_config.json"
    status_mcp, msg_mcp = check_mcp_json_file(antigravity_mcp)
    plugin_status, plugin_detail = check_antigravity_plugin(g_dir / "config" / "plugins" / "local-ai-hub")
    if plugin_status == "PLUGIN_MANIFEST_PRESENT":
        status_mcp, msg_mcp = plugin_status, plugin_detail
    elif plugin_status == "INVALID_CONFIG" and status_mcp != "HUB_ROUTE_CONFIGURED":
        status_mcp, msg_mcp = plugin_status, plugin_detail
    results.append({"agent": "Antigravity", "status": status_mcp, "detail": msg_mcp})
    gemini_settings = g_dir / "settings.json"
    gemini_status, gemini_detail = check_mcp_json_file(gemini_settings)
    results.append({"agent": "Gemini CLI (settings.json)", "status": gemini_status, "detail": gemini_detail})
    extension_status, extension_detail = check_gemini_cli_extension(
        g_dir / "extensions" / "local-ai-hub"
    )
    results.append({"agent": "Gemini CLI extension", "status": extension_status, "detail": extension_detail})

    # 2. Codex
    codex_home = Path(os.environ.get("CODEX_HOME", user_home / ".codex"))
    codex_cfg = codex_home / "config.toml"
    codex_status, msg_codex = check_codex_config(codex_cfg)
    results.append({"agent": "Codex (config.toml)", "status": codex_status, "detail": msg_codex})

    # 3. Claude Code
    claude_mcp = user_home / ".claude.json"
    claude_status, msg_claude = check_claude_settings(user_home / ".claude" / "settings.json")
    if claude_status != "PLUGIN_ENABLED_CONFIGURED":
        mcp_status, mcp_detail = check_mcp_json_file(claude_mcp)
        if mcp_status in {"HUB_ROUTE_CONFIGURED", "INVALID_CONFIG"}:
            claude_status, msg_claude = mcp_status, mcp_detail
    results.append({"agent": "Claude Code", "status": claude_status, "detail": msg_claude})

    # 4. Cursor
    cursor_mcp = user_home / ".cursor" / "mcp.json"
    cursor_status, msg_cursor = check_mcp_json_file(cursor_mcp)
    cursor_plugin_status, cursor_plugin_detail = check_plugin_manifest(
        user_home / ".cursor" / "plugins" / "local" / "local-ai-hub" / ".cursor-plugin" / "plugin.json",
        "local-ai-hub",
    )
    if cursor_plugin_status == "PLUGIN_MANIFEST_PRESENT":
        cursor_status, msg_cursor = cursor_plugin_status, cursor_plugin_detail
    elif cursor_plugin_status == "INVALID_CONFIG" and cursor_status != "HUB_ROUTE_CONFIGURED":
        cursor_status, msg_cursor = cursor_plugin_status, cursor_plugin_detail
    results.append({"agent": "Cursor", "status": cursor_status, "detail": msg_cursor})

    # 5. Windsurf
    windsurf_mcp = user_home / ".codeium" / "windsurf" / "mcp_config.json"
    windsurf_status, msg_windsurf = check_mcp_json_file(windsurf_mcp)
    results.append({"agent": "Windsurf (mcp_config.json)", "status": windsurf_status, "detail": msg_windsurf})

    # 6. Devin Local
    devin_dir = (
        Path(os.environ["APPDATA"]) / "devin"
        if sys.platform == "win32" and os.environ.get("APPDATA")
        else user_home / ".config" / "devin"
    )
    devin_status, msg_devin = check_mcp_json_file(devin_dir / "mcp_config.json")
    results.append({"agent": "Devin Local (mcp_config.json)", "status": devin_status, "detail": msg_devin})

    # 7. VS Code / Copilot
    copilot_mcp = user_home / ".copilot" / "mcp-config.json"
    copilot_status, msg_copilot = check_mcp_json_file(copilot_mcp)
    results.append({"agent": "Copilot (mcp-config.json)", "status": copilot_status, "detail": msg_copilot})

    # OpenCode supports canonical JSON/JSONC settings, including OPENCODE_HOME.
    oc_status, oc_detail = check_opencode_config(opencode_config_dirs()[0])
    results.append({"agent": "OpenCode", "status": oc_status, "detail": oc_detail})

    # Print table: file presence and syntax do not prove host trust or a live MCP connection.
    for r in results:
        status_sym = "[x]" if r["status"] in {"OK", "CONFIGURED_WHEN_OPENCODE_INSTALLED", "HUB_ROUTE_CONFIGURED", "PLUGIN_ENABLED_CONFIGURED", "PLUGIN_MANIFEST_PRESENT", "EXTENSION_MANIFEST_PRESENT"} else "[-]"
        print(f"{status_sym} {r['agent']:<32} | {r['status']:<32} | {r['detail']}")

    print("-" * 60)
    if args.probe_hub:
        try:
            import urllib.request
            req = urllib.request.Request("http://127.0.0.1:11435/ready")
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode())
                print(f"[OK] Hub readiness at 127.0.0.1:11435 (ready={data.get('ready', False)})")
        except Exception as exc:
            print(f"[WARN] Hub readiness probe failed: {exc}")
    else:
        print("[SKIP] Hub readiness probe skipped; pass --probe-hub to opt in.")

    print("=" * 60)
    return 0

if __name__ == "__main__":
    sys.exit(main())
