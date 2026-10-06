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


def resolve_project_context(root: str | Path, state_dir: str | Path) -> Any | None:
    api = project_config_api()
    if api is None:
        return None
    return api.resolve_project_context(root, state_dir)


def phase_allowed(project_context: Any | None, phase: str) -> bool:
    if project_context is None:
        return True
    api = project_config_api()
    return True if api is None else bool(api.phase_is_allowed(project_context.settings, phase))


def custom_extension_kind(project_context: Any | None, path: str | Path) -> str | None:
    if project_context is None:
        return None
    api = project_config_api()
    return None if api is None else api.custom_extension_kind(Path(path).name, project_context.settings)


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
    if project_context is None:
        return True, None
    api = project_config_api()
    if api is None:
        return True, None
    kind = api.custom_extension_kind(Path(path).name, project_context.settings)
    allowed = api.path_is_allowed(
        root,
        path,
        project_context.settings,
        phase=phase,
        soft_ignored=soft_ignored,
        hard_denied=hard_denied,
        binary=kind == "binary",
        size_bytes=size_bytes,
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
    if project_context is None:
        return not hard_denied
    api = project_config_api()
    if api is None:
        return not hard_denied
    return bool(api.may_descend(
        root,
        directory,
        project_context.settings,
        phase=phase,
        soft_ignored=soft_ignored,
        hard_denied=hard_denied,
    ))
