"""Bounded parsing of reported framework summaries, without inferring counts."""

from __future__ import annotations

import re
from typing import Any

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_COUNT = r"\d{1,12} (?:passed|failed|skipped|xfailed|xpassed|deselected|rerun|errors?|warnings?)"
_FINAL = re.compile(
    rf"^\s*=*\s*(?P<counts>{_COUNT}(?:, {_COUNT})*) in "
    r"(?P<elapsed>\d{1,10}(?:\.\d{1,6})?)s(?: \([^\r\n]{1,32}\))?\s*=*\s*$"
)


def pytest_output_summary(stdout: str, stderr: str) -> dict[str, Any] | None:
    """Parse the last complete pytest summary line in bounded captured tails."""
    for stream in (stdout, stderr):
        tail = stream[-65_536:]
        if len(stream) > len(tail):
            # The initial partial line cannot constitute exact summary evidence.
            tail = tail.partition("\n")[2]
        for raw in reversed(tail.splitlines()):
            if len(raw) > 2048:
                continue
            match = _FINAL.fullmatch(_ANSI.sub("", raw))
            if match is None:
                continue
            counts = {}
            for item in match["counts"].split(", "):
                count, label = item.split(" ")
                label = {"error": "errors", "warning": "warnings"}.get(label, label)
                if label in counts:
                    return None
                counts[label] = int(count)
            return {"framework": "pytest", "source": "captured_final_summary", "counts": counts,
                    "elapsed_seconds": float(match["elapsed"])}
    return None
