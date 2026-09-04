from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from local_ai_hub.client import HubClient
from local_ai_hub.config import load_config
from local_ai_hub.process_utils import hidden_run_kwargs, terminate_tree


def client() -> HubClient:
    return HubClient(tenant="hubctl", config_path=str(ROOT / "config.toml"))


def status() -> dict:
    c = client()
    if not c._online():
        return {"running": False}
    try:
        data = c.get("/v1/status")
    except Exception:
        data = {}
    data["running"] = True
    return data


def _service(action: str) -> bool:
    service = ROOT / "tools" / "service.py"
    if not service.exists():
        return False
    try:
        completed = subprocess.run([sys.executable, str(service), action], check=False, timeout=20, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **hidden_run_kwargs())
        return completed.returncode == 0
    except Exception:
        return False


def _startup_wait_seconds() -> float:
    """Match the supervisor's cold-start contract, with a bounded probe margin."""
    try:
        grace = float(load_config(str(ROOT / "config.toml")).get("headless", {}).get("startup_grace_seconds", 60.0))
    except Exception:
        grace = 60.0
    return min(120.0, max(12.0, grace + 5.0))


def stop() -> bool:
    # Stop the supervisor/service first; killing only the hub would make the supervisor restart it.
    _service("stop")
    data = status()
    if not data.get("running"):
        return True
    pid = int(data.get("hub_pid", 0) or 0)
    if pid <= 0 or pid == os.getpid():
        return False
    try:
        terminate_tree(pid, grace_seconds=5.0)
    except Exception:
        return False
    deadline = time.time() + 8
    c = client()
    while time.time() < deadline:
        if not c._online():
            return True
        time.sleep(0.15)
    return not c._online()


def start() -> bool:
    if _service("start"):
        deadline = time.time() + _startup_wait_seconds()
        c = client()
        while time.time() < deadline:
            if c._online(): return True
            time.sleep(0.2)
        # A successfully launched managed supervisor owns startup. Do not make the
        # control client race it with a direct spawn after an ordinary cold start.
        return c._online()
    return client().ensure_server()


def main() -> int:
    parser = argparse.ArgumentParser(description="Control the Local AI Hub singleton")
    parser.add_argument("action", choices=["status", "start", "stop", "restart", "watch", "dashboard", "service-status", "agent-state", "cleanup"])
    args = parser.parse_args()
    if args.action == "watch":
        return subprocess.call([sys.executable, str(ROOT / "tools" / "monitor.py")])
    if args.action == "dashboard":
        c = client(); print(c.base_url + "/dashboard"); return 0
    if args.action == "service-status":
        path = Path(load_config(str(ROOT / "config.toml"))["server"]["state_dir"]) / "supervisor.status.json"
        print(path.read_text(encoding="utf-8") if path.exists() else json.dumps({"running": False}, indent=2)); return 0
    if args.action == "agent-state":
        c = client()
        print(json.dumps(c.status(detail="agent_state"), indent=2, ensure_ascii=False))
        return 0
    if args.action == "cleanup":
        c = client()
        res = c.post("/v1/agent-state/cleanup", {})
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0 if res.get("success", True) else 1
    if args.action == "status":
        print(json.dumps(status(), indent=2, ensure_ascii=False))
        return 0
    if args.action == "stop":
        ok = stop(); print("stopped" if ok else "stop failed"); return 0 if ok else 1
    if args.action == "start":
        ok = start(); print("started" if ok else "start failed"); return 0 if ok else 1
    ok = stop()
    if not ok:
        print("restart: stop failed", file=sys.stderr); return 1
    ok = start(); print("restarted" if ok else "restart: start failed"); return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
