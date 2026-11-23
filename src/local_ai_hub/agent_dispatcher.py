"""Cross-agent task dispatcher for Local AI Hub.

Dispatches pending tasks between major agents (Codex, Claude, OpenCode, Gemini, Antigravity)
using unified Agent OS coordination and verification receipts.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("local_ai_hub.agent_dispatcher")


def get_agent_executable(agent_name: str) -> str | None:
    """Find installed executable for the requested agent."""
    agent_lower = agent_name.lower().strip()
    direct = shutil.which(agent_lower)
    if direct:
        return direct
    if agent_lower == "opencode":
        # Check standard OpenCode installation paths
        candidates = [
            Path.home() / ".opencode" / "bin" / "opencode.exe",
            Path.home() / ".opencode" / "bin" / "opencode",
            Path.home() / "AppData" / "Local" / "opencode" / "opencode.exe",
            Path(os.environ.get("OPENCODE_HOME", "")) / "opencode.exe",
        ]
        for c in candidates:
            if c.is_file():
                return str(c)
    elif agent_lower in ("gemini", "antigravity"):
        candidates = [
            shutil.which("gemini"),
            shutil.which("agy"),
            shutil.which("antigravity"),
        ]
        for c in candidates:
            if c:
                return c
    return None


def execute_agent_task(
    agent_name: str,
    prompt: str,
    root: Path | str,
    *,
    timeout: int = 300,
) -> dict[str, Any]:
    """Execute a task via the specified agent CLI in bounded headless mode."""
    exe = get_agent_executable(agent_name)
    if not exe:
        return {
            "success": False,
            "error": f"Agent executable for '{agent_name}' was not found on PATH",
            "agent": agent_name,
        }

    agent_lower = agent_name.lower().strip()
    root_path = Path(root).resolve()

    if agent_lower == "codex":
        cmd = [exe, "exec", "--full-auto", "-p", prompt]
    elif agent_lower == "claude":
        cmd = [exe, "-p", prompt]
    elif agent_lower == "opencode":
        cmd = [exe, "run", prompt]
    elif agent_lower in ("gemini", "antigravity"):
        cmd = [exe, "--prompt", prompt]
    else:
        cmd = [exe, prompt]

    started = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root_path),
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
        duration = time.monotonic() - started
        return {
            "success": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout[:8000] if proc.stdout else "",
            "stderr": proc.stderr[:4000] if proc.stderr else "",
            "duration_seconds": round(duration, 2),
            "agent": agent_name,
            "executable": exe,
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": f"Agent '{agent_name}' timed out after {timeout} seconds",
            "agent": agent_name,
        }
    except Exception as exc:
        return {
            "success": False,
            "error": f"Agent execution error: {exc}",
            "agent": agent_name,
        }


def poll_and_dispatch_once(root: Path | str) -> list[dict[str, Any]]:
    """Poll Local AI Hub Agent OS tasks and dispatch any assigned cross-agent tasks."""
    from .client import HubClient
    client = HubClient()
    root_str = str(Path(root).resolve())

    resp = client.post("/api/agent-state/tasks", {"root": root_str, "status": "active", "limit": 10})
    if not isinstance(resp, dict) or not resp.get("success"):
        return []

    tasks = resp.get("tasks", [])
    dispatched = []
    for task in tasks:
        task_id = task.get("task_id")
        checkpoint = task.get("checkpoint", {})
        state_data = checkpoint.get("state_data", {})
        assigned_to = state_data.get("assigned_to") or checkpoint.get("assigned_to")
        if assigned_to and not state_data.get("dispatch_completed"):
            goal = task.get("goal") or checkpoint.get("next_action") or f"Execute task {task_id}"
            result = execute_agent_task(assigned_to, goal, root_str)
            dispatched.append({"task_id": task_id, "assigned_to": assigned_to, "result": result})

            # Checkpoint the task with the dispatch result
            client.post("/api/agent-state/tasks/checkpoint", {
                "root": root_str,
                "task_id": task_id,
                "checkpoint": {
                    "phase": "dispatched_completed" if result.get("success") else "dispatch_failed",
                    "next_action": "verify_and_complete" if result.get("success") else "retry_or_reassign",
                    "state_data": {
                        **state_data,
                        "dispatch_completed": True,
                        "dispatch_result": result,
                    },
                },
            })
    return dispatched


def main() -> int:
    parser = argparse.ArgumentParser(description="Local AI Hub Cross-Agent Task Dispatcher")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Repository root")
    parser.add_argument("--once", action="store_true", help="Run one dispatch check and exit")
    parser.add_argument("--agent", type=str, help="Manually dispatch to an agent")
    parser.add_argument("--prompt", type=str, help="Prompt for manual dispatch")
    args = parser.parse_args()

    if args.agent and args.prompt:
        res = execute_agent_task(args.agent, args.prompt, args.root)
        print(json.dumps(res, indent=2))
        return 0 if res.get("success") else 1

    results = poll_and_dispatch_once(args.root)
    print(f"Dispatched {len(results)} task(s).")
    for r in results:
        print(f"Task {r['task_id']} -> {r['assigned_to']}: success={r['result'].get('success')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
