"""Print identity-verified supervisor-owned Hub PIDs as one JSON object."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from local_ai_hub.config import load_config
from local_ai_hub.process_utils import process_owner_state


def _owned_hub_pid(config_path: str) -> int | None:
    if not isinstance(config_path, str) or "\0" in config_path:
        return None
    try:
        config = load_config(config_path)
    except Exception:
        return None
    if not isinstance(config, dict):
        return None
    server = config.get("server")
    if not isinstance(server, dict):
        return None
    raw_state_dir = server.get("state_dir")
    if not isinstance(raw_state_dir, str) or "\0" in raw_state_dir:
        return None
    try:
        state_dir = Path(raw_state_dir).expanduser().resolve()
        owner_path = state_dir / "hub.owner.json"
        pid_path = state_dir / "hub.pid"
        owner_bytes = owner_path.read_bytes()
        pid_text = pid_path.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, OSError):
        return None
    try:
        owner: Any = json.loads(owner_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(owner, dict) or not pid_text:
        return None
    try:
        pid = int(pid_text)
        owner_pid = owner.get("pid")
    except (TypeError, ValueError):
        return None
    if isinstance(owner_pid, bool) or not isinstance(owner_pid, int) or pid <= 0 or owner_pid != pid:
        return None
    if process_owner_state(owner, state_dir, "hub") != "owned":
        return None

    # Ignore a PID if either owner metadata file changed during identity probing.
    try:
        if owner_path.read_bytes() != owner_bytes or pid_path.read_text(encoding="utf-8").strip() != pid_text:
            return None
    except OSError:
        return None
    return pid


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", action="append", required=True, help="Hub config; repeat for each state directory")
    args = parser.parse_args()
    try:
        pids = sorted({pid for path in args.config if (pid := _owned_hub_pid(path)) is not None})
    except Exception as exc:
        print(json.dumps({"pids": []}, separators=(",", ":")))
        print(f"resolver failed: {type(exc).__name__}", file=sys.stderr)
        return 2
    print(json.dumps({"pids": pids}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
