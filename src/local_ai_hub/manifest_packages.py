from __future__ import annotations

import json
from collections.abc import Callable


ManifestRows = tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]


def parse_package_manifest(
    name: str,
    raw: bytes,
    purpose: Callable[[str], str],
) -> ManifestRows | None:
    """Parse package.json and composer.json dependency and script rows."""
    if name not in {"package.json", "composer.json"}:
        return None

    data = json.loads(raw.decode("utf-8", errors="replace"))
    deps: list[tuple[str, str, str]] = []
    scripts: list[tuple[str, str, str]] = []
    if name == "package.json":
        for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
            obj = data.get(section, {}) if isinstance(data, dict) else {}
            if isinstance(obj, dict):
                deps.extend((str(key), str(value), section) for key, value in obj.items())
        obj = data.get("scripts", {}) if isinstance(data, dict) else {}
        if isinstance(obj, dict):
            scripts.extend((str(key), str(value), purpose(str(key))) for key, value in obj.items())
    else:
        for section in ("require", "require-dev"):
            obj = data.get(section, {}) if isinstance(data, dict) else {}
            if isinstance(obj, dict):
                deps.extend((str(key), str(value), section) for key, value in obj.items())
        obj = data.get("scripts", {}) if isinstance(data, dict) else {}
        if isinstance(obj, dict):
            for key, value in obj.items():
                command = value if isinstance(value, str) else " && ".join(str(item) for item in value) if isinstance(value, list) else str(value)
                scripts.append((str(key), command, purpose(str(key))))
    return deps, scripts
