"""Preserve checkout handoff bytes before Git text normalization; no product edits."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(root), *args])


def exclusion(path: str) -> str | None:
    parts = Path(path).parts
    lower = path.lower()
    if any(part.lower() in {
        "state", "cache", "caches", "__pycache__", ".pytest_cache", ".serena",
        ".mypy_cache", ".ruff_cache", ".venv", "venv", "node_modules",
    } for part in parts):
        return "runtime/cache/dependency directory"
    if any(part.startswith(("t04-sync-pytest", "t04-sync-temp")) for part in parts):
        return "generated test temporary state"
    if lower.endswith((".db", ".sqlite", ".sqlite3", "-wal", "-shm", ".pyc", ".pyo", ".pid", ".lock")):
        return "runtime database/cache/process state"
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("label", choices=("integration", "lock-recovery"))
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    allowed = Path("C:/Users/Adam/.codex/worktrees") / ("t04-" + args.label) / ".local-ai-hub"
    if root != allowed.resolve(strict=True):
        raise SystemExit("root is outside assigned T04 checkout")
    output = root / "handoff" / ("t04-preservation-" + args.label + "-20261006-v2")
    if output.exists():
        raise SystemExit("preservation output already exists; refusing overwrite")
    candidates = set(git(root, "ls-files", "--others", "--exclude-standard", "-z").decode().split("\0"))
    ignored = set(git(root, "ls-files", "--others", "--ignored", "--exclude-standard", "-z").decode().split("\0"))
    # Historical test logs are receipts, even when a blanket *.log rule ignores them.
    candidates.update(p for p in ignored if p and exclusion(p) is None)
    tracked_handoffs = git(root, "ls-files", "-z", "handoff", "artifacts").decode().split("\0")
    candidates.update(p for p in tracked_handoffs if Path(p).name.lower().startswith("t04"))
    candidates.discard("")
    ignored.discard("")
    excluded = []
    preserved = []
    output.mkdir(parents=True)
    archive = output / "original-bytes.zip"
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
        for relative in sorted(candidates):
            reason = exclusion(relative)
            path = root / relative
            if reason or path.is_symlink() or not path.is_file():
                excluded.append({"path": relative, "reason": reason or "symlink/non-file; retained in place"})
                continue
            raw = path.read_bytes()
            bundle.writestr(relative, raw)
            preserved.append({"path": relative, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    with zipfile.ZipFile(archive) as bundle:
        for entry in preserved:
            if hashlib.sha256(bundle.read(entry["path"])).hexdigest() != entry["sha256"]:
                raise SystemExit("raw archive verification failed")
    for relative in sorted(ignored - candidates):
        excluded.append({"path": relative, "reason": exclusion(relative) or "pre-existing Git ignore policy; retained in place"})
    manifest = {
        "checkout": args.label,
        "master_start_revision": "fbc965f568105e1a8d3dc03ae4c9da5531a9617e",
        "synchronized_master_revision": "f8ba97fe9eafa38810dbbbc3c4184800da7bafcd",
        "head_before_preservation": git(root, "rev-parse", "HEAD").decode().strip(),
        "archive": archive.name,
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "preserved": preserved,
        "excluded_preserved_in_place": excluded,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"archive": str(archive), "raw_files_verified": len(preserved), "excluded_paths": len(excluded)}))


if __name__ == "__main__":
    main()
