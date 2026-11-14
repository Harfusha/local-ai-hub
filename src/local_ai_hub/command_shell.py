"""Safety checks for shell syntax accepted by the command broker."""

from __future__ import annotations

import os
import re
import shlex
from collections.abc import Sequence

from .command_policy import _classification_result


def strip_null_redirections(command: str) -> str:
    """Remove broker-supported null-output suffixes from a command string."""
    stripped = re.sub(
        r"\s*(?:2>&1|2>\s*(?:/dev/null|nul|\$null)|>\s*(?:/dev/null|nul|\$null)|\|\s*Out-Null)\s*$",
        "",
        command,
        flags=re.IGNORECASE,
    )
    return stripped.strip()


def is_powershell_command(command: str) -> bool:
    """Recognize PowerShell expressions and common cmdlet prefixes."""
    trimmed = command.strip()
    if trimmed.startswith(("$", "&")):
        return True
    ps_prefixes = (
        "get-", "set-", "test-", "invoke-", "start-", "stop-", "select-", "format-",
        "where-", "out-", "new-", "remove-", "clear-", "write-", "read-", "measure-",
        "compare-", "convertfrom-", "convertto-", "add-type",
    )
    first = trimmed.split()[0].lower() if trimmed.split() else ""
    return any(first.startswith(prefix) for prefix in ps_prefixes)


def needs_shell(command: str) -> bool:
    """Return whether command syntax requires a shell wrapper."""
    trimmed = command.strip()
    if is_powershell_command(trimmed):
        return True
    sequence = split_shell_command(trimmed, (";", "&&", "||", "|", ">", "<"))
    if len(sequence) > 1:
        return True
    return any(operator in trimmed for operator in ("2>&1", "| Out-Null", "| out-null", ">nul", "> nul"))


def tokenize_command(command: str) -> list[str]:
    """Tokenize using native Windows argv rules or POSIX shell quoting."""
    try:
        if os.name == "nt":
            from .windows_argv import parse_windows_command_line

            return parse_windows_command_line(command)
        return shlex.split(command, posix=True)
    except (OSError, ValueError):
        return []


def classify_raw_shell_subshell(
    command: str | Sequence[str], *, structured: bool
) -> dict[str, object] | None:
    """Reject unquoted shell subshell syntax in raw command strings."""
    if structured:
        return None

    unquoted = re.sub(r'("[^"]*"|\'[^\']*\')', "", command)
    if any(operator in unquoted for operator in ("`", "$(")):
        return _classification_result(
            "unknown", cacheable=False, allowed=False,
            reason="shell subshells are not accepted",
        )
    return None


def split_shell_command(
    command: str, delimiters: tuple[str, ...]
) -> list[tuple[str, str]]:
    """Split on delimiters outside quotes, preserving each preceding delimiter."""
    parts = []
    current = []
    in_quote = False
    quote_char = ""
    i = 0
    n = len(command)
    last_delim = ""
    while i < n:
        char = command[i]
        if in_quote:
            current.append(char)
            if char == quote_char:
                in_quote = False
            i += 1
            continue
        if char in ('"', "'"):
            in_quote = True
            quote_char = char
            current.append(char)
            i += 1
            continue
        matched_delim = None
        for delimiter in delimiters:
            if command[i : i + len(delimiter)] == delimiter:
                matched_delim = delimiter
                break
        if matched_delim:
            parts.append((last_delim, "".join(current).strip()))
            current = []
            last_delim = matched_delim
            i += len(matched_delim)
        else:
            current.append(char)
            i += 1
    if current or last_delim:
        parts.append((last_delim, "".join(current).strip()))
    return [(delimiter, part) for delimiter, part in parts if part]
