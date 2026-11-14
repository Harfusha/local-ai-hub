from __future__ import annotations

from re import Pattern


ManifestRows = tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]


def parse_gemfile_manifest(name: str, raw: bytes, gem_pattern: Pattern[str]) -> ManifestRows | None:
    """Parse Gemfile gem declarations using the engine's established matcher."""
    if name.lower() != "gemfile":
        return None

    dependencies: list[tuple[str, str, str]] = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        match = gem_pattern.match(line)
        if match:
            dependencies.append((match.group(1), match.group(2) or "", "gem"))
    return dependencies, []
