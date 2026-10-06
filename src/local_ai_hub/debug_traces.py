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


_TRACE_DETAIL_DEFAULT_LIMIT = 100
_TRACE_DETAIL_MAX_LIMIT = 1000
_TRACE_DETAIL_DEFAULT_BYTES = 8 * 1024 * 1024
_TRACE_DETAIL_MAX_BYTES = 128 * 1024 * 1024


class DebugTraceStore:
    """Bounded, dashboard-only execution traces kept apart from telemetry."""

    TERMINAL_STATES = {"done", "failed", "cancelled", "expired"}
    JSON_FIELDS = {"request", "effective_payload", "response"}
    CONTENT_CHUNK_CHARS = 8192
    CONTENT_PREVIEW_CHARS = 8192
    CONTENT_PAGE_MAX_CHARS = 256 * 1024

    def __init__(self, config: dict[str, Any]):
        cfg = config.get("debug_traces") or config.get("observability", {}).get("debug_traces", {})
        self.enabled = bool(cfg.get("enabled", True))
        self.retention_days: int | None
        try:
            self.retention_days = max(1, min(3650, int(cfg["retention_days"]))) if "retention_days" in cfg else None
        except (TypeError, ValueError, OverflowError):
            self.retention_days = 3
        default_ttl = config.get("async_jobs", {}).get("result_ttl_seconds", 259200)
        terminal_ttl = self.retention_days * 86400 if self.retention_days is not None else default_ttl
        self.terminal_ttl_seconds = max(1.0, float(cfg.get("terminal_ttl_seconds", terminal_ttl)))
        if self.retention_days is not None:
            self.terminal_ttl_seconds = self.retention_days * 86400
        elif "terminal_ttl_seconds" not in cfg and "result_ttl_seconds" not in config.get("async_jobs", {}):
            self.retention_days = max(1, min(3650, int(self.terminal_ttl_seconds // 86400)))
        self.max_bytes = max(1024, int(cfg.get("max_bytes", 268435456)))
        self.max_sessions = max(1, int(cfg.get("max_sessions", 1000)))
        self.max_events_per_session = max(2, int(cfg.get("max_events_per_session", 20000)))
        self.max_event_bytes = max(256, int(cfg.get("max_event_bytes", 4 * 1024 * 1024)))
        self.max_session_text_bytes = max(1024, int(cfg.get("max_session_text_bytes", 64 * 1024 * 1024)))
        self.max_detail_response_bytes = max(
            4096,
            min(16 * 1024 * 1024, int(cfg.get("max_detail_response_bytes", _TRACE_DETAIL_DEFAULT_BYTES))),
        )
        self.cleanup_batch_size = max(1, int(cfg.get("cleanup_batch_size", 50)))
        self.max_list_limit = max(1, int(cfg.get("max_list_limit", 200)))
        self.path = Path(config["server"]["state_dir"]) / "debug_traces.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialized = False
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        con = connect_sqlite(self.path, timeout_seconds=0.25)
        con.execute("PRAGMA foreign_keys=ON")
        return con

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
                    con.execute("""CREATE TABLE IF NOT EXISTS trace_content_meta (
                        trace_id TEXT NOT NULL REFERENCES traces(trace_id) ON DELETE CASCADE,
                        content_field TEXT NOT NULL, event_seq INTEGER NOT NULL DEFAULT 0,
                        encoding TEXT NOT NULL, total_chars INTEGER NOT NULL DEFAULT 0,
                        total_bytes INTEGER NOT NULL DEFAULT 0,
                        storage_truncated INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY(trace_id, content_field, event_seq)
                    )""")
                    con.execute("""CREATE TABLE IF NOT EXISTS trace_content_chunks (
                        trace_id TEXT NOT NULL, content_field TEXT NOT NULL,
                        event_seq INTEGER NOT NULL DEFAULT 0, chunk_index INTEGER NOT NULL,
                        chunk_text TEXT NOT NULL,
                        PRIMARY KEY(trace_id, content_field, event_seq, chunk_index),
                        FOREIGN KEY(trace_id, content_field, event_seq)
                            REFERENCES trace_content_meta(trace_id, content_field, event_seq)
                            ON DELETE CASCADE
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

    def _replace_content(
        self,
        con: sqlite3.Connection,
        trace_id: str,
        content_field: str,
        text: str,
        *,
        event_seq: int = 0,
        encoding: str,
        storage_truncated: bool = False,
    ) -> None:
        value = str(text)
        con.execute(
            "DELETE FROM trace_content_meta WHERE trace_id=? AND content_field=? AND event_seq=?",
            (trace_id, content_field, event_seq),
        )
        con.execute(
            "INSERT INTO trace_content_meta(trace_id,content_field,event_seq,encoding,total_chars,total_bytes,storage_truncated) "
            "VALUES(?,?,?,?,?,?,?)",
            (trace_id, content_field, event_seq, encoding, len(value), len(value.encode("utf-8")), int(storage_truncated)),
        )
        if value:
            width = self.CONTENT_CHUNK_CHARS
            con.executemany(
                "INSERT INTO trace_content_chunks(trace_id,content_field,event_seq,chunk_index,chunk_text) "
                "VALUES(?,?,?,?,?)",
                (
                    (trace_id, content_field, event_seq, index, value[start:start + width])
                    for index, start in enumerate(range(0, len(value), width))
                ),
            )

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
                for content_field, encoding in (
                    ("request", "json"),
                    ("effective_payload", "json"),
                    ("output", "text"),
                    ("response", "json"),
                ):
                    self._replace_content(con, trace_id, content_field, "", encoding=encoding)
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
            old_seq = int(oldest[0])
            con.execute("DELETE FROM trace_content_meta WHERE trace_id=? AND event_seq=?", (trace_id, old_seq))
            con.execute("DELETE FROM trace_events WHERE trace_id=? AND seq=?", (trace_id, old_seq))
            count -= 1
        if at_limit:
            marker_payload = self._encode({"reason": "max_events_per_session", "limit": self.max_events_per_session})
            marker_seq = self._next_seq(con, trace_id)
            con.execute("INSERT OR REPLACE INTO trace_events(trace_id,seq,created_at,event_type,payload_json) VALUES(?,?,?,?,?)", (trace_id, marker_seq, time.time(), "trace_truncated", marker_payload[:self.CONTENT_PREVIEW_CHARS]))
            self._replace_content(con, trace_id, "event", marker_payload, event_seq=marker_seq, encoding="json")
            count += 1
        if truncated and not marker:
            marker_payload = self._encode({"reason": "max_event_bytes", "original_bytes": raw_size})
            marker_seq = self._next_seq(con, trace_id)
            con.execute("INSERT OR REPLACE INTO trace_events(trace_id,seq,created_at,event_type,payload_json) VALUES(?,?,?,?,?)", (trace_id, marker_seq, time.time(), "trace_truncated", marker_payload[:self.CONTENT_PREVIEW_CHARS]))
            self._replace_content(con, trace_id, "event", marker_payload, event_seq=marker_seq, encoding="json")
        seq = self._next_seq(con, trace_id)
        con.execute("INSERT INTO trace_events(trace_id,seq,created_at,event_type,payload_json) VALUES(?,?,?,?,?)", (trace_id, seq, time.time(), str(event_type), bounded[:self.CONTENT_PREVIEW_CHARS]))
        self._replace_content(
            con,
            trace_id,
            "event",
            bounded,
            event_seq=seq,
            encoding="json",
            storage_truncated=truncated or (isinstance(payload, dict) and payload.get("truncated") is True),
        )
        if str(event_type) == "thinking" and isinstance(payload, dict):
            thinking_text = str(payload.get("text") or "")
            thinking_preview = thinking_text[:4096]
            self._replace_content(
                con,
                trace_id,
                "thinking",
                thinking_preview,
                event_seq=seq,
                encoding="text",
                storage_truncated=len(thinking_preview) < len(thinking_text),
            )
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
        reopening = str(fields.get("state", "")) in {"queued", "running"}
        now = time.time()
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
        content_inputs = {
            key: candidate[key]
            for key in ("request", "effective_payload", "output", "response")
            if key in fields and key in allowed
        }
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
                stored_preview = candidate[key]
                if key == "output" and stored_preview.endswith("\n[trace output truncated]"):
                    marker = "\n[trace output truncated]"
                    stored_preview = stored_preview[: max(0, self.CONTENT_PREVIEW_CHARS - len(marker))] + marker
                else:
                    stored_preview = stored_preview[:self.CONTENT_PREVIEW_CHARS]
                updates.append(f"{column}=?"); values.append(stored_preview)
        for key, value in fields.items():
            if key in allowed and key not in self.JSON_FIELDS and key not in {"output", "thinking"} and not (reopening and key == "error"):
                updates.append(f"{key}=?"); values.append(value)
        if reopening:
            # A recovered async job may reopen a trace that restart recovery
            # temporarily marked terminal. Clear stale terminal metadata so the
            # inspector does not show a live trace with a finished timestamp.
            updates.extend(["error=?", "finished_at=?", "expires_at=?"])
            values.extend(["", 0.0, now + self.terminal_ttl_seconds])
        if not updates:
            return False
        total_text_bytes = sum(len(candidate[key].encode("utf-8")) for key in text_fields)
        updates.extend(["updated_at=?", "text_bytes=?"])
        values.extend([now, total_text_bytes])
        values.append(trace_id)
        try:
            with closing(self._connect()) as con:
                con.execute("BEGIN IMMEDIATE")
                cur = con.execute(f"UPDATE traces SET {', '.join(updates)} WHERE trace_id=?", values)
                for key, content in content_inputs.items():
                    stored = candidate[key]
                    decoded = self._decode(stored, {}) if key in self.JSON_FIELDS else None
                    storage_truncated = stored != content or (
                        isinstance(decoded, dict) and decoded.get("truncated") is True
                    ) or (key == "output" and stored.endswith("\n[trace output truncated]"))
                    self._replace_content(
                        con,
                        trace_id,
                        key,
                        stored,
                        encoding="json" if key in self.JSON_FIELDS else "text",
                        storage_truncated=storage_truncated,
                    )
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
        result["thinking"] = ""
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

    def _content_page(self, trace_id: str, content_field: str, content_offset: int) -> dict[str, Any]:
        field = str(content_field or "")
        event_match = re.fullmatch(r"event:([1-9][0-9]{0,9})", field)
        if field in {"request", "effective_payload", "output", "response"}:
            content_key = field
            event_seq = 0
        elif event_match:
            content_key = "event"
            event_seq = int(event_match.group(1))
        else:
            return {"success": False, "error": "trace content field not found", "terminal": True}

        try:
            offset = 0 if isinstance(content_offset, bool) else min(2**63 - 2, max(0, int(content_offset)))
        except (TypeError, ValueError, OverflowError):
            offset = 0
        page_chars = max(64, min(self.CONTENT_PAGE_MAX_CHARS, (self.max_detail_response_bytes - 2048) // 8))
        try:
            with closing(self._connect()) as con:
                metadata = con.execute(
                    "SELECT encoding,total_chars,storage_truncated FROM trace_content_meta "
                    "WHERE trace_id=? AND content_field=? AND event_seq=?",
                    (trace_id, content_key, event_seq),
                ).fetchone()
                if not metadata:
                    exists = con.execute("SELECT 1 FROM traces WHERE trace_id=?", (trace_id,)).fetchone()
                    if not exists:
                        return {"success": False, "error": "trace not found", "trace_id": trace_id, "terminal": True}
                    return {
                        "success": False,
                        "error": "trace content is not indexed for bounded paging",
                        "trace_id": trace_id,
                        "terminal": True,
                    }
                encoding = str(metadata[0])
                total_chars = max(0, int(metadata[1] or 0))
                storage_truncated = bool(metadata[2])
                start = min(offset, total_chars)
                end = min(total_chars, start + page_chars)
                text = ""
                if end > start:
                    first_chunk = start // self.CONTENT_CHUNK_CHARS
                    after_last_chunk = (end - 1) // self.CONTENT_CHUNK_CHARS + 1
                    rows = con.execute(
                        "SELECT chunk_index,chunk_text FROM trace_content_chunks "
                        "WHERE trace_id=? AND content_field=? AND event_seq=? "
                        "AND chunk_index>=? AND chunk_index<? ORDER BY chunk_index LIMIT ?",
                        (trace_id, content_key, event_seq, first_chunk, after_last_chunk, after_last_chunk - first_chunk),
                    ).fetchall()
                    parts = []
                    for chunk_index, chunk_text in rows:
                        chunk_start = int(chunk_index) * self.CONTENT_CHUNK_CHARS
                        local_start = max(0, start - chunk_start)
                        local_end = min(len(str(chunk_text)), end - chunk_start)
                        parts.append(str(chunk_text)[local_start:local_end])
                    text = "".join(parts)
                    if len(text) != end - start:
                        return {
                            "success": False,
                            "error": "trace content page is incomplete",
                            "trace_id": trace_id,
                            "retryable": True,
                        }
                next_offset = start + len(text)
                result = {
                    "success": True,
                    "trace_id": trace_id,
                    "full_payload_requested": True,
                    "content_page": {
                        "field": field,
                        "encoding": encoding,
                        "offset": start,
                        "next_offset": next_offset,
                        "total_chars": total_chars,
                        "has_more": next_offset < total_chars,
                        "storage_truncated": storage_truncated,
                        "text": text,
                    },
                    "response_bytes": 0,
                }
                for _ in range(3):
                    measured = len(self._encode(result).encode("utf-8"))
                    if result["response_bytes"] == measured:
                        break
                    result["response_bytes"] = measured
                if result["response_bytes"] > self.max_detail_response_bytes:
                    return {
                        "success": False,
                        "error": "trace content page exceeds response budget",
                        "trace_id": trace_id,
                        "retryable": True,
                    }
                return result
        except sqlite3.Error:
            return {"success": False, "error": "trace store unavailable", "trace_id": trace_id, "retryable": True}

    def detail(
        self,
        trace_id: str,
        *,
        since_seq: int = 0,
        limit: int = _TRACE_DETAIL_DEFAULT_LIMIT,
        max_bytes: int = _TRACE_DETAIL_DEFAULT_BYTES,
        before_seq: int = 0,
        full_payload: bool = False,
        content_field: str = "",
        content_offset: int = 0,
    ) -> dict[str, Any]:
        trace_id = str(trace_id or "")[:160]
        if content_field:
            if not full_payload:
                return {"success": False, "error": "full payload access required", "terminal": True}
            return self._content_page(trace_id, content_field, content_offset)
        try:
            cursor = 0 if isinstance(since_seq, bool) else min(2**63 - 1, max(0, int(since_seq)))
        except (TypeError, ValueError, OverflowError):
            cursor = 0
        try:
            backward_cursor = 0 if isinstance(before_seq, bool) else min(2**63 - 1, max(0, int(before_seq)))
        except (TypeError, ValueError, OverflowError):
            backward_cursor = 0
        try:
            page_limit = 100 if isinstance(limit, bool) else max(1, min(int(limit), _TRACE_DETAIL_MAX_LIMIT))
        except (TypeError, ValueError, OverflowError):
            page_limit = _TRACE_DETAIL_DEFAULT_LIMIT
        try:
            byte_limit = 1024 if isinstance(max_bytes, bool) else max(
                1024, min(int(max_bytes), _TRACE_DETAIL_MAX_BYTES, self.max_detail_response_bytes)
            )
        except (TypeError, ValueError, OverflowError):
            byte_limit = _TRACE_DETAIL_DEFAULT_BYTES

        if not trace_id:
            return {"success": False, "error": "trace not found", "terminal": True}
        try:
            with closing(self._connect()) as con:
                con.row_factory = sqlite3.Row
                row = con.execute("SELECT * FROM traces WHERE trace_id=?", (trace_id,)).fetchone()
                if not row:
                    return {"success": False, "error": "trace not found", "trace_id": trace_id, "terminal": True}
                session_content_meta = {
                    str(meta[0]): (int(meta[1] or 0), bool(meta[2]))
                    for meta in con.execute(
                        "SELECT content_field,total_chars,storage_truncated FROM trace_content_meta "
                        "WHERE trace_id=? AND event_seq=0",
                        (trace_id,),
                    )
                }
                stats = con.execute(
                    "SELECT COUNT(*),MIN(seq),MAX(seq) FROM trace_events WHERE trace_id=?",
                    (trace_id,),
                ).fetchone()
                events_total = int(stats[0] or 0) if stats else 0
                first_retained_seq = int(stats[1] or 0) if stats else 0
                last_seq = int(stats[2] or 0) if stats else 0
                backward_has_more = False
                if backward_cursor:
                    backward_count = con.execute(
                        "SELECT COUNT(*) FROM (SELECT 1 FROM trace_events WHERE trace_id=? AND seq<? LIMIT ?)",
                        (trace_id, backward_cursor, page_limit + 1),
                    ).fetchone()
                    backward_has_more = bool(backward_count and int(backward_count[0] or 0) > page_limit)
                # Preserve the pinned forward-cursor contract: past-end requests
                # are empty, not an implicit replay of previously retained events.
                cursor_reset = False
                effective_cursor = cursor
                gap_ranges: list[dict[str, int]] = []
                if first_retained_seq and effective_cursor < first_retained_seq - 1:
                    gap_ranges.append({"from_seq": effective_cursor + 1, "to_seq": first_retained_seq - 1})
                    effective_cursor = first_retained_seq - 1
                thinking_parts = []
                thinking_bytes = 0
                thinking_limit = max(0, int(self.max_session_text_bytes))
                thinking_rows = con.execute(
                    "SELECT payload_json FROM trace_events WHERE trace_id=? AND event_type=? ORDER BY seq ASC",
                    (trace_id, "thinking"),
                )
                for thinking_row in thinking_rows:
                    payload = self._decode(thinking_row[0], {})
                    if isinstance(payload, dict):
                        text = str(payload.get("text") or "")
                        remaining = thinking_limit - thinking_bytes
                        if remaining <= 0:
                            break
                        if not text:
                            continue
                        encoded = text.encode("utf-8")
                        if len(encoded) > remaining:
                            text = encoded[:remaining].decode("utf-8", errors="ignore")
                        thinking_parts.append(text)
                        thinking_bytes += len(text.encode("utf-8"))
                        if thinking_bytes >= thinking_limit:
                            break
                session = self._session(row)
                session["thinking"] = "".join(thinking_parts)
                session_payload_truncated = False
                preview_columns = {
                    "request": "request_json",
                    "effective_payload": "effective_payload_json",
                    "output": "output_text",
                    "response": "response_json",
                }
                for field in ("request", "effective_payload", "output", "response", "thinking"):
                    value = session.get(field)
                    truncated = (
                        isinstance(value, dict)
                        and value.get("truncated") is True
                        and isinstance(value.get("preview"), str)
                    )
                    output_marker = field == "output" and isinstance(value, str) and value.endswith("\n[trace output truncated]")
                    if field in preview_columns:
                        raw_preview = str(row[preview_columns[field]] or "")
                        meta = session_content_meta.get(field)
                        content_is_truncated = bool(meta and (meta[0] > len(raw_preview) or meta[1]))
                        if full_payload and content_is_truncated:
                            if field == "output" and raw_preview.endswith("\n[trace output truncated]"):
                                value = raw_preview
                            else:
                                value = {"truncated": True, "preview": raw_preview}
                            session[field] = value
                            truncated = True
                    if full_payload and isinstance(value, str) and len(value.encode("utf-8")) > 64 * 1024 and not output_marker:
                        preview = value.encode("utf-8")[: 64 * 1024].decode("utf-8", errors="ignore")
                        session[field] = {"truncated": True, "preview": preview}
                        truncated = True
                    if full_payload and output_marker:
                        truncated = True
                    session_payload_truncated = session_payload_truncated or truncated
                events: list[dict[str, Any]] = []
                result: dict[str, Any] = {
                    "success": True,
                    "session": session,
                    "events": events,
                    "next_seq": effective_cursor,
                    "first_retained_seq": first_retained_seq,
                    "last_seq": last_seq,
                    "events_total": events_total,
                    "limit": page_limit,
                    "max_bytes": byte_limit,
                    "has_more": False,
                    "page_truncated": False,
                    "oversize_seq": None,
                    "required_bytes": None,
                    "gap_ranges": gap_ranges,
                    "cursor_reset": cursor_reset,
                    "terminal": session["state"] in self.TERMINAL_STATES,
                    "response_bytes": 0,
                    "events_has_more": backward_has_more,
                    "events_before_seq": backward_cursor,
                    "full_payload_requested": bool(full_payload),
                }
                if full_payload:
                    result["payload_truncated"] = session_payload_truncated

                def serialized_size(value: dict[str, Any]) -> int:
                    value["response_bytes"] = 0
                    for _ in range(5):
                        size = len(self._encode(value).encode("utf-8"))
                        if value["response_bytes"] == size:
                            return size
                        value["response_bytes"] = size
                    return len(self._encode(value).encode("utf-8"))

                def oversize_response(required_bytes: int, oversize_seq: int | None) -> dict[str, Any]:
                    response: dict[str, Any] = {
                        "success": False,
                        "error": "trace detail exceeds requested byte budget",
                        "error_code": "trace_detail_oversize",
                        "trace_id": trace_id,
                        "events": [],
                        "next_seq": effective_cursor,
                        "first_retained_seq": first_retained_seq,
                        "last_seq": last_seq,
                        "events_total": events_total,
                        "limit": page_limit,
                        "max_bytes": byte_limit,
                        "has_more": backward_has_more if backward_cursor else last_seq > effective_cursor,
                        "oversize_seq": oversize_seq,
                        "required_bytes": required_bytes,
                        "gap_ranges": gap_ranges,
                        "cursor_reset": cursor_reset,
                        "response_bytes": 0,
                        "events_has_more": backward_has_more if backward_cursor else last_seq > effective_cursor,
                        "events_before_seq": backward_cursor,
                        "full_payload_requested": bool(full_payload),
                    }
                    response["response_bytes"] = serialized_size(response)
                    if response["response_bytes"] > byte_limit:
                        response = {
                            "success": False,
                            "error": "trace detail exceeds requested byte budget",
                            "error_code": "trace_detail_oversize",
                            "trace_id": trace_id[:128],
                            "next_seq": effective_cursor,
                            "max_bytes": byte_limit,
                            "has_more": backward_has_more if backward_cursor else last_seq > effective_cursor,
                            "oversize_seq": oversize_seq,
                            "required_bytes": required_bytes,
                            "response_bytes": 0,
                            "events_has_more": backward_has_more if backward_cursor else last_seq > effective_cursor,
                            "events_before_seq": backward_cursor,
                            "full_payload_requested": bool(full_payload),
                        }
                        response["response_bytes"] = serialized_size(response)
                    return response

                base_bytes = serialized_size(result)
                if base_bytes > byte_limit:
                    return oversize_response(base_bytes, None)

                if backward_cursor:
                    backward_rows = con.execute(
                        "SELECT e.seq,e.created_at,e.event_type,e.payload_json,"
                        "m.total_chars AS content_total_chars,m.storage_truncated AS content_storage_truncated "
                        "FROM trace_events e LEFT JOIN trace_content_meta m "
                        "ON m.trace_id=e.trace_id AND m.content_field='event' AND m.event_seq=e.seq "
                        "WHERE e.trace_id=? AND e.seq<? ORDER BY e.seq DESC LIMIT ?",
                        (trace_id, backward_cursor, page_limit + 1),
                    ).fetchall()
                    rows = iter(reversed(backward_rows[:page_limit]))
                else:
                    rows = iter(con.execute(
                        "SELECT e.seq,e.created_at,e.event_type,e.payload_json,"
                        "m.total_chars AS content_total_chars,m.storage_truncated AS content_storage_truncated "
                        "FROM trace_events e LEFT JOIN trace_content_meta m "
                        "ON m.trace_id=e.trace_id AND m.content_field='event' AND m.event_seq=e.seq "
                        "WHERE e.trace_id=? AND e.seq>? ORDER BY e.seq ASC LIMIT ?",
                        (trace_id, effective_cursor, page_limit + 1),
                    ).fetchall())
                while True:
                    event_row = next(rows, None)
                    if event_row is None:
                        break
                    if len(events) >= page_limit:
                        result["has_more"] = backward_has_more if backward_cursor else True
                        if backward_cursor:
                            result["events_has_more"] = backward_has_more
                        else:
                            result["events_has_more"] = True
                        break
                    event = dict(event_row)
                    raw_payload = str(event.pop("payload_json") or "")
                    total_chars = event.pop("content_total_chars", None)
                    storage_truncated = bool(event.pop("content_storage_truncated", False))
                    payload = self._decode(raw_payload, {})
                    payload_truncated = storage_truncated or (total_chars is not None and int(total_chars) > len(raw_payload))
                    if full_payload and payload_truncated and not (isinstance(payload, dict) and payload.get("truncated") is True):
                        payload = {"truncated": True, "preview": raw_payload}
                    event["payload"] = payload
                    if full_payload and (payload_truncated or (isinstance(payload, dict) and payload.get("truncated") is True)):
                        result["payload_truncated"] = True
                    candidate_events = [*events, event]
                    candidate = dict(result)
                    candidate["events"] = candidate_events
                    candidate["next_seq"] = int(event["seq"] or 0)
                    if backward_cursor:
                        candidate["has_more"] = backward_has_more
                    else:
                        candidate["has_more"] = candidate["next_seq"] < last_seq
                        candidate["events_has_more"] = candidate["has_more"]
                        candidate["events_before_seq"] = int(candidate_events[0]["seq"] or 0)
                    required_bytes = serialized_size(candidate)
                    if required_bytes > byte_limit:
                        if not events:
                            return oversize_response(required_bytes, int(event["seq"] or 0))
                        result["has_more"] = backward_has_more if backward_cursor else True
                        if backward_cursor:
                            result["events_has_more"] = backward_has_more
                        else:
                            result["events_has_more"] = True
                        result["page_truncated"] = True
                        result["oversize_seq"] = int(event["seq"] or 0)
                        result["required_bytes"] = required_bytes
                        while serialized_size(result) > byte_limit and events:
                            dropped = events.pop()
                            dropped_seq = int(dropped["seq"] or 0)
                            result["next_seq"] = int(events[-1]["seq"] or 0) if events else effective_cursor
                            if backward_cursor:
                                result["events_before_seq"] = int(events[0]["seq"] or 0) if events else backward_cursor
                            result["oversize_seq"] = dropped_seq
                            candidate = dict(result)
                            candidate["events"] = [*events, dropped]
                            candidate["next_seq"] = dropped_seq
                            candidate["page_truncated"] = False
                            candidate["oversize_seq"] = None
                            candidate["required_bytes"] = None
                            result["required_bytes"] = serialized_size(candidate)
                        if not events:
                            return oversize_response(
                                int(result["required_bytes"] or required_bytes),
                                result.get("oversize_seq"),
                            )
                        break
                    events.append(event)
                    result["next_seq"] = int(event["seq"] or 0)
                    if backward_cursor:
                        result["events_has_more"] = backward_has_more
                        result["events_before_seq"] = int(events[0]["seq"] or 0)
                    else:
                        result["events_has_more"] = result["has_more"]
                        result["events_before_seq"] = int(events[0]["seq"] or 0)
                    result["response_bytes"] = required_bytes

                result["response_bytes"] = serialized_size(result)
                if result["response_bytes"] > byte_limit:
                    result["has_more"] = backward_has_more if backward_cursor else True
                    if backward_cursor:
                        result["events_has_more"] = backward_has_more
                    else:
                        result["events_has_more"] = True
                    result["page_truncated"] = True
                    first_dropped_seq: int | None = None
                    required_bytes = result["response_bytes"]
                    while events and serialized_size(result) > byte_limit:
                        dropped = events.pop()
                        first_dropped_seq = int(dropped["seq"] or 0)
                        candidate = dict(result)
                        candidate["events"] = [*events, dropped]
                        candidate["next_seq"] = first_dropped_seq
                        candidate["page_truncated"] = False
                        candidate["oversize_seq"] = None
                        candidate["required_bytes"] = None
                        required_bytes = serialized_size(candidate)
                        result["next_seq"] = int(events[-1]["seq"] or 0) if events else effective_cursor
                        result["oversize_seq"] = first_dropped_seq
                        result["required_bytes"] = required_bytes
                    if not events:
                        return oversize_response(required_bytes, first_dropped_seq)
                    result["response_bytes"] = serialized_size(result)
                return result
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
                if offset >= total:
                    # Past-end pages are empty; avoid binding oversized offsets to SQLite.
                    rows = []
                else:
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
            return {"enabled": self.enabled, "counts": counts, "events": events, "bytes": self._file_bytes(), "max_bytes": self.max_bytes, "max_sessions": self.max_sessions, "retention_days": self.retention_days, "terminal_ttl_seconds": int(self.terminal_ttl_seconds)}
        except sqlite3.Error:
            return {
                "enabled": self.enabled,
                "error": "trace store unavailable",
                "retryable": True,
                "retention_days": self.retention_days,
                "terminal_ttl_seconds": int(self.terminal_ttl_seconds),
            }


class DebugTraceObserver:
    def __init__(self, store: DebugTraceStore, trace_id: str):
        self.store = store
        self.trace_id = trace_id
        self._output = ""
        self._thinking = ""

    def event(self, event_type: str, payload: Any) -> None:
        self.store.event(self.trace_id, event_type, payload)

    def model_request(self, payload: Any) -> None:
        if isinstance(payload, dict) and payload.get("model"):
            self.store.update(self.trace_id, model=str(payload["model"]))
        self.store.update(self.trace_id, effective_payload=payload)
        self.event("model_request", payload)

    def output_delta(self, text: str) -> None:
        text = str(text)
        if not text:
            return
        self._output += text
        max_bytes = max(64, int(self.store.max_session_text_bytes))
        raw = self._output.encode("utf-8")
        if len(raw) > max_bytes:
            self._output = raw[:max_bytes].decode("utf-8", errors="ignore") + "\n[trace output truncated]"
        self.store.update(self.trace_id, output=self._output)
        self.event("output_delta", {"text": text})

    def thinking_delta(self, text: str) -> None:
        text = str(text)
        if not text:
            return
        self._thinking += text
        max_bytes = max(64, int(self.store.max_session_text_bytes))
        raw = self._thinking.encode("utf-8")
        if len(raw) > max_bytes:
            self._thinking = raw[:max_bytes].decode("utf-8", errors="ignore") + "\n[trace thinking truncated]"
        self.event("thinking", {"text": text})

    def tool_call(self, payload: Any) -> None:
        self.event("tool_call", payload)

    def tool_result(self, payload: Any) -> None:
        self.event("tool_result", payload)
