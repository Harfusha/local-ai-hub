from __future__ import annotations

import tomllib


_SUPPORTED_LOCK_NAMES = {"uv.lock", "poetry.lock", "cargo.lock"}


def parse_toml_lock_manifest(
    name: str,
    raw: bytes,
) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]] | None:
    """Parse package rows from supported TOML lockfiles."""
    if name.lower() not in _SUPPORTED_LOCK_NAMES:
        return None

    data = tomllib.loads(raw.decode("utf-8", errors="replace"))
    packages = data.get("package", []) if isinstance(data, dict) else []
    dependencies = [
        (str(package["name"]), str(package.get("version", "")), "lock")
        for package in (packages if isinstance(packages, list) else [])
        if isinstance(package, dict) and package.get("name")
    ]
    return dependencies, []
