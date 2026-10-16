from __future__ import annotations

from .json_utils import dumps as json_dumps

import hashlib
import json
import math
import os
import re
import threading
import time
import uuid
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Collection, Mapping

from .agent_events import AgentEvent, AgentStateStore
from .sqlite_support import connect_sqlite, retry_busy


def _incident_scope_key(kind: str, value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if kind == "repository":
        try:
            raw = os.path.normcase(str(Path(raw).expanduser().resolve(strict=False)))
        except (OSError, RuntimeError, TypeError, ValueError):
            return ""
    digest = hashlib.sha256(f"agent-incident:{kind}\0{raw}".encode("utf-8")).hexdigest()
    return digest


@dataclass(frozen=True)
class IncidentFingerprint:
    error_class: str
    operation_class: str
    signature_hash: str

    def __post_init__(self) -> None:
        ec = str(self.error_class).replace("\x00", "").strip() if self.error_class is not None else ""
        oc = str(self.operation_class).replace("\x00", "").strip() if self.operation_class is not None else ""
        sh = str(self.signature_hash).replace("\x00", "").strip() if self.signature_hash is not None else ""
        object.__setattr__(self, "error_class", ec or "unknown")
        object.__setattr__(self, "operation_class", oc or "command")
        object.__setattr__(self, "signature_hash", sh)

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_class": self.error_class,
            "operation_class": self.operation_class,
            "signature_hash": self.signature_hash,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> IncidentFingerprint:
        if not isinstance(data, Mapping):
            return cls(error_class="unknown", operation_class="command", signature_hash="")
        return cls(
            error_class=str(data.get("error_class", "")),
            operation_class=str(data.get("operation_class", "")),
            signature_hash=str(data.get("signature_hash", "")),
        )


@dataclass(frozen=True)
class ToolOutcome:
    tool_name: str
    command: str = ""
    error: str = ""
    exit_code: int = 0
    state_revision: str = ""
    evidence_ids: tuple[str, ...] = ()
    policy_blocked: bool = False
    cancelled: bool = False
    timed_out: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    affected_paths: tuple[str, ...] = ()
    repository_root: str = ""
    tenant: str = ""

    def __post_init__(self) -> None:
        tn = str(self.tool_name).replace("\x00", "").strip() if self.tool_name is not None else ""
        cmd = str(self.command).replace("\x00", "").strip() if self.command is not None else ""
        err = str(self.error).replace("\x00", "").strip() if self.error is not None else ""
        ec = self.exit_code
        if type(ec) is not int or not -(2**31) <= ec <= (2**32 - 1):
            raise ValueError("exit_code must be a signed or unsigned 32-bit integer")
        s_rev = str(self.state_revision).replace("\x00", "").strip() if self.state_revision is not None else ""

        ev_raw = (self.evidence_ids,) if isinstance(self.evidence_ids, str) else (self.evidence_ids or ())
        ev_ids = tuple(str(x).replace("\x00", "").strip() for x in ev_raw if str(x).replace("\x00", "").strip())

        ap_raw = (self.affected_paths,) if isinstance(self.affected_paths, str) else (self.affected_paths or ())
        ap_paths = tuple(str(x).replace("\x00", "").strip() for x in ap_raw if str(x).replace("\x00", "").strip())

        meta = dict(self.metadata) if isinstance(self.metadata, Mapping) else {}
        rr = str(self.repository_root).replace("\x00", "").strip() if self.repository_root is not None else ""
        tnt = str(self.tenant).replace("\x00", "").strip() if self.tenant is not None else ""

        object.__setattr__(self, "tool_name", tn or "command")
        object.__setattr__(self, "command", cmd)
        object.__setattr__(self, "error", err)
        object.__setattr__(self, "exit_code", ec)
        object.__setattr__(self, "state_revision", s_rev)
        object.__setattr__(self, "evidence_ids", ev_ids)
        object.__setattr__(self, "affected_paths", ap_paths)
        object.__setattr__(self, "metadata", meta)
        object.__setattr__(self, "repository_root", rr)
        object.__setattr__(self, "tenant", tnt)


@dataclass(frozen=True)
class IncidentRecord:
    incident_id: str
    fingerprint: IncidentFingerprint
    operation_class: str
    error_class: str
    redacted_message: str
    state_revision: str
    attempts: int = 1
    evidence_ids: tuple[str, ...] = ()
    root_cause: str | None = None
    verified_fix: str | None = None
    confidence: float = 0.0
    resolved: bool = False
    ignored: bool = False
    created_at: float = 0.0
    updated_at: float = 0.0
    expires_at: float | None = None
    affected_paths: tuple[str, ...] = ()
    repository_key: str = ""
    tenant_key: str = ""

    def __post_init__(self) -> None:
        iid = str(self.incident_id).replace("\x00", "").strip() if self.incident_id is not None else ""
        if not iid:
            iid = f"inc_{uuid.uuid4().hex[:8]}"
        op = str(self.operation_class).replace("\x00", "").strip() if self.operation_class is not None else ""
        ec = str(self.error_class).replace("\x00", "").strip() if self.error_class is not None else ""
        rm = str(self.redacted_message).replace("\x00", "").strip() if self.redacted_message is not None else ""
        sr = str(self.state_revision).replace("\x00", "").strip() if self.state_revision is not None else ""
        try:
            att = max(1, int(self.attempts))
        except (ValueError, TypeError):
            att = 1
        try:
            conf = float(self.confidence)
            if not math.isfinite(conf):
                conf = 0.0
            else:
                conf = max(0.0, min(1.0, conf))
        except (ValueError, TypeError):
            conf = 0.0
        try:
            ca = float(self.created_at)
            if not math.isfinite(ca):
                ca = 0.0
            else:
                ca = max(0.0, ca)
        except (ValueError, TypeError):
            ca = 0.0
        try:
            ua = float(self.updated_at)
            if not math.isfinite(ua):
                ua = 0.0
            else:
                ua = max(0.0, ua)
        except (ValueError, TypeError):
            ua = 0.0

        ea = self.expires_at
        if ea is not None:
            try:
                ea_val = float(ea)
                ea = max(0.0, ea_val) if math.isfinite(ea_val) else None
            except (ValueError, TypeError):
                ea = None

        ev_raw = (self.evidence_ids,) if isinstance(self.evidence_ids, str) else (self.evidence_ids or ())
        ev_ids = tuple(str(x).replace("\x00", "").strip() for x in ev_raw if str(x).replace("\x00", "").strip())
        ap_raw = (self.affected_paths,) if isinstance(self.affected_paths, str) else (self.affected_paths or ())
        ap_paths = tuple(str(x).replace("\x00", "").strip() for x in ap_raw if str(x).replace("\x00", "").strip())

        object.__setattr__(self, "incident_id", iid)
        object.__setattr__(self, "operation_class", op or "command")
        object.__setattr__(self, "error_class", ec or "unknown")
        object.__setattr__(self, "redacted_message", rm)
        object.__setattr__(self, "state_revision", sr)
        object.__setattr__(self, "attempts", att)
        object.__setattr__(self, "confidence", conf)
        object.__setattr__(self, "created_at", ca)
        object.__setattr__(self, "updated_at", ua)
        object.__setattr__(self, "expires_at", ea)
        object.__setattr__(self, "evidence_ids", ev_ids)
        object.__setattr__(self, "affected_paths", ap_paths)

    def is_resolved(self) -> bool:
        return self.resolved

    def is_ignored(self) -> bool:
        return self.ignored

    def is_active(self) -> bool:
        return not self.resolved and not self.ignored

    def has_verified_fix(self) -> bool:
        return bool(self.verified_fix)

    @property
    def status(self) -> str:
        if self.ignored:
            return "ignored"
        return "resolved" if self.resolved else "unresolved"

    def to_dict(self) -> dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "fingerprint": self.fingerprint.to_dict(),
            "operation_class": self.operation_class,
            "error_class": self.error_class,
            "redacted_message": self.redacted_message,
            "state_revision": self.state_revision,
            "attempts": self.attempts,
            "evidence_ids": list(self.evidence_ids),
            "root_cause": self.root_cause,
            "verified_fix": self.verified_fix,
            "confidence": self.confidence,
            "resolved": self.resolved,
            "ignored": self.ignored,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "expires_at": self.expires_at,
            "affected_paths": list(self.affected_paths),
            "provenance": {
                "repository_key": self.repository_key,
                "tenant_key": self.tenant_key,
            },
        }


