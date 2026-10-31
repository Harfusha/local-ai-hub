"""Persistent, unexpiring long-term telemetry for endpoints and MCP tools."""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Any, Mapping, Sequence

from .sqlite_support import connect_sqlite, is_busy_error


LATENCY_BUCKET_LIMITS: tuple[float, ...] = (
    5.0, 10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0, 2500.0, 5000.0, 10000.0, 30000.0, 60000.0
)
NUM_BUCKETS: int = len(LATENCY_BUCKET_LIMITS) + 1  # 14 buckets: b0..b13

BUCKET_INTERVALS: tuple[tuple[float, float], ...] = (
    (0.0, 5.0),
    (5.0, 10.0),
    (10.0, 25.0),
    (25.0, 50.0),
    (50.0, 100.0),
    (100.0, 250.0),
    (250.0, 500.0),
    (500.0, 1000.0),
    (1000.0, 2500.0),
    (2500.0, 5000.0),
    (5000.0, 10000.0),
    (10000.0, 30000.0),
    (30000.0, 60000.0),
    (60000.0, 120000.0),
)


def get_latency_bucket_index(duration_ms: float) -> int:
    """Return bucket index 0..13 for a given duration in milliseconds."""
    val = float(duration_ms) if duration_ms > 0 else 0.0
    for idx, limit in enumerate(LATENCY_BUCKET_LIMITS):
        if val < limit:
            return idx
    return len(LATENCY_BUCKET_LIMITS)


def calculate_percentiles(bucket_counts: Sequence[int], total_calls: int) -> tuple[float, float, float]:
    """Calculate p50, p95, p99 latency in ms from histogram bucket counts."""
    if total_calls <= 0 or not bucket_counts:
        return 0.0, 0.0, 0.0

    def _calc_p(target_rank: float) -> float:
        accum = 0
        for idx, count in enumerate(bucket_counts):
            if count <= 0:
                continue
            if accum + count >= target_rank:
                low, high = BUCKET_INTERVALS[min(idx, len(BUCKET_INTERVALS) - 1)]
                offset = max(0.0, target_rank - accum)
                fraction = offset / count if count > 0 else 0.5
                val = low + fraction * (high - low)
                return max(0.0, round(val, 1))
            accum += count
        return round(BUCKET_INTERVALS[-1][1], 1)

    p50 = _calc_p(0.50 * total_calls)
    p95 = _calc_p(0.95 * total_calls)
    p99 = _calc_p(0.99 * total_calls)
    return p50, p95, p99


def clean_project_root(root: str | None) -> str:
    """Normalize project root to safe directory basename or empty string."""
    if not root:
        return ""
    raw = str(root).replace("\\", "/").rstrip("/")
    if not raw or raw in ("all", "__all__"):
        return ""
    return Path(raw).name


def get_registered_surface_catalog() -> list[dict[str, str]]:
    """Return all known endpoints and MCP tools/actions to show uncalled items."""
    catalog: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def _add(item_type: str, item_name: str) -> None:
        key = (item_type, item_name)
        if key not in seen:
            seen.add(key)
            catalog.append({"type": item_type, "name": item_name})

    # HTTP POST endpoints
    try:
        from .http_route_registry import POST_ROUTE_REGISTRY
        for rule in POST_ROUTE_REGISTRY:
            for path in sorted(rule.paths):
                _add("endpoint", path)
    except Exception:
        pass

    # Known HTTP GET endpoints
    get_paths = (
        "/api/status", "/api/live", "/api/live/status", "/api/metrics",
        "/api/models", "/api/mode", "/api/preprocess/status", "/api/project/config",
        "/api/rag/workspaces", "/api/telemetry/report", "/api/telemetry/endpoint-stats",
        "/api/doctor", "/api/hardware/gpu", "/api/hardware/system", "/api/db/query",
        "/api/audit/tail", "/api/logs/tail", "/api/benchmark/summary",
        "/health", "/ready", "/dashboard"
    )
    for path in get_paths:
        _add("endpoint", path)

    # MCP tools & common actions
    mcp_items = (
        "local_ai_status",
        "local_ai_task",
        "local_ai_task:review",
        "local_ai_task:second_opinion",
        "local_ai_task:explore",
        "local_ai_task:reason",
        "local_ai_task:compress",
        "local_ai_repo",
        "local_ai_repo:context",
        "local_ai_repo:search",
        "local_ai_repo:code_index",
        "local_ai_repo:solve",
        "local_ai_repo:review_diff",
        "local_ai_repo:security_audit",
        "local_ai_rag",
        "local_ai_rag:query",
        "local_ai_coord",
        "local_ai_coord:task_create",
        "local_ai_coord:task_checkpoint",
        "local_ai_coord:memory_record",
        "local_ai_coord:memory_find",
        "local_ai_work",
        "local_ai_artifact",
    )
    for m in mcp_items:
        _add("mcp", m)

    return catalog


