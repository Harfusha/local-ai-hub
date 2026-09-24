from __future__ import annotations

from .json_utils import dumps as json_dumps

import json
import sqlite3
import time
from contextlib import closing
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from .agent_blackboard import BlackboardStore
from .agent_events import AgentEvent, AgentStateStore
from .agent_verification import VerificationStore
from .leases import ScopeLeaseStore
from .sqlite_support import connect_sqlite, initialize_wal


class SwarmState(str, Enum):
    PENDING = "PENDING"
    CODING = "CODING"
    TESTING = "TESTING"
    REVIEWING = "REVIEWING"
    COMPLETING = "COMPLETING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


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
        self.state_store = state_store or (verifications.state_store if verifications else None)
        self._init_db()
        if self.state_store is not None:
            self.state_store._ensure_schema()
        if self.blackboard is not None:
            self.blackboard._ensure_schema()
        if self.verifications is not None:
            self.verifications._init_tables()
        self._reconcile_pending_outbox()

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self.db_path, timeout_seconds=5.0)

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as con, con:
            initialize_wal(con)
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_swarms (
                    swarm_id TEXT PRIMARY KEY,
                    goal TEXT NOT NULL,
                    target_paths TEXT NOT NULL,
                    test_command TEXT NOT NULL,
                    author TEXT NOT NULL,
                    state TEXT NOT NULL,
                    receipt_id TEXT,
                    history TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_swarm_outbox (
                    operation_id TEXT PRIMARY KEY,
                    swarm_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    last_error TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )

    def _shares_database(self, path: Path | str | None) -> bool:
        return bool(path is not None and Path(path).resolve() == self.db_path.resolve())

    def _append_outbox(
        self,
        con: sqlite3.Connection,
        operation_id: str,
        swarm_id: str,
        payload: dict[str, Any],
        now: float,
    ) -> None:
        if payload:
            con.execute(
                """
                INSERT INTO agent_swarm_outbox(
                    operation_id, swarm_id, payload_json, status, last_error, created_at, updated_at
                ) VALUES (?, ?, ?, 'pending', '', ?, ?)
                """,
                (operation_id, swarm_id, json_dumps(payload), now, now),
            )

    def _reconcile_pending_outbox(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as con:
            rows = con.execute(
                "SELECT operation_id, payload_json FROM agent_swarm_outbox "
                "WHERE status = 'pending' ORDER BY created_at, operation_id"
            ).fetchall()
        failures: list[dict[str, Any]] = []
        for operation_id, raw_payload in rows:
            try:
                payload = json.loads(str(raw_payload))
                event_data = payload.get("event")
                if event_data and self.state_store is not None:
                    result = self.state_store.append(AgentEvent.from_dict(event_data))
                    if result.error or result.retryable or result.event is None:
                        raise RuntimeError(result.error or "swarm event reconciliation failed")
                receipt_data = payload.get("receipt")
                if receipt_data and self.verifications is not None:
                    from .agent_verification import VerificationReceipt

                    self.verifications.record(VerificationReceipt(**receipt_data))
                board_data = payload.get("blackboard")
                if board_data and self.blackboard is not None:
                    result = self.blackboard.update(**board_data)
                    if not result.get("success"):
                        raise RuntimeError(result.get("error", "blackboard reconciliation failed"))
                finalize = payload.get("finalize")
                if finalize:
                    self._finalize_external_receipt(
                        str(finalize["swarm_id"]),
                        str(finalize["receipt_id"]),
                        AgentEvent.from_dict(finalize["event"]),
                    )
                with closing(self._connect()) as con, con:
                    con.execute(
                        "UPDATE agent_swarm_outbox SET status = 'complete', last_error = '', updated_at = ? "
                        "WHERE operation_id = ? AND status = 'pending'",
                        (time.time(), operation_id),
                    )
            except Exception as exc:
                error = str(exc)
                failures.append({"operation_id": operation_id, "error": error})
                with closing(self._connect()) as con, con:
                    con.execute(
                        "UPDATE agent_swarm_outbox SET last_error = ?, updated_at = ? "
                        "WHERE operation_id = ? AND status = 'pending'",
                        (error[:1000], time.time(), operation_id),
                    )
        return failures

    def _finalize_external_receipt(
        self, swarm_id: str, receipt_id: str, event: AgentEvent
    ) -> None:
        append_in_transaction = bool(
            self.state_store is not None
            and self.state_store.enabled
            and self._shares_database(self.state_store.db_path)
        )
        published_event: AgentEvent | None = None
        with closing(self._connect()) as con:
            con.execute("BEGIN IMMEDIATE")
            try:
                row = con.execute(
                    "SELECT state, receipt_id, history FROM agent_swarms WHERE swarm_id = ?",
                    (swarm_id,),
                ).fetchone()
                if row is None:
                    raise RuntimeError(f"swarm '{swarm_id}' disappeared during receipt reconciliation")
                state, current_receipt_id, raw_history = str(row[0]), row[1], str(row[2])
                if state == SwarmState.COMPLETING.value:
                    history = json.loads(raw_history)
                    step_id = str(event.payload.get("step_id") or "")
                    for entry in reversed(history):
                        if entry.get("step_id") == step_id:
                            entry["resulting_state"] = SwarmState.COMPLETED.value
                            break
                    cur = con.execute(
                        "UPDATE agent_swarms SET state = ?, receipt_id = ?, history = ?, updated_at = ? "
                        "WHERE swarm_id = ? AND state = ?",
                        (
                            SwarmState.COMPLETED.value,
                            receipt_id,
                            json_dumps(history),
                            time.time(),
                            swarm_id,
                            SwarmState.COMPLETING.value,
                        ),
                    )
                    if cur.rowcount != 1:
                        raise RuntimeError("swarm completion compare-and-set failed")
                    if append_in_transaction:
                        result = self.state_store._append_event_in_transaction(con, event)
                        if result.error or result.event is None:
                            raise RuntimeError(result.error or "swarm completion event could not be stored")
                        if not result.duplicate:
                            published_event = result.event
                elif state != SwarmState.COMPLETED.value or current_receipt_id != receipt_id:
                    raise RuntimeError("swarm completion state conflicts with verification receipt")
                con.execute("COMMIT")
            except Exception:
                try:
                    con.execute("ROLLBACK")
                except Exception:
                    pass
                raise
        if self.state_store is not None and not append_in_transaction:
            result = self.state_store.append(event)
            if result.error or result.retryable or result.event is None:
                raise RuntimeError(result.error or "swarm completion event could not be stored")
        elif published_event is not None and self.state_store is not None:
            self.state_store._publish(published_event)

    def dispatch(
        self,
        goal: str,
        target_paths: list[str] | None = None,
        test_command: str = "",
        author: str = "agent",
        root: str = ".",
    ) -> dict[str, Any]:
        paths = target_paths or []
        swarm_id = f"swarm_{uuid4().hex[:12]}"
        now = time.time()

        if self.leases and paths:
            claim_res = self.leases.claim(
                tenant=f"swarm:{swarm_id}",
                root=root,
                paths=paths,
                ttl_seconds=3600,
                purpose=f"Swarm: {goal[:100]}",
            )
            if not claim_res.get("success", False):
                return {
                    "success": False,
                    "error": f"Failed to acquire lease: {claim_res.get('error', 'already held')}",
                }

        initial_history = [
            {
                "timestamp": now,
                "role": "Coordinator",
                "action": "dispatch",
                "payload": {"goal": goal, "target_paths": paths, "test_command": test_command},
            }
        ]

        state = SwarmState.CODING.value
        event = AgentEvent.create(
            stream_id=f"swarm:{swarm_id}",
            kind="swarm.created",
            payload={"goal": goal, "target_paths": paths, "test_command": test_command},
            idempotency_key=f"swarm_created_{swarm_id}",
            actor=author,
        )
        outbox: dict[str, Any] = {}
        persisted_event: AgentEvent | None = None
        with closing(self._connect()) as con:
            con.execute("BEGIN IMMEDIATE")
            con.execute(
                """
                INSERT INTO agent_swarms (
                    swarm_id, goal, target_paths, test_command, author, state, receipt_id, history, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    swarm_id,
                    goal,
                    json_dumps(paths),
                    test_command,
                    author,
                    state,
                    None,
                    json_dumps(initial_history),
                    now,
                    now,
                ),
            )
            if self.state_store is not None:
                if self._shares_database(self.state_store.db_path) and self.state_store.enabled:
                    result = self.state_store._append_event_in_transaction(con, event)
                    if result.error or result.event is None:
                        raise RuntimeError(result.error or "swarm creation event could not be stored")
                    if not result.duplicate:
                        persisted_event = result.event
                else:
                    outbox["event"] = event.to_dict()
            self._append_outbox(con, swarm_id, swarm_id, outbox, now)
            con.execute("COMMIT")

        if persisted_event is not None and self.state_store is not None:
            self.state_store._publish(persisted_event)
        reconciliation = self._reconcile_pending_outbox()

        result: dict[str, Any] = {
            "success": True,
            "swarm_id": swarm_id,
            "state": state,
            "goal": goal,
            "target_paths": paths,
        }
        related_failures = [item for item in reconciliation if item.get("operation_id") == swarm_id]
        if related_failures:
            result["reconciliation_required"] = True
            result["error"] = related_failures[0]["error"]
        return result

    def get_status(self, swarm_id: str) -> dict[str, Any]:
        with closing(self._connect()) as con:
            row = con.execute(
                """
                SELECT swarm_id, goal, target_paths, test_command, author, state, receipt_id, history, created_at, updated_at
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
            "state": row[5],
            "receipt_id": row[6],
            "history": json.loads(row[7]),
            "created_at": row[8],
            "updated_at": row[9],
        }

    def _release_all_leases(self, swarm_id: str) -> None:
        if self.leases:
            try:
                self.leases.release(tenant=f"swarm:{swarm_id}")
            except Exception:
                pass

    def step(self, swarm_id: str, role: str, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        info = self.get_status(swarm_id)
        if not info.get("success"):
            return info
        current_state = info["state"]
        if current_state == SwarmState.COMPLETING.value:
            return {"success": False, "swarm_id": swarm_id, "state": current_state,
                    "reconciliation_required": True, "error": "swarm completion receipt reconciliation is pending"}
        if current_state in (SwarmState.COMPLETED.value, SwarmState.FAILED.value):
            return {"success": False, "error": f"Swarm '{swarm_id}' already terminated with state '{current_state}'"}

        paths, goal, history = info["target_paths"], info["goal"], info["history"]
        now, pay = time.time(), payload or {}
        new_state, receipt, receipt_id = current_state, None, None
        pending_blackboard = None
        release_leases = False
        if current_state == SwarmState.CODING.value:
            if role != "Coder":
                return {"success": False, "error": f"Expected Coder role in CODING state, got '{role}'"}
            if self.blackboard:
                pending_blackboard = ("code", pay)
            new_state = SwarmState.TESTING.value
        elif current_state == SwarmState.TESTING.value:
            if role != "Tester":
                return {"success": False, "error": f"Expected Tester role in TESTING state, got '{role}'"}
            if self.blackboard:
                pending_blackboard = ("test", pay)
            if pay.get("passed", False):
                if not str(pay.get("evidence_id") or "").strip():
                    return {"success": False, "swarm_id": swarm_id, "state": current_state,
                            "error": "passed test result requires evidence_id"}
                new_state = SwarmState.REVIEWING.value
            else:
                new_state, release_leases = SwarmState.FAILED.value, True
        elif current_state == SwarmState.REVIEWING.value:
            if role != "Reviewer":
                return {"success": False, "error": f"Expected Reviewer role in REVIEWING state, got '{role}'"}
            if action == "approve":
                if not self.verifications or not self.verifications.state_store.enabled:
                    return {"success": False, "swarm_id": swarm_id, "state": current_state,
                            "error": "verification storage is unavailable; swarm cannot complete"}
                tester = next((entry for entry in reversed(history) if entry.get("role") == "Tester"), None)
                test_payload = tester.get("payload", {}) if isinstance(tester, dict) else {}
                evidence_id = str(test_payload.get("evidence_id") or "").strip()
                if test_payload.get("passed") is not True or not evidence_id:
                    return {"success": False, "swarm_id": swarm_id, "state": current_state,
                            "error": "passing test evidence is unavailable; swarm cannot complete"}
                from .agent_verification import VerificationReceipt
                receipt = VerificationReceipt.create(
                    task_id=swarm_id, criterion=f"Swarm completed goal: {goal}",
                    command_id=info["test_command"][:100], passed=True, evidence_id=evidence_id,
                    details={"review": pay, "target_paths": paths},
                )
                receipt_id = receipt.receipt_id
                verify_same = self._shares_database(self.verifications.state_store.db_path)
                new_state = SwarmState.COMPLETED.value if verify_same else SwarmState.COMPLETING.value
                release_leases = verify_same
            else:
                new_state, release_leases = SwarmState.FAILED.value, True
            if self.blackboard:
                pending_blackboard = ("review", pay)
        else:
            return {"success": False, "swarm_id": swarm_id, "state": current_state, "error": "unknown swarm state"}

        step_id = uuid4().hex
        history.append({"timestamp": now, "role": role, "action": action, "payload": pay,
                        "step_id": step_id, "resulting_state": new_state})
        state_event = AgentEvent.create(
            stream_id=f"swarm:{swarm_id}", kind="swarm.step",
            payload={"step_id": step_id, "role": role, "action": action, "from_state": current_state,
                     "to_state": new_state, "payload": pay},
            idempotency_key=f"swarm_step_{step_id}", actor=role,
        )
        state_same = bool(self.state_store and self.state_store.enabled and
                           self._shares_database(self.state_store.db_path))
        verify_same = bool(receipt and self.verifications and self.verifications.state_store.enabled and
                           self._shares_database(self.verifications.state_store.db_path))
        board_same = bool(pending_blackboard and self.blackboard and
                          self._shares_database(self.blackboard.db_path))
        external: dict[str, Any] = {}
        if self.state_store and not state_same:
            external["event"] = state_event.to_dict()
        if receipt and not verify_same:
            completed_event = AgentEvent.create(
                stream_id=f"swarm:{swarm_id}", kind="swarm.completed",
                payload={"step_id": step_id, "receipt_id": receipt.receipt_id},
                idempotency_key=f"swarm_completed_{step_id}", actor="verifier",
            )
            external["receipt"] = receipt.to_dict()
            external["finalize"] = {"swarm_id": swarm_id, "receipt_id": receipt.receipt_id,
                                    "event": completed_event.to_dict()}
        if pending_blackboard and not board_same:
            section, content = pending_blackboard
            external["blackboard"] = {"board_id": f"swarm:{swarm_id}", "section": section,
                                      "content": content, "author": role, "operation_id": step_id}

        published: list[AgentEvent] = []
        try:
            with closing(self._connect()) as con:
                con.execute("BEGIN IMMEDIATE")
                cur = con.execute(
                    "UPDATE agent_swarms SET state=?, receipt_id=COALESCE(?, receipt_id), history=?, updated_at=? "
                    "WHERE swarm_id=? AND state=? AND updated_at=?",
                    (new_state, receipt_id if verify_same else None, json_dumps(history), now,
                     swarm_id, current_state, info["updated_at"]),
                )
                if cur.rowcount != 1:
                    con.execute("ROLLBACK")
                    return {"success": False, "swarm_id": swarm_id, "state": current_state,
                            "version_conflict": True, "error": "swarm changed during step; reload and retry"}
                if state_same:
                    appended = self.state_store._append_event_in_transaction(con, state_event)
                    if appended.error or appended.event is None:
                        raise RuntimeError(appended.error or "swarm event could not be stored")
                    if not appended.duplicate:
                        published.append(appended.event)
                if verify_same and receipt:
                    task_store = self.verifications.task_store
                    update_task = bool(task_store and
                        task_store.state_store.db_path.resolve() == self.verifications.state_store.db_path.resolve())
                    published.extend(self.verifications.record_in_transaction(con, receipt, update_task=update_task))
                if board_same and pending_blackboard:
                    section, content = pending_blackboard
                    board_result = self.blackboard._update_in_transaction(
                        con, board_id=f"swarm:{swarm_id}", section=section, content=content,
                        author=role, operation_id=step_id,
                    )
                    if not board_result.get("success"):
                        con.execute("ROLLBACK")
                        return {"success": False, "swarm_id": swarm_id, "state": current_state,
                                "version_conflict": bool(board_result.get("version_conflict")),
                                "error": board_result.get("error", "blackboard compare-and-set failed")}
                self._append_outbox(con, step_id, swarm_id, external, now)
                con.execute("COMMIT")
        except Exception as exc:
            return {"success": False, "swarm_id": swarm_id, "state": current_state,
                    "error": f"swarm step transaction failed: {exc}"}

        if self.state_store:
            for event in published:
                self.state_store._publish(event)
        failures = [row for row in self._reconcile_pending_outbox()
                    if row.get("operation_id") == step_id]
        external_verification = bool(receipt and not verify_same)
        final_state = SwarmState.COMPLETING.value if external_verification else new_state
        if external_verification and not failures:
            final_state = SwarmState.COMPLETED.value
        if (release_leases and final_state == SwarmState.FAILED.value) or final_state == SwarmState.COMPLETED.value:
            self._release_all_leases(swarm_id)
        if failures:
            result = {"success": False, "swarm_id": swarm_id, "state": final_state,
                      "reconciliation_required": True, "error": failures[0]["error"]}
            if receipt_id and verify_same:
                result["receipt_id"] = receipt_id
            return result
        result = {"success": True, "swarm_id": swarm_id, "state": final_state, "role": role, "action": action}
        if receipt_id:
            result["receipt_id"] = receipt_id
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

    def cancel(self, swarm_id: str, reason: str = "") -> dict[str, Any]:
        info = self.get_status(swarm_id)
        if not info.get("success"):
            return info
        current_state = info["state"]
        if current_state in (SwarmState.COMPLETED.value, SwarmState.FAILED.value):
            return {"success": False, "error": f"Swarm '{swarm_id}' already terminated ({current_state})"}

        now = time.time()
        history = info["history"]
        history.append({
            "timestamp": now,
            "role": "Coordinator",
            "action": "cancel",
            "payload": {"reason": reason or "cancelled by agent"},
            "resulting_state": SwarmState.FAILED.value,
        })
        self._release_all_leases(swarm_id)
        with closing(self._connect()) as con, con:
            con.execute(
                """
                UPDATE agent_swarms
                SET state = ?, history = ?, updated_at = ?
                WHERE swarm_id = ?
                """,
                (SwarmState.FAILED.value, json_dumps(history), now, swarm_id),
            )
        return {"success": True, "swarm_id": swarm_id, "state": SwarmState.FAILED.value, "cancelled": True}
