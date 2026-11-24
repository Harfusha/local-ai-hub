"""ClientRegistry — detection, registration, and resolution of client adapters."""
from __future__ import annotations

import os
from typing import Any
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import BaseClientAdapter

_REGISTRY: dict[str, type["BaseClientAdapter"]] = {}
_DEFAULT_ADAPTERS_LOADED = False

_ENV_DETECTION_ORDER: list[tuple[str, str]] = [
    ("DEVIN_PROJECT_DIR",        "devin"),
    ("DEVIN_SESSION_ID",         "devin"),
    ("ANTIGRAVITY_ENV",         "antigravity"),
    ("CODEX_HOME",              "codex"),
    ("CODEX_ENV",               "codex"),
    ("CLAUDE_ENV",              "claude"),
    ("CLAUDE_BASE_DIR",         "claude"),
    ("OPENCODE_SESSION",        "opencode"),
    ("OPENCODE_ENV",            "opencode"),
    ("CURSOR_PROJECT_DIR",      "cursor"),
    ("CURSOR_ENV",              "cursor"),
    ("WINDSURF_ENV",            "windsurf"),
    ("VSCODE_CWD",              "vscode"),
    ("VSCODE_GIT_IPC_HANDLE",   "vscode"),
    ("GITHUB_COPILOT_SESSION",  "vscode"),
    ("GEMINI_CLI_HOME",         "gemini_cli"),
]

_HEADER_PREFIX_MAP: dict[str, str] = {
    "devin":       "devin",
    "antigravity": "antigravity",
    "codex":       "codex",
    "claude":      "claude",
    "opencode":    "opencode",
    "cursor":      "cursor",
    "windsurf":    "windsurf",
    "vscode":      "vscode",
    "copilot":     "vscode",
    "gemini":      "gemini_cli",
    "gemini_cli":  "gemini_cli",
}


def register_adapter(client_id: str, adapter_cls: type["BaseClientAdapter"]) -> None:
    """Register an adapter class under its canonical identifier."""
    _REGISTRY[client_id] = adapter_cls


def _ensure_default_adapters() -> None:
    global _DEFAULT_ADAPTERS_LOADED
    if _DEFAULT_ADAPTERS_LOADED:
        return
    _DEFAULT_ADAPTERS_LOADED = True
    try:
        from .adapters import (
            antigravity,
            claude,
            codex,
            cursor,
            devin,
            gemini_cli,
            generic_mcp,
            opencode,
            vscode,
        )
        _ = (
            antigravity,
            claude,
            codex,
            cursor,
            devin,
            gemini_cli,
            generic_mcp,
            opencode,
            vscode,
        )
    except ImportError:
        pass


def detect_client_from_header(agent_header: str | None) -> str | None:
    """Detect client from X-LocalAI-Agent HTTP header."""
    if not isinstance(agent_header, str) or not agent_header.strip():
        return None
    raw_prefix = agent_header.split("/")[0].split("-")[0].lower().strip()
    return _HEADER_PREFIX_MAP.get(raw_prefix)


def detect_client_from_env() -> str:
    """Detect client from environment variables."""
    for env_var, client_id in _ENV_DETECTION_ORDER:
        if os.environ.get(env_var):
            return client_id
    return "generic_mcp"


def detect_client(agent_header: str | None = None) -> str:
    """Detect the active client, prioritizing explicit request header over environment."""
    from_header = detect_client_from_header(agent_header)
    if from_header:
        return from_header
    return detect_client_from_env()


def get_adapter(
    client_id: str | None = None,
    agent_header: str | None = None,
) -> "BaseClientAdapter":
    """Resolve and instantiate the appropriate client adapter."""
    _ensure_default_adapters()
    resolved_id = client_id or detect_client(agent_header)
    adapter_cls = _REGISTRY.get(resolved_id) or _REGISTRY.get("generic_mcp")
    if adapter_cls is None:
        from .adapters.generic_mcp import GenericMcpAdapter
        return GenericMcpAdapter()
    return adapter_cls()


class ClientRegistry:
    """Static facade for client adapter inspection and lookup."""

    @staticmethod
    def all_clients() -> list[str]:
        _ensure_default_adapters()
        return sorted(_REGISTRY.keys())

    @staticmethod
    def list_adapters() -> list[str]:
        return ClientRegistry.all_clients()

    @staticmethod
    def get(client_id: str | None = None, agent_header: str | None = None) -> "BaseClientAdapter":
        return get_adapter(client_id, agent_header)

    @staticmethod
    def detect(agent_header: str | None = None, repo_root: Any = None) -> str:
        res = detect_client(agent_header)
        if res == "generic_mcp" and repo_root is not None:
            try:
                from local_ai_hub.repo_plan.host_adapters import detect_host_environment
                host = detect_host_environment(repo_root=str(repo_root))
                if host and host in _REGISTRY:
                    return host
            except Exception:
                pass
        return res
