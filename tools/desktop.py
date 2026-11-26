"""Local, allowlisted JSON bridge for the Rust desktop. No GUI or listening socket."""
from __future__ import annotations

import argparse
import base64
from contextlib import closing
import json
import http.client
import uuid
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, quote

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
    "Tasks": "/api/agent-state/tasks?limit=100&include_stale=true",
    "Memory": "/api/agent-state/memory",
    "Incidents": "/api/agent-state/incidents",
    "Activity": "/api/live?limit=50",
    "Service health": "/api/logs/tail?lines=250",
    "Diagnostics": "/api/doctor",
    "Settings — activity mode": "/api/mode",
    "Search workspaces": "/api/rag/workspaces",
    "File leases": "/api/leases",
    "Hardware": "/api/hardware/system",
    "Model inventory": "/api/models",
    "Endpoint analytics": "/api/telemetry/endpoint-stats",
    "Benchmark": "/api/benchmark/summary",
    "Telemetry report": "/api/telemetry/report",
    "Capabilities": "/api/capabilities",
    "Resident inventory": "/api/status?scope=process",
    "GPU": "/api/hardware/gpu",
    "Audit": "/api/audit/tail",
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


def transfer(control: HubControl, op: str, args: dict[str, Any]) -> dict[str, Any]:
    """Binary-only local API transport; no redirects, retry or arbitrary URLs."""
    if args.get("confirmed") is not True:
        raise ValueError("Explicit confirmation required")
    file = Path(text_field(args, "file", 4096)).expanduser()
    client = control._client()
    connection = None
    created = False
    try:
        if not client._online(timeout=2.0):
            raise RuntimeError("Hub is not reachable.")
        connection = http.client.HTTPConnection("127.0.0.1", client._http_port, timeout=120)
        headers = {"X-LocalAI-Agent": client.agent, "X-LocalAI-Request-ID": "req_" + uuid.uuid4().hex[:12]}
        if op == "bundle_import":
            root = explicit_root(args.get("root"))
            cap = min(512 * 1024 * 1024, max(1024, int(client.config.get("bundles", {}).get("max_bundle_bytes", 128 * 1024 * 1024))))
            if not file.is_file() or file.stat().st_size > cap:
                raise ValueError("Choose an existing ZIP within the configured size limit.")
            with file.open("rb") as stream:
                body = stream.read(cap + 1)
            if len(body) > cap or not body.startswith(b"PK"):
                raise ValueError("Invalid or oversized ZIP.")
            headers["Content-Type"] = "application/zip"
            connection.request("POST", "/api/bundle/import?" + urlencode({"target_root": root}), body, headers)
            response = connection.getresponse()
            raw = response.read(8_000_001)
            if len(raw) > 8_000_000:
                raise RuntimeError("Import response too large; verify outcome before retrying.")
            result = json.loads(raw)
            if response.status != 200 or result.get("success") is not True:
                raise RuntimeError(str(result.get("error") or "Import not confirmed"))
            return result
        if file.exists() or file.is_symlink():
            raise ValueError("Destination exists; select a new filename.")
        root = explicit_root(args.get("root")) if op == "bundle_export" else None
        route = "/api/bundle/export" if op == "bundle_export" else "/api/diagnostics/export"
        headers.update({"Content-Type": "application/json", "Accept": "application/zip"})
        connection.request("POST", route, json.dumps({"root": root} if root else {}).encode(), headers)
        response = connection.getresponse()
        if response.status != 200 or response.getheader("Content-Type", "").split(";")[0] != "application/zip":
            raise RuntimeError(f"Archive export rejected (HTTP {response.status}).")
        password = response.getheader("X-Local-AI-Export-Password")
        if op == "diagnostics_export" and not password:
            raise RuntimeError("Missing support archive password.")
        cap = 512 * 1024 * 1024
        length = int(response.getheader("Content-Length", "0"))
        if length <= 0 or length > cap:
            raise RuntimeError("Invalid or oversized archive length.")
        with file.open("xb") as stream:
            created = True
            received = 0
            while chunk := response.read(65536):
                received += len(chunk)
                if received > length:
                    raise RuntimeError("Archive exceeded announced size.")
                stream.write(chunk)
            if received != length:
                raise RuntimeError("Incomplete archive.")
        result = {"success": True, "file": str(file.resolve()), "bytes": received}
        if password:
            result["archive_password"] = password
        return result
    except Exception:
        if created:
            file.unlink(missing_ok=True)
        raise
    finally:
        if connection is not None:
            connection.close()
        client.close()


