"""Local, allowlisted JSON bridge for the Rust desktop. No GUI or listening socket."""
from __future__ import annotations

import argparse
import base64
from contextlib import closing
import json
import http.client
import uuid
import os
import stat
import zipfile
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from local_ai_hub.client import HubClient
from local_ai_hub.process_utils import hidden_run_kwargs

LIFECYCLE = frozenset({"start", "stop", "restart"})
MODES = ("active", "gaming", "maintenance", "preprocessing")
VIEWS = {
    "Overview": "/api/live/status?light=1&scope=1h",
    "Requests": "/api/live/status?light=1&scope=1h",
    "Active requests": "/api/live/status?light=1&scope=1h",
    "Scheduler queue": "/api/live/status?light=1&scope=1h",
    "Scheduler running": "/api/live/status?light=1&scope=1h",
    "Recovery journal": "/api/live/status?light=1&scope=1h",
    "Async jobs": "/api/live/status?light=1&scope=1h",
    "Work orders": "/api/live/status?light=1&scope=1h",
    "Laya": "/api/live/status?light=1&scope=1h",
    "Commands": "/api/live/status?light=1&scope=1h",
    "Process sessions": "/api/live/status?light=1&scope=1h",
    "Recent errors": "/api/live/status?light=1&scope=1h",
    "Models & search": "/api/live/status?light=1&scope=1h",
    "Model statistics": "/api/live/status?light=1&scope=1h",
    "Execution profiles": "/api/live/status?light=1&scope=1h",
    "Cache layers": "/api/live/status?light=1&scope=1h",
    "Agent statistics": "/api/live/status?light=1&scope=1h",
    "Execution routes": "/api/live/status?light=1&scope=1h",
    "Laya capture": "/api/live/status?light=1&scope=1h",
    "Runtime health": "/api/live/status?light=1&scope=1h",
    "Settings": "/api/config",
    "Trace index": "/api/debug-traces?limit=100",
    "Projects": "/api/preprocess/status",
    "Tasks": "/api/agent-state/tasks?limit=100&include_stale=true",
    "Memory": "/api/agent-state/memory",
    "Incidents": "/api/agent-state/incidents",
    "Activity": "/api/live?limit=50",
    "Service health": "/api/logs/tail?lines=250",
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
SCOPED = frozenset({"Tasks", "Memory", "Incidents", "File leases"})
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

    def _cli(self, args: tuple[str, ...], timeout: float, *, structured: bool = False) -> Any:
        env = os.environ.copy()
        if self.config is not None:
            env["LOCAL_AI_CONFIG"] = self.config
        completed = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "hubctl.py"), *args],
            cwd=ROOT, env=env, timeout=timeout, check=False,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            **hidden_run_kwargs(),
        )
        if structured:
            output = completed.stdout.strip()
            try:
                report = json.loads(output)
            except ValueError:
                report = {"output": output[-200_000:]}
            return {"success": completed.returncode == 0 and not (
                        isinstance(report, dict) and report.get("success") is False),
                    "exit_code": completed.returncode, "report": report,
                    "stderr": completed.stderr.strip()[-4000:]}
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

    def read(self, view: str, root: str = "", period: str = "process") -> dict[str, Any]:
        path = VIEWS[view]
        if period not in {"process", "window"}:
            raise ValueError("Invalid metrics period")
        if path.startswith("/api/live/status?"):
            path = "/api/live/status?" + urlencode({"light": 1, "scope": period})
        if view in SCOPED or (view == "Endpoint analytics" and root.strip()):
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


def memory_scope_fields(args: dict[str, Any]) -> dict[str, Any]:
    """Select exactly one scope; never infer a narrower identity from a key."""
    from local_ai_hub.agent_identity import AgentScope
    scope = AgentScope(args.get("scope", "repository")).value
    payload = {"root": explicit_root(args.get("root")), "scope": scope}
    field = {"task": "task_id", "session": "session_id", "clone": "clone_id",
             "worktree": "worktree_id", "branch": "branch"}.get(scope)
    if field:
        payload[field] = text_field(args, field, 200)
    return payload


