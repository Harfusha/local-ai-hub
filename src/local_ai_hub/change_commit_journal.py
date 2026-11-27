"""Durable local commit intent log; inspection never retries a mutation."""
from __future__ import annotations

import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from .process_utils import clean_git_env, run_hidden

_ID = re.compile(r"[0-9a-f]{32}")
_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")


class CommitJournal:
    def __init__(self, state_dir: Path):
        self.path = state_dir / "git-commit-journal.sqlite"
        state_dir.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise ValueError("Redirecting commit journal is not supported")
        with closing(self._connect()) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS git_commit_intents_v1 (
                id TEXT PRIMARY KEY, root TEXT NOT NULL, branch TEXT NOT NULL,
                parent TEXT NOT NULL, tree TEXT NOT NULL, candidate TEXT NOT NULL,
                state TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL
            )""")
            db.commit()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5.0)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        return db

    def prepare(self, *, operation_id: str, root: str, branch: str, parent: str, tree: str, candidate: str) -> None:
        if not _ID.fullmatch(operation_id) or not all(_OID.fullmatch(v) for v in (parent, tree, candidate)):
            raise ValueError("Invalid commit journal identity")
        now = time.time()
        with closing(self._connect()) as db, db:
            db.execute("INSERT INTO git_commit_intents_v1 VALUES (?, ?, ?, ?, ?, ?, 'prepared', ?, ?)",
                       (operation_id, root, branch, parent, tree, candidate, now, now))

    def published(self, operation_id: str) -> None:
        with closing(self._connect()) as db, db:
            updated = db.execute("UPDATE git_commit_intents_v1 SET state='published', updated=? WHERE id=? AND state='prepared'",
                                 (time.time(), operation_id))
            if updated.rowcount != 1:
                raise ValueError("Commit journal transition rejected")

    def inspect(self, root: str, operation_id: str) -> dict[str, Any]:
        if not isinstance(operation_id, str) or not _ID.fullmatch(operation_id):
            return {"success": False, "error": "Invalid operation ID"}
        with closing(self._connect()) as db:
            row = db.execute("SELECT * FROM git_commit_intents_v1 WHERE id=? AND root=?", (operation_id, root)).fetchone()
        if row is None:
            return {"success": False, "error": "Scoped operation not found"}
        entry = dict(row)
        branch = entry["branch"]
        if not isinstance(branch, str) or not branch.startswith("refs/heads/"):
            return {"success": False, "error": "Invalid stored branch"}
        cp = run_hidden(["git", "--no-pager", "rev-parse", "--verify", "--end-of-options", branch],
                        cwd=root, capture_output=True, check=False, timeout=10,
                        max_output_bytes=4096, env=clean_git_env(extra_env={"GIT_OPTIONAL_LOCKS":"0",
                        "GIT_NO_REPLACE_OBJECTS":"1", "GIT_NO_LAZY_FETCH":"1"}))
        observed = cp.stdout.strip().decode("ascii", errors="replace") if cp.returncode == 0 else ""
        if not _OID.fullmatch(observed):
            status = "branch_unavailable"
        elif observed == entry["candidate"]:
            status = "candidate_is_branch_tip"
        elif observed == entry["parent"]:
            status = "parent_is_branch_tip"
        else:
            status = "branch_moved"
        return {"success": True, **entry, "observed_branch_tip": observed,
                "recovery_status": status, "retry_authorized": False,
                "index_lock_present": (Path(root) / ".git" / "index.lock").exists()}
