from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import sqlite3
import time
from typing import Any, Iterable

from .telemetry import (
    _DASHBOARD_CACHE_LIMIT,
    _DECISION_DETAIL_LIMIT,
    _MAX_QUERY_WINDOW_DAYS,
    _REPORT_GROUP_LIMIT,
    _SUMMARY_CACHE_LIMIT,
    _bound_telemetry_report,
    _decode_error_page_cursor,
    _encode_error_page_cursor,
    _laya_decision_report,
    _percentile,
    _tail_latency,
)
from . import telemetry as services_module


class TelemetryAggregateMixin:
    def dashboard_report(self, days: int = 30, ttl_seconds: float = 5.0, *, scope: str = "window") -> dict[str, Any]:
        """Cached persistent report used by the realtime dashboard.

        Most dashboard polls are RAM-only; at most one thread refreshes the SQLite
        aggregate every few seconds. This keeps counters stable across hub restarts.
        """
        bounded_days = max(1, min(int(days), _MAX_QUERY_WINDOW_DAYS))
        _, scope = self._scope_cutoff(bounded_days, scope)
        key = (bounded_days, scope)
        now = time.monotonic()
        with self._dashboard_lock:
            cached = self._dashboard_cache.get(key)
            cached_at = self._dashboard_cache_at.get(key, 0.0)
            if cached and now - cached_at < max(1.0, float(ttl_seconds)):
                return self._refresh_dashboard_report_writer(cached)
            try:
                report = self.report(bounded_days, recent_errors=12, scope=scope, _flush=False)
                report["recent_http"] = self.recent_http(50, _flush=False)
                report["summary"] = {**report.get("summary", {}), "data_available": self.enabled, "stale": False}
            except Exception:
                report = dict(cached) if cached else {"summary": {"enabled": self.enabled}}
                report["summary"] = {
                    **report.get("summary", {}), "data_available": False,
                    "stale": bool(cached), "degraded": True,
                }
                if cached:
                    report = self._refresh_dashboard_report_writer(report)
            self._dashboard_cache[key] = report
            self._dashboard_cache_at[key] = now
            while len(self._dashboard_cache) > _DASHBOARD_CACHE_LIMIT:
                oldest_key = min(self._dashboard_cache_at, key=self._dashboard_cache_at.get)
                self._dashboard_cache.pop(oldest_key, None)
                self._dashboard_cache_at.pop(oldest_key, None)
            return dict(report)

    def realtime_summary(self, *, scope: str = "process", light: bool = False) -> dict[str, Any]:
        if not self.enabled:
            return {"enabled": False}
        if getattr(self, "mode", "full") == "minimal":
            with self._stats_lock:
                return {
                    "enabled": True,
                    "mode": "minimal",
                    "events": self._minimal_stats["requests_total"],
                    "requests_total": self._minimal_stats["requests_total"],
                    "errors_total": self._minimal_stats["errors_total"],
                    "uptime_seconds": round(time.time() - self._minimal_stats["start_time"], 2),
                }
        with self._live_lock:
            window_events = len(self._live_events)
            inference_count = 0
            started: dict[str, dict[str, Any]] = {}
            finished: set[str] = set()
            for event in self._live_events:
                if event.get("event_type") == "inference":
                    inference_count += 1
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
                "action": str(event.get("action") or "")[:100],
                "age_ms": max(0, int((now_wall - float(event.get("created_at", now_wall) or now_wall)) * 1000)),
            })
        active_requests.sort(key=lambda item: int(item.get("age_ms", 0)), reverse=True)
        active_requests = active_requests[:24]

        report = self.dashboard_report(30, scope=scope) if self.enabled else {"summary": {}}
        history = report.get("summary", {}) if isinstance(report, dict) else {}
        return {
            "enabled": self.enabled,
            "data_available": bool(history.get("data_available", self.enabled and "net_cloud_token_delta_est" in history)),
            "stale": bool(history.get("stale", False)),
            "writer": history.get("writer", {}),
            "summary_cache_stale": bool(history.get("summary_cache_stale", False)),
            "scope": str(history.get("scope", scope) or scope),
            "process_started_at": history.get("process_started_at") if scope == "process" else None,
            "window_events": window_events, "live_inference_events": inference_count,
            "inference_events": int(history.get("events", inference_count) or 0),
            "cache_hits": int(history.get("cache_hits", 0) or 0),
            "cache_hit_rate": float(history.get("cache_hit_rate", 0.0) or 0.0),
            "generation_cache_hits": int(history.get("generation_cache_hits", history.get("cache_hits", 0)) or 0),
            "generation_cache_hit_rate": float(history.get("generation_cache_hit_rate", history.get("cache_hit_rate", 0.0)) or 0.0),
            "preprocessed_query_hits": int(history.get("preprocessed_query_hits", 0) or 0),
            "preprocessed_query_events": int(history.get("preprocessed_query_events", 0) or 0),
            "preprocessed_query_hit_rate": float(history.get("preprocessed_query_hit_rate", 0.0) or 0.0),
            "sessions": [] if light else history.get("sessions", []),
            "cache_domains": history.get("cache_domains", {}),
            "cache_reuse_breakdown": history.get("cache_reuse_breakdown", {}),
            "http_outcomes": history.get("http_outcomes", {}),
            "net_cloud_token_delta_est": int(history.get("net_cloud_token_delta_est", 0) or 0),
            "realistic_net_cloud_token_delta_est": int(history.get("realistic_net_cloud_token_delta_est", history.get("net_cloud_token_delta_est", 0)) or 0),
            "cloud_token_overhead_est": int(history.get("cloud_token_overhead_est", 0) or 0),
            "gross_cloud_tokens_avoided_est": int(history.get("gross_cloud_tokens_avoided_est", 0) or 0),
            "gross_input_cloud_tokens_avoided_est": int(history.get("gross_input_cloud_tokens_avoided_est", 0) or 0),
            "gross_output_cloud_tokens_avoided_est": int(history.get("gross_output_cloud_tokens_avoided_est", 0) or 0),
            "agent_protocol_tokens_est": int(history.get("agent_protocol_tokens_est", 0) or 0),
            "agent_tool_request_tokens_est": int(history.get("agent_tool_request_tokens_est", 0) or 0),
            "agent_tool_response_tokens_est": int(history.get("agent_tool_response_tokens_est", 0) or 0),
            "tool_schema_tokens_exposure_est": int(history.get("tool_schema_tokens_exposure_est", 0) or 0),
            "net_after_schema_token_delta_est": int(history.get("net_after_schema_token_delta_est", 0) or 0),
            "schema_adjusted_overhead_est": int(history.get("schema_adjusted_overhead_est", 0) or 0),
            "local_compute_tokens_avoided_est": int(history.get("local_compute_tokens_avoided_est", 0) or 0),
            "token_savings_breakdown": history.get("token_savings_breakdown", {}),
            "tool_accounting_events": int(history.get("tool_accounting_events", 0) or 0),
            "accounting_boundary_incomplete": bool(history.get("accounting_boundary_incomplete", False)),
            "token_accounting_storage": history.get("token_accounting_storage", "retained_process_events"),
            "estimated_savings_usd": history.get("estimated_savings_usd"),
            "realistic_savings_usd": history.get("realistic_savings_usd"),
            "estimated_input_savings_usd": history.get("estimated_input_savings_usd"),
            "estimated_output_savings_usd": history.get("estimated_output_savings_usd"),
            "estimated_savings_pricing_mode": str(history.get("estimated_savings_pricing_mode", "unknown")),
            "cloud_input_token_cost_usd_per_million": history.get("cloud_input_token_cost_usd_per_million"),
            "cloud_output_token_cost_usd_per_million": history.get("cloud_output_token_cost_usd_per_million"),
            "cloud_cache_read_token_cost_usd_per_million": history.get("cloud_cache_read_token_cost_usd_per_million"),
            "cloud_cache_write_token_cost_usd_per_million": history.get("cloud_cache_write_token_cost_usd_per_million"),
            "active_pricing_profile": str(history.get("active_pricing_profile", self.pricing_profile)),
            "pricing_profiles": history.get("pricing_profiles", services_module.CLOUD_PRICING_PROFILES),

            "realistic_savings_breakdown": history.get("realistic_savings_breakdown", {}),
            "dynamic_depth_tokens": int(history.get("dynamic_depth_tokens", 25000) or 25000),
            "call_categories": history.get("call_categories", {}),
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
            "laya_decisions": report.get("laya_decisions", {}) if isinstance(report, dict) else {},
            "laya_capture_stages": report.get("laya_capture_stages", []) if isinstance(report, dict) else [],
            "laya_capture_reasons": report.get("laya_capture_reasons", []) if isinstance(report, dict) else [],
            "hotspots": report.get("hotspots", []) if isinstance(report, dict) else [],
            "active_request_count": len(active_requests), "active_requests": active_requests,
            "live_cursor": self._live_seq,
            "recent_http": report.get("recent_http", []) if isinstance(report, dict) else [],
            "window": history.get("window", {"scope": scope}),
            "counts": history.get("counts", {}),
            "routes": [] if light else history.get("routes", []),
            "cache": [] if light else history.get("cache", []),
            "bypass": [] if light else history.get("bypass", []),
            "errors": history.get("errors", {}),
            "queue": history.get("queue", {}),
            "detail": {} if light else history.get("detail", {}),
            "decision_grade": {} if light else history.get("decision_grade", {}),
        }

    def _cutoff(self, days: int) -> float:
        bounded_days = max(1, min(int(days), _MAX_QUERY_WINDOW_DAYS))
        return time.time() - bounded_days * 86400

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
        if event_type == "http" and error_type == "compatibility_404":
            return "compatibility"
        if event_type == "http":
            return "agent_http"
        return "internal"

    @classmethod
    def _cohort_summary(cls, rows: Iterable[tuple[Any, ...]]) -> dict[str, dict[str, Any]]:
        cohorts: dict[str, dict[str, Any]] = {
            name: {
                "events": 0,
                "failures": 0,
                "retry_count": 0,
                "fallback_count": 0,
                "degraded_count": 0,
                "durations": [],
            }
            for name in ("agent_http", "inference", "policy_rejection", "compatibility", "internal")
        }
        for row in rows:
            cohort = cohorts[cls._event_cohort(str(row[0]), str(row[1]))]
            cohort["events"] += 1
            cohort["failures"] += int(not int(row[3]))
            cohort["retry_count"] += int(row[4])
            cohort["fallback_count"] += int(row[5])
            cohort["degraded_count"] += int(row[6])
            cohort["durations"].append(float(row[2]))
        result: dict[str, dict[str, Any]] = {}
        for name, values in cohorts.items():
            events = int(values["events"])
            durations = values["durations"]
            result[name] = {
                "events": events,
                "failures": int(values["failures"]),
                "failure_rate": round(values["failures"] / events, 4) if events else 0.0,
                "p50_duration_ms": _percentile(durations, 0.50),
                "p95_duration_ms": _percentile(durations, 0.95),
                "p99_duration_ms": _percentile(durations, 0.99),
                "retry_count": int(values["retry_count"]),
                "fallback_count": int(values["fallback_count"]),
                "degraded_count": int(values["degraded_count"]),
            }
        return result

    def _decision_grade(self, con: sqlite3.Connection, cutoff: float) -> dict[str, Any]:
        """Return bounded, metadata-only aggregates for operational decisions."""
        limit = _DECISION_DETAIL_LIMIT
        route_rows = con.execute(
            """SELECT route,COUNT(*),COALESCE(SUM(CASE WHEN success=0 THEN 1 ELSE 0 END),0),
                      COALESCE(AVG(duration_ms),0)
               FROM events WHERE created_at>=? AND route<>''
               GROUP BY route ORDER BY COUNT(*) DESC,route LIMIT ?""",
            (cutoff, limit + 1),
        ).fetchall()
        cache_rows = con.execute(
            """SELECT CASE WHEN cache_layer='' THEN 'uncategorized' ELSE cache_layer END,
                      COUNT(*),COALESCE(SUM(cache_hit),0),COALESCE(SUM(coalesced),0)
               FROM events WHERE created_at>=?
               GROUP BY cache_layer ORDER BY COUNT(*) DESC,cache_layer LIMIT ?""",
            (cutoff, limit + 1),
        ).fetchall()
        bypass_rows = con.execute(
            """SELECT bypass_reason,error_type,COUNT(*) FROM events
               WHERE created_at>=? AND bypass_reason<>''
               GROUP BY bypass_reason,error_type ORDER BY COUNT(*) DESC,bypass_reason,error_type LIMIT ?""",
            (cutoff, limit + 1),
        ).fetchall()
        queue_rows = con.execute(
            "SELECT queue_age_ms FROM events INDEXED BY idx_events_created WHERE created_at>=? AND queue_age_ms>0 ORDER BY id DESC LIMIT 1000",
            (cutoff,),
        ).fetchall()
        metrics = con.execute(
            """SELECT COUNT(*),
                      COALESCE(SUM(cache_hit),0),
                      COALESCE(SUM(CASE WHEN bypass_reason<>'' THEN 1 ELSE 0 END),0),
                      COALESCE(SUM(CASE WHEN terminal=1 THEN 1 ELSE 0 END),0),
                      COALESCE(SUM(CASE WHEN retryable=1 THEN 1 ELSE 0 END),0),
                      COALESCE(SUM(CASE WHEN terminal>=0 THEN 1 ELSE 0 END),0),
                      COALESCE(SUM(CASE WHEN retryable>=0 THEN 1 ELSE 0 END),0),
                      COALESCE(SUM(receipt_count),0),
                      COALESCE(SUM(CASE WHEN receipt_count>0 THEN 1 ELSE 0 END),0),
                      COALESCE(MAX(receipt_count),0),
                      COALESCE(SUM(CASE WHEN success=0 THEN 1 ELSE 0 END),0)
               FROM events WHERE created_at>=?""",
            (cutoff,),
        ).fetchone()
        total = int(metrics[0] or 0)
        cache_hits = int(metrics[1] or 0)
        bypass_total = int(metrics[2] or 0)
        outcome = tuple(int(metrics[index] or 0) for index in range(3, 7))
        receipts = tuple(int(metrics[index] or 0) for index in range(7, 10))
        failures = int(metrics[10] or 0)
        truncated = any(len(rows) > limit for rows in (route_rows, cache_rows, bypass_rows))
        queue_ages = [float(row[0] or 0) for row in queue_rows]
        routes = [
            {"route": str(row[0]), "events": int(row[1]), "failures": int(row[2]), "avg_ms": round(float(row[3]), 1)}
            for row in route_rows[:limit]
        ]
        cache = [
            {
                "layer": str(row[0]), "events": int(row[1]), "hits": int(row[2]),
                "coalesced": int(row[3]), "hit_rate": round(int(row[2]) / int(row[1]), 4) if row[1] else 0.0,
            }
            for row in cache_rows[:limit]
        ]
        bypass = [{"reason": str(row[0]), **({"error_type": str(row[1])} if row[1] else {}), "events": int(row[2])} for row in bypass_rows[:limit]]
        return {
            "counts": {
                "events": total, "cache_hits": cache_hits, "bypasses": bypass_total,
                "terminal": int(outcome[0]), "retryable": int(outcome[1]), "receipts": int(receipts[0]),
                "cache_hit_count": cache_hits, "bypass_count": bypass_total,
                "terminal_count": int(outcome[0]), "retryable_count": int(outcome[1]),
                "receipt_count": int(receipts[0]),
            },
            "routes": routes,
            "cache": cache,
            "bypass": bypass,
            "queue": {
                "events": len(queue_ages),
                "avg_age_ms": round(sum(queue_ages) / len(queue_ages), 1) if queue_ages else 0.0,
                "p95_age_ms": _percentile(queue_ages, 0.95),
                "max_age_ms": round(max(queue_ages), 1) if queue_ages else 0.0,
                "avg_queue_age_ms": round(sum(queue_ages) / len(queue_ages), 1) if queue_ages else 0.0,
                "p95_queue_age_ms": _percentile(queue_ages, 0.95),
                "max_queue_age_ms": round(max(queue_ages), 1) if queue_ages else 0.0,
            },
            "outcomes": {
                "terminal": int(outcome[0]), "retryable": int(outcome[1]),
                "terminal_known": int(outcome[2]), "retryable_known": int(outcome[3]),
            },
            "receipts": {
                "events": int(receipts[1]), "total": int(receipts[0]), "max_per_event": int(receipts[2]),
            },
            "errors": {"failures": failures},
            "_truncated": truncated,
        }

    @staticmethod
    def _detail_status(
        *, truncated: bool, flush_complete: bool, writer: dict[str, Any],
        summary_cache_stale: bool = False,
    ) -> dict[str, Any]:
        incomplete = bool(
            truncated or not flush_complete or writer.get("pending")
            or writer.get("dropped") or writer.get("writer_errors")
            or not writer.get("activity_observed", False)
            or writer.get("accounting_balanced") is False
            or summary_cache_stale
        )
        omitted: list[str] = []
        if truncated:
            omitted.append("decision_grade_lists")
        if not flush_complete or writer.get("pending"):
            omitted.append("pending_events")
        if writer.get("dropped") or writer.get("writer_errors"):
            omitted.append("writer_failures")
        if not writer.get("activity_observed", False):
            omitted.append("writer_activity_unobserved")
        if writer.get("accounting_balanced") is False:
            omitted.append("writer_accounting_unbalanced")
        if summary_cache_stale:
            omitted.append("cached_summary_data")
        return {
            "status": "incomplete" if incomplete else "complete",
            "truncated": bool(truncated),
            "incomplete": incomplete,
            "omitted_sections": omitted,
            "list_limit": _DECISION_DETAIL_LIMIT,
        }

    def summary(self, days: int = 30, *, scope: str = "window", _flush: bool = True, session_limit: int = 10, detailed_diagnostics: bool | None = None) -> dict[str, Any]:
        if not self.enabled:
            return {"enabled": False}
        if getattr(self, "mode", "full") == "minimal":
            with self._stats_lock:
                return {
                    "enabled": True,
                    "mode": "minimal",
                    "events": self._minimal_stats["requests_total"],
                    "requests_total": self._minimal_stats["requests_total"],
                    "errors_total": self._minimal_stats["errors_total"],
                    "input_tokens": self._minimal_stats["input_tokens_total"],
                    "output_tokens": self._minimal_stats["output_tokens_total"],
                    "total_tokens": self._minimal_stats["tokens_total"],
                    "uptime_seconds": round(time.time() - self._minimal_stats["start_time"], 2),
                }
        now = time.monotonic()
        bounded_days = max(1, min(int(days), _MAX_QUERY_WINDOW_DAYS))
        cutoff, scope = self._scope_cutoff(bounded_days, scope)
        detailed = detailed_diagnostics
        if detailed is None:
            try:
                from .agent_diagnostics import detailed_diagnostics_enabled
                detailed = detailed_diagnostics_enabled(getattr(self, "config", {}))
            except Exception:
                detailed = False
        # Keep the established rolling-window cache key stable for lightweight
        # callers; process cohorts need the start boundary in their own key.
        key: Any = (bounded_days, bool(detailed)) if scope == "window" else (bounded_days, scope, int(self.process_started_at), bool(detailed))
        with self._summary_cache_lock:
            cached = self._summary_cache.get(key)
        if cached and now - cached["time"] < 3.0:
            return self._refresh_cached_writer_status(
                cached["data"], cached.get("writer_snapshot", {})
            )
        flush_complete = True
        if _flush:
            flush_complete = self.flush(0.5)
        accounting_boundary_incomplete = False
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
            provider_cache_read_tokens = con.execute(
                "SELECT COALESCE(SUM(cache_read_tokens),0) FROM events WHERE created_at>=? AND event_type='inference'",
                (cutoff,),
            ).fetchone()[0]
            wait_metrics = con.execute(
                "SELECT COALESCE(SUM(wait_count),0), COALESCE(SUM(wait_duration_ms),0) FROM events WHERE created_at>=? AND wait_count>0",
                (cutoff,),
            ).fetchone()
            by_action = con.execute(
                """SELECT action,COUNT(*),COALESCE(SUM(avoided_cloud_tokens),0),COALESCE(AVG(duration_ms),0)
                   FROM events WHERE created_at>=? AND event_type='inference' GROUP BY action ORDER BY COUNT(*) DESC LIMIT 20""",
                (cutoff,),
            ).fetchall()
            by_cache = con.execute(
                """SELECT CASE WHEN cache_layer='' THEN 'uncategorized' ELSE cache_layer END,COUNT(*)
                   FROM events WHERE created_at>=? AND event_type='inference' GROUP BY cache_layer ORDER BY COUNT(*) DESC, cache_layer LIMIT ?""",
                (cutoff, _REPORT_GROUP_LIMIT),
            ).fetchall()
            cache_domains_rows = con.execute(
                """SELECT CASE
                           WHEN event_type='inference' THEN 'generation'
                           WHEN action='/api/command' THEN 'command'
                           WHEN cache_layer IN ('workspace','workspace-miss') THEN 'repository'
                           ELSE 'other'
                       END AS domain,
                       COUNT(*),COALESCE(SUM(cache_hit),0),COALESCE(SUM(coalesced),0),
                       COALESCE(SUM(CASE WHEN event_type='inference' AND cache_layer='semantic' AND cache_hit=1 THEN 1 ELSE 0 END),0)
                   FROM events WHERE created_at>=? AND event_type IN ('inference','http')
                   GROUP BY domain ORDER BY domain""",
                (cutoff,),
            ).fetchall()
            cache_decision_rows = con.execute(
                """SELECT error_type,COUNT(*) FROM events
                   WHERE created_at>=? AND event_type='stage' AND stage='cache_decision'
                   GROUP BY error_type ORDER BY COUNT(*) DESC, error_type LIMIT ?""",
                (cutoff, _REPORT_GROUP_LIMIT),
            ).fetchall()
            http_outcome_rows = con.execute(
                """SELECT CASE WHEN error_type='' THEN 'success' ELSE error_type END,
                          COUNT(*),COALESCE(SUM(CASE WHEN success=0 THEN 1 ELSE 0 END),0)
                   FROM events WHERE created_at>=? AND event_type='http'
                   GROUP BY error_type ORDER BY COUNT(*) DESC, error_type LIMIT ?""",
                (cutoff, _REPORT_GROUP_LIMIT),
            ).fetchall()
            durations = [float(r[0]) for r in con.execute(
                "SELECT duration_ms FROM events WHERE created_at>=? AND event_type='inference' ORDER BY id DESC LIMIT 10000", (cutoff,)
            )]
            cohort_rows = con.execute(
                """SELECT event_type,error_type,duration_ms,success,retry_count,fallback_used,degraded
                   FROM events WHERE created_at>=? AND event_type IN ('inference','http')""",
                (cutoff,),
            )
            cohorts = self._cohort_summary(cohort_rows)
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
                          COALESCE(SUM(CASE WHEN action='/api/command' THEN 1 ELSE 0 END),0),
                          COALESCE(SUM(CASE WHEN action LIKE '/api/repo/%' OR action='/api/solve/repo' THEN 1 ELSE 0 END),0)
                   FROM events WHERE created_at>=? AND event_type='http'
                     AND action LIKE '/api/%'
                     AND action NOT IN ('/api/live','/api/live/status','/api/status')""",
                (cutoff,),
            ).fetchone()
            prep_query = con.execute(
                """SELECT
                       COALESCE(SUM(CASE WHEN action LIKE '/api/repo/%' OR action='/api/search' OR action='/api/solve/repo' THEN 1 ELSE 0 END),0),
                       COALESCE(SUM(CASE WHEN (action LIKE '/api/repo/%' OR action='/api/search' OR action='/api/solve/repo') AND preprocessed_hit=1 THEN 1 ELSE 0 END),0)
                   FROM events WHERE created_at>=? AND event_type='http'""",
                (cutoff,),
            ).fetchone()
            # Channel counters are row-level evidence. Aggregate equality can hide
            # legacy rows when another row has overlapping input/output counters.
            unpriced_row = (
                "NOT (gross_avoided_cloud_tokens = gross_input_tokens_avoided + gross_output_tokens_avoided "
                "OR (gross_input_tokens_avoided > 0 AND gross_avoided_cloud_tokens = gross_input_tokens_avoided) "
                "OR (gross_input_tokens_avoided = 0 AND gross_avoided_cloud_tokens = gross_output_tokens_avoided)) "
                "OR net_cloud_token_delta <> gross_avoided_cloud_tokens - tool_request_tokens - tool_response_tokens"
            )
            if scope == "window":
                # Raw retention is shorter than the reporting window. Use daily
                # totals once per complete UTC day, and raw rows only for the
                # partial first day. This preserves the exact rolling cutoff
                # without counting retained rows a second time.
                columns = (
                    "gross_avoided_cloud_tokens", "gross_input_tokens_avoided", "gross_output_tokens_avoided",
                    "agent_protocol_tokens", "tool_request_tokens", "tool_response_tokens", "tool_schema_tokens",
                    "local_compute_tokens_avoided", "net_cloud_token_delta", "cloud_token_overhead",
                    "net_after_schema_token_delta", "schema_adjusted_overhead",
                )
                boundary = datetime.fromtimestamp(cutoff, tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
                boundary_end = (boundary + timedelta(days=1)).timestamp()
                day = boundary.strftime("%Y-%m-%d")
                fields = ",".join(columns)
                sums = ",".join(f"COALESCE(SUM({column}),0)" for column in ("events", *columns))
                tool_accounting = con.execute(
                    f"SELECT {sums} FROM ("
                    f"SELECT events,{fields} FROM daily_rollups WHERE day>? AND event_type='tool_accounting' "
                    f"UNION ALL SELECT 1 AS events,{fields} FROM events "
                    "WHERE created_at>=? AND created_at<? AND event_type='tool_accounting')",
                    (day, cutoff, boundary_end),
                ).fetchone()
                boundary_rollup = con.execute(
                    "SELECT COALESCE(SUM(events),0) FROM daily_rollups WHERE day=? AND event_type='tool_accounting'", (day,)
                ).fetchone()[0]
                boundary_raw = con.execute(
                    "SELECT COUNT(*) FROM events WHERE created_at>=? AND created_at<? AND event_type='tool_accounting'",
                    (boundary.timestamp(), boundary_end),
                ).fetchone()[0]
                accounting_boundary_incomplete = boundary_rollup > boundary_raw
                pricing_table = (
                    "(SELECT events, gross_avoided_cloud_tokens, gross_input_tokens_avoided, gross_output_tokens_avoided, "
                    "tool_request_tokens, tool_response_tokens, net_cloud_token_delta FROM daily_rollups "
                    "WHERE day>? AND event_type='tool_accounting' "
                    "UNION ALL SELECT 1 AS events, gross_avoided_cloud_tokens, gross_input_tokens_avoided, gross_output_tokens_avoided, "
                    "tool_request_tokens, tool_response_tokens, net_cloud_token_delta FROM events "
                    "WHERE created_at>=? AND created_at<? AND event_type='tool_accounting')"
                )
                pricing_table_params = (day, cutoff, boundary_end)
                pricing_rollup_rows = int(con.execute(
                    f"""SELECT COUNT(*) FROM daily_rollups WHERE day>? AND event_type='tool_accounting'
                       AND events>0 AND (gross_avoided_cloud_tokens<>0 OR gross_input_tokens_avoided<>0
                           OR gross_output_tokens_avoided<>0 OR tool_request_tokens<>0
                           OR tool_response_tokens<>0 OR net_cloud_token_delta<>0)
                       AND ({unpriced_row})""",
                    (day,),
                ).fetchone()[0])
                unpriced_event_rows = int(con.execute(
                    f"SELECT COUNT(*) FROM events WHERE created_at>=? AND created_at<? AND event_type='tool_accounting' AND ({unpriced_row})",
                    (cutoff, boundary_end),
                ).fetchone()[0])
                cat_rows = con.execute(
                    """SELECT
                           CASE
                               WHEN action IN ('local_ai_repo', 'local_ai_artifact', 'local_ai_rag') THEN 'discovery'
                               WHEN action IN ('local_ai_coord') THEN 'agent_os'
                               WHEN action IN ('local_ai_task', 'local_ai_work') THEN 'local_inference'
                               ELSE 'system'
                           END AS category,
                           COALESCE(SUM(events),0),
                           COALESCE(SUM(agent_protocol_tokens),0),
                           COALESCE(SUM(gross_avoided_cloud_tokens),0),
                           COALESCE(SUM(net_cloud_token_delta),0)
                       FROM (
                           SELECT action, events, agent_protocol_tokens, gross_avoided_cloud_tokens, net_cloud_token_delta
                           FROM daily_rollups WHERE day>? AND event_type='tool_accounting'
                           UNION ALL
                           SELECT action, 1 AS events, agent_protocol_tokens, gross_avoided_cloud_tokens, net_cloud_token_delta
                           FROM events WHERE created_at>=? AND created_at<? AND event_type='tool_accounting'
                       ) GROUP BY 1""",
                    (day, cutoff, boundary_end),
                ).fetchall()
            else:
                tool_accounting = con.execute(
                    """SELECT COUNT(*), COALESCE(SUM(gross_avoided_cloud_tokens),0),
                              COALESCE(SUM(gross_input_tokens_avoided),0), COALESCE(SUM(gross_output_tokens_avoided),0),
                              COALESCE(SUM(agent_protocol_tokens),0), COALESCE(SUM(tool_request_tokens),0),
                              COALESCE(SUM(tool_response_tokens),0), COALESCE(SUM(tool_schema_tokens),0),
                              COALESCE(SUM(local_compute_tokens_avoided),0), COALESCE(SUM(net_cloud_token_delta),0),
                              COALESCE(SUM(cloud_token_overhead),0), COALESCE(SUM(net_after_schema_token_delta),0),
                              COALESCE(SUM(schema_adjusted_overhead),0)
                       FROM events WHERE created_at>=? AND event_type='tool_accounting'""",
                    (cutoff,),
                ).fetchone()
                pricing_table = (
                    "(SELECT 1 AS events, gross_avoided_cloud_tokens, gross_input_tokens_avoided, gross_output_tokens_avoided, "
                    "tool_request_tokens, tool_response_tokens, net_cloud_token_delta FROM events "
                    "WHERE created_at>=? AND event_type='tool_accounting')"
                )
                pricing_table_params = (cutoff,)
                pricing_rollup_rows = 0
                unpriced_event_rows = int(con.execute(
                    f"SELECT COUNT(*) FROM events WHERE created_at>=? AND event_type='tool_accounting' AND ({unpriced_row})",
                    (cutoff,),
                ).fetchone()[0])
                cat_rows = con.execute(
                    """SELECT
                           CASE
                               WHEN action IN ('local_ai_repo', 'local_ai_artifact', 'local_ai_rag') THEN 'discovery'
                               WHEN action IN ('local_ai_coord') THEN 'agent_os'
                               WHEN action IN ('local_ai_task', 'local_ai_work') THEN 'local_inference'
                               ELSE 'system'
                           END AS category,
                           COUNT(*),
                           COALESCE(SUM(agent_protocol_tokens),0),
                           COALESCE(SUM(gross_avoided_cloud_tokens),0),
                           COALESCE(SUM(net_cloud_token_delta),0)
                       FROM events
                       WHERE created_at>=? AND event_type='tool_accounting'
                       GROUP BY 1""",
                    (cutoff,),
                ).fetchall()
            known_channel_rows = con.execute(
                f"""SELECT COALESCE(SUM(events),0),
                           COALESCE(SUM(CASE
                               WHEN gross_avoided_cloud_tokens = gross_input_tokens_avoided + gross_output_tokens_avoided
                                   THEN gross_input_tokens_avoided
                               WHEN gross_input_tokens_avoided > 0 THEN gross_input_tokens_avoided
                               ELSE 0 END),0),
                           COALESCE(SUM(CASE
                               WHEN gross_avoided_cloud_tokens = gross_input_tokens_avoided + gross_output_tokens_avoided
                                   THEN gross_output_tokens_avoided
                               WHEN gross_input_tokens_avoided = 0 THEN gross_output_tokens_avoided
                               ELSE 0 END),0),
                           COALESCE(SUM(tool_request_tokens),0), COALESCE(SUM(tool_response_tokens),0)
                    FROM {pricing_table} WHERE NOT ({unpriced_row})""",
                pricing_table_params,
            ).fetchone()
            pricing_incomplete = bool(
                pricing_rollup_rows or unpriced_event_rows or accounting_boundary_incomplete
            )
            # Realtime summaries must stay cheap even at max raw-event retention.
            # Attribute each call to its dominant savings source in SQL; the full
            # multi-source breakdown is parsed only by the explicit diagnostic report.
            tool_breakdown_rows = con.execute(
                """SELECT source,COALESCE(SUM(tokens),0) FROM (
                       SELECT input_savings_source AS source,gross_input_tokens_avoided AS tokens
                         FROM events WHERE created_at>=? AND event_type='tool_accounting' AND input_savings_source<>''
                       UNION ALL
                       SELECT output_savings_source AS source,gross_output_tokens_avoided AS tokens
                         FROM events WHERE created_at>=? AND event_type='tool_accounting' AND output_savings_source<>''
                   ) GROUP BY source ORDER BY 2 DESC, source LIMIT ?""",
                (cutoff, cutoff, _REPORT_GROUP_LIMIT),
            ).fetchall()
            if scope == "process":
                session_count_raw = con.execute(
                    "SELECT COUNT(DISTINCT trace_id) FROM events WHERE created_at>=? AND trace_id<>''",
                    (cutoff,),
                ).fetchone()[0]
            else:
                session_count_raw = con.execute(
                    "SELECT COUNT(*) FROM process_sessions WHERE started_at>=?",
                    (cutoff,),
                ).fetchone()[0]
            decision_grade = self._decision_grade(con, cutoff)
        total = int(row[0]); cached = int(row[1]); http_total = int(http[0])
        cache_domains: dict[str, dict[str, Any]] = {}
        semantic_hits = 0
        for domain, events, hits, coalesced, semantic in cache_domains_rows:
            count = int(events)
            semantic_hits += int(semantic)
            cache_domains[str(domain)] = {
                "events": count,
                "hits": int(hits),
                "coalesced": int(coalesced),
                "hit_rate": round(int(hits) / count, 4) if count else 0.0,
            }
        cache_decisions = {str(reason): int(count) for reason, count in cache_decision_rows}
        http_outcomes = {
            str(category): {"events": int(events), "failures": int(failures)}
            for category, events, failures in http_outcome_rows
        }
        tool_accounting_events = int(tool_accounting[0])
        gross_avoided_cloud_tokens = int(tool_accounting[1])
        gross_input_tokens_avoided = int(tool_accounting[2])
        gross_output_tokens_avoided = int(tool_accounting[3])
        agent_protocol_tokens = int(tool_accounting[4])
        tool_request_tokens = int(tool_accounting[5])
        tool_response_tokens = int(tool_accounting[6])
        tool_schema_tokens = int(tool_accounting[7])
        local_compute_tokens_avoided = int(tool_accounting[8])
        net_cloud_token_delta = int(tool_accounting[9])
        cloud_token_overhead = int(tool_accounting[10])
        net_after_schema_token_delta = int(tool_accounting[11])
        schema_adjusted_overhead = int(tool_accounting[12])
        savings_breakdown = {str(source)[:64]: max(0, int(tokens or 0)) for source, tokens in tool_breakdown_rows}
        priced_events = int(known_channel_rows[0])
        estimated_gross_input_tokens = int(known_channel_rows[1])
        estimated_gross_output_tokens = int(known_channel_rows[2])
        priced_tool_request_tokens = int(known_channel_rows[3])
        priced_tool_response_tokens = int(known_channel_rows[4])
        if priced_events and (estimated_gross_input_tokens or estimated_gross_output_tokens):
            # Tool responses are cloud input; tool calls are cloud output. Keep
            # the token delta signed, but price each side with its own rate. SQL
            # selects overlapping channels per row before summing contributions.
            net_input_tokens = estimated_gross_input_tokens - priced_tool_response_tokens
            net_output_tokens = estimated_gross_output_tokens - priced_tool_request_tokens
            estimated_input_savings_usd = round(
                net_input_tokens * self.cloud_input_token_cost_usd_per_million / 1_000_000, 4
            )
            estimated_output_savings_usd = round(
                net_output_tokens * self.cloud_output_token_cost_usd_per_million / 1_000_000, 4
            )
            if pricing_incomplete:
                # Legacy rows without channel counters remain in accounting totals,
                # but their USD cost cannot be reconstructed from channel rates.
                estimated_savings_usd = None
                pricing_mode = "incomplete"
            else:
                estimated_savings_usd = round(estimated_input_savings_usd + estimated_output_savings_usd, 4)
                pricing_mode = "input_output"
        elif pricing_incomplete and not priced_events:
            # Older rows may retain gross and signed token accounting without
            # either channel counter. Never price those rows with a blended rate.
            estimated_input_savings_usd = None
            estimated_output_savings_usd = None
            estimated_savings_usd = None
            pricing_mode = "incomplete"
        else:
            estimated_input_savings_usd = round(
                -priced_tool_response_tokens * self.cloud_input_token_cost_usd_per_million / 1_000_000, 4
            )
            estimated_output_savings_usd = round(
                -priced_tool_request_tokens * self.cloud_output_token_cost_usd_per_million / 1_000_000, 4
            )
            if pricing_incomplete:
                estimated_savings_usd = None
                pricing_mode = "incomplete"
            else:
                estimated_savings_usd = round(estimated_input_savings_usd + estimated_output_savings_usd, 4)
                pricing_mode = "input_output"

        call_categories = {
            "discovery": {"events": 0, "protocol_tokens": 0, "gross_avoided": 0, "net_delta": 0},
            "agent_os": {"events": 0, "protocol_tokens": 0, "gross_avoided": 0, "net_delta": 0},
            "local_inference": {"events": 0, "protocol_tokens": 0, "gross_avoided": 0, "net_delta": 0},
            "system": {"events": 0, "protocol_tokens": 0, "gross_avoided": 0, "net_delta": 0},
        }
        for cat_name, cat_events, cat_proto, cat_avoided, cat_net in cat_rows:
            if cat_name in call_categories:
                call_categories[cat_name] = {
                    "events": int(cat_events or 0),
                    "protocol_tokens": int(cat_proto or 0),
                    "gross_avoided": int(cat_avoided or 0),
                    "net_delta": int(cat_net or 0),
                }
        discovery_events = call_categories["discovery"]["events"]

        session_count = max(1, int(session_count_raw or 0))
        calls_per_session = max(1, round(tool_accounting_events / session_count)) if tool_accounting_events else 1
        dynamic_depth_tokens = int(min(128_000, max(6_000, 6_000 + (calls_per_session * 1_800))))

        avoided_turns = discovery_events
        avoided_turn_output_tokens = avoided_turns * 250
        avoided_cache_read_tokens = avoided_turns * dynamic_depth_tokens
        avoided_slice_tokens = avoided_turns * 600

        realistic_gross_tokens = gross_avoided_cloud_tokens + (avoided_turn_output_tokens + avoided_slice_tokens)
        realistic_net_cloud_token_delta = realistic_gross_tokens - agent_protocol_tokens

        sonnet_output_rate = max(self.cloud_output_token_cost_usd_per_million, 12.50)

        realistic_output_savings_usd = round(
            (gross_output_tokens_avoided + avoided_turn_output_tokens - priced_tool_request_tokens)
            * sonnet_output_rate / 1_000_000, 4
        )
        realistic_cache_read_savings_usd = round(
            avoided_cache_read_tokens * self.cloud_cache_read_token_cost_usd_per_million / 1_000_000, 4
        )
        realistic_input_savings_usd = round(
            (gross_input_tokens_avoided + avoided_slice_tokens - priced_tool_response_tokens)
            * self.cloud_input_token_cost_usd_per_million / 1_000_000, 4
        )

        if pricing_incomplete:
            realistic_savings_usd = None
        else:
            realistic_savings_usd = round(
                realistic_output_savings_usd + realistic_cache_read_savings_usd + realistic_input_savings_usd, 4
            )

        detailed = detailed_diagnostics
        if detailed is None:
            try:
                from .agent_diagnostics import detailed_diagnostics_enabled
                detailed = detailed_diagnostics_enabled(getattr(self, "config", {}))
            except Exception:
                detailed = False

        prep_events = int(prep_query[0] or 0)
        prep_hits = int(prep_query[1] or 0)
        prep_hit_rate = round(prep_hits / prep_events, 4) if prep_events else 0.0
        writer = self._writer_snapshot()
        decision_grade["detail"] = self._detail_status(
            truncated=bool(decision_grade.pop("_truncated", False)),
            flush_complete=flush_complete,
            writer=writer,
        )
        res = {
            "enabled": True, "window_days": max(1, int(days)), "scope": scope,
            "process_started_at": self.process_started_at if scope == "process" else None, "events": total,
            "cache_hits": cached, "cache_hit_rate": round(cached / total, 4) if total else 0.0,
            "generation_cache_hits": cached,
            "generation_cache_hit_rate": round(cached / total, 4) if total else 0.0,
            "preprocessed_query_hits": prep_hits,
            "preprocessed_query_events": prep_events,
            "preprocessed_query_hit_rate": prep_hit_rate,
            "sessions": self.sessions(days=int(days), limit=max(1, min(int(session_limit), 20))),
            "cache_domains": cache_domains,
            "cache_decisions": cache_decisions,
            "cache_reuse_breakdown": {
                "semantic_hits": semantic_hits,
                "single_flight_waiters": cache_domains.get("generation", {}).get("coalesced", 0),
            },
            "http_outcomes": http_outcomes,
            "coalesced_waiters": int(row[2]), "local_input_tokens_est": int(row[3]),
            "provider_cache_read_tokens": int(provider_cache_read_tokens),
            "local_output_tokens_est": int(row[4]),
            "context_tokens_avoided_est": int(row[5]),
            "net_cloud_token_delta_est": net_cloud_token_delta,
            "realistic_net_cloud_token_delta_est": realistic_net_cloud_token_delta,
            "cloud_token_overhead_est": cloud_token_overhead,
            "gross_cloud_tokens_avoided_est": gross_avoided_cloud_tokens,
            "gross_input_cloud_tokens_avoided_est": gross_input_tokens_avoided,
            "gross_output_cloud_tokens_avoided_est": gross_output_tokens_avoided,
            "agent_protocol_tokens_est": agent_protocol_tokens,
            "agent_tool_request_tokens_est": tool_request_tokens,
            "agent_tool_response_tokens_est": tool_response_tokens,
            "tool_schema_tokens_exposure_est": tool_schema_tokens,
            "net_after_schema_token_delta_est": net_after_schema_token_delta,
            "schema_adjusted_overhead_est": schema_adjusted_overhead,
            "local_compute_tokens_avoided_est": local_compute_tokens_avoided,
            "token_savings_breakdown": dict(sorted(savings_breakdown.items(), key=lambda kv: (-kv[1], kv[0]))),
            "tool_accounting_events": tool_accounting_events,
            "accounting_boundary_incomplete": accounting_boundary_incomplete,
            "token_accounting_storage": "daily_rollups_and_boundary_events" if scope == "window" else "retained_process_events",
            "cloud_input_token_cost_usd_per_million": self.cloud_input_token_cost_usd_per_million,
            "cloud_output_token_cost_usd_per_million": self.cloud_output_token_cost_usd_per_million,
            "cloud_cache_read_token_cost_usd_per_million": self.cloud_cache_read_token_cost_usd_per_million,
            "cloud_cache_write_token_cost_usd_per_million": self.cloud_cache_write_token_cost_usd_per_million,
            "dynamic_depth_tokens": dynamic_depth_tokens,
            "call_categories": call_categories,
            "active_pricing_profile": self.pricing_profile,
            "pricing_profiles": services_module.CLOUD_PRICING_PROFILES,

            "estimated_input_savings_usd": estimated_input_savings_usd,
            "estimated_output_savings_usd": estimated_output_savings_usd,
            "estimated_savings_pricing_mode": pricing_mode,
            "estimated_savings_usd": estimated_savings_usd,
            "realistic_savings_usd": realistic_savings_usd,
            "avg_duration_ms": round(float(row[6]), 1), "p50_duration_ms": _percentile(durations, 0.50),
            "p95_duration_ms": _percentile(durations, 0.95), "p99_duration_ms": _percentile(durations, 0.99),
            "aggregate_duration_scope": "inference_only", "cohorts": cohorts,
            "failures": int(row[7]), "failure_rate": round(int(row[7]) / total, 4) if total else 0.0,
            "avg_model_load_duration_ms": round(float(row[8]), 1), "avg_queue_wait_ms": round(float(row[9]), 1),
            "wait_count": int(wait_metrics[0]), "wait_duration_ms": round(float(wait_metrics[1]), 1),
            "fallback_count": int(row[10]), "degraded_count": int(row[11]), "retry_count": int(row[12]),
            "ollama_inference_calls": int(dict(by_cache).get("ollama", 0)),
            "ollama_calls_avoided_est": max(0, total - int(dict(by_cache).get("ollama", 0))),
            "cache_layers": {str(r[0]): int(r[1]) for r in by_cache},
            "by_action": [
                {"action": r[0], "calls": int(r[1]), "context_tokens_avoided_est": int(r[2]), "avg_ms": round(float(r[3]), 1)}
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
            "window": {"days": max(1, int(days)), "scope": scope,
                       "events": decision_grade["counts"]["events"], "inference_events": total},
            "counts": decision_grade["counts"],
            "routes": decision_grade["routes"],
            "cache": decision_grade["cache"],
            "bypass": decision_grade["bypass"],
            "errors": decision_grade["errors"],
            "queue": decision_grade["queue"],
            "detail": decision_grade["detail"],
            "decision_grade": decision_grade,
            "summary_cache_stale": False,
        }
        if detailed:
            res["realistic_savings_breakdown"] = {
                "avoided_turns": avoided_turns,
                "avoided_agent_output_tokens": avoided_turn_output_tokens,
                "avoided_cache_read_tokens": avoided_cache_read_tokens,
                "avoided_slice_tokens": avoided_slice_tokens,
                "dynamic_depth_tokens": dynamic_depth_tokens,
                "calls_per_session_est": calls_per_session,
                "sonnet_output_rate": sonnet_output_rate,
                "cache_read_rate": self.cloud_cache_read_token_cost_usd_per_million,
                "input_rate": self.cloud_input_token_cost_usd_per_million,
                "realistic_output_savings_usd": realistic_output_savings_usd,
                "realistic_cache_read_savings_usd": realistic_cache_read_savings_usd,
                "realistic_input_savings_usd": realistic_input_savings_usd,
            }
        with self._summary_cache_lock:
            self._summary_cache[key] = {"time": now, "data": res, "writer_snapshot": dict(writer)}
            while len(self._summary_cache) > _SUMMARY_CACHE_LIMIT:
                oldest_key = min(self._summary_cache, key=lambda item: self._summary_cache[item]["time"])
                self._summary_cache.pop(oldest_key, None)
        return res

    def report(
        self, days: int = 30, *, recent_errors: int = 25, _error_offset: int = 0,
        error_cursor: str | None = None, scope: str = "window", _flush: bool = True,
    ) -> dict[str, Any]:
        """Produce a prompt/source-free diagnostic report suitable for sharing."""
        if not self.enabled:
            return {"enabled": False}
        flush_complete = True
        if _flush:
            flush_complete = self.flush(1.0)
        days = max(1, min(int(days), self.rollup_retention_days))
        cutoff, scope = self._scope_cutoff(days, scope)
        error_limit = max(1, min(int(recent_errors), 100))
        error_offset = max(0, min(int(_error_offset), 100_000))
        cursor_requested = error_cursor is not None
        cursor_values = _decode_error_page_cursor(error_cursor)
        if cursor_requested and error_offset:
            raise ValueError("internal offset cannot be combined with error_cursor")
        with closing(self._connect()) as con:
            by_agent = con.execute(
                """SELECT CASE WHEN agent='' THEN 'unknown' ELSE agent END,
                          COALESCE(SUM(CASE WHEN event_type='http' THEN 1 ELSE 0 END),0),
                          COALESCE(AVG(CASE WHEN event_type='http' THEN duration_ms END),0),
                          COALESCE(SUM(CASE WHEN event_type='http' AND success=0 THEN 1 ELSE 0 END),0),
                          COALESCE(SUM(CASE WHEN event_type='inference' THEN avoided_cloud_tokens ELSE 0 END),0),
                          COALESCE(SUM(CASE WHEN event_type='inference' THEN 1 ELSE 0 END),0),
                          COALESCE(SUM(CASE WHEN event_type='tool_accounting' THEN net_cloud_token_delta ELSE 0 END),0),
                          COALESCE(SUM(CASE WHEN event_type='tool_accounting' THEN gross_avoided_cloud_tokens ELSE 0 END),0),
                          COALESCE(SUM(CASE WHEN event_type='tool_accounting' THEN agent_protocol_tokens ELSE 0 END),0),
                          COALESCE(SUM(CASE WHEN event_type='tool_accounting' THEN 1 ELSE 0 END),0)
                   FROM events WHERE created_at>=? GROUP BY agent ORDER BY COUNT(*) DESC, agent LIMIT ?""",
                (cutoff, _REPORT_GROUP_LIMIT),
            ).fetchall()
            by_model = con.execute(
                """SELECT model,COUNT(*),COALESCE(AVG(duration_ms),0),COALESCE(AVG(load_duration_ms),0),COALESCE(SUM(CASE WHEN success=0 THEN 1 ELSE 0 END),0)
                   FROM events WHERE created_at>=? AND event_type='inference' AND model<>'' GROUP BY model ORDER BY COUNT(*) DESC, model LIMIT ?""",
                (cutoff, _REPORT_GROUP_LIMIT),
            ).fetchall()
            provider_usage = con.execute(
                """SELECT action,task_type,model,COALESCE(SUM(input_tokens),0),
                          COALESCE(SUM(cache_read_tokens),0),COALESCE(SUM(output_tokens),0)
                   FROM events WHERE created_at>=? AND event_type='inference'
                   GROUP BY action,task_type,model ORDER BY COUNT(*) DESC,action,task_type,model LIMIT 50""",
                (cutoff,),
            ).fetchall()
            actions = con.execute(
                """SELECT action,event_type,COUNT(*),COALESCE(AVG(duration_ms),0),COALESCE(AVG(queue_wait_ms),0),
                          COALESCE(SUM(CASE WHEN success=0 THEN 1 ELSE 0 END),0),COALESCE(SUM(cache_hit),0),
                          COALESCE(SUM(fallback_used),0),COALESCE(SUM(retry_count),0)
                   FROM events WHERE created_at>=? GROUP BY action,event_type ORDER BY COUNT(*) DESC LIMIT 50""", (cutoff,)
            ).fetchall()
            laya_capture_stages = con.execute(
                """SELECT stage,COUNT(*),COALESCE(SUM(CASE WHEN success=0 THEN 1 ELSE 0 END),0)
                   FROM events WHERE created_at>=? AND event_type='stage' AND action='laya_capture'
                   GROUP BY stage ORDER BY stage LIMIT 10""",
                (cutoff,),
            ).fetchall()
            laya_capture_reasons = con.execute(
                """SELECT stage,COALESCE(NULLIF(bypass_reason,''),'unspecified'),COALESCE(error_type,''),COUNT(*),
                          COALESCE(SUM(CASE WHEN success=0 THEN 1 ELSE 0 END),0)
                   FROM events WHERE created_at>=? AND event_type='stage' AND action='laya_capture'
                   GROUP BY stage,COALESCE(NULLIF(bypass_reason,''),'unspecified'),COALESCE(error_type,'')
                   ORDER BY COUNT(*) DESC,stage,bypass_reason,error_type LIMIT 32""",
                (cutoff,),
            ).fetchall()
            routes = con.execute(
                """SELECT route,task_type,complexity,COUNT(*),COALESCE(AVG(duration_ms),0),COALESCE(SUM(CASE WHEN success=0 THEN 1 ELSE 0 END),0)
                   FROM events WHERE created_at>=? AND event_type='http' AND route<>''
                   GROUP BY route,task_type,complexity ORDER BY COUNT(*) DESC LIMIT 40""", (cutoff,)
            ).fetchall()
            error_select = """SELECT fingerprint,error_type,component,operation,COUNT(*),MAX(created_at),MAX(safe_message),SUM(retryable),SUM(recovered)
                              FROM errors WHERE created_at>=?"""
            if cursor_requested:
                if cursor_values is None:
                    error_snapshot_cutoff = cutoff
                    error_snapshot_id = int(con.execute(
                        "SELECT COALESCE(MAX(id),0) FROM errors WHERE created_at>=?", (error_snapshot_cutoff,),
                    ).fetchone()[0])
                    error_rows = con.execute(
                        error_select + " AND id<=? GROUP BY fingerprint,error_type,component,operation "
                        "ORDER BY fingerprint,error_type,component,operation LIMIT ?",
                        (error_snapshot_cutoff, error_snapshot_id, error_limit + 1),
                    ).fetchall()
                else:
                    error_snapshot_id, error_snapshot_cutoff, *group_cursor = cursor_values
                    error_rows = con.execute(
                        error_select + " AND id<=? AND (fingerprint,error_type,component,operation)>(?,?,?,?) "
                        "GROUP BY fingerprint,error_type,component,operation ORDER BY fingerprint,error_type,component,operation LIMIT ?",
                        (error_snapshot_cutoff, error_snapshot_id, *group_cursor, error_limit + 1),
                    ).fetchall()
                error_total = int(con.execute(
                    """SELECT COUNT(*) FROM (
                           SELECT 1 FROM errors WHERE created_at>=? AND id<=?
                           GROUP BY fingerprint,error_type,component,operation
                       )""",
                    (error_snapshot_cutoff, error_snapshot_id),
                ).fetchone()[0])
            else:
                error_rows = con.execute(
                    error_select + " GROUP BY fingerprint,error_type,component,operation "
                    "ORDER BY COUNT(*) DESC,MAX(created_at) DESC LIMIT ? OFFSET ?",
                    (cutoff, error_limit + 1, error_offset),
                ).fetchall()
                error_total = int(con.execute(
                    """SELECT COUNT(*) FROM (
                           SELECT 1 FROM errors WHERE created_at>=?
                           GROUP BY fingerprint,error_type,component,operation
                       )""",
                    (cutoff,),
                ).fetchone()[0])
            error_has_more = len(error_rows) > error_limit
            errors = error_rows[:error_limit]
            daily = con.execute(
                """SELECT day,event_type,SUM(events),SUM(duration_ms),SUM(queue_wait_ms),
                          SUM(cache_hits),SUM(fallback_count),SUM(degraded_count),SUM(CASE WHEN success=0 THEN events ELSE 0 END),
                          SUM(gross_avoided_cloud_tokens),SUM(gross_input_tokens_avoided),SUM(gross_output_tokens_avoided),
                          SUM(agent_protocol_tokens),SUM(tool_schema_tokens),SUM(local_compute_tokens_avoided),
                          SUM(tool_request_tokens),SUM(tool_response_tokens),SUM(net_cloud_token_delta),SUM(cloud_token_overhead),
                          SUM(net_after_schema_token_delta),SUM(schema_adjusted_overhead)
                   FROM daily_rollups WHERE day>=? AND event_type IN ('inference','tool_accounting')
                   GROUP BY day,event_type ORDER BY day,event_type""",
                (datetime.fromtimestamp(cutoff, tz=timezone.utc).strftime("%Y-%m-%d"),),
            ).fetchall()
            cache = con.execute(
                """SELECT CASE WHEN cache_layer='' THEN 'uncategorized' ELSE cache_layer END,COUNT(*),COALESCE(AVG(duration_ms),0),COALESCE(SUM(avoided_cloud_tokens),0)
                   FROM events WHERE created_at>=? AND event_type='inference' GROUP BY cache_layer ORDER BY COUNT(*) DESC, cache_layer LIMIT ?""", (cutoff, _REPORT_GROUP_LIMIT)
            ).fetchall()
            cache_decisions = con.execute(
                """SELECT error_type,COUNT(*) FROM events
                   WHERE created_at>=? AND event_type='stage' AND stage='cache_decision'
                   GROUP BY error_type ORDER BY COUNT(*) DESC, error_type LIMIT ?""",
                (cutoff, _REPORT_GROUP_LIMIT),
            ).fetchall()
            # Tail diagnostics are a recent distribution, not an accounting total.
            # Read one bounded sample once instead of scanning the same raw HTTP
            # population three times on every dashboard refresh.
            http_tail_sample = con.execute(
                """SELECT action, CASE WHEN cache_layer='' THEN 'uncategorized' ELSE cache_layer END,
                          CASE WHEN agent='' THEN 'unknown' ELSE agent END,
                          duration_ms, queue_wait_ms, service_ms, success
                   FROM events WHERE created_at>=? AND event_type='http'
                   ORDER BY id DESC LIMIT 10000""",
                (cutoff,),
            ).fetchall()
            http_tail_rows = [(r[0], r[3], r[4], r[5], r[6]) for r in http_tail_sample]
            http_cache_tail_rows = [(r[1], r[3], r[4], r[5], r[6]) for r in http_tail_sample]
            agent_tail_rows = [(r[2], r[3], r[4], r[5], r[6]) for r in http_tail_sample]
            snapshots = con.execute(
                "SELECT created_at,name,metrics_json FROM snapshots WHERE created_at>=? ORDER BY created_at DESC LIMIT 20", (cutoff,)
            ).fetchall()
            laya_snapshot_rows = (
                con.execute(
                    "SELECT metrics_json FROM snapshots WHERE created_at>=? AND name='laya_decision' "
                    "ORDER BY id DESC LIMIT 1001",
                    (cutoff,),
                ).fetchall()
            )
            laya_eligible_rows = (
                con.execute(
                    "SELECT metrics_json FROM snapshots WHERE created_at>=? AND name='laya_decision_eligible' "
                    "ORDER BY id DESC LIMIT 1001",
                    (cutoff,),
                ).fetchall()
            )
            evaluations = con.execute(
                "SELECT created_at,metrics_json FROM snapshots WHERE created_at>=? AND name='agent_evaluation' ORDER BY created_at",
                (cutoff,),
            ).fetchall()
        summary = self.summary(days, scope=scope, _flush=False)
        daily_selected: list[tuple[Any, ...]] = []
        daily_by_day: dict[str, list[tuple[Any, ...]]] = {}
        for row_daily in daily:
            daily_by_day.setdefault(str(row_daily[0]), []).append(row_daily)
        for day in sorted(daily_by_day):
            candidates = daily_by_day[day]
            selected = next((row_daily for row_daily in candidates if str(row_daily[1]) == "tool_accounting"), None)
            if selected is not None:
                daily_selected.append(selected)
        evaluation = self._evaluation_summary(evaluations)
        if scope == "process" and self._current_session_id is None:
            laya_decisions = {
                "available": False,
                "reason": "process_identity_not_recorded",
                "scope": scope,
            }
        else:
            laya_decisions = _laya_decision_report(
                laya_snapshot_rows, laya_eligible_rows, scope=scope,
            )
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
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "window_days": days,
            "scope": scope,
            "process_started_at": self.process_started_at if scope == "process" else None,
            "privacy": {
                "mode": "metadata_only", "payloads": "not_stored",
                "labels": "bounded and sanitized", "error_messages": "sanitized paths/tokens; max 500 chars",
            },
            "summary": summary,
            "token_efficiency": {
                key: summary.get(key, 0) for key in (
                    "gross_cloud_tokens_avoided_est", "gross_input_cloud_tokens_avoided_est",
                    "gross_output_cloud_tokens_avoided_est", "agent_protocol_tokens_est",
                    "agent_tool_request_tokens_est", "agent_tool_response_tokens_est",
                    "tool_schema_tokens_exposure_est", "net_cloud_token_delta_est",
                    "cloud_token_overhead_est", "net_after_schema_token_delta_est",
                    "schema_adjusted_overhead_est", "local_compute_tokens_avoided_est",
                    "token_savings_breakdown", "tool_accounting_events",
                )
            },
            "by_agent": [
                {
                    "agent": r[0], "requests": int(r[1]), "avg_ms": round(float(r[2]), 1), "failures": int(r[3]),
                    "net_cloud_token_delta_est": int(r[6]),
                    "gross_cloud_tokens_avoided_est": int(r[7]),
                    "agent_protocol_tokens_est": int(r[8]),
                    "local_inference_calls": int(r[5]), "tool_accounting_calls": int(r[9]),
                }
                for r in by_agent
            ],
            "by_model": [
                {"model": r[0], "calls": int(r[1]), "avg_ms": round(float(r[2]), 1), "avg_load_ms": round(float(r[3]), 1), "failures": int(r[4])}
                for r in by_model
            ],
            "provider_token_usage": [
                {"action": r[0], "task_type": r[1], "model": r[2], "input_tokens": int(r[3]),
                 "cache_read_tokens": int(r[4]), "output_tokens": int(r[5])}
                for r in provider_usage
            ],
            "by_operation": [
                {"action": r[0], "event_type": r[1], "calls": int(r[2]), "avg_ms": round(float(r[3]), 1), "avg_queue_wait_ms": round(float(r[4]), 1), "failures": int(r[5]), "cache_hits": int(r[6]), "fallbacks": int(r[7]), "retries": int(r[8])}
                for r in actions
            ],
            "laya_capture_stages": [
                {"stage": r[0], "calls": int(r[1]), "failures": int(r[2])}
                for r in laya_capture_stages
            ],
            "laya_capture_reasons": [
                {"stage": r[0], "reason": r[1], "error_type": r[2], "calls": int(r[3]), "failures": int(r[4])}
                for r in laya_capture_reasons
            ],
            "execution_routes": [
                {"route": r[0], "task_type": r[1], "complexity": r[2], "calls": int(r[3]), "avg_ms": round(float(r[4]), 1), "failures": int(r[5])}
                for r in routes
            ],
            "cache_layers": [
                {"layer": r[0], "calls": int(r[1]), "avg_ms": round(float(r[2]), 1),
                 "context_tokens_avoided_est": int(r[3])}
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
            "error_fingerprints_page": {
                "limit": error_limit,
                "total": error_total,
                **({
                    "cursor": error_cursor or "",
                    "snapshot_id": error_snapshot_id,
                    "snapshot_cutoff": error_snapshot_cutoff,
                    "has_more": error_has_more,
                    "next_cursor": _encode_error_page_cursor(
                        error_snapshot_id, error_snapshot_cutoff, errors[-1][:4]
                    )
                    if error_has_more and errors else None,
                } if cursor_requested else {
                    "offset": error_offset,
                    "next_offset": (
                        error_offset + len(errors) if error_offset + len(errors) < error_total else None
                    ),
                }),
            },
            "daily": [
                {
                    "day": r[0], "accounting": r[1], "events": int(r[2]),
                    "duration_ms": round(float(r[3]), 1), "queue_wait_ms": round(float(r[4]), 1),
                    "cache_hits": int(r[5]), "fallbacks": int(r[6]), "degraded": int(r[7]), "failures": int(r[8]),
                    "gross_cloud_tokens_avoided_est": int(r[9]),
                    "gross_input_cloud_tokens_avoided_est": int(r[10]), "gross_output_cloud_tokens_avoided_est": int(r[11]),
                    "agent_protocol_tokens_est": int(r[12]), "tool_schema_tokens_exposure_est": int(r[13]),
                    "local_compute_tokens_avoided_est": int(r[14]),
                    "agent_tool_request_tokens_est": int(r[15]), "agent_tool_response_tokens_est": int(r[16]),
                    "net_cloud_token_delta_est": int(r[17]), "cloud_token_overhead_est": int(r[18]),
                    "net_after_schema_token_delta_est": int(r[19]), "schema_adjusted_overhead_est": int(r[20]),
                }
                for r in daily_selected
            ],
            "runtime_snapshots": [
                {"created_at": float(r[0]), "name": r[1], "metrics": json.loads(r[2]) if r[2] else {}} for r in snapshots
            ],
            "laya_decisions": laya_decisions,
            "evaluation": evaluation,
            "hotspots": hotspots,
            "window": summary.get("window", {"days": days, "scope": scope}),
            "counts": summary.get("counts", {}),
            "routes": summary.get("routes", []),
            "cache": summary.get("cache", []),
            "bypass": summary.get("bypass", []),
            "errors": summary.get("errors", {}),
            "queue": summary.get("queue", {}),
            "summary_cache_stale": bool(summary.get("summary_cache_stale", False)),
            "detail": self._detail_status(
                truncated=bool(summary.get("detail", {}).get("truncated", False)),
                flush_complete=flush_complete,
                writer=summary.get("writer", {}),
                summary_cache_stale=bool(summary.get("summary_cache_stale", False)),
            ),
            "decision_grade": summary.get("decision_grade", {}),
        }
        return _bound_telemetry_report(report)
