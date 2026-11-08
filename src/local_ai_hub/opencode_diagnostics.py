"""Read-only component hints; never infer OpenCode runtime acceptance."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .opencode_hardware import inspect_opencode_hardware


def inspect_components(cfg: dict[str, Any], hardware: dict[str, Any], install_root: Path,
                       executable: Path | None, expected_digest: str, installed: set[str]) -> dict[str, Any]:
    profile = inspect_opencode_hardware(hardware)
    verified = False
    try:
        if executable is not None and not executable.is_symlink() and executable.is_file() and executable.stat().st_size <= 400 * 1024 * 1024:
            digest = hashlib.sha256()
            with executable.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            verified = digest.hexdigest() == expected_digest
    except OSError:
        pass
    security = cfg.get("security", {})
    api_auth_configured = isinstance(security, dict) and bool(security.get("api_token"))
    candidates = profile["candidates"]
    return {
        "hardware_profile": profile["profile"],
        "executable_verified": verified,
        "goal_plugin_present": (install_root / "tools" / "opencode_goal" / "index.js").is_file(),
        "hub_api_auth_configured": api_auth_configured,
        "available_candidates": [name for name in candidates if name in installed] if installed else None,
        "inventory_source": "doctor status or local runtime" if installed else "unavailable_or_empty",
        "runtime_verified": False,
        "ready": False,
        "reason": "runtime and local-only acceptance not verified",
    }
