from __future__ import annotations

from .json_utils import dumps as json_dumps

import json
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any, Callable

from .cache import stable_hash
from .debug_traces import DebugTraceObserver
from .sqlite_support import connect_sqlite, initialize_wal, retry_busy
from .trace_context import reset_observer, set_observer


class AsyncJobManager:
    """Durable, tenant-scoped orchestration whose model calls use the scheduler."""

    ACTIONS = {"delegate", "reason", "review", "review_diff", "second_opinion", "compress", "route", "batch", "speculative_lint"}

    def __init__(
        self,
        config: dict[str, Any],
        scheduler: Any,
        artifacts: Any,
        executor: Callable[[str, dict[str, Any], str], dict[str, Any]],
        debug_traces: Any | None = None,
        task_store: Any | None = None,
        verification_store: Any | None = None,
        telemetry: Any | None = None,
    ):
        cfg = config.get("async_jobs", {})
        self.enabled = bool(cfg.get("enabled", True))
        self.max_pending = max(1, int(cfg.get("max_pending", 64)))
        self.wait_max_seconds = max(1.0, min(3600.0, float(cfg.get("wait_max_seconds", 600))))
        self.lease_seconds = max(30.0, float(cfg.get("lease_seconds", 900)))
        self.result_ttl_seconds = max(60.0, float(cfg.get("result_ttl_seconds", 259200)))
        self.max_attempts = max(1, int(cfg.get("max_attempts", 2)))
        self.scheduler, self.artifacts, self.executor, self.debug_traces = scheduler, artifacts, executor, debug_traces
        self.task_store = task_store
        self.verification_store = verification_store
        self.telemetry = telemetry
        self.path = Path(config["server"]["state_dir"]) / "async_jobs.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._events: dict[str, threading.Event] = {}
        self._delayed_dispatch: dict[str, threading.Timer] = {}
        self._dispatchers: set[threading.Thread] = set()
        self._workers: set[threading.Thread] = set()
        self._shutdown = threading.Event()
        self._stats = {"submitted": 0, "coalesced": 0, "completed": 0, "failed": 0, "cancelled": 0, "recovered": 0, "expired": 0}
        self._initialized = False
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self.path, timeout_seconds=0.75)

    def _init_db(self) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            def _setup() -> None:
                with closing(self._connect()) as con:
                    initialize_wal(con)
                    expected_columns = [
                        "job_id", "tenant", "action", "request_hash", "payload_json", "state", "result_json",
                        "artifact_id", "error", "lease_until", "attempts", "cancel_requested", "created_at",
                        "updated_at", "expires_at", "trace_id", "task_id",
                    ]
                    existing = {str(row[0]) for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    if "async_jobs" in existing:
                        actual_columns = [str(row[1]) for row in con.execute("PRAGMA table_info(async_jobs)")]
                        if actual_columns != expected_columns:
                            con.execute("DROP TABLE async_jobs")
                    con.execute("""CREATE TABLE IF NOT EXISTS async_jobs (
                        job_id TEXT PRIMARY KEY, tenant TEXT NOT NULL, action TEXT NOT NULL, request_hash TEXT NOT NULL,
                        payload_json TEXT NOT NULL, state TEXT NOT NULL, result_json TEXT NOT NULL DEFAULT '',
                        artifact_id TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '', lease_until REAL NOT NULL DEFAULT 0,
                        attempts INTEGER NOT NULL DEFAULT 0, cancel_requested INTEGER NOT NULL DEFAULT 0,
                        created_at REAL NOT NULL, updated_at REAL NOT NULL, expires_at REAL NOT NULL,
                        trace_id TEXT NOT NULL DEFAULT '', task_id TEXT NOT NULL DEFAULT ''
                    )""")
                    con.execute("CREATE INDEX IF NOT EXISTS idx_async_jobs_state ON async_jobs(state, lease_until, expires_at)")
                    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_async_jobs_active_dedupe ON async_jobs(tenant, request_hash) WHERE state IN ('queued','running')")
                    con.commit()
            retry_busy(_setup, retries=5, base_delay_seconds=0.02)
            self._initialized = True

    @staticmethod
    def _safe_payload(payload: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "task", "context", "candidate", "complexity", "max_tokens", "tasks", "task_id", "root", "paths", "command",
            "instructions", "base", "staged", "mode", "diff_tokens", "consensus", "_async_job",
        }
        return {key: payload[key] for key in allowed if key in payload}

    def _event(self, job_id: str) -> threading.Event:
        with self._lock:
            return self._events.setdefault(job_id, threading.Event())

    def _dispatch_background(self, job_id: str) -> None:
        """Start scheduler admission off the request thread."""
        def run() -> None:
            try:
                self._dispatch(job_id)
            finally:
                with self._lock:
                    self._dispatchers.discard(threading.current_thread())

        worker = threading.Thread(target=run, name=f"async-dispatch-{job_id[:8]}", daemon=True)
        with self._lock:
            if self._shutdown.is_set():
                return
            self._dispatchers.add(worker)
        worker.start()

    def submit(self, tenant: str, action: str, payload: dict[str, Any], *, dispatch_delay_seconds: float = 0.0) -> dict[str, Any]:
        if self._shutdown.is_set():
            return {"success": False, "error": "async job manager is closed", "terminal": True, "retryable": False}
        if not self.enabled:
            return {"success": False, "error": "async jobs disabled", "terminal": True, "retryable": False}
        action = str(action).strip().lower().replace("-", "_")
        if action not in self.ACTIONS:
            return {"success": False, "error": f"unsupported async task action: {action}", "terminal": True, "retryable": False}
        clean = self._safe_payload(payload)
        encoded = json_dumps(clean, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > 2_000_000:
            return {"success": False, "error": "async task payload exceeds 2MB", "terminal": True, "retryable": False}
        request_hash = stable_hash({"tenant": tenant, "action": action, "payload": clean})
        task_id = str(clean.get("task_id") or "")
        now = time.time()
        with self._lock, closing(self._connect()) as con:
            existing = con.execute("SELECT job_id,state,trace_id,task_id FROM async_jobs WHERE tenant=? AND request_hash=? AND state IN ('queued','running')", (tenant, request_hash)).fetchone()
            if existing:
                self._stats["coalesced"] += 1
                return {"success": True, "job_id": existing[0], "trace_id": str(existing[2] or ""), "task_id": str(existing[3] or ""), "state": existing[1], "coalesced": True}
            pending = int(con.execute("SELECT COUNT(*) FROM async_jobs WHERE state IN ('queued','running')").fetchone()[0])
            if pending >= self.max_pending:
                return {"success": False, "error": "async job queue limit reached", "retryable": True}
            job_id = uuid.uuid4().hex
            con.execute("INSERT INTO async_jobs(job_id,tenant,action,request_hash,payload_json,state,created_at,updated_at,expires_at,task_id) VALUES(?,?,?,?,?,'queued',?,?,?,?)", (job_id, tenant, action, request_hash, encoded, now, now, now + self.result_ttl_seconds, task_id))
            con.commit()
            self._stats["submitted"] += 1
        trace_id = ""
        if self.debug_traces is not None:
            try:
                trace_id = self.debug_traces.start(kind="async_job", tenant=tenant, action=action, source="async-job")
                self.debug_traces.update(trace_id, request=clean)
                self.debug_traces.link(trace_id, async_job_id=job_id)
                with self._lock, closing(self._connect()) as con:
                    con.execute("UPDATE async_jobs SET trace_id=? WHERE job_id=?", (trace_id, job_id)); con.commit()
            except Exception:
                trace_id = ""
        self._event(job_id)
        delay = max(0.0, min(30.0, float(dispatch_delay_seconds or 0.0)))
        if delay:
            timer = threading.Timer(delay, self._dispatch, args=(job_id,))
            timer.daemon = True
            with self._lock:
                self._delayed_dispatch[job_id] = timer
            timer.start()
        else:
            self._dispatch_background(job_id)
        return {"success": True, "job_id": job_id, "trace_id": trace_id, "task_id": task_id, "state": "queued", "coalesced": False}

    def _row(self, tenant: str, job_id: str) -> sqlite3.Row | None:
        def read() -> sqlite3.Row | None:
            with closing(self._connect()) as con:
                con.row_factory = sqlite3.Row
                return con.execute("SELECT * FROM async_jobs WHERE job_id=? AND tenant=?", (job_id, tenant)).fetchone()
        return retry_busy(read, retries=3)

    def _dispatch(self, job_id: str) -> None:
        if self._shutdown.is_set():
            return
        with self._lock:
            self._delayed_dispatch.pop(job_id, None)
        with self._lock, closing(self._connect()) as con:
            con.row_factory = sqlite3.Row
            row = con.execute("SELECT * FROM async_jobs WHERE job_id=?", (job_id,)).fetchone()
            if not row or row["state"] != "queued" or row["cancel_requested"] or float(row["lease_until"] or 0) > time.time():
                return
            con.execute("UPDATE async_jobs SET lease_until=?,updated_at=? WHERE job_id=? AND state='queued'", (time.time() + self.lease_seconds, time.time(), job_id))
            con.commit()

        def run() -> None:
            try:
                self._execute(job_id)
            except Exception as exc:
                self._release_for_retry(job_id, str(exc))
            finally:
                with self._lock:
                    self._workers.discard(threading.current_thread())

        worker = threading.Thread(target=run, name=f"async-job-{job_id[:8]}", daemon=True)
        with self._lock:
            if self._shutdown.is_set():
                return
            self._workers.add(worker)
        worker.start()

    def _release_for_retry(self, job_id: str, error: str) -> None:
        trace_id = ""
        with self._lock, closing(self._connect()) as con:
            row = con.execute("SELECT attempts,cancel_requested,trace_id FROM async_jobs WHERE job_id=?", (job_id,)).fetchone()
            if not row:
                return
            attempts, cancelled = int(row[0] or 0) + 1, bool(row[1])
            trace_id = str(row[2] or "") if len(row) > 2 and row[2] else ""
            state = "cancelled" if cancelled else "failed" if attempts >= self.max_attempts else "queued"
            con.execute("UPDATE async_jobs SET state=?,attempts=?,lease_until=0,error=?,updated_at=? WHERE job_id=?", (state, attempts, error[:500], time.time(), job_id))
            con.commit()
            if state == "failed": self._stats["failed"] += 1
            if state == "cancelled": self._stats["cancelled"] += 1
        if self.debug_traces is not None and trace_id:
            try:
                self.debug_traces.event(trace_id, "retry" if state == "queued" else state, {"error": error, "attempts": attempts})
                if state in {"failed", "cancelled"}:
                    self.debug_traces.finish(trace_id, state=state, error=error)
            except Exception:
                pass
        self._event(job_id).set()

    def _execute(self, job_id: str) -> dict[str, Any]:
        with self._lock, closing(self._connect()) as con:
            con.row_factory = sqlite3.Row
            row = con.execute("SELECT * FROM async_jobs WHERE job_id=?", (job_id,)).fetchone()
            if not row or row["state"] != "queued" or row["cancel_requested"]:
                return {"success": False, "error": "async job cancelled before execution", "terminal": True}
            con.execute("UPDATE async_jobs SET state='running',attempts=attempts+1,lease_until=?,updated_at=? WHERE job_id=?", (time.time() + self.lease_seconds, time.time(), job_id))
            con.commit()
            tenant, action, payload, trace_id = str(row["tenant"]), str(row["action"]), json.loads(str(row["payload_json"])), str(row["trace_id"] or "")
            task_id = str(row["task_id"] or "") if "task_id" in row.keys() else ""
        if task_id and self.task_store is not None:
            try:
                from .agent_tasks import TaskCheckpoint
                self.task_store.checkpoint(task_id, TaskCheckpoint(phase=f"async_job:{action}", next_action="running"))
            except Exception:
                pass
        if self.debug_traces is not None and trace_id:
            try:
                self.debug_traces.update(trace_id, state="running")
                self.debug_traces.event(trace_id, "running", {"action": action})
            except Exception:
                pass
        observer = DebugTraceObserver(self.debug_traces, trace_id) if self.debug_traces is not None and trace_id else None
        observer_token = set_observer(observer)
        try:
            result = self.executor(action, payload, tenant)
            if not isinstance(result, dict):
                result = {
                    "success": False,
                    "error": "async executor returned a non-object result",
                    "retryable": False,
                }
        except Exception as exc:
            result = {"success": False, "error": str(exc), "retryable": True}
        finally:
            reset_observer(observer_token)
        with self._lock, closing(self._connect()) as con:
            cur_cancel = con.execute("SELECT cancel_requested FROM async_jobs WHERE job_id=?", (job_id,)).fetchone()
            cancelled = bool(cur_cancel[0]) if cur_cancel else False
            if cancelled:
                con.execute("UPDATE async_jobs SET state='cancelled',lease_until=0,updated_at=? WHERE job_id=?", (time.time(), job_id))
                self._stats["cancelled"] += 1
                final = {"success": False, "error": "async job cancelled", "terminal": True, "retryable": False}
                if task_id and self.task_store is not None:
                    try:
                        self.task_store.fail(task_id, reason="async job cancelled")
                    except Exception:
                        pass
            elif result.get("success"):
                artifact_id = ""
                try: artifact_id = str(self.artifacts.put(json_dumps(result, ensure_ascii=False, separators=(",", ":")), tenant, "async-job"))
                except Exception: pass
                con.execute("UPDATE async_jobs SET state='done',result_json=?,artifact_id=?,lease_until=0,updated_at=? WHERE job_id=?", (json_dumps(result, ensure_ascii=False, separators=(",", ":")), artifact_id, time.time(), job_id))
                self._stats["completed"] += 1
                final = result
                if task_id and self.task_store is not None:
                    try:
                        from .agent_tasks import TaskCheckpoint
                        self.task_store.checkpoint(
                            task_id,
                            TaskCheckpoint(
                                phase=f"async_job:{action}:done",
                                next_action="complete",
                                evidence_ids=(artifact_id,) if artifact_id else (),
                            ),
                        )
                    except Exception:
                        pass
                if task_id and self.verification_store is not None:
                    try:
                        from .agent_verification import VerificationReceipt
                        rcpt = VerificationReceipt.create(
                            task_id=task_id,
                            criterion=f"async_job:{action}",
                            passed=True,
                            evidence_id=artifact_id,
                            details={"job_id": job_id, "action": action},
                        )
                        self.verification_store.record(rcpt)
                    except Exception:
                        pass
            else:
                con.row_factory = sqlite3.Row
                cur_row = con.execute("SELECT attempts FROM async_jobs WHERE job_id=?", (job_id,)).fetchone()
                attempts = int(cur_row["attempts"] if cur_row else 1)
                if attempts < self.max_attempts and bool(result.get("retryable", True)):
                    con.execute("UPDATE async_jobs SET state='queued',result_json=?,error=?,lease_until=0,updated_at=? WHERE job_id=?", (json_dumps(result, ensure_ascii=False, separators=(",", ":")), str(result.get("error", "async job failed"))[:500], time.time(), job_id))
                    final = result
                else:
                    con.execute("UPDATE async_jobs SET state='failed',result_json=?,error=?,lease_until=0,updated_at=? WHERE job_id=?", (json_dumps(result, ensure_ascii=False, separators=(",", ":")), str(result.get("error", "async job failed"))[:500], time.time(), job_id))
                    self._stats["failed"] += 1
                    final = result
                    if task_id and self.task_store is not None:
                        try:
                            self.task_store.fail(task_id, reason=str(result.get("error", "async job failed")))
                        except Exception:
                            pass
            con.commit()
        if self.debug_traces is not None and trace_id:
            try:
                self.debug_traces.finish(trace_id, state="done" if final.get("success") else "failed", response=final if final.get("success") else None, error=str(final.get("error", "")))
            except Exception:
                pass
        self._event(job_id).set()
        return final

    def status(self, tenant: str, job_id: str) -> dict[str, Any]:
        row = self._row(tenant, job_id)
        if not row: return {"success": False, "error": "async job not found", "terminal": True, "retryable": False}
        if float(row["expires_at"]) <= time.time() and row["state"] in {"done", "failed", "cancelled"}:
            return {"success": False, "job_id": job_id, "state": "expired", "terminal": True, "retryable": False}
        result = {"success": True, "job_id": job_id, "state": row["state"], "attempts": int(row["attempts"]), "cancel_requested": bool(row["cancel_requested"]), "updated_at": float(row["updated_at"]), "retryable": row["state"] in {"queued", "running"}}
        if "trace_id" in row.keys(): result["trace_id"] = str(row["trace_id"] or "")
        return result

    def wait(self, tenant: str, job_id: str, timeout_seconds: float) -> dict[str, Any]:
        started = time.perf_counter()
        timeout = max(1.0, min(self.wait_max_seconds, float(timeout_seconds or self.wait_max_seconds)))
        status = self.status(tenant, job_id)
        if status.get("success") and status.get("state") in {"queued", "running"}: self._event(job_id).wait(timeout)
        result = self.status(tenant, job_id); result["wait_timeout_seconds"] = timeout
        if self.telemetry is not None:
            try:
                elapsed_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
                self.telemetry.record(
                    event_type="coordination", action="async_wait", tenant=tenant,
                    success=bool(result.get("success")), duration_ms=elapsed_ms,
                    wait_count=1, wait_duration_ms=elapsed_ms,
                )
            except Exception:
                pass
        return result

    def result(self, tenant: str, job_id: str) -> dict[str, Any]:
        row = self._row(tenant, job_id)
        if not row: return {"success": False, "error": "async job not found", "terminal": True, "retryable": False}
        if row["state"] != "done":
            return {"success": False, "job_id": job_id, "state": row["state"], "error": str(row["error"] or "async job is not complete"), "terminal": row["state"] in {"failed", "cancelled", "expired"}, "retryable": row["state"] in {"queued", "running"}}
        try: value = json.loads(str(row["result_json"]))
        except Exception: value = {"success": True}
        return {"success": True, "job_id": job_id, "state": "done", "artifact_id": str(row["artifact_id"]), "result": value}

    def cancel(self, tenant: str, job_id: str) -> dict[str, Any]:
        with self._lock:
            delayed = self._delayed_dispatch.pop(job_id, None)
            if delayed is not None:
                delayed.cancel()
        with self._lock, closing(self._connect()) as con:
            row = con.execute("SELECT state,trace_id FROM async_jobs WHERE job_id=? AND tenant=?", (job_id, tenant)).fetchone()
            if not row: return {"success": False, "error": "async job not found", "terminal": True, "retryable": False}
            state = str(row[0])
            trace_id = str(row[1] or "")
            if state in {"done", "failed", "cancelled", "expired"}: return {"success": False, "job_id": job_id, "state": state, "error": "async job is already terminal", "terminal": True, "retryable": False}
            con.execute("UPDATE async_jobs SET cancel_requested=1,state=CASE WHEN state='queued' THEN 'cancelled' ELSE state END,updated_at=? WHERE job_id=?", (time.time(), job_id)); con.commit()
        self._stats["cancelled"] += 1; self._event(job_id).set()
        if self.debug_traces is not None and trace_id and state == "queued":
            try: self.debug_traces.finish(trace_id, state="cancelled", error="async job cancelled before execution")
            except Exception: pass
        return {"success": True, "job_id": job_id, "state": "cancelled" if state == "queued" else "running", "cancel_requested": True}

    def recover(self) -> int:
        if self._shutdown.is_set():
            return 0
        with self._lock, closing(self._connect()) as con:
            rows = con.execute("SELECT job_id,state,attempts,cancel_requested,trace_id FROM async_jobs WHERE state IN ('queued','running')").fetchall(); ids: list[tuple[str, str]] = []
            for job_id, state, attempts, cancelled, trace_id in rows:
                if cancelled: con.execute("UPDATE async_jobs SET state='cancelled',lease_until=0,updated_at=? WHERE job_id=?", (time.time(), job_id))
                elif int(attempts or 0) >= self.max_attempts and state == "running": con.execute("UPDATE async_jobs SET state='failed',lease_until=0,error='async job interrupted too many times',updated_at=? WHERE job_id=?", (time.time(), job_id))
                else:
                    con.execute("UPDATE async_jobs SET state='queued',lease_until=0,updated_at=? WHERE job_id=?", (time.time(), job_id)); ids.append((str(job_id), str(trace_id or "")))
            con.commit()
        for job_id, trace_id in ids:
            if self.debug_traces is not None and trace_id:
                try:
                    self.debug_traces.update(trace_id, state="queued")
                    self.debug_traces.event(trace_id, "recovered", {"job_id": job_id})
                except Exception:
                    pass
            self._event(job_id); self._dispatch(job_id)
        self._stats["recovered"] += len(ids); return len(ids)

    def tick(self) -> None:
        if self._shutdown.is_set():
            return
        now = time.time()
        with self._lock, closing(self._connect()) as con:
            expired = con.execute("UPDATE async_jobs SET state='expired',updated_at=? WHERE state IN ('done','failed','cancelled') AND expires_at<?", (now, now)).rowcount
            # Periodic tombstone purge: evict expired jobs whose retention period has lapsed
            con.execute("DELETE FROM async_jobs WHERE state='expired' AND updated_at<?", (now - self.result_ttl_seconds,))
            stuck = con.execute("SELECT job_id, attempts, cancel_requested, task_id FROM async_jobs WHERE state='running' AND lease_until<?", (now,)).fetchall()
            for s_id, s_att, s_canc, s_tid in stuck:
                s_attempts = int(s_att or 0)
                if s_canc or s_attempts >= self.max_attempts:
                    con.execute("UPDATE async_jobs SET state='failed',lease_until=0,error='async job execution lease expired',updated_at=? WHERE job_id=?", (now, str(s_id)))
                    self._stats["failed"] += 1
                    if s_tid and self.task_store is not None:
                        try:
                            self.task_store.fail(str(s_tid), reason="async job execution lease expired")
                        except Exception:
                            pass
                else:
                    con.execute("UPDATE async_jobs SET state='queued',lease_until=0,updated_at=? WHERE job_id=?", (now, str(s_id)))
            rows = con.execute("SELECT job_id FROM async_jobs WHERE state='queued' AND lease_until<?", (now,)).fetchall()
            delayed_ids = set(self._delayed_dispatch)
            active_rows = con.execute("SELECT job_id FROM async_jobs WHERE state IN ('queued','running')").fetchall()
            active_ids = {str(r[0]) for r in active_rows}
            for jid in list(self._events.keys()):
                if jid not in active_ids:
                    self._events.pop(jid, None)
            con.commit()
        self._stats["expired"] += int(expired or 0)
        for (job_id,) in rows[:self.max_pending]:
            if str(job_id) not in delayed_ids:
                self._dispatch(str(job_id))

    def __enter__(self) -> "AsyncJobManager":
        return self

    def __exit__(self, _exc_type: Any, _exc: Any, _tb: Any) -> None:
        self.close()

    def close(self) -> None:
        if self._shutdown.is_set():
            return
        self._shutdown.set()
        with self._lock:
            waiters = list(self._events.values())
            workers = list(self._workers)
            dispatchers = list(self._dispatchers)
            delayed = list(self._delayed_dispatch.values())
            self._delayed_dispatch.clear()
        for timer in delayed:
            timer.cancel()
        for event in waiters:
            event.set()
        deadline = time.monotonic() + 1.5
        current = threading.current_thread()
        for worker in dispatchers + workers:
            if worker is current or not worker.is_alive():
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            worker.join(timeout=remaining)
        with self._lock:
            self._dispatchers = {thread for thread in self._dispatchers if thread.is_alive()}
            self._workers = {thread for thread in self._workers if thread.is_alive()}

    def stats(self) -> dict[str, Any]:
        def read() -> dict[str, int]:
            with closing(self._connect()) as con:
                return {str(state): int(count) for state, count in con.execute("SELECT state,COUNT(*) FROM async_jobs GROUP BY state")}
        counts = retry_busy(read, retries=3)
        with self._lock:
            current_stats = dict(self._stats)
        return {"enabled": self.enabled, "counts": counts, "wait_max_seconds": self.wait_max_seconds, **current_stats}