@dataclass(frozen=True)
class RetryDecision:
    action: str  # "apply_verified_fix", "stop", "retry", "proceed"
    reason: str
    verified_fix: str | None = None
    confidence: float = 0.0

    def __post_init__(self) -> None:
        act = str(self.action).replace("\x00", "").strip() if self.action is not None else ""
        rsn = str(self.reason).replace("\x00", "").strip() if self.reason is not None else ""
        try:
            conf = float(self.confidence)
            if not math.isfinite(conf):
                conf = 0.0
            else:
                conf = max(0.0, min(1.0, conf))
        except (ValueError, TypeError):
            conf = 0.0
        object.__setattr__(self, "action", act or "stop")
        object.__setattr__(self, "reason", rsn)
        object.__setattr__(self, "confidence", conf)

    def can_retry(self) -> bool:
        return self.action in {"apply_verified_fix", "retry", "proceed"}

    def should_stop(self) -> bool:
        return self.action == "stop"

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "verified_fix": self.verified_fix,
            "confidence": self.confidence,
        }


def _redact_message(msg: str) -> str:
    if not isinstance(msg, str):
        msg = str(msg).replace("\x00", "") if msg is not None else ""
    else:
        msg = msg.replace("\x00", "")
    cleaned = re.sub(r"[a-zA-Z]:\\[^\s:\"']+", "[PATH]", msg)
    cleaned = re.sub(r"/[a-zA-Z0-9_\.-]+/[^\s:\"']+", "[PATH]", cleaned)
    cleaned = re.sub(r"(token|secret|key|password)[=:]\s*\S+", r"\1=[REDACTED]", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()[:256]


def _normalize_signature(msg: str) -> str:
    if not isinstance(msg, str):
        msg = str(msg).replace("\x00", "") if msg is not None else ""
    else:
        msg = msg.replace("\x00", "")
    norm = msg.lower()
    norm = re.sub(r"0x[0-9a-f]+", "", norm)
    norm = re.sub(r"\d+", "", norm)
    norm = re.sub(r"[^\w\s]", " ", norm)
    norm = " ".join(norm.split())
    if not norm:
        norm = "empty"
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def _classify_error(error_msg: str, timed_out: bool) -> str:
    if timed_out:
        return "TimeoutError"
    if not isinstance(error_msg, str):
        error_msg = str(error_msg).replace("\x00", "") if error_msg is not None else ""
    else:
        error_msg = error_msg.replace("\x00", "")
    low = error_msg.lower()
    if "lock" in low or "busy" in low:
        return "BusyLockError"
    if "syntax" in low or "parse" in low or "invalid syntax" in low:
        return "SyntaxError"
    if "config" in low:
        return "ConfigError"
    if "not found" in low or "filenotfound" in low:
        return "NotFoundError"
    if "permission" in low or "access denied" in low:
        return "PermissionError"
    if "connection" in low or "refused" in low or "network" in low:
        return "NetworkError"
    return "CommandExecutionError"


def _extract_root_cause_and_fix(error_msg: str, tool_name: str = "", timed_out: bool = False) -> tuple[str, str, float]:
    """Analyze error patterns to extract actionable root cause and resolution guidance."""
    if timed_out:
        return "operation exceeded deadline or hung", "increase timeout or check for blocking calls", 0.85

    match = re.search(r"No module named ['\"]?([a-zA-Z0-9_\.-]+)['\"]?", error_msg)
    if match:
        mod = match.group(1)
        return f"missing Python module '{mod}'", f"install '{mod}' or verify active virtual environment", 0.95

    match = re.search(r"(?:No such file or directory|cannot find the (?:path|file) specified)[:\s]*['\"]?([^\r\n'\"]+)", error_msg, re.IGNORECASE)
    if match:
        target = match.group(1).strip()
        return f"target path does not exist: {target}", f"ensure target path exists before accessing: {target}", 0.90

    match = re.search(r"missing script:\s*([a-zA-Z0-9_\.-]+)", error_msg, re.IGNORECASE)
    if match:
        script = match.group(1)
        return f"package.json missing script '{script}'", "check available npm scripts in package.json", 0.95

    low = error_msg.lower()
    if "database is locked" in low or "database table is locked" in low or "sqlite3.busyerror" in low:
        return "concurrent write lock contention on SQLite", "retry with busy backoff and avoid long-running transactions", 0.90

    if "permission denied" in low or "access is denied" in low:
        return "insufficient filesystem or execution permissions", "check file permissions or run in authorized directory", 0.85

    if "connection refused" in low or "actively refused" in low:
        return "target network service is offline or port is closed", "start backend service or verify configured port/URL", 0.90

    if "syntaxerror" in low or "invalid syntax" in low:
        return "source code syntax error", "check syntax at the reported line and column", 0.85

    match = re.search(r"(?:unrecognized option|unknown option|no such option|unexpected argument)[:\s]*['\"]?([^\r\n'\"]+)", error_msg, re.IGNORECASE)
    if match:
        flag = match.group(1).strip()
        return f"unrecognized command line flag '{flag}'", f"remove or correct flag '{flag}' using tool help", 0.90

    return "", "", 0.0


def _send_incident_webhooks(urls: list[str], payload: bytes) -> None:
    import logging
    import urllib.request

    logger = logging.getLogger(__name__)
    for url in urls:
        try:
            request = urllib.request.Request(
                url,
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "LocalAIHub-IncidentHook/1.0",
                },
            )
            with urllib.request.urlopen(request, timeout=3.0) as response:
                response.read()
        except Exception as exc:
            # Keep delivery best-effort without exposing URLs, payloads or
            # untrusted exception text in logs.
            logger.warning("Incident webhook delivery failed (%s)", type(exc).__name__)


