"""PowerShell-specific command classification for the command broker."""

from typing import Any

from .command_policy import (
    POWERSHELL_DANGEROUS,
    POWERSHELL_MUTATING,
    POWERSHELL_READ_PREFIXES,
    POWERSHELL_VALIDATION_KEYWORDS,
)


def classify_powershell_command(
    command_text: str,
    config: dict[str, Any],
    extra_allowed: set[str],
) -> dict[str, Any]:
    """Classify recognized PowerShell commands using broker policy."""
    cmd_lower = command_text.lower()
    if any(d in cmd_lower for d in POWERSHELL_DANGEROUS):
        return {"class": "dangerous", "cacheable": False, "allowed": False, "reason": "dangerous or network powershell command"}

    if any(m in cmd_lower for m in POWERSHELL_MUTATING):
        return {"class": "mutating", "cacheable": False, "allowed": bool(config.get("allow_mutating", False)), "reason": "mutating powershell command"}

    if any(w in cmd_lower for w in POWERSHELL_VALIDATION_KEYWORDS):
        return {"class": "validation", "cacheable": False, "allowed": bool(config.get("allow_validation", True)), "replay_safe": True, "reason": "powershell validation command"}
    if any(w in cmd_lower for w in extra_allowed):
        return {"class": "validation", "cacheable": False, "allowed": bool(config.get("allow_validation", True)), "replay_safe": False, "reason": "user-whitelisted powershell tool"}

    first_word = command_text.strip().split()[0].lower() if command_text.strip() else ""
    if any(first_word.startswith(p) or f" {p}" in cmd_lower for p in POWERSHELL_READ_PREFIXES):
        return {"class": "read", "cacheable": False, "allowed": bool(config.get("allow_read", True)), "reason": "powershell read command"}

    return {"class": "unknown", "cacheable": False, "allowed": False, "reason": "unrecognized powershell command"}
