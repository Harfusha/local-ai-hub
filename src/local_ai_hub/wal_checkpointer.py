"""SQLite Zero-Lock WAL Checkpointer Daemon.

Prevents unbounded growth of SQLite Write-Ahead Log (-wal) files on Windows under heavy
concurrent agent writes, avoiding disk bloat and read latency degradation.

Features:
1. Size-threshold detection (triggers checkpoint when WAL exceeds max_wal_bytes).
2. Non-blocking PRAGMA wal_checkpoint(PASSIVE) execution without reader/writer lockouts.
3. Clean Windows file handle management with connection closing and timeout protection.
4. Optional background thread execution with cooperative cancellation.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
# import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CheckpointReport:
    """Outcome of WAL checkpoint on a single database."""

    db_path: str
    wal_size_before: int
    wal_size_after: int
    busy: bool
    log_pages: int
    checkpointed_pages: int
    status: str


class SQLiteWALCheckpointer:
    """Manages active WAL checkpointing across database stores."""

    def __init__(
        self,
        target_dir: str | Path,
        max_wal_bytes: int = 4 * 1024 * 1024,  # 4 MB
        checkpoint_mode: str = "PASSIVE",
    ):
        self.target_dir = Path(target_dir).resolve()
        self.max_wal_bytes = max_wal_bytes
        self.checkpoint_mode = checkpoint_mode.upper()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def checkpoint_database(self, db_path: str | Path) -> CheckpointReport:
        """Run checkpoint on a single database if its WAL file exceeds threshold."""
        p = Path(db_path).resolve()
        wal_p = Path(str(p) + "-wal")

        if not p.is_file():
            return CheckpointReport(
                db_path=str(p),
                wal_size_before=0,
                wal_size_after=0,
                busy=False,
                log_pages=0,
                checkpointed_pages=0,
                status="db_not_found",
            )

        wal_before = wal_p.stat().st_size if wal_p.is_file() else 0
        if wal_before < self.max_wal_bytes:
            return CheckpointReport(
                db_path=str(p),
                wal_size_before=wal_before,
                wal_size_after=wal_before,
                busy=False,
                log_pages=0,
                checkpointed_pages=0,
                status="skipped_threshold",
            )

        try:
            con = sqlite3.connect(str(p), timeout=2.0)
            try:
                res = con.execute(f"PRAGMA wal_checkpoint({self.checkpoint_mode})").fetchone()
                busy = bool(res[0]) if res else False
                log_pages = int(res[1]) if res else 0
                ckpt_pages = int(res[2]) if res else 0
            finally:
                con.close()

            wal_after = wal_p.stat().st_size if wal_p.is_file() else 0
            return CheckpointReport(
                db_path=str(p),
                wal_size_before=wal_before,
                wal_size_after=wal_after,
                busy=busy,
                log_pages=log_pages,
                checkpointed_pages=ckpt_pages,
                status="checkpointed" if not busy else "busy",
            )
        except Exception as exc:
            logger.debug("Checkpoint failed on %s: %s", p, exc)
            return CheckpointReport(
                db_path=str(p),
                wal_size_before=wal_before,
                wal_size_after=wal_before,
                busy=True,
                log_pages=0,
                checkpointed_pages=0,
                status=f"error: {exc}",
            )

    def scan_and_checkpoint_all(self) -> List[CheckpointReport]:
        """Scan target directory and checkpoint all active *.sqlite3 and *.db databases."""
        if not self.target_dir.is_dir():
            return []

        reports: List[CheckpointReport] = []
        candidates = list(self.target_dir.glob("*.sqlite3")) + list(self.target_dir.glob("*.db"))
        for cand in candidates:
            reports.append(self.checkpoint_database(cand))
        return reports

    def start_daemon(self, interval_seconds: float = 60.0) -> None:
        """Start background monitoring thread."""
        self._stop_event.clear()

        def _loop():
            while not self._stop_event.is_set():
                self.scan_and_checkpoint_all()
                self._stop_event.wait(interval_seconds)

        self._thread = threading.Thread(target=_loop, name="WALCheckpointerDaemon", daemon=True)
        self._thread.start()

    def stop_daemon(self) -> None:
        """Signal and join background thread."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
