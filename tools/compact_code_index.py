"""Dry-run or safely compact the configured SQLite code index while the Hub is offline."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

from local_ai_hub.config import load_config
from local_ai_hub.process_utils import pid_alive, run_hidden
from local_ai_hub.sqlite_support import compact_sqlite_database


def _listener_state(port: int) -> bool | None:
    """Return whether a local TCP listener owns the configured port."""
    if os.name != "nt":
        # A connect timeout is ambiguous on POSIX; do not infer offline state
        # from an optional platform-specific listener utility.
        return None
    try:
        result = run_hidden(
            ["netstat", "-ano", "-p", "tcp"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3.0,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    target_port = str(port)
    for line in (result.stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0].upper() == "TCP" and parts[3].upper() == "LISTENING":
            local_port = parts[1].rsplit(":", 1)[-1]
            if local_port == target_port:
                return True
    return False


def _managed_hub_process_alive(state_dir: Path) -> bool:
    """Fail closed when the Hub or its supervisor still has a live PID."""
    for name in ("hub.pid", "supervisor.pid"):
        path = state_dir / name
        try:
            raw_pid = path.read_text(encoding="ascii").strip()
        except FileNotFoundError:
            continue
        except OSError:
            return True
        if not raw_pid.isdecimal() or int(raw_pid) <= 0:
            return True
        if pid_alive(int(raw_pid)):
            return True
    return False


def _hub_is_online(host: str, port: int, state_dir: Path | None = None) -> bool | None:
    probe_host = "127.0.0.1" if host in {"", "0.0.0.0", "::"} else host
    try:
        with socket.create_connection((probe_host, port), timeout=0.5):
            return True
    except ConnectionRefusedError:
        return False
    except OSError as exc:
        if getattr(exc, "winerror", None) == 10061:
            return False
        if getattr(exc, "errno", None) in {61, 111}:
            return False
        if state_dir is not None:
            listener = _listener_state(port)
            process_alive = _managed_hub_process_alive(state_dir)
            if listener is True or process_alive:
                return True
            if listener is False:
                return False
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="measure only (default)")
    mode.add_argument("--apply", action="store_true", help="run VACUUM after confirming the Hub is offline")
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    args = parser.parse_args(argv)

    try:
        config = load_config(probe_hardware=False)
        server = config.get("server", {})
        state_dir = Path(server["state_dir"])
        database = state_dir / "code-index.sqlite3"
        dry_run = not args.apply
        if args.apply:
            online = _hub_is_online(
                str(server.get("host", "127.0.0.1")),
                int(server.get("port", 11435)),
                state_dir,
            )
            if online is True:
                print(json.dumps({"success": False, "error": "hub_online", "path": str(database)}))
                return 2
            if online is None:
                print(json.dumps({"success": False, "error": "hub_state_unknown", "path": str(database)}))
                return 2
        result: dict[str, Any] = compact_sqlite_database(
            database,
            dry_run=dry_run,
            timeout_seconds=args.timeout_seconds,
            offline_confirmed=bool(args.apply),
        )
    except (OSError, ValueError, KeyError) as exc:
        result = {"success": False, "error": type(exc).__name__}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("success") is True else 2


if __name__ == "__main__":
    sys.exit(main())
