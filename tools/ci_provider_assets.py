"""Capture and remove only unchanged CI-generated provider assets."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def snapshot(root: Path) -> dict[str, str]:
    generated = root / "generated"
    if generated.is_symlink() or not generated.is_dir():
        raise ValueError("generated directory is missing or linked")
    result: dict[str, str] = {}
    for path in sorted(generated.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"linked generated path: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError(f"unexpected generated path: {path}")
        relative = path.relative_to(generated).as_posix()
        if relative == ".gitkeep":
            continue
        result[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not result:
        raise ValueError("provider generation produced no assets")
    return result


def cleanup(root: Path, expected: dict[str, str]) -> None:
    current = snapshot(root)
    if current != expected:
        changed = sorted(name for name in set(current) | set(expected)
                         if current.get(name) != expected.get(name))
        raise ValueError(f"generated provider assets changed during tests: {changed}")
    for relative in current:
        (root / "generated" / relative).unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("capture", "cleanup"))
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.action == "capture":
        args.manifest.write_text(json.dumps(snapshot(root), sort_keys=True), encoding="utf-8")
    else:
        cleanup(root, json.loads(args.manifest.read_text(encoding="utf-8")))


if __name__ == "__main__":
    main()
