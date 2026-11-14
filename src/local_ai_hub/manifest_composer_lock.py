from __future__ import annotations

import json


ManifestRows = tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]


def parse_composer_lock_manifest(name: str, raw: bytes) -> ManifestRows | None:
    """Parse Composer production and development lock rows."""
    if name.lower() != "composer.lock":
        return None

    data = json.loads(raw.decode("utf-8", errors="replace"))
    dependencies: list[tuple[str, str, str]] = []
    if isinstance(data, dict):
        for section in ("packages", "packages-dev"):
            entries = data.get(section, [])
            for package in entries if isinstance(entries, list) else []:
                if isinstance(package, dict) and package.get("name"):
                    scope = "lock-dev" if section.endswith("dev") else "lock"
                    dependencies.append((str(package["name"]), str(package.get("version", "")), scope))
    return dependencies, []
