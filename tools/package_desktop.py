"""Create a portable verified native desktop package from a CI release binary."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import tomllib
from pathlib import Path
import zipfile


def dependency_notices(metadata: dict, lock: dict) -> bytes:
    """Retain the locked package inventory and bundled upstream license/notice texts.

    This is a distribution evidence report, not a legal compatibility verdict.
    Metadata comes from the trusted Cargo build, never a network/user request.
    """
    packages = metadata.get("packages")
    if not isinstance(packages, list) or len(packages) > 2000:
        raise ValueError("Invalid Cargo package metadata")
    locked = {(p["name"], p["version"], p.get("source")) for p in lock["package"]}
    actual = {(p["name"], p["version"], p.get("source")) for p in packages}
    if not actual or not actual <= locked or len(actual) != len(packages):
        raise ValueError("Cargo metadata does not match locked packages")
    sections = ["Local AI Hub desktop — Cargo dependency notices\n"
                "Inventory includes resolved Cargo metadata; some entries may be target/build-only.\n"
                "License expressions and bundled source texts are upstream metadata, not a legal review.\n"]
    total = len(sections[0].encode("utf-8"))
    for package in sorted(packages, key=lambda p: (p["name"], p["version"], p.get("source") or "")):
        manifest = Path(package["manifest_path"]).resolve(strict=True)
        root = manifest.parent
        text = f"\n=== {package['name']} {package['version']} ===\n"
        text += f"Source: {package.get('source') or 'workspace'}\n"
        text += f"License expression: {package.get('license') or 'not declared'}\n"
        candidates = set()
        declared = package.get("license_file")
        if declared:
            candidate = root / declared
            if not candidate.resolve(strict=True).is_relative_to(root):
                raise ValueError("Declared package license escapes crate")
            candidates.add(candidate)
        for item in root.iterdir():
            label = item.name.casefold()
            if item.is_file() and label.startswith(("license", "licence", "copying", "notice", "copyright", "unlicense")):
                candidates.add(item)
            elif item.is_dir() and label in {"licenses", "licences"} and not item.is_symlink():
                candidates.update(child for child in item.iterdir() if child.is_file())
        if not candidates:
            text += "No bundled license/notice file found in crate root; upstream review required.\n"
        for item in sorted(candidates):
            if item.is_symlink() or not item.resolve(strict=True).is_relative_to(root):
                raise ValueError("Unsafe bundled package license path")
            with item.open("rb") as stream:
                raw = stream.read(512 * 1024 + 1)
            if len(raw) > 512 * 1024:
                raise ValueError("Bundled package license exceeds limit")
            text += f"--- {item.relative_to(root).as_posix()} ---\n" + raw.decode("utf-8", errors="replace") + "\n"
        total += len(text.encode("utf-8"))
        if total > 16 * 1024 * 1024:
            raise ValueError("Dependency notices exceed limit")
        sections.append(text)
    return "".join(sections).encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--cargo-metadata", required=True, type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.revision):
        parser.error("Expected exact source revision")
    root = Path(__file__).resolve().parents[1]
    version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    system = {"Windows": "Windows", "Darwin": "macOS", "Linux": "Linux"}.get(platform.system())
    machine = platform.machine().lower()
    arch = {"amd64": "X64", "x86_64": "X64", "arm64": "ARM64", "aarch64": "ARM64"}.get(machine)
    if not system or not arch:
        parser.error("Unsupported desktop platform")
    binary = args.binary.resolve(strict=True)
    lock_bytes = (root / "desktop" / "Cargo.lock").read_bytes()
    with args.cargo_metadata.open("rb") as stream:
        raw_metadata = stream.read(32 * 1024 * 1024 + 1)
    if len(raw_metadata) > 32 * 1024 * 1024:
        parser.error("Cargo metadata exceeds limit")
    notices = dependency_notices(json.loads(raw_metadata), tomllib.loads(lock_bytes.decode("utf-8")))
    license_text = (root / "LICENSE").read_bytes()
    with binary.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    with zipfile.ZipFile(args.output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.write(binary, binary.name)
        archive.writestr("LICENSE", license_text)
        archive.writestr("THIRD-PARTY-NOTICES.txt", notices)
        archive.writestr("Cargo.lock", lock_bytes)
        auxiliary = {
            "LICENSE": hashlib.sha256(license_text).hexdigest(),
            "THIRD-PARTY-NOTICES.txt": hashlib.sha256(notices).hexdigest(),
            "Cargo.lock": hashlib.sha256(lock_bytes).hexdigest(),
        }
        archive.writestr("SHA256SUMS", f"{digest}  {binary.name}\n" + "".join(
            f"{sha}  {name}\n" for name, sha in sorted(auxiliary.items())))
        archive.writestr("desktop-receipt.json", json.dumps({
            "format": 2, "hub_version": version, "repository_revision": args.revision,
            "os": system, "architecture": arch, "binary": binary.name, "sha256": digest,
            "auxiliary_sha256": auxiliary,
        }, sort_keys=True) + "\n")
        archive.writestr("README.txt", "Local AI Hub native Rust desktop\n"
                         "Requires an existing Local AI Hub installation.\n"
                         "Extract this archive, then from the trusted Hub installation run:\n"
                         f"python tools/install_desktop.py /path/to/{binary.name} --sha256 {digest} --version {version}\n"
                         "python tools/hubctl.py desktop\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
