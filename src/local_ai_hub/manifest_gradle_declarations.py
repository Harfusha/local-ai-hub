from __future__ import annotations

import re


_MANIFEST_IMPLEMENTATION = re.compile(
    r"^\s*(implementation|api|compileOnly|runtimeOnly|testImplementation|testRuntimeOnly|kapt)\s*\(?[\"']([^\"']+)[\"']"
)
ManifestRows = tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]


def parse_gradle_declarations_manifest(name: str, raw: bytes) -> ManifestRows | None:
    """Parse literal dependency declarations from Gradle build files."""
    if name.lower() not in {"build.gradle", "build.gradle.kts"}:
        return None

    dependencies: list[tuple[str, str, str]] = []
    text = raw.decode("utf-8", errors="replace")
    for line in text.splitlines():
        match = _MANIFEST_IMPLEMENTATION.match(line)
        if not match:
            continue
        coordinate = match.group(2)
        parts = coordinate.split(":")
        package = ":".join(parts[:2]) if len(parts) >= 2 else coordinate
        version = parts[2] if len(parts) >= 3 else ""
        dependencies.append((package, version, match.group(1)))
    return dependencies, []
