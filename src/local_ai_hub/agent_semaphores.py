from __future__ import annotations

import json
import logging
import math
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .sqlite_support import connect_sqlite, initialize_wal, retry_busy, write_transaction

logger = logging.getLogger(__name__)


def _holder_is_active(holder: dict[str, Any], now: float) -> bool:
    expiry = holder.get("expires_at", 0)
    if expiry is None:
        return True
    if isinstance(expiry, bool) or not isinstance(expiry, (int, float)) or not math.isfinite(expiry):
        raise ValueError("invalid semaphore holder expiry")
    return expiry > now


class SemaphoreStore:
    """Capacity-bounded resource coordination semaphore store."""

    def __init__(self, db_path: Path | str, pubsub: Any | None = None) -> None:
        self.db_path = Path(db_path)
        self.pubsub = pubsub
        self._lock = threading.RLock()
        self._initialized = False

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        return connect_sqlite(self.db_path)

    def _ensure_schema(self) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return

            def init_db() -> None:
                con = self._connect()
                try:
                    initialize_wal(con)
                    with con:
                        con.execute("""
                        CREATE TABLE IF NOT EXISTS agent_semaphores (
                            name TEXT PRIMARY KEY,
                            capacity INTEGER NOT NULL DEFAULT 1,
                            holders_json TEXT NOT NULL DEFAULT '[]',
                            queue_json TEXT NOT NULL DEFAULT '[]',
                            created_at REAL NOT NULL,
                            updated_at REAL NOT NULL
                        );
                        """)
                finally:
                    con.close()

            retry_busy(init_db, retries=5, base_delay_seconds=0.02)
            self._initialized = True

    def acquire(
        self,
        name: str,
        owner: str = "agent",
        capacity: int = 1,
        ttl_seconds: float | None = None,
        purpose: str = "",
        timeout: float = 0.0,
    ) -> dict[str, Any]:
        self._ensure_schema()
        clean_name = str(name).strip().lower()
        if not clean_name:
            raise ValueError("semaphore name must be a non-empty string")
        cap = max(1, int(capacity))
        ttl = None if ttl_seconds is None else float(ttl_seconds)
        if ttl is not None:
            if not math.isfinite(ttl):
                raise ValueError("ttl_seconds must be finite")
            ttl = max(0.05, ttl)
        now = time.time()

        with self._lock:
            con = self._connect()
            try:
                with write_transaction(con, rollback_label="agent semaphore"):
                    row = con.execute(
                        "SELECT capacity, holders_json, queue_json FROM agent_semaphores WHERE name = ?",
                        (clean_name,),
                    ).fetchone()
                    if row is None:
                        holders: list[dict[str, Any]] = []
                        wait_queue: list[dict[str, Any]] = []
                        effective_capacity = cap
                    else:
                        effective_capacity = int(row[0])
                        holders = json.loads(row[1])
                        wait_queue = json.loads(row[2])

                    # Prune expired holders
                    active_holders = [h for h in holders if _holder_is_active(h, now)]

                    has_turn = not wait_queue or wait_queue[0].get("owner") == owner
                    if len(active_holders) < effective_capacity and has_turn:
                        wait_queue = [w for w in wait_queue if w.get("owner") != owner]
                        # Acquired
                        lease_id = f"sem_{uuid.uuid4().hex[:12]}"
                        new_holder = {
                            "lease_id": lease_id,
                            "owner": owner,
                            "purpose": purpose,
                            "acquired_at": now,
                            "expires_at": None if ttl is None else now + ttl,
                        }
                        active_holders.append(new_holder)
                        con.execute(
                            """
                            INSERT INTO agent_semaphores (name, capacity, holders_json, queue_json, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?)
                            ON CONFLICT(name) DO UPDATE SET
                                capacity = excluded.capacity,
                                holders_json = excluded.holders_json,
                                queue_json = excluded.queue_json,
                                updated_at = excluded.updated_at
                            """,
                            (
                                clean_name,
                                effective_capacity,
                                json.dumps(active_holders, separators=(",", ":")),
                                json.dumps(wait_queue, separators=(",", ":")),
                                now,
                                now,
                            ),
                        )
                        return {
                            "success": True,
                            "acquired": True,
                            "name": clean_name,
                            "lease_id": lease_id,
                            "owner": owner,
                            "expires_at": None if ttl is None else now + ttl,
                            "capacity": effective_capacity,
                            "held_count": len(active_holders),
                            "available_slots": max(0, effective_capacity - len(active_holders)),
                            "position": 0,
                        }
                    else:
                        # Queue only callers that can wait; immediate failures leave no stale entry.
                        is_queued = any(w.get("owner") == owner for w in wait_queue)
                        if timeout > 0 and self.pubsub is not None and not is_queued:
                            wait_entry = {
                                "wait_id": f"wait_{uuid.uuid4().hex[:8]}",
                                "owner": owner,
                                "purpose": purpose,
                                "requested_at": now,
                            }
                            wait_queue.append(wait_entry)
                        pos = next(
                            (i + 1 for i, w in enumerate(wait_queue) if w.get("owner") == owner),
                            len(wait_queue) + 1,
                        )
                        con.execute(
                            """
                            INSERT INTO agent_semaphores (name, capacity, holders_json, queue_json, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?)
                            ON CONFLICT(name) DO UPDATE SET
                                holders_json = excluded.holders_json,
                                queue_json = excluded.queue_json,
                                updated_at = excluded.updated_at
                            """,
                            (
                                clean_name,
                                effective_capacity,
                                json.dumps(active_holders, separators=(",", ":")),
                                json.dumps(wait_queue, separators=(",", ":")),
                                now,
                                now,
                            ),
                        )
            finally:
                con.close()

        # If not acquired and timeout > 0, wait on pubsub event
        if timeout > 0 and self.pubsub is not None:
            wait_topic = f"semaphore.{clean_name}.released"
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                rem = deadline - time.monotonic()
                if rem <= 0:
                    break
                next_expiry = min(
                    (float(holder["expires_at"]) for holder in active_holders if holder.get("expires_at") is not None),
                    default=None,
                )
                wait_timeout = rem
                if next_expiry is not None:
                    wait_timeout = min(wait_timeout, max(0.0, next_expiry - time.time()))
                wait_res = (
                    self.pubsub.wait_for_event(wait_topic, timeout=wait_timeout)
                    if wait_timeout > 0
                    else {"success": False, "timeout": True}
                )
                expiry_reached = next_expiry is not None and time.time() >= next_expiry
                if (wait_res.get("success") and not wait_res.get("timeout")) or expiry_reached:
                    retry_res = self.acquire(clean_name, owner=owner, capacity=cap, ttl_seconds=ttl, purpose=purpose, timeout=0.0)
                    if retry_res.get("acquired"):
                        return retry_res
                    active_holders = retry_res.get("active_holders", active_holders)

            # A timed-out waiter cancels its queue entry.
            with self._lock:
                con = self._connect()
                try:
                    with con:
                        row = con.execute(
                            "SELECT queue_json FROM agent_semaphores WHERE name = ?",
                            (clean_name,),
                        ).fetchone()
                        if row is not None:
                            wait_queue = json.loads(row[0])
                            remaining_queue = [w for w in wait_queue if w.get("owner") != owner]
                            if len(remaining_queue) != len(wait_queue):
                                con.execute(
                                    "UPDATE agent_semaphores SET queue_json = ?, updated_at = ? WHERE name = ?",
                                    (
                                        json.dumps(remaining_queue, separators=(",", ":")),
                                        time.time(),
                                        clean_name,
                                    ),
                                )
                finally:
                    con.close()

        return {
            "success": True,
            "acquired": False,
            "name": clean_name,
            "capacity": effective_capacity,
            "held_count": len(active_holders),
            "position": pos,
            "queue_position": pos,
            "reason": "capacity_reached",
            "waiting": False,
            "active_holders": [{"lease_id": h["lease_id"], "owner": h["owner"], "expires_at": h["expires_at"]} for h in active_holders],
        }

    def release(self, name: str, lease_id: str, owner: str = "") -> dict[str, Any]:
        self._ensure_schema()
        clean_name = str(name).strip().lower()
        now = time.time()
        released = False

        with self._lock:
            con = self._connect()
            try:
                with con:
                    row = con.execute(
                        "SELECT capacity, holders_json, queue_json FROM agent_semaphores WHERE name = ?",
                        (clean_name,),
                    ).fetchone()
                    if row is None:
                        return {"success": False, "error": f"semaphore '{clean_name}' not found", "released": False}
                    int(row[0])  # Validate stored capacity even on the release path.
                    holders = json.loads(row[1])
                    wait_queue = json.loads(row[2])

                    remaining_holders = []
                    for h in holders:
                        if h.get("lease_id") == lease_id:
                            if not owner or not h.get("owner") or h.get("owner") != owner:
                                remaining_holders.append(h)
                            else:
                                released = True
                        else:
                            remaining_holders.append(h)

                    if owner:
                        wait_queue = [w for w in wait_queue if w.get("owner") != owner]

                    con.execute(
                        "UPDATE agent_semaphores SET holders_json = ?, queue_json = ?, updated_at = ? WHERE name = ?",
                        (json.dumps(remaining_holders, separators=(",", ":")), json.dumps(wait_queue, separators=(",", ":")), now, clean_name),
                    )
            finally:
                con.close()

        if released and self.pubsub is not None:
            try:
                self.pubsub.publish(
                    f"semaphore.{clean_name}.released",
                    {"name": clean_name, "released_lease_id": lease_id, "freed_at": now},
                    sender="semaphore",
                )
            except Exception as exc:
                logger.warning("failed to publish semaphore release event: %s", exc)

        return {"success": True, "released": released, "name": clean_name, "lease_id": lease_id}

    def status(self, name: str | None = None) -> dict[str, Any]:
        self._ensure_schema()
        now = time.time()
        with self._lock:
            con = self._connect()
            try:
                if name:
                    clean_name = str(name).strip().lower()
                    row = con.execute(
                        "SELECT capacity, holders_json, queue_json, updated_at FROM agent_semaphores WHERE name = ?",
                        (clean_name,),
                    ).fetchone()
                    if row is None:
                        return {"success": True, "semaphore": None, "semaphores": {}, "found": False}
                    holders = [h for h in json.loads(row[1]) if _holder_is_active(h, now)]
                    queue = json.loads(row[2])
                    sem_data = {
                        "name": clean_name,
                        "capacity": int(row[0]),
                        "active_count": len(holders),
                        "holders_count": len(holders),
                        "active_holders": holders,
                        "holders": holders,
                        "queue": queue,
                        "queue_length": len(queue),
                        "updated_at": float(row[3]),
                    }
                    return {
                        "success": True,
                        "found": True,
                        "semaphore": sem_data,
                        "semaphores": {clean_name: sem_data},
                    }
                else:
                    rows = con.execute("SELECT name, capacity, holders_json, queue_json, updated_at FROM agent_semaphores").fetchall()
                    semaphores = {}
                    for r in rows:
                        s_name = r[0]
                        holders = [h for h in json.loads(r[2]) if _holder_is_active(h, now)]
                        queue = json.loads(r[3])
                        semaphores[s_name] = {
                            "name": s_name,
                            "capacity": int(r[1]),
                            "active_count": len(holders),
                            "holders_count": len(holders),
                            "active_holders": holders,
                            "holders": holders,
                            "queue_length": len(queue),
                            "updated_at": float(r[4]),
                        }
                    return {"success": True, "semaphores": semaphores}
            finally:
                con.close()
