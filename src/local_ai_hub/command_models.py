"""Shared typed models for command invocation and project configuration."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class CommandInvocation:
    """Validated subprocess input that cannot request shell interpretation."""

    argv: list[str]
    cwd: str | None = None
    shell: bool = False


class _ProjectSettingsLike(Protocol):
    env_references: Mapping[str, str]


class ProjectContextLike(Protocol):
    root: str | Path
    config_digest: str
    settings: _ProjectSettingsLike


@dataclass(frozen=True)
class _ResolvedProjectCommand:
    alias: str
    command: str | CommandInvocation
    environment: dict[str, str]
    config_digest: str
    cache_context: str
    configured_command: str | CommandInvocation
    caller_arguments: tuple[str, ...]
