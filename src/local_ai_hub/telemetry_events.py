from __future__ import annotations

from contextlib import closing
import json
import math
import os
from pathlib import Path
import queue
import re
import time
from typing import Any

from .json_utils import dumps as json_dumps
from .trace_context import current as current_trace_context
from .telemetry import (
    _LAYA_DECISION_FIELDS,
    _LAYA_DECISION_OPTIONS,
    _LAYA_DECISION_STATUSES,
    _LAYA_IDENTIFIER,
    _LAYA_REASON_CODES,
    _LIVE_OMIT_EMPTY,
    _SAFE_ERROR_CODE_MESSAGES,
    _SAFE_HTTP_ROUTE_LABELS,
    _bounded_number,
    _clean_savings_breakdown,
    _clean_savings_source,
    _error_fingerprint,
    _outcome_flag,
    _phase_timing,
    _receipt_count,
    _retired_tenant_field,
    _safe_error_code,
    _safe_error_message,
    _safe_error_metadata,
    _safe_metadata,
    _safe_operation_metadata,
    _safe_request_id,
)


class TelemetryEventMixin:
    @staticmethod
    def _clean_event(event: dict[str, Any]) -> dict[str, Any]:
        retired = _retired_tenant_field(event)
        if retired:
            raise ValueError(retired)
        created = float(event.get("created_at", time.time()))
        queue_wait_ms = _bounded_number(event.get("queue_wait_ms", 0))
        event_type = _safe_metadata(event.get("event_type", "inference"), 40)
        db_wait_ms, db_wait_measured = _phase_timing(event, "db_wait_ms")
        exec_ms, exec_measured = _phase_timing(event, "exec_ms")
        serialization_ms, serialization_measured = _phase_timing(event, "serialization_ms")
        # Route labels are safe only when exact-listed, regardless of event kind.
        # This keeps useful action labels in tool-result events without exposing IDs.
        preserve_route = True
        # Error categories are composed sanitized labels, not MCP selectors.
        # Continue redacting paths/secrets without treating component:operation
        # (for example inference:generate) as an unknown tool route.
        preserve_action_route = not (event_type == "error" and ":" in str(event.get("action", "")))
        safe_root = ""
        if event.get("root"):
            raw_root = str(event["root"]).replace("\\", "/").rstrip("/")
            safe_root = Path(raw_root).name if raw_root else ""
        return {
            "created_at": created,
            "event_type": event_type,
            "agent": _safe_metadata(event.get("agent", ""), 80),
            "request_id": _safe_request_id(event.get("request_id", ""), 96),
            "trace_id": _safe_metadata(event.get("trace_id", ""), 96),
            "action": _safe_metadata(event.get("action", "unknown"), preserve_route=preserve_action_route),
            "stage": _safe_metadata(event.get("stage", ""), 80),
            "task_type": _safe_metadata(event.get("task_type", ""), 80),
            "complexity": _safe_metadata(event.get("complexity", ""), 40),
            "route": _safe_metadata(event.get("route", ""), 120, preserve_route=preserve_route),
            "model": _safe_metadata(event.get("model", "") or ""),
            "cache_hit": 1 if event.get("cache_hit") else 0,
            "coalesced": 1 if event.get("coalesced") else 0,
            "cache_layer": _safe_metadata(event.get("cache_layer", ""), 80),
            "input_tokens": max(0, int(event.get("input_tokens", 0) or 0)),
            "cache_read_tokens": max(0, int(event.get("cache_read_tokens", 0) or 0)),
            "output_tokens": max(0, int(event.get("output_tokens", 0) or 0)),
            "avoided_cloud_tokens": max(0, int(event.get("avoided_cloud_tokens", 0) or 0)),
            "duration_ms": _bounded_number(event.get("duration_ms", 0)),
            "queue_wait_ms": queue_wait_ms,
            "queue_age_ms": _bounded_number(event.get("queue_age_ms", queue_wait_ms)),
            "wait_count": max(0, int(event.get("wait_count", 0) or 0)),
            "wait_duration_ms": max(0.0, float(event.get("wait_duration_ms", 0) or 0)),
            "service_ms": max(0.0, float(event.get("service_ms", 0) or 0)),
            "load_duration_ms": max(0.0, float(event.get("load_duration_ms", 0) or 0)),
            "success": 1 if event.get("success", True) else 0,
            "status_code": max(0, int(event.get("status_code", 0) or 0)),
            "degraded": 1 if event.get("degraded") else 0,
            "retry_count": max(0, int(event.get("retry_count", 0) or 0)),
            "fallback_used": 1 if event.get("fallback_used") else 0,
            "bypass_reason": _safe_metadata(event.get("bypass_reason", ""), 80),
            "terminal": _outcome_flag(event, "terminal"),
            "retryable": _outcome_flag(event, "retryable"),
            "receipt_count": _receipt_count(event),
            "error_type": _safe_metadata(event.get("error_type", ""), 120),
            "error_fingerprint": _safe_metadata(event.get("error_fingerprint", ""), 32),
            "tool_calls": max(0, int(event.get("tool_calls", 0) or 0)),
            "evidence_count": max(0, int(event.get("evidence_count", 0) or 0)),
            "response_bytes": max(0, int(event.get("response_bytes", 0) or 0)),
            "gross_avoided_cloud_tokens": max(0, int(event.get("gross_avoided_cloud_tokens", 0) or 0)),
            "gross_input_tokens_avoided": max(0, int(event.get("gross_input_tokens_avoided", 0) or 0)),
            "gross_output_tokens_avoided": max(0, int(event.get("gross_output_tokens_avoided", 0) or 0)),
            "agent_protocol_tokens": max(0, int(event.get("agent_protocol_tokens", 0) or 0)),
            "tool_request_tokens": max(0, int(event.get("tool_request_tokens", 0) or 0)),
            "tool_response_tokens": max(0, int(event.get("tool_response_tokens", 0) or 0)),
            "tool_schema_tokens": max(0, int(event.get("tool_schema_tokens", 0) or 0)),
            "local_compute_tokens_avoided": max(0, int(event.get("local_compute_tokens_avoided", 0) or 0)),
            "net_cloud_token_delta": int(event.get("net_cloud_token_delta", 0) or 0),
            "cloud_token_overhead": max(0, int(event.get("cloud_token_overhead", 0) or 0)),
            "net_after_schema_token_delta": int(event.get("net_after_schema_token_delta", 0) or 0),
            "schema_adjusted_overhead": max(0, int(event.get("schema_adjusted_overhead", 0) or 0)),
            "savings_source": _clean_savings_source(event.get("savings_source", "")),
            "input_savings_source": _clean_savings_source(event.get("input_savings_source", "")),
            "output_savings_source": _clean_savings_source(event.get("output_savings_source", "")),
            "savings_breakdown_json": _clean_savings_breakdown(event.get("savings_breakdown_json", ""))[:2000],
            "preprocessed_hit": 1 if event.get("preprocessed_hit") else 0,
            "root": _safe_metadata(safe_root, 64) if safe_root else "",
            "db_wait_ms": db_wait_ms,
            "exec_ms": exec_ms,
            "serialization_ms": serialization_ms,
            "db_wait_measured": db_wait_measured,
            "exec_measured": exec_measured,
            "serialization_measured": serialization_measured,
        }

    def _publish_live(self, kind: str, payload: dict[str, Any]) -> None:
        retired = _retired_tenant_field(payload)
        if retired:
            raise ValueError(retired)
        allowed = {
            "created_at", "event_type", "agent", "request_id", "trace_id",
            "action", "stage", "task_type", "complexity", "route", "model",
            "cache_hit", "coalesced", "cache_layer", "duration_ms", "queue_wait_ms", "wait_count", "wait_duration_ms",
            "service_ms", "load_duration_ms", "success", "status_code", "degraded",
            "retry_count", "fallback_used", "bypass_reason", "queue_age_ms", "terminal", "retryable", "receipt_count",
            "error_type", "error_fingerprint",
            "tool_calls", "evidence_count", "response_bytes", "component", "operation",
            "fingerprint", "retryable", "recovered", "name", "metrics_json",
            "preprocessed_hit", "root",
            "db_wait_ms", "exec_ms", "serialization_ms",
            "db_wait_measured", "exec_measured", "serialization_measured",
        }
        event = {k: v for k, v in payload.items() if k in allowed}
        event["kind"] = kind
        event.setdefault("created_at", time.time())
        with self._live_lock:
            self._live_seq += 1
            event["seq"] = self._live_seq
            self._live_events.append(event)

    def live(self, after: int = 0, limit: int = 200, compact: bool = True) -> dict[str, Any]:
        limit = max(1, min(int(limit), 1000))
        with self._live_lock:
            raw_events = [e for e in self._live_events if int(e.get("seq", 0)) > int(after)]
            if len(raw_events) > limit:
                raw_events = raw_events[-limit:]
            cursor = self._live_seq
            oldest = int(self._live_events[0].get("seq", 0)) if self._live_events else cursor
        if compact:
            events = [
                {k: v for k, v in e.items() if not (k in _LIVE_OMIT_EMPTY and (v in ("", 0, 0.0, -1, None)))}
                for e in raw_events
            ]
        else:
            events = [dict(e) for e in raw_events]
        return {"success": True, "cursor": cursor, "oldest": oldest, "events": events}

    def _enqueue(self, kind: str, payload: dict[str, Any]) -> bool:
        if not self.enabled:
            return False
        # Reserve the queue sequence before publishing the item.  The writer
        # thread may consume a freshly queued item immediately; incrementing
        # afterwards lets flush() observe processed >= queued and return before
        # the item is actually visible in SQLite.
        with self._stats_lock:
            self._stats["attempted"] += 1
            self._stats["queued"] += 1
            self._stats["accepted"] += 1
            try:
                self._queue.put_nowait((kind, payload))
            except queue.Full:
                # Observability must never become a back-pressure source for foreground work.
                self._stats["queued"] -= 1
                self._stats["accepted"] -= 1
                self._stats["dropped"] += 1
                self._stats["rejected_overflow"] += 1
                return False
            # Keep accepted queue order aligned with the live feed. The writer can
            # dequeue now, but cannot publish completion stats until this lock releases.
            self._publish_live(kind, payload)
            return True

    def record_live(self, kind: str = "live", **event: Any) -> None:
        retired = _retired_tenant_field(event)
        if retired:
            raise ValueError(retired)
        if not self.enabled:
            return
        ctx = current_trace_context()
        for key in ("request_id", "trace_id", "agent"):
            if not event.get(key) and ctx.get(key):
                event[key] = ctx[key]
        self._publish_live(kind, self._clean_event(event))

    def _refresh_dashboard_report_writer(self, report: dict[str, Any]) -> dict[str, Any]:
        """Refresh cached dashboard writer evidence without querying SQLite."""
        refreshed = dict(report)
        summary = refreshed.get("summary")
        if isinstance(summary, dict):
            refreshed["summary"] = self._refresh_cached_writer_status(
                summary, summary.get("writer", {})
            )
        return refreshed

    def record(self, **event: Any) -> bool:
        retired = _retired_tenant_field(event)
        if retired:
            raise ValueError(retired)
        if not self.enabled:
            return event.get("event_type") == "system"
        if getattr(self, "mode", "full") == "minimal":
            in_tok = max(0, int(event.get("input_tokens", 0) or 0))
            out_tok = max(0, int(event.get("output_tokens", 0) or 0))
            with self._stats_lock:
                self._stats["attempted"] += 1
                self._stats["accepted"] += 1
                self._stats["processed"] += 1
                self._minimal_stats["requests_total"] += 1
                self._minimal_stats["tokens_total"] += (in_tok + out_tok)
                self._minimal_stats["input_tokens_total"] += in_tok
                self._minimal_stats["output_tokens_total"] += out_tok
            return True
        ctx = current_trace_context()
        for key in ("request_id", "trace_id", "agent"):
            if not event.get(key) and ctx.get(key):
                event[key] = ctx[key]
        return self._enqueue("event", self._clean_event(event))

    def record_http(self, **event: Any) -> None:
        event["event_type"] = "http"
        self.record(**event)

    def record_stage(self, **event: Any) -> None:
        event["event_type"] = "stage"
        self.record(**event)

    def record_tool_accounting(self, event: dict[str, Any]) -> bool:
        """Record one agent-visible MCP call without storing arguments or output.

        Signed net deltas are stored independently from inference context reduction.
        Gross savings, protocol cost and schema exposure remain separate so the
        dashboard can explain the accounting without double counting.
        """
        if not isinstance(event, dict):
            raise TypeError("tool accounting event must be an object")
        retired = _retired_tenant_field(event)
        if retired:
            raise ValueError(retired)
        tool_name = event.get("tool")
        if isinstance(tool_name, str) and tool_name[:160] == "local_ai_telemetry":
            return False
        breakdown = event.get("savings_breakdown") if isinstance(event.get("savings_breakdown"), dict) else {}
        clean_breakdown_json = _clean_savings_breakdown(breakdown)
        clean_breakdown = json.loads(clean_breakdown_json) if clean_breakdown_json else {}
        primary = max(clean_breakdown.items(), key=lambda kv: kv[1], default=("", 0))[0]
        gross = max(0, int(event.get("gross_cloud_tokens_avoided_est", 0) or 0))
        input_source = _clean_savings_source(event.get("input_savings_source", ""))
        output_source = _clean_savings_source(event.get("output_savings_source", ""))
        gross_input = max(0, int(event.get("gross_input_tokens_avoided_est", 0) or 0))
        gross_output = max(0, int(event.get("gross_output_tokens_avoided_est", 0) or 0))
        accepted = self.record(
            event_type="tool_accounting",
            agent=str(event.get("agent", ""))[:80],
            action=str(event.get("tool", "unknown"))[:160],
            success=True,
            tool_calls=1,
            input_tokens=max(0, int(event.get("agent_tool_request_tokens_est", 0) or 0)),
            output_tokens=max(0, int(event.get("agent_tool_response_tokens_est", 0) or 0)),
            avoided_cloud_tokens=0,
            gross_avoided_cloud_tokens=gross,
            gross_input_tokens_avoided=gross_input,
            gross_output_tokens_avoided=gross_output,
            agent_protocol_tokens=max(0, int(event.get("agent_protocol_tokens_est", 0) or 0)),
            tool_request_tokens=max(0, int(event.get("agent_tool_request_tokens_est", 0) or 0)),
            tool_response_tokens=max(0, int(event.get("agent_tool_response_tokens_est", 0) or 0)),
            tool_schema_tokens=max(0, int(event.get("tool_schema_tokens_est", 0) or 0)),
            local_compute_tokens_avoided=max(0, int(event.get("local_compute_tokens_avoided_est", 0) or 0)),
            net_cloud_token_delta=int(event.get("net_cloud_token_delta_est", 0) or 0),
            cloud_token_overhead=max(0, int(event.get("cloud_token_overhead_est", 0) or 0)),
            net_after_schema_token_delta=int(event.get("net_after_schema_token_delta_est", 0) or 0),
            schema_adjusted_overhead=max(0, int(event.get("schema_adjusted_overhead_est", 0) or 0)),
            savings_source=primary,
            input_savings_source=input_source,
            output_savings_source=output_source,
            savings_breakdown_json=json_dumps(clean_breakdown, separators=(",", ":"), sort_keys=True),
        )
        return accepted

    def record_system(self, action: str, *, success: bool = True, duration_ms: float = 0.0, **event: Any) -> bool:
        event.update({"event_type": "system", "action": action, "success": success, "duration_ms": duration_ms})
        if not self.enabled:
            return True
        return self.record(**event)

    def record_error(
        self,
        component: str,
        operation: str,
        error: Any,
        *,
        request_id: str = "",
        agent: str = "",
        error_type_override: str = "",
        error_code_override: str = "",
        retryable: bool = False,
        recovered: bool = False,
    ) -> str:
        retired = _retired_tenant_field({"component": component, "operation": operation})
        if retired:
            raise ValueError(retired)
        if not self.enabled:
            return ""
        if getattr(self, "mode", "full") == "minimal":
            with self._stats_lock:
                self._minimal_stats["errors_total"] += 1
            return "minimal_err"
        ctx = current_trace_context()
        request_id = request_id or str(ctx.get("request_id") or "")
        agent = agent or str(ctx.get("agent") or "")
        error_type = error_type_override or (type(error).__name__ if isinstance(error, BaseException) else "Error")
        safe_request_id = _safe_error_metadata(request_id, 96)
        safe_agent = _safe_error_metadata(agent, 80)
        safe_component = _safe_error_metadata(component, 120)
        safe_operation = _safe_operation_metadata(operation)
        safe_error_type = _safe_error_metadata(error_type, 120)
        safe_error_code = error_code_override if error_code_override in _SAFE_ERROR_CODE_MESSAGES else _safe_error_code(error)
        message = (
            f"{safe_error_type}: {_SAFE_ERROR_CODE_MESSAGES[error_code_override]}"
            if error_code_override in _SAFE_ERROR_CODE_MESSAGES
            else _safe_error_message(error, error_type_override=safe_error_type)
        )[:96]
        fp = _error_fingerprint(safe_error_type, safe_component, safe_operation, safe_error_code)
        payload = {
            "created_at": time.time(), "request_id": safe_request_id, "agent": safe_agent,
            "component": safe_component, "operation": safe_operation, "error_type": safe_error_type,
            "fingerprint": fp, "safe_message": message, "retryable": 1 if retryable else 0,
            "recovered": 1 if recovered else 0,
        }
        self._enqueue("error", payload)
        self.record(
            event_type="error", agent=safe_agent, request_id=safe_request_id,
            action=(
                safe_operation
                if safe_component == "http" and safe_operation in _SAFE_HTTP_ROUTE_LABELS
                else f"{safe_component}:{safe_operation}"
            ), success=False,
            error_type=safe_error_type, error_fingerprint=fp,
        )
        return fp

    def session_start(self, pid: int | None = None, version: str = "") -> int:
        if not self.enabled:
            return 0
        if getattr(self, "mode", "full") == "minimal":
            self.process_started_at = time.time()
            self._current_session_id = 1
            return 1
        now = time.time()
        pid = os.getpid() if pid is None else int(pid)
        self._current_pid = pid
        self._current_version = str(version)
        self.process_started_at = now
        with closing(self._connect()) as con:
            cur = con.execute(
                "INSERT INTO process_sessions (pid, version, started_at, last_heartbeat, exit_clean) VALUES (?, ?, ?, ?, 0)",
                (pid, str(version), now, now),
            )
            con.commit()
            session_id = int(cur.lastrowid or 0)
        self._current_session_id = session_id
        return session_id

    def session_heartbeat(self) -> None:
        if not self.enabled or not self._current_session_id or getattr(self, "mode", "full") == "minimal":
            return
        now = time.time()
        try:
            with closing(self._connect()) as con:
                con.execute(
                    "UPDATE process_sessions SET last_heartbeat=? WHERE id=?",
                    (now, self._current_session_id),
                )
                con.commit()
        except Exception:
            pass

    def session_stop(self) -> None:
        if not self.enabled or not self._current_session_id or getattr(self, "mode", "full") == "minimal":
            return
        now = time.time()
        try:
            with closing(self._connect()) as con:
                con.execute(
                    "UPDATE process_sessions SET stopped_at=?, last_heartbeat=?, exit_clean=1 WHERE id=?",
                    (now, now, self._current_session_id),
                )
                con.commit()
        except Exception:
            pass
        self._current_session_id = None

    def sessions(self, days: int = 30, limit: int = 100) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        cutoff = time.time() - max(1, int(days)) * 86400
        now = time.time()
        session_limit = max(1, min(int(limit), 100))
        with closing(self._connect()) as con:
            session_rows = con.execute(
                "SELECT id,pid,version,started_at,stopped_at,last_heartbeat,exit_clean "
                "FROM process_sessions WHERE started_at>=? ORDER BY started_at DESC LIMIT ?",
                (cutoff, session_limit),
            ).fetchall()
            if not session_rows:
                return []

            sessions = []
            for row in session_rows:
                sid, _pid, _version, _started_at, stopped_at, last_heartbeat, exit_clean = row
                if sid == self._current_session_id and stopped_at is None:
                    status = "active"
                    end_time = now
                elif exit_clean:
                    status = "clean_stop"
                    end_time = stopped_at if stopped_at is not None else last_heartbeat
                else:
                    status = "crashed"
                    end_time = stopped_at if stopped_at is not None else last_heartbeat
                sessions.append((*row, status, end_time))

            aggregates = (
                "COUNT(*), COALESCE(SUM(cache_hit),0), "
                "COALESCE(SUM(CASE WHEN event_type='inference' THEN 1 ELSE 0 END),0), "
                "COALESCE(SUM(CASE WHEN event_type='inference' AND cache_hit=1 THEN 1 ELSE 0 END),0), "
                "COALESCE(SUM(CASE WHEN event_type='tool_accounting' THEN net_cloud_token_delta ELSE 0 END),0), "
                "COALESCE(SUM(CASE WHEN success=0 THEN 1 ELSE 0 END),0)"
            )
            branches = []
            parameters = []
            for position, session in enumerate(sessions):
                # position is generated locally; all database values remain bound.
                branches.append(
                    f"SELECT {position}, {aggregates} FROM events "
                    "WHERE created_at>=? AND created_at<=?"
                )
                parameters.extend((session[3], session[8]))
            aggregate_sql = " UNION ALL ".join(branches)
            aggregate_rows = con.execute(aggregate_sql, parameters).fetchall()

        aggregates_by_position = {int(row[0]): row[1:] for row in aggregate_rows}
        result = []
        for position, session in enumerate(sessions):
            (sid, pid, version, started_at, stopped_at, last_heartbeat, exit_clean,
             status, end_time) = session
            (total, total_cache_hits, inf_events, inf_cache_hits,
             avoided_tokens, failures) = aggregates_by_position[position]
            duration_seconds = max(0.0, float(end_time - started_at))
            total_events = int(total or 0)
            total_cache_hits = int(total_cache_hits or 0)
            inf_events = int(inf_events or 0)
            inf_cache_hits = int(inf_cache_hits or 0)
            avoided_tokens = int(avoided_tokens or 0)
            failures = int(failures or 0)
            if inf_events > 0:
                hit_rate = round(inf_cache_hits / inf_events, 4)
            elif total_events > 0:
                hit_rate = round(total_cache_hits / total_events, 4)
            else:
                hit_rate = 0.0

            result.append({
                "session_id": sid,
                "pid": pid,
                "version": version,
                "started_at": started_at,
                "stopped_at": stopped_at,
                "last_heartbeat": last_heartbeat,
                "duration_seconds": round(duration_seconds, 1),
                "exit_clean": int(exit_clean),
                "status": status,
                "events": total_events,
                "cache_hits": inf_cache_hits if inf_events > 0 else total_cache_hits,
                "cache_hit_rate": hit_rate,
                "tokens_saved": avoided_tokens,
                "failures": failures,
            })
        return result

    def record_snapshot(self, name: str, metrics: dict[str, Any]) -> None:
        retired = _retired_tenant_field(metrics)
        if retired:
            raise ValueError(retired)
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
        self._enqueue("snapshot", {"created_at": time.time(), "name": str(name)[:80], "metrics_json": json_dumps(safe, separators=(",", ":"))[:8000]})

    def record_laya_decision(
        self,
        metadata: dict[str, Any],
        *,
        repository_id: str,
        task_id: str | None,
        session_id: str,
    ) -> bool:
        """Persist one validated Laya decision projection in existing snapshots.

        This accepts only the side-effect-free decision contract's metadata. It is
        intentionally not an inference or candidate-text API. Identity arguments
        must come from the server-bound request context, never from caller payload.
        """
        if not isinstance(metadata, dict) or set(metadata) != _LAYA_DECISION_FIELDS:
            raise ValueError("invalid Laya decision metadata fields")
        server_task_id = task_id
        for field, value in (
            ("repository_id", repository_id),
            ("session_id", session_id),
        ):
            if not isinstance(value, str) or not _LAYA_IDENTIFIER.fullmatch(value):
                raise ValueError(f"invalid server-bound Laya {field}")
        if server_task_id is not None and (
            not isinstance(server_task_id, str) or not _LAYA_IDENTIFIER.fullmatch(server_task_id)
        ):
            raise ValueError("invalid server-bound Laya task_id")
        for field in ("decision_id", "repository_id", "session_id"):
            value = metadata[field]
            if not isinstance(value, str) or not _LAYA_IDENTIFIER.fullmatch(value):
                raise ValueError(f"invalid Laya {field}")
        task_id = metadata["task_id"]
        if task_id is not None and (
            not isinstance(task_id, str) or not _LAYA_IDENTIFIER.fullmatch(task_id)
        ):
            raise ValueError("invalid Laya task_id")
        if (
            metadata["repository_id"] != repository_id
            or metadata["task_id"] != server_task_id
            or metadata["session_id"] != session_id
        ):
            raise ValueError("Laya metadata identity does not match server-bound context")
        mode = metadata["mode"]
        status = metadata["status"]
        category = metadata["category"]
        if not isinstance(mode, str) or mode not in {"shadow", "advisory"}:
            raise ValueError("invalid Laya mode")
        if not isinstance(status, str) or status not in _LAYA_DECISION_STATUSES:
            raise ValueError("invalid Laya status")
        if not isinstance(category, str) or category not in _LAYA_DECISION_OPTIONS:
            raise ValueError("invalid Laya category")
        if type(metadata["success"]) is not bool:
            raise ValueError("invalid Laya success flag")
        if metadata["success"] is not (status in {"success", "abstain"}):
            raise ValueError("inconsistent Laya success status")
        if type(metadata["model_estimate"]) is not bool:
            raise ValueError("invalid Laya model_estimate flag")
        if metadata["model_estimate"] is not (status in {"success", "abstain"}):
            raise ValueError("inconsistent Laya model_estimate status")
        expected_uncertainty = "UNCALIBRATED" if metadata["model_estimate"] else "NOT_APPLICABLE"
        if metadata["uncertainty"] != expected_uncertainty:
            raise ValueError("invalid Laya uncertainty")
        if metadata["execution_verification"] != "NOT_VERIFIED":
            raise ValueError("Laya execution provenance is not verified")

        suggestion = metadata["suggestion"]
        if status == "success":
            if not isinstance(suggestion, str) or suggestion not in _LAYA_DECISION_OPTIONS[category]:
                raise ValueError("invalid Laya suggestion")
        elif suggestion is not None:
            raise ValueError("non-success Laya decision cannot include a suggestion")

        reason_codes = metadata["reason_codes"]
        evidence_ids = metadata["evidence_ids"]
        if not isinstance(reason_codes, list) or len(reason_codes) > 8:
            raise ValueError("invalid Laya reason_codes")
        if not isinstance(evidence_ids, list) or len(evidence_ids) > 64:
            raise ValueError("invalid Laya evidence_ids")
        if any(not isinstance(code, str) or code not in _LAYA_REASON_CODES for code in reason_codes):
            raise ValueError("invalid Laya reason_codes")
        if len(set(reason_codes)) != len(reason_codes):
            raise ValueError("invalid Laya reason_codes")
        if status != "success" and not reason_codes:
            raise ValueError("non-success Laya decision requires a reason code")
        if any(not isinstance(item, str) or not _LAYA_IDENTIFIER.fullmatch(item) for item in evidence_ids):
            raise ValueError("invalid Laya evidence_ids")
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("invalid Laya evidence_ids")

        safe = dict(metadata)
        safe["reason_codes"] = json_dumps(reason_codes, separators=(",", ":"))
        safe["evidence_ids"] = json_dumps(evidence_ids, separators=(",", ":"))
        for field in ("runtime_latency_ms", "inference_latency_ms", "queue_wait_ms"):
            value = safe[field]
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(float(value)) or not 0 <= float(value) <= 86_400_000
            ):
                raise ValueError(f"invalid Laya {field}")
        backend = safe["backend"]
        if backend is not None and (
            not isinstance(backend, str) or not _LAYA_IDENTIFIER.fullmatch(backend)
        ):
            raise ValueError("invalid Laya backend")
        fallback_used = safe["fallback_used"]
        if fallback_used is not None and type(fallback_used) is not bool:
            raise ValueError("invalid Laya fallback flag")
        fallback_reason = safe["fallback_reason"]
        if fallback_reason is not None and (
            not isinstance(fallback_reason, str)
            or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", fallback_reason)
        ):
            raise ValueError("invalid Laya fallback reason")
        if (fallback_used is True) != (fallback_reason is not None):
            raise ValueError("inconsistent Laya fallback metadata")
        encoded = json_dumps(safe, separators=(",", ":"), sort_keys=True)
        if len(encoded) > 8000:
            raise ValueError("Laya decision metadata exceeds snapshot limit")
        if not self.enabled:
            return False
        return self._enqueue(
            "snapshot",
            {"created_at": time.time(), "name": "laya_decision", "metrics_json": encoded},
        )

    def record_laya_eligibility(
        self,
        *,
        decision_id: str,
        mode: str,
        category: str,
    ) -> bool:
        """Record one validated Laya inference attempt before model execution."""
        if not isinstance(decision_id, str) or not _LAYA_IDENTIFIER.fullmatch(decision_id):
            raise ValueError("invalid Laya decision_id")
        if not isinstance(mode, str) or mode not in {"shadow", "advisory"}:
            raise ValueError("invalid Laya mode")
        if not isinstance(category, str) or category not in _LAYA_DECISION_OPTIONS:
            raise ValueError("invalid Laya category")
        encoded = json_dumps(
            {"decision_id": decision_id, "mode": mode, "category": category},
            separators=(",", ":"), sort_keys=True,
        )
        if not self.enabled:
            return False
        return self._enqueue(
            "snapshot",
            {"created_at": time.time(), "name": "laya_decision_eligible", "metrics_json": encoded},
        )

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
