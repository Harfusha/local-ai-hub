from __future__ import annotations

from .json_utils import dumps as json_dumps

import hashlib
import json
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
                self.leases.release(tenant=tenant)

    @_serialized_event_writer
    def dispatch(
        self,
        goal: str,
        target_paths: list[str] | None = None,
        test_command: str = "",
        author: str = "agent",
        root: str = ".",
    ) -> dict[str, Any]:
        paths = list(target_paths or [])
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

    def get_status(self, swarm_id: str) -> dict[str, Any]:
        with closing(self._connect()) as con:
            row = con.execute(
                """
                SELECT swarm_id, goal, target_paths, test_command, author, root, state,
                       receipt_id, history, created_at, updated_at, version
                FROM agent_swarms WHERE swarm_id = ?
                """,
                (swarm_id,),
            ).fetchone()
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
            result = self.leases.release(tenant=f"swarm:{swarm_id}")
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
    ) -> dict[str, Any]:
        return self._step_transaction(
            swarm_id,
            role,
            action,
            payload or {},
            expected_version=expected_version,
            idempotency_key=idempotency_key,
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
                SELECT swarm_id, goal, target_paths, test_command, state, receipt_id,
                       history, updated_at, version
                FROM agent_swarms WHERE swarm_id = ?
                """,
                (swarm_id,),
            ).fetchone()
            if not row:
                con.execute("ROLLBACK")
                return {"success": False, "error": f"Swarm '{swarm_id}' not found"}
            current_state = str(row[4])
            current_version = int(row[8])
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
            old_receipt_id = row[5]
            history = json.loads(row[6])
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

    def list_swarms(self, state: str | None = None, limit: int = 50) -> dict[str, Any]:
        with closing(self._connect()) as con:
            sql = "SELECT swarm_id, goal, target_paths, test_command, author, state, receipt_id, created_at, updated_at FROM agent_swarms"
            params: list[Any] = []
            if state:
                sql += " WHERE state = ?"
                params.append(state)
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
    ) -> dict[str, Any]:
        con = self._connect()
        published: list[AgentEvent] = []
        try:
            con.isolation_level = None
            con.execute("BEGIN IMMEDIATE")
            row = con.execute(
                "SELECT state, history, version FROM agent_swarms WHERE swarm_id = ?",
                (swarm_id,),
            ).fetchone()
            if not row:
                con.execute("ROLLBACK")
                return {"success": False, "error": f"Swarm '{swarm_id}' not found"}
            current_state = str(row[0])
            history = json.loads(row[1])
            version = int(row[2])
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
