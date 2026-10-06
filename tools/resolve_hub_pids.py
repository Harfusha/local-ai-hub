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
    config = load_config(config_path)
    state_dir = Path(config["server"]["state_dir"]).expanduser().resolve()
    owner_path = state_dir / "hub.owner.json"
    pid_path = state_dir / "hub.pid"

    try:
        owner_bytes = owner_path.read_bytes()
        pid_text = pid_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    owner: Any = json.loads(owner_bytes)
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
    if owner_path.read_bytes() != owner_bytes or pid_path.read_text(encoding="utf-8").strip() != pid_text:
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
