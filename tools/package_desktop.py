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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--revision", required=True)
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
    with binary.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    with zipfile.ZipFile(args.output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.write(binary, binary.name)
        archive.writestr("SHA256SUMS", f"{digest}  {binary.name}\n")
        archive.writestr("desktop-receipt.json", json.dumps({
            "format": 1, "hub_version": version, "repository_revision": args.revision,
            "os": system, "architecture": arch, "binary": binary.name, "sha256": digest,
        }, sort_keys=True) + "\n")
        archive.writestr("README.txt", "Local AI Hub native Rust desktop\n"
                         "Requires an existing Local AI Hub installation.\n"
                         "Extract this archive, then from the trusted Hub installation run:\n"
                         f"python tools/install_desktop.py /path/to/{binary.name} --sha256 {digest} --version {version}\n"
                         "python tools/hubctl.py desktop\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
