from __future__ import annotations

from .json_utils import dumps as json_dumps

import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any, Callable

from .cache import stable_hash
from .debug_traces import DebugTraceObserver
from .sqlite_support import connect_sqlite, initialize_wal, retry_busy
from .trace_context import reset_observer, set_observer
from .process_utils import terminate_tree


class AsyncJobManager:
    """Durable, tenant-scoped orchestration whose model calls use the scheduler."""

    ACTIONS = {"delegate", "reason", "review", "review_diff", "second_opinion", "compress", "route", "batch", "speculative_lint"}
    INFERENCE_ACTIONS = frozenset(ACTIONS - {"speculative_lint"})
    # Command-backed actions stay out until they have an explicit T07 replay contract.
    RECOVERY_REPLAY_SAFE_ACTIONS = frozenset(
        {"delegate", "reason", "review", "review_diff", "second_opinion", "compress", "route", "batch"}
    )
    TERMINAL_STATES = frozenset({"done", "failed", "cancelled", "expired", "outcome_unknown"})

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
        artifact_ttl_seconds = getattr(artifacts, "ttl_seconds", None)
        if artifact_ttl_seconds is not None and float(artifact_ttl_seconds) < self.result_ttl_seconds:
            raise ValueError("async_jobs.result_ttl_seconds must not exceed artifact store ttl_seconds")
        self.max_attempts = max(1, int(cfg.get("max_attempts", 2)))
        self.stats_max_items = max(1, min(256, int(cfg.get("stats_max_items", 32))))
        self.scheduler, self.artifacts, self.executor, self.debug_traces = scheduler, artifacts, executor, debug_traces
        self.task_store = task_store
        self.verification_store = verification_store
        self.telemetry = telemetry
        self.path = Path(config["server"]["state_dir"]) / "async_jobs.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._mode_transition_lock = threading.RLock()
        self._events: dict[str, threading.Event] = {}
        self._delayed_dispatch: dict[str, threading.Timer] = {}
        self._dispatchers: set[threading.Thread] = set()
        self._workers: set[threading.Thread] = set()
        self._processes: dict[str, list[Any]] = {}
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
                    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_async_jobs_request_id ON async_jobs(tenant, json_extract(payload_json, '$.request_id')) WHERE json_valid(payload_json) AND json_type(payload_json, '$.request_id')='text' AND json_extract(payload_json, '$.request_id')<>''")
                    con.commit()
            retry_busy(_setup, retries=5, base_delay_seconds=0.02)
            self._initialized = True

    @staticmethod
    def _safe_payload(payload: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "task", "context", "candidate", "complexity", "max_tokens", "tasks", "task_id", "root", "paths", "command",
            "instructions", "base", "staged", "mode", "diff_tokens", "consensus", "_async_job", "request_id",
        }
        return {key: payload[key] for key in allowed if key in payload}

    @staticmethod
    def _request_id(payload: Any) -> str:
        try:
            value = json.loads(payload).get("request_id", "") if isinstance(payload, str) else payload.get("request_id", "")
        except Exception:
            return ""
        return value.strip() if isinstance(value, str) else ""

    def _can_replay_after_interruption(self, action: Any, payload: Any, attempts: int) -> bool:
        normalized_action = str(action or "").strip().lower().replace("-", "_")
        attempt_count = int(attempts or 0)
        return (
            normalized_action in self.RECOVERY_REPLAY_SAFE_ACTIONS
            and bool(self._request_id(payload))
            and 0 < attempt_count < self.max_attempts
        )

    def _result_artifact_available(self, artifact_id: str, tenant: str) -> bool:
        artifact_id = str(artifact_id or "").strip()
        if not artifact_id:
            return False
        getter = getattr(self.artifacts, "get", None)
        if not callable(getter):
            return True
        try:
            artifact = getter(artifact_id, offset=0, max_chars=256, tenant=tenant)
        except Exception:
            return False
        return isinstance(artifact, dict) and bool(artifact.get("success"))

    def _event(self, job_id: str) -> threading.Event:
        with self._lock:
            return self._events.setdefault(job_id, threading.Event())

    @staticmethod
    def _admission(state: str, reason: str, *, retryable: bool, queue_age_ms: float = 0.0) -> dict[str, Any]:
        return {
            "state": state, "reason": reason, "queue_age_ms": max(0.0, round(float(queue_age_ms), 1)),
            "retryable": bool(retryable),
        }

    def _resource_admission(self) -> dict[str, Any]:
        provider = getattr(self.scheduler, "resource_status", None) or getattr(self.scheduler, "_resource_status", None)
        resource: dict[str, Any] = {}
        if callable(provider):
            try:
                value = provider()
                if isinstance(value, dict):
                    resource = value
            except Exception:
                pass
        pressure = str(resource.get("pressure_level", "nominal") or "nominal").lower()
        try:
            factor = max(0.0, min(1.0, float(resource.get("context_budget_factor", 1.0))))
        except (TypeError, ValueError, OverflowError):
            factor = 1.0
        if pressure == "critical" or (pressure == "high" and bool(resource.get("throttle_background", False))):
            return {**self._admission("rejected", "resource_pressure", retryable=True), "pressure_level": pressure, "context_budget_factor": factor}
        if pressure in {"moderate", "high"} or factor < 1.0:
            return {**self._admission("degraded", "resource_pressure", retryable=False), "pressure_level": pressure, "context_budget_factor": factor}
        return self._admission("accepted", "capacity_available", retryable=False)

    @staticmethod
    def _operational_mode_api() -> tuple[Callable[..., Any] | None, Callable[..., Any] | None]:
        loader = globals().get("load_operational_mode")
        gate_error = globals().get("operational_mode_gate_error")
        if callable(loader):
            return loader, gate_error if callable(gate_error) else None
        try:
            from importlib import import_module

            module = import_module(".operational_mode", package=__package__)
        except Exception:
            return None, None
        loader = getattr(module, "load_operational_mode", None)
        gate_error = getattr(module, "operational_mode_gate_error", None)
        return (
            loader if callable(loader) else None,
            gate_error if callable(gate_error) else None,
        )

    def _operational_mode_snapshot(self) -> dict[str, Any]:
        loader, gate_error = self._operational_mode_api()
        try:
            if not callable(loader):
                raise RuntimeError("operational mode loader is not available")
            snapshot = loader(self.path.parent)
        except Exception as exc:
            return self._normalize_operational_mode_snapshot(
                None, gate_error, error=str(exc)
            )
        return self._normalize_operational_mode_snapshot(snapshot, gate_error)

    @staticmethod
    def _normalize_operational_mode_snapshot(
        snapshot: Any,
        gate_error: Callable[..., Any] | None,
        *,
        error: str = "",
    ) -> dict[str, Any]:
        try:
            mode = str(getattr(snapshot, "mode", "") or "").strip().lower()
            revision = max(0, int(getattr(snapshot, "revision", 0) or 0))
            degraded = bool(getattr(snapshot, "degraded", False))
            error = error or str(getattr(snapshot, "error", "") or "")[:240]
        except Exception as exc:
            mode, revision, degraded = "maintenance", -1, True
            error = str(exc)[:240]
        if mode not in {"active", "gaming", "maintenance"}:
            mode, degraded = "maintenance", True
        if degraded:
            mode = "maintenance"
        return {
            "mode": mode,
            "revision": revision,
            "degraded": degraded,
            "error": error,
            "snapshot": snapshot,
            "gate_error": gate_error,
        }

    def on_operational_mode_changed(self, snapshot: Any) -> None:
        """Request cooperative cancellation for jobs blocked by the new mode."""
        _, gate_error = self._operational_mode_api()
        normalized = self._normalize_operational_mode_snapshot(snapshot, gate_error)
        with self._mode_transition_lock:
            self._cancel_jobs_blocked_by_mode(normalized)

    @contextmanager
    def operational_mode_change_guard(self):
        """Serialize mode persistence against async executor admission.

        The mode setter must hold this guard while it persists the new snapshot
        and calls ``on_operational_mode_changed`` with that snapshot.
        """
        with self._mode_transition_lock:
            yield

    @classmethod
    def _mode_blocked_actions(cls, snapshot: dict[str, Any]) -> frozenset[str]:
        mode = str(snapshot.get("mode", "maintenance"))
        if snapshot.get("degraded") or mode == "maintenance":
            return frozenset(cls.ACTIONS)
        if mode == "gaming":
            return cls.INFERENCE_ACTIONS
        return frozenset()

    def _mode_blocked_result(self, action: str, snapshot: dict[str, Any]) -> dict[str, Any] | None:
        if action not in self._mode_blocked_actions(snapshot):
            return None
        gate_error = snapshot.get("gate_error")
        raw_snapshot = snapshot.get("snapshot")
        response = gate_error(raw_snapshot) if callable(gate_error) and raw_snapshot is not None else None
        if not isinstance(response, dict):
            mode = str(snapshot.get("mode", "maintenance"))
            response = {
                "success": False,
                "mode": mode,
                "error": f"hub paused: {mode} mode active",
                "terminal": True,
                "retryable": False,
            }
        admission = self._admission("rejected", "operational_mode_blocked", retryable=False)
        return {
            **response,
            "success": False,
            "state": "rejected",
            "code": str(response.get("error_code") or "operational_mode_blocked"),
            "status_code": 423,
            "operational_mode": snapshot["mode"],
            "operational_mode_revision": snapshot["revision"],
            "operational_mode_degraded": snapshot["degraded"],
            "admission": admission,
            "admission_state": admission["state"],
            "terminal": True,
            "retryable": False,
            "coalesced": False,
        }

    def _cancel_jobs_blocked_by_mode(self, snapshot: dict[str, Any]) -> None:
        blocked = self._mode_blocked_actions(snapshot)
        if not blocked or self._shutdown.is_set():
            return
        with self._lock, closing(self._connect()) as con:
            rows = con.execute(
                "SELECT job_id,tenant,action FROM async_jobs "
                "WHERE state IN ('queued','running') AND cancel_requested=0"
            ).fetchall()
        for job_id, tenant, action in rows:
            if str(action) in blocked:
                # Reuse the regular cancellation path, including bounded process cleanup.
                self.cancel(str(tenant), str(job_id))

    def register_process(self, job_id: str, process_or_pid: Any) -> None:
        """Register child process so cancellation/close can terminate its process tree."""
        with self._lock:
            processes = self._processes.setdefault(str(job_id), [])
            if not any(existing is process_or_pid for existing in processes):
                processes.append(process_or_pid)

    def _cleanup_processes(self, job_id: str) -> None:
        with self._lock:
            processes = list(self._processes.pop(str(job_id), []))
        for process in processes:
            if hasattr(process, "poll") and hasattr(process, "terminate"):
                try:
                    if process.poll() is None:
                        process.terminate()
                        process.wait(timeout=1.0)
                    continue
                except Exception:
                    try:
                        process.kill()
                        process.wait(timeout=1.0)
                    except Exception:
                        pass
                    continue
            try:
                pid = int(getattr(process, "pid", process))
            except (TypeError, ValueError):
                continue
            if pid > 0 and pid != os.getpid():
                try:
                    terminate_tree(pid, grace_seconds=1.0)
                except Exception:
                    pass

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
        if bool(payload.get("conversation", False)):
            return {"success": False, "error": "conversations require delivery=sync", "terminal": True, "retryable": False}
        clean = self._safe_payload(payload)
        request_id = self._request_id(clean)
        if request_id:
            clean["request_id"] = request_id
        else:
            clean.pop("request_id", None)
        encoded = json_dumps(clean, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > 2_000_000:
            return {"success": False, "error": "async task payload exceeds 2MB", "terminal": True, "retryable": False}
        request_hash = stable_hash({"tenant": tenant, "action": action, "payload": clean})
        task_id = str(clean.get("task_id") or "")
        now = time.time()
        mode_snapshot: dict[str, Any] | None = None
        mode_rejection: dict[str, Any] | None = None
        with self._lock, closing(self._connect()) as con:
            if request_id:
                identified = con.execute(
                    "SELECT job_id,action,request_hash,state,trace_id,task_id,expires_at,created_at,error,artifact_id FROM async_jobs WHERE tenant=? AND json_valid(payload_json) AND json_extract(payload_json,'$.request_id')=? ORDER BY created_at LIMIT 1",
                    (tenant, request_id),
                ).fetchone()
                if identified:
                    job_id, old_action, old_hash, old_state, trace_id, old_task_id, expires_at, created_at, old_error, artifact_id = identified
                    if str(old_action) != action or str(old_hash) != request_hash:
                        return {"success": False, "job_id": str(job_id), "state": "conflict", "artifact_id": str(artifact_id or ""), "expires_at": float(expires_at), "error": "request_id already used with different operation or payload", "conflict": True, "terminal": True, "retryable": False}
                    state = str(old_state)
                    if state in self.TERMINAL_STATES and float(expires_at) <= now:
                        state = "expired"
                    if state == "done" and not self._result_artifact_available(str(artifact_id or ""), tenant):
                        state = "outcome_unknown"
                        old_error = "async job result artifact unavailable"
                    age_ms = max(0.0, (now - float(created_at)) * 1000.0)
                    admission = self._admission("coalesced", "idempotent_request_replay", retryable=False, queue_age_ms=age_ms)
                    if state == "expired":
                        return {"success": False, "job_id": str(job_id), "state": state, "artifact_id": str(artifact_id or ""), "expires_at": float(expires_at), "error": "async job result expired", "terminal": True, "retryable": False}
                    if state == "outcome_unknown":
                        return {"success": False, "job_id": str(job_id), "state": state, "artifact_id": str(artifact_id or ""), "expires_at": float(expires_at), "error": str(old_error or "async job outcome unknown"), "outcome_unknown": True, "terminal": True, "retryable": False}
                    self._stats["coalesced"] += 1
                    return {"success": True, "job_id": str(job_id), "trace_id": str(trace_id or ""), "task_id": str(old_task_id or ""), "state": state, "artifact_id": str(artifact_id or ""), "expires_at": float(expires_at), "coalesced": state in {"queued", "running"}, "idempotent_replay": True, "admission": admission, "admission_state": admission["state"]}
            existing = con.execute("SELECT job_id,state,trace_id,task_id,expires_at,artifact_id FROM async_jobs WHERE tenant=? AND request_hash=? AND state IN ('queued','running')", (tenant, request_hash)).fetchone()
            if existing:
                self._stats["coalesced"] += 1
                age_ms = max(0.0, (now - float(con.execute("SELECT created_at FROM async_jobs WHERE job_id=?", (existing[0],)).fetchone()[0])) * 1000.0)
                admission = self._admission("coalesced", "duplicate_active_job", retryable=False, queue_age_ms=age_ms)
                return {"success": True, "job_id": existing[0], "trace_id": str(existing[2] or ""), "task_id": str(existing[3] or ""), "state": existing[1], "artifact_id": str(existing[5] or ""), "expires_at": float(existing[4]), "coalesced": True, "admission": admission, "admission_state": admission["state"]}
            mode_snapshot = self._operational_mode_snapshot()
            mode_rejection = self._mode_blocked_result(action, mode_snapshot)
            if mode_rejection is None:
                admission = self._resource_admission()
                if admission["state"] == "rejected":
                    return {"success": False, "state": "rejected", "error": "async job admission rejected by resource pressure", "admission": admission, "admission_state": admission["state"], "terminal": False, "retryable": True, "coalesced": False}
                pending = int(con.execute("SELECT COUNT(*) FROM async_jobs WHERE state IN ('queued','running')").fetchone()[0])
                if pending >= self.max_pending:
                    admission = self._admission("rejected", "queue_limit", retryable=True)
                    return {"success": False, "state": "rejected", "error": "async job queue limit reached", "admission": admission, "admission_state": admission["state"], "terminal": False, "retryable": True, "coalesced": False}
                job_id = uuid.uuid4().hex
                expires_at = now + self.result_ttl_seconds
                con.execute("INSERT INTO async_jobs(job_id,tenant,action,request_hash,payload_json,state,created_at,updated_at,expires_at,task_id) VALUES(?,?,?,?,?,'queued',?,?,?,?)", (job_id, tenant, action, request_hash, encoded, now, now, expires_at, task_id))
                con.commit()
                self._stats["submitted"] += 1
        if mode_rejection is not None:
            self._cancel_jobs_blocked_by_mode(mode_snapshot or {})
            return mode_rejection
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
        return {"success": True, "job_id": job_id, "trace_id": trace_id, "task_id": task_id, "state": "queued", "artifact_id": "", "expires_at": expires_at, "coalesced": False, "admission": admission, "admission_state": admission["state"]}

    def _row(self, tenant: str, job_id: str) -> sqlite3.Row | None:
        def read() -> sqlite3.Row | None:
            with closing(self._connect()) as con:
                con.row_factory = sqlite3.Row
                return con.execute("SELECT * FROM async_jobs WHERE job_id=? AND tenant=?", (job_id, tenant)).fetchone()
        return retry_busy(read, retries=3)

    def _dispatch(self, job_id: str) -> None:
        if self._shutdown.is_set():
            return
        self._cancel_jobs_blocked_by_mode(self._operational_mode_snapshot())
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
        already_terminal = False
        with self._lock, closing(self._connect()) as con:
            row = con.execute(
                "SELECT state,attempts,cancel_requested,trace_id,payload_json,action FROM async_jobs WHERE job_id=?",
                (job_id,),
            ).fetchone()
            if not row:
                return
            current_state, attempts, cancelled = str(row[0] or ""), int(row[1] or 0), bool(row[2])
            trace_id = str(row[3] or "")
            already_terminal = current_state in self.TERMINAL_STATES
            if already_terminal:
                state, detail = current_state, ""
            elif cancelled:
                state, detail = "cancelled", error[:500]
            elif current_state == "queued" and attempts == 0:
                # No executor attempt began; keep this dispatch retry free.
                state, detail = "queued", error[:500]
            elif self._can_replay_after_interruption(row[5], row[4], attempts):
                state, detail = "queued", error[:500]
            else:
                state = "outcome_unknown"
                detail = f"async job outcome unknown after interrupted attempt: {error}"[:500]
            if not already_terminal:
                con.execute(
                    "UPDATE async_jobs SET state=?,attempts=?,lease_until=0,error=?,updated_at=? WHERE job_id=?",
                    (state, attempts, detail, time.time(), job_id),
                )
                con.commit()
                if state == "cancelled":
                    self._stats["cancelled"] += 1
        if not already_terminal and self.debug_traces is not None and trace_id:
            try:
                self.debug_traces.event(trace_id, "retry" if state == "queued" else state, {"error": detail, "attempts": attempts})
                if state in {"cancelled", "outcome_unknown"}:
                    self.debug_traces.finish(trace_id, state=state, error=detail)
            except Exception:
                pass
        self._event(job_id).set()

    def _execute(self, job_id: str) -> dict[str, Any]:
        self._cancel_jobs_blocked_by_mode(self._operational_mode_snapshot())
        with self._lock, closing(self._connect()) as con:
            con.row_factory = sqlite3.Row
            row = con.execute("SELECT * FROM async_jobs WHERE job_id=?", (job_id,)).fetchone()
            if not row:
                return {"success": False, "error": "async job cancelled before execution (job not found)", "terminal": True, "retryable": False}
            current_state = str(row["state"])
            if current_state != "queued" or row["cancel_requested"]:
                cancelled = bool(row["cancel_requested"]) or current_state == "cancelled"
                state = "cancelled" if cancelled else current_state
                return {"success": False, "job_id": job_id, "state": state, "error": "async job cancelled before execution" if cancelled else "async job is not queued", "outcome_unknown": state == "outcome_unknown", "terminal": state in self.TERMINAL_STATES, "retryable": state in {"queued", "running"}, "admission": self._admission("accepted", "capacity_available", retryable=False)}
            con.execute("UPDATE async_jobs SET state='running',attempts=attempts+1,lease_until=?,updated_at=? WHERE job_id=?", (time.time() + self.lease_seconds, time.time(), job_id))
            con.commit()
            tenant, action, payload, trace_id = str(row["tenant"]), str(row["action"]), json.loads(str(row["payload_json"])), str(row["trace_id"] or "")
            request_id = self._request_id(payload)
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
            result = self._invoke_executor_if_allowed(job_id, action, payload, tenant)
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
            self._cleanup_processes(job_id)
        if result.get("success") and str(result.get("state", "")) in {"queued", "running"}:
            result = {"success": False, "error": "async executor returned non-terminal state", "retryable": True}
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
                try:
                    stored_id = self.artifacts.put(json_dumps(result, ensure_ascii=False, separators=(",", ":")), tenant, "async-job")
                    artifact_id = str(stored_id or "").strip()
                except Exception:
                    pass
                if not self._result_artifact_available(artifact_id, tenant):
                    final = {"success": False, "state": "outcome_unknown", "outcome_unknown": True, "error": "async job result artifact unavailable", "terminal": True, "retryable": False}
                    con.execute("UPDATE async_jobs SET state='outcome_unknown',result_json=?,artifact_id='',error=?,lease_until=0,updated_at=? WHERE job_id=?", (json_dumps(final, ensure_ascii=False, separators=(",", ":")), final["error"], time.time(), job_id))
                else:
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
                                    evidence_ids=(artifact_id,),
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
                retryable = bool(result.get("retryable", True))
                if retryable and self._can_replay_after_interruption(action, payload, attempts):
                    con.execute("UPDATE async_jobs SET state='queued',result_json=?,error=?,lease_until=0,updated_at=? WHERE job_id=?", (json_dumps(result, ensure_ascii=False, separators=(",", ":")), str(result.get("error", "async job failed"))[:500], time.time(), job_id))
                    final = result
                elif retryable:
                    detail = str(result.get("error", "async job interrupted without a durable outcome"))[:400]
                    final = {"success": False, "state": "outcome_unknown", "outcome_unknown": True, "error": f"async job outcome unknown: {detail}", "terminal": True, "retryable": False}
                    con.execute("UPDATE async_jobs SET state='outcome_unknown',result_json=?,error=?,lease_until=0,updated_at=? WHERE job_id=?", (json_dumps(final, ensure_ascii=False, separators=(",", ":")), final["error"][:500], time.time(), job_id))
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
                self.debug_traces.finish(trace_id, state=str(final.get("state") or ("done" if final.get("success") else "failed")), response=final if final.get("success") else None, error=str(final.get("error", "")))
            except Exception:
                pass
        self._event(job_id).set()
        return final

    def _invoke_executor_if_allowed(
        self, job_id: str, action: str, payload: dict[str, Any], tenant: str
    ) -> dict[str, Any]:
        """Recheck mode and cancellation at the last async boundary before dispatch."""
        with self._mode_transition_lock:
            snapshot = self._operational_mode_snapshot()
            blocked = self._mode_blocked_actions(snapshot)
            if action in blocked:
                self._cancel_jobs_blocked_by_mode(snapshot)
                return {
                    "success": False,
                    "error": "async job cancelled before executor start",
                    "terminal": True,
                    "retryable": False,
                }
            with self._lock, closing(self._connect()) as con:
                row = con.execute(
                    "SELECT state,cancel_requested FROM async_jobs WHERE job_id=?",
                    (job_id,),
                ).fetchone()
                if not row or str(row[0]) != "running" or bool(row[1]):
                    return {
                        "success": False,
                        "error": "async job cancelled before executor start",
                        "terminal": True,
                        "retryable": False,
                    }
        return self.executor(action, payload, tenant)

    def status(self, tenant: str, job_id: str) -> dict[str, Any]:
        self._cancel_jobs_blocked_by_mode(self._operational_mode_snapshot())
        row = self._row(tenant, job_id)
        if not row: return {"success": False, "error": "async job not found", "terminal": True, "retryable": False}
        if float(row["expires_at"]) <= time.time() and row["state"] in self.TERMINAL_STATES:
            return {"success": False, "job_id": job_id, "state": "expired", "artifact_id": str(row["artifact_id"] or ""), "expires_at": float(row["expires_at"]), "terminal": True, "retryable": False}
        state = str(row["state"])
        artifact_unavailable = state == "done" and not self._result_artifact_available(str(row["artifact_id"] or ""), tenant)
        if artifact_unavailable:
            state = "outcome_unknown"
        result = {
            "success": True,
            "job_id": job_id,
            "state": state,
            "artifact_id": str(row["artifact_id"] or ""),
            "expires_at": float(row["expires_at"]),
            "outcome_unknown": state == "outcome_unknown",
            "attempts": int(row["attempts"]),
            "cancel_requested": bool(row["cancel_requested"]),
            "updated_at": float(row["updated_at"]),
            "queue_age_ms": max(0.0, (time.time() - float(row["created_at"])) * 1000.0),
            "in_progress": state in {"queued", "running"},
            "terminal": state in self.TERMINAL_STATES,
            "retryable": state in {"queued", "running"},
            "next_action": "wait_or_result" if state in {"queued", "running"} else "inspect_result",
            "admission": self._admission("accepted", "capacity_available", retryable=False, queue_age_ms=(time.time() - float(row["created_at"])) * 1000.0),
        }
        if artifact_unavailable:
            result["error"] = "async job result artifact unavailable"
        elif state == "outcome_unknown":
            result["error"] = str(row["error"] or "async job outcome unknown")
        result["admission_state"] = result["admission"]["state"]
        if "trace_id" in row.keys(): result["trace_id"] = str(row["trace_id"] or "")
        return result

    def wait(self, tenant: str, job_id: str, timeout_seconds: float) -> dict[str, Any]:
        started = time.perf_counter()
        requested_timeout = self.wait_max_seconds if timeout_seconds is None else float(timeout_seconds)
        timeout = max(0.0, min(self.wait_max_seconds, requested_timeout))
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
        self._cancel_jobs_blocked_by_mode(self._operational_mode_snapshot())
        row = self._row(tenant, job_id)
        if not row: return {"success": False, "error": "async job not found", "terminal": True, "retryable": False}
        state = str(row["state"])
        if state == "expired" or (float(row["expires_at"]) <= time.time() and state in self.TERMINAL_STATES):
            return {"success": False, "job_id": job_id, "state": "expired", "artifact_id": str(row["artifact_id"] or ""), "expires_at": float(row["expires_at"]), "error": "async job result expired", "terminal": True, "retryable": False}
        if row["state"] != "done":
            return {"success": False, "job_id": job_id, "state": state, "artifact_id": str(row["artifact_id"] or ""), "expires_at": float(row["expires_at"]), "error": str(row["error"] or "async job is not complete"), "outcome_unknown": state == "outcome_unknown", "terminal": state in self.TERMINAL_STATES, "retryable": state in {"queued", "running"}}
        artifact_id = str(row["artifact_id"] or "").strip()
        if not self._result_artifact_available(artifact_id, tenant):
            return {"success": False, "job_id": job_id, "state": "outcome_unknown", "artifact_id": artifact_id, "expires_at": float(row["expires_at"]), "error": "async job result artifact unavailable", "outcome_unknown": True, "terminal": True, "retryable": False}
        try:
            value = json.loads(str(row["result_json"]))
        except Exception:
            return {"success": False, "job_id": job_id, "state": "outcome_unknown", "artifact_id": artifact_id, "expires_at": float(row["expires_at"]), "error": "async job result payload unavailable", "outcome_unknown": True, "terminal": True, "retryable": False}
        return {"success": True, "job_id": job_id, "state": "done", "artifact_id": artifact_id, "expires_at": float(row["expires_at"]), "result": value, "terminal": True, "retryable": False}

    def cancel(self, tenant: str, job_id: str) -> dict[str, Any]:
        with self._lock, closing(self._connect()) as con:
            row = con.execute("SELECT state,trace_id,expires_at,artifact_id FROM async_jobs WHERE job_id=? AND tenant=?", (job_id, tenant)).fetchone()
            if not row: return {"success": False, "error": "async job not found", "terminal": True, "retryable": False}
            state = str(row[0])
            trace_id = str(row[1] or "")
            expires_at = float(row[2])
            artifact_id = str(row[3] or "")
            if expires_at <= time.time() and state in self.TERMINAL_STATES:
                state = "expired"
            if state == "cancelled":
                admission = self._admission("accepted", "capacity_available", retryable=False)
                return {"success": True, "job_id": job_id, "state": "cancelled", "artifact_id": artifact_id, "expires_at": expires_at, "cancel_requested": True, "terminal": True, "retryable": False, "admission": admission, "admission_state": admission["state"]}
            if state in {"done", "failed", "expired", "outcome_unknown"}: return {"success": False, "job_id": job_id, "state": state, "artifact_id": artifact_id, "expires_at": expires_at, "error": "async job is already terminal", "terminal": True, "retryable": False}
            delayed = self._delayed_dispatch.pop(job_id, None)
            if delayed is not None:
                delayed.cancel()
            changed = con.execute("UPDATE async_jobs SET cancel_requested=1,state=CASE WHEN state='queued' THEN 'cancelled' ELSE state END,updated_at=? WHERE job_id=? AND cancel_requested=0", (time.time(), job_id)).rowcount
            con.commit()
        self._cleanup_processes(job_id)
        if changed:
            self._stats["cancelled"] += 1
        if self.debug_traces is not None and trace_id and state == "queued":
            try: self.debug_traces.finish(trace_id, state="cancelled", error="async job cancelled before execution")
            except Exception: pass
        admission = self._admission("accepted", "capacity_available", retryable=False)
        final_state = "cancelled" if state == "queued" else "running"
        if final_state == "cancelled":
            # A running cancellation is only an acknowledgement; _execute wakes waiters at completion.
            self._event(job_id).set()
        return {"success": True, "job_id": job_id, "state": final_state, "artifact_id": artifact_id, "expires_at": expires_at, "cancel_requested": True, "terminal": final_state == "cancelled", "retryable": final_state == "running", "admission": admission, "admission_state": admission["state"]}

    def recover(self) -> int:
        if self._shutdown.is_set():
            return 0
        cancelled_ids: list[tuple[str, str]] = []
        unknown_ids: list[tuple[str, str]] = []
        with self._lock, closing(self._connect()) as con:
            rows = con.execute(
                "SELECT job_id,state,action,attempts,cancel_requested,trace_id,payload_json "
                "FROM async_jobs WHERE state IN ('queued','running')"
            ).fetchall(); ids: list[tuple[str, str]] = []
            for job_id, state, action, attempts, cancelled, trace_id, payload_json in rows:
                if cancelled:
                    con.execute("UPDATE async_jobs SET state='cancelled',lease_until=0,updated_at=? WHERE job_id=?", (time.time(), job_id))
                    cancelled_ids.append((str(job_id), str(trace_id or "")))
                elif (state == "running" or int(attempts or 0) > 0) and not self._can_replay_after_interruption(action, payload_json, int(attempts or 0)):
                    error = "async job outcome unknown after restart; safe replay unavailable"
                    con.execute("UPDATE async_jobs SET state='outcome_unknown',lease_until=0,error=?,updated_at=? WHERE job_id=?", (error, time.time(), job_id))
                    unknown_ids.append((str(job_id), str(trace_id or "")))
                else:
                    con.execute("UPDATE async_jobs SET state='queued',lease_until=0,updated_at=? WHERE job_id=?", (time.time(), job_id)); ids.append((str(job_id), str(trace_id or "")))
            con.commit()
        for job_id, trace_id in cancelled_ids:
            self._event(job_id).set()
            self._stats["cancelled"] += 1
            if self.debug_traces is not None and trace_id:
                try: self.debug_traces.finish(trace_id, state="cancelled", error="async job cancelled during recovery")
                except Exception: pass
        for job_id, trace_id in unknown_ids:
            self._event(job_id).set()
            if self.debug_traces is not None and trace_id:
                try: self.debug_traces.finish(trace_id, state="outcome_unknown", error="async job outcome unknown after restart; safe replay unavailable")
                except Exception: pass
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
            expired = con.execute("UPDATE async_jobs SET state='expired',updated_at=? WHERE state IN ('done','failed','cancelled','outcome_unknown') AND expires_at<?", (now, now)).rowcount
            # Periodic tombstone purge: evict expired jobs whose retention period has lapsed
            con.execute("DELETE FROM async_jobs WHERE state='expired' AND updated_at<?", (now - self.result_ttl_seconds,))
            stuck = con.execute(
                "SELECT job_id, action, attempts, cancel_requested, payload_json "
                "FROM async_jobs WHERE state='running' AND lease_until<?",
                (now,),
            ).fetchall()
            for s_id, s_action, s_att, s_canc, payload_json in stuck:
                s_attempts = int(s_att or 0)
                if s_canc or not self._can_replay_after_interruption(s_action, payload_json, s_attempts):
                    state = "cancelled" if s_canc else "outcome_unknown"
                    error = "async job cancelled" if s_canc else "async job outcome unknown after lease expiry; safe replay unavailable"
                    con.execute("UPDATE async_jobs SET state=?,lease_until=0,error=?,updated_at=? WHERE job_id=?", (state, error, now, str(s_id)))
                    self._event(str(s_id)).set()
                    if s_canc:
                        self._stats["cancelled"] += 1
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
            # A retry reuses the job event; clear the previous attempt's
            # completion signal before a delayed or immediate next attempt.
            self._event(str(job_id)).clear()
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
        with self._lock, closing(self._connect()) as con:
            con.execute("UPDATE async_jobs SET cancel_requested=1,state=CASE WHEN state='queued' THEN 'cancelled' ELSE state END,updated_at=? WHERE state IN ('queued','running')", (time.time(),))
            con.commit()
        for timer in delayed:
            timer.cancel()
        for event in waiters:
            event.set()
        for job_id in list(self._processes):
            self._cleanup_processes(job_id)
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
        all_counts = retry_busy(read, retries=3)
        counts = dict(sorted(all_counts.items())[: self.stats_max_items])
        with self._lock:
            current_stats = dict(self._stats)
        return {"enabled": self.enabled, "counts": counts, "counts_total": len(all_counts), "counts_truncated": len(all_counts) > self.stats_max_items, "counts_limit": self.stats_max_items, "wait_max_seconds": self.wait_max_seconds, **current_stats}
