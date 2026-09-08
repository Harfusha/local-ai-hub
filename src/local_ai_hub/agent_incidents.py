from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .agent_events import AgentEvent, AgentStateStore
from .sqlite_support import connect_sqlite, retry_busy


@dataclass(frozen=True)
class IncidentFingerprint:
    error_class: str
    operation_class: str
    signature_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_class": self.error_class,
            "operation_class": self.operation_class,
            "signature_hash": self.signature_hash,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> IncidentFingerprint:
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
    created_at: float = 0.0
    updated_at: float = 0.0
    expires_at: float | None = None
    affected_paths: tuple[str, ...] = ()

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
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "expires_at": self.expires_at,
            "affected_paths": list(self.affected_paths),
        }


@dataclass(frozen=True)
class RetryDecision:
    action: str  # "apply_verified_fix", "stop", "retry", "proceed"
    reason: str
    verified_fix: str | None = None
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "verified_fix": self.verified_fix,
            "confidence": self.confidence,
        }


def _redact_message(msg: str) -> str:
    cleaned = re.sub(r"[a-zA-Z]:\\[^\s:\"']+", "[PATH]", msg)
    cleaned = re.sub(r"/[a-zA-Z0-9_\.-]+/[^\s:\"']+", "[PATH]", cleaned)
    cleaned = re.sub(r"(token|secret|key|password)[=:]\s*\S+", r"\1=[REDACTED]", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()[:256]


def _normalize_signature(msg: str) -> str:
    # Lowercase, remove numbers, file extensions, extra spaces
    norm = msg.lower()
    norm = re.sub(r"0x[0-9a-f]+", "", norm)
    norm = re.sub(r"\d+", "", norm)
    norm = re.sub(r"[^\w\s]", " ", norm)
    norm = " ".join(norm.split())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def _classify_error(error_msg: str, timed_out: bool) -> str:
    if timed_out:
        return "TimeoutError"
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
        return f"package.json missing script '{script}'", f"check available npm scripts in package.json", 0.95

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


class IncidentStore:
    def __init__(self, state_store: AgentStateStore) -> None:
        self.state_store = state_store
        self._lock = threading.RLock()
        self._initialized = False
        self._init_table()

    def _init_table(self) -> None:
        if self._initialized or not self.state_store.enabled:
            return
        with self._lock:
            if self._initialized or not self.state_store.enabled:
                return
            self.state_store._ensure_schema()
            def _setup() -> None:
                con = connect_sqlite(self.state_store.db_path)
                try:
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
                                affected_paths TEXT NOT NULL DEFAULT '[]'
                            );
                            """
                        )
                        try:
                            con.execute("ALTER TABLE agent_incidents ADD COLUMN affected_paths TEXT NOT NULL DEFAULT '[]'")
                        except Exception:
                            pass
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

        meta_rc = str(outcome.metadata.get("root_cause") or "")
        meta_fix = str(outcome.metadata.get("verified_fix") or "")
        meta_conf = float(outcome.metadata.get("confidence") or 0.0)
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
                    SELECT incident_id, attempts, root_cause, verified_fix, confidence, affected_paths FROM agent_incidents
                    WHERE error_class = ? AND operation_class = ? AND signature_hash = ? AND state_revision = ?
                    """,
                    (err_class, op_class, sig_hash, outcome.state_revision),
                ).fetchone()

        row = retry_busy(_fetch_existing, retries=5, base_delay_seconds=0.02)

        if row:
            inc_id, attempts, old_rc, old_fix, old_conf = row[0], row[1], row[2], row[3], row[4]
            old_aff = tuple(json.loads(row[5]) if len(row) > 5 and row[5] else ())
            new_attempts = attempts + 1
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
                verified_fix=eff_fix or old_fix,
                confidence=max(eff_conf, float(old_conf or 0.0)),
                created_at=now,
                updated_at=now,
                affected_paths=affected or old_aff,
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
            created_at=record.created_at,
            updated_at=time.time(),
            expires_at=record.expires_at,
            affected_paths=record.affected_paths,
        )

        event = AgentEvent.create(
            stream_id=f"incident:{incident_id}",
            kind="incident.resolved",
            payload={"verified_fix": verified_fix, "confidence": confidence, "root_cause": root_cause},
            idempotency_key=f"inc_res_{incident_id}_{int(time.time())}",
            actor="agent",
        )
        self.state_store.append(event)
        self._save_record(resolved_rec)
        return resolved_rec

    def retry_decision(
        self,
        fingerprint: IncidentFingerprint,
        state_revision: str,
    ) -> RetryDecision:
        if not self.state_store.enabled or not self.state_store.db_path.exists():
            return RetryDecision(action="proceed", reason="incident store disabled")
        self._init_table()
        def _fetch_decision() -> list[Any]:
            with closing(connect_sqlite(self.state_store.db_path)) as con:
                cur = con.execute(
                    """
                    SELECT incident_id, state_revision, verified_fix, confidence, resolved
                    FROM agent_incidents
                    WHERE operation_class = ? AND signature_hash = ?
                    ORDER BY updated_at DESC
                    """,
                    (fingerprint.operation_class, fingerprint.signature_hash),
                )
                return cur.fetchall()

        rows = retry_busy(_fetch_decision, retries=5, base_delay_seconds=0.02)

        if not rows:
            return RetryDecision(action="proceed", reason="no prior incidents found")

        # Check for verified fix first
        for _, rev, fix, conf, resolved in rows:
            if fix and conf >= 0.8:
                return RetryDecision(
                    action="apply_verified_fix",
                    reason="verified fix exists with high confidence",
                    verified_fix=fix,
                    confidence=conf,
                )

        # Check unresolved incidents
        for _, rev, _, _, resolved in rows:
            if not resolved:
                if rev == state_revision:
                    return RetryDecision(
                        action="stop",
                        reason=f"negative knowledge: identical error failed on unchanged revision {state_revision}",
                    )
                else:
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
                           confidence, resolved, created_at, updated_at, expires_at, affected_paths
                    FROM agent_incidents
                    WHERE incident_id = ?
                    """,
                    (incident_id,),
                ).fetchone()

        row = retry_busy(_fetch_record, retries=5, base_delay_seconds=0.02)
        if not row:
            return None
        return self._row_to_record(row)

    def list_incidents(self, resolved: bool | None = None, limit: int = 100) -> list[IncidentRecord]:
        if not self.state_store.enabled or not self.state_store.db_path.exists():
            return []
        self._init_table()
        def _fetch_list() -> list[Any]:
            with closing(connect_sqlite(self.state_store.db_path)) as con:
                query = "SELECT incident_id, operation_class, error_class, signature_hash, redacted_message, state_revision, attempts, evidence_ids, root_cause, verified_fix, confidence, resolved, created_at, updated_at, expires_at, affected_paths FROM agent_incidents"
                params: list[Any] = []
                if resolved is not None:
                    query += " WHERE resolved = ?"
                    params.append(1 if resolved else 0)
                query += " ORDER BY updated_at DESC LIMIT ?"
                params.append(max(1, int(limit)))
                cur = con.execute(query, tuple(params))
                return cur.fetchall()

        rows = retry_busy(_fetch_list, retries=5, base_delay_seconds=0.02)
        return [self._row_to_record(r) for r in rows]

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
                        created_at, updated_at, expires_at, affected_paths
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(incident_id) DO UPDATE SET
                        attempts = excluded.attempts,
                        root_cause = excluded.root_cause,
                        verified_fix = excluded.verified_fix,
                        confidence = excluded.confidence,
                        resolved = excluded.resolved,
                        updated_at = excluded.updated_at,
                        expires_at = excluded.expires_at,
                        affected_paths = excluded.affected_paths
                    """,
                    (
                        record.incident_id,
                        record.operation_class,
                        record.error_class,
                        record.fingerprint.signature_hash,
                        record.redacted_message,
                        record.state_revision,
                        record.attempts,
                        json.dumps(list(record.evidence_ids)),
                        record.root_cause,
                        record.verified_fix,
                        record.confidence,
                        1 if record.resolved else 0,
                        record.created_at,
                        record.updated_at,
                        record.expires_at,
                        json.dumps(list(record.affected_paths)),
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
            created_at=float(created_at),
            updated_at=float(updated_at),
            expires_at=float(expires_at) if expires_at is not None else None,
            affected_paths=aff_paths,
        )

    def find_regressions(self, paths: Collection[str]) -> list[dict[str, Any]]:
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
                SELECT incident_id, operation_class, error_class, redacted_message,
                       state_revision, root_cause, verified_fix, confidence, attempts, affected_paths, updated_at
                FROM agent_incidents
                WHERE verified_fix IS NOT NULL AND confidence >= 0.6
                ORDER BY updated_at DESC
                """
            )
            regressions: list[dict[str, Any]] = []
            for row in cur.fetchall():
                inc_id, op, err_cls, msg, rev, rc, fix, conf, attempts, aff_raw, updated_at = row
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

    def find_negative_knowledge(self, query: str = "", limit: int = 20) -> list[dict[str, Any]]:
        if not self.state_store.enabled or not self.state_store.db_path.exists():
            return []
        self._init_table()
        con = connect_sqlite(self.state_store.db_path)
        try:
            cur = con.execute(
                """
                SELECT incident_id, operation_class, error_class, redacted_message, state_revision,
                       root_cause, verified_fix, confidence, attempts, updated_at
                FROM agent_incidents
                ORDER BY updated_at DESC
                """
            )
            q_norm = str(query or "").strip().lower()
            results: list[dict[str, Any]] = []
            for r in cur.fetchall():
                rc = str(r[5] or "")
                fix = str(r[6] or "")
                msg = str(r[3] or "")
                err_cls = str(r[2] or "")
                if q_norm:
                    if (q_norm not in rc.lower() and q_norm not in fix.lower() and
                        q_norm not in msg.lower() and q_norm not in err_cls.lower()):
                        continue
                results.append({
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
                })
                if len(results) >= limit:
                    break
            return results
        finally:
            con.close()
