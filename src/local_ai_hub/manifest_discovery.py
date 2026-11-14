from __future__ import annotations

import os
from pathlib import Path


_MANIFEST_NAMES = {
    "package.json", "package-lock.json", "pnpm-lock.yaml", "deno.json", "deno.jsonc",
    "composer.json", "composer.lock", "pyproject.toml", "poetry.lock", "uv.lock",
    "cargo.toml", "cargo.lock", "go.mod", "go.sum", "go.work", "pom.xml", "pipfile", "gemfile", "gemfile.lock",
    "yarn.lock", "build.gradle", "build.gradle.kts", "libs.versions.toml", "makefile", "gnumakefile", "justfile",
    "packages.lock.json", "global.json", "directory.packages.props", "directory.build.props", "directory.build.targets",
}
_MANIFEST_SUFFIXES = {".csproj", ".fsproj", ".vbproj"}


def walk_manifest_paths(
    base: Path,
    *,
    max_files: int,
    ignore_dirs: set[str],
) -> list[Path]:
    """Walk a bounded tree when Git inventory is unavailable."""
    paths: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [name for name in dirnames if name not in ignore_dirs]
        for filename in filenames:
            paths.append(Path(dirpath) / filename)
            if len(paths) >= max_files:
                break
        if len(paths) >= max_files:
            break
    return paths


def select_manifest_files(paths: list[Path], *, max_bytes: int) -> list[Path]:
    """Select supported, bounded manifests and return a stable path order."""
    found: list[Path] = []
    for path in paths:
        name = path.name.lower()
        is_manifest = (
            name in _MANIFEST_NAMES
            or (name.startswith("requirements") and name.endswith((".txt", ".in")))
            or path.suffix.lower() in _MANIFEST_SUFFIXES
        )
        if not is_manifest:
            continue
        try:
            if path.stat().st_size <= max_bytes:
                found.append(path)
        except OSError:
            continue
    return sorted(found, key=lambda path: str(path).lower())
