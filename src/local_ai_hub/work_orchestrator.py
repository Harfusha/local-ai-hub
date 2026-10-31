from __future__ import annotations

from .json_utils import dumps as json_dumps

import base64
import hashlib
import json
import math
import os
import re
import sqlite3
import stat
import subprocess
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .process_utils import hidden_run_kwargs, is_rooted_path
from .response_protocol import project_response
from .sqlite_support import connect_sqlite, retry_busy
from .work_fencing import (
    FencingLease,
    FencingLeaseStore,
    LeaseLostError,
    LeaseUnavailableError,
    WorkAttemptFence,
    canonical_resource,
    normalize_paths,
)


_TERMINAL = {"complete", "failed", "cancelled", "needs_agent", "partial"}
_WORK_PERMISSION_FIELDS = frozenset({"read", "edit", "tests", "build", "network", "git_commit", "create", "delete"})


def is_terminal_work_status(status: Any) -> bool:
    """Return True if work status represents a terminal state."""
    if not isinstance(status, str):
        return False
    return status.strip().lower() in _TERMINAL


def is_valid_work_order_id(work_id: Any) -> bool:
    """Return True if work order ID is a valid alphanumeric identifier."""
    if not isinstance(work_id, str):
        return False
    clean = work_id.strip()
    if not clean or "\x00" in clean or len(clean) > 128:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9_-]+", clean))


def _string_list(value: Any, *, limit: int = 24, item_chars: int = 2000) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    out: list[str] = []
    for item in value:
        if item is None or isinstance(item, bool):
            continue
        text = str(item).replace("\x00", "").strip()
        if not text:
            continue
        out.append(text[:item_chars])
        if len(out) >= limit:
            break
    return out


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        parsed = int(default)
    else:
        try:
            parsed = int(value)
            if not math.isfinite(parsed):
                parsed = int(default)
        except (TypeError, ValueError, OverflowError):
            parsed = int(default)
    return max(minimum, min(parsed, maximum))


