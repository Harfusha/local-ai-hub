#!/usr/bin/env python3
"""clean.py — Purge temporary caches, build artifacts, and release violations.

Usage:
    python tools/clean.py [--all] [--dry-run]
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SAFE_DIR_NAMES_TO_REMOVE = {
    "__pycache__",
    ".pytest_cache",
    ".coverage",
    "htmlcov",
    "build",
    "dist",
}

SAFE_FILE_PATTERNS_TO_REMOVE = {
    "*.pyc",
    "*.pyo",
    ".coverage*",
    "*.local-ai-hub-backup-*",
}


def clean(root: Path, *, all_clean: bool = False, dry_run: bool = False) -> tuple[int, int]:
    """Remove cache files and build artifacts."""
    files_removed = 0
    dirs_removed = 0

    # 1. Remove directories
    for path in sorted(root.rglob("*"), reverse=True):
        rel = path.relative_to(root).as_posix()
        parts = path.relative_to(root).parts
        if ".git" in parts:
            continue
        if not all_clean and (".venv" in parts or "tool-envs" in parts):
            continue

        if path.is_dir():
            if path.name in SAFE_DIR_NAMES_TO_REMOVE or path.name.endswith(".egg-info"):
                dirs_removed += 1
                if dry_run:
                    print(f"[dry-run] would remove dir: {rel}")
                else:
                    try:
                        shutil.rmtree(path)
                        print(f"Removed dir: {rel}")
                    except Exception as exc:
                        print(f"Warning: could not remove {rel}: {exc}", file=sys.stderr)
            elif all_clean and path.name == "wheel-smoke":
                dirs_removed += 1
                if not dry_run:
                    shutil.rmtree(path, ignore_errors=True)

    # 2. Remove files
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        parts = path.relative_to(root).parts
        if ".git" in parts:
            continue
        if not all_clean and (".venv" in parts or "tool-envs" in parts):
            continue

        rel = path.relative_to(root).as_posix()
        should_remove = False

        if path.suffix in {".pyc", ".pyo"}:
            should_remove = True
        elif path.name.startswith(".coverage"):
            should_remove = True
        elif ".local-ai-hub-backup-" in path.name:
            should_remove = True
        elif all_clean and path.name.endswith(".log") and "state" in parts:
            should_remove = True

        if should_remove:
            files_removed += 1
            if dry_run:
                print(f"[dry-run] would remove file: {rel}")
            else:
                try:
                    path.unlink()
                    print(f"Removed file: {rel}")
                except Exception as exc:
                    print(f"Warning: could not remove {rel}: {exc}", file=sys.stderr)

    return dirs_removed, files_removed


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean repository cache and build artifacts.")
    parser.add_argument("--root", type=Path, default=ROOT, help="Repository root directory")
    parser.add_argument("--all", action="store_true", help="Also clean logs and packaging smoke dirs")
    parser.add_argument("--dry-run", action="store_true", help="Print items without deleting")
    args = parser.parse_args()

    dirs, files = clean(args.root.resolve(), all_clean=args.all, dry_run=args.dry_run)
    action = "Would remove" if args.dry_run else "Removed"
    print(f"\nCleanup complete. {action} {dirs} directories and {files} files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
