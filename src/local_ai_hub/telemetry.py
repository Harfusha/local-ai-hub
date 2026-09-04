from __future__ import annotations

import hashlib
import json
import queue
import re
import sqlite3
import threading
import time
from contextlib import closing
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .trace_context import current as current_trace_context
from .sqlite_support import connect_sqlite, initialize_wal, is_busy_error


_PATH_RE = re.compile(r"(?:(?:[A-Za-z]:\\\\|/)(?:[^\s:'\"<>|]+[/\\\\])+[^\s:'\"<>|]*)")
_LONG_TOKEN_RE = re.compile(r"\b(?:[A-Fa-f0-9]{24,}|[A-Za-z0-9_\-]{48,})\b")


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(x) for x in values)
    idx = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * pct))))
    return round(ordered[idx], 1)


def _tail_latency(rows: list[tuple[Any, ...]], key_name: str) -> list[dict[str, Any]]:
    """Aggregate metadata-only HTTP tail latency without schema changes."""
    groups: dict[str, list[tuple[float, float, float, int]]] = {}
    for key, duration_ms, queue_wait_ms, service_ms, success in rows:
        group = str(key or "uncategorized")[:160]
        groups.setdefault(group, []).append((
            float(duration_ms or 0), float(queue_wait_ms or 0),
            float(service_ms or 0), int(success or 0),
        ))
    result: list[dict[str, Any]] = []
    for key, items in groups.items():
        durations = [item[0] for item in items]
        queue_waits = [item[1] for item in items]
        services = [item[2] for item in items]
        result.append({
            key_name: key, "events": len(items), "failures": sum(1 for item in items if not item[3]),
            "failure_rate": round(sum(1 for item in items if not item[3]) / len(items), 4) if items else 0.0,
            "p50_duration_ms": _percentile(durations, 0.50),
            "p95_duration_ms": _percentile(durations, 0.95),
            "p99_duration_ms": _percentile(durations, 0.99),
            "p95_queue_wait_ms": _percentile(queue_waits, 0.95),
            "p95_service_ms": _percentile(services, 0.95),
        })
    return sorted(result, key=lambda item: (-float(item["p99_duration_ms"]), -int(item["events"]), str(item[key_name])))


def _safe_error_message(value: Any) -> str:
    """Keep error diagnostics useful without persisting project/source content."""
    text = str(value or "").replace("\r", " ").replace("\n", " ")[:1200]
    text = _PATH_RE.sub("<path>", text)
    text = _LONG_TOKEN_RE.sub("<token>", text)
    return " ".join(text.split())[:500]


def _error_fingerprint(error_type: str, component: str, operation: str, message: str) -> str:
    # Strip volatile numbers so the same failure groups together across requests.
    stable = re.sub(r"\b\d+\b", "#", message.lower())
    raw = f"{error_type}|{component}|{operation}|{stable}".encode("utf-8", "replace")
    return hashlib.sha256(raw).hexdigest()[:16]


