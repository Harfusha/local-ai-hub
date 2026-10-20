"""Bounded dependency inventory with explicitly partial offline advisory coverage."""
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any


MAX_MANIFEST_BYTES = 4 * 1024 * 1024
SUPPORTED_MANIFESTS = frozenset({"requirements.txt", "poetry.lock", "package-lock.json", "composer.lock", "pyproject.toml"})

# Historical positive detections only. This is not a current advisory database,
# and absence from these rules must never produce a clean security verdict.
_LEGACY_RULES = (
    ("requests", "2.31.0", "CVE-2023-32681", "MEDIUM"),
    ("urllib3", "2.0.7", "CVE-2023-45803", "HIGH"),
    ("pyyaml", "5.4.0", "CVE-2020-14343", "CRITICAL"),
    ("jinja2", "3.1.3", "CVE-2024-22195", "HIGH"),
    ("cryptography", "41.0.6", "CVE-2023-49083", "HIGH"),
    ("lodash", "4.17.21", "CVE-2021-23337", "HIGH"),
    ("jsonwebtoken", "9.0.0", "CVE-2022-23529", "HIGH"),
    ("axios", "1.7.4", "CVE-2024-39338", "MEDIUM"),
    ("guzzlehttp/guzzle", "7.4.5", "CVE-2022-31090", "HIGH"),
    ("laravel/framework", "9.1.8", "CVE-2022-40482", "HIGH"),
)


def audit_manifest(path: Path, text: str) -> dict[str, Any]:
    """Inspect already-confined text; preserve duplicate resolved package versions."""
    if path.name not in SUPPORTED_MANIFESTS:
        return {"success": False, "status": "unsupported", "parse_complete": False,
                "advisory_complete": False, "error": "unsupported dependency manifest format",
                "terminal": True, "retryable": False}
    packages: list[tuple[str, str]] = []
    package_keys: set[tuple[str, str]] = set()
    parse_complete = True

    def add(name: Any, version: Any) -> None:
        nonlocal parse_complete
        if not isinstance(name, str) or not name.strip():
            parse_complete = False
            return
        normalized = name.strip().lower()
        exact = version if isinstance(version, str) and re.fullmatch(r"\d+(?:\.\d+)*(?:[-+._a-zA-Z0-9]*)?", version) else "unresolved"
        item = (normalized, exact)
        if len(package_keys) >= 100_000:
            raise ValueError("dependency inventory exceeded item limit")
        if item not in package_keys:
            package_keys.add(item)
            packages.append(item)

    def requirement(value: Any) -> None:
        nonlocal parse_complete
        if not isinstance(value, str):
            parse_complete = False
            return
        match = re.match(r"\s*([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?\s*(.*)", value)
        if not match:
            parse_complete = False
            return
        spec = match[2].split(";", 1)[0].strip().strip("()")
        exact = re.fullmatch(r"==\s*([^,\s]+)", spec)
        add(re.sub(r"[-_.]+", "-", match[1]), exact[1] if exact else None)

    try:
        if path.name == "requirements.txt":
            for line in text.splitlines():
                line = line.split(" #", 1)[0].strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("-"):
                    # Includes, indexes and hashes require a resolver; do not follow them.
                    parse_complete = False
                    continue
                requirement(line)
        elif path.name == "pyproject.toml":
            project = tomllib.loads(text).get("project", {})
            dependencies = project.get("dependencies", [])
            optional = project.get("optional-dependencies", {})
            if not isinstance(dependencies, list) or not isinstance(optional, dict):
                raise ValueError("invalid dependency collections")
            if "dependencies" in project.get("dynamic", []):
                parse_complete = False
            for item in dependencies:
                requirement(item)
            for values in optional.values():
                if not isinstance(values, list):
                    raise ValueError("invalid optional dependency collection")
                for item in values:
                    requirement(item)
        elif path.name == "poetry.lock":
            rows = tomllib.loads(text).get("package")
            if not isinstance(rows, list):
                raise ValueError("missing package list")
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError("invalid package row")
                add(row.get("name"), row.get("version"))
        elif path.name == "composer.lock":
            document = json.loads(text)
            rows = document.get("packages", []) + document.get("packages-dev", [])
            if not isinstance(rows, list):
                raise ValueError("invalid package list")
            for row in rows:
                add(row.get("name"), row.get("version", "").removeprefix("v"))
        else:
            document = json.loads(text)
            rows = document.get("packages")
            if rows is not None:
                if not isinstance(rows, dict):
                    raise ValueError("invalid packages mapping")
                for name, row in rows.items():
                    if not isinstance(row, dict):
                        raise ValueError("invalid package row")
                    if not name:  # root project is not an installed dependency
                        continue
                    add(row.get("name") or name.rsplit("node_modules/", 1)[-1], row.get("version"))
            else:
                pending = [document.get("dependencies")]
                seen = 0
                while pending:
                    rows = pending.pop()
                    if not isinstance(rows, dict):
                        raise ValueError("invalid dependencies mapping")
                    for name, row in rows.items():
                        seen += 1
                        if seen > 100_000 or not isinstance(row, dict):
                            raise ValueError("invalid or oversized dependency graph")
                        add(name, row.get("version"))
                        if "dependencies" in row:
                            pending.append(row["dependencies"])
    except (ValueError, TypeError, AttributeError):
        return {"success": False, "status": "invalid", "parse_complete": False,
                "advisory_complete": False, "error": "invalid dependency manifest",
                "terminal": True, "retryable": False}

    vulnerabilities = []
    for name, installed in packages:
        for package, fixed, cve, severity in _LEGACY_RULES:
            # Restrict this historical comparator to simple releases. Prereleases,
            # direct URLs and ranges remain unresolved rather than being guessed.
            if name == package and re.fullmatch(r"\d+(?:\.\d+){1,3}", installed):
                version = tuple(int(x) for x in installed.split("."))
                threshold = tuple(int(x) for x in fixed.split("."))
                if version + (0,) * (4 - len(version)) < threshold + (0,) * (4 - len(threshold)):
                    vulnerabilities.append({"package": name, "installed_version": installed,
                        "vulnerable_below": fixed, "cve": cve, "severity": severity,
                        "recommendation": f"Upgrade {name} to >={fixed}"})
    unresolved = sum(version == "unresolved" for _, version in packages)
    return {
        "success": True, "manifest": str(path),
        "lockfile": None if path.name == "pyproject.toml" else str(path),
        "manifest_only": path.name == "pyproject.toml", "packages_scanned": len(packages),
        "resolved_count": len(packages) - unresolved, "unresolved_count": unresolved,
        "parse_complete": parse_complete, "advisory_complete": False,
        "advisory_source": "bundled_legacy_rules", "advisory_updated_at": None,
        "vulnerabilities_found": len(vulnerabilities), "vulnerabilities": vulnerabilities,
        "status": "vulnerabilities_detected" if vulnerabilities else "unknown",
        "warnings": ["Offline rules are incomplete; no current clean-security verdict is available."],
    }
