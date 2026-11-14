"""Command-name helpers for identifying safe validation executables."""

from __future__ import annotations

import ntpath
from collections.abc import Iterable
from typing import Any

from .command_policy import _classification_result


PHP_VALIDATORS = frozenset({"phpunit", "phpstan", "pest"})
FORMATTER_EXECUTABLES = frozenset({"black", "isort"})


def classify_php_validation_script(
    script_path: str, config: dict[str, Any]
) -> dict[str, Any] | None:
    """Classify a PHP validator invoked as a script path."""
    script_name = ntpath.basename(script_path.replace("/", "\\"))
    return classify_validation_tool(
        script_name, PHP_VALIDATORS, config, "PHP validation tool"
    )


def is_validation_executable(executable_name: str, validator_names: Iterable[str]) -> bool:
    """Match a validator name or its numeric hyphenated version suffix."""
    if not isinstance(executable_name, str):
        return False

    for validator_name in validator_names:
        if executable_name == validator_name:
            return True
        prefix = f"{validator_name}-"
        if not executable_name.startswith(prefix):
            continue
        version_parts = executable_name[len(prefix) :].split(".")
        if version_parts and all(
            part.isascii() and part.isdigit() for part in version_parts
        ):
            return True

    return False


def _validation_classification(
    config: dict[str, Any], reason: str
) -> dict[str, Any]:
    return _classification_result(
        "validation", cacheable=True,
        allowed=bool(config.get("allow_validation", True)),
        replay_safe=True, reason=reason,
    )


def classify_validation_tool(
    executable_name: str,
    validator_names: Iterable[str],
    config: dict[str, Any],
    reason: str,
) -> dict[str, Any] | None:
    if not is_validation_executable(executable_name, validator_names):
        return None

    return _validation_classification(config, reason)


def classify_formatter_command(
    executable_name: str, arguments: Iterable[str], config: dict[str, Any]
) -> dict[str, Any] | None:
    if executable_name not in FORMATTER_EXECUTABLES:
        return None

    if any(flag in arguments for flag in {"--check", "--diff"}):
        return _validation_classification(config, f"{executable_name} check")

    return _classification_result(
        "mutating", cacheable=False,
        allowed=bool(config.get("allow_mutating", False)),
        reason=f"{executable_name} format without --check",
    )