class EndpointStatsStore:
    """Stores persistent, non-expiring statistics for endpoints and MCP tools."""

    def __init__(self, state_dir: Path | str, *, enabled: bool = True) -> None:
        self.enabled = bool(enabled)
        self.state_dir = Path(state_dir)
        self.path = self.state_dir / "endpoint_stats.sqlite3"
        self._lock = threading.RLock()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        if self.enabled:
            self._init_db()

    def _connect(self, timeout_seconds: float = 5.0) -> sqlite3.Connection:
        return connect_sqlite(self.path, timeout_seconds=timeout_seconds)

    def _init_db(self) -> None:
        with self._lock, closing(self._connect()) as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA synchronous=NORMAL")
            columns = [
                "scope_root TEXT NOT NULL DEFAULT ''",
                "item_type TEXT NOT NULL",
                "item_name TEXT NOT NULL",
                "calls INTEGER NOT NULL DEFAULT 0",
                "success_calls INTEGER NOT NULL DEFAULT 0",
                "fail_calls INTEGER NOT NULL DEFAULT 0",
            ]
            for i in range(NUM_BUCKETS):
                columns.append(f"b{i} INTEGER NOT NULL DEFAULT 0")
            columns.append("last_used REAL NOT NULL DEFAULT 0")
            columns.append("PRIMARY KEY(scope_root, item_type, item_name)")

            sql = f"CREATE TABLE IF NOT EXISTS endpoint_stats ({', '.join(columns)})"
            con.execute(sql)
            con.execute("CREATE INDEX IF NOT EXISTS idx_ep_stats_root ON endpoint_stats(scope_root)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_ep_stats_item ON endpoint_stats(item_type, item_name)")
            con.commit()

    def record_call(
        self,
        *,
        item_type: str,
        item_name: str,
        duration_ms: float,
        success: bool = True,
        root: str = "",
    ) -> None:
        """Record an endpoint or MCP tool call into the histogram."""
        if not self.enabled:
            return
        clean_type = "mcp" if str(item_type).lower().strip() == "mcp" else "endpoint"
        clean_name = str(item_name).strip()[:200]
        if not clean_name:
            return
        safe_root = clean_project_root(root)
        b_idx = get_latency_bucket_index(duration_ms)
        is_succ = 1 if success else 0
        is_fail = 0 if success else 1
        now = time.time()

        col_b = f"b{b_idx}"
        sql = f"""
        INSERT INTO endpoint_stats(
            scope_root, item_type, item_name, calls, success_calls, fail_calls, {col_b}, last_used
        ) VALUES (?, ?, ?, 1, ?, ?, 1, ?)
        ON CONFLICT(scope_root, item_type, item_name) DO UPDATE SET
            calls = calls + 1,
            success_calls = success_calls + ?,
            fail_calls = fail_calls + ?,
            {col_b} = {col_b} + 1,
            last_used = ?
        """
        try:
            with self._lock, closing(self._connect()) as con:
                con.execute(sql, (safe_root, clean_type, clean_name, is_succ, is_fail, now, is_succ, is_fail, now))
                con.commit()
        except sqlite3.Error:
            pass

    def get_stats(self, root: str | None = None) -> dict[str, Any]:
        """Query statistics, optionally filtered to a project root or aggregated globally."""
        if not self.enabled:
            return {"success": False, "error": "endpoint stats disabled", "projects": [], "items": []}

        target_root = clean_project_root(root)
        is_global = root is None or str(root).strip() in ("", "all", "__all__")

        catalog = get_registered_surface_catalog()
        known_map: dict[tuple[str, str], dict[str, Any]] = {}
        for c in catalog:
            known_map[(c["type"], c["name"])] = {
                "type": c["type"],
                "name": c["name"],
                "calls": 0,
                "success_calls": 0,
                "fail_calls": 0,
                "success_rate": None,
                "p50_ms": 0.0,
                "p95_ms": 0.0,
                "p99_ms": 0.0,
                "last_used": 0.0,
                "status": "unused",
                "bucket_counts": [0] * NUM_BUCKETS,
            }

        projects: list[str] = []
        try:
            with self._lock, closing(self._connect()) as con:
                p_rows = con.execute("SELECT DISTINCT scope_root FROM endpoint_stats WHERE scope_root != '' ORDER BY scope_root").fetchall()
                projects = [str(r[0]) for r in p_rows]

                # Also include all items currently known in DB across any scope
                db_items = con.execute("SELECT DISTINCT item_type, item_name FROM endpoint_stats").fetchall()
                for d_type, d_name in db_items:
                    key = (str(d_type), str(d_name))
                    if key not in known_map:
                        known_map[key] = {
                            "type": str(d_type),
                            "name": str(d_name),
                            "calls": 0,
                            "success_calls": 0,
                            "fail_calls": 0,
                            "success_rate": None,
                            "p50_ms": 0.0,
                            "p95_ms": 0.0,
                            "p99_ms": 0.0,
                            "last_used": 0.0,
                            "status": "unused",
                            "bucket_counts": [0] * NUM_BUCKETS,
                        }

                bucket_cols = ", ".join(f"b{i}" for i in range(NUM_BUCKETS))
                if is_global:
                    query = f"""
                    SELECT item_type, item_name,
                           SUM(calls), SUM(success_calls), SUM(fail_calls),
                           {', '.join(f'SUM(b{i})' for i in range(NUM_BUCKETS))},
                           MAX(last_used)
                    FROM endpoint_stats
                    GROUP BY item_type, item_name
                    """
                    rows = con.execute(query).fetchall()
                else:
                    query = f"""
                    SELECT item_type, item_name,
                           calls, success_calls, fail_calls,
                           {bucket_cols},
                           last_used
                    FROM endpoint_stats
                    WHERE scope_root = ?
                    """
                    rows = con.execute(query, (target_root,)).fetchall()

                for r in rows:
                    itype = str(r[0])
                    iname = str(r[1])
                    calls = int(r[2] or 0)
                    succ = int(r[3] or 0)
                    fail = int(r[4] or 0)
                    b_counts = [int(r[5 + i] or 0) for i in range(NUM_BUCKETS)]
                    l_used = float(r[5 + NUM_BUCKETS] or 0.0)

                    p50, p95, p99 = calculate_percentiles(b_counts, calls)
                    succ_rate = round((succ / calls) * 100.0, 1) if calls > 0 else None

                    status = "active"
                    if calls == 0:
                        status = "unused"
                    elif succ_rate is not None and succ_rate < 90.0:
                        status = "failing"
                    elif p95 >= 1000.0:
                        status = "slow"

                    known_map[(itype, iname)] = {
                        "type": itype,
                        "name": iname,
                        "calls": calls,
                        "success_calls": succ,
                        "fail_calls": fail,
                        "success_rate": succ_rate,
                        "p50_ms": p50,
                        "p95_ms": p95,
                        "p99_ms": p99,
                        "last_used": l_used,
                        "status": status,
                        "bucket_counts": b_counts,
                    }
        except sqlite3.Error:
            pass

        items = list(known_map.values())
        return {
            "success": True,
            "root": target_root if not is_global else "",
            "is_global": is_global,
            "projects": projects,
            "total_items": len(items),
            "unused_count": sum(1 for it in items if it["calls"] == 0),
            "slow_count": sum(1 for it in items if it["status"] == "slow"),
            "failing_count": sum(1 for it in items if it["status"] == "failing"),
            "items": items,
        }

    def reset(self, root: str | None = None) -> bool:
        """Reset statistics globally or for a specific project."""
        if not self.enabled:
            return False
        target_root = clean_project_root(root)
        is_global = root is None or str(root).strip() in ("", "all", "__all__")
        try:
            with self._lock, closing(self._connect()) as con:
                if is_global:
                    con.execute("DELETE FROM endpoint_stats")
                else:
                    con.execute("DELETE FROM endpoint_stats WHERE scope_root = ?", (target_root,))
                con.commit()
            return True
        except sqlite3.Error:
            return False
