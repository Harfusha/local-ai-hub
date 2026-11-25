#!/usr/bin/env python3
"""Verify agent configurations, MCP manifests, skills, and live Hub handshake."""
from __future__ import annotations

import json
import os
import sys
import argparse
import subprocess
import tomllib
import re
import shutil
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


def check_codex_plugin_cache(codex_home: Path, expected_version: str) -> tuple[str, str]:
    """Detect an installed Codex plugin snapshot older than the source bundle."""
    cache_root = codex_home / "plugins" / "cache"
    versions: set[str] = set()
    for manifest_path in cache_root.glob("*/local-ai-hub/*/plugin.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if isinstance(manifest, dict) and manifest.get("name") == "local-ai-hub":
            version = manifest.get("version")
            if isinstance(version, str) and version.strip():
                versions.add(version.strip())
    if not versions:
        return "PLUGIN_CACHE_NOT_OBSERVED", "No installed Local AI Hub Codex plugin cache found"
    if expected_version in versions:
        return "PLUGIN_CACHE_CURRENT", f"Codex plugin cache includes source version {expected_version}"
    rendered = ", ".join(sorted(versions))
    return (
        "STALE_PLUGIN_CACHE",
        f"Codex plugin cache version(s) {rendered} differ from source {expected_version}; reload the Local AI Hub plugin",
    )


def check_codex_active_mcp_processes(
    codex_home: Path,
    expected_version: str,
    *,
    process_commands: list[str] | None = None,
) -> tuple[str, str]:
    """Compare live Codex Hub MCP launch paths with the installed source version."""
    if process_commands is None:
        if os.name != "nt":
            return "RUNTIME_PROCESS_UNKNOWN", "Live Codex MCP process inspection is supported on Windows only"
        powershell = shutil.which("powershell")
        if not powershell:
            return "RUNTIME_PROCESS_UNKNOWN", "PowerShell is unavailable; live Codex MCP version was not inspected"
        env = os.environ.copy()
        env["LOCAL_AI_CODEX_HOME"] = str(codex_home.expanduser().resolve())
        script = r"""
$prefix = [regex]::Escape($env:LOCAL_AI_CODEX_HOME + '\plugins\cache\local-ai-hub\local-ai-hub\')
$pattern = $prefix + '([^\\/]+)[\\/]+scripts[\\/]+run_hub\.py\s+mcp_server'
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine -match $pattern } | ForEach-Object {
  $match = [regex]::Match($_.CommandLine, $pattern)
  if ($match.Success) { $match.Groups[1].Value }
}
"""
        try:
            result = subprocess.run(
                [powershell, "-NoProfile", "-Command", script],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=10, env=env, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return "RUNTIME_PROCESS_UNKNOWN", f"Live Codex MCP process inspection failed: {type(exc).__name__}"
        if result.returncode != 0:
            return "RUNTIME_PROCESS_UNKNOWN", "Live Codex MCP process inspection failed"
        process_commands = result.stdout.splitlines()

    if all(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", value.strip()) for value in process_commands):
        versions = sorted({
            version for value in process_commands
            if (version := value.strip())
        })
    else:
        parts = [part for part in re.split(r"[\\/]+", str(codex_home.expanduser().resolve())) if part]
        home_pattern = r"[\\/]+".join(re.escape(part) for part in parts)
        pattern = re.compile(
            home_pattern
            + r"[\\/]+plugins[\\/]+cache[\\/]+local-ai-hub[\\/]+local-ai-hub[\\/]+"
            + r"([^\\/]+)[\\/]+scripts[\\/]+run_hub\.py\s+mcp_server",
            re.IGNORECASE,
        )
        versions = sorted({
            match.group(1).strip()
            for command in process_commands
            for match in [pattern.search(command)]
            if match and match.group(1).strip()
        })
    if not versions:
        return "RUNTIME_NOT_OBSERVED", "No running Codex Local AI Hub MCP subprocess was observed"
    if any(version != expected_version for version in versions):
        return (
            "STALE_ACTIVE_MCP_PROCESS",
            f"Running Codex MCP cache version(s) {', '.join(versions)} differ from source {expected_version}; restart Codex to reload",
        )
    return "ACTIVE_MCP_PROCESS_CURRENT", f"Running Codex MCP process uses source cache version {expected_version}"

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


def check_antigravity_plugin_bundle(gemini_dir: Path) -> tuple[str, str]:
    """Verify the generated MCP, hook, and skill files behind an installed manifest."""
    plugin_dir = gemini_dir / "config" / "plugins" / "local-ai-hub"
    status, detail = check_antigravity_plugin(plugin_dir)
    if status != "PLUGIN_MANIFEST_PRESENT":
        return status, detail
    mcp_status, mcp_detail = check_mcp_json_file(plugin_dir / "mcp_config.json")
    if mcp_status != "HUB_ROUTE_CONFIGURED":
        return "INVALID_CONFIG", f"Plugin manifest present but its MCP route is invalid: {mcp_detail}"
    try:
        hooks = json.loads((plugin_dir / "hooks.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return "INVALID_CONFIG", f"Plugin manifest present but hooks are invalid: {exc}"
    hook_group = hooks.get("local-ai-hub") if isinstance(hooks, dict) else None
    required_events = {"SessionStart", "PreToolUse", "PostToolUse"}
    if (
        not isinstance(hook_group, dict)
        or not required_events.issubset(hook_group)
        or any(not isinstance(hook_group[event], list) or not hook_group[event] for event in required_events)
    ):
        return "INVALID_CONFIG", "Plugin manifest present but required Hub hook events are missing"
    runner = plugin_dir / "scripts" / "run_hub.py"
    skill = plugin_dir / "skills" / "local-ai-orchestrator" / "SKILL.md"
    missing = [str(path) for path in (runner, skill) if not path.is_file()]
    if missing:
        return "INVALID_CONFIG", "Plugin bundle files missing: " + ", ".join(missing)
    return "PLUGIN_MANIFEST_PRESENT", "Native plugin bundle present: MCP route, 3 hook events, runner, and orchestrator skill"


def discover_multigravity_profile_homes(user_home: Path) -> list[tuple[str, Path]]:
    """Find isolated MultiGravity profile homes for config-only verification."""
    configured = os.environ.get("MULTIGRAVITY_PROFILES") or os.environ.get("MULTIGRAVITY_HOME")
    profiles_dir: Path | None = None
    if configured:
        candidate = Path(configured).expanduser()
        profiles_dir = candidate if candidate.name.casefold() == "profiles" else candidate / "profiles"
    else:
        for parent in (user_home, *user_home.parents):
            candidate = parent / "Desktop" / "Multigravity" / "profiles"
            if candidate.is_dir():
                profiles_dir = candidate
                break
    if profiles_dir is None or not profiles_dir.is_dir():
        return []
    found: list[tuple[str, Path]] = []
    for profile in sorted((item for item in profiles_dir.iterdir() if item.is_dir()), key=lambda item: item.name.casefold()):
        home = profile / "home" if (profile / "home").is_dir() else profile
        if home.is_dir():
            found.append((profile.name, home / ".gemini"))
    return found


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


def probe_mcp_stdio(repo_root: Path, *, timeout_seconds: float = 15.0) -> tuple[bool, str]:
    """Launch the bundled MCP server and verify the real initialize/tools/list exchange."""
    root = repo_root.resolve()
    env = os.environ.copy()
    source_path = str(root / "src")
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (source_path, existing_pythonpath) if part
    )
    env.setdefault("LOCAL_AI_CONFIG", str(root / "config.toml"))
    messages = (
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "local-ai-hub-handshake-check", "version": "1"},
        }},
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    )
    payload = "".join(json.dumps(message, separators=(",", ":")) + "\n" for message in messages)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "local_ai_hub.mcp_server"],
            cwd=root,
            env=env,
            input=payload,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"MCP stdio handshake could not complete ({type(exc).__name__})"

    responses: dict[int, dict[str, Any]] = {}
    for line in result.stdout.splitlines():
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(message, dict) and isinstance(message.get("id"), int):
            responses[message["id"]] = message

    initialized = responses.get(1, {}).get("result")
    listing = responses.get(2, {}).get("result")
    tools = listing.get("tools") if isinstance(listing, dict) else None
    if result.returncode != 0:
        return False, f"MCP server exited with code {result.returncode}"
    if not isinstance(initialized, dict) or not isinstance(tools, list):
        return False, "MCP server did not complete initialize and tools/list"
    names = sorted(
        item["name"] for item in tools
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    )
    required = {
        "local_ai_status", "local_ai_task", "local_ai_repo", "local_ai_rag",
        "local_ai_coord", "local_ai_artifact",
    }
    missing = sorted(required - set(names))
    if missing:
        return False, f"MCP handshake omitted required tools: {', '.join(missing)}"
    return True, f"MCP stdio handshake OK ({len(names)} tools: {', '.join(names)})"

