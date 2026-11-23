"""Prepare version metadata and documentation for a CI-gated stable release."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tomllib
from datetime import date
from pathlib import Path

_COMPONENT = r"(0|[1-9][0-9]*)"
_SEMVER = re.compile(rf"{_COMPONENT}\.{_COMPONENT}\.{_COMPONENT}")
_LEGACY_TAG = re.compile(rf"v{_COMPONENT}\.{_COMPONENT}")
_PACKAGE_VERSION = re.compile(r'^version\s*=\s*"([^"\r\n]+)"$', re.MULTILINE)
_INIT_VERSION = re.compile(r'^__version__\s*=\s*"([^"\r\n]+)"$', re.MULTILINE)
BUMP_LEVELS = ("major", "minor", "patch")


def version_parts(version: str) -> tuple[int, int, int]:
    match = _SEMVER.fullmatch(version) if isinstance(version, str) else None
    if match is None:
        raise ValueError(f"invalid stable SemVer: {version!r}")
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch)


def prepare_release(root: Path, bump: str, tags: list[str], release_date: date) -> str:
    package = root / "pyproject.toml"
    init = root / "src/local_ai_hub/__init__.py"
    manifest = root / "RELEASE.json"
    package_text = package.read_text(encoding="utf-8")
    init_text = init.read_text(encoding="utf-8")
    release = json.loads(manifest.read_text(encoding="utf-8"))
    current = tomllib.loads(package_text)["project"]["version"]
    if (
        _PACKAGE_VERSION.findall(package_text) != [current]
        or _INIT_VERSION.findall(init_text) != [current]
        or release.get("version") != current
    ):
        raise ValueError("release version metadata is inconsistent")

    versions = [version_parts(current)]
    for tag in tags:
        if tag.startswith("v") and _SEMVER.fullmatch(tag[1:]):
            versions.append(version_parts(tag[1:]))
        elif _LEGACY_TAG.fullmatch(tag):
            versions.append(version_parts(f"{tag[1:]}.0"))
    parts = list(max(versions))
    index = BUMP_LEVELS.index(bump)
    parts[index] += 1
    parts[index + 1:] = [0] * (2 - index)
    version = ".".join(map(str, parts))
    tag = f"v{version}"

    readme = root / "README.md"
    changelog = root / "CHANGELOG.md"
    readme_text = readme.read_text(encoding="utf-8")
    heading, separator, history = changelog.read_text(encoding="utf-8").partition("\n\n")
    if not separator or not heading.startswith("# "):
        raise ValueError("CHANGELOG.md is missing its document heading")
    status_line = (
        f"**Release status:** stable release **{version}**. "
        "See [`RELEASE.json`](RELEASE.json) and the release workflow for verification gates."
    )
    readme_text, replaced = re.subn(r"^\*\*Release status:\*\*.*$", status_line, readme_text, count=1, flags=re.MULTILINE)
    if not replaced:
        raise ValueError("README.md is missing its release status")
    readme_text = readme_text.replace(f"Local AI Hub **{current}**", f"Local AI Hub **{version}**")
    readme_text = readme_text.replace(f"Local AI Hub {current} ", f"Local AI Hub {version} ")
    entry = f"## {version} — {release_date.isoformat()}"
    notes = f"- [Changes in {tag}](https://github.com/Harfusha/local-ai-hub/releases/tag/{tag})"

    release.update(version=version, release_date=release_date.isoformat(), status="production-ready", focus=f"Release {tag}")
    package.write_text(_PACKAGE_VERSION.sub(f'version = "{version}"', package_text), encoding="utf-8")
    init.write_text(_INIT_VERSION.sub(f'__version__ = "{version}"', init_text), encoding="utf-8")
    manifest.write_text(json.dumps(release, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    readme.write_text(readme_text, encoding="utf-8")
    changelog.write_text(f"{heading}\n\n{entry}\n\n{notes}\n\n{history}", encoding="utf-8")
    return tag


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bump", choices=BUMP_LEVELS)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    tags = subprocess.check_output(["git", "tag", "--list"], cwd=root, text=True, timeout=30).splitlines()
    print(prepare_release(root, args.bump, tags, date.today()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
