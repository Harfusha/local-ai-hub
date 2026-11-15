"""Offline static dashboard shell, allow-listed assets, and host diagnostics (HUB-093)."""

from __future__ import annotations

import json
import os
import shutil
import stat
import time
import tomllib
from importlib.resources import files
from pathlib import Path
from types import MappingProxyType
from typing import Any


_ASSETS = MappingProxyType({
    "app.css": "text/css; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
})

LEGACY_PAGES = (
    ("overview", "Overview", "overview"),
    ("projects", "Projects", "projects"),
    ("commands", "Commands", "agents"),
    ("work", "Requests", "tasks"),
    ("agentos", "Tasks", "tasks"),
    ("coordination", "Coordination", "tasks"),
    ("performance", "Models & search", "models"),
    ("reliability", "Service health", "diagnostics"),
    ("config", "Settings", "settings"),
    ("bundles", "Transfers", "projects"),
    ("events", "Activity", "diagnostics"),
)


def _asset_bytes(name: str) -> bytes:
    return files("local_ai_hub").joinpath("ui_static", name).read_bytes()


def dashboard_frontend_html() -> str:
    return _asset_bytes("index.html").decode("utf-8")


def dashboard_frontend_asset(name: str) -> tuple[str, bytes] | None:
    """Return a packaged frontend asset only for an exact allow-listed name."""
    content_type = _ASSETS.get(name)
    if content_type is None:
        return None
    return content_type, _asset_bytes(name)


def _redact_path(path: str | Path | None) -> str | None:
    """Redact only real home-directory descendants, never a string prefix."""
    if not path:
        return None
    value = str(path)
    try:
        relative = Path(value).expanduser().relative_to(Path.home())
        return "~" if str(relative) == "." else "~/" + relative.as_posix()
    except ValueError:
        return value


_MAX_HOST_CONFIG_BYTES = 256 * 1024


def _bounded_host_config(path: Path) -> str:
    """Only inspect small regular manifest files; never follow host symlinks.

    This diagnostic has no reason to read arbitrary files outside known host
    config paths, and status is UNKNOWN if a file cannot be parsed.
    """
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_HOST_CONFIG_BYTES:
        raise ValueError("host manifest is not a small regular file")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or opened.st_size > _MAX_HOST_CONFIG_BYTES:
            raise ValueError("host manifest identity changed")
        raw = stream.read(_MAX_HOST_CONFIG_BYTES + 1)
        if len(raw) > _MAX_HOST_CONFIG_BYTES:
            raise ValueError("host manifest exceeded size limit")
        checked = path.lstat()
        if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != (
            checked.st_dev, checked.st_ino, checked.st_size, checked.st_mtime_ns
        ):
            raise ValueError("host manifest changed during read")
    return raw.decode("utf-8")


def _mcp_entry_valid(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    command = value.get("command")
    url = value.get("url")
    # Registration describes a runnable transport, not a successful handshake.
    return (isinstance(command, str) and bool(command.strip())) or (
        isinstance(url, str) and url.startswith(("http://127.0.0.1:", "http://localhost:", "http://[::1]:"))
    )


def _codex_mcp_registered(path: Path | None) -> bool:
    if path is None:
        return False
    try:
        value = tomllib.loads(_bounded_host_config(path))
        servers = value.get("mcp_servers")
        return isinstance(servers, dict) and _mcp_entry_valid(servers.get("local-ai"))
    except (OSError, ValueError, TypeError):
        return False


def _antigravity_mcp_registered(path: Path | None) -> bool:
    if path is None:
        return False
    try:
        data = json.loads(_bounded_host_config(path))
        servers = data.get("mcpServers") if isinstance(data, dict) else None
        return isinstance(servers, dict) and _mcp_entry_valid(servers.get("local-ai"))
    except (OSError, ValueError, TypeError):
        return False


def inspect_agent_hosts(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Report installation and registration separately from unobserved sessions.

    Local configuration files cannot demonstrate MCP connectivity or a live
    host handshake. Those facts remain unknown until host-issued evidence exists.
    """
    observed_at = time.time()
    home = Path.home()
    codex_cli = shutil.which("codex") or shutil.which("codex.cmd")
    codex_dir = Path(os.environ.get("CODEX_HOME") or home / ".codex")
    codex_config = codex_dir / "config.toml"
    codex_registered = _codex_mcp_registered(codex_config)
    codex_skills = (codex_dir / "skills" / "local-ai-orchestrator" / "SKILL.md").is_file() or (
        home / ".agents" / "skills" / "local-ai-orchestrator" / "SKILL.md"
    ).is_file()

    gemini_home = Path(os.environ.get("GEMINI_CLI_HOME") or home / ".gemini")
    agy_cli = shutil.which("agy") or shutil.which("agy.cmd") or shutil.which("antigravity")
    agy_env_detected = bool(os.environ.get("ANTIGRAVITY_ENV") or os.environ.get("GEMINI_CLI_HOME"))
    agy_candidates = (
        gemini_home / "config" / "mcp_config.json",
        gemini_home / "mcp_config.json",
        gemini_home / "settings.json",
    )
    agy_config = next((candidate for candidate in agy_candidates if candidate.is_file() and not candidate.is_symlink()), None)
    agy_registered = any(_antigravity_mcp_registered(candidate) for candidate in agy_candidates if candidate.is_file() and not candidate.is_symlink())
    agy_skills = (gemini_home / "skills" / "local-ai-orchestrator" / "SKILL.md").is_file() or (
        gemini_home / "config" / "skills" / "local-ai-orchestrator" / "SKILL.md"
    ).is_file()
    agy_detected = bool(agy_cli) or agy_env_detected or agy_registered or agy_skills

    def describe_host(
        host_id: str, name: str, binary: str | None, detected: bool,
        registered: bool, skills: bool, config_path: Path | None,
    ) -> dict[str, Any]:
        # No handshake data is available from a static inspection; never fake it.
        status = "degraded" if detected else "not_installed"
        if not detected:
            remediation = "Host not detected. Install the host and configure its Local AI Hub MCP connection."
        elif not registered:
            remediation = "Host detected but Local AI Hub MCP is not registered in its host configuration."
        else:
            remediation = "MCP registered, live connectivity not verified. Run a host session handshake."
        return {
            "host_id": host_id,
            "display_name": name,
            "status": status,
            "detected_cli": _redact_path(binary) if binary else ("host configuration detected" if detected else None),
            "cli_installed": bool(binary),
            "mcp_config_path": _redact_path(config_path) if config_path and config_path.exists() else None,
            "mcp_registered": registered,
            "mcp_connection": "unverified" if registered else "not_configured",
            "skills_state": "installed" if skills else "missing",
            "handshake_verified": False,
            "last_handshake": None,
            "stale": False,
            "remediation": remediation,
            "version": None,
        }

    return {
        "success": True,
        "hosts": [
            describe_host(
                "codex", "Codex CLI", codex_cli,
                bool(codex_cli), codex_registered, codex_skills, codex_config,
            ),
            describe_host(
                "antigravity", "Antigravity IDE / CLI", agy_cli,
                agy_detected, agy_registered, agy_skills, agy_config,
            ),
        ],
        "observed_at": observed_at,
    }
