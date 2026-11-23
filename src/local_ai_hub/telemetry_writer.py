from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import math
import queue
import sqlite3
import time
from typing import Any

from .sqlite_support import connect_sqlite, is_busy_error


class TelemetryWriterMixin:
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
            agg = grouped.setdefault(key, [0, 0.0, 0.0] + [0] * 19)
            agg[0] += 1; agg[1] += e["duration_ms"]; agg[2] += e["queue_wait_ms"]
            agg[3] += e["input_tokens"]; agg[4] += e["cache_read_tokens"]; agg[5] += e["output_tokens"]; agg[6] += e["avoided_cloud_tokens"]
            agg[7] += e["cache_hit"]; agg[8] += e["fallback_used"]; agg[9] += e["degraded"]
            agg[10] += e["gross_avoided_cloud_tokens"]
            agg[11] += e["gross_input_tokens_avoided"]; agg[12] += e["gross_output_tokens_avoided"]
            agg[13] += e["agent_protocol_tokens"]; agg[14] += e["tool_schema_tokens"]
            agg[15] += e["local_compute_tokens_avoided"]
            agg[16] += e["tool_request_tokens"]; agg[17] += e["tool_response_tokens"]
            agg[18] += e["net_cloud_token_delta"]; agg[19] += e["cloud_token_overhead"]
            agg[20] += e["net_after_schema_token_delta"]; agg[21] += e["schema_adjusted_overhead"]
        con.executemany(
            """INSERT INTO daily_rollups(day,event_type,action,agent,model,cache_layer,success,events,duration_ms,queue_wait_ms,input_tokens,cache_read_tokens,output_tokens,avoided_cloud_tokens,cache_hits,fallback_count,degraded_count,gross_avoided_cloud_tokens,gross_input_tokens_avoided,gross_output_tokens_avoided,agent_protocol_tokens,tool_schema_tokens,local_compute_tokens_avoided,tool_request_tokens,tool_response_tokens,net_cloud_token_delta,cloud_token_overhead,net_after_schema_token_delta,schema_adjusted_overhead)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(day,event_type,action,agent,model,cache_layer,success) DO UPDATE SET
                 events=events+excluded.events, duration_ms=duration_ms+excluded.duration_ms,
                 queue_wait_ms=queue_wait_ms+excluded.queue_wait_ms, input_tokens=input_tokens+excluded.input_tokens,
                 cache_read_tokens=cache_read_tokens+excluded.cache_read_tokens,
                 output_tokens=output_tokens+excluded.output_tokens, avoided_cloud_tokens=avoided_cloud_tokens+excluded.avoided_cloud_tokens,
                 cache_hits=cache_hits+excluded.cache_hits, fallback_count=fallback_count+excluded.fallback_count,
                 degraded_count=degraded_count+excluded.degraded_count,
                 gross_avoided_cloud_tokens=gross_avoided_cloud_tokens+excluded.gross_avoided_cloud_tokens,
                 gross_input_tokens_avoided=gross_input_tokens_avoided+excluded.gross_input_tokens_avoided,
                 gross_output_tokens_avoided=gross_output_tokens_avoided+excluded.gross_output_tokens_avoided,
                 agent_protocol_tokens=agent_protocol_tokens+excluded.agent_protocol_tokens,
                 tool_schema_tokens=tool_schema_tokens+excluded.tool_schema_tokens,
                 local_compute_tokens_avoided=local_compute_tokens_avoided+excluded.local_compute_tokens_avoided,
                 tool_request_tokens=tool_request_tokens+excluded.tool_request_tokens,
                 tool_response_tokens=tool_response_tokens+excluded.tool_response_tokens,
                 net_cloud_token_delta=net_cloud_token_delta+excluded.net_cloud_token_delta,
                 cloud_token_overhead=cloud_token_overhead+excluded.cloud_token_overhead,
                 net_after_schema_token_delta=net_after_schema_token_delta+excluded.net_after_schema_token_delta,
                 schema_adjusted_overhead=schema_adjusted_overhead+excluded.schema_adjusted_overhead""",
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
                    """INSERT INTO errors(created_at,request_id,agent,component,operation,error_type,fingerprint,safe_message,retryable,recovered)
                       VALUES(:created_at,:request_id,:agent,:component,:operation,:error_type,:fingerprint,:safe_message,:retryable,:recovered)""",
                    errors,
                )
            if snapshots:
                con.executemany(
                    "INSERT INTO snapshots(created_at,name,metrics_json) VALUES(:created_at,:name,:metrics_json)", snapshots
                )
            con.commit()
        with self._stats_lock:
            self._stats["processed"] += len(batch)
            self._stats["written"] += len(batch)
            self._stats["batches"] += 1

    def _prune(self) -> None:
        cutoff = time.time() - self.retention_days * 86400
        rollup_cutoff = datetime.fromtimestamp(time.time() - self.rollup_retention_days * 86400, tz=timezone.utc).strftime("%Y-%m-%d")
        with closing(self._connect()) as con:
            con.execute("DELETE FROM events WHERE created_at<?", (cutoff,))
            con.execute("DELETE FROM errors WHERE created_at<?", (cutoff,))
            con.execute("DELETE FROM snapshots WHERE created_at<?", (cutoff,))
            con.execute("DELETE FROM process_sessions WHERE started_at<?", (cutoff,))
            count = int(con.execute("SELECT COUNT(*) FROM events").fetchone()[0])
            if count > self.max_events:
                con.execute("DELETE FROM events WHERE id IN (SELECT id FROM events ORDER BY id ASC LIMIT ?)", (count - self.max_events,))
            con.execute("DELETE FROM daily_rollups WHERE day<?", (rollup_cutoff,))
            con.commit()

    def resolve_errors(self, *, timeout_seconds: float = 2.0) -> dict[str, Any]:
        """Acknowledge and clear all recorded operational failures, errors, crashes, and unclean sessions."""
        if not self.enabled:
            return {"enabled": False}
        duration = float(timeout_seconds)
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("timeout_seconds must be a positive finite number")
        deadline = time.monotonic() + min(10.0, duration)

        def remaining() -> float:
            budget = deadline - time.monotonic()
            if budget <= 0:
                raise TimeoutError("telemetry resolution time budget exceeded")
            return budget

        try:
            if not self.flush(min(1.0, remaining())):
                raise TimeoutError("telemetry resolution time budget exceeded")
            with closing(connect_sqlite(self.path, timeout_seconds=min(1.0, remaining()))) as con:
                con.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
                try:
                    with con:
                        remaining()
                        resolved_events = con.execute("UPDATE events SET success=1, error_type='' WHERE success=0;").rowcount
                        remaining()
                        cleared_errors = con.execute("DELETE FROM errors;").rowcount
                        remaining()
                        cleaned_sessions = con.execute("UPDATE process_sessions SET exit_clean=1 WHERE exit_clean=0;").rowcount
                        remaining()
                        con.execute("DELETE FROM daily_rollups WHERE success=0;")
                        remaining()
                finally:
                    con.set_progress_handler(None, 0)
        except (TimeoutError, sqlite3.Error) as exc:
            if isinstance(exc, TimeoutError) or is_busy_error(exc) or "interrupted" in str(exc).lower():
                return {"success": False, "degraded": True, "retryable": True,
                        "error": "telemetry resolution time budget exceeded"}
            raise
        with self._summary_cache_lock:
            self._summary_cache.clear()
        with self._live_lock:
            for ev in self._live_events:
                if not ev.get("success", True):
                    ev["success"] = True
                    ev["error_type"] = ""
                    ev["resolved"] = True
        return {
            "success": True,
            "resolved_events": resolved_events,
            "cleared_errors": cleared_errors,
            "cleaned_sessions": cleaned_sessions,
        }

    def _writer_loop(self) -> None:
        last_prune = 0.0
        batch: list[tuple[str, dict[str, Any]]] = []
        busy_retries = 0
        while not self._stop.is_set() or not self._queue.empty() or batch:
            try:
                if not batch:
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
                    busy_retries = 0
                    self.session_heartbeat()
                if time.monotonic() - last_prune > 60.0:
                    self._prune(); last_prune = time.monotonic()
                    self.session_heartbeat()
            except Exception as exc:
                abandoned = 0
                with self._stats_lock:
                    self._stats["writer_errors"] += 1
                    is_busy = is_busy_error(exc)
                    if is_busy:
                        busy_retries += 1
                    if not is_busy or busy_retries > 10 or (self._stop.is_set() and busy_retries > 2):
                        abandoned = len(batch)
                        batch.clear()
                        busy_retries = 0
                if abandoned:
                    self._record_writer_abandonment(abandoned)
                retry_multiplier = max(1, busy_retries) if is_busy else 2
                retry_delay = min(1.0, self.flush_interval_seconds * retry_multiplier)
                sleep_dur = 0.05 if self._stop.is_set() else retry_delay
                time.sleep(sleep_dur)

    def _record_writer_abandonment(self, count: int) -> None:
        """Account for accepted queue records permanently abandoned by the writer."""
        abandoned = max(0, int(count))
        if not abandoned:
            return
        with self._stats_lock:
            self._stats["processed"] += abandoned
            self._stats["dropped"] += abandoned
            self._stats["lost_after_acceptance"] += abandoned

    def flush(self, timeout: float = 3.0) -> bool:
        """True only when accepted records through the boundary were persisted."""
        return self.flush_status(timeout)["durable"]

    def flush_status(self, timeout: float = 3.0) -> dict[str, Any]:
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout < 0:
            raise ValueError("flush timeout must be finite and nonnegative")
        if not self.enabled:
            return {"enabled": False, "drained": True, "durable": True, "accepted_target": 0,
                    "processed": 0, "written": 0, "lost_after_acceptance": 0, "timed_out": False}
        if getattr(self, "mode", "full") == "minimal":
            return {"enabled": True, "mode": "minimal", "drained": True, "durable": True,
                    "accepted_target": 0, "processed": 0, "written": 0,
                    "lost_after_acceptance": 0, "timed_out": False}
        with self._stats_lock:
            target = int(self._stats["queued"])
        deadline = time.monotonic() + min(float(timeout), 3600.0)
        while True:
            with self._stats_lock:
                completed = int(self._stats["processed"])
                written = int(self._stats.get("written", 0))
                lost = int(self._stats.get("lost_after_acceptance", 0))
            remaining = deadline - time.monotonic()
            if completed >= target or remaining <= 0:
                drained = completed >= target
                return {"enabled": True, "accepted_target": target, "processed": completed,
                        "written": written, "lost_after_acceptance": lost,
                        "drained": drained, "durable": drained and written >= target and lost == 0,
                        "timed_out": not drained}
            time.sleep(min(0.02, remaining))

    def _writer_snapshot(self) -> dict[str, Any]:
        """Snapshot current-process queue accounting, independent of report window."""
        with self._stats_lock:
            writer = dict(self._stats)
            snapshot_end_at = time.time()
            elapsed = max(0.0, time.monotonic() - self._process_started_monotonic)
        attempted = int(writer.get("attempted", 0))
        accepted = int(writer.get("accepted", writer.get("queued", 0)))
        processed = int(writer.get("processed", 0))
        written = int(writer.get("written", 0))
        rejected = int(writer.get("rejected_overflow", 0))
        lost = int(writer.get("lost_after_acceptance", 0))
        pending = max(0, accepted - processed)
        rejected_or_lost = rejected + lost
        writer.update({
            "scope": "current_process",
            "process_started_at": self.process_started_at,
            "snapshot_end_at": snapshot_end_at,
            "interval_seconds": round(elapsed, 6),
            "queue_depth": self._queue.qsize(),
            "attempted": attempted,
            "accepted": accepted,
            "rejected_overflow": rejected,
            "lost_after_acceptance": lost,
            "pending": pending,
            "activity_observed": attempted > 0,
            "writer_error_attempts": int(writer.get("writer_errors", 0)),
            "accounting_balanced": (
                attempted == accepted + rejected
                and int(writer.get("queued", accepted)) == accepted
                and int(writer.get("dropped", rejected_or_lost)) == rejected_or_lost
                and processed == written + lost
                and accepted == written + lost + pending
            ),
            "writer_errors_unit": "caught writer exception attempts; may include retryable attempts",
            "accepted_rate": round(accepted / attempted, 4) if attempted else None,
            "overflow_rejection_rate": round(rejected / attempted, 4) if attempted else None,
            "post_acceptance_loss_rate": round(lost / accepted, 4) if accepted else None,
            "written_rate": round(written / accepted, 4) if accepted else None,
            "pending_rate": round(pending / accepted, 4) if accepted else None,
        })
        return writer

    def _refresh_cached_writer_status(
        self, data: dict[str, Any], previous_writer: dict[str, Any]
    ) -> dict[str, Any]:
        """Refresh cheap process counters so cache hits cannot preserve a false clean status."""
        refreshed = dict(data)
        writer = self._writer_snapshot()
        # Only a new SQL summary can clear a prior stale marker; identical later
        # writer counters do not make the cached aggregate current again.
        changed = bool(data.get("summary_cache_stale") or data.get("stale")) or any(
            int(writer.get(key, 0)) != int(previous_writer.get(key, 0))
            for key in ("attempted", "accepted", "rejected_overflow", "lost_after_acceptance", "written", "writer_errors")
        )
        if not changed:
            refreshed["writer"] = dict(previous_writer)
            refreshed["summary_cache_stale"] = False
            return refreshed
        old_detail = refreshed.get("detail", {})
        detail = self._detail_status(
            truncated=bool(old_detail.get("truncated", False)) if isinstance(old_detail, dict) else False,
            flush_complete=writer["pending"] == 0,
            writer=writer,
        )
        detail["status"] = "incomplete"
        detail["incomplete"] = True
        detail["omitted_sections"] = sorted(set(detail["omitted_sections"] + ["cached_summary_data"]))
        refreshed["writer"] = writer
        refreshed["detail"] = detail
        refreshed["summary_cache_stale"] = True
        decision_grade = refreshed.get("decision_grade")
        if isinstance(decision_grade, dict):
            decision_grade = dict(decision_grade)
            decision_grade["detail"] = detail
            refreshed["decision_grade"] = decision_grade
        return refreshed
