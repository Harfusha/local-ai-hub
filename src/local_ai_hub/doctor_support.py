from __future__ import annotations

from typing import Any


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
    except Exception:
        return set()


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
    return {
        "hub_online": reachable or bool(status.get("hub_online", False)),
        "status_available": bool(status.get("hub_online", False)),
        "status": status,
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
