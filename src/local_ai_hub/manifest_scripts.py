from __future__ import annotations

from collections.abc import Callable
from re import Pattern


ManifestRows = tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]


def parse_build_scripts_manifest(
    name: str,
    raw: bytes,
    target_pattern: Pattern[str],
    purpose: Callable[[str], str],
) -> ManifestRows | None:
    """Parse Make and Just targets using the engine's established matchers."""
    normalized_name = name.lower()
    if normalized_name not in {"makefile", "gnumakefile", "justfile"}:
        return None

    runner = "just" if normalized_name == "justfile" else "make"
    scripts: list[tuple[str, str, str]] = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        match = target_pattern.match(line)
        if match and not match.group(1).startswith("."):
            target = match.group(1)
            scripts.append((target, f"{runner} {target}", purpose(target)))
    return [], scripts
