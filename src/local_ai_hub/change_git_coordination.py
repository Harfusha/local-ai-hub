"""Use the same server-derived coordination namespace as Agent OS."""
from __future__ import annotations

from typing import Any

from .project_config import resolve_project_context
from .state_paths import configured_state_dir


def git_coordination_id(config: dict[str, Any], root: str) -> str:
    context = resolve_project_context(root, configured_state_dir(config))
    identity = context.coordination_id
    if not isinstance(identity, str) or not identity:
        raise ValueError("Repository coordination identity unavailable")
    return identity
