from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from .agent_blackboard import BlackboardStore
from .agent_verification import VerificationStore
from .leases import ScopeLeaseStore
from .sqlite_support import connect_sqlite, initialize_wal


class SwarmState(str, Enum):
    PENDING = "PENDING"
    CODING = "CODING"
    TESTING = "TESTING"
    REVIEWING = "REVIEWING"
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
    ) -> None:
        self.db_path = Path(db_path)
        self.leases = leases
        self.blackboard = blackboard
        self.verifications = verifications
        self._init_db()

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
        with closing(self._connect()) as con, con:
            con.execute(
                """
                INSERT INTO agent_swarms (
                    swarm_id, goal, target_paths, test_command, author, state, receipt_id, history, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    swarm_id,
                    goal,
                    json.dumps(paths),
                    test_command,
                    author,
                    state,
                    None,
                    json.dumps(initial_history),
                    now,
                    now,
                ),
            )

        return {
            "success": True,
            "swarm_id": swarm_id,
            "state": state,
            "goal": goal,
            "target_paths": paths,
        }

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

    def step(
        self,
        swarm_id: str,
        role: str,
        action: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        info = self.get_status(swarm_id)
        if not info.get("success"):
            return info

        current_state = info["state"]
        paths = info["target_paths"]
        goal = info["goal"]
        history = info["history"]
        now = time.time()
        pay = payload or {}

        if current_state in (SwarmState.COMPLETED.value, SwarmState.FAILED.value):
            return {
                "success": False,
                "error": f"Swarm '{swarm_id}' already terminated with state '{current_state}'",
            }

        new_state = current_state
        receipt_id: str | None = None

        if current_state == SwarmState.CODING.value:
            if role != "Coder":
                return {"success": False, "error": f"Expected Coder role in CODING state, got '{role}'"}
            if self.blackboard:
                self.blackboard.update(
                    board_id=f"swarm:{swarm_id}",
                    section="code",
                    content=pay,
                    author=role,
                )
            new_state = SwarmState.TESTING.value

        elif current_state == SwarmState.TESTING.value:
            if role != "Tester":
                return {"success": False, "error": f"Expected Tester role in TESTING state, got '{role}'"}
            if self.blackboard:
                self.blackboard.update(
                    board_id=f"swarm:{swarm_id}",
                    section="test",
                    content=pay,
                    author=role,
                )
            if pay.get("passed", False):
                new_state = SwarmState.REVIEWING.value
            else:
                new_state = SwarmState.FAILED.value
                self._release_all_leases(swarm_id)

        elif current_state == SwarmState.REVIEWING.value:
            if role != "Reviewer":
                return {"success": False, "error": f"Expected Reviewer role in REVIEWING state, got '{role}'"}
            if self.blackboard:
                self.blackboard.update(
                    board_id=f"swarm:{swarm_id}",
                    section="review",
                    content=pay,
                    author=role,
                )
            if action == "approve":
                new_state = SwarmState.COMPLETED.value
                if self.verifications:
                    try:
                        from .agent_verification import VerificationReceipt
                        rcpt = VerificationReceipt.create(
                            task_id=swarm_id,
                            criterion=f"Swarm completed goal: {goal}",
                            command_id=info["test_command"][:100],
                            passed=True,
                            details={"review": pay, "target_paths": paths},
                        )
                        self.verifications.record(rcpt)
                        receipt_id = rcpt.receipt_id
                    except Exception:
                        receipt_id = f"receipt_{uuid4().hex[:12]}"
                else:
                    receipt_id = f"receipt_{uuid4().hex[:12]}"
                self._release_all_leases(swarm_id)
            else:
                new_state = SwarmState.FAILED.value
                self._release_all_leases(swarm_id)

        history.append({
            "timestamp": now,
            "role": role,
            "action": action,
            "payload": pay,
            "resulting_state": new_state,
        })

        with closing(self._connect()) as con, con:
            con.execute(
                """
                UPDATE agent_swarms
                SET state = ?, receipt_id = COALESCE(?, receipt_id), history = ?, updated_at = ?
                WHERE swarm_id = ?
                """,
                (new_state, receipt_id, json.dumps(history), now, swarm_id),
            )

        res: dict[str, Any] = {
            "success": True,
            "swarm_id": swarm_id,
            "state": new_state,
            "role": role,
            "action": action,
        }
        if receipt_id:
            res["receipt_id"] = receipt_id
        return res

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
                (SwarmState.FAILED.value, json.dumps(history), now, swarm_id),
            )
        return {"success": True, "swarm_id": swarm_id, "state": SwarmState.FAILED.value, "cancelled": True}
