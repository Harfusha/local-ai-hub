from __future__ import annotations

import re
import tomllib
from collections.abc import Callable


ManifestRows = tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]


def parse_project_manifest(
    name: str,
    raw: bytes,
    purpose: Callable[[str], str],
) -> ManifestRows | None:
    """Parse PEP 621, Poetry, and Cargo project manifests."""
    normalized_name = name.lower()
    if normalized_name not in {"pyproject.toml", "cargo.toml"}:
        return None

    data = tomllib.loads(raw.decode("utf-8", errors="replace"))
    dependencies: list[tuple[str, str, str]] = []
    scripts: list[tuple[str, str, str]] = []
    if normalized_name == "pyproject.toml":
        project = data.get("project", {}) if isinstance(data, dict) else {}
        for item in project.get("dependencies", []) if isinstance(project, dict) else []:
            token = re.split(r"[<>=!~ ;\[]", str(item), maxsplit=1)[0]
            dependencies.append((token, str(item), "project"))
        optional = project.get("optional-dependencies", {}) if isinstance(project, dict) else {}
        if isinstance(optional, dict):
            for group, items in optional.items():
                for item in items if isinstance(items, list) else []:
                    token = re.split(r"[<>=!~ ;\[]", str(item), maxsplit=1)[0]
                    dependencies.append((token, str(item), f"optional:{group}"))
        tool = data.get("tool", {}) if isinstance(data, dict) else {}
        poetry = tool.get("poetry", {}) if isinstance(tool, dict) else {}
        poetry_dependencies = poetry.get("dependencies", {}) if isinstance(poetry, dict) else {}
        if isinstance(poetry_dependencies, dict):
            dependencies.extend(
                (str(key), str(value), "poetry")
                for key, value in poetry_dependencies.items()
                if str(key).lower() != "python"
            )
        project_scripts = project.get("scripts", {}) if isinstance(project, dict) else {}
        if isinstance(project_scripts, dict):
            scripts.extend((str(key), str(value), purpose(str(key))) for key, value in project_scripts.items())
        poetry_scripts = poetry.get("scripts", {}) if isinstance(poetry, dict) else {}
        if isinstance(poetry_scripts, dict):
            scripts.extend((str(key), str(value), purpose(str(key))) for key, value in poetry_scripts.items())
    else:
        for section in ("dependencies", "dev-dependencies", "build-dependencies"):
            values = data.get(section, {}) if isinstance(data, dict) else {}
            if isinstance(values, dict):
                dependencies.extend((str(key), str(value), section) for key, value in values.items())
    return dependencies, scripts
