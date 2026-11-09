"""Disposable case-102 mutation adapter; never touches a Hub or Git checkout."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any


COUNTER_NAME = "case102-counter.json"


def _inside_git_checkout(path: Path) -> bool:
    for parent in (path, *path.parents):
        marker = parent / ".git"
        if marker.exists() or marker.is_symlink():
            return True
    return False


def _sandbox_root(value: str | Path) -> Path:
    root = Path(value)
    if not root.is_absolute():
        raise ValueError("sandbox root must be absolute")
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("sandbox root must be a directory")
    if _inside_git_checkout(root):
        raise ValueError("sandbox root must be outside Git checkouts")
    state = (root / "state").resolve(strict=True)
    if not state.is_dir() or not state.is_relative_to(root):
        raise ValueError("state directory must stay inside sandbox root")
    return root


def _read_count(path: Path) -> int:
    if not path.exists():
        return 0
    payload: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or type(payload.get("mutation_count")) is not int:
        raise ValueError("counter state is malformed")
    count = payload["mutation_count"]
    if count < 0:
        raise ValueError("counter state is malformed")
    return count


def _write_count(path: Path, count: int) -> None:
    fd, temp_name = tempfile.mkstemp(prefix="case102-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump({"mutation_count": count}, stream, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def run_action(root: str | Path, action: str) -> dict[str, Any]:
    """Perform one bounded local action; mutation deliberately returns unknown."""
    sandbox = _sandbox_root(root)
    counter = sandbox / "state" / COUNTER_NAME
    if counter.is_symlink():
        raise ValueError("counter state must not be a symlink")
    count = _read_count(counter)
    if action == "read":
        return {"success": True, "mutation_count": count}
    if action != "mutate":
        raise ValueError("unsupported action")
    _write_count(counter, count + 1)
    return {
        "success": False,
        "outcome_unknown": True,
        "terminal": True,
        "retryable": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="absolute disposable sandbox root")
    parser.add_argument("action", choices=("mutate", "read"))
    args = parser.parse_args()
    try:
        result = run_action(args.root, args.action)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = {"success": False, "error": str(exc)}
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
