from __future__ import annotations

from collections.abc import Callable
import logging
from pathlib import Path
import subprocess
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
    names = {
        str(name).replace("\x00", "").strip()
        for name in direct
        if str(name or "").replace("\x00", "").strip()
    } if isinstance(direct, list) else set()
    if names:
        return names
    try:
        if runtime_factory is None:
            from .ollama import OllamaRuntime
            runtime_factory = OllamaRuntime
        runtime = runtime_factory(cfg or {})
        return {
            str(name).replace("\x00", "").strip()
            for name in runtime.installed_models()
            if str(name or "").replace("\x00", "").strip()
        }
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
    if not isinstance(install_dir, (str, Path)) or "\x00" in str(install_dir):
        return command_lookup("serena")
    try:
        root = Path(install_dir)
        candidates = (
            root / "tool-envs" / "serena" / "Scripts" / "serena.exe",
            root / "tool-envs" / "serena" / "bin" / "serena",
        )
        managed = next((candidate for candidate in candidates if candidate.is_file()), None)
        return str(managed) if managed is not None else command_lookup("serena")
    except (OSError, RuntimeError, ValueError):
        return command_lookup("serena")


def serena_backend_status(status: dict[str, Any]) -> dict[str, Any] | None:
    """Expose only Serena details from Hub code-intelligence diagnostics."""
    diagnostics = status.get("code_intelligence") if isinstance(status, dict) else None
    if not isinstance(diagnostics, dict):
        return None
    serena = diagnostics.get("serena")
    return {"serena": serena} if isinstance(serena, dict) else None


def _git_hooks_directory(repo_root: Path) -> Path | None:
    """Resolve Git's active hook directory, including linked worktrees."""
    from .process_utils import run_hidden

    try:
        if not repo_root.is_dir():
            return None
        result = run_hidden(
            ["git", "rev-parse", "--git-path", "hooks"],
            cwd=str(repo_root),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        LOGGER.warning("doctor git hooks path discovery failed error_type=%s", type(exc).__name__)
        return None
    if result.returncode != 0:
        return None
    path_text = str(result.stdout or "").strip()
    if not path_text or "\x00" in path_text:
        return None
    try:
        hooks_dir = Path(path_text)
        if not hooks_dir.is_absolute():
            hooks_dir = repo_root / hooks_dir
        return hooks_dir.resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def probe_hub_status(client: Any, *, timeout: float = 15.0) -> dict[str, Any]:
    """Keep a healthy hub distinct from an unavailable diagnostic status payload."""
    if client is None:
        return {
            "hub_online": False,
            "status_available": False,
            "status": {},
            "code_intelligence_status": {"available": False, "reason": "hub_offline"},
        }
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
    if not isinstance(repo_root, (str, Path)) or "\x00" in str(repo_root):
        return {"success": False, "error": f"invalid repository root: {repo_root!r}"}
    try:
        p_root = Path(repo_root).resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        return {"success": False, "error": f"invalid repository root: {exc}"}
    hooks_dir = _git_hooks_directory(p_root)
    if hooks_dir is None:
        return {"success": False, "error": f"not a git repository: {p_root}"}
    try:
        hooks_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {"success": False, "error": f"cannot create hooks directory: {exc}"}

    hook_file = hooks_dir / "pre-commit"
    hook_script = """#!/bin/sh
set -e
# Local AI Hub automated pre-commit hook
echo "[local-ai-hub] Running fast pre-commit checks..."
python -m compileall -q src tools tests 2>/dev/null
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
    if not isinstance(repo_root, (str, Path)) or "\x00" in str(repo_root):
        return {"success": False, "error": f"invalid repository root: {repo_root!r}"}
    try:
        p_root = Path(repo_root).resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        return {"success": False, "error": f"invalid repository root: {exc}"}
    hooks_dir = _git_hooks_directory(p_root)
    if hooks_dir is None:
        return {"success": True, "removed": False, "message": "hook not present"}
    hook_file = hooks_dir / "pre-commit"
    if not hook_file.exists():
        return {"success": True, "removed": False, "message": "hook not present"}
    try:
        hook_file.unlink()
        return {"success": True, "removed": True, "hook_path": str(hook_file)}
    except Exception as exc:
        return {"success": False, "error": f"failed to remove hook: {exc}"}


def is_git_precommit_hook_installed(repo_root: str | Path) -> bool:
    """Return True if Local AI Hub pre-commit hook is installed in repo."""
    if not isinstance(repo_root, (str, Path)) or "\x00" in str(repo_root):
        return False
    try:
        p_root = Path(repo_root).resolve()
        hooks_dir = _git_hooks_directory(p_root)
        if hooks_dir is None:
            return False
        hook_file = hooks_dir / "pre-commit"
        if not hook_file.is_file():
            return False
        content = hook_file.read_text(encoding="utf-8", errors="replace")
        return "local-ai-hub" in content.lower()
    except Exception:
        return False


def format_doctor_summary(probe_result: dict[str, Any]) -> str:
    """Format a one-line summary from probe_hub_status output."""
    if not isinstance(probe_result, dict):
        return "Hub status unknown"
    online = probe_result.get("hub_online", False)
    status_avail = probe_result.get("status_available", False)
    code_intel = probe_result.get("code_intelligence_status", {})
    intel_state = (
        "available" if code_intel.get("available")
        else f"degraded ({code_intel.get('reason', 'unknown')})"
    )
    if online:
        status_desc = "online" if status_avail else "online (limited status)"
        return f"Local AI Hub is {status_desc}; code intelligence is {intel_state}"
    return f"Local AI Hub is offline ({code_intel.get('reason', 'offline')})"