def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect provider configuration and optionally probe Hub/MCP readiness.")
    parser.add_argument(
        "--probe-hub",
        action="store_true",
        help="Make an HTTP readiness request to the local Hub at 127.0.0.1:11435.",
    )
    parser.add_argument(
        "--probe-mcp",
        action="store_true",
        help="Launch the bundled MCP stdio server and require initialize plus the six core tools.",
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
    plugin_status, plugin_detail = check_antigravity_plugin_bundle(g_dir)
    if plugin_status == "PLUGIN_MANIFEST_PRESENT":
        status_mcp, msg_mcp = plugin_status, plugin_detail
    elif plugin_status == "INVALID_CONFIG" and status_mcp != "HUB_ROUTE_CONFIGURED":
        status_mcp, msg_mcp = plugin_status, plugin_detail
    results.append({"agent": "Antigravity", "status": status_mcp, "detail": msg_mcp})
    for profile_name, profile_gemini_dir in discover_multigravity_profile_homes(user_home):
        profile_status, profile_detail = check_antigravity_plugin_bundle(profile_gemini_dir)
        if profile_status == "MISSING":
            profile_status, profile_detail = check_mcp_json_file(
                profile_gemini_dir / "config" / "mcp_config.json"
            )
        results.append({
            "agent": f"Antigravity (MultiGravity: {profile_name})",
            "status": profile_status,
            "detail": profile_detail,
        })
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
    source_version = None
    if codex_status == "PLUGIN_ENABLED_CONFIGURED":
        source_manifest = Path(__file__).resolve().parents[1] / "plugins" / "codex" / "local-ai-hub" / "plugin.json"
        try:
            source_data = json.loads(source_manifest.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            source_data = {}
        source_version = source_data.get("version") if isinstance(source_data, dict) else None
        if isinstance(source_version, str) and source_version.strip():
            cache_status, cache_detail = check_codex_plugin_cache(codex_home, source_version.strip())
            if cache_status == "STALE_PLUGIN_CACHE":
                codex_status, msg_codex = cache_status, cache_detail
    results.append({"agent": "Codex (config.toml)", "status": codex_status, "detail": msg_codex})
    if codex_status == "PLUGIN_ENABLED_CONFIGURED" and isinstance(source_version, str) and source_version.strip():
        runtime_status, runtime_detail = check_codex_active_mcp_processes(codex_home, source_version.strip())
        results.append({"agent": "Codex MCP runtime", "status": runtime_status, "detail": runtime_detail})

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

    mcp_failed = False
    if args.probe_mcp:
        ok, detail = probe_mcp_stdio(Path(__file__).resolve().parents[1])
        print(f"[{'OK' if ok else 'FAIL'}] {detail}")
        mcp_failed = not ok
    else:
        print("[SKIP] MCP stdio handshake skipped; pass --probe-mcp to opt in.")

    print("=" * 60)
    return 1 if mcp_failed else 0

if __name__ == "__main__":
    sys.exit(main())
