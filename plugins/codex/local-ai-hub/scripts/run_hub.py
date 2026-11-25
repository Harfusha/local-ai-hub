"""Resolve the user's Local AI Hub install and launch one approved module."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


ALLOWED_MODULES = {
    "mcp_server": "local_ai_hub.mcp_server",
    "antigravity_hook": "local_ai_hub.antigravity_hook",
    "host_hooks": "local_ai_hub.repo_plan.host_hooks",
}


def resolve_hub_install() -> Path | None:
    """Find an explicit or standard Hub install without guessing sibling apps."""
    def valid_install(path: Path) -> Path | None:
        try:
            root = path.resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            return None
        if (root / "config.toml").is_file() and (
            root / "src" / "local_ai_hub" / "mcp_server.py"
        ).is_file():
            return root
        return None

    candidates: list[Path] = []
    configured = os.environ.get("LOCAL_AI_HUB_DIR", "").strip()
    if configured:
        explicit = valid_install(Path(configured).expanduser())
        if explicit is not None:
            return explicit

    # Host hooks run outside the MCP server process, so they do not inherit its
    # environment. Setup writes the canonical install path into the adjacent
    # plugin MCP config; use it for hooks and MCP launches alike.
    plugin_root = Path(__file__).resolve().parent.parent
    for config_name in ("mcp_config.json", "mcp.json", ".mcp.json", "gemini-extension.json"):
        try:
            config = json.loads((plugin_root / config_name).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        servers = config.get("mcpServers") if isinstance(config, dict) else None
        server = servers.get("local-ai") if isinstance(servers, dict) else None
        env = server.get("env") if isinstance(server, dict) else None
        install_dir = env.get("LOCAL_AI_HUB_DIR") if isinstance(env, dict) else None
        if isinstance(install_dir, str) and install_dir.strip():
            configured_install = valid_install(Path(install_dir).expanduser())
            if configured_install is not None:
                return configured_install

    candidates.append(Path.home() / ".local-ai-hub")
    candidates.append(Path.cwd())
    user_home = Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or str(Path.home()))
    candidates.append(user_home / ".local-ai-hub")
    for parent in Path(__file__).resolve().parents:
        candidates.append(parent)

    seen: set[str] = set()
    for candidate in candidates:
        root = valid_install(candidate)
        if root is None:
            continue
        key = os.path.normcase(str(root))
        if key in seen:
            continue
        seen.add(key)
        return root
    return None


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in ALLOWED_MODULES:
        print("Local AI Hub plugin: unsupported module", file=sys.stderr)
        return 2
    module, *module_args = args
    root = resolve_hub_install()
    if root is None:
        print(
            "Local AI Hub plugin: set LOCAL_AI_HUB_DIR or install Hub at ~/.local-ai-hub",
            file=sys.stderr,
        )
        return 2

    python = root / ".venv" / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )
    if not python.is_file():
        python = Path(sys.executable)
    env = os.environ.copy()
    env.setdefault("LOCAL_AI_CONFIG", str(root / "config.toml"))
    provider = "generic_mcp"
    explicit_host = None
    if module == "host_hooks" and "--host" in module_args:
        host_index = module_args.index("--host")
        if host_index + 1 < len(module_args):
            explicit_host = module_args[host_index + 1]
    if explicit_host:
        provider = explicit_host
        env["LOCAL_AI_AGENT"] = provider
        env["LOCAL_AI_AGENT_PROFILE"] = provider
    else:
        provider = env.get("LOCAL_AI_AGENT", provider)
        env.setdefault("LOCAL_AI_AGENT", provider)
        env.setdefault("LOCAL_AI_AGENT_PROFILE", provider)
    source = str(root / "src")
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = source + (os.pathsep + existing_pythonpath if existing_pythonpath else "")
    return subprocess.call(
        [str(python), "-m", ALLOWED_MODULES[module], *module_args],
        env=env,
    )


if __name__ == "__main__":
    raise SystemExit(main())
