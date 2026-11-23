from __future__ import annotations

from contextlib import closing
from typing import Any

from .telemetry import (
    _percentile,
)


class TelemetryQueryMixin:
    def tail(self, limit: int = 20) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        self.flush(0.5)
        limit = max(1, min(int(limit), 100))
        with closing(self._connect()) as con:
            rows = con.execute(
                """SELECT id,created_at,event_type,agent,request_id,action,stage,model,cache_hit,coalesced,input_tokens,cache_read_tokens,output_tokens,
                          avoided_cloud_tokens,duration_ms,queue_wait_ms,wait_count,wait_duration_ms,success,status_code,cache_layer,fallback_used,degraded,error_type,error_fingerprint
                   FROM events ORDER BY id DESC LIMIT ?""", (limit,)
            ).fetchall()
        return [
            {
                "id": r[0], "created_at": r[1], "event_type": r[2], "agent": r[3], "request_id": r[4],
                "action": r[5], "stage": r[6], "model": r[7], "cache_hit": bool(r[8]), "coalesced": bool(r[9]),
                "input_tokens": r[10], "cache_read_tokens": r[11], "output_tokens": r[12], "net_cloud_token_delta_est": r[13], "duration_ms": r[14],
                "queue_wait_ms": r[15], "wait_count": r[16], "wait_duration_ms": r[17], "success": bool(r[18]), "status_code": r[19], "cache_layer": r[20],
                "fallback_used": bool(r[21]), "degraded": bool(r[22]), "error_type": r[23], "error_fingerprint": r[24],
            }
            for r in rows
        ]

    def request_metrics(self, request_id: str) -> dict[str, Any]:
        """Return bounded numeric telemetry for one request, without event payloads."""
        empty = {
            "available": False,
            "inference_events": 0,
            "cache_hits": 0,
            "cache_hit_rate": None,
            "input_tokens": 0,
            "cache_read_tokens": 0,
            "output_tokens": 0,
            "avoided_cloud_tokens": 0,
            "gross_avoided_cloud_tokens": 0,
            "net_cloud_token_delta": 0,
        }
        request_id = str(request_id or "").strip()
        if not self.enabled or not request_id or len(request_id) > 128:
            return empty
        self.flush(0.5)
        with closing(self._connect()) as con:
            row = con.execute(
                """SELECT COUNT(*),
                          SUM(CASE WHEN event_type='inference' THEN 1 ELSE 0 END),
                          SUM(CASE WHEN event_type='inference' AND cache_hit=1 THEN 1 ELSE 0 END),
                          SUM(CASE WHEN event_type='inference' THEN input_tokens ELSE 0 END),
                          SUM(CASE WHEN event_type='inference' THEN cache_read_tokens ELSE 0 END),
                          SUM(CASE WHEN event_type='inference' THEN output_tokens ELSE 0 END),
                          SUM(avoided_cloud_tokens),
                          SUM(gross_avoided_cloud_tokens),
                          SUM(net_cloud_token_delta)
                   FROM events WHERE request_id=?""",
                (request_id,),
            ).fetchone()
        inference_events = int(row[1] or 0)
        cache_hits = int(row[2] or 0)
        return {
            "available": inference_events > 0,
            "inference_events": inference_events,
            "cache_hits": cache_hits,
            "cache_hit_rate": round(cache_hits / inference_events, 4) if inference_events else None,
            "input_tokens": int(row[3] or 0),
            "cache_read_tokens": int(row[4] or 0),
            "output_tokens": int(row[5] or 0),
            "avoided_cloud_tokens": int(row[6] or 0),
            "gross_avoided_cloud_tokens": int(row[7] or 0),
            "net_cloud_token_delta": int(row[8] or 0),
        }

    def recent_http(self, limit: int = 50, *, _flush: bool = True) -> list[dict[str, Any]]:
        """Return recent persisted API requests for the dashboard request history."""
        if not self.enabled:
            return []
        if _flush:
            self.flush(0.5)
        limit = max(1, min(int(limit), 200))
        with closing(self._connect()) as con:
            rows = con.execute(
                """SELECT id,created_at,request_id,agent,root,action,status_code,duration_ms,success,error_type
                   FROM events WHERE event_type='http' ORDER BY id DESC LIMIT ?""", (limit,)
            ).fetchall()
        return [
            {
                "id": int(row[0]), "created_at": float(row[1]), "request_id": row[2], "agent": row[3],
                "root": row[4], "action": row[5], "status_code": int(row[6] or 0),
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

    def get_timeline_page(
        self,
        limit: int = 100,
        *,
        before_id: int | None = None,
        _flush: bool = True,
    ) -> dict[str, Any]:
        """Return a recent chronological page with a cursor for older events."""
        if not self.enabled:
            return {"timeline": [], "next_cursor": None, "has_more": False}
        if _flush:
            self.flush(0.2)
        try:
            bounded_limit = max(1, min(int(limit), 500))
        except (TypeError, ValueError, OverflowError):
            bounded_limit = 100
        try:
            cursor = min(2**63 - 1, max(0, int(before_id))) if before_id is not None else None
        except (TypeError, ValueError, OverflowError):
            cursor = None
        with closing(self._connect()) as con:
            sql = """SELECT id, created_at, event_type, agent, action, duration_ms, success,
                          avoided_cloud_tokens, error_type
                   FROM events"""
            values: tuple[Any, ...] = ()
            if cursor is not None:
                sql += " WHERE id < ?"
                values = (cursor,)
            rows = con.execute(
                sql + " ORDER BY id DESC LIMIT ?",
                (*values, bounded_limit + 1),
            ).fetchall()
        has_more = len(rows) > bounded_limit
        page_rows = list(reversed(rows[:bounded_limit]))
        timeline = [
            {
                "id": int(row[0]),
                "timestamp": float(row[1]),
                "event_type": str(row[2]),
                "agent": str(row[3]),
                "action": str(row[4]),
                "duration_ms": float(row[5] or 0),
                "success": bool(row[6]),
                "net_tokens_saved": int(row[7] or 0),
                "error_type": str(row[8] or ""),
            }
            for row in page_rows
        ]
        return {
            "timeline": timeline,
            "next_cursor": int(page_rows[0][0]) if has_more and page_rows else None,
            "has_more": has_more,
        }

    def get_timeline(self, limit: int = 100, *, _flush: bool = True) -> list[dict[str, Any]]:
        """Return chronological timeline of agent operations for session replay and visualization."""
        if not self.enabled:
            return []
        if _flush:
            self.flush(0.2)
        limit = max(1, min(int(limit), 500))
        with closing(self._connect()) as con:
            rows = con.execute(
                """SELECT id, created_at, event_type, agent, action, duration_ms, success,
                          avoided_cloud_tokens, error_type
                   FROM events ORDER BY id ASC LIMIT ?""", (limit,)
            ).fetchall()
        return [
            {
                "id": int(r[0]),
                "timestamp": float(r[1]),
                "event_type": str(r[2]),
                "agent": str(r[3]),
                "action": str(r[4]),
                "duration_ms": float(r[5] or 0),
                "success": bool(r[6]),
                "net_tokens_saved": int(r[7] or 0),
                "error_type": str(r[8] or ""),
            }
            for r in rows
        ]
