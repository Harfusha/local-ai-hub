from __future__ import annotations

from .json_utils import dumps as json_dumps

import json
import re
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any

from .sqlite_support import connect_sqlite, initialize_wal, is_busy_error, retry_busy


def _compact_project_label(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip().rstrip("/\\")
    return re.split(r"[\\/]", text)[-1] if text else ""


class DebugTraceStore:
    """Bounded, dashboard-only execution traces kept apart from telemetry."""

    TERMINAL_STATES = {"done", "failed", "cancelled", "expired"}
    JSON_FIELDS = {"request", "effective_payload", "response"}

    def __init__(self, config: dict[str, Any]):
        cfg = config.get("debug_traces") or config.get("observability", {}).get("debug_traces", {})
        self.enabled = bool(cfg.get("enabled", True))
        self.terminal_ttl_seconds = max(1.0, float(cfg.get("terminal_ttl_seconds", config.get("async_jobs", {}).get("result_ttl_seconds", 259200))))
        self.max_bytes = max(1024, int(cfg.get("max_bytes", 268435456)))
        self.max_sessions = max(1, int(cfg.get("max_sessions", 1000)))
        self.max_events_per_session = max(2, int(cfg.get("max_events_per_session", 20000)))
        self.max_event_bytes = max(256, int(cfg.get("max_event_bytes", 65536)))
        self.max_session_text_bytes = max(1024, int(cfg.get("max_session_text_bytes", 8388608)))
        self.cleanup_batch_size = max(1, int(cfg.get("cleanup_batch_size", 50)))
        self.max_list_limit = max(1, int(cfg.get("max_list_limit", 200)))
        self.path = Path(config["server"]["state_dir"]) / "debug_traces.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialized = False
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self.path, timeout_seconds=0.25)

    def _init_db(self) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            def _setup() -> None:
                with closing(self._connect()) as con:
                    initialize_wal(con)
                    con.execute("PRAGMA foreign_keys=ON")
                    con.execute("""CREATE TABLE IF NOT EXISTS traces (
                        trace_id TEXT PRIMARY KEY, kind TEXT NOT NULL, tenant TEXT NOT NULL,
                        agent TEXT NOT NULL DEFAULT '', action TEXT NOT NULL DEFAULT '',
                        source TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '',
                        request_id TEXT NOT NULL DEFAULT '', async_job_id TEXT NOT NULL DEFAULT '',
                        scheduler_job_id TEXT NOT NULL DEFAULT '', state TEXT NOT NULL,
                        request_json TEXT NOT NULL DEFAULT '', effective_payload_json TEXT NOT NULL DEFAULT '',
                        output_text TEXT NOT NULL DEFAULT '', response_json TEXT NOT NULL DEFAULT '',
                        error TEXT NOT NULL DEFAULT '', text_bytes INTEGER NOT NULL DEFAULT 0,
                        created_at REAL NOT NULL, updated_at REAL NOT NULL, finished_at REAL NOT NULL DEFAULT 0,
                        expires_at REAL NOT NULL
                    )""")
                    con.execute("""CREATE TABLE IF NOT EXISTS trace_events (
                        trace_id TEXT NOT NULL REFERENCES traces(trace_id) ON DELETE CASCADE,
                        seq INTEGER NOT NULL, created_at REAL NOT NULL, event_type TEXT NOT NULL,
                        payload_json TEXT NOT NULL DEFAULT '',
                        PRIMARY KEY(trace_id, seq)
                    )""")
                    con.execute("CREATE INDEX IF NOT EXISTS idx_traces_state_updated ON traces(state, updated_at)")
                    con.execute("CREATE INDEX IF NOT EXISTS idx_traces_kind_created ON traces(kind, created_at)")
                    con.execute("CREATE INDEX IF NOT EXISTS idx_trace_events_created ON trace_events(created_at)")
                    con.commit()
            retry_busy(_setup, retries=5, base_delay_seconds=0.02)
            self._initialized = True

    @staticmethod
    def _encode(value: Any) -> str:
        return json_dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)

    @staticmethod
    def _decode(value: str, default: Any = None) -> Any:
        if not value:
            return default
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return default if default is not None else value

    def _bounded_payload(self, payload: Any) -> tuple[str, bool, int]:
        encoded = self._encode(payload)
        raw_size = len(encoded.encode("utf-8"))
        if raw_size <= self.max_event_bytes:
            return encoded, False, raw_size
        preview_limit = max(64, self.max_event_bytes // 4)
        preview = encoded[:preview_limit]
        bounded = self._encode({"truncated": True, "original_bytes": raw_size, "preview": preview})
        while len(bounded.encode("utf-8")) > self.max_event_bytes and len(preview) > 16:
            preview = preview[: max(16, len(preview) // 2)]
            bounded = self._encode({"truncated": True, "original_bytes": raw_size, "preview": preview})
        return bounded, True, raw_size

    def start(self, *, kind: str, tenant: str, agent: str = "", action: str = "", source: str = "", model: str = "", request_id: str = "", trace_id: str | None = None) -> str:
        if not self.enabled:
            return ""
        trace_id = trace_id or uuid.uuid4().hex
        now = time.time()
        def _do_start() -> str:
            with closing(self._connect()) as con:
                con.execute("""INSERT INTO traces(trace_id,kind,tenant,agent,action,source,model,request_id,state,created_at,updated_at,expires_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (trace_id, str(kind), str(tenant), str(agent), str(action), str(source), str(model), str(request_id), "queued", now, now, now + self.terminal_ttl_seconds))
                con.commit()
            return trace_id
        try:
            return retry_busy(_do_start, retries=3)
        except sqlite3.Error:
            return ""

    def link(self, trace_id: str, *, request_id: str = "", async_job_id: str = "", scheduler_job_id: str = "") -> bool:
        if not trace_id:
            return False
        values = (str(request_id), str(async_job_id), str(scheduler_job_id), time.time(), trace_id)
        try:
            with closing(self._connect()) as con:
                cur = con.execute("UPDATE traces SET request_id=COALESCE(NULLIF(?,''),request_id), async_job_id=COALESCE(NULLIF(?,''),async_job_id), scheduler_job_id=COALESCE(NULLIF(?,''),scheduler_job_id), updated_at=? WHERE trace_id=?", values)
                con.commit()
                return cur.rowcount > 0
        except sqlite3.Error:
            return False

    def _next_seq(self, con: sqlite3.Connection, trace_id: str) -> int:
        row = con.execute("SELECT COALESCE(MAX(seq),0)+1 FROM trace_events WHERE trace_id=?", (trace_id,)).fetchone()
        return int(row[0])

    def _append_event(self, con: sqlite3.Connection, trace_id: str, event_type: str, payload: Any, *, marker: bool = False) -> int | None:
        if not con.execute("SELECT 1 FROM traces WHERE trace_id=?", (trace_id,)).fetchone():
            return None
        count = int(con.execute("SELECT COUNT(*) FROM trace_events WHERE trace_id=?", (trace_id,)).fetchone()[0])
        bounded, truncated, raw_size = self._bounded_payload(payload)
        at_limit = not marker and count >= self.max_events_per_session - 1
        marker_count = int(at_limit) + int(not marker and truncated)
        while count > self.max_events_per_session - 1 - marker_count:
            oldest = con.execute("SELECT seq FROM trace_events WHERE trace_id=? ORDER BY seq ASC LIMIT 1", (trace_id,)).fetchone()
            if not oldest:
                break
            con.execute("DELETE FROM trace_events WHERE trace_id=? AND seq=?", (trace_id, int(oldest[0])))
            count -= 1
        if at_limit:
            marker_payload = self._encode({"reason": "max_events_per_session", "limit": self.max_events_per_session})
            con.execute("INSERT OR REPLACE INTO trace_events(trace_id,seq,created_at,event_type,payload_json) VALUES(?,?,?,?,?)", (trace_id, self._next_seq(con, trace_id), time.time(), "trace_truncated", marker_payload))
            count += 1
        if truncated and not marker:
            marker_payload = self._encode({"reason": "max_event_bytes", "original_bytes": raw_size})
            con.execute("INSERT OR REPLACE INTO trace_events(trace_id,seq,created_at,event_type,payload_json) VALUES(?,?,?,?,?)", (trace_id, self._next_seq(con, trace_id), time.time(), "trace_truncated", marker_payload))
        seq = self._next_seq(con, trace_id)
        con.execute("INSERT INTO trace_events(trace_id,seq,created_at,event_type,payload_json) VALUES(?,?,?,?,?)", (trace_id, seq, time.time(), str(event_type), bounded))
        con.execute("UPDATE traces SET updated_at=? WHERE trace_id=?", (time.time(), trace_id))
        return seq

    def event(self, trace_id: str, event_type: str, payload: Any) -> int | None:
        if not self.enabled or not trace_id:
            return None
        try:
            with closing(self._connect()) as con:
                con.execute("BEGIN IMMEDIATE")
                seq = self._append_event(con, trace_id, event_type, payload)
                con.commit()
                return seq
        except sqlite3.Error:
            return None

    def update(self, trace_id: str, **fields: Any) -> bool:
        if not self.enabled or not trace_id:
            return False
        allowed = {"state", "source", "model", "request", "effective_payload", "output", "response", "error", "queue_wait_ms", "inference_ms", "total_ms"}
        updates: list[str] = []
        values: list[Any] = []
        try:
            with closing(self._connect()) as read_con:
                read_con.row_factory = sqlite3.Row
                current = read_con.execute("SELECT request_json,effective_payload_json,output_text,response_json FROM traces WHERE trace_id=?", (trace_id,)).fetchone()
        except sqlite3.Error:
            return False
        if not current:
            return False
        candidate: dict[str, Any] = {
            "request": str(current[0] or ""),
            "effective_payload": str(current[1] or ""),
            "output": str(current[2] or ""),
            "response": str(current[3] or ""),
        }
        for key, value in fields.items():
            if key not in allowed:
                continue
            candidate[key] = self._encode(value) if key in self.JSON_FIELDS else str(value)
        text_fields = ["request", "effective_payload", "output", "response"]
        remaining = self.max_session_text_bytes
        for key in text_fields:
            raw = candidate[key].encode("utf-8")
            budget = max(16, remaining // max(1, len([name for name in text_fields if candidate[name]]))) if raw else 0
            if len(raw) > budget:
                preview = raw[: max(0, budget - 32)].decode("utf-8", errors="ignore")
                candidate[key] = self._encode({"truncated": True, "preview": preview}) if key != "output" else preview + "\n[trace output truncated]"
            used = len(candidate[key].encode("utf-8"))
            if used > remaining:
                candidate[key] = candidate[key].encode("utf-8")[:remaining].decode("utf-8", errors="ignore")
                used = len(candidate[key].encode("utf-8"))
            remaining = max(0, remaining - used)
        for key, column in (("request", "request_json"), ("effective_payload", "effective_payload_json"), ("output", "output_text"), ("response", "response_json")):
            if key in fields:
                updates.append(f"{column}=?"); values.append(candidate[key])
        for key, value in fields.items():
            if key in allowed and key not in self.JSON_FIELDS and key != "output":
                updates.append(f"{key}=?"); values.append(value)
        if not updates:
            return False
        total_text_bytes = sum(len(candidate[key].encode("utf-8")) for key in text_fields)
        updates.extend(["updated_at=?", "text_bytes=?"])
        values.extend([time.time(), total_text_bytes])
        values.append(trace_id)
        try:
            with closing(self._connect()) as con:
                cur = con.execute(f"UPDATE traces SET {', '.join(updates)} WHERE trace_id=?", values)
                con.commit()
                return cur.rowcount > 0
        except sqlite3.Error:
            return False

    def finish(self, trace_id: str, *, state: str, response: Any = None, error: str = "") -> bool:
        if not self.enabled or not trace_id:
            return False
        state = str(state)
        now = time.time()
        if response is not None:
            # Keep the response write bounded but give it the same short lock
            # recovery as the terminal transition. A failed response preview
            # must never prevent the trace from becoming terminal.
            for attempt in range(3):
                if self.update(trace_id, response=response):
                    break
                if attempt < 2:
                    time.sleep(0.02 * (attempt + 1))
        # A busy WAL is expected while an observer appends the last event. The
        # request has already completed, so spend a small, fixed budget here;
        # never leave a successful API call looking permanently running merely
        # because one SQLite writer briefly won the race.
        for attempt in range(4):
            try:
                with closing(self._connect()) as con:
                    con.execute("BEGIN IMMEDIATE")
                    fields = ["state=?", "updated_at=?", "finished_at=?", "expires_at=?"]
                    values: list[Any] = [state, now, now, now + self.terminal_ttl_seconds]
                    if error:
                        fields.append("error=?"); values.append(str(error)[:4000])
                    values.append(trace_id)
                    cur = con.execute(f"UPDATE traces SET {', '.join(fields)} WHERE trace_id=?", values)
                    if cur.rowcount:
                        self._append_event(con, trace_id, state if state in self.TERMINAL_STATES else "state", {"state": state, "error": str(error)[:1000] if error else ""})
                    con.commit()
                    return cur.rowcount > 0
            except sqlite3.Error as exc:
                if is_busy_error(exc) and attempt < 3:
                    time.sleep(0.02 * (attempt + 1))
                    continue
                return False
        return False

    def reconcile_terminal(self, trace_id: str, *, state: str, response: Any = None, error: str = "") -> bool:
        """Mirror a terminal recovery-journal result into a trace row.

        The request journal is written before the HTTP socket is flushed. If a
        client-side transport finishes from that journal while the debug writer
        loses its final SQLite race, the two stores can briefly disagree. Only
        terminal journal states are accepted here; live work is never guessed.
        """
        if str(state) not in self.TERMINAL_STATES:
            return False
        return self.finish(trace_id, state=str(state), response=response, error=error)

    def recover_incomplete(self, *, reason: str = "hub restarted") -> dict[str, int]:
        """Close traces left non-terminal by a previous hub process."""
        result = {"recovered_sessions": 0}
        if not self.enabled:
            return result
        now = time.time()
        try:
            with closing(self._connect()) as con:
                con.execute("BEGIN IMMEDIATE")
                rows = con.execute("SELECT trace_id FROM traces WHERE state IN ('queued','running')").fetchall()
                for (trace_id,) in rows:
                    cur = con.execute(
                        "UPDATE traces SET state='failed',error=?,updated_at=?,finished_at=?,expires_at=? "
                        "WHERE trace_id=? AND state IN ('queued','running')",
                        (str(reason)[:4000], now, now, now + self.terminal_ttl_seconds, str(trace_id)),
                    )
                    if cur.rowcount:
                        self._append_event(con, str(trace_id), "failed", {"state": "failed", "reason": str(reason)[:1000]})
                        result["recovered_sessions"] += 1
                con.commit()
        except sqlite3.Error:
            return result
        return result

    def _session(self, row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        for key in ("request_json", "effective_payload_json", "response_json"):
            result[key.removesuffix("_json")] = self._decode(result.pop(key), {})
        result["output"] = result.pop("output_text", "")
        result["request"] = result.get("request") or {}
        result["effective_payload"] = result.get("effective_payload") or {}
        result["response"] = result.get("response") or {}
        return result

    @staticmethod
    def _request_summary(action: str, request_action: Any, command: Any) -> str:
        if action != "/api/command":
            return ""
        operation = re.sub(r"[^A-Za-z0-9_.-]", "", str(request_action or ""))[:32]
        preview = " ".join(command.split()) if isinstance(command, str) else ""
        if preview:
            preview = re.sub(
                r"(?i)(--?[A-Za-z0-9_.-]*(?:TOKEN|PASSWORD|SECRET|PASSWD|API[-_]?KEY|ACCESS[-_]?KEY|AUTHORIZATION|CREDENTIAL)[A-Za-z0-9_.-]*(?:=|\s+))(?:(?:\"[^\"]*\")|(?:'[^']*')|\S+)",
                r"\1[redacted]",
                preview,
            )
            preview = re.sub(
                r"(?i)\b([A-Z0-9_.-]*(?:TOKEN|SECRET|PASSWORD|PASSWD|API[_-]?KEY|ACCESS[_-]?KEY|AUTHORIZATION|CREDENTIAL)[A-Z0-9_.-]*\s*=\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)",
                r"\1[redacted]",
                preview,
            )
            preview = re.sub(r"(?i)\bBearer\s+\S+", "Bearer [redacted]", preview)
            preview = preview[:160]
        return " · ".join(part for part in (operation, preview) if part)

    def detail(self, trace_id: str, *, since_seq: int = 0) -> dict[str, Any]:
        if not trace_id:
            return {"success": False, "error": "trace not found", "terminal": True}
        try:
            with closing(self._connect()) as con:
                con.row_factory = sqlite3.Row
                row = con.execute("SELECT * FROM traces WHERE trace_id=?", (trace_id,)).fetchone()
                if not row:
                    return {"success": False, "error": "trace not found", "trace_id": trace_id, "terminal": True}
                session = self._session(row)
                events = [dict(event) for event in con.execute("SELECT seq,created_at,event_type,payload_json FROM trace_events WHERE trace_id=? AND seq>? ORDER BY seq ASC", (trace_id, max(0, int(since_seq))))]
                for event in events:
                    event["payload"] = self._decode(event.pop("payload_json"), {})
                return {"success": True, "session": session, "events": events, "next_seq": events[-1]["seq"] if events else max(0, int(since_seq)), "terminal": session["state"] in self.TERMINAL_STATES}
        except sqlite3.Error:
            return {"success": False, "error": "trace store unavailable", "trace_id": trace_id, "retryable": True}

    def list(self, *, kind: str = "", state: str = "", agent: str = "", model: str = "", limit: int = 50, offset: int = 0) -> dict[str, Any]:
        limit = min(self.max_list_limit, max(1, int(limit)))
        offset = max(0, int(offset))
        where: list[str] = []
        values: list[Any] = []
        for column, value in (("kind", kind), ("state", state), ("agent", agent), ("model", model)):
            if value:
                where.append(f"{column}=?"); values.append(str(value))
        clause = " WHERE " + " AND ".join(where) if where else ""
        try:
            with closing(self._connect()) as con:
                con.row_factory = sqlite3.Row
                total = int(con.execute(f"SELECT COUNT(*) FROM traces{clause}", values).fetchone()[0])
                rows = con.execute(f"""SELECT trace_id,kind,tenant,agent,action,source,model,request_id,async_job_id,scheduler_job_id,state,created_at,updated_at,finished_at,error,
                    CASE WHEN json_valid(request_json) THEN substr(json_extract(request_json, '$.action'), 1, 48) END AS request_action,
                    CASE WHEN json_valid(request_json) THEN substr(json_extract(request_json, '$.command'), 1, 512) END AS request_command,
                    CASE WHEN json_valid(request_json) THEN COALESCE(json_extract(request_json, '$.project'), json_extract(request_json, '$.workspace'), json_extract(request_json, '$.root'), json_extract(request_json, '$.repo_root')) END AS request_project,
                    CASE WHEN json_valid(effective_payload_json) THEN COALESCE(json_extract(effective_payload_json, '$.project'), json_extract(effective_payload_json, '$.workspace'), json_extract(effective_payload_json, '$.root'), json_extract(effective_payload_json, '$.repo_root')) END AS payload_project
                    FROM traces{clause} ORDER BY updated_at DESC LIMIT ? OFFSET ?""", [*values, limit, offset]).fetchall()
                items = []
                for row in rows:
                    item = dict(row)
                    item["request_summary"] = self._request_summary(item["action"], item.pop("request_action", None), item.pop("request_command", None))
                    item["project"] = _compact_project_label(item.pop("request_project", None) or item.pop("payload_project", None))
                    items.append(item)
                return {"success": True, "items": items, "total": total, "limit": limit, "offset": offset}
        except sqlite3.Error:
            return {"success": False, "error": "trace store unavailable", "retryable": True}

    def _file_bytes(self) -> int:
        total = 0
        for suffix in ("", "-wal", "-shm"):
            path = Path(f"{self.path}{suffix}")
            try:
                total += path.stat().st_size
            except OSError:
                pass
        return total

    def cleanup(self, *, now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else float(now)
        result = {"deleted_sessions": 0, "deleted_events": 0, "bytes": self._file_bytes(), "busy": False}
        if not self.enabled:
            return result
        try:
            with closing(self._connect()) as con:
                con.execute("PRAGMA foreign_keys=ON")
                total_count = int(con.execute("SELECT COUNT(*) FROM traces").fetchone()[0])
                candidates = con.execute("SELECT trace_id,expires_at FROM traces WHERE state IN ('done','failed','cancelled','expired') ORDER BY updated_at ASC").fetchall()
                deleted = 0
                for trace_id, expires_at in candidates:
                    if deleted >= self.cleanup_batch_size:
                        break
                    if not (float(expires_at) <= now or total_count > self.max_sessions or self._file_bytes() > self.max_bytes):
                        continue
                    event_count = int(con.execute("SELECT COUNT(*) FROM trace_events WHERE trace_id=?", (trace_id,)).fetchone()[0])
                    con.execute("DELETE FROM traces WHERE trace_id=?", (trace_id,))
                    result["deleted_sessions"] += 1
                    result["deleted_events"] += event_count
                    deleted += 1
                    total_count -= 1
                con.commit()
                try:
                    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                except sqlite3.Error:
                    pass
        except sqlite3.Error as exc:
            if is_busy_error(exc):
                result["busy"] = True
            else:
                result["error"] = "trace cleanup unavailable"
        result["bytes"] = self._file_bytes()
        return result

    def stats(self) -> dict[str, Any]:
        try:
            with closing(self._connect()) as con:
                counts = {str(state): int(count) for state, count in con.execute("SELECT state,COUNT(*) FROM traces GROUP BY state")}
                events = int(con.execute("SELECT COUNT(*) FROM trace_events").fetchone()[0])
            return {"enabled": self.enabled, "counts": counts, "events": events, "bytes": self._file_bytes(), "max_bytes": self.max_bytes, "max_sessions": self.max_sessions}
        except sqlite3.Error:
            return {"enabled": self.enabled, "error": "trace store unavailable", "retryable": True}


class DebugTraceObserver:
    def __init__(self, store: DebugTraceStore, trace_id: str):
        self.store = store
        self.trace_id = trace_id
        self._output = ""

    def event(self, event_type: str, payload: Any) -> None:
        self.store.event(self.trace_id, event_type, payload)

    def model_request(self, payload: Any) -> None:
        if isinstance(payload, dict) and payload.get("model"):
            self.store.update(self.trace_id, model=str(payload["model"]))
        self.store.update(self.trace_id, effective_payload=payload)
        self.event("model_request", payload)

    def output_delta(self, text: str) -> None:
        self._output += str(text)
        max_bytes = max(64, int(self.store.max_session_text_bytes))
        raw = self._output.encode("utf-8")
        if len(raw) > max_bytes:
            self._output = raw[:max_bytes].decode("utf-8", errors="ignore") + "\n[trace output truncated]"
        self.store.update(self.trace_id, output=self._output)
        self.event("output_delta", {"text": str(text)})

    def tool_call(self, payload: Any) -> None:
        self.event("tool_call", payload)

    def tool_result(self, payload: Any) -> None:
        self.event("tool_result", payload)
