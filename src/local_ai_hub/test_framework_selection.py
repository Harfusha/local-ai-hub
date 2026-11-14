from __future__ import annotations

from collections.abc import Iterable

import json
import os
import stat
from pathlib import Path
from typing import Iterator

_FRAMEWORK_COMMANDS = {
    "pytest": "python -m pytest",
    "dotnet": "dotnet test",
    "npm": "npm test",
    "cargo": "cargo test",
    "go": "go test ./...",
    "pest": "vendor/bin/pest",
    "phpunit": "vendor/bin/phpunit",
}


def select_test_framework(candidates: Iterable[str]) -> tuple[str, str]:
    """Select the first recognized framework and its default run-all command."""
    for framework in candidates:
        command = _FRAMEWORK_COMMANDS.get(framework)
        if command is not None:
            return framework, command
    return "unknown", ""


def detect_test_framework(resolved_root: Path) -> tuple[str, str, bool, list[str]]:
    root_str = str(resolved_root)
    warnings: list[str] = []
    incomplete = False
    framework = "unknown"
    run_all_cmd = ""

    dotnet_project = False
    if resolved_root.is_dir():
        try:
            with os.scandir(root_str) as root_entries:
                for index, entry in enumerate(root_entries):
                    if index >= 128:
                        incomplete = True
                        warnings.append("root_framework_scan_limit_reached")
                        break
                    if entry.name.endswith((".sln", ".csproj")) and entry.is_file(follow_symlinks=False):
                        dotnet_project = True
                        break
        except OSError:
            incomplete = True
            warnings.append("root_framework_scan_failed")

    # Fast framework detection via files in root
    python_project = (resolved_root / "pytest.ini").exists() or (resolved_root / "pyproject.toml").exists() or any((resolved_root / f).is_file() for f in ("setup.py", "requirements.txt", "requirements-core.txt"))

    def framework_candidates() -> Iterator[str]:
        if python_project:
            yield "pytest"
        elif dotnet_project:
            yield "dotnet"
        elif (resolved_root / "package.json").exists():
            yield "npm"
        elif (resolved_root / "Cargo.toml").exists():
            yield "cargo"
        elif (resolved_root / "go.mod").exists():
            yield "go"

    framework, run_all_cmd = select_test_framework(framework_candidates())
    if framework == "unknown":
        composer_path = resolved_root / "composer.json"
        phpunit_config = any((resolved_root / name).is_file() for name in ("phpunit.xml", "phpunit.xml.dist"))
        php_packages: set[str] = set()
        if composer_path.exists() or composer_path.is_symlink():
            try:
                manifest_stat = composer_path.lstat()
                if stat.S_ISLNK(manifest_stat.st_mode) or (getattr(manifest_stat, "st_file_attributes", 0) & 0x400):
                    incomplete = True
                    warnings.append("composer_manifest_reparse_point_skipped")
                elif not stat.S_ISREG(manifest_stat.st_mode):
                    incomplete = True
                    warnings.append("composer_manifest_not_regular_file")
                elif manifest_stat.st_size > 256_000:
                    incomplete = True
                    warnings.append("composer_manifest_too_large")
                else:
                    manifest = json.loads(composer_path.read_text(encoding="utf-8-sig"))
                    if isinstance(manifest, dict):
                        for field in ("require", "require-dev"):
                            packages = manifest.get(field, {})
                            if isinstance(packages, dict):
                                php_packages.update(str(name).lower() for name in packages)
            except (OSError, UnicodeError, json.JSONDecodeError):
                incomplete = True
                warnings.append("composer_manifest_unreadable")
        pest_config = (resolved_root / "Pest.php").is_file() or (resolved_root / "tests" / "Pest.php").is_file()
        framework, run_all_cmd = select_test_framework((
            "pest" if "pestphp/pest" in php_packages or pest_config else "",
            "phpunit" if "phpunit/phpunit" in php_packages or phpunit_config else "",
        ))
    return framework, run_all_cmd, incomplete, warnings