def plan_text_patch(args: dict[str, Any], *, task: bool, create: bool = False) -> dict[str, Any]:
    """Validate explicit plan fields without replacing omitted data or clipping edits."""
    result: dict[str, Any] = {}
    if create or "title" in args:
        title = args.get("title")
        if (not isinstance(title, str) or not title.strip()
                or len(title) > (240 if task else 160)):
            raise ValueError("Invalid plan title")
        result["title"] = title
    for key, limit in (("description", 12000), ("next_action", 2000),
                       ("accountable_role", 2000), ("blocker", 2000)):
        if key not in args or (not task and key != "description"):
            continue
        value = args[key]
        if not isinstance(value, str) or len(value) > limit:
            raise ValueError(f"Invalid plan field: {key}")
        result[key] = (value or None) if key in {"blocker", "accountable_role"} else value
    if task and "criteria" in args:
        criteria = args["criteria"]
        if not isinstance(criteria, str) or len(criteria) > 12000:
            raise ValueError("Invalid plan acceptance criteria")
        result["acceptance_criteria"] = [line.strip() for line in criteria.splitlines() if line.strip()]
    if not result:
        raise ValueError("No plan fields supplied")
    return result


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


class BoundedArchiveBody:
    """Read exactly the announced bytes without retaining a whole ZIP in RAM."""

    def __init__(self, stream: Any, length: int) -> None:
        self.stream = stream
        self.remaining = length

    def read(self, size: int = 65536) -> bytes:
        if self.remaining == 0:
            return b""
        chunk = self.stream.read(min(self.remaining, size if size > 0 else 65536, 65536))
        if not chunk:
            raise RuntimeError("Archive changed during upload; verify outcome before retrying.")
        self.remaining -= len(chunk)
        return chunk


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
            if not file.is_file():
                raise ValueError("Choose an existing ZIP within the configured size limit.")
            with file.open("rb") as stream:
                observed = os.fstat(stream.fileno())
                length = observed.st_size
                if not stat.S_ISREG(observed.st_mode) or not 22 <= length <= cap:
                    raise ValueError("Invalid or oversized ZIP.")
                if not zipfile.is_zipfile(stream):
                    raise ValueError("Invalid ZIP archive.")
                stream.seek(0)
                body = BoundedArchiveBody(stream, length)
                headers.update({"Content-Type": "application/zip", "Content-Length": str(length)})
                connection.request("POST", "/api/bundle/import?" + urlencode({"target_root": root}), body, headers)
                if body.remaining:
                    raise RuntimeError("Incomplete archive upload; verify outcome before retrying.")
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
        # Exclusive creation preserves no-overwrite semantics and requests owner-only permissions on POSIX.
        with os.fdopen(os.open(file, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600), "wb") as stream:
            created = True
            received = 0
            while chunk := response.read(65536):
                received += len(chunk)
                if received > length:
                    raise RuntimeError("Archive exceeded announced size.")
                stream.write(chunk)
            if received != length:
                raise RuntimeError("Incomplete archive.")
        # HTTP success and matching length alone cannot prove the payload is
        # an archive; reject malformed transfers without decompressing data.
        if not zipfile.is_zipfile(file):
            raise RuntimeError("Server returned an invalid ZIP archive.")
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
    if op in {"operator_catalog", "operator_run"}:
        from tools.desktop_operator import build_argv, catalog
        if op == "operator_catalog":
            return catalog()
        argv, spec = build_argv(args)
        return control._cli(argv, timeout=spec.timeout, structured=True)
    if op in {"bundle_import", "bundle_export", "diagnostics_export"}:
        return transfer(control, op, args)
    if op == "doctor":
        result = checked_post(control, "/api/doctor", {}, timeout=120.0)
        if result.get("success") is not True or not isinstance(result.get("checks"), list):
            raise RuntimeError("Invalid diagnostics report")
        return result
    if op == "timeline_page":
        before = args.get("before", 0)
        limit = args.get("limit", 100)
        if type(before) is not int or not 0 <= before <= (1 << 63) - 1:
            raise ValueError("Invalid telemetry cursor")
        if type(limit) is not int or limit not in (50, 100, 250):
            raise ValueError("Invalid telemetry page size")
        query = {"limit": limit, **({"before_id": before} if before else {})}
        client = control._client()
        try:
            if not client._online(timeout=2.0):
                raise RuntimeError("Hub is not reachable.")
            result = client.get("/api/telemetry/timeline?" + urlencode(query),
                                timeout=15.0, requires_heavy_work=False)
            if result.get("success") is not True:
                raise RuntimeError(str(result.get("error") or "Telemetry history unavailable"))
            rows = result.get("timeline")
            more = result.get("has_more")
            cursor = result.get("next_cursor")
            if not isinstance(rows, list) or len(rows) > limit or type(more) is not bool:
                raise RuntimeError("Malformed telemetry page")
            ids = [row.get("id") if isinstance(row, dict) else None for row in rows]
            if (any(type(item) is not int or item <= 0 or (before and item >= before) for item in ids)
                    or ids != sorted(set(ids))
                    or (more and (not ids or type(cursor) is not int or cursor != ids[0]))
                    or (not more and cursor is not None)):
                raise RuntimeError("Malformed telemetry cursor sequence")
            return result
        finally:
            client.close()
    if op == "log_tail":
        lines = args.get("lines", 250)
        if type(lines) is not int or lines not in {100, 250, 500}:
            raise ValueError("Log tail requires 100, 250 or 500 lines")
        client = control._client()
        try:
            if not client._online(timeout=2.0):
                raise RuntimeError("Hub is not reachable.")
            result = client.get("/api/logs/tail?" + urlencode({"lines": lines}),
                                timeout=15.0, requires_heavy_work=False)
            if result.get("success") is not True or result.get("outcome_unknown"):
                raise RuntimeError(str(result.get("error") or "Log tail unavailable"))
            entries = result.get("lines")
            if (not isinstance(entries, list) or len(entries) > lines
                    or any(not isinstance(line, str) for line in entries)):
                raise RuntimeError("Invalid log tail response")
            return result
        finally:
            client.close()
    if op == "trace_page":
        offset = args.get("offset", 0)
        minimum = args.get("min_duration_ms", 0)
        if type(offset) is not int or not 0 <= offset <= (1 << 31) - 1:
            raise ValueError("Invalid trace offset")
        if type(minimum) is not int or not 0 <= minimum <= 86400000:
            raise ValueError("Invalid trace duration")
        params: dict[str, Any] = {"limit": 100, "offset": offset, "min_duration_ms": minimum}
        for key in ("kind", "state", "agent", "model", "action"):
            value = args.get(key, "")
            if not isinstance(value, str) or len(value) > (64 if key == "action" else 200):
                raise ValueError("Invalid trace filter: " + key)
            if value:
                params[key] = value
        client = control._client()
        try:
            if not client._online(timeout=2.0):
                raise RuntimeError("Hub is not reachable.")
            result = client.get("/api/debug-traces?" + urlencode(params), timeout=15.0, requires_heavy_work=False)
            if result.get("success") is not True:
                raise RuntimeError(str(result.get("error") or "Trace page unavailable"))
            return result
        finally:
            client.close()
    if op == "task_page":
        root = explicit_root(args.get("root"))
        offset = args.get("offset", 0)
        if type(offset) is not int or not 0 <= offset <= (1 << 31) - 1:
            raise ValueError("Invalid task offset")
        query = args.get("query", "")
        if not isinstance(query, str) or len(query) > 4096:
            raise ValueError("Invalid task query")
        from local_ai_hub.agent_tasks import TaskStatus
        status = args.get("status", "")
        if type(status) is not str or (status and status not in {item.value for item in TaskStatus}):
            raise ValueError("Invalid task status filter")
        limit = args.get("limit", 100)
        if type(limit) is not int or limit not in (25, 50, 100, 250):
            raise ValueError("Invalid task page size")
        client = control._client()
        try:
            if not client._online(timeout=2.0):
                raise RuntimeError("Hub is not reachable.")
            result = client.get("/api/agent-state/tasks?" + urlencode({
                "root": root, "limit": limit, "offset": offset, "include_stale": "true", "query": query,
                **({"status": status} if status else {}),
            }), timeout=15.0, requires_heavy_work=False)
            if result.get("success") is not True:
                raise RuntimeError(str(result.get("error") or "Task page unavailable"))
            rows, more, next_offset = result.get("tasks"), result.get("has_more"), result.get("next_offset")
            if (not isinstance(rows, list) or len(rows) > limit or type(more) is not bool
                    or type(next_offset) is not int or not offset <= next_offset <= (1 << 31) - 1
                    or result.get("offset") != offset or result.get("limit") != limit):
                raise RuntimeError("Malformed task page")
            # Incomplete bounded scans can report has_more but make no progress.
            # Preserve that evidence without looping or guessing an offset.
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
                        checkpoint = event.get("next_seq", event.get("last_seq"))
                        if type(checkpoint) is int and checkpoint >= 0:
                            if kind in {"replay_cursor_reset", "cursor_reset"}:
                                next_seq = checkpoint
                                events.clear()
                                size = 0
                            elif kind != "replay_limit":
                                next_seq = max(next_seq, checkpoint)
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
        mime = "image/png" if raw.startswith(b"\x89PNG\r\n\x1a\n") else (
            "image/jpeg" if raw.startswith(b"\xff\xd8\xff") else "")
        if not mime:
            raise ValueError("Unsupported image format; choose PNG or JPEG")
        image = "data:" + mime + ";base64," + base64.b64encode(raw).decode("ascii")
        return checked_post(control, "/api/vision/review", {"prompt": prompt, "source": "upload",
                            "image": image}, timeout=360.0)
    if op in {"async_job", "work_order"}:
        action = text_field(args, "action", 20)
        if action not in ({"status", "result", "cancel"} if op == "async_job" else {"status", "get", "cancel", "continue"}):
            raise ValueError("Unsupported work action")
        if action in {"cancel", "continue"} and args.get("confirmed") is not True:
            raise ValueError("Explicit confirmation required")
        payload = {"action": action, "job_id" if op == "async_job" else "work_id": text_field(args, "id", 200)}
        if action == "continue":
            payload["answer"] = text_field(args, "answer", 12000)
        return checked_post(control, "/api/async-jobs" if op == "async_job" else "/api/work-orders", payload)
    if op == "settings_batch":
        if args.get("confirmed") is not True:
            raise ValueError("Explicit confirmation required")
        settings = args.get("settings")
        from local_ai_hub.dashboard_contracts import dashboard_settings_patch
        if not isinstance(settings, dict) or not settings or len(settings) > 20:
            raise ValueError("Choose 1–20 settings")
        if set(settings) & {"features.dashboard", "monitoring.dashboard_enabled", "telemetry.mode"}:
            raise ValueError("Retired web settings and live telemetry are not part of this batch")
        dashboard_settings_patch(settings)
        return checked_post(control, "/api/config/update", {"action": "update", "settings": settings})
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
    if op in {"trace_detail", "trace_content", "trace_metrics", "trace_export"}:
        trace_id = text_field(args, "id", 200)
        if not all(c.isascii() and (c.isalnum() or c in "_-") for c in trace_id):
            raise ValueError("Invalid trace identifier")
        after, before, offset = (args.get(k, 0) for k in ("after", "before", "offset"))
        if any(type(v) is not int or not 0 <= v <= (1 << 63) - 1 for v in (after, before, offset)):
            raise ValueError("Invalid trace cursor")
        if before and after:
            raise ValueError("Choose either the before or after cursor")
        query = {"since_seq": after, "before_seq": before, "limit": 100, "max_bytes": 4_000_000}
        suffix = ""
        if op == "trace_content":
            if args.get("confirmed") is not True:
                raise ValueError("Explicit confirmation required")
            field = text_field(args, "field", 32)
            if field not in {"request", "effective_payload", "output", "response"}:
                if not (field.startswith("event:") and field[6:].isascii() and field[6:].isdigit()):
                    raise ValueError("Invalid trace content field")
            query = {"full": 1, "content_field": field, "content_offset": offset, "limit": 1}
        elif op == "trace_metrics":
            suffix, query = "/metrics", {}
        elif op == "trace_export":
            if args.get("confirmed") is not True:
                raise ValueError("Explicit confirmation required")
            file = Path(text_field(args, "file", 4096)).expanduser()
            if file.exists() or file.is_symlink():
                raise ValueError("Destination exists; choose a new filename")
            suffix = "/export"
        client = control._client()
        try:
            if not client._online(timeout=2.0):
                raise RuntimeError("Hub is not reachable.")
            route = "/api/debug-traces/" + quote(trace_id, safe="") + suffix
            result = client.get(route + "?" + urlencode(query), timeout=30.0, requires_heavy_work=False)
            if result.get("success") is not True:
                raise RuntimeError(str(result.get("error") or "Trace unavailable"))
            if op == "trace_export":
                if result.get("redacted_export") is not True:
                    raise RuntimeError("Server did not certify redacted export")
                raw = json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8")
                created = False
                try:
                    with file.open("xb") as stream:
                        created = True
                        stream.write(raw)
                except Exception:
                    if created:
                        file.unlink(missing_ok=True)
                    raise
                return {"success": True, "file": str(file.resolve()), "bytes": len(raw),
                        "has_more": result.get("has_more"), "next_seq": result.get("next_seq")}
            return result
        finally:
            client.close()
    if op == "session_briefing":
        root = explicit_root(args.get("root"))
        include = args.get("include", ["board", "plans", "active_tasks"])
        if (not isinstance(include, list) or not include
                or any(type(item) is not str or item not in {"board", "plans", "active_tasks"} for item in include)
                or len(include) != len(set(include))):
            raise ValueError("Invalid session briefing sections")
        return checked_post(control, "/api/coord/session_briefing", {"root": root, "include": include})
    if op in {"plan_update", "plan_archive", "plan_task_create", "plan_task_edit", "plan_task_move", "plan_task_delete", "lease_release",
              "semaphore_acquire", "semaphore_release", "worktree_prune", "worktree_release"}:
        if args.get("confirmed") is not True:
            raise ValueError("Explicit confirmation required")
        if op == "lease_release":
            root = explicit_root(args.get("root"))
            lease_id, owner = text_field(args, "id", 200), text_field(args, "owner", 200)
            observed = scoped_read(control, "/api/leases", root)
            rows = observed.get("leases")
            if not isinstance(rows, list) or not any(
                isinstance(row, dict) and row.get("lease_id") == lease_id and row.get("owner") == owner
                for row in rows
            ):
                raise ValueError("Lease and owner not present in selected repository; reload inventory")
            result = checked_post(control, "/api/leases/release", {"lease_id": lease_id, "owner": owner})
            if (result.get("success") is not True or type(result.get("released_rows")) is not int
                    or result["released_rows"] < 1):
                raise RuntimeError("Lease release not confirmed; lease may already be gone")
            return result
        if op.startswith("semaphore_"):
            payload = {"name": text_field(args, "name", 200)}
            if op == "semaphore_release":
                payload["lease_id"] = text_field(args, "id", 200)
                payload["owner"] = text_field(args, "owner", 200)
            else:
                capacity = args.get("capacity", 1)
                if type(capacity) is not int or not 1 <= capacity <= 100:
                    raise ValueError("Capacity must be 1–100")
                payload.update({"owner": text_field(args, "id", 200), "capacity": capacity, "ttl_seconds": 300})
            result = checked_post(control, "/api/coord/" + op, payload)
            if op == "semaphore_release" and result.get("released") is not True:
                raise RuntimeError("Semaphore lease was not released; check exact owner and lease")
            return result
        root = explicit_root(args.get("root"))
        if op.startswith("worktree_"):
            payload = {"root": root}
            if op == "worktree_release":
                payload["worktree_path"] = explicit_root(args.get("id"))
            return checked_post(control, "/api/coord/" + op, payload)
        payload = {"root": root, "plan_id": text_field(args, "id", 85),
                   "expected_revision": text_field(args, "revision", 200),
                   "owner": "desktop", "idempotency_key": "desktop-" + uuid.uuid4().hex}
        if op == "plan_archive":
            return checked_post(control, "/api/coord/plan_archive", payload)
        if op == "plan_update":
            payload.update(plan_text_patch(args, task=False))
        else:
            payload["task_id"] = text_field(args, "task_id", 200)
            if op == "plan_task_move":
                status = text_field(args, "status", 30)
                if status not in {"planned", "ready", "in_progress", "blocked"}:
                    raise ValueError("Only ordinary work states may be changed here; completion requires evidence")
            else:
                status = ""
            # plan_task_edit is an upsert. Fence both creation and mutations
            # using the exact observed document and revision, so edit/move
            # cannot accidentally create a new card with a mistyped ID.
            current = checked_post(control, "/api/coord/plan_get",
                                   {"root": root, "plan_id": payload["plan_id"]})
            plan = current.get("plan")
            if (current.get("success") is not True
                    or current.get("file_revision") != payload["expected_revision"]
                    or not isinstance(plan, dict) or plan.get("id") != payload["plan_id"]
                    or not isinstance(plan.get("tasks"), dict)):
                raise ValueError("Plan changed or unavailable; reload exact plan revision")
            exists = payload["task_id"] in plan["tasks"]
            if op == "plan_task_create" and exists:
                raise ValueError("Task ID already exists; load it for editing instead")
            if op != "plan_task_create" and not exists:
                raise ValueError("Task ID not found in reviewed plan revision")
            if op in {"plan_task_create", "plan_task_edit"}:
                data = plan_text_patch(args, task=True, create=op == "plan_task_create")
                if op == "plan_task_create":
                    data.update({"kind": "code", "work_status": "planned", "depends_on": [], "clarifications": []})
                    op = "plan_task_edit"
                payload["task_data"] = data
            if op == "plan_task_move":
                payload["task_data"] = {"work_status": status}
                op = "plan_task_edit"
        return checked_post(control, "/api/coord/" + op, payload)
    if op == "probe":
        return {"online": control.online()}
    if op == "read":
        return control.read(text_field(args, "view", 100), args.get("root", ""), args.get("period", "process"))
    if op == "lifecycle":
        action = text_field(args, "action", 20)
        if action != "start" and args.get("confirmed") is not True:
            raise ValueError("Explicit confirmation required")
        return control.lifecycle(action)
    if op == "mode":
        if args.get("confirmed") is not True:
            raise ValueError("Explicit confirmation required")
        return control.mode(text_field(args, "mode", 20))
    if op == "maintenance":
        if args.get("confirmed") is not True:
            raise ValueError("Explicit confirmation required")
        return control.maintenance(text_field(args, "action", 100))
    if op in {"plans", "plan_board", "plan_detail", "plan_validate", "worktrees", "project_config"}:
        root = explicit_root(args.get("root"))
        if op in {"plans", "plan_board"}:
            query = args.get("query", "")
            if not isinstance(query, str) or len(query) > 1000:
                raise ValueError("Invalid plan search")
            payload = {"root": root, "query": query}
            if op == "plans":
                limit = args.get("limit", 100)
                if type(limit) is not int or limit not in (25, 100, 250):
                    raise ValueError("Invalid plan list limit")
                lifecycle = args.get("lifecycle", "")
                if lifecycle not in ("", "draft", "active", "paused", "completed", "archived", "cancelled"):
                    raise ValueError("Invalid plan lifecycle")
                payload["limit"] = limit
                if lifecycle:
                    payload["lifecycle"] = lifecycle
                result = checked_post(control, "/api/coord/plan_list", payload)
                result["desktop_list_limit"] = limit
                return result
            plan_id = args.get("id", "")
            if not isinstance(plan_id, str) or len(plan_id) > 85:
                raise ValueError("Invalid plan ID")
            if plan_id.strip():
                payload["plan_id"] = plan_id.strip()
            return checked_post(control, "/api/coord/plan_board_view", payload)
        if op in {"plan_detail", "plan_validate"}:
            return checked_post(control, "/api/coord/" + ("plan_get" if op == "plan_detail" else "plan_validate"),
                                {"root": root, "plan_id": text_field(args, "id", 85)})
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
        purge = args.get("purge_data", False)
        if type(purge) is not bool or (purge and action != "unregister"):
            raise ValueError("Invalid project purge option")
        return checked_post(control, "/api/preprocess",
                            {"root": explicit_root(args.get("root")), "action": action,
                             **({"purge_data": purge} if action == "unregister" else {})})
    if op == "memory_find":
        from local_ai_hub.agent_identity import MemoryStatus
        payload = memory_scope_fields(args)
        query = args.get("query", "")
        key = args.get("key", "")
        status = args.get("status", "")
        limit = args.get("limit", 100)
        if not isinstance(query, str) or len(query) > 2000 or "\x00" in query:
            raise ValueError("Invalid memory search")
        if not isinstance(key, str) or len(key) > 200 or "\x00" in key:
            raise ValueError("Invalid memory key filter")
        if type(status) is not str or (status and status not in {item.value for item in MemoryStatus}):
            raise ValueError("Invalid memory status filter")
        if type(limit) is not int or limit not in (25, 50, 100):
            raise ValueError("Invalid memory result limit")
        payload.update({"action": "find", "query": query, "limit": limit})
        if key:
            payload["key"] = key
        if status:
            payload["status"] = status
        return checked_post(control, "/api/agent-state/memory", payload)
    if op in {"memory_get", "memory_quarantine"}:
        payload = memory_scope_fields(args)
        record_id = text_field(args, "record_id", 200)
        payload.update({"record_id": record_id, "action": "get"})
        if op == "memory_quarantine":
            if args.get("confirmed") is not True:
                raise ValueError("Explicit confirmation required")
            if payload["scope"] == "worktree":
                raise ValueError("Worktree mutation requires independently verified scope")
            payload.update({"action": "quarantine", "reason": text_field(args, "reason", 4096)})
        result = checked_post(control, "/api/agent-state/memory", payload)
        record = result.get("record")
        if (result.get("success") is not True or not isinstance(record, dict)
                or record.get("record_id") != record_id or record.get("scope") != payload["scope"]
                or (op == "memory_quarantine" and record.get("status") != "quarantined")):
            raise RuntimeError("Memory operation not confirmed for exact scoped record")
        return result
    if op == "task_gate":
        return checked_post(control, "/api/agent-state/verification", {
            "root": explicit_root(args.get("root")), "action": "completion",
            "task_id": text_field(args, "id", 200),
        })
    if op == "endpoint_reset":
        if args.get("confirmed") is not True:
            raise ValueError("Explicit confirmation required")
        root = args.get("root", "")
        if not isinstance(root, str):
            raise ValueError("Invalid repository root")
        if not root.strip() and args.get("global") is not True:
            raise ValueError("Global reset requires explicit global scope")
        result = checked_post(control, "/api/telemetry/endpoint-stats/reset",
                              {"root": explicit_root(root) if root.strip() else ""})
        if result.get("reset") is not True:
            raise RuntimeError("Statistics store did not confirm reset")
        return result
    if op == "task":
        if args.get("confirmed") is not True:
            raise ValueError("Explicit confirmation required")
        action = text_field(args, "action", 20)
        if action not in {"get", "complete", "fail", "transition"}:
            raise ValueError("Unsupported task action")
        payload = {"root": explicit_root(args.get("root")), "action": action,
                   "task_id": text_field(args, "id", 200)}
        if action != "get":
            payload["reason"] = text_field(args, "reason")
        if action == "transition":
            target = args.get("status")
            if target not in {"active", "verifying", "blocked", "planned", "waiting", "cancelled", "abandoned"}:
                raise ValueError("Unsupported task transition")
            payload["status"] = target
        result = checked_post(control, "/api/agent-state/tasks", payload)
        task = result.get("task")
        if (result.get("success") is not True or not isinstance(task, dict)
                or task.get("task_id") != payload["task_id"]):
            raise RuntimeError("Task operation not confirmed for exact task")
        expected = {"complete": "completed", "fail": "failed", "transition": payload.get("status")}.get(action)
        if expected is not None and task.get("status") != expected:
            raise RuntimeError("Task operation returned an unexpected status")
        return result
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
            from local_ai_hub.agent_identity import AgentScope
            scope, risk = args.get("scope", "task"), args.get("risk", "normal")
            if (type(scope) is not str or scope not in {item.value for item in AgentScope}
                    or type(risk) is not str or risk not in {"low", "normal", "high", "critical"}):
                raise ValueError("Invalid task scope or risk")
            contract: dict[str, Any] = {"goal": text_field(args, "goal", 12000), "scope": scope, "risk_profile": risk}
            for source, field in (("criteria", "acceptance_criteria"), ("non_goals", "non_goals"),
                                  ("constraints", "constraints")):
                value = args.get(source, "")
                if not isinstance(value, str) or len(value) > 12000 or "\x00" in value:
                    raise ValueError(f"Invalid task {field}")
                contract[field] = [line.strip() for line in value.splitlines() if line.strip()]
            description = args.get("description", "")
            slo = args.get("slo", "")
            if not isinstance(description, str) or len(description) > 12000 or "\x00" in description:
                raise ValueError("Invalid task description")
            if not isinstance(slo, str) or len(slo) > 12000:
                raise ValueError("Invalid task SLO profile")
            profile = json.loads(slo) if slo.strip() else {}
            if not isinstance(profile, dict):
                raise ValueError("Task SLO profile must be a JSON object")
            contract.update({"description": description, "slo_profile": profile})
            result = checked_post(control, "/api/agent-state/tasks", {"root": root, "action": "create",
                "contract": contract})
            task = result.get("task")
            if (result.get("success") is not True or not isinstance(task, dict)
                    or not isinstance(task.get("task_id"), str) or not task["task_id"]
                    or task.get("status") != "planned"):
                raise RuntimeError("Task creation not confirmed")
            return result
        if op in {"memory_record", "memory_delete"}:
            from local_ai_hub.agent_identity import MemoryKind
            payload = memory_scope_fields(args)
            payload["action"] = "record" if op == "memory_record" else "delete"
            if op == "memory_record":
                payload["key"] = text_field(args, "key", 200)
                raw = text_field(args, "value", 12000)
                try:
                    value = json.loads(raw)
                except ValueError:
                    value = raw
                payload.update({"value": value, "kind": MemoryKind(args.get("kind", "fact")).value, "confidence": 1.0})
            else:
                if payload["scope"] == "worktree":
                    raise ValueError("Worktree deletion requires a verified scope; use the authorized Hub route")
                payload["record_id"] = text_field(args, "record_id", 200)
            return checked_post(control, "/api/agent-state/memory", payload)
        return checked_post(control, "/api/coord/plan_create", {"root": root,
            "plan_id": text_field(args, "id", 85), **plan_text_patch(args, task=False, create=True),
            "lifecycle": "active", "owner": "desktop",
            "idempotency_key": "desktop-" + uuid.uuid4().hex})
    if op == "incident_list":
        root = explicit_root(args.get("root"))
        status = args.get("status", "")
        limit = args.get("limit", 100)
        if type(status) is not str or status not in {"", "ignored", "resolved", "unresolved"}:
            raise ValueError("Invalid incident status")
        if type(limit) is not int or limit not in (25, 50, 100):
            raise ValueError("Invalid incident result limit")
        client = control._client()
        try:
            if not client._online(timeout=2.0):
                raise RuntimeError("Hub is not reachable.")
            query = {"root": root, "limit": limit, **({"status": status} if status else {})}
            result = client.get("/api/agent-state/incidents?" + urlencode(query),
                                timeout=15.0, requires_heavy_work=False)
            if result.get("success") is not True or not isinstance(result.get("incidents"), list):
                raise RuntimeError("Incident inventory unavailable")
            if len(result["incidents"]) > limit:
                raise RuntimeError("Malformed incident inventory")
            return result
        finally:
            client.close()
    if op == "incident_find":
        query = text_field(args, "query", 2000)
        limit = args.get("limit", 100)
        if type(limit) is not int or limit not in (25, 50, 100):
            raise ValueError("Invalid incident result limit")
        result = checked_post(control, "/api/agent-state/incidents", {
            "root": explicit_root(args.get("root")), "action": "find",
            "query": query, "limit": limit,
        })
        if (result.get("success") is not True or not isinstance(result.get("incidents"), list)
                or len(result["incidents"]) > limit):
            raise RuntimeError("Invalid negative knowledge response")
        return result
    if op == "incident":
        if args.get("confirmed") is not True:
            raise ValueError("Explicit confirmation required")
        cause, fix = args.get("cause", ""), args.get("fix", "")
        if any(not isinstance(value, str) or len(value) > 4096 for value in (cause, fix)):
            raise ValueError("Invalid incident cause or verified fix")
        if fix.strip().casefold() == "resolved":
            raise ValueError("Describe the verified fix rather than asserting resolution")
        result = checked_post(control, "/api/agent-state/incidents", {
            "root": explicit_root(args.get("root")), "action": "record",
            "operation_class": text_field(args, "kind", 200),
            "message": text_field(args, "message"),
            "root_cause": cause, "verified_fix": fix,
        })
        if result.get("success") is not True or not isinstance(result.get("incident"), dict):
            raise RuntimeError("Incident recording not confirmed")
        return result
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
        if args.get("confirmed") is not True:
            raise ValueError("Explicit confirmation required before running two inference requests")
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
