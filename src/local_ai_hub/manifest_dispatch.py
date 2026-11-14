from __future__ import annotations

import re

from .manifest_packages import parse_package_manifest
from .manifest_python import parse_python_manifest
from .manifest_go import parse_go_manifest, parse_go_sum_manifest
from .manifest_xml import parse_xml_manifest
from .manifest_deno import parse_deno_manifest
from .manifest_npm_lock import parse_npm_lock_manifest
from .manifest_dotnet import parse_dotnet_manifest
from .manifest_toml_lock import parse_toml_lock_manifest
from .manifest_gradle import parse_gradle_catalog_manifest
from .manifest_gradle_declarations import parse_gradle_declarations_manifest
from .manifest_text_lock import parse_text_lock_manifest
from .manifest_project import parse_project_manifest
from .manifest_ruby import parse_gemfile_manifest
from .manifest_scripts import parse_build_scripts_manifest
from .manifest_composer_lock import parse_composer_lock_manifest


ManifestRows = tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]
_MANIFEST_IDENTIFIER = re.compile(r"^\s*gem\s+['\"]([^'\"]+)['\"](?:\s*,\s*['\"]([^'\"]+)['\"])?")
_MANIFEST_IDENTIFIER_REGEX = re.compile(r"^([A-Za-z0-9_.-]+)\s*:(?:[^=]|$)")
_MANIFEST_IDENTIFIER_REGEX_PATTERN = re.compile(r"^([A-Za-z0-9_.-]+)\s*(?:[^:=]*)?:\s*$")


def parse_manifest_dispatch(name: str, suffix: str, raw: bytes, purpose: str) -> ManifestRows:
    """Route a snapshotted manifest to its format-specific pure parser."""
    filename = name.lower()
    suffix = suffix.lower()
    if filename in {"package.json", "composer.json"}:
        parsed = parse_package_manifest(filename, raw, purpose)
    elif filename in {"deno.json", "deno.jsonc"}:
        parsed = parse_deno_manifest(filename, raw, purpose)
    elif filename in {"package-lock.json", "pnpm-lock.yaml"}:
        parsed = parse_npm_lock_manifest(filename, raw)
    elif filename in {"packages.lock.json", "global.json"}:
        parsed = parse_dotnet_manifest(filename, raw)
    elif filename == "composer.lock":
        parsed = parse_composer_lock_manifest(filename, raw)
    elif filename in {"uv.lock", "poetry.lock", "cargo.lock"}:
        parsed = parse_toml_lock_manifest(filename, raw)
    elif filename == "go.sum":
        parsed = parse_go_sum_manifest(filename, raw)
    elif filename in {"yarn.lock", "gemfile.lock"}:
        parsed = parse_text_lock_manifest(filename, raw)
    elif filename in {"build.gradle", "build.gradle.kts"}:
        parsed = parse_gradle_declarations_manifest(filename, raw)
    elif filename in {"gradle/libs.versions.toml", "libs.versions.toml"}:
        parsed = parse_gradle_catalog_manifest(filename, raw)
    elif (filename.startswith("requirements") and filename.endswith((".txt", ".in"))) or filename == "pipfile":
        parsed = parse_python_manifest(filename, raw, purpose)
    elif filename == "gemfile":
        parsed = parse_gemfile_manifest(filename, raw, _MANIFEST_IDENTIFIER)
    elif filename in {"makefile", "gnumakefile", "justfile"}:
        target_pattern = _MANIFEST_IDENTIFIER_REGEX if filename != "justfile" else _MANIFEST_IDENTIFIER_REGEX_PATTERN
        parsed = parse_build_scripts_manifest(filename, raw, target_pattern, purpose)
    elif filename in {"pyproject.toml", "cargo.toml"}:
        parsed = parse_project_manifest(filename, raw, purpose)
    elif filename in {"go.mod", "go.work"}:
        parsed = parse_go_manifest(filename, raw)
    elif suffix in {".csproj", ".fsproj", ".vbproj"} or filename in {
        "directory.packages.props", "directory.build.props", "directory.build.targets", "pom.xml"
    }:
        parsed = parse_xml_manifest(filename, suffix, raw)
    else:
        parsed = None
    return parsed if parsed is not None else ([], [])