class TelemetryStore:
    """Low-overhead, metadata-only observability store.

    Foreground callers never write SQLite directly. Events are queued and flushed in
    small batches by a daemon writer. Prompts, source text and model output are never
    accepted by the schema. Raw events have bounded retention; compact daily rollups
    are retained longer so real-world tuning data survives pruning.
    """

    _EVENT_COLUMNS = (
        "created_at", "event_type", "tenant", "agent", "request_id", "trace_id",
        "action", "stage", "task_type", "complexity", "route", "model",
        "cache_hit", "coalesced", "cache_layer", "input_tokens", "output_tokens",
        "avoided_cloud_tokens", "duration_ms", "queue_wait_ms", "service_ms",
        "load_duration_ms", "success", "status_code", "degraded", "retry_count",
        "fallback_used", "error_type", "error_fingerprint", "tool_calls",
        "evidence_count", "response_bytes",
    )

    def __init__(
        self,
        state_dir: Path,
        enabled: bool = True,
        max_events: int = 100000,
        *,
        retention_days: int = 30,
        rollup_retention_days: int = 365,
        cloud_token_cost_usd_per_million: float = 3.0,
        batch_size: int = 64,
        flush_interval_seconds: float = 0.5,
        queue_size: int = 10000,
        live_buffer_size: int = 2500,
    ):
        self.enabled = bool(enabled)
        self.max_events = max(100, int(max_events))
        self.retention_days = max(1, int(retention_days))
        self.rollup_retention_days = max(self.retention_days, int(rollup_retention_days))
        self.cloud_token_cost_usd_per_million = max(0.0, float(cloud_token_cost_usd_per_million))
        self.batch_size = max(1, min(int(batch_size), 1000))
        self.flush_interval_seconds = max(0.05, float(flush_interval_seconds))
        self.path = state_dir / "telemetry.sqlite3"
        # Persisted telemetry spans restarts. Keep an explicit in-memory boundary
        # so operators can separate current deploy/process behavior from history.
        self.process_started_at = time.time()
        self._queue: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue(maxsize=max(100, int(queue_size)))
        self._stop = threading.Event()
        self._stats_lock = threading.Lock()
        self._stats = {"queued": 0, "written": 0, "dropped": 0, "writer_errors": 0, "batches": 0}
        self._live_lock = threading.Lock()
        self._live_seq = 0
        self._live_events: deque[dict[str, Any]] = deque(maxlen=max(100, int(live_buffer_size)))
        self._dashboard_lock = threading.Lock()
        self._dashboard_cache: dict[tuple[int, str], dict[str, Any]] = {}
        self._dashboard_cache_at: dict[tuple[int, str], float] = {}
        self._thread: threading.Thread | None = None
        state_dir.mkdir(parents=True, exist_ok=True)
        if self.enabled:
            self._init_db_with_recovery()
            self._thread = threading.Thread(target=self._writer_loop, name="local-ai-telemetry", daemon=True)
            self._thread.start()

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self.path, timeout_seconds=0.75)

    def _init_db_with_recovery(self) -> None:
        try:
            self._init_db()
            with closing(self._connect()) as con:
                if con.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise sqlite3.DatabaseError("telemetry quick_check failed")
        except sqlite3.DatabaseError as exc:
            if is_busy_error(exc):
                return
            # Telemetry is derived state. Quarantine corruption instead of blocking hub startup.
            try:
                self.path.replace(self.path.with_suffix(f".corrupt-{int(time.time())}.sqlite3"))
            except OSError:
                pass
            self._init_db()

    def _init_db(self) -> None:
        with closing(self._connect()) as con:
            initialize_wal(con)
            con.execute(
                """CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    tenant TEXT NOT NULL DEFAULT 'default',
                    action TEXT NOT NULL DEFAULT 'unknown',
                    model TEXT,
                    cache_hit INTEGER NOT NULL DEFAULT 0,
                    coalesced INTEGER NOT NULL DEFAULT 0,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    avoided_cloud_tokens INTEGER NOT NULL DEFAULT 0,
                    duration_ms REAL NOT NULL DEFAULT 0,
                    success INTEGER NOT NULL DEFAULT 1,
                    cache_layer TEXT NOT NULL DEFAULT '',
                    load_duration_ms REAL NOT NULL DEFAULT 0,
                    event_type TEXT NOT NULL DEFAULT 'inference',
                    agent TEXT NOT NULL DEFAULT '',
                    request_id TEXT NOT NULL DEFAULT '',
                    trace_id TEXT NOT NULL DEFAULT '',
                    stage TEXT NOT NULL DEFAULT '',
                    task_type TEXT NOT NULL DEFAULT '',
                    complexity TEXT NOT NULL DEFAULT '',
                    route TEXT NOT NULL DEFAULT '',
                    queue_wait_ms REAL NOT NULL DEFAULT 0,
                    service_ms REAL NOT NULL DEFAULT 0,
                    status_code INTEGER NOT NULL DEFAULT 0,
                    degraded INTEGER NOT NULL DEFAULT 0,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    fallback_used INTEGER NOT NULL DEFAULT 0,
                    error_type TEXT NOT NULL DEFAULT '',
                    error_fingerprint TEXT NOT NULL DEFAULT '',
                    tool_calls INTEGER NOT NULL DEFAULT 0,
                    evidence_count INTEGER NOT NULL DEFAULT 0,
                    response_bytes INTEGER NOT NULL DEFAULT 0
                )"""
            )
            con.executescript(
                """
                CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at);
                CREATE INDEX IF NOT EXISTS idx_events_type_created ON events(event_type, created_at);
                CREATE INDEX IF NOT EXISTS idx_events_action_created ON events(action, created_at);
                CREATE INDEX IF NOT EXISTS idx_events_error ON events(error_fingerprint, created_at);
                CREATE INDEX IF NOT EXISTS idx_events_model ON events(model, created_at);
                CREATE TABLE IF NOT EXISTS errors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    tenant TEXT NOT NULL DEFAULT '',
                    agent TEXT NOT NULL DEFAULT '',
                    component TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    error_type TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    safe_message TEXT NOT NULL,
                    retryable INTEGER NOT NULL DEFAULT 0,
                    recovered INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_errors_fp_created ON errors(fingerprint, created_at);
                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    name TEXT NOT NULL,
                    metrics_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_snapshots_name_created ON snapshots(name, created_at);
                CREATE TABLE IF NOT EXISTS daily_rollups (
                    day TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    action TEXT NOT NULL,
                    agent TEXT NOT NULL,
                    model TEXT NOT NULL,
                    cache_layer TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    events INTEGER NOT NULL DEFAULT 0,
                    duration_ms REAL NOT NULL DEFAULT 0,
                    queue_wait_ms REAL NOT NULL DEFAULT 0,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    avoided_cloud_tokens INTEGER NOT NULL DEFAULT 0,
                    cache_hits INTEGER NOT NULL DEFAULT 0,
                    fallback_count INTEGER NOT NULL DEFAULT 0,
                    degraded_count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(day,event_type,action,agent,model,cache_layer,success)
                );
                """
            )
            con.commit()

    @staticmethod
    def _clean_event(event: dict[str, Any]) -> dict[str, Any]:
        def redact(value: Any) -> str:
            text = str(value or "")
            text = re.sub(r"(?i)\bbearer\s+[^\s,;]+", "Bearer [redacted]", text)
            return re.sub(r"(?i)\b(api[_-]?key|token|password|secret|authorization)\s*([=:])\s*[^&\s,;]+", r"\1\2[redacted]", text)

        created = float(event.get("created_at", time.time()))
        return {
            "created_at": created,
            "event_type": str(event.get("event_type", "inference"))[:40],
            "tenant": redact(event.get("tenant", "default"))[:160],
            "agent": redact(event.get("agent", ""))[:80],
            "request_id": str(event.get("request_id", ""))[:96],
            "trace_id": str(event.get("trace_id", ""))[:96],
            "action": redact(event.get("action", "unknown"))[:160],
            "stage": redact(event.get("stage", ""))[:80],
            "task_type": redact(event.get("task_type", ""))[:80],
            "complexity": redact(event.get("complexity", ""))[:40],
            "route": redact(event.get("route", ""))[:120],
            "model": redact(event.get("model", "") or "")[:160],
            "cache_hit": 1 if event.get("cache_hit") else 0,
            "coalesced": 1 if event.get("coalesced") else 0,
            "cache_layer": str(event.get("cache_layer", ""))[:80],
            "input_tokens": max(0, int(event.get("input_tokens", 0) or 0)),
            "output_tokens": max(0, int(event.get("output_tokens", 0) or 0)),
            "avoided_cloud_tokens": max(0, int(event.get("avoided_cloud_tokens", 0) or 0)),
            "duration_ms": max(0.0, float(event.get("duration_ms", 0) or 0)),
            "queue_wait_ms": max(0.0, float(event.get("queue_wait_ms", 0) or 0)),
            "service_ms": max(0.0, float(event.get("service_ms", 0) or 0)),
            "load_duration_ms": max(0.0, float(event.get("load_duration_ms", 0) or 0)),
            "success": 1 if event.get("success", True) else 0,
            "status_code": max(0, int(event.get("status_code", 0) or 0)),
            "degraded": 1 if event.get("degraded") else 0,
            "retry_count": max(0, int(event.get("retry_count", 0) or 0)),
            "fallback_used": 1 if event.get("fallback_used") else 0,
            "error_type": str(event.get("error_type", ""))[:120],
            "error_fingerprint": str(event.get("error_fingerprint", ""))[:32],
            "tool_calls": max(0, int(event.get("tool_calls", 0) or 0)),
            "evidence_count": max(0, int(event.get("evidence_count", 0) or 0)),
            "response_bytes": max(0, int(event.get("response_bytes", 0) or 0)),
        }

    def _publish_live(self, kind: str, payload: dict[str, Any]) -> None:
        allowed = {
            "created_at", "event_type", "tenant", "agent", "request_id", "trace_id",
            "action", "stage", "task_type", "complexity", "route", "model",
            "cache_hit", "coalesced", "cache_layer", "duration_ms", "queue_wait_ms",
            "service_ms", "load_duration_ms", "success", "status_code", "degraded",
            "retry_count", "fallback_used", "error_type", "error_fingerprint",
            "tool_calls", "evidence_count", "response_bytes", "component", "operation",
            "fingerprint", "retryable", "recovered", "name", "metrics_json",
        }
        event = {k: v for k, v in payload.items() if k in allowed}
        event["kind"] = kind
        event.setdefault("created_at", time.time())
        with self._live_lock:
            self._live_seq += 1
            event["seq"] = self._live_seq
            self._live_events.append(event)

    def live(self, after: int = 0, limit: int = 200) -> dict[str, Any]:
        limit = max(1, min(int(limit), 1000))
        with self._live_lock:
            events = [dict(e) for e in self._live_events if int(e.get("seq", 0)) > int(after)]
            if len(events) > limit:
                events = events[-limit:]
            cursor = self._live_seq
            oldest = int(self._live_events[0].get("seq", 0)) if self._live_events else cursor
        return {"success": True, "cursor": cursor, "oldest": oldest, "events": events}

    def _enqueue(self, kind: str, payload: dict[str, Any]) -> None:
        if not self.enabled:
            return
        self._publish_live(kind, payload)
        try:
            self._queue.put_nowait((kind, payload))
            with self._stats_lock:
                self._stats["queued"] += 1
        except queue.Full:
            # Observability must never become a back-pressure source for foreground work.
            with self._stats_lock:
                self._stats["dropped"] += 1

    def record_live(self, kind: str = "live", **event: Any) -> None:
        if not self.enabled:
            return
        ctx = current_trace_context()
        for key in ("request_id", "trace_id", "agent", "tenant"):
            if not event.get(key) and ctx.get(key):
                event[key] = ctx[key]
        self._publish_live(kind, self._clean_event(event))

    def dashboard_report(self, days: int = 30, ttl_seconds: float = 5.0, *, scope: str = "window") -> dict[str, Any]:
        """Cached persistent report used by the realtime dashboard.

        Most dashboard polls are RAM-only; at most one thread refreshes the SQLite
        aggregate every few seconds. This keeps counters stable across hub restarts.
        """
        _, scope = self._scope_cutoff(days, scope)
        key = (max(1, int(days)), scope)
        now = time.monotonic()
        with self._dashboard_lock:
            cached = self._dashboard_cache.get(key)
            cached_at = self._dashboard_cache_at.get(key, 0.0)
            if cached and now - cached_at < max(1.0, float(ttl_seconds)):
                return dict(cached)
            try:
                report = self.report(days, recent_errors=12, scope=scope)
                report["recent_http"] = self.recent_http(50)
            except Exception:
                report = dict(cached) if cached else {"summary": {"enabled": self.enabled}}
            self._dashboard_cache[key] = report
            self._dashboard_cache_at[key] = now
            return dict(report)

    def realtime_summary(self, *, scope: str = "process") -> dict[str, Any]:
        with self._live_lock:
            events = [dict(e) for e in self._live_events]
        inference = [e for e in events if e.get("event_type") == "inference"]

        # Only real application requests are published as request_start. Monitoring
        # endpoints are excluded by the HTTP server/config and can never inflate this.
        started: dict[str, dict[str, Any]] = {}
        finished: set[str] = set()
        for event in events:
            request_id = str(event.get("request_id") or "")
            if not request_id:
                continue
            if event.get("event_type") == "request_start":
                started[request_id] = event
            elif event.get("event_type") == "http":
                finished.add(request_id)
        now_wall = time.time()
        active_requests = []
        for request_id, event in started.items():
            if request_id in finished:
                continue
            active_requests.append({
                "request_id": request_id[:12], "agent": str(event.get("agent") or "")[:40],
                "tenant": str(event.get("tenant") or "")[:80], "action": str(event.get("action") or "")[:100],
                "age_ms": max(0, int((now_wall - float(event.get("created_at", now_wall) or now_wall)) * 1000)),
            })
        active_requests.sort(key=lambda item: int(item.get("age_ms", 0)), reverse=True)
        active_requests = active_requests[:24]

        report = self.dashboard_report(30, scope=scope) if self.enabled else {"summary": {}}
        history = report.get("summary", {}) if isinstance(report, dict) else {}
        return {
            "scope": str(history.get("scope", scope) or scope),
            "process_started_at": history.get("process_started_at") if scope == "process" else None,
            "window_events": len(events), "live_inference_events": len(inference),
            "inference_events": int(history.get("events", len(inference)) or 0),
            "cache_hits": int(history.get("cache_hits", 0) or 0),
            "cache_hit_rate": float(history.get("cache_hit_rate", 0.0) or 0.0),
            "cloud_tokens_avoided_est": int(history.get("cloud_tokens_avoided_est", 0) or 0),
            "cloud_token_cost_usd_per_million": float(history.get("cloud_token_cost_usd_per_million", self.cloud_token_cost_usd_per_million) or 0.0),
            "estimated_savings_usd": float(history.get("estimated_savings_usd", 0.0) or 0.0),
            "fallback_count": int(history.get("fallback_count", 0) or 0),
            "degraded_count": int(history.get("degraded_count", 0) or 0),
            "retry_count": int(history.get("retry_count", 0) or 0),
            "failures": int(history.get("failures", 0) or 0),
            "failure_rate": float(history.get("failure_rate", 0.0) or 0.0),
            "p50_duration_ms": float(history.get("p50_duration_ms", 0.0) or 0.0),
            "p95_duration_ms": float(history.get("p95_duration_ms", 0.0) or 0.0),
            "p99_duration_ms": float(history.get("p99_duration_ms", 0.0) or 0.0),
            "aggregate_duration_scope": str(history.get("aggregate_duration_scope", "") or ""),
            "cohorts": history.get("cohorts", {}),
            "avg_queue_wait_ms": float(history.get("avg_queue_wait_ms", 0.0) or 0.0),
            "ollama_inference_calls": int(history.get("ollama_inference_calls", 0) or 0),
            "ollama_calls_avoided_est": int(history.get("ollama_calls_avoided_est", 0) or 0),
            "cache_layers": report.get("cache_layers", []) if isinstance(report, dict) else [],
            "http_tail_latency": report.get("http_tail_latency", {}) if isinstance(report, dict) else {},
            "http": history.get("http", {}),
            "tool_adoption": history.get("tool_adoption", {}),
            "by_model": report.get("by_model", []) if isinstance(report, dict) else [],
            "by_agent": report.get("by_agent", []) if isinstance(report, dict) else [],
            "execution_routes": report.get("execution_routes", []) if isinstance(report, dict) else [],
            "recent_errors": report.get("error_fingerprints", []) if isinstance(report, dict) else [],
            "hotspots": report.get("hotspots", []) if isinstance(report, dict) else [],
            "active_request_count": len(active_requests), "active_requests": active_requests,
            "live_cursor": self._live_seq,
            "recent_http": report.get("recent_http", []) if isinstance(report, dict) else [],
        }

    def record(self, **event: Any) -> None:
        ctx = current_trace_context()
        for key in ("request_id", "trace_id", "agent", "tenant"):
            if not event.get(key) and ctx.get(key):
                event[key] = ctx[key]
        self._enqueue("event", self._clean_event(event))

    def record_http(self, **event: Any) -> None:
        event["event_type"] = "http"
        self.record(**event)

    def record_stage(self, **event: Any) -> None:
        event["event_type"] = "stage"
        self.record(**event)

    def record_system(self, action: str, *, success: bool = True, duration_ms: float = 0.0, **event: Any) -> None:
        event.update({"event_type": "system", "action": action, "success": success, "duration_ms": duration_ms})
        self.record(**event)

    def record_error(
        self,
        component: str,
        operation: str,
        error: Any,
        *,
        request_id: str = "",
        tenant: str = "",
        agent: str = "",
        retryable: bool = False,
        recovered: bool = False,
    ) -> str:
        if not self.enabled:
            return ""
        ctx = current_trace_context()
        request_id = request_id or str(ctx.get("request_id") or "")
        tenant = tenant or str(ctx.get("tenant") or "")
        agent = agent or str(ctx.get("agent") or "")
        error_type = type(error).__name__ if isinstance(error, BaseException) else "Error"
        message = _safe_error_message(error)
        fp = _error_fingerprint(error_type, component, operation, message)
        payload = {
            "created_at": time.time(), "request_id": request_id[:96], "tenant": tenant[:160], "agent": agent[:80],
            "component": str(component)[:120], "operation": str(operation)[:160], "error_type": error_type[:120],
            "fingerprint": fp, "safe_message": message, "retryable": 1 if retryable else 0,
            "recovered": 1 if recovered else 0,
        }
        self._enqueue("error", payload)
        self.record(
            event_type="error", tenant=tenant, agent=agent, request_id=request_id,
            action=f"{component}:{operation}", success=False, error_type=error_type, error_fingerprint=fp,
        )
        return fp


    def record_snapshot(self, name: str, metrics: dict[str, Any]) -> None:
        if not self.enabled:
            return
        # Snapshot payloads are internal numeric/status metrics only. Bound size to
        # keep observability from becoming an accidental generic data store.
        safe: dict[str, Any] = {}
        for key, value in metrics.items():
            if isinstance(value, (bool, int, float)) or value is None:
                safe[str(key)[:80]] = value
            elif isinstance(value, str) and len(value) <= 160:
                safe[str(key)[:80]] = value
        self._enqueue("snapshot", {"created_at": time.time(), "name": str(name)[:80], "metrics_json": json.dumps(safe, separators=(",", ":"))[:8000]})

    def record_evaluation(
        self,
        *,
        task_id: str,
        cohort: str,
        quality_pass: bool | None = None,
        test_pass: bool | None = None,
        duration_ms: float = 0.0,
    ) -> dict[str, Any]:
        task_id = str(task_id).strip()
        if not task_id or len(task_id) > 96 or not re.fullmatch(r"[A-Za-z0-9._:-]+", task_id):
            return {"success": False, "error": "task_id must be an opaque identifier up to 96 characters", "terminal": True}
        if cohort not in {"hub_on", "hub_off"}:
            return {"success": False, "error": "cohort must be hub_on or hub_off", "terminal": True}
        if quality_pass is not None and not isinstance(quality_pass, bool):
            return {"success": False, "error": "quality_pass must be boolean", "terminal": True}
        if test_pass is not None and not isinstance(test_pass, bool):
            return {"success": False, "error": "test_pass must be boolean", "terminal": True}
        self.record_snapshot("agent_evaluation", {
            "task_id": task_id,
            "cohort": cohort,
            "quality_pass": quality_pass,
            "test_pass": test_pass,
            "duration_ms": max(0.0, float(duration_ms)),
        })
        return {"success": True, "task_id": task_id, "cohort": cohort}

    def record_request_evaluation(self, evaluation: Any, *, duration_ms: float) -> dict[str, Any]:
        """Persist request-attached A/B metadata with measured server duration."""
        if not isinstance(evaluation, dict):
            return {"success": False, "error": "evaluation must be an object", "terminal": True}
        try:
            measured = max(0.0, float(duration_ms))
        except (TypeError, ValueError):
            return {"success": False, "error": "duration_ms must be numeric", "terminal": True}
        result = self.record_evaluation(
            task_id=evaluation.get("task_id", ""),
            cohort=evaluation.get("cohort", ""),
            quality_pass=evaluation.get("quality_pass"),
            test_pass=evaluation.get("test_pass"),
            duration_ms=measured,
        )
        if result.get("success"):
            result["duration_ms"] = measured
        return result

    @staticmethod
    def _evaluation_summary(rows: list[tuple[Any, ...]]) -> dict[str, Any]:
        latest: dict[tuple[str, str], dict[str, Any]] = {}
        for _created_at, raw_metrics in rows:
            try:
                metrics = json.loads(raw_metrics)
            except (TypeError, ValueError):
                continue
            if not isinstance(metrics, dict):
                continue
            task_id = metrics.get("task_id")
            cohort = metrics.get("cohort")
            if not isinstance(task_id, str) or cohort not in {"hub_on", "hub_off"}:
                continue
            latest[(task_id, cohort)] = metrics
        matched = [
            task_id for task_id in {key[0] for key in latest}
            if (task_id, "hub_on") in latest and (task_id, "hub_off") in latest
        ]
        cohorts: dict[str, dict[str, Any]] = {}
        for cohort in ("hub_on", "hub_off"):
            records = [latest[(task_id, cohort)] for task_id in matched]
            durations = [float(item.get("duration_ms", 0) or 0) for item in records]
            quality = [item["quality_pass"] for item in records if isinstance(item.get("quality_pass"), bool)]
            tests = [item["test_pass"] for item in records if isinstance(item.get("test_pass"), bool)]
            cohorts[cohort] = {
                "records": len(records),
                "avg_duration_ms": round(sum(durations) / len(durations), 1) if durations else 0.0,
                "quality_evaluated": len(quality),
                "quality_pass_rate": round(sum(quality) / len(quality), 4) if quality else None,
                "tests_evaluated": len(tests),
                "test_pass_rate": round(sum(tests) / len(tests), 4) if tests else None,
            }
        gate = {"verdict": "hold", "reason": "insufficient_matched_tasks", "minimum_matched_tasks": 10}
        if len(matched) >= 10:
            on, off = cohorts["hub_on"], cohorts["hub_off"]
            evidence_complete = on["quality_evaluated"] == len(matched) and off["quality_evaluated"] == len(matched) and on["tests_evaluated"] == len(matched) and off["tests_evaluated"] == len(matched)
            if not evidence_complete:
                gate = {"verdict": "hold", "reason": "missing_quality_or_test_evidence", "minimum_matched_tasks": 10}
            elif on["quality_pass_rate"] < off["quality_pass_rate"] or on["test_pass_rate"] < off["test_pass_rate"]:
                gate = {"verdict": "hold", "reason": "quality_or_test_regression", "minimum_matched_tasks": 10}
            elif on["avg_duration_ms"] < off["avg_duration_ms"]:
                gate = {"verdict": "promote", "reason": "quality_test_safe_and_faster", "minimum_matched_tasks": 10}
            else:
                gate = {"verdict": "hold", "reason": "no_duration_improvement", "minimum_matched_tasks": 10}
        return {
            "verdict": "comparison_ready" if matched else "insufficient_evidence",
            "matched_tasks": len(matched),
            "cohorts": cohorts,
            "gate": gate,
        }

    def _insert_event_batch(self, con: sqlite3.Connection, events: list[dict[str, Any]]) -> None:
        if not events:
            return
        cols = self._EVENT_COLUMNS
        placeholders = ",".join("?" for _ in cols)
        con.executemany(
            f"INSERT INTO events({','.join(cols)}) VALUES({placeholders})",
            [tuple(event[col] for col in cols) for event in events],
        )
        # Compact daily aggregates survive raw-event pruning.
        grouped: dict[tuple[Any, ...], list[float]] = {}
        for e in events:
            day = datetime.fromtimestamp(e["created_at"], tz=timezone.utc).strftime("%Y-%m-%d")
            key = (day, e["event_type"], e["action"], e["agent"], e["model"], e["cache_layer"], e["success"])
            agg = grouped.setdefault(key, [0, 0.0, 0.0, 0, 0, 0, 0, 0, 0])
            agg[0] += 1; agg[1] += e["duration_ms"]; agg[2] += e["queue_wait_ms"]
            agg[3] += e["input_tokens"]; agg[4] += e["output_tokens"]; agg[5] += e["avoided_cloud_tokens"]
            agg[6] += e["cache_hit"]; agg[7] += e["fallback_used"]; agg[8] += e["degraded"]
        con.executemany(
            """INSERT INTO daily_rollups(day,event_type,action,agent,model,cache_layer,success,events,duration_ms,queue_wait_ms,input_tokens,output_tokens,avoided_cloud_tokens,cache_hits,fallback_count,degraded_count)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(day,event_type,action,agent,model,cache_layer,success) DO UPDATE SET
                 events=events+excluded.events, duration_ms=duration_ms+excluded.duration_ms,
                 queue_wait_ms=queue_wait_ms+excluded.queue_wait_ms, input_tokens=input_tokens+excluded.input_tokens,
                 output_tokens=output_tokens+excluded.output_tokens, avoided_cloud_tokens=avoided_cloud_tokens+excluded.avoided_cloud_tokens,
                 cache_hits=cache_hits+excluded.cache_hits, fallback_count=fallback_count+excluded.fallback_count,
                 degraded_count=degraded_count+excluded.degraded_count""",
            [key + tuple(vals) for key, vals in grouped.items()],
        )

    def _flush_batch(self, batch: list[tuple[str, dict[str, Any]]]) -> None:
        events = [payload for kind, payload in batch if kind == "event"]
        errors = [payload for kind, payload in batch if kind == "error"]
        snapshots = [payload for kind, payload in batch if kind == "snapshot"]
        with closing(self._connect()) as con:
            self._insert_event_batch(con, events)
            if errors:
                con.executemany(
                    """INSERT INTO errors(created_at,request_id,tenant,agent,component,operation,error_type,fingerprint,safe_message,retryable,recovered)
                       VALUES(:created_at,:request_id,:tenant,:agent,:component,:operation,:error_type,:fingerprint,:safe_message,:retryable,:recovered)""",
                    errors,
                )
            if snapshots:
                con.executemany(
                    "INSERT INTO snapshots(created_at,name,metrics_json) VALUES(:created_at,:name,:metrics_json)", snapshots
                )
            con.commit()
        with self._stats_lock:
            self._stats["written"] += len(batch)
            self._stats["batches"] += 1

    def _prune(self) -> None:
        cutoff = time.time() - self.retention_days * 86400
        rollup_cutoff = datetime.fromtimestamp(time.time() - self.rollup_retention_days * 86400, tz=timezone.utc).strftime("%Y-%m-%d")
        with closing(self._connect()) as con:
            con.execute("DELETE FROM events WHERE created_at<?", (cutoff,))
            con.execute("DELETE FROM errors WHERE created_at<?", (cutoff,))
            con.execute("DELETE FROM snapshots WHERE created_at<?", (cutoff,))
            count = int(con.execute("SELECT COUNT(*) FROM events").fetchone()[0])
            if count > self.max_events:
                con.execute("DELETE FROM events WHERE id IN (SELECT id FROM events ORDER BY id ASC LIMIT ?)", (count - self.max_events,))
            con.execute("DELETE FROM daily_rollups WHERE day<?", (rollup_cutoff,))
            con.commit()

    def _writer_loop(self) -> None:
        last_prune = 0.0
        batch: list[tuple[str, dict[str, Any]]] = []
        while not self._stop.is_set() or not self._queue.empty() or batch:
            try:
                try:
                    item = self._queue.get(timeout=self.flush_interval_seconds)
                    batch.append(item)
                except queue.Empty:
                    pass
                while len(batch) < self.batch_size:
                    try:
                        batch.append(self._queue.get_nowait())
                    except queue.Empty:
                        break
                if batch:
                    self._flush_batch(batch)
                    batch.clear()
                if time.monotonic() - last_prune > 60.0:
                    self._prune(); last_prune = time.monotonic()
            except Exception as exc:
                with self._stats_lock:
                    self._stats["writer_errors"] += 1
                    if not is_busy_error(exc):
                        self._stats["dropped"] += len(batch)
                        batch.clear()
                time.sleep(min(1.0, self.flush_interval_seconds * 2))

    def flush(self, timeout: float = 3.0) -> bool:
        if not self.enabled:
            return True
        with self._stats_lock:
            target = int(self._stats["queued"])
        deadline = time.monotonic() + max(0.05, float(timeout))
        while time.monotonic() < deadline:
            with self._stats_lock:
                completed = int(self._stats["written"]) + int(self._stats["dropped"])
            if completed >= target:
                return True
            time.sleep(0.02)
        with self._stats_lock:
            return int(self._stats["written"]) + int(self._stats["dropped"]) >= target

    def _cutoff(self, days: int) -> float:
        return time.time() - max(1, int(days)) * 86400

    def _scope_cutoff(self, days: int, scope: str) -> tuple[float, str]:
        normalized = str(scope or "window").strip().lower()
        if normalized not in {"window", "process"}:
            raise ValueError("scope must be 'window' or 'process'")
        cutoff = self._cutoff(days)
        if normalized == "process":
            # A process cohort is a deployment boundary, not a rolling window.
            # It must include the full current process even for long-lived hubs.
            cutoff = float(self.process_started_at)
        return cutoff, normalized

    @staticmethod
    def _event_cohort(event_type: str, error_type: str) -> str:
        if event_type == "inference":
            return "inference"
        if event_type == "http" and error_type == "policy_block":
            return "policy_rejection"
        if event_type == "http":
            return "agent_http"
        return "internal"

    @classmethod
    def _cohort_summary(cls, rows: list[tuple[Any, ...]]) -> dict[str, dict[str, Any]]:
        cohorts: dict[str, list[tuple[Any, ...]]] = {
            "agent_http": [], "inference": [], "policy_rejection": [], "internal": [],
        }
        for row in rows:
            cohorts[cls._event_cohort(str(row[0]), str(row[1]))].append(row)
        result: dict[str, dict[str, Any]] = {}
        for name, items in cohorts.items():
            durations = [float(item[2]) for item in items]
            failures = sum(1 for item in items if not int(item[3]))
            events = len(items)
            result[name] = {
                "events": events,
                "failures": failures,
                "failure_rate": round(failures / events, 4) if events else 0.0,
                "p50_duration_ms": _percentile(durations, 0.50),
                "p95_duration_ms": _percentile(durations, 0.95),
                "p99_duration_ms": _percentile(durations, 0.99),
                "retry_count": sum(int(item[4]) for item in items),
                "fallback_count": sum(int(item[5]) for item in items),
                "degraded_count": sum(int(item[6]) for item in items),
            }
        return result

    def summary(self, days: int = 30, *, scope: str = "window") -> dict[str, Any]:
        if not self.enabled:
            return {"enabled": False}
        now = time.monotonic()
        cutoff, scope = self._scope_cutoff(days, scope)
        # Keep the established rolling-window cache key stable for lightweight
        # callers; process cohorts need the start boundary in their own key.
        key: Any = int(days) if scope == "window" else (int(days), scope, int(self.process_started_at))
        if not hasattr(self, "_summary_cache"):
            self._summary_cache = {}
        cached = self._summary_cache.get(key)
        if cached and now - cached["time"] < 3.0:
            return dict(cached["data"])
        self.flush(0.5)
        with closing(self._connect()) as con:
            row = con.execute(
                """SELECT COUNT(*), COALESCE(SUM(cache_hit),0), COALESCE(SUM(coalesced),0),
                          COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0),
                          COALESCE(SUM(avoided_cloud_tokens),0), COALESCE(AVG(duration_ms),0),
                          COALESCE(SUM(CASE WHEN success=0 THEN 1 ELSE 0 END),0),
                          COALESCE(AVG(CASE WHEN load_duration_ms>0 THEN load_duration_ms END),0),
                          COALESCE(AVG(queue_wait_ms),0), COALESCE(SUM(fallback_used),0), COALESCE(SUM(degraded),0),
                          COALESCE(SUM(retry_count),0)
                   FROM events WHERE created_at>=? AND event_type='inference'""",
                (cutoff,),
            ).fetchone()
            by_action = con.execute(
                """SELECT action,COUNT(*),COALESCE(SUM(avoided_cloud_tokens),0),COALESCE(AVG(duration_ms),0)
                   FROM events WHERE created_at>=? AND event_type='inference' GROUP BY action ORDER BY COUNT(*) DESC LIMIT 20""",
                (cutoff,),
            ).fetchall()
            by_cache = con.execute(
                """SELECT CASE WHEN cache_layer='' THEN 'uncategorized' ELSE cache_layer END,COUNT(*)
                   FROM events WHERE created_at>=? AND event_type='inference' GROUP BY cache_layer ORDER BY COUNT(*) DESC""",
                (cutoff,),
            ).fetchall()
            durations = [float(r[0]) for r in con.execute(
                "SELECT duration_ms FROM events WHERE created_at>=? AND event_type='inference' ORDER BY id DESC LIMIT 10000", (cutoff,)
            )]
            cohort_rows = con.execute(
                """SELECT event_type,error_type,duration_ms,success,retry_count,fallback_used,degraded
                   FROM events WHERE created_at>=? AND event_type IN ('inference','http')""",
                (cutoff,),
            ).fetchall()
            http = con.execute(
                "SELECT COUNT(*),COALESCE(SUM(CASE WHEN success=0 THEN 1 ELSE 0 END),0),COALESCE(AVG(duration_ms),0) FROM events WHERE created_at>=? AND event_type='http'",
                (cutoff,),
            ).fetchone()
            # Persistent tool-adoption metric.  This deliberately counts agent -> hub
            # application calls, not dashboard/health/control polling, so it survives
            # hub restarts and reflects whether agents are actually using the local
            # tool layer rather than the ephemeral in-process ToolAwareLocalAgent count.
            tool_http = con.execute(
                """SELECT COUNT(*), COUNT(DISTINCT CASE WHEN agent<>'' THEN agent END),
                          COALESCE(SUM(CASE WHEN action='/v1/command' THEN 1 ELSE 0 END),0),
                          COALESCE(SUM(CASE WHEN action LIKE '/v1/repo/%' OR action='/v1/solve/repo' THEN 1 ELSE 0 END),0)
                   FROM events WHERE created_at>=? AND event_type='http'
                     AND action LIKE '/v1/%'
                     AND action NOT IN ('/v1/live','/v1/live/status','/v1/status','/v1/control')""",
                (cutoff,),
            ).fetchone()
        total = int(row[0]); cached = int(row[1]); http_total = int(http[0])
        avoided_cloud_tokens = int(row[5])
        cohorts = self._cohort_summary(cohort_rows)
        with self._stats_lock:
            writer = dict(self._stats)
        writer["queue_depth"] = self._queue.qsize()
        res = {
            "enabled": True, "window_days": max(1, int(days)), "scope": scope,
            "process_started_at": self.process_started_at if scope == "process" else None, "events": total,
            "cache_hits": cached, "cache_hit_rate": round(cached / total, 4) if total else 0.0,
            "coalesced_waiters": int(row[2]), "local_input_tokens_est": int(row[3]),
            "local_output_tokens_est": int(row[4]), "cloud_tokens_avoided_est": avoided_cloud_tokens,
            "cloud_token_cost_usd_per_million": self.cloud_token_cost_usd_per_million,
            "estimated_savings_usd": round(avoided_cloud_tokens * self.cloud_token_cost_usd_per_million / 1_000_000, 4),
            "avg_duration_ms": round(float(row[6]), 1), "p50_duration_ms": _percentile(durations, 0.50),
            "p95_duration_ms": _percentile(durations, 0.95), "p99_duration_ms": _percentile(durations, 0.99),
            "aggregate_duration_scope": "inference_only", "cohorts": cohorts,
            "failures": int(row[7]), "failure_rate": round(int(row[7]) / total, 4) if total else 0.0,
            "avg_model_load_duration_ms": round(float(row[8]), 1), "avg_queue_wait_ms": round(float(row[9]), 1),
            "fallback_count": int(row[10]), "degraded_count": int(row[11]), "retry_count": int(row[12]),
            "ollama_inference_calls": int(dict(by_cache).get("ollama", 0)),
            "ollama_calls_avoided_est": max(0, total - int(dict(by_cache).get("ollama", 0))),
            "cache_layers": {str(r[0]): int(r[1]) for r in by_cache},
            "by_action": [
                {"action": r[0], "calls": int(r[1]), "cloud_tokens_avoided_est": int(r[2]), "avg_ms": round(float(r[3]), 1)}
                for r in by_action
            ],
            "http": {
                "requests": http_total, "failures": int(http[1]),
                "failure_rate": round(int(http[1]) / http_total, 4) if http_total else 0.0,
                "avg_ms": round(float(http[2]), 1),
            },
            "tool_adoption": {
                "http_calls": int(tool_http[0]), "agents": int(tool_http[1]),
                "command_calls": int(tool_http[2]), "repo_calls": int(tool_http[3]),
            },
            "writer": writer,
        }
        self._summary_cache[key] = {"time": now, "data": res}
        return res

    def report(self, days: int = 30, *, recent_errors: int = 25, scope: str = "window") -> dict[str, Any]:
        """Produce a prompt/source-free diagnostic report suitable for sharing."""
        if not self.enabled:
            return {"enabled": False}
        self.flush(1.0)
        days = max(1, min(int(days), self.rollup_retention_days))
        cutoff, scope = self._scope_cutoff(days, scope)
        with closing(self._connect()) as con:
            by_agent = con.execute(
                """SELECT CASE WHEN agent='' THEN 'unknown' ELSE agent END,
                          COALESCE(SUM(CASE WHEN event_type='http' THEN 1 ELSE 0 END),0),
                          COALESCE(AVG(CASE WHEN event_type='http' THEN duration_ms END),0),
                          COALESCE(SUM(CASE WHEN event_type='http' AND success=0 THEN 1 ELSE 0 END),0),
                          COALESCE(SUM(CASE WHEN event_type='inference' THEN avoided_cloud_tokens ELSE 0 END),0),
                          COALESCE(SUM(CASE WHEN event_type='inference' THEN 1 ELSE 0 END),0)
                   FROM events WHERE created_at>=? GROUP BY agent ORDER BY COUNT(*) DESC""", (cutoff,)
            ).fetchall()
            by_model = con.execute(
                """SELECT model,COUNT(*),COALESCE(AVG(duration_ms),0),COALESCE(AVG(load_duration_ms),0),COALESCE(SUM(CASE WHEN success=0 THEN 1 ELSE 0 END),0)
                   FROM events WHERE created_at>=? AND event_type='inference' AND model<>'' GROUP BY model ORDER BY COUNT(*) DESC""", (cutoff,)
            ).fetchall()
            actions = con.execute(
                """SELECT action,event_type,COUNT(*),COALESCE(AVG(duration_ms),0),COALESCE(AVG(queue_wait_ms),0),
                          COALESCE(SUM(CASE WHEN success=0 THEN 1 ELSE 0 END),0),COALESCE(SUM(cache_hit),0),
                          COALESCE(SUM(fallback_used),0),COALESCE(SUM(retry_count),0)
                   FROM events WHERE created_at>=? GROUP BY action,event_type ORDER BY COUNT(*) DESC LIMIT 50""", (cutoff,)
            ).fetchall()
            routes = con.execute(
                """SELECT route,task_type,complexity,COUNT(*),COALESCE(AVG(duration_ms),0),COALESCE(SUM(CASE WHEN success=0 THEN 1 ELSE 0 END),0)
                   FROM events WHERE created_at>=? AND event_type='http' AND route<>''
                   GROUP BY route,task_type,complexity ORDER BY COUNT(*) DESC LIMIT 40""", (cutoff,)
            ).fetchall()
            errors = con.execute(
                """SELECT fingerprint,error_type,component,operation,COUNT(*),MAX(created_at),MAX(safe_message),SUM(retryable),SUM(recovered)
                   FROM errors WHERE created_at>=? GROUP BY fingerprint,error_type,component,operation ORDER BY COUNT(*) DESC,MAX(created_at) DESC LIMIT ?""",
                (cutoff, max(1, min(int(recent_errors), 100))),
            ).fetchall()
            daily = con.execute(
                """SELECT day,SUM(events),SUM(duration_ms),SUM(queue_wait_ms),SUM(avoided_cloud_tokens),SUM(cache_hits),SUM(fallback_count),SUM(degraded_count),SUM(CASE WHEN success=0 THEN events ELSE 0 END)
                   FROM daily_rollups WHERE day>=? GROUP BY day ORDER BY day""",
                (datetime.fromtimestamp(cutoff, tz=timezone.utc).strftime("%Y-%m-%d"),),
            ).fetchall()
            cache = con.execute(
                """SELECT CASE WHEN cache_layer='' THEN 'uncategorized' ELSE cache_layer END,COUNT(*),COALESCE(AVG(duration_ms),0),COALESCE(SUM(avoided_cloud_tokens),0)
                   FROM events WHERE created_at>=? AND event_type='inference' GROUP BY cache_layer ORDER BY COUNT(*) DESC""", (cutoff,)
            ).fetchall()
            cache_decisions = con.execute(
                """SELECT error_type,COUNT(*) FROM events
                   WHERE created_at>=? AND event_type='stage' AND stage='cache_decision'
                   GROUP BY error_type ORDER BY COUNT(*) DESC""",
                (cutoff,),
            ).fetchall()
            http_tail_rows = con.execute(
                """SELECT action, duration_ms, queue_wait_ms, service_ms, success
                   FROM events WHERE created_at>=? AND event_type='http'""",
                (cutoff,),
            ).fetchall()
            http_cache_tail_rows = con.execute(
                """SELECT CASE WHEN cache_layer='' THEN 'uncategorized' ELSE cache_layer END,
                          duration_ms, queue_wait_ms, service_ms, success
                   FROM events WHERE created_at>=? AND event_type='http'""",
                (cutoff,),
            ).fetchall()
            agent_tail_rows = con.execute(
                """SELECT CASE WHEN agent='' THEN 'unknown' ELSE agent END,
                          duration_ms, queue_wait_ms, service_ms, success
                   FROM events WHERE created_at>=? AND event_type='http'""",
                (cutoff,),
            ).fetchall()
            snapshots = con.execute(
                "SELECT created_at,name,metrics_json FROM snapshots WHERE created_at>=? ORDER BY created_at DESC LIMIT 20", (cutoff,)
            ).fetchall()
            evaluations = con.execute(
                "SELECT created_at,metrics_json FROM snapshots WHERE created_at>=? AND name='agent_evaluation' ORDER BY created_at",
                (cutoff,),
            ).fetchall()
        summary = self.summary(days, scope=scope)
        evaluation = self._evaluation_summary(evaluations)
        hotspots: list[dict[str, Any]] = []
        if summary.get("failure_rate", 0) >= 0.02:
            hotspots.append({"type": "reliability", "signal": "inference_failure_rate", "value": summary["failure_rate"]})
        if summary.get("avg_queue_wait_ms", 0) >= 500:
            hotspots.append({"type": "latency", "signal": "queue_wait", "value_ms": summary["avg_queue_wait_ms"]})
        if summary.get("cache_hit_rate", 0) < 0.35 and summary.get("events", 0) >= 50:
            hotspots.append({"type": "efficiency", "signal": "low_cache_hit_rate", "value": summary["cache_hit_rate"]})
        if summary.get("fallback_count", 0) >= 5:
            hotspots.append({"type": "quality", "signal": "frequent_model_fallbacks", "count": summary["fallback_count"]})
        if summary.get("retry_count", 0) >= 10:
            hotspots.append({"type": "reliability", "signal": "frequent_ollama_retries", "count": summary["retry_count"]})
        if summary.get("writer", {}).get("dropped", 0):
            hotspots.append({"type": "observability", "signal": "telemetry_queue_drops", "count": summary["writer"]["dropped"]})
        return {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "window_days": days,
            "scope": scope,
            "process_started_at": self.process_started_at if scope == "process" else None,
            "privacy": {
                "prompts_stored": False, "source_text_stored": False, "model_output_stored": False,
                "error_messages": "sanitized paths/tokens; max 500 chars",
            },
            "summary": summary,
            "by_agent": [
                {"agent": r[0], "requests": int(r[1]), "avg_ms": round(float(r[2]), 1), "failures": int(r[3]), "cloud_tokens_avoided_est": int(r[4]), "local_inference_calls": int(r[5])}
                for r in by_agent
            ],
            "by_model": [
                {"model": r[0], "calls": int(r[1]), "avg_ms": round(float(r[2]), 1), "avg_load_ms": round(float(r[3]), 1), "failures": int(r[4])}
                for r in by_model
            ],
            "by_operation": [
                {"action": r[0], "event_type": r[1], "calls": int(r[2]), "avg_ms": round(float(r[3]), 1), "avg_queue_wait_ms": round(float(r[4]), 1), "failures": int(r[5]), "cache_hits": int(r[6]), "fallbacks": int(r[7]), "retries": int(r[8])}
                for r in actions
            ],
            "execution_routes": [
                {"route": r[0], "task_type": r[1], "complexity": r[2], "calls": int(r[3]), "avg_ms": round(float(r[4]), 1), "failures": int(r[5])}
                for r in routes
            ],
            "cache_layers": [
                {"layer": r[0], "calls": int(r[1]), "avg_ms": round(float(r[2]), 1), "cloud_tokens_avoided_est": int(r[3])}
                for r in cache
            ],
            "cache_decisions": {str(r[0]): int(r[1]) for r in cache_decisions},
            "http_tail_latency": {
                "by_action": _tail_latency(http_tail_rows, "action"),
                "by_cache_layer": _tail_latency(http_cache_tail_rows, "cache_layer"),
            },
            "agent_slo": _tail_latency(agent_tail_rows, "agent"),
            "error_fingerprints": [
                {"fingerprint": r[0], "error_type": r[1], "component": r[2], "operation": r[3], "count": int(r[4]),
                 "last_seen": float(r[5]), "safe_message": r[6], "retryable_count": int(r[7]), "recovered_count": int(r[8])}
                for r in errors
            ],
            "daily": [
                {"day": r[0], "events": int(r[1]), "duration_ms": round(float(r[2]), 1), "queue_wait_ms": round(float(r[3]), 1),
                 "cloud_tokens_avoided_est": int(r[4]), "cache_hits": int(r[5]), "fallbacks": int(r[6]), "degraded": int(r[7]), "failures": int(r[8])}
                for r in daily
            ],
            "runtime_snapshots": [
                {"created_at": float(r[0]), "name": r[1], "metrics": json.loads(r[2]) if r[2] else {}} for r in snapshots
            ],
            "evaluation": evaluation,
            "hotspots": hotspots,
        }

    def tail(self, limit: int = 20) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        self.flush(0.5)
        limit = max(1, min(int(limit), 100))
        with closing(self._connect()) as con:
            rows = con.execute(
                """SELECT id,created_at,event_type,tenant,agent,request_id,action,stage,model,cache_hit,coalesced,input_tokens,output_tokens,
                          avoided_cloud_tokens,duration_ms,queue_wait_ms,success,status_code,cache_layer,fallback_used,degraded,error_type,error_fingerprint
                   FROM events ORDER BY id DESC LIMIT ?""", (limit,)
            ).fetchall()
        return [
            {
                "id": r[0], "created_at": r[1], "event_type": r[2], "tenant": r[3], "agent": r[4], "request_id": r[5],
                "action": r[6], "stage": r[7], "model": r[8], "cache_hit": bool(r[9]), "coalesced": bool(r[10]),
                "input_tokens": r[11], "output_tokens": r[12], "cloud_tokens_avoided_est": r[13], "duration_ms": r[14],
                "queue_wait_ms": r[15], "success": bool(r[16]), "status_code": r[17], "cache_layer": r[18],
                "fallback_used": bool(r[19]), "degraded": bool(r[20]), "error_type": r[21], "error_fingerprint": r[22],
            }
            for r in rows
        ]

    def recent_http(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return recent persisted API requests for the dashboard request history."""
        if not self.enabled:
            return []
        self.flush(0.5)
        limit = max(1, min(int(limit), 200))
        with closing(self._connect()) as con:
            rows = con.execute(
                """SELECT id,created_at,request_id,agent,tenant,action,status_code,duration_ms,success,error_type
                   FROM events WHERE event_type='http' ORDER BY id DESC LIMIT ?""", (limit,)
            ).fetchall()
        return [
            {
                "id": int(row[0]), "created_at": float(row[1]), "request_id": row[2], "agent": row[3],
                "tenant": row[4], "action": row[5], "status_code": int(row[6] or 0),
                "duration_ms": float(row[7] or 0), "success": bool(row[8]), "error_type": row[9],
            }
            for row in rows
        ]

    def http_latency_estimate(self, action: str, limit: int = 200) -> dict[str, Any]:
        """Return bounded endpoint history for opt-in foreground/async delivery choice."""
        if not self.enabled:
            return {"samples": 0, "p95_duration_ms": 0.0}
        self.flush(0.1)
        bounded = max(1, min(int(limit), 500))
        with closing(self._connect()) as con:
            rows = con.execute(
                """SELECT duration_ms FROM events WHERE event_type='http' AND action=?
                   ORDER BY id DESC LIMIT ?""",
                (str(action)[:160], bounded),
            ).fetchall()
        values = [float(row[0] or 0.0) for row in rows]
        return {"samples": len(values), "p95_duration_ms": _percentile(values, 0.95)}

    def close(self) -> None:
        if not self.enabled:
            return
        self._stop.set()
        if self._thread and self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join(timeout=max(1.0, self.flush_interval_seconds * 4))
