"""Seed an untrusted malformed receipt artifact in a disposable case 098 Hub."""
from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any


def build_fixture_payload(target_task_id: str) -> dict[str, Any]:
    if not isinstance(target_task_id, str) or not re.fullmatch(r"task_[0-9a-f]{12}", target_task_id):
        raise ValueError("valid target task ID required")
    wrong_task_id = "task_000000000000"
    if wrong_task_id == target_task_id:
        wrong_task_id = "task_000000000001"
    return {
        "task_id": wrong_task_id,
        "criterion": "case-103-disposable-check",
        "passed": "true",
        "evidence_id": "fixture-evidence-without-command",
        "repository_revision": "fixture-revision-not-a-git-receipt",
    }


def seed_artifact(sandbox_root: Path, target_task_id: str) -> dict[str, str]:
    if not isinstance(sandbox_root, Path) or not sandbox_root.is_absolute():
        raise ValueError("absolute sandbox root required")
    root = sandbox_root.resolve(strict=True)
    if sandbox_root.is_symlink() or not root.is_dir():
        raise ValueError("physical sandbox root required")
    if any((parent / ".git").exists() for parent in (root, *root.parents)):
        raise ValueError("case 103 sandbox must be outside Git checkouts")
    workspace = root / "workspace"
    state = root / "state"
    config_path = root / "config.toml"
    if (workspace.is_symlink() or state.is_symlink() or not workspace.is_dir()
            or not state.is_dir() or not config_path.is_file()):
        raise ValueError("prepared case 098 sandbox required")
    with config_path.open("rb") as stream:
        config = tomllib.load(stream)
    server = config.get("server", {})
    security = config.get("security", {})
    if (server.get("bind") != "127.0.0.1"
            or type(server.get("port")) is not int
            or server["port"] in (11434, 11435)
            or Path(server.get("state_dir", "")).resolve() != state.resolve()
            or security.get("allowed_roots") != [workspace.resolve().as_posix()]
            or any(key in security for key in ("api_token", "supervisor_token", "action_tokens", "api_token_permissions"))):
        raise ValueError("case 098 isolated tokenless Hub config required")
    source_file = root / "source.txt"
    source = Path(source_file.read_text(encoding="utf-8").strip()).resolve(strict=True)
    if not (source / "src" / "local_ai_hub" / "artifacts.py").is_file():
        raise ValueError("Hub source checkout unavailable")
    sys.path.insert(0, str(source / "src"))
    from local_ai_hub.artifacts import ArtifactStore

    artifact_id = ArtifactStore(state).put_json(
        build_fixture_payload(target_task_id), kind="case-103-invalid-receipt"
    )
    return {"artifact_id": artifact_id, "target_task_id": target_task_id}


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: seed_invalid_receipt.py SANDBOX_ROOT TARGET_TASK_ID")
    try:
        result = seed_artifact(Path(sys.argv[1]), sys.argv[2])
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps({"success": True, **result}, separators=(",", ":")))
