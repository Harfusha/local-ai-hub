"""Local, allowlisted JSON bridge for the Rust desktop. No GUI or listening socket."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from local_ai_hub.client import HubClient
from local_ai_hub.process_utils import hidden_run_kwargs

LIFECYCLE = frozenset({"start", "stop", "restart"})
MODES = ("active", "gaming", "maintenance", "preprocessing")
VIEWS = {
    "Overview": "/api/live/status?light=1&scope=1h",
    "Requests": "/api/live/status?light=1&scope=1h",
    "Commands": "/api/live/status?light=1&scope=1h",
    "Models & search": "/api/live/status?light=1&scope=1h",
    "Runtime health": "/api/live/status?light=1&scope=1h",
    "Settings": "/api/config",
    "Trace index": "/api/debug-traces?limit=100",
    "Projects": "/api/preprocess/status",
    "Tasks": "/api/agent-state/tasks?limit=100",
    "Memory": "/api/agent-state/memory",
    "Incidents": "/api/agent-state/incidents",
    "Activity": "/api/live?limit=50",
    "Service health": "/api/logs/tail?lines=250",
    "Diagnostics": "/api/doctor",
    "Settings — activity mode": "/api/mode",
    "Search workspaces": "/api/rag/workspaces",
    "File leases": "/api/leases",
    "Hardware": "/api/hardware/system",
}
SCOPED = frozenset({"Tasks", "Memory", "Incidents"})
MAINTENANCE = {
    "Optimize databases": ("/api/maintenance/optimize_db", {}),
    "Purge expired cache (7 days)": ("/api/maintenance/purge_cache", {"days": 7}),
    "Cleanup stale agent state": ("/api/agent-state/cleanup", {}),
    "Purge detailed traces": ("/api/debug-traces/purge", {"confirm": True}),
    "Reset all statistics": ("/api/telemetry/endpoint-stats/reset", {"root": "", "purge_telemetry": True}),
}


class HubControl:
    """Explicit, bounded operations only. Reads must never start the service."""

    def __init__(self, config: str | None = None) -> None:
        self.config = config or (str(ROOT / "config.toml") if (ROOT / "config.toml").is_file() else None)

    def _client(self) -> HubClient:
        return HubClient(config_path=self.config, auto_start=False)

    def online(self) -> bool:
        client = self._client()
        try:
            return client._online(timeout=2.0)
        finally:
            client.close()

    def _cli(self, args: tuple[str, ...], timeout: float) -> str:
        env = os.environ.copy()
        if self.config is not None:
            env["LOCAL_AI_CONFIG"] = self.config
        completed = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "hubctl.py"), *args],
            cwd=ROOT, env=env, timeout=timeout, check=False,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            **hidden_run_kwargs(),
        )
        if completed.returncode:
            raise RuntimeError(
                f"Hub command failed (exit {completed.returncode}): "
                + (completed.stderr.strip() or completed.stdout.strip())[-4000:]
            )
        return completed.stdout.strip()

    def lifecycle(self, action: str) -> str:
        if action not in LIFECYCLE:
            raise ValueError("Unsupported lifecycle action")
        if action == "start" and self.online():
            return "Hub is already online."
        # Stop even if unreachable: a managed supervisor may be warming up.
        return self._cli((action,), timeout=760)

    def mode(self, value: str) -> str:
        if value not in MODES:
            raise ValueError("Unsupported activity mode")
        return self._cli(("mode", value), timeout=30)

    def maintenance(self, action: str) -> dict[str, Any]:
        path, payload = MAINTENANCE[action]
        client = self._client()
        try:
            if not client._online(timeout=2.0):
                raise RuntimeError("Hub is not reachable.")
            result = client.post(path, dict(payload), timeout=120.0)
            if result.get("success") is not True:
                raise RuntimeError(str(result.get("error") or "Hub did not confirm completion"))
            return result
        finally:
            client.close()

    def read(self, view: str, root: str = "") -> dict[str, Any]:
        path = VIEWS[view]
        if view in SCOPED:
            if not root.strip():
                raise ValueError("Select an explicit repository root first.")
            root_path = Path(root).expanduser().resolve(strict=True)
            if not root_path.is_dir():
                raise ValueError("Repository root must be a directory.")
            path += ("&" if "?" in path else "?") + urlencode({"root": str(root_path)})
        client = self._client()
        try:
            if not client._online(timeout=2.0):
                raise RuntimeError("Hub is not reachable. Use Start Hub if it is stopped.")
            data = client.get(path, timeout=15.0, requires_heavy_work=False)
            if data.get("success") is False or data.get("outcome_unknown"):
                raise RuntimeError(str(data.get("error") or "Hub request failed"))
            return data
        finally:
            client.close()


def explicit_root(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Select an explicit repository root.")
    path = Path(value).expanduser().resolve(strict=True)
    if not path.is_dir():
        raise ValueError("Repository root must be a directory.")
    return str(path)


def text_field(data: dict[str, Any], key: str, limit: int = 4096) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"Invalid or missing {key}")
    return value.strip()


def checked_post(control: HubControl, route: str, payload: dict[str, Any],
                 timeout: float = 120.0) -> dict[str, Any]:
    client = control._client()
    try:
        if not client._online(timeout=2.0):
            raise RuntimeError("Hub is not reachable. Start Hub first.")
        result = client.post(route, payload, timeout=timeout)
        if result.get("success") is False or result.get("outcome_unknown"):
            raise RuntimeError(str(result.get("error") or "Hub did not confirm the outcome"))
        return result
    finally:
        client.close()


def scoped_read(control: HubControl, route: str, root: str) -> dict[str, Any]:
    client = control._client()
    try:
        if not client._online(timeout=2.0):
            raise RuntimeError("Hub is not reachable.")
        result = client.get(route + "?" + urlencode({"root": root}), timeout=15.0,
                            requires_heavy_work=False)
        if result.get("success") is False:
            raise RuntimeError(str(result.get("error") or "Hub request failed"))
        return result
    finally:
        client.close()


def dispatch(control: HubControl, request: dict[str, Any]) -> Any:
    """No caller-supplied route, executable, shell, or arbitrary action payload."""
    op = request.get("op")
    args = request.get("args", {})
    if not isinstance(args, dict):
        raise ValueError("args must be an object")
    if op == "probe":
        return {"online": control.online()}
    if op == "read":
        return control.read(text_field(args, "view", 100), args.get("root", ""))
    if op == "lifecycle":
        return control.lifecycle(text_field(args, "action", 20))
    if op == "mode":
        return control.mode(text_field(args, "mode", 20))
    if op == "maintenance":
        if args.get("confirmed") is not True:
            raise ValueError("Explicit confirmation required")
        return control.maintenance(text_field(args, "action", 100))
    if op in {"plans", "plan_board", "worktrees", "project_config"}:
        root = explicit_root(args.get("root"))
        if op == "plans":
            return checked_post(control, "/api/coord/plan_list", {"root": root})
        if op == "plan_board":
            return checked_post(control, "/api/coord/plan_board_view",
                                {"root": root, "plan_id": text_field(args, "id", 100)})
        return scoped_read(control, "/api/coord/worktrees" if op == "worktrees"
                           else "/api/project/config", root)
    if op == "semaphores":
        return checked_post(control, "/api/coord/semaphore_status", {})
    if op == "project":
        if args.get("confirmed") is not True:
            raise ValueError("Explicit confirmation required")
        action = text_field(args, "action", 30)
        if action not in {"register", "refresh", "unregister", "pause", "resume"}:
            raise ValueError("Unsupported project action")
        return checked_post(control, "/api/preprocess",
                            {"root": explicit_root(args.get("root")), "action": action,
                             **({"purge_data": False} if action == "unregister" else {})})
    if op == "task":
        if args.get("confirmed") is not True:
            raise ValueError("Explicit confirmation required")
        action = text_field(args, "action", 20)
        if action not in {"get", "complete", "fail"}:
            raise ValueError("Unsupported task action")
        payload = {"root": explicit_root(args.get("root")), "action": action,
                   "task_id": text_field(args, "id", 200)}
        if action != "get":
            payload["reason"] = text_field(args, "reason")
        return checked_post(control, "/api/agent-state/tasks", payload)
    if op in {"task_create", "memory_record", "memory_delete", "plan_create",
              "global_preprocess", "feature"}:
        if args.get("confirmed") is not True:
            raise ValueError("Explicit confirmation required")
        if op == "global_preprocess":
            action = text_field(args, "action", 30)
            if action not in {"pause", "resume", "cleanup_deleted"}:
                raise ValueError("Unsupported preprocessing action")
            return checked_post(control, "/api/preprocess", {"action": action})
        if op == "feature":
            feature = text_field(args, "feature", 100)
            if feature not in {"status", "repo", "tasks", "rag", "commands", "coord",
                               "artifacts", "subagents", "agent_os"} or type(args.get("enabled")) is not bool:
                raise ValueError("Unsupported feature or invalid boolean")
            return checked_post(control, "/api/config/update",
                                {"action": "update", "settings": {f"features.{feature}": args["enabled"]}})
        root = explicit_root(args.get("root"))
        if op == "task_create":
            criteria = text_field(args, "criteria", 12000)
            return checked_post(control, "/api/agent-state/tasks", {"root": root, "action": "create",
                "contract": {"goal": text_field(args, "goal", 12000),
                             "acceptance_criteria": [line.strip() for line in criteria.splitlines() if line.strip()],
                             "scope": "task", "risk_profile": "normal"}})
        if op in {"memory_record", "memory_delete"}:
            payload = {"root": root, "action": "record" if op == "memory_record" else "delete",
                       "key": text_field(args, "key", 200), "scope": "repository"}
            if op == "memory_record":
                raw = text_field(args, "value", 12000)
                try:
                    value = json.loads(raw)
                except ValueError:
                    value = raw
                payload.update({"value": value, "kind": "fact", "confidence": 1.0})
            return checked_post(control, "/api/agent-state/memory", payload)
        import uuid
        return checked_post(control, "/api/coord/plan_create", {"root": root,
            "plan_id": text_field(args, "id", 85), "title": text_field(args, "title", 160),
            "description": "", "lifecycle": "active", "owner": "desktop",
            "idempotency_key": "desktop-" + uuid.uuid4().hex})
    if op == "incident":
        if args.get("confirmed") is not True:
            raise ValueError("Explicit confirmation required")
        return checked_post(control, "/api/agent-state/incidents", {
            "root": explicit_root(args.get("root")), "action": "record",
            "operation_class": text_field(args, "kind", 200),
            "message": text_field(args, "message"),
            "root_cause": args.get("cause", ""), "verified_fix": args.get("fix", ""),
        })
    if op == "telemetry":
        if args.get("confirmed") is not True or args.get("mode") not in {"minimal", "full"}:
            raise ValueError("Explicit confirmation and valid mode required")
        return checked_post(control, "/api/config/update",
                            {"settings": {"telemetry.mode": args["mode"]}})
    if op == "config_reset":
        if args.get("confirmed") is not True:
            raise ValueError("Explicit confirmation required")
        return checked_post(control, "/api/config/update", {"action": "reset"})
    if op == "compare":
        prompt = text_field(args, "prompt", 12000)
        results = {}
        for tier in ("auto", "high"):
            import time
            start = time.monotonic()
            result = checked_post(control, "/api/delegate", {"task": prompt, "complexity": tier},
                                  timeout=360.0)
            results[tier] = {"elapsed_seconds": time.monotonic() - start, "result": result}
        return results
    raise ValueError("Unsupported desktop operation")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bridge", action="store_true", required=True)
    parser.add_argument("--config", default=os.environ.get("LOCAL_AI_CONFIG"))
    args = parser.parse_args()
    # One request per child: no resident Python GUI/runtime while desktop is idle.
    # Never read arbitrary files or execute user-supplied commands.
    try:
        raw = sys.stdin.buffer.read(65537)
        if len(raw) > 65536:
            raise ValueError("Request exceeds 64 KiB")
        request = json.loads(raw)
        if not isinstance(request, dict):
            raise ValueError("Request must be an object")
        config = str(Path(args.config).expanduser().resolve()) if args.config else None
        result = dispatch(HubControl(config), request)
        envelope = {"ok": True, "result": result}
    except Exception as exc:
        envelope = {"ok": False, "error": str(exc)[:4000]}
    try:
        output = json.dumps(envelope, ensure_ascii=True, allow_nan=False)
        if len(output) > 8_000_000:
            output = json.dumps({"ok": False, "error": "Response exceeds desktop limit; narrow scope."})
    except (ValueError, TypeError):
        output = json.dumps({"ok": False, "error": "Invalid Hub response"})
    sys.stdout.write(output + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
