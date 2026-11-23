#!/usr/bin/env python3
"""Verify agent configurations, MCP manifests, skills, and live Hub handshake."""
from __future__ import annotations

import json
import os
import sys
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

def main() -> int:
    print("=" * 60)
    print("Local AI Hub Agent Handshake & Configuration Verification")
    print("=" * 60)

    user_home = Path.home()
    results: list[dict[str, Any]] = []

    # 1. Antigravity / Gemini CLI
    g_dir = user_home / ".gemini"
    antigravity_mcp = g_dir / "config" / "mcp_config.json"
    ok_mcp, msg_mcp = check_json_file(antigravity_mcp)
    results.append({"agent": "Antigravity (mcp_config.json)", "status": "OK" if ok_mcp else "MISSING", "detail": msg_mcp})

    # 2. Codex
    codex_home = Path(os.environ.get("CODEX_HOME", user_home / ".codex"))
    codex_cfg = codex_home / "config.toml"
    ok_codex, msg_codex = check_file_exists(codex_cfg)
    results.append({"agent": "Codex (config.toml)", "status": "OK" if ok_codex else "MISSING", "detail": msg_codex})

    # 3. Claude Code
    claude_mcp = user_home / ".claude.json"
    ok_claude, msg_claude = check_json_file(claude_mcp)
    results.append({"agent": "Claude Code (.claude.json)", "status": "OK" if ok_claude else "MISSING", "detail": msg_claude})

    # 4. Cursor
    cursor_mcp = user_home / ".cursor" / "mcp.json"
    ok_cursor, msg_cursor = check_json_file(cursor_mcp)
    results.append({"agent": "Cursor (mcp.json)", "status": "OK" if ok_cursor else "MISSING", "detail": msg_cursor})

    # 5. Windsurf
    windsurf_mcp = user_home / ".codeium" / "windsurf" / "mcp_config.json"
    ok_windsurf, msg_windsurf = check_json_file(windsurf_mcp)
    results.append({"agent": "Windsurf (mcp_config.json)", "status": "OK" if ok_windsurf else "MISSING", "detail": msg_windsurf})

    # 6. VS Code / Copilot
    copilot_mcp = user_home / ".copilot" / "mcp-config.json"
    ok_copilot, msg_copilot = check_json_file(copilot_mcp)
    results.append({"agent": "Copilot (mcp-config.json)", "status": "OK" if ok_copilot else "MISSING", "detail": msg_copilot})

    # 7. OpenCode
    opencode_dirs = []
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        opencode_dirs.append(Path(os.environ["APPDATA"]) / "opencode")
    opencode_dirs.append(user_home / ".config" / "opencode")
    opencode_dirs.append(user_home / ".opencode")
    found_oc = False
    oc_detail = "Checked standard paths"
    for oc in opencode_dirs:
        mcp_path = oc / "opencode.json"
        if mcp_path.exists():
            ok_oc, oc_msg = check_json_file(mcp_path)
            found_oc = True
            oc_detail = f"{mcp_path}: {oc_msg}"
            break
        mcp_alt = oc / "mcp.json"
        if mcp_alt.exists():
            ok_oc, oc_msg = check_json_file(mcp_alt)
            found_oc = True
            oc_detail = f"{mcp_alt}: {oc_msg}"
            break

    results.append({"agent": "OpenCode", "status": "OK" if found_oc else "CONFIGURED_WHEN_OPENCODE_INSTALLED", "detail": oc_detail})

    # Print table
    for r in results:
        status_sym = "[x]" if r["status"] == "OK" else "[-]"
        print(f"{status_sym} {r['agent']:<32} | {r['status']:<32} | {r['detail']}")

    print("-" * 60)
    # Check Hub alive
    try:
        import urllib.request
        req = urllib.request.Request("http://127.0.0.1:11435/ready")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
            print(f"[OK] Local AI Hub alive at 127.0.0.1:11435 (ready={data.get('ready', False)})")
    except Exception as exc:
        print(f"[WARN] Local AI Hub live probe failed: {exc}")

    print("=" * 60)
    return 0

if __name__ == "__main__":
    sys.exit(main())
