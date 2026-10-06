"""Create deterministic tracked repository fixtures in disposable T15 worktrees."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

SCHEMA = "t15-command-broker-repo-fixture-v1"
FIXTURE_DIR = ".t15-benchmark-fixture"
FIXTURE_DATA_DIR = f"{FIXTURE_DIR}/data"
ALLOWED_FILE_COUNTS = (100, 10_000, 100_000)
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40,64}$")


def _git(worktree: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(worktree), *args],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[:400]
        raise RuntimeError(f"git {' '.join(args[:2])} failed: {detail}")
    return result.stdout.strip()


def build_fixture(
    worktree: Path,
    *,
    source_pin_sha: str,
    file_count: int,
) -> dict[str, Any]:
    """Commit one fixed-size synthetic data tree atop an exact clean source pin."""
    worktree = Path(worktree).resolve(strict=True)
    if not worktree.is_dir() or not worktree.name.lower().startswith("t15-benchmark-"):
        raise ValueError("fixture worktree must be a disposable t15-benchmark-* checkout")
    if not isinstance(source_pin_sha, str) or not _GIT_SHA_RE.fullmatch(source_pin_sha):
        raise ValueError("source pin must be a full hexadecimal Git SHA")
    if isinstance(file_count, bool) or file_count not in ALLOWED_FILE_COUNTS:
        raise ValueError(f"file_count must be one of {ALLOWED_FILE_COUNTS}")

    git_root = Path(_git(worktree, "rev-parse", "--show-toplevel")).resolve(strict=True)
    if git_root != worktree:
        raise ValueError("worktree argument must be the Git worktree root")
    actual_source_pin = _git(worktree, "rev-parse", "HEAD")
    if actual_source_pin != source_pin_sha:
        raise ValueError("worktree HEAD does not match source_pin_sha")
    if _git(worktree, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("fixture worktree must be clean before fixture generation")

    fixture_root = worktree / FIXTURE_DIR
    if fixture_root.exists():
        raise ValueError(f"fixture path already exists: {FIXTURE_DIR}")
    data_root = fixture_root / "data"
    content_digest = hashlib.sha256()
    payload_bytes = 0

    for index in range(file_count):
        relative_path = f"data/{index // 1_000:04d}/file-{index:06d}.dat"
        payload = f"T15 synthetic command broker fixture {index:06d}\n".encode("ascii")
        content = payload.ljust(128, b"x")
        output_path = data_root / f"{index // 1_000:04d}" / f"file-{index:06d}.dat"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(content)
        content_digest.update(relative_path.encode("ascii"))
        content_digest.update(b"\0")
        content_digest.update(content)
        content_digest.update(b"\n")
        payload_bytes += len(content)

    manifest = {
        "schema": SCHEMA,
        "source_pin_sha": source_pin_sha,
        "file_count": file_count,
        "bytes_per_file": 128,
        "total_data_bytes": payload_bytes,
        "content_tree_sha256": content_digest.hexdigest(),
    }
    manifest_path = fixture_root / "manifest.json"
    manifest_bytes = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode("utf-8")
    manifest_path.write_bytes(manifest_bytes)

    _git(worktree, "add", "--", FIXTURE_DIR)
    _git(
        worktree,
        "-c", "user.name=T15 Benchmark Fixture",
        "-c", "user.email=t15-benchmark-fixture@example.invalid",
        "commit", "--quiet", "-m", f"T15 synthetic command fixture ({file_count} files)",
    )
    fixture_head = _git(worktree, "rev-parse", "HEAD")
    fixture_parent = _git(worktree, "rev-parse", "HEAD^")
    if fixture_parent != source_pin_sha:
        raise RuntimeError("fixture commit parent changed from source pin")
    committed_paths = _git(
        worktree, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"
    ).splitlines()
    if not committed_paths or any(
        path != FIXTURE_DIR and not path.startswith(f"{FIXTURE_DIR}/")
        for path in committed_paths
    ):
        raise RuntimeError("fixture commit includes paths outside the fixture directory")
    if _git(worktree, "status", "--porcelain", "--untracked-files=all"):
        raise RuntimeError("fixture worktree is dirty after fixture commit")

    return {
        "schema": SCHEMA,
        "worktree": str(worktree),
        "source_pin_sha": source_pin_sha,
        "fixture_parent_sha": fixture_parent,
        "fixture_head": fixture_head,
        "file_count": file_count,
        "total_data_bytes": payload_bytes,
        "content_tree_sha256": content_digest.hexdigest(),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "manifest_path": str(manifest_path),
        "clean_after_commit": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--source-pin-sha", required=True)
    parser.add_argument("--file-count", type=int, choices=ALLOWED_FILE_COUNTS, required=True)
    args = parser.parse_args()
    receipt = build_fixture(
        args.worktree,
        source_pin_sha=args.source_pin_sha,
        file_count=args.file_count,
    )
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
