"""Pure environment-key policy for project command execution."""

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

PROJECT_COMMAND_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PROJECT_COMMAND_ENV_BLOCKED = frozenset(
    {
        "BASH_ENV",
        "COMSPEC",
        "ENV",
        "GIT_COMMON_DIR",
        "GIT_DIR",
        "GIT_INDEX_FILE",
        "GIT_PREFIX",
        "GIT_WORK_TREE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "LD_AUDIT",
        "LD_LIBRARY_PATH",
        "LD_PRELOAD",
        "DYLD_FRAMEWORK_PATH",
        "DYLD_INSERT_LIBRARIES",
        "DYLD_LIBRARY_PATH",
        "PATH",
        "PATHEXT",
        "SHELL",
    }
)


def is_unsafe_project_command_env_key(key: str) -> bool:
    normalized = key.upper()
    return normalized in PROJECT_COMMAND_ENV_BLOCKED or normalized.startswith("GIT_CONFIG_")


def is_valid_project_command_env_key(key: object) -> bool:
    return (
        isinstance(key, str)
        and PROJECT_COMMAND_ENV_KEY_RE.fullmatch(key) is not None
        and not is_unsafe_project_command_env_key(key)
    )


def resolve_project_environment(
    project_context: Any | None,
    cwd: str,
    *,
    host_environment: Mapping[str, str],
    max_entries: int,
    max_bytes: int,
) -> tuple[str, dict[str, str], str | None]:
    if project_context is None:
        return "", {}, None
    try:
        config_digest = project_context.config_digest
        context_root = Path(project_context.root).expanduser().resolve(strict=False)
        command_root = Path(cwd).expanduser().resolve(strict=False)
        environment_refs = project_context.settings.env_references
    except (AttributeError, OSError, TypeError, ValueError):
        return "", {}, "project context is invalid"
    if not isinstance(config_digest, str) or not config_digest or not isinstance(environment_refs, Mapping):
        return "", {}, "project context is invalid"
    try:
        command_root.relative_to(context_root)
    except ValueError:
        return "", {}, "command working directory is outside the project context"

    environment: dict[str, str] = {}
    if len(environment_refs) > max_entries:
        return "", {}, "project environment configuration is invalid"
    environment_size = 0
    for child_name, parent_name in environment_refs.items():
        if not isinstance(child_name, str) or not isinstance(parent_name, str):
            return "", {}, "project environment configuration is invalid"
        if (
            not is_valid_project_command_env_key(child_name)
            or not PROJECT_COMMAND_ENV_KEY_RE.fullmatch(parent_name)
        ):
            return "", {}, "project environment configuration is invalid"
        if not child_name or "=" in child_name or "\0" in child_name or not parent_name or "=" in parent_name or "\0" in parent_name:
            return "", {}, "project environment configuration is invalid"
        if parent_name not in host_environment:
            return "", {}, "configured project environment source is unavailable"
        environment[child_name] = host_environment[parent_name]
        environment_size += len(child_name.encode("utf-8")) + len(environment[child_name].encode("utf-8"))
        if "\x00" in environment[child_name] or environment_size > max_bytes:
            return "", {}, "project environment configuration is invalid"
    return config_digest, environment, None
