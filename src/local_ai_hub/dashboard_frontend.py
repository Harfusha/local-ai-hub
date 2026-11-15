"""Offline static dashboard shell, allow-listed assets, and host diagnostics (HUB-093)."""

from __future__ import annotations

import os
import shutil
import time
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
    if not path:
        return None
    p_str = str(path)
    home = str(Path.home())
    if p_str.startswith(home):
        return "~" + p_str[len(home):]
    return p_str


def inspect_agent_hosts(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Inspect installed agent host CLI binaries, MCP registration, and handshake state (HUB-093).

    Truthful reporting: never reports a host as ready if the CLI binary is missing
    or MCP is unconfigured.
    """
    hosts_report: list[dict[str, Any]] = []
    now = time.time()

    # 1. Codex CLI inspection
    codex_bin = shutil.which("codex") or shutil.which("codex.cmd")
    codex_home = os.environ.get("CODEX_HOME")
    codex_mcp_path: Path | None = None
    if codex_home:
        candidate = Path(codex_home) / "config.json"
        if candidate.exists():
            codex_mcp_path = candidate
    if codex_mcp_path is None:
        default_codex = Path.home() / ".codex" / "config.json"
        if default_codex.exists():
            codex_mcp_path = default_codex

    codex_mcp_registered = False
    if codex_mcp_path is not None and codex_mcp_path.exists():
        try:
            txt = codex_mcp_path.read_text(encoding="utf-8", errors="ignore")
            codex_mcp_registered = "local-ai" in txt
        except Exception:
            codex_mcp_registered = False

    codex_status = "not_installed"
    codex_remediation = "Install Codex CLI via official installer or package manager."
    if codex_bin:
        if codex_mcp_registered:
            codex_status = "ready"
            codex_remediation = "Codex CLI is installed and configured with Local AI Hub MCP."
        else:
            codex_status = "degraded"
            codex_remediation = "Codex CLI is installed, but Local AI Hub MCP is not configured in ~/.codex/config.json."

    hosts_report.append({
        "host_id": "codex",
        "display_name": "Codex CLI",
        "status": codex_status,
        "detected_cli": _redact_path(codex_bin),
        "version": None,
        "mcp_config_path": _redact_path(codex_mcp_path),
        "mcp_registered": codex_mcp_registered,
        "skills_state": "installed" if codex_mcp_registered else "missing",
        "last_handshake": None,
        "stale": False,
        "remediation": codex_remediation,
    })

    # 2. Antigravity IDE / CLI inspection
    agy_bin = shutil.which("agy") or shutil.which("agy.cmd") or shutil.which("antigravity")
    agy_env = os.environ.get("ANTIGRAVITY_ENV") or os.environ.get("GEMINI_CLI_HOME")
    agy_mcp_path: Path | None = None

    # Check known Antigravity MCP paths
    candidates = [
        Path.home() / ".gemini" / "antigravity" / "mcp" / "local-ai",
        Path.home() / ".gemini" / "antigravity" / "mcp_config.json",
        Path.home() / ".gemini" / "settings.json",
    ]
    for c in candidates:
        if c.exists():
            agy_mcp_path = c
            break

    agy_mcp_registered = False
    if agy_mcp_path is not None:
        try:
            if agy_mcp_path.is_dir():
                agy_mcp_registered = (agy_mcp_path / "instructions.md").exists() or any(agy_mcp_path.glob("*.json"))
            else:
                txt = agy_mcp_path.read_text(encoding="utf-8", errors="ignore")
                agy_mcp_registered = "local-ai" in txt
        except Exception:
            agy_mcp_registered = False

    agy_status = "not_installed"
    agy_remediation = "Install Antigravity IDE or CLI."
    if agy_bin or agy_env:
        if agy_mcp_registered:
            agy_status = "ready"
            agy_remediation = "Antigravity is configured with Local AI Hub MCP."
        else:
            agy_status = "degraded"
            agy_remediation = "Antigravity detected, but Local AI Hub MCP registration is missing."

    hosts_report.append({
        "host_id": "antigravity",
        "display_name": "Antigravity IDE / CLI",
        "status": agy_status,
        "detected_cli": _redact_path(agy_bin) if agy_bin else ("env:" + str(agy_env) if agy_env else None),
        "version": None,
        "mcp_config_path": _redact_path(agy_mcp_path),
        "mcp_registered": agy_mcp_registered,
        "skills_state": "installed" if agy_mcp_registered else "missing",
        "last_handshake": now if agy_env else None,
        "stale": False,
        "remediation": agy_remediation,
    })

    return {
        "success": True,
        "hosts": hosts_report,
        "observed_at": now,
    }