class IncidentStore:
    def __init__(self, state_store: AgentStateStore) -> None:
        self.state_store = state_store
        self._lock = threading.RLock()
        self._initialized = False
        self.webhook_urls: list[str] = []
        self._webhook_lock = threading.Lock()
        self._init_table()

    def register_webhook(self, url: str) -> None:
        clean = url.strip()
        with self._webhook_lock:
            if clean and clean not in self.webhook_urls:
                self.webhook_urls.append(clean)

    def unregister_webhook(self, url: str) -> None:
        clean = url.strip()
        with self._webhook_lock:
            if clean in self.webhook_urls:
                self.webhook_urls.remove(clean)

    def _dispatch_webhooks(self, record_dict: dict[str, Any]) -> None:
        with self._webhook_lock:
            urls = list(self.webhook_urls)
        if not urls:
            return
        payload = json_dumps(record_dict, default=str).encode("utf-8")
        def _send() -> None:
            _send_incident_webhooks(urls, payload)
        threading.Thread(target=_send, daemon=True).start()

    def _init_table(self) -> None:
        if self._initialized or not self.state_store.enabled:
            return
        with self._lock:
            if self._initialized or not self.state_store.enabled:
                return
            self.state_store._ensure_schema()
            def _setup() -> None:
                # Snapshot drift from another initializer is a transient busy
                # result and belongs inside the existing bounded retry budget.
                self.state_store._preflight_schema_read_only()
                con = connect_sqlite(self.state_store.db_path)
                try:
                    con.execute("BEGIN IMMEDIATE")
                    with con:
                        con.execute(
                            """
                            CREATE TABLE IF NOT EXISTS agent_incidents (
                                incident_id TEXT PRIMARY KEY,
                                operation_class TEXT NOT NULL,
                                error_class TEXT NOT NULL,
                                signature_hash TEXT NOT NULL,
                                redacted_message TEXT NOT NULL,
                                state_revision TEXT NOT NULL,
                                attempts INTEGER NOT NULL,
                                evidence_ids TEXT NOT NULL,
                                root_cause TEXT,
                                verified_fix TEXT,
                                confidence REAL NOT NULL,
                                resolved INTEGER NOT NULL,
                                created_at REAL NOT NULL,
                                updated_at REAL NOT NULL,
                                expires_at REAL,
                                affected_paths TEXT NOT NULL DEFAULT '[]',
                                ignored INTEGER NOT NULL DEFAULT 0,
                                repository_key TEXT NOT NULL DEFAULT '',
                                tenant_key TEXT NOT NULL DEFAULT ''
                            );
                            """
                        )
                        con.execute(
                            """
                            CREATE INDEX IF NOT EXISTS idx_agent_incidents_fp
                            ON agent_incidents (error_class, operation_class, signature_hash, state_revision);
                            """
                        )
                        con.execute(
                            """
                            CREATE INDEX IF NOT EXISTS idx_agent_incidents_lookup
                            ON agent_incidents (operation_class, signature_hash, state_revision, updated_at DESC);
                            """
                        )
                        con.execute(
                            """
                            CREATE INDEX IF NOT EXISTS idx_agent_incidents_recent
                            ON agent_incidents (operation_class, signature_hash, updated_at DESC);
                            """
                        )
                        con.execute(
                            """
                            CREATE INDEX IF NOT EXISTS idx_agent_incidents_scope
                            ON agent_incidents (repository_key, tenant_key, ignored, updated_at DESC);
                            """
                        )
                finally:
                    con.close()
            retry_busy(_setup, retries=5, base_delay_seconds=0.02)
            self._initialized = True

    def capture(self, outcome: ToolOutcome) -> IncidentRecord | None:
        if outcome.policy_blocked or outcome.cancelled:
            return None

        # Succeeded without errors
        if not outcome.error and outcome.exit_code == 0 and not outcome.timed_out:
            return None

        redacted = _redact_message(outcome.error or f"exit code {outcome.exit_code}")
        sig_hash = _normalize_signature(redacted)
        err_class = _classify_error(redacted, outcome.timed_out)
        op_class = outcome.tool_name or "command"
        fp = IncidentFingerprint(
            error_class=err_class,
            operation_class=op_class,
            signature_hash=sig_hash,
        )

        meta = outcome.metadata if isinstance(outcome.metadata, Mapping) else {}
        meta_rc = str(meta.get("root_cause") or "")
        meta_fix = str(meta.get("verified_fix") or "")
        try:
            meta_conf_val = float(meta.get("confidence") or 0.0)
            meta_conf = meta_conf_val if math.isfinite(meta_conf_val) else 0.0
        except (ValueError, TypeError):
            meta_conf = 0.0
        repository_key = _incident_scope_key(
            "repository", outcome.repository_root or meta.get("repository_root")
        )
        tenant_key = _incident_scope_key(
            "tenant", outcome.tenant or meta.get("tenant")
        )
        auto_rc, auto_fix, auto_conf = _extract_root_cause_and_fix(outcome.error, outcome.tool_name, outcome.timed_out)
        eff_rc = meta_rc or auto_rc or None
        eff_fix = meta_fix or auto_fix or None
        eff_conf = max(meta_conf, auto_conf)

        # Extract affected paths from outcome or heuristically from error/command
        paths: set[str] = set(outcome.affected_paths)
        if not paths and outcome.metadata.get("affected_paths"):
            for p in outcome.metadata["affected_paths"]:
                paths.add(str(p))
        if not paths:
            found = re.findall(r"[\w\./\\-]+\.(?:py|js|ts|tsx|jsx|rs|go|c|cpp|h|cs|php|java|rb|json|toml|yaml|yml)", outcome.error + " " + outcome.command)
            paths.update(p.replace("\\", "/").strip("./") for p in found if not p.startswith("http"))
        affected = tuple(sorted(paths))

        now = time.time()
        self._init_table()
        def _fetch_existing() -> Any:
            with closing(connect_sqlite(self.state_store.db_path)) as con:
                return con.execute(
                    """
                    SELECT incident_id, state_revision, attempts, root_cause, verified_fix, confidence,
                           affected_paths, ignored, resolved
                    FROM agent_incidents
                    WHERE error_class = ? AND operation_class = ? AND signature_hash = ?
                      AND repository_key = ? AND tenant_key = ?
                    ORDER BY updated_at DESC, incident_id DESC LIMIT 1
                    """,
                    (err_class, op_class, sig_hash, repository_key, tenant_key),
                ).fetchone()

        row = retry_busy(_fetch_existing, retries=5, base_delay_seconds=0.02)

        if row:
            inc_id = str(row[0])
            old_rc, old_fix, old_conf = row[3], row[4], row[5]
            old_aff = tuple(json.loads(row[6]) if row[6] else ())
            was_resolved = bool(row[8])
            new_attempts = int(row[2]) + 1
            updated = IncidentRecord(
                incident_id=inc_id,
                fingerprint=fp,
                operation_class=op_class,
                error_class=err_class,
                redacted_message=redacted,
                state_revision=outcome.state_revision,
                attempts=new_attempts,
                evidence_ids=outcome.evidence_ids,
                root_cause=eff_rc or old_rc,
                verified_fix=eff_fix or (None if was_resolved else old_fix),
                confidence=eff_conf if was_resolved else max(eff_conf, float(old_conf or 0.0)),
                resolved=False,
                ignored=bool(row[7]),
                created_at=now,
                updated_at=now,
                affected_paths=affected or old_aff,
                repository_key=repository_key,
                tenant_key=tenant_key,
            )
            event = AgentEvent.create(
                stream_id=f"incident:{inc_id}",
                kind="incident.repeated",
                payload={"attempts": new_attempts, "updated_at": now},
                idempotency_key=f"inc_rep_{inc_id}_{new_attempts}",
                actor="system",
            )
            self.state_store.append(event)
            self._save_record(updated)
            return updated

        new_id = f"inc_{uuid.uuid4().hex[:12]}"
        record = IncidentRecord(
            incident_id=new_id,
            fingerprint=fp,
            operation_class=op_class,
            error_class=err_class,
            redacted_message=redacted,
            state_revision=outcome.state_revision,
            attempts=1,
            evidence_ids=outcome.evidence_ids,
            root_cause=eff_rc,
            verified_fix=eff_fix,
            confidence=eff_conf,
            created_at=now,
            updated_at=now,
            affected_paths=affected,
            repository_key=repository_key,
            tenant_key=tenant_key,
        )

        event = AgentEvent.create(
            stream_id=f"incident:{new_id}",
            kind="incident.captured",
            payload=record.to_dict(),
            idempotency_key=f"inc_cap_{new_id}",
            actor="system",
        )
        self.state_store.append(event)
        self._save_record(record)
        self._dispatch_webhooks(record.to_dict())
        return record

    def resolve(
        self,
        incident_id: str,
        *,
        verified_fix: str,
        confidence: float = 1.0,
        root_cause: str | None = None,
    ) -> IncidentRecord:
        record = self.get(incident_id)
        if not record:
            raise KeyError(f"Incident {incident_id} not found")

        resolved_rec = IncidentRecord(
            incident_id=record.incident_id,
            fingerprint=record.fingerprint,
            operation_class=record.operation_class,
            error_class=record.error_class,
            redacted_message=record.redacted_message,
            state_revision=record.state_revision,
            attempts=record.attempts,
            evidence_ids=record.evidence_ids,
            root_cause=root_cause or record.root_cause,
            verified_fix=verified_fix,
            confidence=float(confidence),
            resolved=True,
            ignored=False,
            created_at=record.created_at,
            updated_at=time.time(),
            expires_at=record.expires_at,
            affected_paths=record.affected_paths,
            repository_key=record.repository_key,
            tenant_key=record.tenant_key,
        )

        event = AgentEvent.create(
            stream_id=f"incident:{incident_id}",
            kind="incident.resolved",
            payload={"verified_fix": verified_fix, "confidence": confidence, "root_cause": root_cause},
            idempotency_key=f"inc_res_{incident_id}_{int(time.time())}",
            actor="agent",
        )
        self.state_store.append(event)
        self._init_table()
        with closing(connect_sqlite(self.state_store.db_path)) as con:
            with con:
                con.execute(
                    """
                    UPDATE agent_incidents
                    SET root_cause = COALESCE(?, root_cause), verified_fix = ?, confidence = ?,
                        resolved = 1, ignored = 0, updated_at = ?
                    WHERE operation_class = ? AND error_class = ? AND signature_hash = ?
                    """,
                    (
                        resolved_rec.root_cause, resolved_rec.verified_fix, resolved_rec.confidence,
                        resolved_rec.updated_at, record.operation_class, record.error_class,
                        record.fingerprint.signature_hash,
                    ),
                )
        return self.get(incident_id) or resolved_rec

    def resolve_all(
        self,
        *,
        verified_fix: str = "Resolved by operator",
        root_cause: str | None = None,
        timeout_seconds: float = 2.0,
    ) -> int:
        if not self.state_store.enabled or not self.state_store.db_path.exists():
            return 0
        timeout_seconds = max(0.01, min(10.0, float(timeout_seconds)))
        deadline = time.monotonic() + timeout_seconds
        self._init_table()
        self.state_store._ensure_schema()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("incident resolution time budget exceeded")
        connection_timeout = min(1.0, remaining)
        now = time.time()
        event_to_publish: AgentEvent | None = None
        try:
            with closing(connect_sqlite(self.state_store.db_path, timeout_seconds=connection_timeout)) as con:
                con.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
                try:
                    with con:
                        cur = con.execute(
                            """
                            UPDATE agent_incidents
                            SET resolved = 1, ignored = 0, verified_fix = COALESCE(verified_fix, ?),
                                root_cause = COALESCE(root_cause, ?), updated_at = ?
                            WHERE resolved = 0
                            """,
                            (verified_fix, root_cause or "Operator cleared unresolved incidents", now),
                        )
                        count = cur.rowcount
                        if count > 0:
                            event = AgentEvent.create(
                                stream_id="incident:all",
                                kind="incident.all_resolved",
                                payload={"verified_fix": verified_fix, "resolved_count": count},
                                idempotency_key=f"inc_res_all_{uuid.uuid4().hex}",
                                actor="operator",
                            )
                            appended = self.state_store.append_in_transaction(con, event)
                            if appended.retryable:
                                raise TimeoutError("incident resolution event append timed out")
                            if appended.error:
                                raise RuntimeError(appended.error)
                            if not appended.duplicate:
                                event_to_publish = appended.event
                        if time.monotonic() >= deadline:
                            raise TimeoutError("incident resolution time budget exceeded")
                finally:
                    con.set_progress_handler(None, 0)
        except Exception as exc:
            message = str(exc).lower()
            if isinstance(exc, TimeoutError) or time.monotonic() >= deadline or "interrupt" in message or "locked" in message or "busy" in message:
                raise TimeoutError("incident resolution time budget exceeded") from exc
            raise
        # The durable commit is final; publish wakes live streams and cannot change its outcome.
        if event_to_publish is not None:
            try:
                self.state_store._publish(event_to_publish)
            except Exception:
                pass
        return count

    def set_ignored(self, incident_id: str, ignored: bool = True) -> IncidentRecord:
        record = self.get(incident_id)
        if not record:
            raise KeyError(f"Incident {incident_id} not found")

        ignored = bool(ignored)
        now = time.time()
        action = "ignored" if ignored else "unignored"
        event = AgentEvent.create(
            stream_id=f"incident:{incident_id}",
            kind=f"incident.{action}",
            payload={"ignored": ignored, "updated_at": now},
            idempotency_key=f"inc_{action}_{incident_id}_{uuid.uuid4().hex}",
            actor="agent",
        )
        self.state_store.append(event)
        with closing(connect_sqlite(self.state_store.db_path)) as con:
            with con:
                con.execute(
                    """
                    UPDATE agent_incidents SET ignored = ?, updated_at = ?
                    WHERE operation_class = ? AND error_class = ? AND signature_hash = ?
                    """,
                    (
                        1 if ignored else 0, now, record.operation_class, record.error_class,
                        record.fingerprint.signature_hash,
                    ),
                )
        return self.get(incident_id) or record

    def retry_decision(
        self,
        fingerprint: IncidentFingerprint,
        state_revision: str,
        *,
        root: str | None = None,
        tenant: str | None = None,
    ) -> RetryDecision:
        if not self.state_store.enabled or not self.state_store.db_path.exists():
            return RetryDecision(action="proceed", reason="incident store disabled")
        self._init_table()
        scope_clause = ""
        scope_params: tuple[Any, ...] = ()
        if root is not None or tenant is not None:
            if root is None or tenant is None:
                return RetryDecision(action="stop", reason="incident scope unavailable")
            repository_key = _incident_scope_key("repository", root)
            tenant_key = _incident_scope_key("tenant", tenant)
            if not repository_key or not tenant_key:
                return RetryDecision(action="stop", reason="incident scope unavailable")
            scope_clause = " AND repository_key = ? AND tenant_key = ?"
            scope_params = (repository_key, tenant_key)

        def _fetch_decision() -> Any:
            with closing(connect_sqlite(self.state_store.db_path)) as con:
                cur = con.execute(
                    f"""
                    SELECT state_revision, verified_fix, confidence, resolved, ignored
                    FROM agent_incidents
                    WHERE operation_class = ? AND error_class = ? AND signature_hash = ?
                      {scope_clause}
                    ORDER BY updated_at DESC, incident_id DESC LIMIT 1
                    """,
                    (fingerprint.operation_class, fingerprint.error_class, fingerprint.signature_hash, *scope_params),
                )
                return cur.fetchone()

        rows = retry_busy(_fetch_decision, retries=5, base_delay_seconds=0.02)

        if not rows:
            return RetryDecision(action="proceed", reason="no prior incidents found")

        rev, fix, confidence, resolved, ignored = rows
        if ignored:
            return RetryDecision(action="proceed", reason="matching incident is ignored")
        if fix and confidence >= 0.8:
            return RetryDecision(
                action="apply_verified_fix",
                reason="verified fix exists with high confidence",
                verified_fix=fix,
                confidence=confidence,
            )
        if not resolved:
            if rev == state_revision:
                return RetryDecision(
                    action="stop",
                    reason=f"negative knowledge: identical error failed on unchanged revision {state_revision}",
                )
            return RetryDecision(
                action="retry",
                reason=f"state revision changed from {rev} to {state_revision}",
            )

        return RetryDecision(action="proceed", reason="no blocking incidents")

    def get(self, incident_id: str) -> IncidentRecord | None:
        if not self.state_store.enabled or not self.state_store.db_path.exists():
            return None
        self._init_table()
        def _fetch_record() -> Any:
            with closing(connect_sqlite(self.state_store.db_path)) as con:
                return con.execute(
                    """
                    SELECT incident_id, operation_class, error_class, signature_hash, redacted_message,
                           state_revision, attempts, evidence_ids, root_cause, verified_fix,
                           confidence, resolved, created_at, updated_at, expires_at, affected_paths, ignored,
                           repository_key, tenant_key
                    FROM agent_incidents
                    WHERE incident_id = ?
                    """,
                    (incident_id,),
                ).fetchone()

        row = retry_busy(_fetch_record, retries=5, base_delay_seconds=0.02)
        if not row:
            return None
        return self._row_to_record(row)

    def list_incidents(
        self,
        resolved: bool | None = None,
        limit: int = 100,
        status: str | None = None,
    ) -> list[IncidentRecord]:
        if not self.state_store.enabled or not self.state_store.db_path.exists():
            return []
        if isinstance(resolved, str):
            resolved_norm = resolved.strip().lower()
            if resolved_norm in {"true", "1", "yes", "resolved"}:
                resolved = True
            elif resolved_norm in {"false", "0", "no", "unresolved"}:
                resolved = False
            else:
                resolved = None
        self._init_table()
        def _fetch_list() -> list[Any]:
            with closing(connect_sqlite(self.state_store.db_path)) as con:
                query = """
                    WITH ranked AS (
                        SELECT incident_id, operation_class, error_class, signature_hash, redacted_message,
                               state_revision,
                               SUM(attempts) OVER (PARTITION BY operation_class, error_class, signature_hash, repository_key, tenant_key) AS attempts,
                               evidence_ids, root_cause, verified_fix, confidence, resolved, created_at,
                               updated_at, expires_at, affected_paths, ignored, repository_key, tenant_key,
                               ROW_NUMBER() OVER (
                                   PARTITION BY operation_class, error_class, signature_hash, repository_key, tenant_key
                                   ORDER BY updated_at DESC, incident_id DESC
                               ) AS row_num
                        FROM agent_incidents
                    )
                    SELECT incident_id, operation_class, error_class, signature_hash, redacted_message,
                           state_revision, attempts, evidence_ids, root_cause, verified_fix, confidence,
                           resolved, created_at, updated_at, expires_at, affected_paths, ignored,
                           repository_key, tenant_key
                    FROM ranked WHERE row_num = 1
                """
                params: list[Any] = []
                filters: list[str] = []
                if resolved is not None:
                    filters.append("resolved = ?")
                    params.append(1 if resolved else 0)
                status_norm = str(status or "").strip().lower()
                if status_norm not in {"", "ignored", "resolved", "unresolved"}:
                    status_norm = ""
                if status_norm == "ignored":
                    filters.append("ignored = 1")
                elif status_norm == "resolved":
                    filters.extend(("ignored = 0", "resolved = 1"))
                elif status_norm == "unresolved":
                    filters.extend(("ignored = 0", "resolved = 0"))
                if filters:
                    query += " AND " + " AND ".join(filters)
                query += " ORDER BY updated_at DESC LIMIT ?"
                params.append(max(1, int(limit)))
                cur = con.execute(query, tuple(params))
                return cur.fetchall()

        rows = retry_busy(_fetch_list, retries=5, base_delay_seconds=0.02)
        return [self._row_to_record(r) for r in rows]

    def has_incidents(self) -> bool:
        if not self.state_store.enabled or not self.state_store.db_path.exists():
            return False
        self._init_table()

        def _check() -> bool:
            with closing(connect_sqlite(self.state_store.db_path)) as con:
                row = con.execute("SELECT 1 FROM agent_incidents LIMIT 1").fetchone()
                return row is not None

        return retry_busy(_check, retries=5, base_delay_seconds=0.02)

    def incident_count(self, resolved: bool | None = None) -> int:
        if not self.state_store.enabled or not self.state_store.db_path.exists():
            return 0
        self._init_table()

        def _count() -> int:
            with closing(connect_sqlite(self.state_store.db_path)) as con:
                if resolved is None:
                    row = con.execute("SELECT COUNT(*) FROM agent_incidents").fetchone()
                else:
                    val = 1 if resolved else 0
                    row = con.execute("SELECT COUNT(*) FROM agent_incidents WHERE resolved = ?", (val,)).fetchone()
                return int(row[0]) if row else 0

        return retry_busy(_count, retries=5, base_delay_seconds=0.02)

    def _save_record(self, record: IncidentRecord) -> None:
        if not self.state_store.enabled:
            return
        self._init_table()

        def _do_save() -> None:
            con = connect_sqlite(self.state_store.db_path, isolation_level=None)
            try:
                con.execute("BEGIN IMMEDIATE")
                con.execute(
                    """
                    INSERT INTO agent_incidents (
                        incident_id, operation_class, error_class, signature_hash,
                        redacted_message, state_revision, attempts, evidence_ids,
                        root_cause, verified_fix, confidence, resolved,
                        created_at, updated_at, expires_at, affected_paths, ignored,
                        repository_key, tenant_key
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(incident_id) DO UPDATE SET
                        redacted_message = excluded.redacted_message,
                        state_revision = excluded.state_revision,
                        attempts = excluded.attempts,
                        evidence_ids = excluded.evidence_ids,
                        root_cause = excluded.root_cause,
                        verified_fix = excluded.verified_fix,
                        confidence = excluded.confidence,
                        resolved = excluded.resolved,
                        ignored = excluded.ignored,
                        updated_at = excluded.updated_at,
                        expires_at = excluded.expires_at,
                        affected_paths = excluded.affected_paths,
                        repository_key = excluded.repository_key,
                        tenant_key = excluded.tenant_key
                    """,
                    (
                        record.incident_id,
                        record.operation_class,
                        record.error_class,
                        record.fingerprint.signature_hash,
                        record.redacted_message,
                        record.state_revision,
                        record.attempts,
                        json_dumps(list(record.evidence_ids)),
                        record.root_cause,
                        record.verified_fix,
                        record.confidence,
                        1 if record.resolved else 0,
                        record.created_at,
                        record.updated_at,
                        record.expires_at,
                        json_dumps(list(record.affected_paths)),
                        1 if record.ignored else 0,
                        record.repository_key,
                        record.tenant_key,
                    ),
                )
                con.execute("COMMIT")
            except Exception:
                try:
                    con.execute("ROLLBACK")
                except Exception:
                    pass
                raise
            finally:
                con.close()

        retry_busy(_do_save, retries=5, base_delay_seconds=0.02)

    def _row_to_record(self, row: tuple[Any, ...]) -> IncidentRecord:
        (
            incident_id,
            operation_class,
            error_class,
            signature_hash,
            redacted_message,
            state_revision,
            attempts,
            evidence_ids_raw,
            root_cause,
            verified_fix,
            confidence,
            resolved_val,
            created_at,
            updated_at,
            expires_at,
        ) = row[:15]
        affected_paths_raw = row[15] if len(row) > 15 else "[]"
        ignored_val = row[16] if len(row) > 16 else 0
        repository_key = str(row[17] or "") if len(row) > 17 else ""
        tenant_key = str(row[18] or "") if len(row) > 18 else ""
        aff_paths = tuple(json.loads(affected_paths_raw) if affected_paths_raw else ())
        fp = IncidentFingerprint(
            error_class=error_class,
            operation_class=operation_class,
            signature_hash=signature_hash,
        )
        return IncidentRecord(
            incident_id=incident_id,
            fingerprint=fp,
            operation_class=operation_class,
            error_class=error_class,
            redacted_message=redacted_message,
            state_revision=state_revision,
            attempts=int(attempts),
            evidence_ids=tuple(json.loads(evidence_ids_raw) if evidence_ids_raw else ()),
            root_cause=root_cause,
            verified_fix=verified_fix,
            confidence=float(confidence),
            resolved=bool(resolved_val),
            ignored=bool(ignored_val),
            created_at=float(created_at),
            updated_at=float(updated_at),
            expires_at=float(expires_at) if expires_at is not None else None,
            affected_paths=aff_paths,
            repository_key=repository_key,
            tenant_key=tenant_key,
        )

    def find_regressions(self, paths: Collection[str], *, state_revision: str | None = None) -> list[dict[str, Any]]:
        if not self.state_store.enabled or not self.state_store.db_path.exists() or not paths:
            return []
        self._init_table()
        norm_targets = [p.replace("\\", "/").strip("/").lower() for p in paths if p]
        if not norm_targets:
            return []
        con = connect_sqlite(self.state_store.db_path)
        try:
            cur = con.execute(
                """
                WITH ranked AS (
                    SELECT incident_id, operation_class, error_class, signature_hash, redacted_message,
                           state_revision, root_cause, verified_fix, confidence,
                           SUM(attempts) OVER (
                               PARTITION BY operation_class, error_class, signature_hash, repository_key, tenant_key
                           ) AS attempts,
                           affected_paths, updated_at, ignored,
                           ROW_NUMBER() OVER (
                               PARTITION BY operation_class, error_class, signature_hash
                               ORDER BY updated_at DESC, incident_id DESC
                           ) AS row_num
                    FROM agent_incidents
                )
                SELECT incident_id, operation_class, error_class, redacted_message,
                       state_revision, root_cause, verified_fix, confidence, attempts, affected_paths, updated_at
                FROM ranked
                WHERE row_num = 1 AND verified_fix IS NOT NULL AND confidence >= 0.6 AND ignored = 0
                ORDER BY updated_at DESC
                """
            )
            regressions: list[dict[str, Any]] = []
            for row in cur.fetchall():
                inc_id, op, err_cls, msg, rev, rc, fix, conf, attempts, aff_raw, updated_at = row
                if state_revision is not None and str(rev or "") != str(state_revision):
                    continue
                aff_paths = json.loads(aff_raw) if aff_raw else []
                matched = False
                for p in aff_paths:
                    norm_p = str(p).replace("\\", "/").strip("/").lower()
                    for target in norm_targets:
                        if (
                            norm_p == target
                            or norm_p.endswith("/" + target)
                            or target.endswith("/" + norm_p)
                            or (norm_p.split("/")[-1] == target.split("/")[-1] and len(target.split("/")[-1]) > 3)
                        ):
                            matched = True
                            break
                    if matched:
                        break
                if matched:
                    regressions.append({
                        "incident_id": inc_id,
                        "error_class": err_cls,
                        "operation_class": op,
                        "redacted_message": msg,
                        "root_cause": rc or "",
                        "verified_fix": fix or "",
                        "confidence": float(conf or 0.0),
                        "affected_paths": aff_paths,
                        "attempts": int(attempts or 1),
                        "updated_at": float(updated_at or 0.0),
                    })
            return regressions
        finally:
            con.close()

    def find_negative_knowledge(
        self,
        query: str = "",
        limit: int = 20,
        *,
        root: str | None = None,
        tenant: str | None = None,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        if not self.state_store.enabled or not self.state_store.db_path.exists():
            return []
        self._init_table()
        if root is None or tenant is None:
            return []
        repository_key = _incident_scope_key("repository", root)
        tenant_key = _incident_scope_key("tenant", tenant)
        if not repository_key or not tenant_key:
            return []
        scoped = True
        scope_sql = "WHERE repository_key = ? AND tenant_key = ?"
        scope_params = (repository_key, tenant_key)
        con = connect_sqlite(self.state_store.db_path)
        try:
            cur = con.execute(
                f"""
                WITH ranked AS (
                    SELECT incident_id, operation_class, error_class, signature_hash, redacted_message,
                           state_revision, root_cause, verified_fix, confidence,
                           SUM(attempts) OVER (PARTITION BY operation_class, error_class, signature_hash) AS attempts,
                           updated_at, affected_paths, ignored, expires_at, repository_key, tenant_key,
                           ROW_NUMBER() OVER (
                               PARTITION BY operation_class, error_class, signature_hash, repository_key, tenant_key
                               ORDER BY updated_at DESC, incident_id DESC
                           ) AS row_num
                    FROM agent_incidents
                    WHERE repository_key = ? AND tenant_key = ?
                )
                SELECT incident_id, operation_class, error_class, redacted_message, state_revision,
                       root_cause, verified_fix, confidence, attempts, updated_at, affected_paths,
                       repository_key, tenant_key
                FROM ranked
                WHERE ignored = 0 AND row_num = 1
                  AND (expires_at IS NULL OR expires_at > ?)
                ORDER BY updated_at DESC
                """,
                (*scope_params, time.time()),
            )
            q_norm = str(query or "").strip().lower()
            results: list[dict[str, Any]] = []
            for r in cur.fetchall():
                rc = str(r[5] or "")
                fix = str(r[6] or "")
                msg = str(r[3] or "")
                err_cls = str(r[2] or "")
                aff = str(r[10] or "") if len(r) > 10 else ""
                if q_norm:
                    _STOPWORDS = {"python", "python3", "pytest", "tests", "test", "pip", "node", "npm", "pnpm", "yarn", "cargo", "bash", "sh", "run", "exec", "status", "list", "true", "false", "none"}
                    q_words = [w for w in q_norm.replace("/", " ").replace("\\", " ").replace(".", " ").split() if len(w) >= 3 and w not in _STOPWORDS]
                    matched = (
                        q_norm in rc.lower() or q_norm in fix.lower() or q_norm in msg.lower() or q_norm in err_cls.lower() or
                        (bool(q_words) and any(w in rc.lower() or w in fix.lower() or w in msg.lower() or w in aff.lower() for w in q_words))
                    )
                    if not matched:
                        continue
                item = {
                    "incident_id": r[0],
                    "operation_class": r[1],
                    "error_class": err_cls,
                    "redacted_message": msg,
                    "state_revision": r[4],
                    "root_cause": rc,
                    "verified_fix": fix,
                    "confidence": float(r[7] or 0.0),
                    "attempts": int(r[8] or 1),
                    "updated_at": float(r[9] or 0.0),
                }
                item["provenance"] = {
                    "repository_key": str(r[11] or ""),
                    "tenant_key": str(r[12] or ""),
                }
                results.append(item)
                if len(results) >= limit:
                    break
            return results
        finally:
            con.close()
