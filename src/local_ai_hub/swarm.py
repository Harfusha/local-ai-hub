from __future__ import annotations

from .json_utils import dumps as json_dumps

import concurrent.futures
import hashlib
import json
import math
import sqlite3
import time
from contextlib import closing
from enum import Enum
from functools import wraps
from pathlib import Path
from typing import Any
from uuid import uuid4

from .agent_blackboard import BlackboardStore
from .agent_events import AgentEvent, AgentStateStore
from .agent_verification import VerificationStore
from .leases import ScopeLeaseStore
from .sqlite_support import connect_sqlite, initialize_wal, validate_durable_schema


def _serialized_event_writer(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self.state_store._append_publish_lock:
            return method(self, *args, **kwargs)

    return wrapped


class SwarmState(str, Enum):
    PENDING = "PENDING"
    CODING = "CODING"
    TESTING = "TESTING"
    REVIEWING = "REVIEWING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ConcurrentSwarmUpdateError(RuntimeError):
    """Raised when a swarm compare-and-set loses to a concurrent step."""


class SwarmCoordinator:
    """Coordinates autonomous multi-agent swarms (Coder, Tester, Reviewer)

    with atomic lease claims, CRDT blackboard communication, and receipt minting.
    """

    def __init__(
        self,
        db_path: Path | str,
        leases: ScopeLeaseStore | None = None,
        blackboard: BlackboardStore | None = None,
        verifications: VerificationStore | None = None,
        state_store: AgentStateStore | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.leases = leases
        self.blackboard = blackboard
        self.verifications = verifications
        self.state_store = state_store or (
            verifications.state_store if verifications is not None else AgentStateStore(self.db_path)
        )
        if self.state_store.db_path.resolve() != self.db_path.resolve():
            raise ValueError("swarm and agent state stores must share one SQLite database")
        if self.blackboard is not None:
            if self.blackboard.db_path.resolve() != self.db_path.resolve():
                raise ValueError("swarm and blackboard stores must share one SQLite database")
            if self.blackboard.state_store is None:
                self.blackboard.state_store = self.state_store
            elif self.blackboard.state_store.db_path.resolve() != self.db_path.resolve():
                raise ValueError("swarm and blackboard state stores must share one SQLite database")
        if self.verifications is not None and self.verifications.state_store.db_path.resolve() != self.db_path.resolve():
            raise ValueError("swarm and verification stores must share one SQLite database")
        self._init_db()
        self._reconcile_leases()

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self.db_path, timeout_seconds=5.0)

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if self.state_store.enabled:
            self.state_store._ensure_schema()
        expected = {
            "agent_swarms": [
                ("swarm_id", "TEXT", 0, 1), ("goal", "TEXT", 1, 0),
                ("target_paths", "TEXT", 1, 0), ("test_command", "TEXT", 1, 0),
                ("author", "TEXT", 1, 0), ("root", "TEXT", 1, 0),
                ("state", "TEXT", 1, 0), ("receipt_id", "TEXT", 0, 0),
                ("history", "TEXT", 1, 0), ("created_at", "REAL", 1, 0),
                ("updated_at", "REAL", 1, 0), ("version", "INTEGER", 1, 0),
            ],
        }
        with closing(self._connect()) as con:
            validate_durable_schema(
                con,
                self.db_path,
                expected,
                required_if_event_kinds={"agent_swarms": ("swarm.%",)},
            )
            initialize_wal(con)
            with con:
                con.execute(
                    """
                    CREATE TABLE IF NOT EXISTS agent_swarms (
                        swarm_id TEXT PRIMARY KEY,
                        goal TEXT NOT NULL,
                        target_paths TEXT NOT NULL,
                        test_command TEXT NOT NULL,
                        author TEXT NOT NULL,
                        root TEXT NOT NULL,
                        state TEXT NOT NULL,
                        receipt_id TEXT,
                        history TEXT NOT NULL,
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL,
                        version INTEGER NOT NULL
                    )
                    """
                )

    def _append_event(self, con: sqlite3.Connection, event: AgentEvent, published: list[AgentEvent]) -> None:
        if not self.state_store.enabled:
            return
        result = self.state_store.append_in_transaction(
            con, event, strict_idempotency=True
        )
        if result.error or result.event is None:
            raise RuntimeError(result.error or "swarm event append returned no persisted event")
        if not result.duplicate and result.event is not None:
            published.append(result.event)

    def _publish_after_commit(self, events: list[AgentEvent]) -> None:
        for event in events:
            self.state_store._publish(event)

    @_serialized_event_writer
    def _recover_swarm_state(
        self,
        swarm_id: str,
        expected_version: int,
        expected_state: str,
        new_state: str,
        reason: str,
    ) -> bool:
        if expected_state == new_state:
            return True
        published: list[AgentEvent] = []
        changed = False
        con = self._connect()
        try:
            con.isolation_level = None
            con.execute("BEGIN IMMEDIATE")
            row = con.execute(
                "SELECT version, state, history FROM agent_swarms WHERE swarm_id = ?",
                (swarm_id,),
            ).fetchone()
            if not row or int(row[0]) != expected_version or str(row[1]) != expected_state:
                con.execute("ROLLBACK")
                return False
            version = int(row[0])
            updated_at = time.time()
            cur = con.execute(
                "UPDATE agent_swarms SET state = ?, updated_at = ?, version = ? "
                "WHERE swarm_id = ? AND state = ? AND version = ?",
                (new_state, updated_at, version + 1, swarm_id, expected_state, version),
            )
            if cur.rowcount != 1:
                raise ConcurrentSwarmUpdateError(f"Swarm {swarm_id} changed during recovery")
            self._append_event(
                con,
                AgentEvent.create(
                    stream_id=f"swarm:{swarm_id}",
                    kind="swarm.reconciled",
                    payload={"from_state": expected_state, "state": new_state, "reason": reason},
                    idempotency_key=f"reconcile:{swarm_id}:{version}:{new_state}",
                    actor="system",
                ),
                published,
            )
            con.execute("COMMIT")
            changed = True
        except Exception:
            try:
                con.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            con.close()
        self._publish_after_commit(published)
        return changed

    def _reconcile_leases(self) -> None:
        if self.leases is None:
            return
        with closing(self._connect()) as con:
            rows = con.execute(
                "SELECT swarm_id, root, target_paths, state, version FROM agent_swarms"
            ).fetchall()
        active_leases = self.leases.list()
        tenants = {str(item.get("tenant", "")) for item in active_leases}
        known = {str(row[0]) for row in rows}
        for row in rows:
            swarm_id = str(row[0])
            root = str(row[1])
            paths = json.loads(row[2])
            state = str(row[3])
            version = int(row[4])
            tenant = f"swarm:{swarm_id}"
            if state in (SwarmState.COMPLETED.value, SwarmState.FAILED.value):
                if tenant in tenants:
                    self._release_all_leases(swarm_id)
                continue
            if not paths:
                if state == SwarmState.PENDING.value:
                    self._recover_swarm_state(
                        swarm_id, version, state, SwarmState.CODING.value, "dispatch recovered without paths"
                    )
                continue
            if tenant not in tenants:
                claim = self.leases.claim(
                    tenant=tenant,
                    root=root,
                    paths=paths,
                    ttl_seconds=3600,
                    purpose=f"Swarm recovery: {swarm_id}",
                )
                if not claim.get("success", False):
                    self._recover_swarm_state(
                        swarm_id, version, state, SwarmState.FAILED.value,
                        "owned lease could not be recovered",
                    )
                    continue
            if state == SwarmState.PENDING.value:
                self._recover_swarm_state(
                    swarm_id, version, state, SwarmState.CODING.value, "dispatch lease recovered"
                )
        for lease in active_leases:
            tenant = str(lease.get("tenant", ""))
            if tenant.startswith("swarm:") and tenant[len("swarm:"):] not in known:
                self.leases.release_tenant(tenant)

    def is_valid_swarm_id(self, swarm_id: str) -> bool:
        if not isinstance(swarm_id, str) or not swarm_id.startswith("swarm_") or "\x00" in swarm_id:
            return False
        return len(swarm_id) <= 64

    def active_swarms_count(self) -> int:
        with closing(self._connect()) as con:
            row = con.execute(
                "SELECT COUNT(*) FROM agent_swarms WHERE state NOT IN (?, ?)",
                (SwarmState.COMPLETED.value, SwarmState.FAILED.value),
            ).fetchone()
            return int(row[0]) if row else 0

    @_serialized_event_writer
    def dispatch(
        self,
        goal: str,
        target_paths: list[str] | None = None,
        test_command: str = "",
        author: str = "agent",
        root: str = ".",
    ) -> dict[str, Any]:
        if not isinstance(goal, str) or not goal.strip() or "\x00" in goal:
            raise ValueError("invalid goal")
        paths = list(target_paths or [])
        for p in paths:
            if not isinstance(p, str) or "\x00" in p:
                raise ValueError("target paths cannot contain null bytes")
        swarm_id = f"swarm_{uuid4().hex[:12]}"
        now = time.time()
        needs_lease = bool(self.leases and paths)
        state = SwarmState.PENDING.value if needs_lease else SwarmState.CODING.value
        initial_history = [{
            "timestamp": now,
            "role": "Coordinator",
            "action": "dispatch",
            "payload": {"goal": goal, "target_paths": paths, "test_command": test_command},
        }]
        published: list[AgentEvent] = []
        con = self._connect()
        try:
            con.isolation_level = None
            con.execute("BEGIN IMMEDIATE")
            con.execute(
                """
                INSERT INTO agent_swarms (
                    swarm_id, goal, target_paths, test_command, author, root, state,
                    receipt_id, history, created_at, updated_at, version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    swarm_id, goal, json_dumps(paths), test_command, author, root,
                    state, None, json_dumps(initial_history), now, now, 1,
                ),
            )
            self._append_event(
                con,
                AgentEvent.create(
                    stream_id=f"swarm:{swarm_id}",
                    kind="swarm.dispatched",
                    payload={"goal": goal, "target_paths": paths, "test_command": test_command, "state": state},
                    idempotency_key=f"dispatch:{swarm_id}",
                    actor=author,
                ),
                published,
            )
            con.execute("COMMIT")
        except Exception as exc:
            try:
                con.execute("ROLLBACK")
            except Exception:
                pass
            return {"success": False, "error": str(exc)}
        finally:
            con.close()
        self._publish_after_commit(published)

        if needs_lease:
            self._reconcile_leases()
        status = self.get_status(swarm_id)
        if status.get("state") == SwarmState.FAILED.value:
            return {
                "success": False,
                "error": "Failed to acquire or recover swarm path lease",
                "swarm_id": swarm_id,
                "state": status["state"],
            }
        return {
            "success": True,
            "swarm_id": swarm_id,
            "state": status.get("state", state),
            "goal": goal,
            "target_paths": paths,
            "version": status.get("version", 1),
        }

    def get_status(self, swarm_id: str, *, root: str | None = None) -> dict[str, Any]:
        with closing(self._connect()) as con:
            sql = """
                SELECT swarm_id, goal, target_paths, test_command, author, root, state,
                       receipt_id, history, created_at, updated_at, version
                FROM agent_swarms WHERE swarm_id = ?
            """
            params: list[Any] = [swarm_id]
            if root is not None:
                sql += " AND root = ?"
                params.append(root)
            row = con.execute(sql, tuple(params)).fetchone()
        if not row:
            return {"success": False, "error": f"Swarm '{swarm_id}' not found"}
        return {
            "success": True,
            "swarm_id": row[0],
            "goal": row[1],
            "target_paths": json.loads(row[2]),
            "test_command": row[3],
            "author": row[4],
            "root": row[5],
            "state": row[6],
            "receipt_id": row[7],
            "history": json.loads(row[8]),
            "created_at": row[9],
            "updated_at": row[10],
            "version": int(row[11]),
        }

    def _release_all_leases(self, swarm_id: str) -> bool:
        if self.leases is None:
            return True
        try:
            result = self.leases.release_tenant(f"swarm:{swarm_id}")
            return bool(result.get("success", False))
        except Exception:
            return False

    def step(
        self,
        swarm_id: str,
        role: str,
        action: str,
        payload: dict[str, Any] | None = None,
        *,
        expected_version: int | None = None,
        idempotency_key: str = "",
        root: str | None = None,
    ) -> dict[str, Any]:
        return self._step_transaction(
            swarm_id,
            role,
            action,
            payload or {},
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            root=root,
        )

    @_serialized_event_writer
    def _step_transaction(
        self,
        swarm_id: str,
        role: str,
        action: str,
        payload: dict[str, Any],
        *,
        expected_version: int | None,
        idempotency_key: str,
        root: str | None,
    ) -> dict[str, Any]:
        con = self._connect()
        published: list[AgentEvent] = []
        terminal = False
        receipt_id: str | None = None
        try:
            con.isolation_level = None
            con.execute("BEGIN IMMEDIATE")
            row = con.execute(
                """
                SELECT swarm_id, goal, target_paths, test_command, root, state, receipt_id,
                       history, updated_at, version
                FROM agent_swarms WHERE swarm_id = ?
                """,
                (swarm_id,),
            ).fetchone()
            if not row:
                con.execute("ROLLBACK")
                return {"success": False, "error": f"Swarm '{swarm_id}' not found"}
            if root is not None and str(row[4]) != str(root):
                con.execute("ROLLBACK")
                return {"success": False, "error": f"Swarm '{swarm_id}' not found"}
            current_state = str(row[5])
            current_version = int(row[9])
            requested_version = (
                int(expected_version) if expected_version is not None else None
            )
            payload_fingerprint = hashlib.sha256(
                json_dumps(
                    {"role": role, "action": action, "payload": payload},
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
            ).hexdigest()[:20]
            operation_key = idempotency_key or (
                f"step:{swarm_id}:{payload_fingerprint}"
            )
            existing = con.execute(
                "SELECT seq, event_id, kind, payload, idempotency_key FROM agent_events "
                "WHERE stream_id = ? AND idempotency_key = ?",
                (f"swarm:{swarm_id}", operation_key),
            ).fetchone() if self.state_store.enabled else None
            if existing:
                saved_payload = json.loads(str(existing[3]))
                if (
                    str(existing[2]) != "swarm.step"
                    or saved_payload.get("role") != role
                    or saved_payload.get("action") != action
                    or saved_payload.get("payload") != payload
                    or (
                        "expected_version" in saved_payload
                        and saved_payload.get("expected_version") != requested_version
                    )
                    or (
                        "expected_version" not in saved_payload
                        and requested_version is not None
                    )
                ):
                    con.execute("ROLLBACK")
                    return {
                        "success": False,
                        "error": "idempotency key was already used for a different swarm step",
                        "idempotency_conflict": True,
                        "current_version": current_version,
                    }
                con.execute("COMMIT")
                saved_state = str(saved_payload.get("resulting_state", current_state))
                lease_pending = (
                    saved_state in (SwarmState.COMPLETED.value, SwarmState.FAILED.value)
                    and not self._release_all_leases(swarm_id)
                )
                result = {
                    "success": True, "duplicate": True, "swarm_id": swarm_id,
                    "state": saved_state,
                    "version": int(saved_payload.get("version", current_version)),
                    "current_version": current_version,
                }
                if lease_pending:
                    result["lease_release_pending"] = True
                return result
            if requested_version is not None and current_version != requested_version:
                con.execute("ROLLBACK")
                return {
                    "success": False,
                    "error": "version conflict",
                    "version_conflict": True,
                    "current_version": current_version,
                    "expected_version": requested_version,
                }
            if current_state in (SwarmState.COMPLETED.value, SwarmState.FAILED.value):
                con.execute("ROLLBACK")
                return {
                    "success": False,
                    "error": f"Swarm '{swarm_id}' already terminated with state '{current_state}'",
                    "state": current_state,
                    "version": current_version,
                }

            goal = str(row[1])
            paths = json.loads(row[2])
            test_command = str(row[3])
            old_receipt_id = row[6]
            history = json.loads(row[7])
            now = time.time()
            new_state = current_state
            pay = dict(payload)
            board_section: str | None = None

            if current_state == SwarmState.CODING.value:
                if role != "Coder":
                    con.execute("ROLLBACK")
                    return {"success": False, "error": f"Expected Coder role in CODING state, got '{role}'"}
                board_section = "code"
                new_state = SwarmState.TESTING.value
            elif current_state == SwarmState.TESTING.value:
                if role != "Tester":
                    con.execute("ROLLBACK")
                    return {"success": False, "error": f"Expected Tester role in TESTING state, got '{role}'"}
                board_section = "test"
                new_state = SwarmState.REVIEWING.value if pay.get("passed") is True else SwarmState.FAILED.value
            elif current_state == SwarmState.REVIEWING.value:
                if role != "Reviewer":
                    con.execute("ROLLBACK")
                    return {"success": False, "error": f"Expected Reviewer role in REVIEWING state, got '{role}'"}
                board_section = "review"
                if action == "approve":
                    if self.verifications is None or not self.verifications.state_store.enabled:
                        con.execute("ROLLBACK")
                        return {
                            "success": False, "error": "durable verification store is unavailable",
                            "state": current_state, "retryable": False,
                        }
                    tester = next(
                        (
                            item for item in reversed(history)
                            if item.get("role") == "Tester"
                            and item.get("resulting_state") == SwarmState.REVIEWING.value
                            and item.get("payload", {}).get("passed") is True
                            and item.get("evidence_id")
                        ),
                        None,
                    )
                    if tester is None:
                        con.execute("ROLLBACK")
                        return {
                            "success": False, "error": "successful tester evidence is missing",
                            "state": current_state, "retryable": False,
                        }
                    evidence_id = str(tester["evidence_id"])
                    receipt_key = hashlib.sha256(
                        f"{swarm_id}:{evidence_id}:{current_version}".encode("utf-8")
                    ).hexdigest()[:12]
                    from .agent_verification import VerificationReceipt
                    receipt = VerificationReceipt(
                        receipt_id=f"rcpt_{receipt_key}",
                        task_id=swarm_id,
                        criterion=f"Swarm completed goal: {goal}",
                        evidence_id=evidence_id,
                        command_id=test_command[:100],
                        observed_at=now,
                        passed=True,
                        details={
                            "review": pay,
                            "target_paths": paths,
                            "tester_evidence": tester["payload"],
                        },
                    )
                    new_state = SwarmState.COMPLETED.value
                    receipt_id = receipt.receipt_id
                else:
                    new_state = SwarmState.FAILED.value
            else:
                con.execute("ROLLBACK")
                return {"success": False, "error": f"Unsupported swarm state '{current_state}'"}

            if board_section and self.blackboard is not None:
                board_result = self.blackboard.update(
                    board_id=f"swarm:{swarm_id}",
                    section=board_section,
                    content=pay,
                    author=role,
                    expected_version=0,
                    idempotency_key=f"swarm-step:{swarm_id}:{current_version}:{board_section}",
                    connection=con,
                )
                if not board_result.get("success"):
                    con.execute("ROLLBACK")
                    return {
                        "success": False,
                        "error": board_result.get("error", "blackboard compare-and-set failed"),
                        "version_conflict": bool(board_result.get("version_conflict")),
                        "state": current_state,
                        "version": current_version,
                    }
                blackboard_event = board_result.pop("_event", None)
                if blackboard_event is not None:
                    published.append(blackboard_event)

            step_event = AgentEvent.create(
                stream_id=f"swarm:{swarm_id}",
                kind="swarm.step",
                payload={
                    "role": role,
                    "action": action,
                    "payload": pay,
                    "expected_version": requested_version,
                    "from_state": current_state,
                    "resulting_state": new_state,
                    "version": current_version + 1,
                },
                idempotency_key=operation_key,
                actor=role,
            )
            self._append_event(con, step_event, published)
            evidence_event = next(
                (event for event in reversed(published) if event.kind == "swarm.step" and event.stream_id == f"swarm:{swarm_id}"),
                step_event,
            )
            history.append({
                "timestamp": now,
                "role": role,
                "action": action,
                "payload": pay,
                "resulting_state": new_state,
                **(
                    {"evidence_id": evidence_event.event_id}
                    if role == "Tester" and pay.get("passed") is True
                    else {}
                ),
            })

            if receipt_id and self.verifications is not None:
                receipt_events = self.verifications.record_in_transaction(con, receipt)
                published.extend(receipt_events)

            next_version = current_version + 1
            cur = con.execute(
                """
                UPDATE agent_swarms
                SET state = ?, receipt_id = COALESCE(?, receipt_id), history = ?,
                    updated_at = ?, version = ?
                WHERE swarm_id = ? AND state = ? AND version = ?
                """,
                (
                    new_state, receipt_id, json_dumps(history), now, next_version,
                    swarm_id, current_state, current_version,
                ),
            )
            if cur.rowcount != 1:
                raise ConcurrentSwarmUpdateError(f"Swarm {swarm_id} changed during step")
            con.execute("COMMIT")
            terminal = new_state in (SwarmState.COMPLETED.value, SwarmState.FAILED.value)
        except Exception as exc:
            try:
                con.execute("ROLLBACK")
            except Exception:
                pass
            return {
                "success": False,
                "error": str(exc),
                "state": current_state if "current_state" in locals() else "",
                "version": current_version if "current_version" in locals() else None,
                "retryable": bool(getattr(exc, "retryable", False)),
            }
        finally:
            con.close()

        self._publish_after_commit(published)
        lease_pending = terminal and not self._release_all_leases(swarm_id)
        result: dict[str, Any] = {
            "success": True,
            "swarm_id": swarm_id,
            "state": new_state,
            "role": role,
            "action": action,
            "version": next_version,
        }
        if receipt_id:
            result["receipt_id"] = receipt_id
        if lease_pending:
            result["lease_release_pending"] = True
        return result

    def list_swarms(self, state: str | None = None, limit: int = 50, *, root: str | None = None) -> dict[str, Any]:
        with closing(self._connect()) as con:
            sql = "SELECT swarm_id, goal, target_paths, test_command, author, state, receipt_id, created_at, updated_at FROM agent_swarms"
            params: list[Any] = []
            filters: list[str] = []
            if state:
                filters.append("state = ?")
                params.append(state)
            if root is not None:
                filters.append("root = ?")
                params.append(root)
            if filters:
                sql += " WHERE " + " AND ".join(filters)
            sql += " ORDER BY updated_at DESC LIMIT ?"
            params.append(max(1, int(limit)))
            rows = con.execute(sql, tuple(params)).fetchall()

        swarms = []
        for r in rows:
            swarms.append({
                "swarm_id": r[0],
                "goal": r[1],
                "target_paths": json.loads(r[2]),
                "test_command": r[3],
                "author": r[4],
                "state": r[5],
                "receipt_id": r[6],
                "created_at": r[7],
                "updated_at": r[8],
            })
        return {"success": True, "swarms": swarms, "count": len(swarms)}

    @_serialized_event_writer
    def cancel(
        self,
        swarm_id: str,
        reason: str = "",
        *,
        expected_version: int | None = None,
        idempotency_key: str = "",
        root: str | None = None,
    ) -> dict[str, Any]:
        con = self._connect()
        published: list[AgentEvent] = []
        try:
            con.isolation_level = None
            con.execute("BEGIN IMMEDIATE")
            sql = "SELECT root, state, history, version FROM agent_swarms WHERE swarm_id = ?"
            params: list[Any] = [swarm_id]
            if root is not None:
                sql += " AND root = ?"
                params.append(root)
            row = con.execute(sql, tuple(params)).fetchone()
            if not row:
                con.execute("ROLLBACK")
                return {"success": False, "error": f"Swarm '{swarm_id}' not found"}
            current_state = str(row[1])
            history = json.loads(row[2])
            version = int(row[3])
            requested_version = (
                int(expected_version) if expected_version is not None else None
            )
            clean_reason = str(reason or "cancelled by agent")
            reason_hash = hashlib.sha256(clean_reason.encode("utf-8")).hexdigest()[:16]
            operation_key = idempotency_key or f"cancel:{swarm_id}:{reason_hash}"
            existing = con.execute(
                "SELECT seq, event_id, kind, payload, idempotency_key FROM agent_events "
                "WHERE stream_id = ? AND idempotency_key = ?",
                (f"swarm:{swarm_id}", operation_key),
            ).fetchone() if self.state_store.enabled else None
            if existing:
                saved_payload = json.loads(str(existing[3]))
                if (
                    str(existing[2]) != "swarm.cancelled"
                    or saved_payload.get("reason") != clean_reason
                    or (
                        "expected_version" in saved_payload
                        and saved_payload.get("expected_version") != requested_version
                    )
                    or (
                        "expected_version" not in saved_payload
                        and requested_version is not None
                    )
                ):
                    con.execute("ROLLBACK")
                    return {
                        "success": False,
                        "error": "idempotency key was already used for a different swarm operation",
                        "idempotency_conflict": True,
                        "current_version": version,
                    }
                con.execute("COMMIT")
                lease_pending = not self._release_all_leases(swarm_id)
                result = {
                    "success": True,
                    "duplicate": True,
                    "swarm_id": swarm_id,
                    "state": str(saved_payload.get("state", SwarmState.FAILED.value)),
                    "version": int(saved_payload.get("version", version)),
                    "current_version": version,
                    "cancelled": True,
                }
                if lease_pending:
                    result["lease_release_pending"] = True
                return result
            if requested_version is not None and version != requested_version:
                con.execute("ROLLBACK")
                return {
                    "success": False,
                    "error": "version conflict",
                    "version_conflict": True,
                    "current_version": version,
                    "expected_version": requested_version,
                }
            if current_state in (SwarmState.COMPLETED.value, SwarmState.FAILED.value):
                con.execute("ROLLBACK")
                return {
                    "success": False,
                    "error": f"Swarm '{swarm_id}' already terminated ({current_state})",
                    "state": current_state,
                    "version": version,
                }

            now = time.time()
            new_version = version + 1
            event = AgentEvent.create(
                stream_id=f"swarm:{swarm_id}",
                kind="swarm.cancelled",
                payload={
                    "reason": clean_reason,
                    "expected_version": requested_version,
                    "from_state": current_state,
                    "state": SwarmState.FAILED.value,
                    "version": new_version,
                },
                idempotency_key=operation_key,
                actor="Coordinator",
            )
            history.append({
                "timestamp": now,
                "role": "Coordinator",
                "action": "cancel",
                "payload": {"reason": clean_reason},
                "resulting_state": SwarmState.FAILED.value,
                "event_id": event.event_id,
            })
            cur = con.execute(
                "UPDATE agent_swarms SET state = ?, history = ?, updated_at = ?, version = ? "
                "WHERE swarm_id = ? AND state = ? AND version = ?",
                (SwarmState.FAILED.value, json_dumps(history), now, new_version, swarm_id, current_state, version),
            )
            if cur.rowcount != 1:
                raise ConcurrentSwarmUpdateError(f"Swarm {swarm_id} changed during cancellation")
            self._append_event(con, event, published)
            con.execute("COMMIT")
        except Exception as exc:
            try:
                con.execute("ROLLBACK")
            except Exception:
                pass
            return {
                "success": False,
                "error": str(exc),
                "version": version if "version" in locals() else None,
            }
        finally:
            con.close()

        self._publish_after_commit(published)
        lease_pending = not self._release_all_leases(swarm_id)
        result = {
            "success": True,
            "swarm_id": swarm_id,
            "state": SwarmState.FAILED.value,
            "version": new_version,
            "cancelled": True,
        }
        if lease_pending:
            result["lease_release_pending"] = True
        return result

    def execute_dag(
        self,
        steps: list[dict[str, Any]],
        *,
        worktree_path: str | Path | None = None,
        max_workers: int = 4,
        command_broker: Any | None = None,
        command_timeout: int = 120,
        task_id: str | None = None,
        paths: list[str] | None = None,
        work_attempt_fence: Any | None = None,
        request_cancel_event: Any | None = None,
        overall_timeout: float | None = None,
    ) -> dict[str, Any]:
        """Execute a preflighted DAG; Python callbacks must cooperate with cancellation."""
        return execute_swarm_dag(
            steps,
            worktree_path=worktree_path,
            max_workers=max_workers,
            command_broker=command_broker,
            command_timeout=command_timeout,
            task_id=task_id,
            paths=paths,
            work_attempt_fence=work_attempt_fence,
            request_cancel_event=request_cancel_event,
            overall_timeout=overall_timeout,
        )

    run_dag = execute_dag


def execute_swarm_dag(
    steps: list[dict[str, Any]],
    *,
    worktree_path: str | Path | None = None,
    max_workers: int = 4,
    command_broker: Any | None = None,
    command_timeout: int = 120,
    task_id: str | None = None,
    paths: list[str] | None = None,
    work_attempt_fence: Any | None = None,
    request_cancel_event: Any | None = None,
    overall_timeout: float | None = None,
) -> dict[str, Any]:
    """Execute a fully validated DAG.

    Brokered commands share the optional overall deadline and have bounded
    process timeouts. In-process callbacks cannot be safely preempted or timed
    out and may overrun the deadline; callbacks must cooperate with cancellation.
    Failure never triggers global filesystem or Git rollback, so completed work
    remains available for inspection and recovery by its owner.
    """
    if not isinstance(steps, list) or not steps:
        return _dag_preflight_failure("steps must be a non-empty list")
    if len(steps) > 256:
        return _dag_preflight_failure("steps cannot exceed 256 entries")
    if not isinstance(max_workers, int) or isinstance(max_workers, bool) or not 1 <= max_workers <= 64:
        return _dag_preflight_failure("max_workers must be an integer from 1 through 64")
    started_at = time.monotonic()
    deadline = None
    if overall_timeout is not None:
        if (
            isinstance(overall_timeout, bool)
            or not isinstance(overall_timeout, (int, float))
            or not 0 < overall_timeout <= 3600
            or not math.isfinite(overall_timeout)
        ):
            return _dag_preflight_failure("overall_timeout must be greater than 0 and at most 3600 seconds")
        deadline = started_at + overall_timeout
    if request_cancel_event is not None and not callable(getattr(request_cancel_event, "is_set", None)):
        return _dag_preflight_failure("request_cancel_event must provide callable is_set")

    errors: list[str] = []
    step_map: dict[str, dict[str, Any]] = {}
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            errors.append(f"step at index {index} must be a dictionary")
            continue
        step_id = step.get("id")
        if not isinstance(step_id, str) or not step_id.strip():
            errors.append(f"step at index {index} must have a non-empty string id")
            continue
        if step_id in step_map:
            errors.append(f"duplicate step id: {step_id}")
            continue
        step_map[step_id] = step

    deps_by_id: dict[str, list[str]] = {}
    for step_id, step in step_map.items():
        deps = step.get("depends_on", [])
        if not isinstance(deps, list):
            errors.append(f"{step_id}: depends_on must be a list")
            deps = []
        if len(set(dep for dep in deps if isinstance(dep, str))) != len(deps):
            errors.append(f"{step_id}: depends_on contains duplicates or invalid values")
        for dep in deps:
            if not isinstance(dep, str) or dep not in step_map:
                errors.append(f"{step_id}: unknown dependency {dep!r}")
            elif dep == step_id:
                errors.append(f"{step_id}: self dependency is invalid")
        deps_by_id[step_id] = deps

        fn_present = "fn" in step
        command_present = "command" in step
        if fn_present == command_present:
            errors.append(f"{step_id}: provide exactly one callable fn or command")
        elif fn_present and not callable(step.get("fn")):
            errors.append(f"{step_id}: fn must be callable")
        elif command_present:
            command = step.get("command")
            if (
                not isinstance(command, list)
                or not command
                or not isinstance(command[0], str)
                or command[0] == ""
                or any(not isinstance(arg, str) or "\x00" in arg for arg in command)
            ):
                errors.append(f"{step_id}: command must be argv with a non-empty executable and NUL-free string arguments")
            if command_broker is None or not callable(getattr(command_broker, "run", None)):
                errors.append(f"{step_id}: command broker is required")
            if worktree_path is None:
                errors.append(f"{step_id}: worktree_path is required for commands")
            elif not isinstance(worktree_path, (str, Path)) or not Path(worktree_path).is_dir():
                errors.append(f"{step_id}: worktree_path must be an existing directory")
            if not isinstance(task_id, str) or not task_id.strip():
                errors.append(f"{step_id}: explicit task_id is required for commands")
            if (
                not isinstance(paths, list)
                or not paths
                or any(not isinstance(path, str) or not path.strip() for path in paths)
            ):
                errors.append(f"{step_id}: explicit non-empty write paths are required for commands")
            if work_attempt_fence is None:
                errors.append(f"{step_id}: explicit work_attempt_fence is required for commands")
            if request_cancel_event is None:
                errors.append(f"{step_id}: explicit request_cancel_event is required for commands")

    if not isinstance(command_timeout, int) or isinstance(command_timeout, bool) or not 1 <= command_timeout <= 600:
        errors.append("command_timeout must be an integer from 1 through 600 seconds")

    if not errors:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(step_id: str) -> None:
            if step_id in visiting:
                errors.append(f"dependency cycle includes {step_id}")
                return
            if step_id in visited:
                return
            visiting.add(step_id)
            for dep in deps_by_id[step_id]:
                visit(dep)
            visiting.remove(step_id)
            visited.add(step_id)

        for step_id in sorted(step_map):
            visit(step_id)

    if errors:
        return _dag_preflight_failure("; ".join(dict.fromkeys(errors)), step_map)

    completed_steps: set[str] = set()
    failed_steps: set[str] = set()
    step_results: dict[str, Any] = {}
    remaining_steps = set(step_map)

    aborted = False
    cancelled_steps: set[str] = set()
    timed_out_steps: set[str] = set()

    def _cancel_requested() -> bool:
        if request_cancel_event is None:
            return False
        try:
            return bool(request_cancel_event.is_set())
        except Exception:
            return True

    while remaining_steps and not aborted:
        if _cancel_requested():
            break
        if deadline is not None and time.monotonic() >= deadline:
            break
        ready = [
            sid for sid in sorted(remaining_steps)
            if all(dep in completed_steps for dep in deps_by_id[sid])
        ]
        if not ready:
            break

        def _run_single_step(step_id: str) -> tuple[str, bool, Any]:
            step_data = step_map[step_id]
            fn = step_data.get("fn")
            cmd = step_data.get("command")
            try:
                if _cancel_requested():
                    return step_id, False, {"success": False, "status": "cancelled", "cancelled": True}
                remaining_budget = None if deadline is None else deadline - time.monotonic()
                if remaining_budget is not None and remaining_budget < 1:
                    return step_id, False, {"success": False, "status": "timed_out", "timed_out": True}
                if callable(fn):
                    out = fn()
                    success = True
                    if isinstance(out, dict):
                        success = out.get("success", True) is True
                    elif isinstance(out, bool):
                        success = out
                    return step_id, success, out
                else:
                    from .commands import CommandInvocation

                    invocation = CommandInvocation(
                        argv=list(cmd), cwd=str(Path(worktree_path).resolve()), shell=False
                    )
                    step_timeout = command_timeout
                    if remaining_budget is not None:
                        step_timeout = min(command_timeout, math.floor(remaining_budget))
                    out = command_broker.run(
                        invocation,
                        cwd=str(Path(worktree_path).resolve()),
                        timeout=step_timeout,
                        task_id=task_id,
                        paths=paths,
                        _work_attempt_fence=work_attempt_fence,
                        request_cancel_event=request_cancel_event,
                    )
                    return step_id, bool(isinstance(out, dict) and out.get("success") is True), out
            except Exception as exc:
                return step_id, False, {"error": str(exc)}

        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(ready)))) as executor:
            future_to_step = {executor.submit(_run_single_step, sid): sid for sid in ready}
            for future in concurrent.futures.as_completed(future_to_step):
                sid, success, out = future.result()
                step_results[sid] = out
                remaining_steps.remove(sid)
                if isinstance(out, dict) and out.get("cancelled") is True:
                    cancelled_steps.add(sid)
                elif isinstance(out, dict) and out.get("timed_out") is True:
                    timed_out_steps.add(sid)
                elif success:
                    completed_steps.add(sid)
                else:
                    failed_steps.add(sid)
                    if step_map[sid].get("required", True):
                        aborted = True

    skipped_steps = []
    was_cancelled = bool(cancelled_steps) or _cancel_requested()
    deadline_exceeded = deadline is not None and time.monotonic() >= deadline
    for sid in sorted(remaining_steps):
        if was_cancelled:
            cancelled_steps.add(sid)
            step_results[sid] = {"success": False, "status": "cancelled", "cancelled": True}
        elif deadline_exceeded:
            timed_out_steps.add(sid)
            step_results[sid] = {"success": False, "status": "timed_out", "timed_out": True}
        else:
            skipped_steps.append(sid)
            step_results[sid] = {
                "success": False,
                "status": "skipped",
                "error": "aborted_after_required_failure" if aborted else "unmet_dependencies",
            }

    overall_success = not failed_steps and not skipped_steps and not cancelled_steps and not timed_out_steps and not deadline_exceeded
    return {
        "success": overall_success,
        "completed_steps": sorted(completed_steps),
        "failed_steps": sorted(failed_steps),
        "skipped_steps": skipped_steps,
        "cancelled_steps": sorted(cancelled_steps),
        "timed_out_steps": sorted(timed_out_steps),
        "cancelled": was_cancelled,
        "deadline_exceeded": deadline_exceeded,
        "step_results": {sid: step_results[sid] for sid in sorted(step_results)},
        "rolled_back": False,
        "rollback_status": "not_performed",
        "work_preserved": True,
    }


def _dag_preflight_failure(
    error: str, step_map: dict[str, dict[str, Any]] | None = None
) -> dict[str, Any]:
    ids = sorted(step_map or {})
    return {
        "success": False,
        "completed_steps": [],
        "failed_steps": [],
        "skipped_steps": ids,
        "step_results": {
            step_id: {"success": False, "status": "not_started", "error": "preflight_failed"}
            for step_id in ids
        },
        "error": error,
        "rolled_back": False,
        "rollback_status": "not_performed",
        "work_preserved": True,
    }
