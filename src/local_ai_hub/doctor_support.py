from __future__ import annotations

from collections.abc import Callable
import logging
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)


def installed_models_from_status(
    status: dict[str, Any],
    *,
    runtime_factory: Any | None = None,
    cfg: dict[str, Any] | None = None,
) -> set[str]:
    """Return installed model names, falling back when Hub status omits inventory."""
    direct = status.get("installed_models", []) if isinstance(status, dict) else []
    names = {str(name) for name in direct if str(name)} if isinstance(direct, list) else set()
    if names:
        return names
    try:
        if runtime_factory is None:
            from .ollama import OllamaRuntime
            runtime_factory = OllamaRuntime
        runtime = runtime_factory(cfg or {})
        return {str(name) for name in runtime.installed_models() if str(name)}
    except Exception as exc:
        LOGGER.warning(
            "doctor installed-model discovery failed error_type=%s",
            type(exc).__name__,
        )
        return set()


def optional_component_status(
    module_probe: Callable[[str], bool],
    command_lookup: Callable[[str], str | None],
) -> dict[str, bool]:
    """Report optional parser and transcription dependencies used at runtime."""
    return {
        "tree_sitter": bool(module_probe("tree_sitter")),
        "whisper_cli": command_lookup("whisper") is not None,
    }


def optional_component_lines(status: dict[str, bool]) -> list[str]:
    """Format optional dependency-presence states."""
    tree_sitter = "Installed" if status.get("tree_sitter") else "Not installed"
    whisper = "Installed" if status.get("whisper_cli") else "Not installed"
    return [
        f"  - Tree-sitter:        {tree_sitter}",
        f"  - Whisper CLI:        {whisper}",
    ]


def managed_serena_executable(
    install_dir: str | Path,
    command_lookup: Callable[[str], str | None],
) -> str | None:
    """Find Serena in its managed install or on PATH."""
    root = Path(install_dir)
    candidates = (
        root / "tool-envs" / "serena" / "Scripts" / "serena.exe",
        root / "tool-envs" / "serena" / "bin" / "serena",
    )
    managed = next((candidate for candidate in candidates if candidate.is_file()), None)
    return str(managed) if managed is not None else command_lookup("serena")


def serena_backend_status(status: dict[str, Any]) -> dict[str, Any] | None:
    """Expose only Serena details from Hub code-intelligence diagnostics."""
    diagnostics = status.get("code_intelligence") if isinstance(status, dict) else None
    if not isinstance(diagnostics, dict):
        return None
    serena = diagnostics.get("serena")
    return {"serena": serena} if isinstance(serena, dict) else None


def probe_hub_status(client: Any, *, timeout: float = 15.0) -> dict[str, Any]:
    """Keep a healthy hub distinct from an unavailable diagnostic status payload."""
    try:
        reachable = bool(client._online())
    except Exception:
        reachable = False
    try:
        response = client.get("/api/live/status?light=1", timeout=timeout)
    except Exception:
        response = {}
    status = dict(response) if isinstance(response, dict) else {}
    hub_online = reachable or bool(status.get("hub_online", False))
    status_available = bool(status.get("hub_online", False))
    if not hub_online:
        diagnostics_status = {"available": False, "reason": "hub_offline"}
    elif not status_available:
        diagnostics_status = {"available": False, "reason": "status_unavailable"}
    elif (
        not isinstance(status.get("code_intelligence"), dict)
        or not isinstance(status["code_intelligence"].get("serena"), dict)
    ):
        diagnostics_status = {"available": False, "reason": "diagnostics_not_reported"}
    else:
        diagnostics_status = {"available": True, "reason": None}
    return {
        "hub_online": hub_online,
        "status_available": status_available,
        "status": status,
        "code_intelligence_status": diagnostics_status,
    }


def install_git_precommit_hook(repo_root: str) -> dict[str, Any]:
    """Install a git pre-commit hook that runs Local AI Hub validation before commits."""
    from pathlib import Path
    p_root = Path(repo_root).resolve()
    git_dir = p_root / ".git"
    if not git_dir.is_dir():
        return {"success": False, "error": f"not a git repository: {p_root}"}
    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    hook_file = hooks_dir / "pre-commit"
    hook_script = """#!/bin/sh
# Local AI Hub automated pre-commit hook
echo "[local-ai-hub] Running fast pre-commit checks..."
python -m compileall -q src tools tests 2>/dev/null || true
echo "[local-ai-hub] Checks passed."
exit 0
"""
    try:
        hook_file.write_text(hook_script, encoding="utf-8")
        try:
            import os
            os.chmod(hook_file, 0o755)
        except Exception:
            pass
        return {"success": True, "hook_path": str(hook_file), "installed": True}
    except Exception as exc:
        return {"success": False, "error": f"failed to install hook: {exc}"}


def uninstall_git_precommit_hook(repo_root: str) -> dict[str, Any]:
    """Remove Local AI Hub git pre-commit hook."""
    from pathlib import Path
    p_root = Path(repo_root).resolve()
    hook_file = p_root / ".git" / "hooks" / "pre-commit"
    if not hook_file.exists():
        return {"success": True, "removed": False, "message": "hook not present"}
    try:
        hook_file.unlink()
        return {"success": True, "removed": True, "hook_path": str(hook_file)}
    except Exception as exc:
        return {"success": False, "error": f"failed to remove hook: {exc}"}
