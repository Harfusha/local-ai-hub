"""Bridge Codex plugin hook events into the configured Local AI Hub runtime."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path


def _configured_hub_command() -> tuple[list[str], Path, dict[str, str]] | None:
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    config_path = codex_home / "config.toml"
    install_dir: Path | None = None
    config: dict[str, object] = {}
    try:
        config = tomllib.loads(config_path.read_text(encoding="utf-8"))
        entry = config.get("mcp_servers", {}).get("local-ai")
    except (OSError, UnicodeError, tomllib.TOMLDecodeError, AttributeError):
        entry = None

    if isinstance(entry, dict) and "url" not in entry:
        command = entry.get("command")
        args = entry.get("args")
        cwd = entry.get("cwd")
        env = entry.get("env", {})
        if (
            isinstance(command, str) and Path(command).is_absolute() and Path(command).is_file()
            and args == ["-m", "local_ai_hub.mcp_server"]
            and isinstance(cwd, str) and Path(cwd).is_absolute() and Path(cwd).is_dir()
            and isinstance(env, dict)
            and all(isinstance(key, str) and isinstance(value, str) for key, value in env.items())
        ):
            install_dir = Path(cwd)
            if (
                env.get("LOCAL_AI_AGENT") == "codex"
                and env.get("LOCAL_AI_AGENT_PROFILE") == "codex"
                and env.get("LOCAL_AI_CONFIG") == str(install_dir / "config.toml")
                and env.get("PYTHONPATH") == str(install_dir / "src")
            ):
                return [command, "-m", "local_ai_hub.repo_plan.host_hooks", "--host", "codex"], install_dir, env

    # The Hub may expose MCP over HTTP, which has no local interpreter to reuse.
    # Resolve only the explicitly configured Hub installation and its managed venv.
    explicit_home = os.environ.get("LOCAL_AI_HUB_DIR", "").strip()
    if explicit_home:
        # Match the bundled MCP launcher: an explicit install is authoritative.
        candidates = [Path(explicit_home).expanduser()]
    else:
        setup = config.get("setup") if isinstance(config, dict) else None
        configured_home = setup.get("install_dir") if isinstance(setup, dict) else None
        candidates = [Path(configured_home).expanduser()] if isinstance(configured_home, str) else []
        candidates.append(Path.home() / ".local-ai-hub")
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        module = resolved / "src" / "local_ai_hub" / "repo_plan" / "host_hooks.py"
        config_file = resolved / "config.toml"
        python = resolved / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not (resolved.is_dir() and config_file.is_file() and module.is_file() and python.is_file()):
            continue
        env = os.environ.copy()
        env.update({
            "LOCAL_AI_AGENT": "codex",
            "LOCAL_AI_AGENT_PROFILE": "codex",
            "LOCAL_AI_CONFIG": str(config_file),
            "PYTHONPATH": str(resolved / "src"),
        })
        return [str(python), "-m", "local_ai_hub.repo_plan.host_hooks", "--host", "codex"], resolved, env
    return None


def main() -> int:
    raw = sys.stdin.buffer.read(65537)
    if len(raw) > 65536:
        sys.stdout.write("{}\n")
        return 0
    try:
        event = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        sys.stdout.write("{}\n")
        return 0
    if not isinstance(event, dict):
        sys.stdout.write("{}\n")
        return 0
    configured = _configured_hub_command()
    if configured is None:
        sys.stdout.write("{}\n")
        return 0
    command, cwd, server_env = configured
    env = os.environ.copy()
    env.update(server_env)
    try:
        result = subprocess.run(
            command,
            input=raw,
            capture_output=True,
            cwd=cwd,
            env=env,
            timeout=4,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        sys.stdout.write("{}\n")
        return 0
    if result.returncode != 0:
        sys.stdout.write("{}\n")
        return 0
    try:
        output = json.loads(result.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError):
        output = None
    sys.stdout.write(json.dumps(output if isinstance(output, dict) else {}, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
