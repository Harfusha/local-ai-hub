"""Validate exact CI-built desktop archives and stage them for release publication."""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.install_desktop import verify_archive

TARGETS = (("Linux", "X64"), ("Windows", "X64"), ("macOS", "ARM64"), ("macOS", "X64"))


def stage(source: Path, destination: Path, version: str, revision: str) -> None:
    for system, arch in TARGETS:
        name = f"local-ai-hub-desktop-{system}-{arch}.zip"
        matches = list(source.rglob(name))
        if len(matches) != 1 or matches[0].stat().st_size > 64 * 1024 * 1024:
            raise ValueError(f"Missing, duplicate or oversized CI desktop asset: {name}")
        verify_archive(matches[0].read_bytes(), version=version, revision=revision, system=system, arch=arch)
        shutil.copyfile(matches[0], destination / name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    stage(args.source, args.destination, args.version, args.revision)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
