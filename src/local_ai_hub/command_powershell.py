"""PowerShell-specific command classification for the command broker."""

from typing import Any

from .command_policy import (
    _classification_result,
    POWERSHELL_DANGEROUS,
    POWERSHELL_MUTATING,
    POWERSHELL_READ_PREFIXES,
    POWERSHELL_VALIDATION_KEYWORDS,
    contains_user_whitelisted_tool,
)


def classify_powershell_command(
    command_text: str,
    config: dict[str, Any],
    extra_allowed: set[str],
) -> dict[str, Any]:
    """Classify recognized PowerShell commands using broker policy."""
    cmd_lower = command_text.lower()
    if any(d in cmd_lower for d in POWERSHELL_DANGEROUS):
        return _classification_result(
            "dangerous", cacheable=False, allowed=False,
            reason="dangerous or network powershell command",
        )

    if any(m in cmd_lower for m in POWERSHELL_MUTATING):
        return _classification_result(
            "mutating", cacheable=False,
            allowed=bool(config.get("allow_mutating", False)),
            reason="mutating powershell command",
        )

    if any(w in cmd_lower for w in POWERSHELL_VALIDATION_KEYWORDS):
        return _classification_result(
            "validation", cacheable=False,
            allowed=bool(config.get("allow_validation", True)),
            reason="powershell validation command", replay_safe=True,
        )
    if contains_user_whitelisted_tool(command_text, extra_allowed):
        return _classification_result(
            "validation", cacheable=False,
            allowed=bool(config.get("allow_validation", True)),
            reason="user-whitelisted powershell tool", replay_safe=False,
        )

    first_word = command_text.strip().split()[0].lower() if command_text.strip() else ""
    if any(first_word.startswith(p) or f" {p}" in cmd_lower for p in POWERSHELL_READ_PREFIXES):
        return _classification_result(
            "read", cacheable=False, allowed=bool(config.get("allow_read", True)),
            reason="powershell read command",
        )

    return _classification_result(
        "unknown", cacheable=False, allowed=False,
        reason="unrecognized powershell command",
    )
