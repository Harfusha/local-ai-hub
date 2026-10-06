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
    CONTENT_CHUNK_CHARS = 8192
    CONTENT_PREVIEW_CHARS = 8192
    CONTENT_PAGE_MAX_CHARS = 256 * 1024

    def __init__(self, config: dict[str, Any]):
        cfg = config.get("debug_traces") or config.get("observability", {}).get("debug_traces", {})
        self.enabled = bool(cfg.get("enabled", True))
        self.terminal_ttl_seconds = max(1.0, min(365 * 86400.0, float(cfg.get("terminal_ttl_seconds", config.get("async_jobs", {}).get("result_ttl_seconds", 259200)))))
        self.max_bytes = max(1024, min(1024 * 1024 * 1024, int(cfg.get("max_bytes", 268435456))))
        self.max_sessions = max(1, min(10000, int(cfg.get("max_sessions", 1000))))
        self.max_events_per_session = max(2, min(100000, int(cfg.get("max_events_per_session", 20000))))
        self.max_event_bytes = max(256, min(16 * 1024 * 1024, int(cfg.get("max_event_bytes", 4 * 1024 * 1024))))
        self.max_session_text_bytes = max(1024, min(256 * 1024 * 1024, int(cfg.get("max_session_text_bytes", 64 * 1024 * 1024))))
        self.cleanup_batch_size = max(1, min(1000, int(cfg.get("cleanup_batch_size", 50))))
        self.max_list_limit = max(1, min(500, int(cfg.get("max_list_limit", 200))))
        self.max_detail_events = max(1, min(500, int(cfg.get("max_detail_events", 100))))
        self.max_detail_response_bytes = max(4096, min(16 * 1024 * 1024, int(cfg.get("max_detail_response_bytes", 1024 * 1024))))
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
            (
                trace_id,
                content_field,
                event_seq,
                encoding,
                len(value),
                len(value.encode("utf-8")),
                int(storage_truncated),
            ),
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

    def _clip_session_content(self, field: str, text: str, budget_bytes: int) -> tuple[str, bool]:
        raw = text.encode("utf-8")
        if len(raw) <= budget_bytes:
            return text, False
        budget = max(0, int(budget_bytes))
        if budget == 0:
            return "", True
        if field == "output":
            marker = "\n[trace output truncated]"
            marker_bytes = marker.encode("utf-8")
            if budget <= len(marker_bytes):
                return marker_bytes[:budget].decode("utf-8", errors="ignore"), True
            preview = raw[:budget - len(marker_bytes)].decode("utf-8", errors="ignore")
            while len((preview + marker).encode("utf-8")) > budget and preview:
                preview = preview[:-1]
            return preview + marker, True

        preview = raw[:max(0, budget - 64)].decode("utf-8", errors="ignore")
        while preview:
            bounded = self._encode({"truncated": True, "preview": preview})
            if len(bounded.encode("utf-8")) <= budget:
                return bounded, True
            preview = preview[:max(0, len(preview) // 2)]
        bounded = self._encode({"truncated": True, "preview": ""})
        return (bounded if len(bounded.encode("utf-8")) <= budget else "{}"[:budget]), True

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
                for content_field, encoding in (("request", "json"), ("effective_payload", "json"), ("output", "text"), ("response", "json")):
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
        event_storage_truncated = truncated or (isinstance(payload, dict) and payload.get("truncated") is True)
        self._replace_content(con, trace_id, "event", bounded, event_seq=seq, encoding="json", storage_truncated=event_storage_truncated)
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
            with closing(self._connect()) as con:
                con.row_factory = sqlite3.Row
                con.execute("BEGIN IMMEDIATE")
                current = con.execute("SELECT text_bytes FROM traces WHERE trace_id=?", (trace_id,)).fetchone()
                if not current:
                    con.rollback()
                    return False

                text_fields = ("request", "effective_payload", "output", "response")
                columns = {
                    "request": "request_json",
                    "effective_payload": "effective_payload_json",
                    "output": "output_text",
                    "response": "response_json",
                }
                content_meta = {
                    str(row["content_field"]): int(row["total_bytes"] or 0)
                    for row in con.execute(
                        "SELECT content_field,total_bytes FROM trace_content_meta WHERE trace_id=? AND event_seq=0",
                        (trace_id,),
                    )
                }
                content_inputs = {
                    key: self._encode(fields[key]) if key in self.JSON_FIELDS else str(fields[key])
                    for key in text_fields
                    if key in fields and key in allowed
                }
                legacy_bytes = max(0, int(current["text_bytes"] or 0) - sum(content_meta.values()))
                unchanged_bytes = sum(content_meta.get(key, 0) for key in text_fields if key not in content_inputs)
                remaining = max(0, self.max_session_text_bytes - legacy_bytes - unchanged_bytes)
                active_count = sum(bool(value) for value in content_inputs.values())

                for key in text_fields:
                    if key not in content_inputs:
                        continue
                    original_value = fields[key]
                    budget = remaining // max(1, active_count) if content_inputs[key] else 0
                    stored, clipped = self._clip_session_content(key, content_inputs[key], budget)
                    semantic_truncation = (
                        isinstance(original_value, dict) and original_value.get("truncated") is True
                    )
                    storage_truncated = clipped or semantic_truncation
                    self._replace_content(
                        con,
                        trace_id,
                        key,
                        stored,
                        encoding="json" if key in self.JSON_FIELDS else "text",
                        storage_truncated=storage_truncated,
                    )
                    updates.append(f"{columns[key]}=?")
                    values.append(stored[:self.CONTENT_PREVIEW_CHARS])
                    remaining = max(0, remaining - len(stored.encode("utf-8")))
                    if content_inputs[key]:
                        active_count = max(0, active_count - 1)
                    content_meta[key] = len(stored.encode("utf-8"))

                for key, value in fields.items():
                    if key in allowed and key not in self.JSON_FIELDS and key not in {"output", "thinking"} and key not in text_fields and not (reopening and key == "error"):
                        updates.append(f"{key}=?")
                        values.append(value)
                if reopening:
                    # A recovered async job may reopen a trace that restart recovery
                    # temporarily marked terminal. Clear stale terminal metadata so the
                    # inspector does not show a live trace with a finished timestamp.
                    updates.extend(["error=?", "finished_at=?", "expires_at=?"])
                    values.extend(["", 0.0, now + self.terminal_ttl_seconds])
                if not updates:
                    con.rollback()
                    return False
                if content_inputs:
                    total_text_bytes = legacy_bytes + sum(content_meta.values())
                    updates.append("text_bytes=?")
                    values.append(total_text_bytes)
                updates.append("updated_at=?")
                values.extend([now, trace_id])
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
            event_seq = None
        elif event_match:
            content_key = "event"
            event_seq = int(event_match.group(1))
        else:
            return {"success": False, "error": "trace content field not found", "terminal": True}

        try:
            offset = min(2**63 - 2, max(0, int(content_offset)))
        except (TypeError, ValueError, OverflowError):
            offset = 0
        page_chars = max(64, min(self.CONTENT_PAGE_MAX_CHARS, (self.max_detail_response_bytes - 2048) // 8))
        try:
            with closing(self._connect()) as con:
                metadata = con.execute(
                    "SELECT encoding,total_chars,storage_truncated FROM trace_content_meta "
                    "WHERE trace_id=? AND content_field=? AND event_seq=?",
                    (trace_id, content_key, int(event_seq or 0)),
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
                    chunk_limit = after_last_chunk - first_chunk
                    rows = con.execute(
                        "SELECT chunk_index,chunk_text FROM trace_content_chunks "
                        "WHERE trace_id=? AND content_field=? AND event_seq=? "
                        "AND chunk_index>=? AND chunk_index<? ORDER BY chunk_index LIMIT ?",
                        (trace_id, content_key, int(event_seq or 0), first_chunk, after_last_chunk, chunk_limit),
                    ).fetchall()
                    parts: list[str] = []
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
                has_more = next_offset < total_chars
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
                        "has_more": has_more,
                        "storage_truncated": storage_truncated,
                        "text": text,
                    },
                }
                result["response_bytes"] = 0
                for _ in range(3):
                    measured = len(self._encode(result).encode("utf-8"))
                    if result["response_bytes"] == measured:
                        break
                    result["response_bytes"] = measured
                if int(result["response_bytes"]) > self.max_detail_response_bytes:
                    return {"success": False, "error": "trace content page exceeds response budget", "trace_id": trace_id, "retryable": True}
                return result
        except sqlite3.Error:
            return {"success": False, "error": "trace store unavailable", "trace_id": trace_id, "retryable": True}

    def detail(
        self,
        trace_id: str,
        *,
        since_seq: int = 0,
        limit: int = 100,
        full_payload: bool = False,
        content_field: str = "",
        content_offset: int = 0,
        before_seq: int = 0,
    ) -> dict[str, Any]:
        trace_id = str(trace_id or "")[:160]
        if not trace_id:
            return {"success": False, "error": "trace not found", "terminal": True}
        if content_field:
            if not full_payload:
                return {"success": False, "error": "full payload access required", "terminal": True}
            return self._content_page(trace_id, content_field, content_offset)
        try:
            cursor = min(2**63 - 1, max(0, int(since_seq)))
        except (TypeError, ValueError, OverflowError):
            cursor = 0
        try:
            backward_cursor = min(2**63 - 1, max(0, int(before_seq)))
        except (TypeError, ValueError, OverflowError):
            backward_cursor = 0
        try:
            bounded_limit = max(1, min(self.max_detail_events, int(limit)))
        except (TypeError, ValueError, OverflowError):
            bounded_limit = min(100, self.max_detail_events)
        event_preview_chars = max(128, min(self.CONTENT_PREVIEW_CHARS, self.max_detail_response_bytes // max(4, bounded_limit * 4)))
        session_preview_chars = max(128, min(self.CONTENT_PREVIEW_CHARS, self.max_detail_response_bytes // 16))
        try:
            with closing(self._connect()) as con:
                con.row_factory = sqlite3.Row
                row = con.execute(
                    """SELECT trace_id,kind,tenant,agent,action,source,model,request_id,async_job_id,scheduler_job_id,state,
                              substr(request_json,1,?) AS request_json, substr(effective_payload_json,1,?) AS effective_payload_json,
                              substr(output_text,1,?) AS output_text, substr(response_json,1,?) AS response_json,
                               substr(error,1,256) AS error,text_bytes,created_at,updated_at,finished_at,expires_at
                       FROM traces WHERE trace_id=?""",
                    (session_preview_chars, session_preview_chars, session_preview_chars, session_preview_chars, trace_id),
                ).fetchone()
                if not row:
                    return {"success": False, "error": "trace not found", "trace_id": trace_id, "terminal": True}
                if backward_cursor:
                    backward_rows = con.execute(
                        """SELECT e.seq,e.created_at,e.event_type,substr(e.payload_json,1,?),
                                  m.total_chars,m.storage_truncated
                           FROM trace_events e LEFT JOIN trace_content_meta m
                             ON m.trace_id=e.trace_id AND m.content_field='event' AND m.event_seq=e.seq
                           WHERE e.trace_id=? AND e.seq<? ORDER BY e.seq DESC LIMIT ?""",
                        (event_preview_chars, trace_id, backward_cursor, bounded_limit + 1),
                    ).fetchall()
                    has_more = len(backward_rows) > bounded_limit
                    event_rows = list(reversed(backward_rows[:bounded_limit]))
                else:
                    event_rows = con.execute(
                        """SELECT e.seq,e.created_at,e.event_type,substr(e.payload_json,1,?),
                                  m.total_chars,m.storage_truncated
                           FROM trace_events e LEFT JOIN trace_content_meta m
                             ON m.trace_id=e.trace_id AND m.content_field='event' AND m.event_seq=e.seq
                           WHERE e.trace_id=? AND e.seq>? ORDER BY e.seq ASC LIMIT ?""",
                        (event_preview_chars, trace_id, cursor, bounded_limit + 1),
                    ).fetchall()
                    has_more = len(event_rows) > bounded_limit
                events = []
                event_truncated = False
                for event_row in event_rows[:bounded_limit]:
                    raw_payload = str(event_row[3] or "")
                    total_chars = int(event_row[4]) if event_row[4] is not None else None
                    preview_truncated = total_chars is None or total_chars > len(raw_payload)
                    payload = self._decode(raw_payload, {}) if not preview_truncated else {"truncated": True, "preview": raw_payload}
                    stored_payload_truncated = (
                        isinstance(payload, dict)
                        and payload.get("truncated") is True
                        and isinstance(payload.get("preview"), str)
                    )
                    event_truncated = event_truncated or preview_truncated or bool(event_row[5]) or stored_payload_truncated
                    events.append({"seq": int(event_row[0]), "created_at": float(event_row[1]), "event_type": str(event_row[2]), "payload": payload})
                thinking_char_cap = max(64, min(4096, self.max_detail_response_bytes // max(64, self.max_detail_events * 8)))
                thinking_rows = con.execute(
                    """SELECT m.event_seq,m.total_chars,m.storage_truncated
                       FROM trace_content_meta m JOIN trace_events e
                         ON e.trace_id=m.trace_id AND e.seq=m.event_seq
                       WHERE m.trace_id=? AND m.content_field='thinking' AND e.event_type=?
                       ORDER BY m.event_seq ASC LIMIT ?""",
                    (trace_id, "thinking", self.max_detail_events + 1),
                ).fetchall()
                thinking_parts = []
                thinking_truncated = len(thinking_rows) > self.max_detail_events
                for thinking_row in thinking_rows[:self.max_detail_events]:
                    chunk = con.execute(
                        "SELECT chunk_text FROM trace_content_chunks WHERE trace_id=? AND content_field='thinking' "
                        "AND event_seq=? AND chunk_index=0 LIMIT 1",
                        (trace_id, int(thinking_row[0])),
                    ).fetchone()
                    part = str(chunk[0] or "") if chunk else ""
                    thinking_parts.append(part[:thinking_char_cap])
                    thinking_truncated = thinking_truncated or bool(thinking_row[2]) or int(thinking_row[1] or 0) > thinking_char_cap
                session_content_meta = {
                    str(meta[0]): (int(meta[1] or 0), bool(meta[2]))
                    for meta in con.execute(
                        "SELECT content_field,total_chars,storage_truncated FROM trace_content_meta "
                        "WHERE trace_id=? AND event_seq=0",
                        (trace_id,),
                    )
                }
                session = self._session(row)
                session_truncated = False
                preview_columns = {
                    "request": "request_json",
                    "effective_payload": "effective_payload_json",
                    "output": "output_text",
                    "response": "response_json",
                }
                for key, raw_column in preview_columns.items():
                    value = session.get(key)
                    stored_field_truncated = (
                        isinstance(value, dict)
                        and value.get("truncated") is True
                        and isinstance(value.get("preview"), str)
                    )
                    if key == "output" and isinstance(value, str):
                        stored_field_truncated = value.endswith("[trace output truncated]")
                    raw_preview = str(row[raw_column] or "")
                    metadata = session_content_meta.get(key)
                    over_response_limit = metadata is None or metadata[0] > len(raw_preview)
                    if over_response_limit:
                        session[key] = {"truncated": True, "preview": raw_preview}
                    session_truncated = session_truncated or over_response_limit or stored_field_truncated or bool(metadata and metadata[1])
                session["thinking"] = "".join(thinking_parts)[: self.max_session_text_bytes]
                result = {
                    "success": True, "session": session, "events": events,
                    "next_seq": events[-1]["seq"] if events else cursor,
                    "has_more": has_more or len(thinking_rows) > self.max_detail_events,
                    "events_has_more": has_more,
                    "events_before_seq": events[0]["seq"] if events else backward_cursor,
                    "truncated": event_truncated or session_truncated or thinking_truncated,
                    "payload_truncated": event_truncated or session_truncated or thinking_truncated,
                    "full_payload_requested": bool(full_payload),
                    "terminal": session["state"] in self.TERMINAL_STATES,
                }
                last_selected_seq = int(event_rows[min(len(event_rows), bounded_limit) - 1][0]) if event_rows else cursor

                def response_size() -> int:
                    result["response_bytes"] = 0
                    for _ in range(4):
                        measured = len(self._encode(result).encode("utf-8"))
                        if result["response_bytes"] == measured:
                            return measured
                        result["response_bytes"] = measured
                    return len(self._encode(result).encode("utf-8"))

                response_limit = max(1024, self.max_detail_response_bytes - 512)

                while response_size() > response_limit and events:
                    events.pop()
                    result["has_more"] = True
                    if not backward_cursor:
                        result["events_has_more"] = True
                    result["truncated"] = True
                    result["next_seq"] = events[-1]["seq"] if events else cursor
                    result["events_before_seq"] = events[0]["seq"] if events else backward_cursor
                if response_size() > response_limit:
                    for key in ("request", "effective_payload", "response", "output", "thinking"):
                        value = session.get(key)
                        if value:
                            session[key] = {"truncated": True, "preview": self._encode(value)[:32]}
                            result["truncated"] = True
                            result["payload_truncated"] = True
                            if response_size() <= response_limit:
                                break
                if response_size() > response_limit:
                    result["events"] = []
                    result["has_more"] = bool(result["has_more"] or has_more)
                    result["events_has_more"] = bool(result["events_has_more"] or has_more)
                    result["next_seq"] = last_selected_seq
                    result["events_before_seq"] = int(event_rows[0][0]) if backward_cursor and event_rows else backward_cursor
                    result["truncated"] = True
                    result["session"] = {
                        key: str(session.get(key, ""))[:256]
                        for key in ("trace_id", "kind", "state", "tenant", "agent", "action", "source", "model", "request_id")
                        if session.get(key) is not None
                    }
                    result["payload_truncated"] = True
                response_size()
                return result
        except sqlite3.Error:
            return {"success": False, "error": "trace store unavailable", "trace_id": trace_id, "retryable": True}

    def list(self, *, kind: str = "", state: str = "", agent: str = "", model: str = "", limit: int = 50, offset: int = 0) -> dict[str, Any]:
        try:
            limit = min(self.max_list_limit, max(1, int(limit)))
        except (TypeError, ValueError, OverflowError):
            limit = min(50, self.max_list_limit)
        try:
            offset = max(0, int(offset))
        except (TypeError, ValueError, OverflowError):
            offset = 0
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
            return {"enabled": self.enabled, "counts": counts, "events": events, "bytes": self._file_bytes(), "max_bytes": self.max_bytes, "max_sessions": self.max_sessions}
        except sqlite3.Error:
            return {"enabled": self.enabled, "error": "trace store unavailable", "retryable": True}


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
