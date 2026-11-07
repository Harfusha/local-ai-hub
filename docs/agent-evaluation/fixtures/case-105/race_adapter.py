"""Disposable revision-race adapter; candidates are not broker receipts."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any


STATE_NAME = "case105-task.json"
TASK_ID = "task_case105_001"
SESSION_ID = "session_case105_001"


def _is_git_root(path: Path) -> bool:
    return any((parent / ".git").exists() or (parent / ".git").is_symlink() for parent in (path, *path.parents))


def _sandbox(value: str | Path) -> Path:
    root = Path(value)
    if not root.is_absolute():
        raise ValueError("sandbox root must be absolute")
    root = root.resolve(strict=True)
    if not root.is_dir() or _is_git_root(root):
        raise ValueError("sandbox root must be a directory outside Git checkouts")
    state_dir = root / "state"
    if state_dir.is_symlink():
        raise ValueError("state directory must not be a symlink")
    state_dir.mkdir(exist_ok=True)
    if not state_dir.resolve(strict=True).is_relative_to(root):
        raise ValueError("state directory must stay inside sandbox root")
    return root


def _read(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise ValueError("task state must not be a symlink")
    if not path.exists():
        raise ValueError("case 105 state is not initialized")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("case 105 state is malformed")
    return payload


def _write(path: Path, payload: dict[str, Any]) -> None:
    fd, temp_name = tempfile.mkstemp(prefix="case105-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def run_action(root: str | Path, action: str, expected_revision: int | None = None) -> dict[str, Any]:
    sandbox = _sandbox(root)
    path = sandbox / "state" / STATE_NAME
    if action == "init":
        if path.exists() or path.is_symlink():
            raise ValueError("case 105 state already initialized")
        state = {
            "task_id": TASK_ID,
            "repo_root": str(sandbox),
            "session_id": SESSION_ID,
            "revision": 1,
            "mutation_generation": 1,
            "status": "planned",
            "candidate": None,
        }
        _write(path, state)
        return {"success": True, "task": state}

    state = _read(path)
    if action == "read":
        return {"success": True, "task": state}
    if action == "prepare_candidate":
        candidate = {key: state[key] for key in ("task_id", "repo_root", "session_id", "revision", "mutation_generation")}
        state["candidate"] = candidate
        _write(path, state)
        return {"success": True, "candidate": candidate, "is_broker_receipt": False}
    if action == "advance_revision":
        if type(expected_revision) is not int or expected_revision != state["revision"]:
            return {"success": False, "conflict": True, "task": state}
        state["revision"] += 1
        state["mutation_generation"] += 1
        _write(path, state)
        return {"success": True, "task": state}
    if action == "attempt_complete":
        candidate = state.get("candidate")
        if not isinstance(candidate, dict):
            return {"success": False, "completed": False, "reason": "candidate_missing", "task": state}
        identity_matches = all(candidate.get(key) == state.get(key) for key in ("task_id", "repo_root", "session_id"))
        fresh = candidate.get("revision") == state["revision"] and candidate.get("mutation_generation") == state["mutation_generation"]
        reason = "stale_candidate" if not identity_matches or not fresh else "no_broker_receipt"
        return {
            "success": False,
            "completed": False,
            "conflict": reason == "stale_candidate",
            "reason": reason,
            "task_status": state["status"],
            "current_revision": state["revision"],
            "current_mutation_generation": state["mutation_generation"],
            "is_broker_receipt": False,
        }
    raise ValueError("unsupported action")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="absolute disposable sandbox root")
    parser.add_argument("action", choices=("init", "read", "prepare_candidate", "advance_revision", "attempt_complete"))
    parser.add_argument("--expected-revision", type=int)
    args = parser.parse_args()
    try:
        result = run_action(args.root, args.action, args.expected_revision)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = {"success": False, "error": str(exc)}
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
