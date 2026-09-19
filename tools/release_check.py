from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]

_TOP_LEVEL_FORBIDDEN_DIRS = {
    ".agents",
    "_local_ai_hub_patch",
    ".pytest_cache",
    ".serena",
    ".superpowers",
    ".venv",
    "build",
    "dist",
    "state",
    "tool-envs",
    "wheel-smoke",
    ".worktrees",
}
_FORBIDDEN_DIR_NAMES = {"__pycache__"}
_FORBIDDEN_FILE_NAMES = {"config.toml", ".local-ai-hub.zip", "ORIGINAL_REQUEST.md"}
_FORBIDDEN_SUFFIXES = {".pyc", ".pyo", ".sqlite3", ".whl"}
_ALLOWED_RUNTIME_PLACEHOLDERS = {"data/.gitkeep", "generated/.gitkeep"}


def _version_from_init(root: Path) -> str:
    text = (root / "src" / "local_ai_hub" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
    if not match:
        raise ValueError("src/local_ai_hub/__init__.py does not define __version__")
    return match.group(1)


_INSTALLED_ENV_DIRS = {".venv", "tool-envs", "state", ".serena", ".agents", ".superpowers", ".worktrees"}


def _iter_release_hygiene_violations(root: Path, *, post_test: bool = False, allow_installed: bool = False) -> Iterable[str]:
    """Yield release-tree violations.

    ``post_test`` tolerates only known test/install caches that are expected to be
    cleaned before packaging. Runtime databases, local configuration, generated
    payloads and internal workspace files remain fatal so cleanup cannot mask them.

    ``allow_installed`` additionally allows managed runtime/tool environments
    (``.venv``, ``tool-envs``, ``state``) present in active developer checkouts.
    """
    if allow_installed:
        post_test = True

    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        parts = path.relative_to(root).parts
        if ".git" in parts:
            continue
        if allow_installed:
            if parts and parts[0] in _INSTALLED_ENV_DIRS:
                continue
            if parts and parts[0] in {"generated", "data"}:
                continue
            if path.name in {"config.toml", ".local-ai-hub.zip"}:
                continue
            if ".local-ai-hub-backup-" in path.name:
                continue
        if post_test:
            if ".pytest_cache" in parts or "__pycache__" in parts or any(part.endswith(".egg-info") for part in parts):
                continue
            if path.is_file() and path.name.startswith(".coverage"):
                continue
        if parts and parts[0] in _TOP_LEVEL_FORBIDDEN_DIRS:
            if len(parts) == 1:
                yield f"forbidden directory: {rel}/"
            continue
        if path.is_dir():
            if path.name in _FORBIDDEN_DIR_NAMES or path.name.endswith(".egg-info"):
                yield f"forbidden directory: {rel}/"
            continue
        if any(part in _FORBIDDEN_DIR_NAMES for part in parts):
            yield f"compiled cache payload: {rel}"
            continue
        if rel in _ALLOWED_RUNTIME_PLACEHOLDERS:
            continue
        if parts and parts[0] in {"data", "generated"}:
            yield f"generated/runtime payload: {rel}"
            continue
        if path.name in _FORBIDDEN_FILE_NAMES:
            yield f"local-only file: {rel}"
            continue
        if path.name.startswith(".coverage"):
            yield f"coverage payload: {rel}"
            continue
        if ".local-ai-hub-backup-" in path.name:
            yield f"backup payload: {rel}"
            continue
        if path.suffix in _FORBIDDEN_SUFFIXES or ".sqlite3-" in path.name:
            yield f"runtime/build payload: {rel}"


def run_checks(root: Path, *, expected_version: str | None = None, post_test: bool = False, allow_installed: bool = False) -> dict[str, object]:
    errors: list[str] = []
    checks: list[dict[str, object]] = []

    try:
        pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        package_version = str(pyproject["project"]["version"])
        init_version = _version_from_init(root)
        release = json.loads((root / "RELEASE.json").read_text(encoding="utf-8"))
        release_version = str(release.get("version", ""))
        version_ok = len({package_version, init_version, release_version}) == 1
        checks.append({
            "name": "version-consistency",
            "ok": version_ok,
            "versions": {"pyproject": package_version, "package": init_version, "release": release_version},
        })
        if not version_ok:
            errors.append("version metadata is inconsistent")
        if release.get("status") != "production-ready":
            errors.append("RELEASE.json status must be production-ready")
        if expected_version:
            normalized_expected = str(expected_version).strip()
            if normalized_expected.startswith("v"):
                normalized_expected = normalized_expected[1:]
            expected_ok = normalized_expected == package_version
            checks.append({"name": "expected-version", "ok": expected_ok, "expected": normalized_expected, "actual": package_version})
            if not expected_ok:
                errors.append(f"expected release version {normalized_expected!r}, found {package_version!r}")
    except Exception as exc:
        checks.append({"name": "version-consistency", "ok": False, "error": str(exc)})
        errors.append(f"version metadata check failed: {exc}")
        package_version = ""

    source_defaults = root / "src" / "local_ai_hub" / "defaults.toml"
    root_defaults = root / "defaults.toml"
    defaults_ok = source_defaults.is_file() and root_defaults.is_file() and source_defaults.read_bytes() == root_defaults.read_bytes()
    checks.append({"name": "defaults-consistency", "ok": defaults_ok})
    if not defaults_ok:
        errors.append("root defaults.toml and packaged defaults.toml differ")

    manifest = (root / "MANIFEST.in").read_text(encoding="utf-8")
    manifest_ok = (
        "include config.toml\n" not in manifest
        and "include config.toml.example" in manifest
        and "include requirements-openvino.txt" in manifest
    )
    checks.append({"name": "manifest-hygiene", "ok": manifest_ok})
    if not manifest_ok:
        errors.append("MANIFEST.in must ship config.toml.example and requirements-openvino.txt, never local config.toml")

    required_docs = {
        "README.md",
        "LICENSE",
        "SECURITY.md",
        "CONTRIBUTING.md",
        "docs/INSTALLATION.md",
        "docs/CONFIGURATION.md",
        "docs/MCP_AND_AGENTS.md",
        "docs/OPERATIONS.md",
    }
    missing_docs = sorted(item for item in required_docs if not (root / item).is_file())
    checks.append({"name": "public-docs", "ok": not missing_docs, "missing": missing_docs})
    errors.extend(f"missing public release file: {item}" for item in missing_docs)

    hygiene = list(_iter_release_hygiene_violations(root, post_test=post_test, allow_installed=allow_installed))
    checks.append({"name": "workspace-hygiene", "ok": not hygiene, "violations": hygiene})
    errors.extend(hygiene)

    if package_version:
        readme = (root / "README.md").read_text(encoding="utf-8")
        changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
        docs_version_ok = package_version in readme and re.search(rf"^##\s+{re.escape(package_version)}\b", changelog, re.MULTILINE) is not None
        checks.append({"name": "release-doc-version", "ok": docs_version_ok})
        if not docs_version_ok:
            errors.append(f"README.md/CHANGELOG.md are not aligned to {package_version}")

    return {"success": not errors, "root": str(root), "errors": errors, "checks": checks}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate that a Local AI Hub checkout is safe to package/release.")
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root (defaults to this checkout)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument("--expected-version", default=None, help="require package metadata to match this version (leading v is accepted)")
    parser.add_argument("--post-test", action="store_true", help="allow only known test/install caches while still rejecting runtime side effects")
    parser.add_argument("--allow-installed", action="store_true", help="allow managed tool environments (.venv, tool-envs, state) in live checkouts")
    args = parser.parse_args(argv)
    root = args.root.expanduser().resolve()
    result = run_checks(root, expected_version=args.expected_version, post_test=args.post_test, allow_installed=args.allow_installed)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result["success"]:
        print("release-check: OK")
    else:
        print("release-check: FAILED", file=sys.stderr)
        for error in result["errors"]:
            print(f"- {error}", file=sys.stderr)
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
