from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType
from typing import Any


_PROJECT_CONFIG_MODULE = "local_ai_hub.project_config"


def project_config_api() -> ModuleType | None:
    """Load project policy lazily for worktrees that include its core module."""
    try:
        return importlib.import_module(_PROJECT_CONFIG_MODULE)
    except ModuleNotFoundError as exc:
        if exc.name == _PROJECT_CONFIG_MODULE:
            return None
        raise


def is_available() -> bool:
    """Check if project policy configuration API is available."""
    return project_config_api() is not None


def resolve_project_context(root: str | Path, state_dir: str | Path) -> Any | None:
    if not root or not state_dir:
        return None
    root_str = str(root)
    state_str = str(state_dir)
    if "\x00" in root_str or "\x00" in state_str:
        return None
    api = project_config_api()
    if api is None:
        return None
    return api.resolve_project_context(root, state_dir)


def phase_allowed(project_context: Any | None, phase: str) -> bool:
    if project_context is None:
        return True
    settings = getattr(project_context, "settings", None)
    if settings is None:
        return True
    phase_str = str(phase or "").strip()
    if not phase_str or "\x00" in phase_str:
        return False
    api = project_config_api()
    return True if api is None else bool(api.phase_is_allowed(settings, phase_str))


def custom_extension_kind(project_context: Any | None, path: str | Path) -> str | None:
    if project_context is None:
        return None
    settings = getattr(project_context, "settings", None)
    if settings is None:
        return None
    path_str = str(path or "")
    if not path_str or "\x00" in path_str:
        return None
    api = project_config_api()
    return None if api is None else api.custom_extension_kind(Path(path_str).name, settings)


def path_allowed(
    root: str | Path,
    path: str | Path,
    project_context: Any | None,
    *,
    phase: str,
    size_bytes: int | None = None,
    soft_ignored: bool = False,
    hard_denied: bool = False,
) -> tuple[bool, str | None]:
    root_str = str(root or "")
    path_str = str(path or "")
    if "\x00" in root_str or "\x00" in path_str:
        return False, None
    if project_context is None:
        return True, None
    settings = getattr(project_context, "settings", None)
    if settings is None:
        return True, None
    api = project_config_api()
    if api is None:
        return True, None
    kind = api.custom_extension_kind(Path(path_str).name, settings)

    clean_size: int | None = None
    if size_bytes is not None and not isinstance(size_bytes, bool):
        try:
            val = int(size_bytes)
            clean_size = max(0, val)
        except (ValueError, TypeError):
            clean_size = None

    allowed = api.path_is_allowed(
        root,
        path,
        settings,
        phase=str(phase or "").strip(),
        soft_ignored=soft_ignored,
        hard_denied=hard_denied,
        binary=kind == "binary",
        size_bytes=clean_size,
    )
    return bool(allowed), kind


def may_descend(
    root: str | Path,
    directory: str | Path,
    project_context: Any | None,
    *,
    phase: str,
    soft_ignored: bool = False,
    hard_denied: bool = False,
) -> bool:
    root_str = str(root or "")
    dir_str = str(directory or "")
    if "\x00" in root_str or "\x00" in dir_str:
        return False
    if project_context is None:
        return not hard_denied
    settings = getattr(project_context, "settings", None)
    if settings is None:
        return not hard_denied
    api = project_config_api()
    if api is None:
        return not hard_denied
    return bool(api.may_descend(
        root,
        directory,
        settings,
        phase=str(phase or "").strip(),
        soft_ignored=soft_ignored,
        hard_denied=hard_denied,
    ))