def dispatch(control: HubControl, request: dict[str, Any]) -> Any:
    """No caller-supplied route, executable, shell, or arbitrary action payload."""
    op = request.get("op")
    args = request.get("args", {})
    if not isinstance(args, dict):
        raise ValueError("args must be an object")
    if op in {"bundle_import", "bundle_export", "diagnostics_export"}:
        return transfer(control, op, args)
    if op == "task_page":
        root = explicit_root(args.get("root"))
        offset = args.get("offset", 0)
        if type(offset) is not int or not 0 <= offset <= (1 << 31) - 1:
            raise ValueError("Invalid task offset")
        query = args.get("query", "")
        if not isinstance(query, str) or len(query) > 4096:
            raise ValueError("Invalid task query")
        client = control._client()
        try:
            if not client._online(timeout=2.0):
                raise RuntimeError("Hub is not reachable.")
            result = client.get("/api/agent-state/tasks?" + urlencode({
                "root": root, "limit": 100, "offset": offset, "include_stale": "true", "query": query
            }), timeout=15.0, requires_heavy_work=False)
            if result.get("success") is not True:
                raise RuntimeError(str(result.get("error") or "Task page unavailable"))
            return result
        finally:
            client.close()
    if op == "event_page" or op == "event_stream":
        root = explicit_root(args.get("root"))
        stream = text_field(args, "stream", 200)
        cursor = args.get("after", 0)
        if type(cursor) is not int or not 0 <= cursor <= (1 << 63) - 1:
            raise ValueError("Invalid event cursor")
        client = control._client()
        try:
            if not client._online(timeout=2.0):
                raise RuntimeError("Hub is not reachable.")
            if op == "event_page":
                result = client.get("/api/agent-state/events?" + urlencode({
                    "root": root, "stream_id": stream, "after_seq": cursor, "limit": 100,
                }), timeout=15.0, requires_heavy_work=False)
                if result.get("success") is not True:
                    raise RuntimeError(str(result.get("error") or "Event history unavailable"))
                return result
            events: list[dict[str, Any]] = []
            controls: list[dict[str, Any]] = []
            next_seq = cursor
            size = 0
            with closing(client.stream_events(stream_id=stream, after_seq=cursor,
                                              timeout=5.0, root=root)) as stream_events:
                for kind, event in stream_events:
                    if kind in {"error", "replay_error"}:
                        raise RuntimeError(str(event.get("error") or "Event stream disconnected; retry from prior cursor"))
                    if kind in {"stream_timeout", "replay_page", "replay_limit", "replay_cursor_reset",
                                "cursor_reset", "retention_gap", "stream.gap"}:
                        # Keep compact control metadata; replay_page includes the replayed events again.
                        controls.append({"kind": kind, **{k: event[k] for k in (
                            "next_seq", "last_seq", "first_retained_seq", "gap_ranges",
                            "cursor_reset", "requested_after_seq", "has_more") if k in event}})
                        if kind in {"replay_cursor_reset", "cursor_reset"}:
                            next_seq = int(event.get("next_seq", event.get("last_seq", 0)))
                        continue
                    seq = event.get("seq")
                    if type(seq) is not int or seq <= next_seq:
                        continue
                    size += len(json.dumps(event, ensure_ascii=True))
                    if size > 4_000_000:
                        if not events:
                            raise RuntimeError("Single event exceeds desktop response limit")
                        break
                    events.append(event)
                    next_seq = seq
                    if len(events) >= 100:
                        break
            return {"success": True, "events": events, "controls": controls, "next_seq": next_seq}
        finally:
            client.close()
    if op in {"update_status", "update_check", "update_install"}:
        # Native-only fixed local route, with a server-side loopback/non-browser guard.
        if op != "update_status" and args.get("confirmed") is not True:
            raise ValueError("Explicit confirmation required")
        body = None
        if op == "update_check":
            body = {"action": "check"}
        if op == "update_install":
            body = {"action": "install", "version": text_field(args, "version", 50),
                    "revision": text_field(args, "revision", 40), "confirm_restart": True}
        client = control._client()
        connection = None
        try:
            if not client._online(timeout=2.0):
                raise RuntimeError("Hub is not reachable.")
            connection = http.client.HTTPConnection("127.0.0.1", client._http_port, timeout=30)
            headers = {"X-LocalAI-Client": "desktop", "Content-Type": "application/json",
                       "X-LocalAI-Agent": client.agent, "X-LocalAI-Request-ID": "req_" + uuid.uuid4().hex[:12]}
            connection.request("GET" if body is None else "POST", "/api/updates",
                               None if body is None else json.dumps(body).encode(), headers)
            response = connection.getresponse()
            raw = response.read(1_000_001)
            if len(raw) > 1_000_000:
                raise RuntimeError("Update response too large")
            result = json.loads(raw)
            if response.status not in {200, 202} or result.get("success") is not True:
                raise RuntimeError(str(result.get("error") or "Update operation not confirmed"))
            return result
        finally:
            if connection is not None:
                connection.close()
            client.close()
    if op == "vision_review":
        if args.get("confirmed") is not True:
            raise ValueError("Explicit confirmation required")
        prompt = text_field(args, "prompt", 12000)
        file = Path(text_field(args, "file", 4096)).expanduser()
        if not file.is_file() or file.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("Choose an existing PNG or JPEG of at most 8 MiB")
        with file.open("rb") as source:
            raw = source.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError("Image exceeds 8 MiB")
        mime = "image/png" if raw.startswith(b"\\x89PNG\\r\\n\\x1a\\n") else (
            "image/jpeg" if raw.startswith(b"\\xff\\xd8\\xff") else "")
        if not mime:
            raise ValueError("Unsupported image format; choose PNG or JPEG")
        image = "data:" + mime + ";base64," + base64.b64encode(raw).decode("ascii")
        return checked_post(control, "/api/vision/review", {"prompt": prompt, "source": "upload",
                            "image": image}, timeout=360.0)
    if op == "setting":
        if args.get("confirmed") is not True:
            raise ValueError("Explicit confirmation required")
        key = text_field(args, "key", 100)
        value = args.get("value")
        from local_ai_hub.dashboard_contracts import dashboard_settings_patch
        if key in {"monitoring.dashboard_enabled", "features.dashboard"}:
            raise ValueError("Web UI has been retired")
        dashboard_settings_patch({key: value})
        return checked_post(control, "/api/config/update", {"action": "update", "settings": {key: value}})
    if op == "trace_detail":
        trace_id = text_field(args, "id", 200)
        if not all(c.isalnum() or c in "_-" for c in trace_id):
            raise ValueError("Invalid trace identifier")
        client = control._client()
        try:
            if not client._online(timeout=2.0):
                raise RuntimeError("Hub is not reachable.")
            cursor = args.get("after", 0)
            if type(cursor) is not int or cursor < 0:
                raise ValueError("Invalid trace cursor")
            result = client.get("/api/debug-traces/" + quote(trace_id, safe="") + "?" +
                                urlencode({"since_seq": cursor, "limit": 100, "max_bytes": 4_000_000}))
            if result.get("success") is False:
                raise RuntimeError(str(result.get("error") or "Trace unavailable"))
            return result
        finally:
            client.close()
    if op in {"plan_update", "plan_task_edit", "plan_task_move", "plan_task_delete", "lease_release",
              "semaphore_acquire", "semaphore_release", "worktree_prune", "worktree_release", "session_briefing"}:
        if args.get("confirmed") is not True:
            raise ValueError("Explicit confirmation required")
        if op == "lease_release":
            return checked_post(control, "/api/leases/release", {"lease_id": text_field(args, "id", 200)})
        if op == "session_briefing":
            return checked_post(control, "/api/coord/session_briefing", {"agent_id": text_field(args, "id", 200)})
        if op.startswith("semaphore_"):
            payload = {"name": text_field(args, "name", 200)}
            if op == "semaphore_release":
                payload["lease_id"] = text_field(args, "id", 200)
            else:
                capacity = args.get("capacity", 1)
                if type(capacity) is not int or not 1 <= capacity <= 100:
                    raise ValueError("Capacity must be 1–100")
                payload.update({"owner": text_field(args, "id", 200), "capacity": capacity, "ttl_seconds": 300})
            return checked_post(control, "/api/coord/" + op, payload)
        root = explicit_root(args.get("root"))
        if op.startswith("worktree_"):
            payload = {"root": root}
            if op == "worktree_release":
                payload["worktree_path"] = explicit_root(args.get("id"))
            return checked_post(control, "/api/coord/" + op, payload)
        payload = {"root": root, "plan_id": text_field(args, "id", 85),
                   "expected_revision": text_field(args, "revision", 200),
                   "owner": "desktop", "idempotency_key": "desktop-" + uuid.uuid4().hex}
        if op == "plan_update":
            payload.update({"title": text_field(args, "title", 160), "description": str(args.get("description", ""))[:12000]})
        else:
            payload["task_id"] = text_field(args, "task_id", 200)
            if op == "plan_task_edit":
                payload["task_data"] = {"title": text_field(args, "title", 240),
                    "description": str(args.get("description", ""))[:12000]}
            if op == "plan_task_move":
                status = text_field(args, "status", 30)
                if status not in {"planned", "ready", "in_progress", "blocked"}:
                    raise ValueError("Only ordinary work states may be changed here; completion requires evidence")
                payload["task_data"] = {"work_status": status}
                op = "plan_task_edit"
        return checked_post(control, "/api/coord/" + op, payload)
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
        if args.get("confirmed") is not True or args.get("mode") not in {"off", "minimal", "full"}:
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
