"""Conservative classification for read-only command tools."""
from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from typing import Any

from .command_policy import _classification_result

def _blocked_unknown(reason: str) -> dict[str, Any]:
    return _classification_result(
        "unknown", cacheable=False, allowed=False, reason=reason
    )


def classify_read_only_command(
    exe_base: str,
    lower: Sequence[str],
    cfg: Mapping[str, Any],
    *,
    read_only: Collection[str],
    volatile_reads: Collection[str],
) -> dict[str, Any] | None:
    """Return a classification for an allowed read tool, or None when unmatched."""
    if exe_base not in read_only or exe_base == "git":
        return None

    if exe_base in {"rg", "ripgrep"} and any(
        flag == "--pre" or flag.startswith("--pre=") for flag in lower
    ):
        return _blocked_unknown("ripgrep preprocessor may execute arbitrary programs")
    if exe_base == "find" and any(
        flag in {"-exec", "-execdir", "-ok", "-okdir", "-delete"} for flag in lower
    ):
        return _blocked_unknown("find execution flags are not allowed")

    return _classification_result(
        "read", cacheable=exe_base not in volatile_reads,
        allowed=bool(cfg.get("allow_read", True)),
        reason=f"{exe_base} read command",
    )