def _safe_float(value: Any, default: float, minimum: float | None = None, maximum: float | None = None) -> float:
    if isinstance(value, bool) or value is None:
        parsed = float(default)
    else:
        try:
            parsed = float(value)
            if not math.isfinite(parsed):
                parsed = float(default)
        except (TypeError, ValueError, OverflowError):
            parsed = float(default)
    if minimum is not None:
        parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def _budget_int(value: Any, name: str) -> int:
    """Parse an integer budget without bool coercion or fractional truncation."""
    if isinstance(value, bool) or not (
        isinstance(value, int)
        or isinstance(value, str) and re.fullmatch(r"[+-]?\d+", value.strip())
    ):
        raise ValueError(f"work order {name} budget must be an integer")
    return int(value)


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
    but duplicate IDs, self-edges, unknown references and cycles fail closed. Ties
    retain planner order for deterministic execution.
    """
    if not steps:
        return []
    ids = [str(step.get("id", "")) for step in steps]
    if any(not sid.strip() for sid in ids):
        raise ValueError("planner returned an empty step id")
    if len(ids) != len(set(ids)):
        raise ValueError("planner returned duplicate planner step ids")
    id_set = set(ids)
    order = {sid: i for i, sid in enumerate(ids)}
    by_id = {str(step.get("id", "")): step for step in steps}
    deps: dict[str, set[str]] = {}
    followers: dict[str, list[str]] = {sid: [] for sid in ids}
    for step in steps:
        sid = str(step.get("id", ""))
        raw_dependencies = step.get("depends_on", [])
        if not isinstance(raw_dependencies, list):
            raise ValueError(f"planner step {sid} dependencies must be a list")
        normalized = {str(dep).strip() for dep in raw_dependencies}
        if any(not dep for dep in normalized):
            raise ValueError(f"planner step {sid} contains an empty dependency")
        unknown = normalized - id_set
        if unknown:
            raise ValueError(f"planner returned unknown step dependencies: {', '.join(sorted(unknown)[:8])}")
        if sid in normalized:
            raise ValueError(f"planner returned a self dependency for step {sid}")
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
    postimage_existed: bool | None = None
    postimage_sha256: str = ""
    fencing_resource: str = ""
    fencing_lease_id: str = ""
    fencing_owner: str = ""
    fencing_token: int = 0
    attempt_id: str = ""
    attempt_token: int = 0


def _safe_work_target(root: Path | str, relative: str) -> Path:
    if not isinstance(relative, str) or not relative.strip() or "\x00" in relative:
        raise ValueError("unsafe work journal path")
    if not isinstance(root, (str, Path)) or "\x00" in str(root):
        raise ValueError("unsafe work journal root")
    resolved_root = Path(root).resolve()
    rel = Path(relative)
    if rel.is_absolute() or any(part in {"..", ""} for part in rel.parts):
        raise ValueError("unsafe work journal path")
    target = resolved_root
    for part in rel.parts:
        target = target / part
        try:
            metadata = target.lstat()
        except FileNotFoundError:
            continue
        reparse = bool(getattr(metadata, "st_file_attributes", 0) & 0x400)
        if stat.S_ISLNK(metadata.st_mode) or reparse:
            raise ValueError(f"refusing symlink or reparse path: {relative}")
    try:
        target.resolve(strict=False).relative_to(root)
    except (OSError, ValueError) as exc:
        raise ValueError(f"work journal path escapes repository: {relative}") from exc
    return target


class WorkOrchestrator:
    """Durable, serial whole-task executor for local coding work.

    The orchestrator intentionally reuses Local AI Hub's deterministic services,
    command broker, leases, artifacts and local model scheduler. It does not create
    a second agent runtime. Mutations are journalled outside git and rolled back on
    failed final verification unless the caller explicitly asks to preserve failure.
    """

    def __init__(
        self, config: dict[str, Any] | None, state_dir: Path, services: Any, commands: Any,
        leases: Any, artifacts: Any, telemetry: Any | None = None,
        verification_store: Any | None = None,
        fencing_store: FencingLeaseStore | None = None,
    ):
        raw_cfg = config.get("work_orchestrator") if isinstance(config, dict) else {}
        cfg = raw_cfg if isinstance(raw_cfg, dict) else {}
        self.enabled = bool(cfg.get("enabled", True))
        self.max_active = _bounded_int(cfg.get("max_active_work_orders"), 1, 1, 32)
        self.max_pending = _bounded_int(cfg.get("max_pending_work_orders"), 32, 1, 256)
        self.worker_idle_seconds = _safe_float(cfg.get("worker_idle_seconds"), 120.0, 5.0, 3600.0)
        self.max_steps = _bounded_int(cfg.get("max_steps"), 32, 1, 64)
        self.max_llm_calls = _bounded_int(cfg.get("max_llm_steps"), 16, 1, 32)
        self.max_replans = _bounded_int(cfg.get("max_replans"), 2, 0, 4)
        self.parallel_deterministic = _bounded_int(cfg.get("parallel_deterministic_steps"), 2, 1, 4)
        self.default_seconds = _bounded_int(cfg.get("max_seconds"), 900, 30, 7200)
        self.max_patch_files = _bounded_int(cfg.get("max_patch_files"), 24, 1, 128)
        self.max_patch_bytes = _bounded_int(cfg.get("max_patch_bytes"), 524288, 4096, 4 * 1024 * 1024)
        self.step_retry_limit = _bounded_int(cfg.get("step_retry_limit"), 2, 0, 4)
        self.rollback_on_failure = bool(cfg.get("rollback_on_failure", True))
        self.allow_edits = bool(cfg.get("allow_edits", True))
        self.allow_create = bool(cfg.get("allow_create", True))
        self.allow_delete = bool(cfg.get("allow_delete", True))
        self.validation_limit = _bounded_int(cfg.get("validation_commands"), 3, 1, 8)
        self.default_response_profile = str(cfg.get("default_response_profile", "compact") or "compact")
        self.default_max_output_tokens = max(0, _bounded_int(cfg.get("default_max_output_tokens"), 350, 0, 100000))
        self.services, self.commands, self.leases, self.artifacts = services, commands, leases, artifacts
        clean_state_dir = str(state_dir).replace("\x00", "")
        self.fencing_store = fencing_store or FencingLeaseStore(Path(clean_state_dir) / "work_fencing.sqlite3")
        set_fencing_store = getattr(self.commands, "set_fencing_lease_store", None)
        if callable(set_fencing_store):
            set_fencing_store(self.fencing_store)
        self.telemetry = telemetry
        self.verification_store = (
            verification_store
            if verification_store is not None
            else getattr(services, "verification_store", None)
        )
        self.path = Path(state_dir) / "work_orders.sqlite3"
        self.journal_dir = Path(state_dir) / "work_journals"
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._waiters: dict[str, threading.Event] = {}
        self._workers: list[threading.Thread] = []
        self._lock = threading.RLock()
        self._recovery_timer: threading.Timer | None = None
        self._recovery_retry_requested = False
        self._init_db()
        self._worker: threading.Thread | None = None
        self._recover()
        # Work execution is lazy. Most LocalAIApp instances only use retrieval or
        # status APIs; eagerly starting another polling thread for each instance
        # caused avoidable background load in embedded/test workloads.
        if self._has_queued_work():
            self._ensure_workers()

    def is_enabled(self) -> bool:
        """Return True if whole-task orchestrator is enabled."""
        return bool(self.enabled)

    def max_active_orders(self) -> int:
        """Return maximum number of concurrently active work orders."""
        return int(self.max_active)

    def default_timeout_seconds(self) -> int:
        """Return default maximum run duration for work orders in seconds."""
        return int(self.default_seconds)

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self.path, timeout_seconds=2.0, isolation_level=None, row_factory=sqlite3.Row)

    def _coordination_id(self, root: str | Path) -> str | None:
        """Use producer identity for lease scope; keep root identity physical."""
        from .project_config import resolve_project_context

        return resolve_project_context(root, self.path.parent).coordination_id

    def _init_db(self) -> None:
        expected_columns = {
            "work_id", "root", "task", "state", "payload_json", "result_json",
            "cancel_requested", "created_at", "updated_at",
        }
        if self.path.exists():
            read_only_uri = self.path.resolve().as_uri() + "?mode=ro"
            with closing(sqlite3.connect(read_only_uri, uri=True, timeout=2.0)) as check:
                check.execute("PRAGMA query_only=ON")
                table = check.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='work_orders'"
                ).fetchone()
                if table:
                    columns = {
                        str(row[1])
                        for row in check.execute("PRAGMA table_info(work_orders)").fetchall()
                    }
                    if columns != expected_columns:
                        raise RuntimeError(
                            "unsupported work_orders database schema; explicit offline conversion required"
                        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as con:
            con.executescript("""
            CREATE TABLE IF NOT EXISTS work_orders(
              work_id TEXT PRIMARY KEY, root TEXT NOT NULL, task TEXT NOT NULL,
              state TEXT NOT NULL, payload_json TEXT NOT NULL, result_json TEXT NOT NULL DEFAULT '{}',
              cancel_requested INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL, updated_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_work_orders_state_created ON work_orders(state, created_at);
            CREATE INDEX IF NOT EXISTS idx_work_orders_updated ON work_orders(updated_at DESC);
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
            {
                "path": entry.path,
                "existed": entry.existed,
                "data": base64.b64encode(entry.data).decode("ascii"),
                "postimage_existed": entry.postimage_existed,
                "postimage_sha256": entry.postimage_sha256,
                "fencing_resource": entry.fencing_resource,
                "fencing_lease_id": entry.fencing_lease_id,
                "fencing_owner": entry.fencing_owner,
                "fencing_token": entry.fencing_token,
                "attempt_id": entry.attempt_id,
                "attempt_token": entry.attempt_token,
            }
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
                existed = item.get("existed")
                if type(existed) is not bool:
                    raise ValueError("invalid work journal preimage state")
                data = base64.b64decode(str(item.get("data", "")), validate=True)
                if not existed and data:
                    raise ValueError("absent work journal preimage contains data")
                postimage_existed = item.get("postimage_existed")
                postimage_sha256 = str(item.get("postimage_sha256", ""))
                fencing_resource = str(item.get("fencing_resource", ""))
                fencing_lease_id = str(item.get("fencing_lease_id", ""))
                fencing_owner = str(item.get("fencing_owner", ""))
                fencing_token = item.get("fencing_token", 0)
                attempt_id = str(item.get("attempt_id", ""))
                attempt_token = item.get("attempt_token", 0)
                if type(fencing_token) is not int or fencing_token < 0:
                    raise ValueError("invalid work journal fencing token")
                if type(attempt_token) is not int or attempt_token < 0:
                    raise ValueError("invalid work journal attempt token")
                if fencing_token and not all((fencing_resource, fencing_lease_id, fencing_owner)):
                    raise ValueError("incomplete work journal fencing identity")
                if fencing_token and (not attempt_id or attempt_token <= 0):
                    raise ValueError("incomplete work journal attempt identity")
                if postimage_existed is not None and type(postimage_existed) is not bool:
                    raise ValueError("invalid work journal postimage state")
                if (
                    postimage_existed is None and postimage_sha256
                    or postimage_existed is not None
                    and not re.fullmatch(r"[0-9a-f]{64}", postimage_sha256)
                ):
                    raise ValueError("invalid work journal postimage digest")
                entries.append(
                    _JournalEntry(
                        rel,
                        existed,
                        data,
                        postimage_existed,
                        postimage_sha256,
                        fencing_resource,
                        fencing_lease_id,
                        fencing_owner,
                        fencing_token,
                        attempt_id,
                        attempt_token,
                    )
                )
            return entries
        except Exception:
            # A corrupt recovery journal must never be used to write repository files.
            return None

    def _clear_journal(
        self, work_id: str, *, attempt: WorkAttemptFence | None = None
    ) -> None:
        guard = self._state_attempt_guard(work_id, attempt)
        with guard:
            self._persist_journal(work_id, [])

    def _record_recovery_checkpoint(self, work_id: str, journal: list[_JournalEntry]) -> bool:
        manifest = [
            {
                "path": entry.path,
                "existed": entry.existed,
                "content_sha256": hashlib.sha256(entry.data).hexdigest(),
                "postimage_existed": entry.postimage_existed,
                "postimage_sha256": entry.postimage_sha256,
                "fencing_resource": entry.fencing_resource,
                "fencing_lease_id": entry.fencing_lease_id,
                "fencing_owner": entry.fencing_owner,
                "fencing_token": entry.fencing_token,
                "attempt_id": entry.attempt_id,
                "attempt_token": entry.attempt_token,
            }
            for entry in journal
        ]
        checkpoint = {
            "version": 1,
            "work_id": work_id,
            "rollback_complete": True,
            "journal_sha256": hashlib.sha256(
                json_dumps(manifest, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        }
        with closing(self._connect()) as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute(
                "SELECT result_json,state FROM work_orders WHERE work_id=?",
                (work_id,),
            ).fetchone()
            if row is None or str(row["state"]) not in {
                "planning", "executing", "verifying", "integrating"
            }:
                con.execute("ROLLBACK")
                return False
            result = json.loads(str(row["result_json"] or "{}"))
            result["_recovery_checkpoint"] = checkpoint
            updated = con.execute(
                "UPDATE work_orders SET result_json=?,updated_at=? WHERE work_id=? AND state=?",
                (
                    json_dumps(result, ensure_ascii=False, separators=(",", ":")),
                    time.time(),
                    work_id,
                    str(row["state"]),
                ),
            )
            con.execute("COMMIT")
            return int(updated.rowcount or 0) == 1

    def _recover(self) -> None:
        self._recovery_retry_requested = False
        transient = ("planning", "executing", "verifying", "integrating")
        with closing(self._connect()) as con:
            rows = con.execute(
                "SELECT work_id,root,state,result_json FROM work_orders WHERE state IN (?,?,?,?)", transient
            ).fetchall()
        now = time.time()
        for row in rows:
            work_id = str(row["work_id"])
            lease_owner = f"work-recovery:{work_id}"
            state = str(row["state"])
            try:
                prior_result = json.loads(str(row["result_json"] or "{}"))
            except Exception:
                prior_result = {}
            checkpoint = prior_result.get("_recovery_checkpoint")
            journal = self._load_journal(work_id)
            recovered = journal is not None
            deferred = False
            state_attempt: WorkAttemptFence | None = None
            if journal:
                fence: FencingLease | None = None
                attempt: WorkAttemptFence | None = None
                advisory_lease_id = ""
                try:
                    root = Path(str(row["root"])).resolve(strict=False)
                    coordination_id = self._coordination_id(root)
                    if any(
                        entry.fencing_token <= 0
                        or entry.fencing_resource != canonical_resource(root)
                        or not entry.fencing_lease_id
                        or not entry.fencing_owner
                        or not entry.attempt_id
                        or entry.attempt_token <= 0
                        for entry in journal
                    ):
                        raise RuntimeError("work journal lacks authoritative writer fencing metadata")
                    paths = normalize_paths([entry.path for entry in journal], root=root)
                    claim = self.leases.claim_batch(
                        owner=lease_owner,
                        root=str(root),
                        paths=list(paths),
                        ttl_seconds=900,
                        purpose=f"work-recovery:{work_id}",
                        coordination_id=coordination_id,
                    )
                    if not claim.get("success"):
                        raise LeaseUnavailableError("recovery path lease unavailable")
                    advisory_lease_id = str(claim.get("lease_id", ""))
                    try:
                        attempt = self.fencing_store.claim_attempt(
                            str(root),
                            work_id,
                            f"recovery:{work_id}:{uuid.uuid4().hex}",
                            ttl_seconds=900,
                            coordination_id=coordination_id,
                        )
                    except LeaseUnavailableError:
                        raise
                    except Exception:
                        deferred = True
                        raise
                    state_attempt = attempt
                    fence = self.fencing_store.acquire(
                        str(root),
                        f"recovery:{work_id}:{uuid.uuid4().hex}",
                        paths,
                        ttl_seconds=900,
                        attempt=attempt,
                        coordination_id=coordination_id,
                    )
                    with self.fencing_store.commit_guard(fence, paths):
                        self._rollback(root, journal)
                        if not self._record_recovery_checkpoint(work_id, journal):
                            raise RuntimeError("work recovery state changed before checkpoint")
                        self._clear_journal(work_id)
                except LeaseUnavailableError:
                    # A live owner may still be committing. Preserve the transient
                    # row and journal so the scheduled retry can recover after its TTL.
                    deferred = True
                except Exception:
                    recovered = False
                finally:
                    if fence is not None:
                        try:
                            self.fencing_store.release(fence)
                        except Exception:
                            pass
                    if advisory_lease_id:
                        try:
                            self.leases.release(owner=lease_owner, lease_id=advisory_lease_id)
                        except Exception:
                            pass
            else:
                try:
                    recovery_root = str(Path(str(row["root"])).resolve(strict=False))
                    state_attempt = self.fencing_store.claim_attempt(
                        recovery_root,
                        work_id,
                        f"recovery-empty:{work_id}:{uuid.uuid4().hex}",
                        ttl_seconds=900,
                        coordination_id=self._coordination_id(recovery_root),
                    )
                except LeaseUnavailableError:
                    # A running attempt may not have written its journal yet.
                    deferred = True
                except Exception:
                    recovered = False
                    deferred = True
            if journal == [] and not deferred:
                # A missing journal is safe only when there is no evidence that a
                # prior process had already mutated the workspace.
                checkpoint_valid = (
                    isinstance(checkpoint, dict)
                    and checkpoint.get("version") == 1
                    and checkpoint.get("work_id") == work_id
                    and checkpoint.get("rollback_complete") is True
                )
                if not checkpoint_valid and prior_result.get("changed_files"):
                    recovered = False
            if deferred:
                if state_attempt is not None:
                    try:
                        self.fencing_store.release_attempt(state_attempt)
                    except Exception:
                        pass
                self._recovery_retry_requested = True
                continue
            try:
                guard = (
                    self.fencing_store.attempt_guard(state_attempt)
                    if state_attempt is not None else nullcontext()
                )
                with guard:
                    with closing(self._connect()) as con:
                        con.execute("BEGIN IMMEDIATE")
                        if recovered:
                            con.execute(
                                "UPDATE work_orders SET state='queued',result_json='{}',updated_at=? WHERE work_id=? AND state=?",
                                (now, work_id, state),
                            )
                        else:
                            result = json_dumps({
                                "summary": "work order recovery failed",
                                "error": "transaction journal could not be safely restored; manual inspection required",
                                "needs_agent": True,
                            }, separators=(",", ":"))
                            con.execute(
                                "UPDATE work_orders SET state='needs_agent',result_json=?,updated_at=? WHERE work_id=? AND state=?",
                                (result, now, work_id, state),
                            )
                        con.execute("COMMIT")
            except LeaseLostError:
                self._recovery_retry_requested = True
                continue
            finally:
                if state_attempt is not None:
                    try:
                        self.fencing_store.release_attempt(state_attempt)
                    except Exception:
                        pass

        # Completion is durable before its journal is removed. If the process
        # stops between those writes, keep committed workspace and discard only
        # the now-obsolete rollback snapshot on restart.
        with closing(self._connect()) as con:
            completed = con.execute(
                "SELECT work_id FROM work_orders WHERE state='complete'"
            ).fetchall()
        for row in completed:
            work_id = str(row["work_id"])
            journal = self._load_journal(work_id)
            if journal is None or journal:
                try:
                    self._clear_journal(work_id)
                except OSError:
                    # Keep a failed cleanup retryable on the next startup.
                    pass
        if self._recovery_retry_requested:
            self._schedule_recovery_retry()

    def _schedule_recovery_retry(self) -> None:
        """Retry deferred crash recovery while a prior writer's lease is live."""
        if self._stop.is_set():
            return
        with self._lock:
            if self._recovery_timer is not None and self._recovery_timer.is_alive():
                return
            timer = threading.Timer(30.0, self._retry_deferred_recovery)
            timer.name = "local-ai-work-recovery-retry"
            timer.daemon = True
            self._recovery_timer = timer
            timer.start()

    def _retry_deferred_recovery(self) -> None:
        with self._lock:
            self._recovery_timer = None
        if self._stop.is_set():
            return
        self._recover()
        if self._has_queued_work():
            self._ensure_workers()

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

    def submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        if "tenant" in payload:
            return {"success": False, "error": "retired work-order field: tenant", "terminal": True}
        if not self.enabled:
            return {"success": False, "unsupported": True, "error": "work orchestrator disabled"}
        raw_root = str(payload.get("root", "")).strip()
        if not raw_root or not is_rooted_path(raw_root):
            return {"success": False, "error": "root must be an explicit absolute repository directory", "terminal": True}
        root = Path(raw_root).expanduser().resolve(strict=False)
        raw_task = payload.get("task", "")
        if not isinstance(raw_task, str) or "\x00" in raw_task or len(raw_task) > 24000:
            return {"success": False, "error": "task must be a string of at most 24000 characters without NUL", "terminal": True}
        task = raw_task.strip()
        if not root.is_dir():
            return {"success": False, "error": "root must be an existing absolute repository directory", "terminal": True}
        if not task:
            return {"success": False, "error": "task is required", "terminal": True}
        work_id = str(payload.get("work_id", "")).strip() or f"wo_{uuid.uuid4().hex[:20]}"
        if len(work_id) > 128 or any(ord(ch) < 32 for ch in work_id):
            return {"success": False, "error": "work_id must be at most 128 printable characters", "terminal": True}
        raw_task_id = payload.get("task_id", "")
        if raw_task_id is None:
            raw_task_id = ""
        if not isinstance(raw_task_id, str):
            return {"success": False, "error": "task_id must be a string when supplied", "terminal": True}
        task_id = raw_task_id.strip()
        if len(task_id) > 128 or any(ord(ch) < 32 for ch in task_id):
            return {"success": False, "error": "task_id must be at most 128 printable characters", "terminal": True}
        raw_acceptance = payload.get("acceptance_criteria")
        if (not isinstance(raw_acceptance, list) or not raw_acceptance or len(raw_acceptance) > 24
                or any(not isinstance(item, str) or not item.strip() or "\x00" in item or len(item.strip()) > 2000
                       for item in raw_acceptance)):
            return {"success": False, "error": "work order requires explicit non-empty string acceptance criteria", "terminal": True}
        acceptance = [item.strip() for item in raw_acceptance]
        permissions = payload.get("permissions", {})
        if (not isinstance(permissions, dict) or set(permissions) - _WORK_PERMISSION_FIELDS
                or any(type(value) is not bool for value in permissions.values())):
            return {"success": False, "error": "work order permissions must contain only supported boolean fields", "terminal": True}
        if permissions.get("read") is False:
            return {"success": False, "error": "work orders require repository read permission", "terminal": True}
        budgets = payload.get("budget", {})
        if not isinstance(budgets, dict):
            return {"success": False, "error": "work order budget must be an object", "terminal": True}
        if set(budgets) - {"max_steps", "max_llm_calls", "max_seconds", "max_tokens", "max_edits", "max_commands"}:
            return {"success": False, "error": "work order budget contains unsupported fields", "terminal": True}
        hard_max_steps = min(self.max_steps, 16)
        try:
            requested_max_steps = _budget_int(budgets.get("max_steps", hard_max_steps), "max_steps")
        except ValueError as exc:
            return {"success": False, "error": str(exc), "terminal": True}
        if requested_max_steps < 1 or requested_max_steps > hard_max_steps:
            return {"success": False, "error": f"work order max_steps must be between 1 and {hard_max_steps}", "terminal": True}
        execution_budgets: dict[str, int] = {}
        for name, default, lower, upper in (
            ("max_llm_calls", self.max_llm_calls, 1, self.max_llm_calls),
            ("max_seconds", self.default_seconds, 30, 7200),
        ):
            if name not in budgets:
                execution_budgets[name] = default
                continue
            try:
                value = _budget_int(budgets[name], name)
            except ValueError as exc:
                return {"success": False, "error": str(exc), "terminal": True}
            if value < lower or value > upper:
                return {"success": False, "error": f"work order {name} must be between {lower} and {upper}", "terminal": True}
            execution_budgets[name] = value
        planner_budgets: dict[str, int] = {}
        for name, lower, upper in (
            ("max_tokens", 128, 1400),
            ("max_edits", 0, requested_max_steps),
            ("max_commands", 0, requested_max_steps),
        ):
            if name not in budgets:
                continue
            try:
                limit = _budget_int(budgets[name], name)
            except ValueError as exc:
                return {"success": False, "error": str(exc), "terminal": True}
            if limit < lower or limit > upper:
                return {"success": False, "error": f"work order {name} must be between {lower} and {upper}", "terminal": True}
            planner_budgets[name] = limit
        raw_mode = payload.get("mode", "execute")
        if not isinstance(raw_mode, str) or not raw_mode.strip():
            return {"success": False, "error": "work order mode must be a non-empty string", "terminal": True}
        mode = raw_mode.strip().lower().replace("-", "_")
        if mode not in {"execute", "plan", "plan_only", "dry_run"}:
            return {"success": False, "error": "mode must be execute, plan, plan_only, or dry_run", "terminal": True}
        if mode == "execute" and (permissions.get("tests") is False or permissions.get("build") is False):
            return {"success": False, "error": "execute mode requires both test and build permissions; selective validation is unsupported", "terminal": True}
        keep_failed = payload.get("keep_failed_workspace", False)
        if type(keep_failed) is not bool:
            return {"success": False, "error": "keep_failed_workspace must be a boolean", "terminal": True}
        profile = str(payload.get("response_profile", self.default_response_profile) or self.default_response_profile).strip().lower()
        if profile not in {"minimal", "compact", "standard", "debug"}:
            profile = self.default_response_profile if self.default_response_profile in {"minimal", "compact", "standard", "debug"} else "compact"
        return_fields = _string_list(payload.get("return_fields"), limit=32, item_chars=80)
        normalized = {
            "task_id": task_id,
            "acceptance_criteria": acceptance,
            "constraints": _string_list(payload.get("constraints"), limit=24, item_chars=2000),
            "mode": mode,
            "permissions": _permission_map(permissions),
            "budget": {
                "max_steps": requested_max_steps,
                **execution_budgets,
                **planner_budgets,
            },
            "response_profile": profile,
            "return_fields": return_fields,
            "max_output_tokens": _bounded_int(payload.get("max_output_tokens"), self.default_max_output_tokens, 0, 4096),
            "keep_failed_workspace": keep_failed,
        }
        now = time.time()
        try:
            with closing(self._connect()) as con:
                # Serialize admission so concurrent submitters cannot all observe the
                # same free slot and overflow the configured bounded queue.
                con.execute("BEGIN IMMEDIATE")
                try:
                    existing = con.execute(
                        "SELECT * FROM work_orders WHERE work_id=?",
                        (work_id,),
                    ).fetchone()
                    if existing is not None:
                        existing_payload = json.loads(str(existing["payload_json"] or "{}"))
                        if (
                            str(existing["root"]) != str(root)
                            or str(existing["task"]) != task
                            or existing_payload != normalized
                        ):
                            con.execute("ROLLBACK")
                            return {
                                "success": False,
                                "error": "work_id already exists with different request",
                                "work_id": work_id,
                                "terminal": True,
                            }
                        con.execute("COMMIT")
                        return self._canonical(existing)
                    pending = con.execute(
                        "SELECT COUNT(*) FROM work_orders WHERE state IN ('queued','planning','executing','integrating','verifying')"
                    ).fetchone()
                    if pending and int(pending[0]) >= self.max_pending:
                        con.execute("ROLLBACK")
                        return {"success": False, "error": "work-order queue is full", "retryable": True, "terminal": False}
                    con.execute("INSERT INTO work_orders(work_id,root,task,state,payload_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                                (work_id, str(root), task, "queued", json_dumps(normalized, separators=(",", ":")), now, now))
                    con.execute("COMMIT")
                except Exception:
                    con.execute("ROLLBACK")
                    raise
        except sqlite3.IntegrityError:
            return {"success": False, "error": "work_id already exists", "work_id": work_id, "terminal": True}
        self._ensure_workers(); self._wake.set()
        return self._project({"success": True, "status": "queued", "work_id": work_id, "summary": "whole task accepted"}, normalized)

    def _row(self, work_id: str) -> sqlite3.Row | None:
        def query() -> sqlite3.Row | None:
            with closing(self._connect()) as con:
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

    def status(self, work_id: str) -> dict[str, Any]:
        row = self._row(work_id)
        return self._canonical(row) if row else {"success": False, "error": "work order not found", "work_id": work_id}

    def get(self, work_id: str, *, profile: str = "", return_fields: list[str] | None = None, max_output_tokens: int = 0) -> dict[str, Any]:
        row = self._row(work_id)
        if not row:
            return {"success": False, "error": "work order not found", "work_id": work_id}
        payload = json.loads(str(row["payload_json"] or "{}"))
        if profile: payload["response_profile"] = profile
        if return_fields is not None: payload["return_fields"] = return_fields
        if max_output_tokens: payload["max_output_tokens"] = max_output_tokens
        result = json.loads(str(row["result_json"] or "{}"))
        return self._project({"success": str(row["state"]) not in {"failed", "cancelled"}, "status": str(row["state"]), "work_id": work_id, **result}, payload)

    def wait(self, work_id: str, timeout_seconds: float = 90) -> dict[str, Any]:
        started = time.perf_counter()
        deadline = time.monotonic() + max(0.0, min(float(timeout_seconds), 90.0))
        while time.monotonic() < deadline:
            row = self._row(work_id)
            if not row:
                result = {"success": False, "error": "work order not found", "work_id": work_id}
                self._record_wait(result, started)
                return result
            if str(row["state"]) in _TERMINAL:
                result = self._canonical(row)
                self._record_wait(result, started)
                return result
            event = self._event(work_id)
            event.wait(min(0.5, max(0.0, deadline - time.monotonic())))
            event.clear()
        result = self.status(work_id)
        result["in_progress"] = result.get("status") not in _TERMINAL
        self._record_wait(result, started)
        return result

    def _record_wait(self, result: dict[str, Any], started: float) -> None:
        if self.telemetry is None:
            return
        try:
            elapsed_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
            self.telemetry.record(
                event_type="coordination", action="work_wait",
                success=bool(result.get("success")), duration_ms=elapsed_ms,
                wait_count=1, wait_duration_ms=elapsed_ms,
            )
        except Exception:
            pass

    def cancel(self, work_id: str) -> dict[str, Any]:
        row = self._row(work_id)
        if not row:
            return {"success": False, "error": "work order not found", "work_id": work_id}
        terminal_marks = ",".join("?" for _ in _TERMINAL)
        with closing(self._connect()) as con:
            changed = con.execute(
                f"UPDATE work_orders SET cancel_requested=1,updated_at=? WHERE work_id=? AND state NOT IN ({terminal_marks})",
                (time.time(), work_id, *sorted(_TERMINAL)),
            ).rowcount
        if not changed:
            current = self._row(work_id)
            return self._canonical(current) if current else {"success": False, "error": "work order not found", "work_id": work_id}
        self._wake.set(); self._event(work_id).set()
        return {"success": True, "status": "cancelling", "work_id": work_id}

    def continue_work(self, work_id: str, answer: str) -> dict[str, Any]:
        row = self._row(work_id)
        if not row:
            return {"success": False, "error": "work order not found", "work_id": work_id}
        if str(row["state"]) != "needs_agent":
            return {"success": False, "error": "work order is not waiting for agent input", "work_id": work_id}
        payload = json.loads(str(row["payload_json"] or "{}")); payload["agent_answer"] = str(answer).strip()[:8000]
        if not payload["agent_answer"]:
            return {"success": False, "error": "answer is required", "work_id": work_id}
        with closing(self._connect()) as con:
            changed = con.execute(
                "UPDATE work_orders SET state='queued',payload_json=?,cancel_requested=0,updated_at=? WHERE work_id=? AND state='needs_agent' AND cancel_requested=0",
                (json_dumps(payload, separators=(",", ":")), time.time(), work_id),
            ).rowcount
        if not changed:
            return {"success": False, "error": "work order state changed", "work_id": work_id}
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

    def _set_state(
        self, work_id: str, state: str, result: dict[str, Any], *,
        attempt: WorkAttemptFence | None = None,
    ) -> None:
        guard = self._state_attempt_guard(work_id, attempt)
        with guard:
            with closing(self._connect()) as con:
                terminal_marks = ",".join("?" for _ in _TERMINAL)
                changed = con.execute(
                    f"UPDATE work_orders SET state=?,result_json=?,updated_at=? "
                    f"WHERE work_id=? AND state NOT IN ({terminal_marks})",
                    (state, json_dumps(result, ensure_ascii=False, separators=(",", ":")), time.time(), work_id, *sorted(_TERMINAL)),
                ).rowcount
        if int(changed or 0) != 1:
            raise LeaseLostError("work order is terminal or unavailable")
        with self._lock:
            event = self._waiters.get(work_id)
            if event is not None:
                event.set()
                if state in _TERMINAL:
                    self._waiters.pop(work_id, None)

    def _state_attempt_guard(
        self, work_id: str, attempt: WorkAttemptFence | None
    ):
        if attempt is None:
            return nullcontext()
        if attempt.work_id != work_id:
            raise LeaseLostError("work attempt does not own this work order")
        return self.fencing_store.attempt_guard(attempt)

    def _persist_handoff_receipts(
        self, work_id: str, receipts: list[Any], validation: list[dict[str, Any]], *,
        attempt: WorkAttemptFence | None = None,
    ) -> list[Any]:
        from .agent_verification import VerificationReceipt

        guard = self._state_attempt_guard(work_id, attempt)
        with guard:
            serialized = [receipt.to_dict() for receipt in receipts]
            with closing(self._connect()) as con:
                row = con.execute(
                    "SELECT result_json FROM work_orders WHERE work_id=?", (work_id,)
                ).fetchone()
                if row is None:
                    raise RuntimeError("verification receipt work record is unavailable")
                result = json.loads(str(row[0] or "{}"))
                if not isinstance(result, dict):
                    raise RuntimeError("verification receipt work record is invalid")
                result["validation"] = validation
                result["verification_receipts"] = serialized
                con.execute(
                    "UPDATE work_orders SET result_json=?,updated_at=? WHERE work_id=?",
                    (json_dumps(result, ensure_ascii=False, separators=(",", ":")), time.time(), work_id),
                )

            with closing(self._connect()) as con:
                row = con.execute(
                    "SELECT result_json FROM work_orders WHERE work_id=?", (work_id,)
                ).fetchone()
            if row is None:
                raise RuntimeError("persisted verification receipt work record is unavailable")
            stored = json.loads(str(row[0] or "{}"))
            if not isinstance(stored, dict) or not isinstance(stored.get("verification_receipts"), list):
                raise RuntimeError("persisted verification receipts are invalid")
            return [VerificationReceipt.from_dict(item) for item in stored["verification_receipts"]]

    def _complete_if_not_cancelled(
        self, work_id: str, result: dict[str, Any], *, expected_state: str = "verifying",
        attempt: WorkAttemptFence | None = None,
    ) -> bool:
        guard = self._state_attempt_guard(work_id, attempt)
        with guard:
            with closing(self._connect()) as con:
                changed = con.execute(
                    "UPDATE work_orders SET state='complete',result_json=?,updated_at=? WHERE work_id=? AND state=? AND cancel_requested=0",
                    (json_dumps(result, ensure_ascii=False, separators=(",", ":")), time.time(), work_id, expected_state),
                ).rowcount
        if changed:
            with self._lock:
                event = self._waiters.get(work_id)
                if event is not None:
                    event.set()
                    self._waiters.pop(work_id, None)
        return bool(changed)

    def _set_terminal_if_active(
        self, work_id: str, state: str, result: dict[str, Any], *,
        attempt: WorkAttemptFence | None = None,
    ) -> bool:
        terminal_marks = ",".join("?" for _ in _TERMINAL)
        guard = self._state_attempt_guard(work_id, attempt)
        with guard:
            with closing(self._connect()) as con:
                changed = con.execute(
                    f"UPDATE work_orders SET state=?,result_json=?,updated_at=? WHERE work_id=? AND state NOT IN ({terminal_marks})",
                    (state, json_dumps(result, ensure_ascii=False, separators=(",", ":")), time.time(), work_id, *sorted(_TERMINAL)),
                ).rowcount
        if changed:
            with self._lock:
                event = self._waiters.get(work_id)
                if event is not None:
                    event.set()
                    self._waiters.pop(work_id, None)
        return bool(changed)

    def _fail_if_not_cancelled(
        self, work_id: str, result: dict[str, Any], *, attempt: WorkAttemptFence | None = None
    ) -> bool:
        terminal_marks = ",".join("?" for _ in _TERMINAL)
        guard = self._state_attempt_guard(work_id, attempt)
        with guard:
            with closing(self._connect()) as con:
                changed = con.execute(
                    f"UPDATE work_orders SET state='failed',result_json=?,updated_at=? WHERE work_id=? AND state NOT IN ({terminal_marks}) AND cancel_requested=0",
                    (json_dumps(result, ensure_ascii=False, separators=(",", ":")), time.time(), work_id, *sorted(_TERMINAL)),
                ).rowcount
        if changed:
            with self._lock:
                event = self._waiters.get(work_id)
                if event is not None:
                    event.set()
                    self._waiters.pop(work_id, None)
        return bool(changed)

    def _set_terminal_if_not_cancelled(
        self, work_id: str, state: str, result: dict[str, Any], *,
        attempt: WorkAttemptFence | None = None,
    ) -> bool:
        terminal_marks = ",".join("?" for _ in _TERMINAL)
        guard = self._state_attempt_guard(work_id, attempt)
        with guard:
            with closing(self._connect()) as con:
                changed = con.execute(
                    f"UPDATE work_orders SET state=?,result_json=?,updated_at=? WHERE work_id=? AND state NOT IN ({terminal_marks}) AND cancel_requested=0",
                    (state, json_dumps(result, ensure_ascii=False, separators=(",", ":")), time.time(), work_id, *sorted(_TERMINAL)),
                ).rowcount
        if changed:
            with self._lock:
                event = self._waiters.get(work_id)
                if event is not None:
                    event.set()
                    self._waiters.pop(work_id, None)
        return bool(changed)

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
                        work_id = str(row["work_id"])
                        failure = {"summary": "work order failed", "error": f"{type(exc).__name__}: {exc}"}
                        if not self._fail_if_not_cancelled(work_id, failure):
                            self._set_terminal_if_active(work_id, "cancelled", {"summary": "work order cancelled during worker recovery"})
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

    def _ask(
        self,
        root: str,
        task: str,
        context: str,
        max_tokens: int = 4096,
        *,
        review: bool = False,
        complexity: str = "auto",
        task_type: str = "auto",
    ) -> dict[str, Any]:
        if review:
            return self.services.second_opinion({"question": task, "candidate": context, "context": "", "max_tokens": max_tokens, "complexity": "auto"})
        return self.services.delegate_repo({"root": root, "task": task, "context": context, "max_tokens": max_tokens, "complexity": complexity, "task_type": task_type})

    def _plan(self, root: str, task: str, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        acceptance = _string_list(payload.get("acceptance_criteria"), limit=24, item_chars=2000)
        if not acceptance:
            raise ValueError("work order requires explicit acceptance criteria")
        budget = payload.get("budget")
        if budget is None:
            budget = {}
        if not isinstance(budget, dict):
            raise ValueError("work order budget must be an object")
        hard_max_steps = min(self.max_steps, 16)
        requested_max_steps = _budget_int(budget.get("max_steps", hard_max_steps), "max_steps")
        if requested_max_steps < 1 or requested_max_steps > hard_max_steps:
            raise ValueError(f"work order max_steps must be between 1 and {hard_max_steps}")
        requested_max_tokens = _budget_int(budget.get("max_tokens", 1400), "max_tokens")
        if requested_max_tokens < 128 or requested_max_tokens > 1400:
            raise ValueError("work order max_tokens must be between 128 and 1400")
        prompt = (
            "PLAN A CODING WORK ORDER. Return STRICT JSON only: "
            '{"summary":"...","needs_agent":false,"question":"","steps":[{"id":"s1","kind":"inspect|edit|validate|review|integrate","task":"...","depends_on":[],"acceptance":["..."]}],"validation_commands":[]}.'
            " Make steps the smallest independently executable+verifiable units, not trivial microsteps. Max 16 steps. "
            "Use deterministic inspection before edits. Include edit steps only if requested. Do not invent files unless evidence supports them.\n"
            f"ORIGINAL TASK:\n{task}\nACCEPTANCE:\n{json_dumps(acceptance, ensure_ascii=False)}\n"
            f"CONSTRAINTS:\n{json_dumps(payload.get('constraints') or [], ensure_ascii=False)}"
            + (f"\nAGENT ANSWER TO PRIOR BLOCKER:\n{str(payload.get('agent_answer',''))[:8000]}" if payload.get("agent_answer") else "")
        )
        res = self._ask(root, prompt, json_dumps(context, ensure_ascii=False)[:14000], requested_max_tokens)
        parsed = _json_object(str(res.get("text", ""))) if isinstance(res, dict) and res.get("success", True) else None
        if not parsed or not isinstance(parsed.get("steps"), list):
            parsed = {"summary": task[:240], "needs_agent": False, "question": "", "steps": [
                {"id": "s1", "kind": "inspect", "task": task, "depends_on": [], "acceptance": []},
                {"id": "s2", "kind": "edit", "task": task, "depends_on": ["s1"], "acceptance": acceptance},
                {"id": "s3", "kind": "validate", "task": "Run the smallest relevant validation commands", "depends_on": ["s2"], "acceptance": acceptance},
                {"id": "s4", "kind": "review", "task": "Review the integrated change against the original task", "depends_on": ["s3"], "acceptance": acceptance},
            ], "validation_commands": []}
        raw_steps = parsed.get("steps", [])
        if len(raw_steps) > requested_max_steps:
            raise ValueError(f"planner returned more than the {requested_max_steps} step budget")
        cleaned=[]; seen=set()
        for i, raw in enumerate(raw_steps):
            if not isinstance(raw, dict):
                raise ValueError("planner returned a non-object step")
            sid = str(raw.get("id") or "").strip()[:40]
            if not sid:
                raise ValueError("planner returned an empty step id")
            if sid in seen:
                raise ValueError("planner returned duplicate planner step ids")
            seen.add(sid)
            kind=str(raw.get("kind", "inspect")).strip().lower()
            if kind not in {"inspect","edit","validate","review","integrate"}:
                raise ValueError(f"planner returned unknown planner step kind: {kind[:40]}")
            raw_dependencies = raw.get("depends_on", [])
            if not isinstance(raw_dependencies, list):
                raise ValueError(f"planner step {sid} dependencies must be a list")
            if any(not isinstance(dep, str) or not dep.strip() for dep in raw_dependencies):
                raise ValueError(f"planner step {sid} contains an invalid dependency")
            deps = [dep.strip() for dep in raw_dependencies]
            step_task=str(raw.get("task", "")).strip()[:2000] or f"{kind} work-order evidence"
            step_acceptance = _string_list(raw.get("acceptance"), limit=12, item_chars=2000) or acceptance[:12]
            cleaned.append({
                "id":sid, "kind":kind, "task":step_task, "depends_on":deps,
                "acceptance":step_acceptance,
                "state":"pending",
            })
        def declared_limit(name: str, default: int) -> int:
            limit = _budget_int(budget.get(name, default), name)
            if limit < 0 or limit > requested_max_steps:
                raise ValueError(f"work order {name} must be between 0 and {requested_max_steps}")
            return limit

        max_edit_steps = declared_limit("max_edits", requested_max_steps)
        if sum(step["kind"] == "edit" for step in cleaned) > max_edit_steps:
            raise ValueError(f"planner returned more than the {max_edit_steps} edit-step budget")
        raw_commands = parsed.get("validation_commands", [])
        if not isinstance(raw_commands, list) or any(not isinstance(command, str) or not command.strip() for command in raw_commands):
            raise ValueError("planner validation_commands must be a list of non-empty strings")
        max_commands = declared_limit("max_commands", requested_max_steps)
        if len(raw_commands) > max_commands:
            raise ValueError(f"planner returned more than the {max_commands} command budget")
        parsed["validation_commands"] = [command.strip() for command in raw_commands]
        parsed["acceptance_criteria"] = acceptance
        parsed["steps"] = _stable_toposort_steps(cleaned) if cleaned else [{"id":"s1","kind":"inspect","task":task,"depends_on":[],"acceptance":acceptance,"state":"pending"}]
        return parsed

    def _snapshot(self, root: Path, paths: list[str]) -> list[_JournalEntry]:
        root = root.resolve()
        entries=[]
        for rel in paths:
            p = _safe_work_target(root, rel)
            if p.exists() and p.is_dir(): raise ValueError(f"refusing to patch directory: {rel}")
            data=p.read_bytes() if p.exists() else b""
            if b"\x00" in data[:8192]: raise ValueError(f"refusing to edit binary file: {rel}")
            entries.append(_JournalEntry(rel,p.exists(),data))
        return entries

    @staticmethod
    def _failed_patch_source(root: Path, patch: str) -> str:
        """Return a small, path-confined preimage for a failed patch retry."""
        try:
            paths, _, _ = _patch_changes(patch)
        except Exception:
            return ""
        root = root.resolve()
        chunks: list[str] = []
        remaining = 12_000
        for rel in paths[:8]:
            lowered = rel.lower()
            if any(marker in lowered for marker in (
                ".env", "secret", "credential", "password", "token", "private",
                "api_key", "apikey", "id_rsa", "id_ed25519", ".pem", ".p12", ".pfx", ".key",
            )):
                continue
            try:
                target = _safe_work_target(root, rel)
                if not target.is_file():
                    continue
                data = target.read_bytes()
                if b"\x00" in data[:8192]:
                    continue
                source = data.decode("utf-8")
            except (OSError, UnicodeError, ValueError):
                continue
            header = f"\n--- {rel} (current workspace source) ---\n"
            available = remaining - len(header)
            if available <= 0:
                break
            clipped = source[:available]
            chunks.append(header + clipped)
            remaining -= len(header) + len(clipped)
            if len(clipped) < len(source) or remaining <= 0:
                chunks.append("\n[remaining source omitted to keep retry context bounded]\n")
                break
        if not chunks:
            return ""
        return "CURRENT SOURCE FOR FAILED PATCH PATHS:" + "".join(chunks)

    @staticmethod
    def _preview_postimages(patch: str, snapshot: list[_JournalEntry]) -> list[_JournalEntry]:
        """Compute patch outputs in an isolated directory before workspace mutation."""
        with tempfile.TemporaryDirectory(prefix="local-ai-work-preview-") as temporary:
            preview_root = Path(temporary)
            for entry in snapshot:
                if entry.existed:
                    path = preview_root / entry.path
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(entry.data)
            checked = subprocess.run(
                ["git", "-C", str(preview_root), "apply", "--recount", "--check", "--whitespace=nowarn", "-"],
                input=patch,
                capture_output=True,
                text=True,
                timeout=12,
                check=False,
                **hidden_run_kwargs(),
            )
            recount_used = True
            if checked.returncode != 0:
                fallback_check = subprocess.run(
                    ["git", "-C", str(preview_root), "apply", "--check", "--whitespace=nowarn", "-"],
                    input=patch,
                    capture_output=True,
                    text=True,
                    timeout=12,
                    check=False,
                    **hidden_run_kwargs(),
                )
                if fallback_check.returncode == 0:
                    checked = fallback_check
                    recount_used = False
                else:
                    raise ValueError((checked.stderr or checked.stdout or fallback_check.stderr or "git apply preview check failed")[:1000])
            applied_cmd = ["git", "-C", str(preview_root), "apply"]
            if recount_used:
                applied_cmd.append("--recount")
            applied_cmd.extend(["--whitespace=nowarn", "-"])
            applied = subprocess.run(
                applied_cmd,
                input=patch,
                capture_output=True,
                text=True,
                timeout=12,
                check=False,
                **hidden_run_kwargs(),
            )
            if applied.returncode != 0:
                raise ValueError((applied.stderr or applied.stdout or "git apply preview failed")[:1000])
            postimages: list[_JournalEntry] = []
            for entry in snapshot:
                path = preview_root / entry.path
                exists = path.exists()
                data = path.read_bytes() if exists else b""
                postimages.append(
                    _JournalEntry(
                        entry.path,
                        exists,
                        data,
                        exists,
                        hashlib.sha256(data).hexdigest(),
                    )
                )
            return postimages

    @staticmethod
    def _rollback(root: Path, journal: list[_JournalEntry]) -> None:
        root = root.resolve()
        targets: dict[str, Path] = {}
        for entry in journal:
            rel = str(entry.path).replace("\\", "/")
            parts = rel.split("/")
            if (
                not rel
                or rel.startswith("/")
                or re.match(r"^[A-Za-z]:", rel)
                or any(part in {"", ".", ".."} for part in parts)
            ):
                raise ValueError("unsafe work journal path")
            path = root.joinpath(*parts)
            resolved = path.resolve(strict=False)
            try:
                resolved.relative_to(root)
            except ValueError as exc:
                raise ValueError("work journal path escapes repository") from exc
            cursor = root
            for index, part in enumerate(parts):
                cursor = cursor / part
                try:
                    metadata = cursor.lstat()
                except FileNotFoundError:
                    continue
                attributes = int(getattr(metadata, "st_file_attributes", 0))
                reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
                if stat.S_ISLNK(metadata.st_mode) or attributes & reparse_flag:
                    raise ValueError("refusing to restore through a symlink or reparse point")
                if index < len(parts) - 1 and cursor.exists() and not cursor.is_dir():
                    raise RuntimeError(f"rollback refused non-directory ancestor: {entry.path}")
            if path.exists() and path.is_dir():
                raise ValueError(f"rollback refused directory path: {entry.path}")
            targets[entry.path] = path

        simulated: dict[str, tuple[bool, bytes]] = {}
        restore: list[_JournalEntry] = []
        for entry in reversed(journal):
            current = simulated.get(entry.path)
            if current is None:
                path = targets[entry.path]
                current = (path.exists(), path.read_bytes() if path.exists() else b"")
            before = (entry.existed, entry.data)
            if current == before:
                simulated[entry.path] = before
                continue
            postimage_matches = (
                entry.postimage_existed is not None
                and current[0] is entry.postimage_existed
                and hashlib.sha256(current[1]).hexdigest() == entry.postimage_sha256
            )
            if not postimage_matches:
                raise RuntimeError(f"rollback refused: postimage changed for {entry.path}")
            target = targets[entry.path]
            if entry.existed and target.exists() and target.stat().st_nlink > 1:
                raise RuntimeError(f"rollback refused hardlinked postimage: {entry.path}")
            restore.append(entry)
            simulated[entry.path] = before

        for entry in restore:
            path = targets[entry.path]
            if entry.existed:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(entry.data)
            else:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass

    def _rollback_transaction(
        self, work_id: str, root: Path, journal: list[_JournalEntry], *,
        keep: bool = False, attempt: WorkAttemptFence | None = None,
    ) -> bool:
        if not journal:
            self._clear_journal(work_id, attempt=attempt)
            return False
        root = root.resolve(strict=False)
        resource = canonical_resource(root)
        if attempt is not None and attempt.work_id != work_id:
            raise LeaseLostError("work attempt does not own this rollback journal")
        if any(
            entry.fencing_token <= 0
            or entry.fencing_resource != resource
            or not entry.fencing_lease_id
            or not entry.fencing_owner
            or not entry.attempt_id
            or entry.attempt_token <= 0
            for entry in journal
        ):
            raise RuntimeError("work journal lacks authoritative writer fencing metadata")
        paths = normalize_paths([entry.path for entry in journal], root=root)
        coordination_id = self._coordination_id(root)
        owns_attempt = attempt is None
        if attempt is None:
            attempt = self.fencing_store.claim_attempt(
                str(root), work_id, f"rollback:{work_id}:{uuid.uuid4().hex}", ttl_seconds=900,
                coordination_id=coordination_id,
            )
        fence: FencingLease | None = None
        try:
            fence = self.fencing_store.acquire(
                str(root), f"rollback:{work_id}:{uuid.uuid4().hex}", paths,
                ttl_seconds=900, attempt=attempt, coordination_id=coordination_id,
            )
            with self.fencing_store.commit_guard(fence, paths):
                if keep or not self.rollback_on_failure:
                    # The caller explicitly owns the partially-mutated workspace from here.
                    self._clear_journal(work_id)
                    return False
                self._rollback(root, journal)
                if not self._record_recovery_checkpoint(work_id, journal):
                    raise RuntimeError("work rollback state changed before checkpoint")
                journal.clear()
                self._clear_journal(work_id)
                return True
        finally:
            if fence is not None:
                try:
                    self.fencing_store.release(fence)
                except Exception:
                    pass
            if owns_attempt and attempt is not None:
                try:
                    self.fencing_store.release_attempt(attempt)
                except Exception:
                    pass

    def _apply_patch(
        self, root: Path, patch: str, work_id: str,
        journal: list[_JournalEntry], *, permissions: dict[str, Any] | None = None,
        lease_ttl_seconds: int = 900, attempt: WorkAttemptFence | None = None,
    ) -> tuple[list[str], str]:
        root = root.resolve()
        if not self.allow_edits: raise PermissionError("work orchestrator edits are disabled")
        if attempt is not None and (attempt.work_id != work_id or attempt.resource != canonical_resource(root)):
            raise LeaseLostError("work attempt does not own this patch target")
        permissions = permissions or {}
        raw=patch.encode("utf-8")
        if len(raw)>self.max_patch_bytes: raise ValueError("patch exceeds configured byte limit")
        paths, creates, deletes = _patch_changes(patch)
        if not paths or len(paths)>self.max_patch_files: raise ValueError("patch changes no files or exceeds file limit")
        scope_paths = normalize_paths(paths, root=root)
        coordination_id = self._coordination_id(root)
        if creates and (not self.allow_create or not bool(permissions.get("create", True))):
            raise PermissionError(f"file creation disabled: {sorted(creates)[0]}")
        if deletes and (not self.allow_delete or not bool(permissions.get("delete", True))):
            raise PermissionError(f"file deletion disabled: {sorted(deletes)[0]}")
        claim=self.leases.claim_batch(
            owner=work_id,
            root=str(root),
            paths=paths,
            ttl_seconds=lease_ttl_seconds,
            purpose=f"work-order:{work_id}",
            coordination_id=coordination_id,
        )
        if not claim.get("success"): raise RuntimeError(f"edit lease unavailable: {claim.get('error','conflict')}")
        lease_id=str(claim.get("lease_id", ""))
        owns_attempt = attempt is None
        if attempt is None:
            try:
                attempt = self.fencing_store.claim_attempt(
                    str(root), work_id, f"work:{work_id}:{uuid.uuid4().hex}",
                    ttl_seconds=lease_ttl_seconds,
                    coordination_id=coordination_id,
                )
            except Exception as exc:
                try:
                    self.leases.release(owner=work_id, lease_id=lease_id)
                except Exception:
                    pass
                raise RuntimeError(f"work attempt fence unavailable: {exc}") from exc
        fence: FencingLease | None = None
        try:
            fence = self.fencing_store.acquire(
                str(root), f"work:{work_id}:{uuid.uuid4().hex}", scope_paths,
                ttl_seconds=lease_ttl_seconds, attempt=attempt,
                coordination_id=coordination_id,
            )
        except Exception as exc:
            try:
                self.leases.release(owner=work_id, lease_id=lease_id)
            except Exception:
                pass
            if owns_attempt and attempt is not None:
                try:
                    self.fencing_store.release_attempt(attempt)
                except Exception:
                    pass
            raise RuntimeError(f"writer fence unavailable: {exc}") from exc

        journal_start = len(journal)
        try:
            with self.fencing_store.commit_guard(fence, scope_paths):
                snap = self._snapshot(root, paths)
                postimages = self._preview_postimages(patch, snap)
                entries = [
                    _JournalEntry(
                        before.path,
                        before.existed,
                        before.data,
                        after.existed,
                        hashlib.sha256(after.data).hexdigest(),
                        fence.resource,
                        fence.lease_id,
                        fence.owner_id,
                        fence.fencing_token,
                        attempt.attempt_id,
                        attempt.fencing_token,
                    )
                    for before, after in zip(snap, postimages)
                ]
                journal.extend(entries)
                try:
                    # Persist both images under the fence before mutating source.
                    self._persist_journal(work_id, journal)
                    check=subprocess.run(["git","-C",str(root),"apply","--recount","--check","--whitespace=nowarn","-"], input=patch, capture_output=True, text=True, timeout=12, check=False, **hidden_run_kwargs())
                    recount_used = True
                    if check.returncode != 0:
                        fallback_check = subprocess.run(["git","-C",str(root),"apply","--check","--whitespace=nowarn","-"], input=patch, capture_output=True, text=True, timeout=12, check=False, **hidden_run_kwargs())
                        if fallback_check.returncode == 0:
                            check = fallback_check
                            recount_used = False
                        else:
                            raise ValueError((check.stderr or check.stdout or fallback_check.stderr or "git apply --check failed")[:1000])
                    applied_cmd = ["git", "-C", str(root), "apply"]
                    if recount_used:
                        applied_cmd.append("--recount")
                    applied_cmd.extend(["--whitespace=nowarn", "-"])
                    applied=subprocess.run(applied_cmd, input=patch, capture_output=True, text=True, timeout=12, check=False, **hidden_run_kwargs())
                    if applied.returncode != 0: raise ValueError((applied.stderr or applied.stdout or "git apply failed")[:1000])
                    actual = self._snapshot(root, paths)
                    if any(
                        got.existed != expected.postimage_existed
                        or hashlib.sha256(got.data).hexdigest() != expected.postimage_sha256
                        for got, expected in zip(actual, entries)
                    ):
                        raise RuntimeError("applied patch did not match its journaled postimage")
                except Exception:
                    self._rollback(root, entries)
                    del journal[journal_start:]
                    self._persist_journal(work_id, journal)
                    raise
            return paths, lease_id
        except Exception:
            try:
                self.leases.release(owner=work_id, lease_id=lease_id)
            except Exception:
                pass
            raise
        finally:
            if fence is not None:
                try:
                    self.fencing_store.release(fence)
                except Exception:
                    pass
            if owns_attempt and attempt is not None:
                try:
                    self.fencing_store.release_attempt(attempt)
                except Exception:
                    pass

    def _execute(self, row: sqlite3.Row) -> None:
        work_id = str(row["work_id"])
        root = str(row["root"])
        current = self._row(work_id)
        if current is None or str(current["state"]) != "planning":
            return
        try:
            payload = json.loads(str(row["payload_json"] or "{}"))
            budget_seconds = int((payload.get("budget") or {}).get("max_seconds", self.default_seconds))
        except Exception:
            budget_seconds = self.default_seconds
        attempt_ttl = max(30, min(budget_seconds + 60, 24 * 60 * 60))
        owner_id = f"orchestrator:{os.getpid()}:{threading.get_ident()}:{uuid.uuid4().hex}"
        try:
            attempt = self.fencing_store.claim_attempt(
                root,
                work_id,
                owner_id,
                ttl_seconds=attempt_ttl,
                coordination_id=self._coordination_id(root),
            )
        except LeaseUnavailableError:
            # Another live process still owns this work attempt.
            return
        except Exception:
            # Without an authoritative attempt token this worker cannot change
            # durable state. Let recovery retry after the fence store is available.
            self._recovery_retry_requested = True
            self._schedule_recovery_retry()
            return
        try:
            self._execute_fenced(row, attempt, attempt_ttl)
        except LeaseLostError:
            # A successor owns recovery and durable state transitions from here.
            return
        except Exception as exc:
            try:
                self._fail_if_not_cancelled(
                    work_id,
                    {"summary": "work execution failed", "error": f"{type(exc).__name__}: {exc}"[:1200]},
                    attempt=attempt,
                )
            except Exception:
                # Recovery owns any row whose attempt cannot be guarded.
                return
        finally:
            try:
                self.fencing_store.release_attempt(attempt)
            except Exception:
                pass

    def _execute_fenced(
        self, row: sqlite3.Row, attempt: WorkAttemptFence, attempt_ttl: int
    ) -> None:
        work_id, root_s, task = str(row["work_id"]), str(row["root"]), str(row["task"])
        root=Path(root_s); payload=json.loads(str(row["payload_json"] or "{}")); started=time.monotonic()
        permissions = payload.get("permissions")
        mode = payload.get("mode")
        if (not isinstance(permissions, dict) or set(permissions) != _WORK_PERMISSION_FIELDS
                or any(type(value) is not bool for value in permissions.values())
                or not isinstance(mode, str)
                or type(payload.get("keep_failed_workspace")) is not bool
                or mode not in {"execute", "plan", "plan_only", "dry_run"}):
            raise PermissionError("persisted work permission contract is invalid")
        if not permissions["read"]:
            raise PermissionError("work orders require repository read permission")
        if mode == "execute" and (not permissions["tests"] or not permissions["build"]):
            raise PermissionError("execute mode requires both test and build permissions")
        budget=payload["budget"]; llm_calls=0; replans=0; journal: list[_JournalEntry]=[]; lease_ids=[]; changed=[]; step_results=[]; validation=[]
        criteria = payload.get("acceptance_criteria") or []
        verification_receipts: list[Any] = []
        verification: dict[str, Any] = {}
        handoff_revision = ""
        mutation_generation = 0
        validated_generation = -1
        task_owner = ""
        task_id = str(payload.get("task_id", "") or "").strip()
        task_store = getattr(self.verification_store, "task_store", None)
        if task_store is not None and task_id:
            try:
                from .agent_tasks import _task_matches_scope, _task_scope_root

                task_record = task_store.get(task_id)
                expected_root = str(root.resolve(strict=False))
                if (
                    task_record is not None
                    and _task_matches_scope(task_record, expected_root, task_id)
                    and _task_scope_root(task_record) == expected_root
                ):
                    task_owner = str(getattr(task_record, "owner", "") or "").strip()
            except Exception:
                task_owner = ""
        def budget_ok() -> bool:
            return (time.monotonic()-started)<int(budget["max_seconds"]) and llm_calls<int(budget["max_llm_calls"])
        def validation_commands() -> list[str]:
            discovered=self.services.command({"action":"discover","root":root_s})
            commands=[]
            for c in list(plan.get("validation_commands") or []) + list(discovered.get("validation_commands") or []):
                c=str(c).strip()
                if c and c not in commands: commands.append(c)
            return commands[:self.validation_limit] or ["git diff --check"]
        def run_validations(criterion: str) -> None:
            nonlocal attempt, validated_generation, handoff_revision
            from .agent_verification import (
                VerificationReceipt,
                classify_verification_command,
                criterion_evidence_type,
            )

            perms = payload.get("permissions", {})
            if not bool(perms.get("tests", True)) and not bool(perms.get("build", True)):
                raise PermissionError("validation is required for mutating whole-task execution")
            remaining = max(1, int(budget["max_seconds"] - (time.monotonic() - started)))
            for command in validation_commands():
                evidence_type = classify_verification_command(command)
                applicable = [
                    item for item in criteria
                    if evidence_type != "source_review" and criterion_evidence_type(item) == evidence_type
                ]
                run_criterion = applicable[0] if applicable else criterion
                attempt = self.fencing_store.renew_attempt(attempt, ttl_seconds=attempt_ttl)
                command_request = {
                    "action": "run", "command": command, "cwd": root_s,
                    "timeout": min(300, remaining),
                    "criterion": run_criterion, "record_verification": False,
                    "writer_fence": attempt,
                    "paths": list(dict.fromkeys(changed)),
                }
                if task_id:
                    command_request["task_id"] = task_id
                r = self.services.command(command_request)
                self.fencing_store.assert_attempt_current(attempt)
                command_id = str(r.get("execution_id") or r.get("command_id") or "").strip()
                command_revision = str(r.get("repository_revision") or "").strip()
                if command_revision:
                    handoff_revision = command_revision
                validation_entry = {
                    "command": command, "success": bool(r.get("success")),
                    "exit_code": r.get("exit_code"), "error": r.get("error", ""),
                    "generation": mutation_generation, "command_id": command_id,
                    "repository_revision": command_revision, "evidence_type": evidence_type,
                }
                validation.append(validation_entry)
                if not r.get("success"): raise RuntimeError(f"validation failed: {command}: {r.get('error','non-zero exit')}")
                if (
                    applicable and command_id and command_revision
                    and type(r.get("exit_code")) is int and r.get("exit_code") == 0
                ):
                    if not task_owner:
                        raise RuntimeError("task owner/root scope unavailable for verification receipt")
                    for accepted_criterion in applicable:
                        proof = {
                            "kind": "work_command_verification", "passed": True,
                            "task_id": task_id, "owner": task_owner,
                            "criterion": accepted_criterion, "command": command,
                            "command_id": command_id, "repository_revision": command_revision,
                            "mutation_generation": mutation_generation,
                            "exit_code": r.get("exit_code"),
                            "result": {"success": r.get("success") is True, "exit_code": r.get("exit_code")},
                        }
                        with self._state_attempt_guard(work_id, attempt):
                            evidence_id = self.artifacts.put(
                                json_dumps(proof, ensure_ascii=False), kind="command_verification"
                            )
                            if not evidence_id:
                                raise RuntimeError("verification receipt evidence was not persisted")
                            receipt = VerificationReceipt.create(
                                task_id=task_id, criterion=accepted_criterion, passed=True,
                                owner=task_owner, evidence_id=str(evidence_id), command_id=command_id,
                                repository_revision=command_revision,
                                mutation_generation=mutation_generation, evidence_type=evidence_type,
                                details={"command": command, "exit_code": r.get("exit_code")},
                            )
                            if self.verification_store is not None:
                                self.verification_store.record(receipt, update_task=False)
                            verification_receipts.append(receipt)
                            validation_entry.setdefault("receipt_ids", []).append(receipt.receipt_id)
            validated_generation = mutation_generation
        def repair(reason: str) -> bool:
            nonlocal attempt, llm_calls, replans, mutation_generation
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
            res=self._ask(root_s,req,json_dumps(current,ensure_ascii=False)[:18000],1800); llm_calls+=1; replans+=1
            patch=_diff_from_text(str(res.get("text","")))
            if not patch:
                return False
            lease_ttl = attempt_ttl
            try:
                attempt = self.fencing_store.renew_attempt(attempt, ttl_seconds=attempt_ttl)
                paths,lease=self._apply_patch(root,patch,work_id,journal,permissions=payload.get("permissions",{}),lease_ttl_seconds=lease_ttl,attempt=attempt)
            except Exception:
                return False
            lease_ids.append(lease); changed.extend(x for x in paths if x not in changed)
            mutation_generation += 1
            return True
        if self._cancelled(work_id):
            self._set_terminal_if_active(work_id,"cancelled",{"summary":"cancelled before start"},attempt=attempt)
            return
        self._set_state(work_id,"planning",{"summary":"collecting context and planning","progress":{"phase":"planning","completed":0}},attempt=attempt)
        context={"profile":self.services.repo_profile(root_s),"map":self.services.repo_map(root_s,80),"tests":self.services.test_matrix(root_s)}
        plan=self._plan(root_s,task,payload,context); llm_calls+=1
        if bool(plan.get("needs_agent")):
            result={"summary":str(plan.get("summary",task))[:600],"needs_agent":True,"question":str(plan.get("question","Clarification required"))[:1200],"plan":plan}
            if not self._set_terminal_if_not_cancelled(work_id,"needs_agent",result,attempt=attempt):
                raise InterruptedError("work order cancelled before agent handoff")
            return
        if payload.get("mode") in {"plan","plan_only","dry_run"}:
            art=self.artifacts.put(json_dumps({"task":task,"plan":plan},ensure_ascii=False,indent=2),kind="work-plan")
            handoff={"summary":str(plan.get("summary",task))[:600],"plan":plan,"artifact_id":art,"available_details":["plan"]}
            if not self._complete_if_not_cancelled(work_id,handoff,expected_state="planning",attempt=attempt):
                raise InterruptedError("work order cancelled before completion")
            return
        self._set_state(work_id,"executing",{"summary":str(plan.get("summary",task))[:600],"plan":plan,"progress":{"phase":"executing","completed":0,"total":len(plan["steps"]) }},attempt=attempt)
        try:
            for idx, step in enumerate(plan["steps"]):
                attempt = self.fencing_store.renew_attempt(attempt, ttl_seconds=attempt_ttl)
                if self._cancelled(work_id): raise InterruptedError("cancelled")
                if not budget_ok():
                    kept = bool(payload.get("keep_failed_workspace"))
                    rolled = self._rollback_transaction(work_id, root, journal, keep=kept, attempt=attempt)
                    if rolled:
                        changed = []
                    result={"summary":"work budget exhausted" + ("; workspace rolled back" if rolled else ""),"plan":plan,"steps":step_results,"changed_files":changed,"rolled_back":rolled,"progress":{"completed":idx,"total":len(plan["steps"])}}
                    if not self._set_terminal_if_not_cancelled(work_id,"partial",result,attempt=attempt):
                        raise InterruptedError("work order cancelled before partial handoff")
                    return
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
                    for retry_index in range(self.step_retry_limit + 1):
                        retry_source = self._failed_patch_source(root, patch) if last_error and patch else ""
                        req=("Return ONLY a unified git diff that implements this bounded step. No prose. Preserve public APIs unless task requires otherwise. "
                             "Do not edit generated/vendor/cache files. Make the smallest coherent change and include tests when appropriate.\n"
                             f"ORIGINAL TASK:\n{task}\nSTEP:\n{step['task']}\nACCEPTANCE:\n{json_dumps(step.get('acceptance',[]),ensure_ascii=False)}"
                             + (f"\nPREVIOUS PATCH ERROR:\n{last_error}" if last_error else "")
                             + (f"\n{retry_source}" if retry_source else ""))
                        patch_complexity = "auto" if retry_index == 0 else "heavy"
                        res=self._ask(root_s,req,json_dumps(fast,ensure_ascii=False)[:16000],1800,complexity=patch_complexity,task_type="code"); llm_calls+=1
                        patch=_diff_from_text(str(res.get("text","")))
                        if not patch:
                            last_error = "local worker returned no unified diff"
                            if retry_index > 0:
                                raise RuntimeError("local worker returned no unified diff after heavy-code retry")
                            if retry_index < self.step_retry_limit and budget_ok():
                                continue
                            raise RuntimeError(last_error)
                        try:
                            lease_ttl = attempt_ttl
                            paths,lease=self._apply_patch(root,patch,work_id,journal, permissions=perms, lease_ttl_seconds=lease_ttl, attempt=attempt)
                            break
                        except Exception as exc:
                            last_error = str(exc)[:1000]
                            if retry_index >= self.step_retry_limit or not budget_ok():
                                raise
                    lease_ids.append(lease); changed.extend(x for x in paths if x not in changed)
                    mutation_generation += 1
                    outcome.update({"files":paths,"patch_bytes":len(patch.encode('utf-8')),"attempts":retry_index+1})
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
                        vr=self._ask(root_s,q,json_dumps(diff,ensure_ascii=False)[:18000],1200,review=True); llm_calls+=1
                        parsed=_json_object(str(vr.get("text",""))) or {"passed":False,"summary":"verifier returned invalid result","risks":["invalid verifier response"]}
                        outcome["verification"]=parsed
                        if parsed.get("needs_agent"):
                            rolled = self._rollback_transaction(work_id, root, journal, keep=False, attempt=attempt)
                            if rolled:
                                changed = []
                            result={"summary":str(parsed.get("summary","needs agent")),"needs_agent":True,"question":str(parsed.get("question","Decision required")),"plan":plan,"steps":step_results+[outcome],"changed_files":changed,"validation":validation,"rolled_back":rolled}
                            if not self._set_terminal_if_not_cancelled(work_id,"needs_agent",result,attempt=attempt):
                                raise InterruptedError("work order cancelled before agent handoff")
                            return
                        if bool(parsed.get("passed")):
                            break
                        if not repair(f"review failed: {parsed.get('summary','unspecified')}"):
                            raise RuntimeError(f"verification failed: {parsed.get('summary','unspecified')}")
                        run_validations("replanned repair after review")
                step_results.append(outcome)
                self._set_state(work_id,"executing",{"summary":str(plan.get("summary",task))[:600],"plan":plan,"steps":step_results,"changed_files":changed,"validation":validation,"progress":{"phase":"executing","completed":idx+1,"total":len(plan["steps"]) }},attempt=attempt)

            # Whole-task final check uses the original request, not the planner summary.
            self._set_state(work_id,"verifying",{"summary":"whole-task verification","plan":plan,"steps":step_results,"changed_files":changed,"validation":validation},attempt=attempt)
            from .agent_verification import criterion_evidence_type
            requires_execution_evidence = any(
                criterion_evidence_type(criterion) in {"test", "benchmark"}
                for criterion in criteria
            )
            if (changed or requires_execution_evidence) and validated_generation != mutation_generation:
                run_validations("final integrated validation")
            while True:
                if not budget_ok():
                    raise RuntimeError("LLM/time budget exhausted before final whole-task verification")
                diff=self.services.repo_diff(root_s,"HEAD",False,6500)
                final_q=("FINAL WHOLE-TASK VERIFIER. Judge only against ORIGINAL TASK and explicit acceptance criteria. Return STRICT JSON only: "
                         '{"passed":true,"summary":"...","criteria":[{"criterion":"...","passed":true}],"risks":[]}. '
                         "A mutating task cannot pass without successful validation evidence from the current mutation generation.\n"
                         f"ORIGINAL TASK:\n{task}\nACCEPTANCE:\n{json_dumps(criteria,ensure_ascii=False)}\n"
                         f"VALIDATION:\n{json_dumps(validation,ensure_ascii=False)}")
                final=self._ask(root_s,final_q,json_dumps(diff,ensure_ascii=False)[:22000],1200,review=True); llm_calls+=1
                verification=_json_object(str(final.get("text",""))) or {"passed":False,"summary":"invalid final verifier response","risks":["invalid verifier response"]}
                if changed and validated_generation != mutation_generation:
                    verification["passed"]=False
                if criteria:
                    got={str(x.get("criterion","")): bool(x.get("passed")) for x in verification.get("criteria",[]) if isinstance(x,dict)}
                    if not all(any(c == k or c.lower() in k.lower() or k.lower() in c.lower() for k,p in got.items() if p) for c in criteria): verification["passed"]=False
                if verification.get("passed"):
                    if not handoff_revision:
                        revision = subprocess.run(
                            ["git", "-C", root_s, "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=False, timeout=5,
                            **hidden_run_kwargs(),
                        )
                        if revision.returncode != 0 or not revision.stdout.strip():
                            raise RuntimeError("verification receipt gate failed: repository revision is unavailable")
                        handoff_revision = revision.stdout.strip()

                    passed_model_criteria = {
                        criterion for criterion in criteria
                        if any(
                            passed and (
                                criterion == reported
                                or criterion.lower() in reported.lower()
                                or reported.lower() in criterion.lower()
                            )
                            for reported, passed in got.items()
                        )
                    }
                    from .agent_verification import criterion_evidence_type
                    review_criteria = [
                        criterion for criterion in criteria
                        if criterion_evidence_type(criterion) == "source_review"
                        and criterion in passed_model_criteria
                    ]
                    if review_criteria:
                        if not task_owner:
                            raise RuntimeError("task owner/root scope unavailable for source review receipt")
                        review_proof = {
                            "kind": "work_source_review", "passed": True, "task_id": task_id,
                            "owner": task_owner, "criteria": review_criteria,
                            "verification": verification, "repository_revision": handoff_revision,
                            "mutation_generation": mutation_generation, "diff": diff,
                        }
                        review_evidence = self.artifacts.put(
                            json_dumps(review_proof, ensure_ascii=False), kind="source_review"
                        )
                        if not review_evidence:
                            raise RuntimeError("verification receipt gate failed: source review evidence was not persisted")
                        from .agent_verification import VerificationReceipt
                        for review_criterion in review_criteria:
                            receipt = VerificationReceipt.create(
                                task_id=task_id, criterion=review_criterion, passed=True,
                                owner=task_owner, evidence_id=str(review_evidence),
                                repository_revision=handoff_revision,
                                mutation_generation=mutation_generation, evidence_type="source_review",
                                details={"summary": str(verification.get("summary", ""))},
                            )
                            with self._state_attempt_guard(work_id, attempt):
                                if self.verification_store is not None:
                                    self.verification_store.record(receipt, update_task=False)
                                verification_receipts.append(receipt)

                    persisted_receipts = self._persist_handoff_receipts(
                        work_id, verification_receipts, validation, attempt=attempt
                    )
                    latest = {}
                    for receipt in persisted_receipts:
                        previous = latest.get(receipt.criterion)
                        if previous is None or receipt.observed_at > previous.observed_at:
                            latest[receipt.criterion] = receipt
                    from .agent_verification import evaluate_completion_receipts
                    if not task_owner:
                        raise RuntimeError("task owner/root scope unavailable for completion receipt gate")
                    receipt_gate = evaluate_completion_receipts(
                        task_id, criteria, persisted_receipts, owner=task_owner,
                        repository_revision=handoff_revision,
                        mutation_generation=mutation_generation,
                        artifact_store=self.artifacts, require_repository_revision=True,
                        mapped_receipt_ids={
                            criterion: latest[criterion].receipt_id if criterion in latest else ""
                            for criterion in criteria
                        },
                    )
                    verification["receipt_gate"] = {
                        "complete": receipt_gate.complete,
                        "satisfied_criteria": list(receipt_gate.satisfied_criteria),
                        "unsatisfied_criteria": list(receipt_gate.unsatisfied_criteria),
                        "stale_criteria": list(receipt_gate.stale_criteria),
                        "receipt_ids": {key: value.receipt_id for key, value in latest.items()},
                    }
                    if not receipt_gate.complete:
                        missing = ", ".join((*receipt_gate.unsatisfied_criteria, *receipt_gate.stale_criteria))
                        raise RuntimeError(f"verification receipt gate failed for: {missing or 'acceptance criteria'}")
                    break
                if not repair(f"final whole-task verification failed: {verification.get('summary','unspecified')}"):
                    raise RuntimeError(f"whole-task verification failed: {verification.get('summary','unspecified')}")
                run_validations("replanned repair after final verification")
            changed = [str(x) for x in diff.get("changed_files", changed)] if isinstance(diff, dict) else changed
            report={"original_task":task,"plan":plan,"steps":step_results,"changed_files":changed,"diff":diff,"validation":validation,"verification":verification,"verification_receipts":[receipt.to_dict() for receipt in verification_receipts],"llm_calls":llm_calls,"replans":replans,"elapsed_seconds":round(time.monotonic()-started,2)}
            artifact=self.artifacts.put(json_dumps(report,ensure_ascii=False,indent=2),kind="work-handoff")
            handoff={"summary":str(verification.get("summary") or plan.get("summary") or "work complete")[:900],"changed_files":changed,"validation":{"passed":all(v.get("success") for v in validation),"commands":len(validation)},"verification":verification,"verification_receipts":[receipt.to_dict() for receipt in verification_receipts],"risks":verification.get("risks",[])[:8],"handoff_id":artifact,"artifact_id":artifact,"available_details":["plan","steps","diff","validation","verification","verification_receipts"]}
            if not self._complete_if_not_cancelled(work_id, handoff, attempt=attempt):
                raise InterruptedError("work order cancelled before completion")
            try:
                self._clear_journal(work_id, attempt=attempt)
            except OSError:
                # Completion is already durable. Leave the journal for startup
                # cleanup; never roll back a committed handoff on cleanup error.
                pass
        except InterruptedError:
            rolled = self._rollback_transaction(work_id, root, journal, keep=bool(payload.get("keep_failed_workspace")), attempt=attempt)
            if rolled:
                changed = []
            self._set_terminal_if_active(work_id,"cancelled",{"summary":"work order cancelled" + ("; workspace rolled back" if rolled else ""),"changed_files":changed,"rolled_back":rolled,"verification_receipts":[receipt.to_dict() for receipt in verification_receipts]},attempt=attempt)
        except Exception as exc:
            rolled=False
            try:
                rolled = self._rollback_transaction(work_id, root, journal, keep=bool(payload.get("keep_failed_workspace")), attempt=attempt)
                if rolled:
                    changed=[]
            except Exception:
                pass
            try:
                failure_diff = self.services.repo_diff(root_s,"HEAD",False,6500)
            except Exception:
                failure_diff = {"success": False, "error": "diff unavailable"}
            serialized_receipts = [receipt.to_dict() for receipt in verification_receipts]
            report={"original_task":task,"plan":plan,"steps":step_results,"changed_files":changed,"diff":failure_diff,"validation":validation,"verification":verification,"verification_receipts":serialized_receipts,"error":str(exc),"rolled_back":rolled,"llm_calls":llm_calls,"replans":replans}
            artifact=self.artifacts.put(json_dumps(report,ensure_ascii=False,indent=2),kind="work-failure")
            failure={"summary":"whole task failed" + (" and was rolled back" if rolled else ""),"error":str(exc)[:1200],"changed_files":changed,"validation":{"passed":False,"commands":len(validation)},"verification":verification,"verification_receipts":serialized_receipts,"artifact_id":artifact,"available_details":["plan","steps","validation","verification","verification_receipts","failure_report"]}
            if not self._fail_if_not_cancelled(work_id,failure,attempt=attempt):
                self._set_terminal_if_active(work_id,"cancelled",{"summary":"work order cancelled during failure recovery" + ("; workspace rolled back" if rolled else ""),"changed_files":changed,"rolled_back":rolled},attempt=attempt)
        finally:
            for lid in lease_ids:
                try: self.leases.release(owner=work_id, lease_id=lid)
                except Exception: pass

    def close(self) -> None:
        self._stop.set(); self._wake.set()
        with self._lock:
            recovery_timer = self._recovery_timer
            self._recovery_timer = None
        if recovery_timer is not None:
            recovery_timer.cancel()
        current = threading.current_thread()
        with self._lock:
            workers = list(self._workers)
        for worker in workers:
            if worker is not current and worker.is_alive():
                worker.join(timeout=2.0)
