from __future__ import annotations

from .json_utils import dumps as json_dumps

import base64
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .process_utils import hidden_run_kwargs, is_rooted_path
from .response_protocol import project_response
from .sqlite_support import connect_sqlite, retry_busy


_TERMINAL = {"complete", "failed", "cancelled", "needs_agent", "partial"}


def _string_list(value: Any, *, limit: int = 24, item_chars: int = 2000) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if not text:
            continue
        out.append(text[:item_chars])
        if len(out) >= limit:
            break
    return out


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = int(default)
    return max(minimum, min(parsed, maximum))


def _permission_map(value: Any) -> dict[str, bool]:
    defaults = {
        "read": True,
        "edit": True,
        "tests": True,
        "build": True,
        "network": False,
        "git_commit": False,
        "create": True,
        "delete": True,
    }
    if not isinstance(value, dict):
        return defaults
    for key in tuple(defaults):
        raw = value.get(key)
        if isinstance(raw, bool):
            defaults[key] = raw
    return defaults


def _json_object(text: str) -> dict[str, Any] | None:
    text = str(text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except Exception:
        pass
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    value = json.loads(text[start:i + 1])
                    return value if isinstance(value, dict) else None
                except Exception:
                    return None
    return None


def _safe_patch_header_path(raw: str, prefix: str) -> str | None:
    value = raw.split("\t", 1)[0].strip().replace("\\", "/")
    if value == "/dev/null":
        return None
    if value.startswith(prefix):
        value = value[len(prefix):]
    if not value or value.startswith("/") or re.match(r"^[A-Za-z]:/", value):
        raise ValueError("patch contains an absolute path")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("patch contains an unsafe traversal path")
    return value


_HUNK_RE = re.compile(r"^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@")


def _patch_changes(diff_text: str) -> tuple[list[str], set[str], set[str]]:
    """Parse safe paths and create/delete operations from a unified patch.

    Hunk bodies are consumed using the declared old/new line counts. This avoids
    misinterpreting removed source text beginning with ``--- `` or added source
    text beginning with ``+++ `` as a new file header.
    """
    lines = diff_text.splitlines()
    out: list[str] = []
    creates: set[str] = set()
    deletes: set[str] = set()
    old_left = new_left = 0
    in_hunk = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if in_hunk:
            if line.startswith("\\ No newline at end of file"):
                i += 1
                continue
            if line.startswith(" "):
                old_left -= 1; new_left -= 1
            elif line.startswith("-"):
                old_left -= 1
            elif line.startswith("+"):
                new_left -= 1
            else:
                # Malformed hunks are rejected later by ``git apply --check``.
                old_left = new_left = 0
            if old_left <= 0 and new_left <= 0:
                in_hunk = False
            i += 1
            continue
        match = _HUNK_RE.match(line)
        if match:
            # A missing count means one line; an explicit zero means zero lines.
            old_count = int(match.group(1)) if match.group(1) is not None else 1
            new_count = int(match.group(2)) if match.group(2) is not None else 1
            old_left, new_left = old_count, new_count
            in_hunk = old_left > 0 or new_left > 0
            i += 1
            continue
        if line.startswith("--- "):
            if i + 1 >= len(lines) or not lines[i + 1].startswith("+++ "):
                raise ValueError("patch has an unpaired old-file header")
            old = _safe_patch_header_path(line[4:], "a/")
            new = _safe_patch_header_path(lines[i + 1][4:], "b/")
            if old is None and new is None:
                raise ValueError("patch cannot map /dev/null to /dev/null")
            # Snapshot both sides of a rename so rollback can restore the source
            # and remove the destination. For ordinary edits they are identical.
            for path in (old, new):
                if path and path not in out:
                    out.append(path)
            if old is None and new:
                creates.add(new)
            elif new is None and old:
                deletes.add(old)
            elif old and new and old != new:
                # A cross-path patch is a rename/move from a permission perspective:
                # it creates the destination and removes the source even when the
                # unified diff does not use explicit /dev/null headers.
                creates.add(new)
                deletes.add(old)
            i += 2
            continue
        if line.startswith("+++ "):
            raise ValueError("patch has an unpaired new-file header")
        i += 1
    return out, creates, deletes


def _patch_paths(diff_text: str) -> list[str]:
    """Return safe repository-relative paths from unified diff headers."""
    return _patch_changes(diff_text)[0]


def _diff_from_text(text: str) -> str:
    text = str(text or "")
    m = re.search(r"```(?:diff|patch)?\s*\n(.*?)\n```", text, flags=re.S | re.I)
    if m:
        text = m.group(1)
    pos = text.find("--- ")
    return text[pos:].strip() + "\n" if pos >= 0 else ""


def _stable_toposort_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a stable dependency order and reject cyclic planner output.

    Planner JSON is untrusted model output. Forward references are valid DAG edges,
    unknown references are discarded, and ties retain planner order for deterministic
    execution. Cycles fail closed instead of silently dropping dependencies.
    """
    if not steps:
        return []
    ids = [str(step.get("id", "")) for step in steps]
    id_set = set(ids)
    order = {sid: i for i, sid in enumerate(ids)}
    by_id = {str(step.get("id", "")): step for step in steps}
    deps: dict[str, set[str]] = {}
    followers: dict[str, list[str]] = {sid: [] for sid in ids}
    for step in steps:
        sid = str(step.get("id", ""))
        normalized = {str(dep) for dep in step.get("depends_on", []) if str(dep) in id_set and str(dep) != sid}
        step["depends_on"] = sorted(normalized, key=lambda dep: order[dep])
        deps[sid] = set(normalized)
        for dep in normalized:
            followers[dep].append(sid)
    ready = sorted((sid for sid in ids if not deps[sid]), key=lambda sid: order[sid])
    out: list[dict[str, Any]] = []
    while ready:
        sid = ready.pop(0)
        out.append(by_id[sid])
        for follower in sorted(followers[sid], key=lambda value: order[value]):
            deps[follower].discard(sid)
            if not deps[follower] and follower not in ready and by_id[follower] not in out:
                ready.append(follower)
        ready.sort(key=lambda value: order[value])
    if len(out) != len(steps):
        cyclic = [sid for sid in ids if deps[sid]]
        raise ValueError(f"planner returned cyclic step dependencies: {', '.join(cyclic[:8])}")
    return out


@dataclass
class _JournalEntry:
    path: str
    existed: bool
    data: bytes


class WorkOrchestrator:
    """Durable, serial whole-task executor for local coding work.

    The orchestrator intentionally reuses Local AI Hub's deterministic services,
    command broker, leases, artifacts and local model scheduler. It does not create
    a second agent runtime. Mutations are journalled outside git and rolled back on
    failed final verification unless the caller explicitly asks to preserve failure.
    """

    def __init__(self, config: dict[str, Any], state_dir: Path, services: Any, commands: Any, leases: Any, artifacts: Any, telemetry: Any | None = None):
        cfg = config.get("work_orchestrator", {})
        self.enabled = bool(cfg.get("enabled", True))
        self.max_active = max(1, int(cfg.get("max_active_work_orders", 1)))
        self.max_pending = max(1, min(int(cfg.get("max_pending_work_orders", 32)), 256))
        self.worker_idle_seconds = max(5.0, min(float(cfg.get("worker_idle_seconds", 120.0)), 3600.0))
        self.max_steps = max(1, min(int(cfg.get("max_steps", 32)), 64))
        self.max_llm_calls = max(1, min(int(cfg.get("max_llm_steps", 16)), 32))
        self.max_replans = max(0, min(int(cfg.get("max_replans", 2)), 4))
        self.parallel_deterministic = max(1, min(int(cfg.get("parallel_deterministic_steps", 2)), 4))
        self.default_seconds = max(30, min(int(cfg.get("max_seconds", 900)), 7200))
        self.max_patch_files = max(1, min(int(cfg.get("max_patch_files", 24)), 128))
        self.max_patch_bytes = max(4096, min(int(cfg.get("max_patch_bytes", 524288)), 4 * 1024 * 1024))
        self.step_retry_limit = max(0, min(int(cfg.get("step_retry_limit", 2)), 4))
        self.rollback_on_failure = bool(cfg.get("rollback_on_failure", True))
        self.allow_edits = bool(cfg.get("allow_edits", True))
        self.allow_create = bool(cfg.get("allow_create", True))
        self.allow_delete = bool(cfg.get("allow_delete", True))
        self.validation_limit = max(1, min(int(cfg.get("validation_commands", 3)), 8))
        self.default_response_profile = str(cfg.get("default_response_profile", "compact") or "compact")
        self.default_max_output_tokens = max(0, int(cfg.get("default_max_output_tokens", 350) or 0))
        self.services, self.commands, self.leases, self.artifacts = services, commands, leases, artifacts
        self.telemetry = telemetry
        self.path = Path(state_dir) / "work_orders.sqlite3"
        self.journal_dir = Path(state_dir) / "work_journals"
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._waiters: dict[str, threading.Event] = {}
        self._workers: list[threading.Thread] = []
        self._lock = threading.RLock()
        self._init_db()
        self._recover()
        # Work execution is lazy. Most LocalAIApp instances only use retrieval or
        # status APIs; eagerly starting another polling thread for each instance
        # caused avoidable background load in embedded/test workloads.
        self._worker: threading.Thread | None = None
        if self._has_queued_work():
            self._ensure_workers()

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self.path, timeout_seconds=2.0, isolation_level=None, row_factory=sqlite3.Row)

    def _init_db(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as con:
            con.executescript("""
            CREATE TABLE IF NOT EXISTS work_orders(
              work_id TEXT PRIMARY KEY, tenant TEXT NOT NULL, root TEXT NOT NULL, task TEXT NOT NULL,
              state TEXT NOT NULL, payload_json TEXT NOT NULL, result_json TEXT NOT NULL DEFAULT '{}',
              cancel_requested INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL, updated_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_work_orders_state_created ON work_orders(state, created_at);
            CREATE INDEX IF NOT EXISTS idx_work_orders_tenant_updated ON work_orders(tenant, updated_at DESC);
            """)

    def _journal_path(self, work_id: str) -> Path:
        text = str(work_id)
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", text)[:48] or "work"
        digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]
        return self.journal_dir / f"{safe}-{digest}.json"

    def _persist_journal(self, work_id: str, journal: list[_JournalEntry]) -> None:
        path = self._journal_path(work_id)
        if not journal:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            return
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.journal_dir, 0o700)
        except OSError:
            pass
        payload = [
            {"path": entry.path, "existed": entry.existed, "data": base64.b64encode(entry.data).decode("ascii")}
            for entry in journal
        ]
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json_dumps(payload, separators=(",", ":")), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)

    def _load_journal(self, work_id: str) -> list[_JournalEntry] | None:
        path = self._journal_path(work_id)
        if not path.is_file():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            entries: list[_JournalEntry] = []
            for item in raw if isinstance(raw, list) else []:
                if not isinstance(item, dict):
                    raise ValueError("invalid work journal entry")
                rel = str(item.get("path", "")).replace("\\", "/")
                if not rel or rel.startswith("/") or re.match(r"^[A-Za-z]:/", rel) or any(x in {"", ".", ".."} for x in rel.split("/")):
                    raise ValueError("unsafe work journal path")
                entries.append(_JournalEntry(rel, bool(item.get("existed")), base64.b64decode(str(item.get("data", "")), validate=True)))
            return entries
        except Exception:
            # A corrupt recovery journal must never be used to write repository files.
            return None

    def _clear_journal(self, work_id: str) -> None:
        self._persist_journal(work_id, [])

    def _recover(self) -> None:
        transient = ("planning", "executing", "verifying", "integrating")
        with closing(self._connect()) as con:
            rows = con.execute(
                "SELECT work_id,root,state FROM work_orders WHERE state IN (?,?,?,?)", transient
            ).fetchall()
        now = time.time()
        for row in rows:
            work_id = str(row["work_id"])
            journal = self._load_journal(work_id)
            recovered = journal is not None
            if journal:
                try:
                    root = Path(str(row["root"])).resolve(strict=False)
                    self._rollback(root, journal)
                    self._clear_journal(work_id)
                except Exception:
                    recovered = False
            elif journal == []:
                # A missing journal is safe only when there is no evidence that a
                # prior process had already mutated the workspace.
                try:
                    with closing(self._connect()) as con:
                        result_row = con.execute("SELECT result_json FROM work_orders WHERE work_id=?", (work_id,)).fetchone()
                    result = json.loads(str(result_row[0] or "{}")) if result_row else {}
                    if result.get("changed_files"):
                        recovered = False
                except Exception:
                    recovered = False
            with closing(self._connect()) as con:
                if recovered:
                    con.execute(
                        "UPDATE work_orders SET state='queued',result_json='{}',updated_at=? WHERE work_id=?",
                        (now, work_id),
                    )
                else:
                    result = json_dumps({
                        "summary": "work order recovery failed",
                        "error": "transaction journal could not be safely restored; manual inspection required",
                        "needs_agent": True,
                    }, separators=(",", ":"))
                    con.execute(
                        "UPDATE work_orders SET state='needs_agent',result_json=?,updated_at=? WHERE work_id=?",
                        (result, now, work_id),
                    )

    def _has_queued_work(self) -> bool:
        with closing(self._connect()) as con:
            row = con.execute("SELECT 1 FROM work_orders WHERE state='queued' LIMIT 1").fetchone()
        return row is not None

    def _ensure_workers(self) -> None:
        if not self.enabled or self._stop.is_set():
            return
        with self._lock:
            self._workers = [worker for worker in self._workers if worker.is_alive()]
            needed = max(0, self.max_active - len(self._workers))
            for _ in range(needed):
                index = len(self._workers) + 1
                worker = threading.Thread(
                    target=self._loop,
                    name=f"local-ai-work-orchestrator-{index}",
                    daemon=True,
                )
                self._workers.append(worker)
                if self._worker is None or not self._worker.is_alive():
                    self._worker = worker
                worker.start()

    def submit(self, tenant: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            return {"success": False, "unsupported": True, "error": "work orchestrator disabled"}
        raw_root = str(payload.get("root", "")).strip()
        if not raw_root or not is_rooted_path(raw_root):
            return {"success": False, "error": "root must be an explicit absolute repository directory", "terminal": True}
        root = Path(raw_root).expanduser().resolve(strict=False)
        task = str(payload.get("task", "")).strip()[:24000]
        if not root.is_dir():
            return {"success": False, "error": "root must be an existing absolute repository directory", "terminal": True}
        if not task:
            return {"success": False, "error": "task is required", "terminal": True}
        work_id = str(payload.get("work_id", "")).strip() or f"wo_{uuid.uuid4().hex[:20]}"
        if len(work_id) > 128 or any(ord(ch) < 32 for ch in work_id):
            return {"success": False, "error": "work_id must be at most 128 printable characters", "terminal": True}
        acceptance = _string_list(payload.get("acceptance_criteria"), limit=24, item_chars=2000)
        budgets = payload.get("budget") if isinstance(payload.get("budget"), dict) else {}
        mode = str(payload.get("mode", "execute") or "execute").strip().lower().replace("-", "_")
        if mode not in {"execute", "plan", "plan_only", "dry_run"}:
            return {"success": False, "error": "mode must be execute, plan, plan_only, or dry_run", "terminal": True}
        profile = str(payload.get("response_profile", self.default_response_profile) or self.default_response_profile).strip().lower()
        if profile not in {"minimal", "compact", "standard", "debug"}:
            profile = self.default_response_profile if self.default_response_profile in {"minimal", "compact", "standard", "debug"} else "compact"
        return_fields = _string_list(payload.get("return_fields"), limit=32, item_chars=80)
        normalized = {
            "acceptance_criteria": acceptance,
            "constraints": _string_list(payload.get("constraints"), limit=24, item_chars=2000),
            "mode": mode,
            "permissions": _permission_map(payload.get("permissions")),
            "budget": {
                "max_steps": _bounded_int(budgets.get("max_steps"), self.max_steps, 1, self.max_steps),
                "max_llm_calls": _bounded_int(budgets.get("max_llm_calls"), self.max_llm_calls, 1, self.max_llm_calls),
                "max_seconds": _bounded_int(budgets.get("max_seconds"), self.default_seconds, 30, 7200),
            },
            "response_profile": profile,
            "return_fields": return_fields,
            "max_output_tokens": _bounded_int(payload.get("max_output_tokens"), self.default_max_output_tokens, 0, 4096),
            "keep_failed_workspace": bool(payload.get("keep_failed_workspace", False)),
        }
        now = time.time()
        try:
            with closing(self._connect()) as con:
                # Serialize admission so concurrent submitters cannot all observe the
                # same free slot and overflow the configured bounded queue.
                con.execute("BEGIN IMMEDIATE")
                try:
                    pending = con.execute(
                        "SELECT COUNT(*) FROM work_orders WHERE state IN ('queued','planning','executing','integrating','verifying')"
                    ).fetchone()
                    if pending and int(pending[0]) >= self.max_pending:
                        con.execute("ROLLBACK")
                        return {"success": False, "error": "work-order queue is full", "retryable": True, "terminal": False}
                    con.execute("INSERT INTO work_orders(work_id,tenant,root,task,state,payload_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                                (work_id, tenant, str(root), task, "queued", json_dumps(normalized, separators=(",", ":")), now, now))
                    con.execute("COMMIT")
                except Exception:
                    con.execute("ROLLBACK")
                    raise
        except sqlite3.IntegrityError:
            return {"success": False, "error": "work_id already exists", "work_id": work_id, "terminal": True}
        self._ensure_workers(); self._wake.set()
        return self._project({"success": True, "status": "queued", "work_id": work_id, "summary": "whole task accepted"}, normalized)

    def _row(self, work_id: str, tenant: str = "") -> sqlite3.Row | None:
        def query() -> sqlite3.Row | None:
            with closing(self._connect()) as con:
                if tenant and tenant not in {"admin", "system", "*"}:
                    return con.execute("SELECT * FROM work_orders WHERE work_id=? AND tenant=?", (work_id, tenant)).fetchone()
                return con.execute("SELECT * FROM work_orders WHERE work_id=?", (work_id,)).fetchone()
        return retry_busy(query, retries=5, base_delay_seconds=0.02)

    def _canonical(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = json.loads(str(row["payload_json"] or "{}"))
        result = json.loads(str(row["result_json"] or "{}"))
        out = {"success": str(row["state"]) in {"queued", "planning", "executing", "integrating", "verifying", "complete", "needs_agent", "partial"},
               "status": str(row["state"]), "work_id": str(row["work_id"]), **result}
        out.setdefault("progress", result.get("progress", {}))
        return self._project(out, payload)

    @staticmethod
    def _project(value: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        return project_response(value, profile=str(payload.get("response_profile", "compact")),
                                return_fields=payload.get("return_fields") or None,
                                max_output_tokens=int(payload.get("max_output_tokens", 0) or 0))

    def status(self, tenant: str, work_id: str) -> dict[str, Any]:
        row = self._row(work_id, tenant)
        return self._canonical(row) if row else {"success": False, "error": "work order not found", "work_id": work_id}

    def get(self, tenant: str, work_id: str, *, profile: str = "", return_fields: list[str] | None = None, max_output_tokens: int = 0) -> dict[str, Any]:
        row = self._row(work_id, tenant)
        if not row:
            return {"success": False, "error": "work order not found", "work_id": work_id}
        payload = json.loads(str(row["payload_json"] or "{}"))
        if profile: payload["response_profile"] = profile
        if return_fields is not None: payload["return_fields"] = return_fields
        if max_output_tokens: payload["max_output_tokens"] = max_output_tokens
        result = json.loads(str(row["result_json"] or "{}"))
        return self._project({"success": str(row["state"]) not in {"failed", "cancelled"}, "status": str(row["state"]), "work_id": work_id, **result}, payload)

    def wait(self, tenant: str, work_id: str, timeout_seconds: float = 90) -> dict[str, Any]:
        started = time.perf_counter()
        deadline = time.monotonic() + max(0.0, min(float(timeout_seconds), 90.0))
        while time.monotonic() < deadline:
            row = self._row(work_id, tenant)
            if not row:
                result = {"success": False, "error": "work order not found", "work_id": work_id}
                self._record_wait(tenant, result, started)
                return result
            if str(row["state"]) in _TERMINAL:
                result = self._canonical(row)
                self._record_wait(tenant, result, started)
                return result
            event = self._event(work_id)
            event.wait(min(0.5, max(0.0, deadline - time.monotonic())))
            event.clear()
        result = self.status(tenant, work_id)
        result["in_progress"] = result.get("status") not in _TERMINAL
        self._record_wait(tenant, result, started)
        return result

    def _record_wait(self, tenant: str, result: dict[str, Any], started: float) -> None:
        if self.telemetry is None:
            return
        try:
            elapsed_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
            self.telemetry.record(
                event_type="coordination", action="work_wait", tenant=tenant,
                success=bool(result.get("success")), duration_ms=elapsed_ms,
                wait_count=1, wait_duration_ms=elapsed_ms,
            )
        except Exception:
            pass

    def cancel(self, tenant: str, work_id: str) -> dict[str, Any]:
        row = self._row(work_id, tenant)
        if not row:
            return {"success": False, "error": "work order not found", "work_id": work_id}
        with closing(self._connect()) as con:
            if str(row["state"]) in _TERMINAL:
                return self._canonical(row)
            con.execute("UPDATE work_orders SET cancel_requested=1,updated_at=? WHERE work_id=?", (time.time(), work_id))
        self._wake.set(); self._event(work_id).set()
        return {"success": True, "status": "cancelling", "work_id": work_id}

    def continue_work(self, tenant: str, work_id: str, answer: str) -> dict[str, Any]:
        row = self._row(work_id, tenant)
        if not row:
            return {"success": False, "error": "work order not found", "work_id": work_id}
        if str(row["state"]) != "needs_agent":
            return {"success": False, "error": "work order is not waiting for agent input", "work_id": work_id}
        payload = json.loads(str(row["payload_json"] or "{}")); payload["agent_answer"] = str(answer).strip()[:8000]
        if not payload["agent_answer"]:
            return {"success": False, "error": "answer is required", "work_id": work_id}
        with closing(self._connect()) as con:
            con.execute("UPDATE work_orders SET state='queued',payload_json=?,cancel_requested=0,updated_at=? WHERE work_id=?",
                        (json_dumps(payload, separators=(",", ":")), time.time(), work_id))
        self._ensure_workers(); self._wake.set(); self._event(work_id).set()
        return {"success": True, "status": "queued", "work_id": work_id}

    def stats(self) -> dict[str, Any]:
        with closing(self._connect()) as con:
            rows = con.execute("SELECT state,COUNT(*) c FROM work_orders GROUP BY state").fetchall()
        with self._lock:
            alive = sum(1 for worker in self._workers if worker.is_alive())
        return {"enabled": self.enabled, "states": {str(r[0]): int(r[1]) for r in rows}, "worker_alive": alive > 0, "active_workers": alive}

    def _event(self, work_id: str) -> threading.Event:
        with self._lock:
            return self._waiters.setdefault(work_id, threading.Event())

    def _set_state(self, work_id: str, state: str, result: dict[str, Any]) -> None:
        with closing(self._connect()) as con:
            con.execute("UPDATE work_orders SET state=?,result_json=?,updated_at=? WHERE work_id=?",
                        (state, json_dumps(result, ensure_ascii=False, separators=(",", ":")), time.time(), work_id))
        with self._lock:
            event = self._waiters.get(work_id)
            if event is not None:
                event.set()
                if state in _TERMINAL:
                    self._waiters.pop(work_id, None)

    def _cancelled(self, work_id: str) -> bool:
        row = self._row(work_id)
        return bool(row and int(row["cancel_requested"] or 0)) or self._stop.is_set()

    def _next(self) -> sqlite3.Row | None:
        """Atomically claim one queued order for a worker."""
        with closing(self._connect()) as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT * FROM work_orders WHERE state='queued' ORDER BY created_at LIMIT 1").fetchone()
            if row is None:
                con.execute("COMMIT")
                return None
            updated = con.execute(
                "UPDATE work_orders SET state='planning',updated_at=? WHERE work_id=? AND state='queued'",
                (time.time(), str(row["work_id"])),
            )
            if int(updated.rowcount or 0) != 1:
                con.execute("ROLLBACK")
                return None
            con.execute("COMMIT")
            return row

    def _loop(self) -> None:
        idle_since = time.monotonic()
        current = threading.current_thread()
        try:
            while not self._stop.is_set():
                row = self._next()
                if row is None:
                    if time.monotonic() - idle_since >= self.worker_idle_seconds:
                        return
                    self._wake.wait(0.5); self._wake.clear(); continue
                idle_since = time.monotonic()
                try:
                    self._execute(row)
                except Exception as exc:
                    try:
                        self._set_state(str(row["work_id"]), "failed", {"summary": "work order failed", "error": f"{type(exc).__name__}: {exc}"})
                    except Exception:
                        pass
        finally:
            # Retire the worker under the same lock used by _ensure_workers. If a
            # submit races with idle retirement, either the submit sees this worker
            # removed and starts a replacement, or this worker observes queued work
            # below and starts one itself. This closes the otherwise possible
            # queued-with-no-worker window.
            with self._lock:
                self._workers = [worker for worker in self._workers if worker is not current and worker.is_alive()]
                if self._worker is current:
                    self._worker = next((worker for worker in self._workers if worker.is_alive()), None)
            if not self._stop.is_set() and self._has_queued_work():
                self._ensure_workers()

    def _ask(self, tenant: str, root: str, task: str, context: str, max_tokens: int = 4096, *, review: bool = False) -> dict[str, Any]:
        if review:
            return self.services.second_opinion({"question": task, "candidate": context, "context": "", "max_tokens": max_tokens, "complexity": "auto"}, tenant)
        return self.services.delegate_repo({"root": root, "task": task, "context": context, "max_tokens": max_tokens, "complexity": "auto"}, tenant)

    def _plan(self, tenant: str, root: str, task: str, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        acceptance = payload.get("acceptance_criteria") or []
        prompt = (
            "PLAN A CODING WORK ORDER. Return STRICT JSON only: "
            '{"summary":"...","needs_agent":false,"question":"","steps":[{"id":"s1","kind":"inspect|edit|validate|review|integrate","task":"...","depends_on":[],"acceptance":["..."]}],"validation_commands":[]}.'
            " Make steps the smallest independently executable+verifiable units, not trivial microsteps. Max 16 steps. "
            "Use deterministic inspection before edits. Include edit steps only if requested. Do not invent files unless evidence supports them.\n"
            f"ORIGINAL TASK:\n{task}\nACCEPTANCE:\n{json_dumps(acceptance, ensure_ascii=False)}\n"
            f"CONSTRAINTS:\n{json_dumps(payload.get('constraints') or [], ensure_ascii=False)}"
            + (f"\nAGENT ANSWER TO PRIOR BLOCKER:\n{str(payload.get('agent_answer',''))[:8000]}" if payload.get("agent_answer") else "")
        )
        res = self._ask(tenant, root, prompt, json_dumps(context, ensure_ascii=False)[:14000], 1400)
        parsed = _json_object(str(res.get("text", ""))) if isinstance(res, dict) and res.get("success", True) else None
        if not parsed or not isinstance(parsed.get("steps"), list):
            parsed = {"summary": task[:240], "needs_agent": False, "question": "", "steps": [
                {"id": "s1", "kind": "inspect", "task": "Collect deterministic repository evidence relevant to the task", "depends_on": [], "acceptance": []},
                {"id": "s2", "kind": "edit", "task": task, "depends_on": ["s1"], "acceptance": acceptance},
                {"id": "s3", "kind": "validate", "task": "Run the smallest relevant validation commands", "depends_on": ["s2"], "acceptance": acceptance},
                {"id": "s4", "kind": "review", "task": "Review the integrated change against the original task", "depends_on": ["s3"], "acceptance": acceptance},
            ], "validation_commands": []}
        cleaned=[]; seen=set()
        for i, raw in enumerate(parsed.get("steps", [])[: int(payload["budget"]["max_steps"])]):
            if not isinstance(raw, dict):
                continue
            base_sid = str(raw.get("id") or f"s{i+1}").strip()[:40] or f"s{i+1}"
            sid = base_sid
            suffix = 2
            while sid in seen:
                suffix_text = f"-{suffix}"
                sid = base_sid[: max(1, 40 - len(suffix_text))] + suffix_text
                suffix += 1
            seen.add(sid)
            kind=str(raw.get("kind", "inspect")).strip().lower()
            if kind not in {"inspect","edit","validate","review","integrate"}:
                kind="inspect"
            deps=_string_list(raw.get("depends_on"), limit=self.max_steps, item_chars=40)
            step_task=str(raw.get("task", "")).strip()[:2000] or f"{kind} work-order evidence"
            cleaned.append({
                "id":sid, "kind":kind, "task":step_task, "depends_on":deps,
                "acceptance":_string_list(raw.get("acceptance"), limit=12, item_chars=2000),
                "state":"pending",
            })
        parsed["steps"] = _stable_toposort_steps(cleaned) if cleaned else [{"id":"s1","kind":"inspect","task":task,"depends_on":[],"acceptance":acceptance,"state":"pending"}]
        return parsed

    def _snapshot(self, root: Path, paths: list[str]) -> list[_JournalEntry]:
        root = root.resolve()
        entries=[]
        for rel in paths:
            raw_path = root / rel
            cursor = root
            for part in Path(rel).parts:
                cursor = cursor / part
                if cursor.is_symlink():
                    raise ValueError(f"refusing to edit symlink path: {rel}")
            p=raw_path.resolve(strict=False)
            try: p.relative_to(root)
            except ValueError: raise ValueError("patch path escapes repository")
            if p.exists() and p.is_dir(): raise ValueError(f"refusing to patch directory: {rel}")
            data=p.read_bytes() if p.exists() else b""
            if b"\x00" in data[:8192]: raise ValueError(f"refusing to edit binary file: {rel}")
            entries.append(_JournalEntry(rel,p.exists(),data))
        return entries

    @staticmethod
    def _rollback(root: Path, journal: list[_JournalEntry]) -> None:
        root = root.resolve()
        for entry in reversed(journal):
            p = root / entry.path
            if entry.existed:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(entry.data)
            else:
                try:
                    p.unlink()
                except FileNotFoundError:
                    pass

    def _rollback_transaction(self, work_id: str, root: Path, journal: list[_JournalEntry], *, keep: bool = False) -> bool:
        if not journal:
            self._clear_journal(work_id)
            return False
        if keep or not self.rollback_on_failure:
            # The caller explicitly owns the partially-mutated workspace from here.
            self._clear_journal(work_id)
            return False
        self._rollback(root, journal)
        journal.clear()
        self._clear_journal(work_id)
        return True

    def _apply_patch(self, root: Path, patch: str, tenant: str, work_id: str, journal: list[_JournalEntry], *, permissions: dict[str, Any] | None = None, lease_ttl_seconds: int = 900) -> tuple[list[str], str]:
        root = root.resolve()
        if not self.allow_edits: raise PermissionError("work orchestrator edits are disabled")
        permissions = permissions or {}
        raw=patch.encode("utf-8")
        if len(raw)>self.max_patch_bytes: raise ValueError("patch exceeds configured byte limit")
        paths, creates, deletes = _patch_changes(patch)
        if not paths or len(paths)>self.max_patch_files: raise ValueError("patch changes no files or exceeds file limit")
        if creates and (not self.allow_create or not bool(permissions.get("create", True))):
            raise PermissionError(f"file creation disabled: {sorted(creates)[0]}")
        if deletes and (not self.allow_delete or not bool(permissions.get("delete", True))):
            raise PermissionError(f"file deletion disabled: {sorted(deletes)[0]}")
        claim=self.leases.claim_batch(tenant, str(root), paths, ttl_seconds=lease_ttl_seconds, purpose=f"work-order:{work_id}")
        if not claim.get("success"): raise RuntimeError(f"edit lease unavailable: {claim.get('error','conflict')}")
        lease_id=str(claim.get("lease_id", ""))
        snap=self._snapshot(root, paths)
        journal.extend(snap)
        # Persist the rollback journal before the first mutating subprocess. A hard
        # process crash can therefore restore the repository before re-queuing work.
        self._persist_journal(work_id, journal)
        try:
            check=subprocess.run(["git","-C",str(root),"apply","--check","--whitespace=nowarn","-"], input=patch, capture_output=True, text=True, timeout=12, check=False, **hidden_run_kwargs())
            if check.returncode != 0: raise ValueError((check.stderr or check.stdout or "git apply --check failed")[:1000])
            applied=subprocess.run(["git","-C",str(root),"apply","--whitespace=nowarn","-"], input=patch, capture_output=True, text=True, timeout=12, check=False, **hidden_run_kwargs())
            if applied.returncode != 0: raise ValueError((applied.stderr or applied.stdout or "git apply failed")[:1000])
            return paths, lease_id
        except Exception:
            self._rollback(root, snap)
            del journal[-len(snap):]
            self._persist_journal(work_id, journal)
            try: self.leases.release(tenant, lease_id)
            except Exception: pass
            raise

    def _execute(self, row: sqlite3.Row) -> None:
        work_id, tenant, root_s, task = str(row["work_id"]), str(row["tenant"]), str(row["root"]), str(row["task"])
        root=Path(root_s); payload=json.loads(str(row["payload_json"] or "{}")); started=time.monotonic()
        budget=payload["budget"]; llm_calls=0; replans=0; journal: list[_JournalEntry]=[]; lease_ids=[]; changed=[]; step_results=[]; validation=[]
        mutation_generation = 0
        validated_generation = -1
        def budget_ok() -> bool:
            return (time.monotonic()-started)<int(budget["max_seconds"]) and llm_calls<int(budget["max_llm_calls"])
        def validation_commands() -> list[str]:
            discovered=self.services.command({"action":"discover","root":root_s},tenant)
            commands=[]
            for c in list(plan.get("validation_commands") or []) + list(discovered.get("validation_commands") or []):
                c=str(c).strip()
                if c and c not in commands: commands.append(c)
            return commands[:self.validation_limit] or ["git diff --check"]
        def run_validations(criterion: str) -> None:
            nonlocal validated_generation
            perms = payload.get("permissions", {})
            if not bool(perms.get("tests", True)) and not bool(perms.get("build", True)):
                raise PermissionError("validation is required for mutating whole-task execution")
            remaining = max(1, int(budget["max_seconds"] - (time.monotonic() - started)))
            for command in validation_commands():
                r=self.services.command({"action":"run","command":command,"cwd":root_s,"timeout":min(300,remaining),"task_id":work_id,"criterion":criterion},tenant)
                validation.append({"command":command,"success":bool(r.get("success")),"exit_code":r.get("exit_code"),"error":r.get("error",""),"generation":mutation_generation})
                if not r.get("success"): raise RuntimeError(f"validation failed: {command}: {r.get('error','non-zero exit')}")
            validated_generation = mutation_generation
        def repair(reason: str) -> bool:
            nonlocal llm_calls, replans, mutation_generation
            # A repair consumes one model call and must leave capacity for a fresh
            # verifier call; never "repair" into an unverifiable budget state.
            if (replans >= self.max_replans or not budget_ok()
                    or llm_calls + 1 >= int(budget["max_llm_calls"])
                    or not bool(payload.get("permissions", {}).get("edit", True))):
                return False
            current=self.services.repo_diff(root_s,"HEAD",False,6500)
            req=("REPLAN/REPAIR this whole-task implementation after new verification evidence. Return ONLY one unified git diff, no prose. "
                 "Make the smallest corrective change; preserve already-correct work and public APIs.\n"
                 f"ORIGINAL TASK:\n{task}\nACCEPTANCE:\n{json_dumps(payload.get('acceptance_criteria',[]),ensure_ascii=False)}\n"
                 f"NEW EVIDENCE / FAILURE:\n{reason[:4000]}")
            res=self._ask(tenant,root_s,req,json_dumps(current,ensure_ascii=False)[:18000],1800); llm_calls+=1; replans+=1
            patch=_diff_from_text(str(res.get("text","")))
            if not patch:
                return False
            lease_ttl = min(7200, max(900, int(budget["max_seconds"]) + 60))
            try:
                paths,lease=self._apply_patch(root,patch,tenant,work_id,journal,permissions=payload.get("permissions",{}),lease_ttl_seconds=lease_ttl)
            except Exception:
                return False
            lease_ids.append(lease); changed.extend(x for x in paths if x not in changed)
            mutation_generation += 1
            return True
        if self._cancelled(work_id): self._set_state(work_id,"cancelled",{"summary":"cancelled before start"}); return
        self._set_state(work_id,"planning",{"summary":"collecting context and planning","progress":{"phase":"planning","completed":0}})
        context={"profile":self.services.repo_profile(root_s),"map":self.services.repo_map(root_s,80),"tests":self.services.test_matrix(root_s)}
        plan=self._plan(tenant,root_s,task,payload,context); llm_calls+=1
        if bool(plan.get("needs_agent")):
            self._set_state(work_id,"needs_agent",{"summary":str(plan.get("summary",task))[:600],"needs_agent":True,"question":str(plan.get("question","Clarification required"))[:1200],"plan":plan}); return
        if payload.get("mode") in {"plan","plan_only","dry_run"}:
            art=self.artifacts.put(json_dumps({"task":task,"plan":plan},ensure_ascii=False,indent=2),tenant,"work-plan")
            self._set_state(work_id,"complete",{"summary":str(plan.get("summary",task))[:600],"plan":plan,"artifact_id":art,"available_details":["plan"]}); return
        self._set_state(work_id,"executing",{"summary":str(plan.get("summary",task))[:600],"plan":plan,"progress":{"phase":"executing","completed":0,"total":len(plan["steps"])}})
        try:
            for idx, step in enumerate(plan["steps"]):
                if self._cancelled(work_id): raise InterruptedError("cancelled")
                if not budget_ok():
                    kept = bool(payload.get("keep_failed_workspace"))
                    rolled = self._rollback_transaction(work_id, root, journal, keep=kept)
                    if rolled:
                        changed = []
                    self._set_state(work_id,"partial",{"summary":"work budget exhausted" + ("; workspace rolled back" if rolled else ""),"plan":plan,"steps":step_results,"changed_files":changed,"rolled_back":rolled,"progress":{"completed":idx,"total":len(plan["steps"])}}); return
                kind=step["kind"]; outcome={"id":step["id"],"kind":kind,"task":step["task"],"success":True}
                if kind == "inspect":
                    if self.parallel_deterministic > 1:
                        with ThreadPoolExecutor(max_workers=min(2, self.parallel_deterministic), thread_name_prefix="work-inspect") as pool:
                            det_future = pool.submit(self.services.deterministic_query, root_s, step["task"], 24)
                            code_future = pool.submit(self.services.code_query, root_s, step["task"], 20)
                            det, code = det_future.result(), code_future.result()
                    else:
                        det = self.services.deterministic_query(root_s, step["task"], 24)
                        code = self.services.code_query(root_s, step["task"], 20)
                    outcome["evidence"] = {"deterministic": det, "code": code}
                elif kind == "edit":
                    perms = payload.get("permissions", {})
                    if not bool(perms.get("edit", True)):
                        raise PermissionError("work order edit permission is disabled")
                    fast=self.services.fast_context(root_s, step["task"], 2200)
                    last_error = ""
                    patch = ""
                    paths: list[str] = []
                    lease = ""
                    for attempt in range(self.step_retry_limit + 1):
                        req=("Return ONLY a unified git diff that implements this bounded step. No prose. Preserve public APIs unless task requires otherwise. "
                             "Do not edit generated/vendor/cache files. Make the smallest coherent change and include tests when appropriate.\n"
                             f"ORIGINAL TASK:\n{task}\nSTEP:\n{step['task']}\nACCEPTANCE:\n{json_dumps(step.get('acceptance',[]),ensure_ascii=False)}"
                             + (f"\nPREVIOUS PATCH ERROR:\n{last_error}" if last_error else ""))
                        res=self._ask(tenant,root_s,req,json_dumps(fast,ensure_ascii=False)[:16000],1800); llm_calls+=1
                        patch=_diff_from_text(str(res.get("text","")))
                        if not patch:
                            last_error = "local worker returned no unified diff"
                            if attempt < self.step_retry_limit and budget_ok():
                                continue
                            raise RuntimeError(last_error)
                        try:
                            lease_ttl = min(7200, max(900, int(budget["max_seconds"]) + 60))
                            paths,lease=self._apply_patch(root,patch,tenant,work_id,journal, permissions=perms, lease_ttl_seconds=lease_ttl)
                            break
                        except Exception as exc:
                            last_error = str(exc)[:1000]
                            if attempt >= self.step_retry_limit or not budget_ok():
                                raise
                    lease_ids.append(lease); changed.extend(x for x in paths if x not in changed)
                    mutation_generation += 1
                    outcome.update({"files":paths,"patch_bytes":len(patch.encode('utf-8')),"attempts":attempt+1})
                elif kind == "validate":
                    perms = payload.get("permissions", {})
                    if not bool(perms.get("tests", True)) and not bool(perms.get("build", True)):
                        raise PermissionError("validation permission disabled for a mutating work order")
                    try:
                        run_validations(step["task"])
                    except RuntimeError as exc:
                        if not repair(str(exc)):
                            raise
                        # A repair invalidates all prior validation evidence; rerun
                        # the complete bounded validation set on the new generation.
                        run_validations(step["task"] + " after repair")
                elif kind in {"review","integrate"}:
                    while True:
                        diff=self.services.repo_diff(root_s,"HEAD",False,5000)
                        q=("Verify this integrated change against the ORIGINAL TASK and acceptance criteria. Return STRICT JSON only: "
                           '{"passed":true,"summary":"...","criteria":[{"criterion":"...","passed":true}],"risks":[],"needs_agent":false,"question":""}. '
                           "Fail closed on missing validation, semantic mismatch, regression or unsupported assumption.\n"
                           f"ORIGINAL TASK:\n{task}\nACCEPTANCE:\n{json_dumps(payload.get('acceptance_criteria',[]),ensure_ascii=False)}")
                        vr=self._ask(tenant,root_s,q,json_dumps(diff,ensure_ascii=False)[:18000],1200,review=True); llm_calls+=1
                        parsed=_json_object(str(vr.get("text",""))) or {"passed":False,"summary":"verifier returned invalid result","risks":["invalid verifier response"]}
                        outcome["verification"]=parsed
                        if parsed.get("needs_agent"):
                            rolled = self._rollback_transaction(work_id, root, journal, keep=False)
                            if rolled:
                                changed = []
                            self._set_state(work_id,"needs_agent",{"summary":str(parsed.get("summary","needs agent")),"needs_agent":True,"question":str(parsed.get("question","Decision required")),"plan":plan,"steps":step_results+[outcome],"changed_files":changed,"validation":validation,"rolled_back":rolled}); return
                        if bool(parsed.get("passed")):
                            break
                        if not repair(f"review failed: {parsed.get('summary','unspecified')}"):
                            raise RuntimeError(f"verification failed: {parsed.get('summary','unspecified')}")
                        run_validations("replanned repair after review")
                step_results.append(outcome)
                self._set_state(work_id,"executing",{"summary":str(plan.get("summary",task))[:600],"plan":plan,"steps":step_results,"changed_files":changed,"validation":validation,"progress":{"phase":"executing","completed":idx+1,"total":len(plan["steps"])}})

            # Whole-task final check uses the original request, not the planner summary.
            self._set_state(work_id,"verifying",{"summary":"whole-task verification","plan":plan,"steps":step_results,"changed_files":changed,"validation":validation})
            if changed and validated_generation != mutation_generation:
                run_validations("final integrated validation")
            criteria=payload.get("acceptance_criteria") or []
            while True:
                if not budget_ok():
                    raise RuntimeError("LLM/time budget exhausted before final whole-task verification")
                diff=self.services.repo_diff(root_s,"HEAD",False,6500)
                final_q=("FINAL WHOLE-TASK VERIFIER. Judge only against ORIGINAL TASK and explicit acceptance criteria. Return STRICT JSON only: "
                         '{"passed":true,"summary":"...","criteria":[{"criterion":"...","passed":true}],"risks":[]}. '
                         "A mutating task cannot pass without successful validation evidence from the current mutation generation.\n"
                         f"ORIGINAL TASK:\n{task}\nACCEPTANCE:\n{json_dumps(criteria,ensure_ascii=False)}\n"
                         f"VALIDATION:\n{json_dumps(validation,ensure_ascii=False)}")
                final=self._ask(tenant,root_s,final_q,json_dumps(diff,ensure_ascii=False)[:22000],1200,review=True); llm_calls+=1
                verification=_json_object(str(final.get("text",""))) or {"passed":False,"summary":"invalid final verifier response","risks":["invalid verifier response"]}
                if changed and validated_generation != mutation_generation:
                    verification["passed"]=False
                if criteria:
                    got={str(x.get("criterion","")): bool(x.get("passed")) for x in verification.get("criteria",[]) if isinstance(x,dict)}
                    if not all(any(c == k or c.lower() in k.lower() or k.lower() in c.lower() for k,p in got.items() if p) for c in criteria): verification["passed"]=False
                if verification.get("passed"):
                    break
                if not repair(f"final whole-task verification failed: {verification.get('summary','unspecified')}"):
                    raise RuntimeError(f"whole-task verification failed: {verification.get('summary','unspecified')}")
                run_validations("replanned repair after final verification")
            changed = [str(x) for x in diff.get("changed_files", changed)] if isinstance(diff, dict) else changed
            report={"original_task":task,"plan":plan,"steps":step_results,"changed_files":changed,"diff":diff,"validation":validation,"verification":verification,"llm_calls":llm_calls,"replans":replans,"elapsed_seconds":round(time.monotonic()-started,2)}
            artifact=self.artifacts.put(json_dumps(report,ensure_ascii=False,indent=2),tenant,"work-handoff")
            handoff={"summary":str(verification.get("summary") or plan.get("summary") or "work complete")[:900],"changed_files":changed,"validation":{"passed":all(v.get("success") for v in validation),"commands":len(validation)},"verification":verification,"risks":verification.get("risks",[])[:8],"handoff_id":artifact,"artifact_id":artifact,"available_details":["plan","steps","diff","validation","verification"]}
            self._clear_journal(work_id)
            self._set_state(work_id,"complete",handoff)
        except InterruptedError:
            rolled = self._rollback_transaction(work_id, root, journal, keep=bool(payload.get("keep_failed_workspace")))
            if rolled:
                changed = []
            self._set_state(work_id,"cancelled",{"summary":"work order cancelled" + ("; workspace rolled back" if rolled else ""),"changed_files":changed,"rolled_back":rolled})
        except Exception as exc:
            rolled=False
            try:
                rolled = self._rollback_transaction(work_id, root, journal, keep=bool(payload.get("keep_failed_workspace")))
                if rolled:
                    changed=[]
            except Exception:
                pass
            try:
                failure_diff = self.services.repo_diff(root_s,"HEAD",False,6500)
            except Exception:
                failure_diff = {"success": False, "error": "diff unavailable"}
            report={"original_task":task,"plan":plan,"steps":step_results,"changed_files":changed,"diff":failure_diff,"validation":validation,"error":str(exc),"rolled_back":rolled,"llm_calls":llm_calls,"replans":replans}
            artifact=self.artifacts.put(json_dumps(report,ensure_ascii=False,indent=2),tenant,"work-failure")
            self._set_state(work_id,"failed",{"summary":"whole task failed" + (" and was rolled back" if rolled else ""),"error":str(exc)[:1200],"changed_files":changed,"validation":{"passed":False,"commands":len(validation)},"artifact_id":artifact,"available_details":["plan","steps","validation","failure_report"]})
        finally:
            for lid in lease_ids:
                try: self.leases.release(tenant,lid)
                except Exception: pass

    def close(self) -> None:
        self._stop.set(); self._wake.set()
        current = threading.current_thread()
        with self._lock:
            workers = list(self._workers)
        for worker in workers:
            if worker is not current and worker.is_alive():
                worker.join(timeout=2.0)
